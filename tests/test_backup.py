"""Pruebas de las copias de seguridad (sin Podman)."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from serviscraft.core.backup import BackupManager
from serviscraft.core.errors import BackupError, ValidationError
from serviscraft.core.models import ServerSpec
from serviscraft.core.store import ServerStore
from tests.conftest import make_spec


@pytest.fixture
def backups(store: ServerStore) -> BackupManager:
    return BackupManager(store)


def test_crear_y_listar(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec
) -> None:
    info = backups.create_backup(populated_server.id, label="antes-de-tocar", origin="manual")
    assert info.filename.endswith(".tar.gz")
    assert info.label == "antes-de-tocar"
    assert info.size_bytes > 0
    assert Path(info.path).is_file()
    # El fichero de metadatos acompana a la copia.
    assert Path(str(info.path) + ".json").is_file()

    listado = backups.list_backups(populated_server.id)
    assert len(listado) == 1
    assert listado[0].filename == info.filename
    assert listado[0].display_name == "antes-de-tocar"
    assert listado[0].origin == "manual"


def test_la_copia_contiene_los_datos(
    backups: BackupManager, populated_server: ServerSpec
) -> None:
    info = backups.create_backup(populated_server.id)
    with tarfile.open(info.path, "r:gz") as archive:
        nombres = archive.getnames()
    assert "world/level.dat" in nombres
    assert "world/region/r.0.0.mca" in nombres
    assert "plugins/ejemplo.jar" in nombres
    assert "server.properties" in nombres


def test_etiqueta_se_limpia(backups: BackupManager, populated_server: ServerSpec) -> None:
    info = backups.create_backup(populated_server.id, label="../../etc/passwd")
    assert ".." not in info.filename
    assert "/" not in info.filename
    assert info.filename.startswith("backup-")


def test_restaurar_revierte_los_cambios(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec
) -> None:
    data = store.data_dir(populated_server.id)
    info = backups.create_backup(populated_server.id, label="estado-bueno")

    # El jugador rompe cosas: modifica el mundo y anade basura.
    (data / "world" / "level.dat").write_bytes(b"destruido")
    (data / "basura").mkdir()
    (data / "basura" / "restos.txt").write_text("no deberia seguir aqui", encoding="utf-8")

    backups.restore_backup(populated_server.id, info.path)

    assert (data / "world" / "level.dat").read_bytes() == b"nivel"
    assert not (data / "basura").exists()
    # El directorio provisional se limpia.
    assert not list(store.backups_dir(populated_server.id).glob("serviscraft-restore-*"))


def test_restaurar_sin_copia_valida(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec, tmp_path: Path
) -> None:
    # Una copia que no existe dentro de la carpeta de copias.
    with pytest.raises(BackupError):
        backups.restore_backup(populated_server.id, store.backups_dir(populated_server.id) / "no-existe.tar.gz")
    # Y un fichero de cualquier otra ubicacion.
    with pytest.raises(ValidationError):
        backups.restore_backup(populated_server.id, tmp_path / "no-existe.tar.gz")


def test_no_se_puede_restaurar_una_copia_de_otro_servidor(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec, tmp_path: Path
) -> None:
    dentro = tmp_path / "level.dat"
    dentro.write_bytes(b"mundo")
    ajena = tmp_path / "ajena.tar.gz"
    with tarfile.open(ajena, "w:gz") as archive:
        archive.add(dentro, arcname="world/level.dat")
    with pytest.raises(ValidationError):
        backups.restore_backup(populated_server.id, ajena)


def test_importar_copia(
    backups: BackupManager, populated_server: ServerSpec, tmp_path: Path
) -> None:
    externa = tmp_path / "copia-externa.tar.gz"
    with tarfile.open(externa, "w:gz") as archive:
        fichero = tmp_path / "level.dat"
        fichero.write_bytes(b"mundo importado")
        archive.add(fichero, arcname="world/level.dat")

    info = backups.import_backup(populated_server.id, externa)
    assert info.origin == "importada"
    assert Path(info.path).is_file()

    # Importar dos veces no sobrescribe: se renombra.
    segunda = backups.import_backup(populated_server.id, externa)
    assert segunda.filename != info.filename

    assert len(backups.list_backups(populated_server.id)) == 2


def test_importar_rechaza_lo_que_no_es_tar(
    backups: BackupManager, populated_server: ServerSpec, tmp_path: Path
) -> None:
    falso = tmp_path / "falso.tar.gz"
    falso.write_text("no soy un tar", encoding="utf-8")
    with pytest.raises(BackupError):
        backups.import_backup(populated_server.id, falso)
    with pytest.raises(BackupError):
        backups.import_backup(populated_server.id, tmp_path / "no-existe.tar.gz")


def test_importar_deja_el_fichero_dentro_de_las_copias(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec, tmp_path: Path
) -> None:
    externa = tmp_path / "externa.tar.gz"
    with tarfile.open(externa, "w:gz") as archive:
        fichero = tmp_path / "level.dat"
        fichero.write_bytes(b"x")
        archive.add(fichero, arcname="world/level.dat")

    info = backups.import_backup(populated_server.id, externa)
    # La copia siempre se guarda dentro de la carpeta de copias del servidor,
    # aunque el usuario haya elegido un fichero de cualquier otra ubicacion.
    assert Path(info.path).parent == store.backups_dir(populated_server.id)
    assert Path(info.path).is_file()


def test_restaurar_copia_con_rutas_maliciosas(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec, tmp_path: Path
) -> None:
    """Una copia con ``..`` no puede escribir fuera de la carpeta del servidor."""
    maliciosa = store.backups_dir(populated_server.id) / "maliciosa.tar.gz"
    with tarfile.open(maliciosa, "w:gz") as archive:
        fichero = tmp_path / "malo.txt"
        fichero.write_text("fuera", encoding="utf-8")
        info = archive.gettarinfo(str(fichero), arcname="../fuera.txt")
        with fichero.open("rb") as handle:
            archive.addfile(info, handle)

    with pytest.raises(BackupError):
        backups.restore_backup(populated_server.id, maliciosa)
    assert not (store.root / "fuera.txt").exists()
    # El contenido original sigue intacto.
    assert (store.data_dir(populated_server.id) / "server.properties").is_file()


def test_borrar_copia(backups: BackupManager, populated_server: ServerSpec) -> None:
    info = backups.create_backup(populated_server.id)
    backups.delete_backup(populated_server.id, info.path)
    assert backups.list_backups(populated_server.id) == []
    assert not Path(info.path).exists()
    with pytest.raises(BackupError):
        backups.delete_backup(populated_server.id, info.path)


def test_borrar_copia_de_otro_servidor(
    backups: BackupManager, populated_server: ServerSpec, tmp_path: Path
) -> None:
    with pytest.raises(ValidationError):
        backups.delete_backup(populated_server.id, tmp_path / "otra.tar.gz")


def test_limpiar_conserva_las_mas_recientes(
    backups: BackupManager, populated_server: ServerSpec
) -> None:
    for i in range(5):
        backups.create_backup(populated_server.id, label=f"copia{i}")
    assert len(backups.list_backups(populated_server.id)) == 5
    borradas = backups.prune(populated_server.id, keep=2)
    assert borradas == 3
    assert len(backups.list_backups(populated_server.id)) == 2
    # Y no borra de mas.
    assert backups.prune(populated_server.id, keep=10) == 0


def test_limpiar_con_keep_negativo(backups: BackupManager, populated_server: ServerSpec) -> None:
    with pytest.raises(ValidationError):
        backups.prune(populated_server.id, keep=-1)


def test_dos_copias_seguidas_no_se_pisan(
    backups: BackupManager, populated_server: ServerSpec
) -> None:
    """El nombre lleva la fecha al segundo: dos copias seguidas no deben pisarse."""
    primera = backups.create_backup(populated_server.id)
    segunda = backups.create_backup(populated_server.id)

    assert primera.path != segunda.path
    assert Path(primera.path).is_file()
    assert Path(segunda.path).is_file()
    assert len(backups.list_backups(populated_server.id)) == 2


def test_dos_copias_a_la_vez_acaban_las_dos_bien(
    backups: BackupManager, populated_server: ServerSpec
) -> None:
    """La copia programada y una manual pueden coincidir: se hacen una tras otra."""
    from threading import Barrier, Thread

    salida: list = []
    fallos: list = []
    empiezan = Barrier(2)

    def copiar(origin: str) -> None:
        empiezan.wait(5)
        try:
            salida.append(backups.create_backup(populated_server.id, origin=origin))
        except BaseException as exc:  # noqa: BLE001 - se revisa en la prueba
            fallos.append(exc)

    hilos = [
        Thread(target=copiar, args=("programada",)),
        Thread(target=copiar, args=("manual",)),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)

    assert not fallos, fallos
    assert len({info.path for info in salida}) == 2
    # Las dos copias son validas y no queda ningun fichero a medias.
    for info in salida:
        with tarfile.open(info.path, "r:gz") as archive:
            assert "world/level.dat" in archive.getnames()
    assert len(backups.list_backups(populated_server.id)) == 2
    assert not list(backups.backups_dir(populated_server.id).glob("*.part"))


def test_la_retencion_no_borra_la_copia_recien_creada(
    backups: BackupManager, populated_server: ServerSpec
) -> None:
    """Varias copias caen en el mismo segundo: el orden no puede ser alfabetico.

    Con etiquetas elegidas para que el orden alfabetico sea el inverso al de
    creacion, la limpieza debe conservar las **ultimas creadas**, no las que
    primero aparecen por nombre.
    """
    from serviscraft.core.backup import ORIGENES_AUTOMATICOS

    copias = [
        backups.create_backup(populated_server.id, label=etiqueta, origin="programada")
        for etiqueta in ("zzz", "aaa", "mmm", "bbb")
    ]
    ultimas = {copias[2].path, copias[3].path}

    borradas = backups.prune(populated_server.id, keep=2, origins=ORIGENES_AUTOMATICOS)

    assert borradas == 2
    quedan = {info.path for info in backups.list_backups(populated_server.id)}
    assert quedan == ultimas


def test_la_retencion_por_origen_respeta_las_manuales(
    backups: BackupManager, populated_server: ServerSpec
) -> None:
    manual = backups.create_backup(populated_server.id, origin="manual")
    for _ in range(3):
        backups.create_backup(populated_server.id, origin="programada")

    borradas = backups.prune(populated_server.id, keep=1, origins=("programada",))

    assert borradas == 2
    rutas = [info.path for info in backups.list_backups(populated_server.id)]
    assert manual.path in rutas
    assert len(rutas) == 2


def test_copia_progreso(backups: BackupManager, populated_server: ServerSpec) -> None:
    pasos: list[tuple[int, int]] = []
    backups.create_backup(
        populated_server.id,
        on_progress=lambda hecho, total: pasos.append((hecho, total)),
    )
    assert pasos, "se esperaba al menos un aviso de progreso"
    hecho, total = pasos[-1]
    assert hecho == total > 0


def test_copia_cancelada_no_deja_restos(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec
) -> None:
    with pytest.raises(BackupError):
        backups.create_backup(populated_server.id, should_cancel=lambda: True)
    assert list(store.backups_dir(populated_server.id).glob("*")) == []


def test_sin_datos_no_hay_copia(backups: BackupManager, store: ServerStore, spec: ServerSpec) -> None:
    store.delete(spec.id, remove_data=True)
    with pytest.raises(BackupError):
        backups.create_backup(spec.id)


def test_renombrar_cambia_la_etiqueta_sin_tocar_el_archivo(
    backups: BackupManager, populated_server: ServerSpec
) -> None:
    from serviscraft.core.backup import MAX_LABEL_LENGTH

    info = backups.create_backup(populated_server.id, label="original")
    ruta = Path(info.path)
    tamano = ruta.stat().st_size

    actualizada = backups.rename_backup(populated_server.id, info.path, "  antes de los mods  ")
    assert actualizada.label == "antes de los mods"
    assert actualizada.display_name == "antes de los mods"
    assert actualizada.filename == info.filename
    assert ruta.is_file()
    assert ruta.stat().st_size == tamano
    # Y el cambio se ve al volver a listar.
    assert backups.list_backups(populated_server.id)[0].label == "antes de los mods"

    vacia = backups.rename_backup(populated_server.id, info.path, "   ")
    assert vacia.label == ""
    assert vacia.display_name == info.filename

    with pytest.raises(ValidationError):
        backups.rename_backup(populated_server.id, info.path, "x" * (MAX_LABEL_LENGTH + 1))


def test_no_se_renombra_una_copia_de_otro_servidor(
    backups: BackupManager, store: ServerStore, populated_server: ServerSpec
) -> None:
    info = backups.create_backup(populated_server.id)
    otro = make_spec(id="otro-servidor", name="Otro", port=25566, rcon_port=25576)
    store.prepare_dirs(otro.id)
    store.save(otro)
    with pytest.raises(ValidationError):
        backups.rename_backup(otro.id, info.path, "ajena")
