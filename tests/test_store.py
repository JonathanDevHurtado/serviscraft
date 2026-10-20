"""Pruebas del almacen de servidores y de la asignacion de puertos."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from serviscraft.core.errors import ServerNotFoundError, ValidationError
from serviscraft.core.models import ServerType
from serviscraft.core.store import ServerStore

from .conftest import make_spec


def test_guardar_y_leer(store: ServerStore) -> None:
    spec = make_spec()
    store.prepare_dirs(spec.id)
    store.save(spec)
    assert store.exists(spec.id)
    assert store.load(spec.id).to_dict() == spec.to_dict()


def test_meta_queda_en_el_servidor(store: ServerStore) -> None:
    spec = make_spec()
    store.prepare_dirs(spec.id)
    store.save(spec)
    assert store.meta_file(spec.id).is_file()
    assert store.data_dir(spec.id).is_dir()
    assert store.backups_dir(spec.id).is_dir()


def test_meta_es_privado(store: ServerStore) -> None:
    """``meta.json`` guarda la contrasena de RCON: solo el usuario puede leerlo."""
    spec = make_spec()
    store.prepare_dirs(spec.id)
    store.save(spec)
    modo = stat.S_IMODE(store.meta_file(spec.id).stat().st_mode)
    assert modo == 0o600


def test_listado(store: ServerStore) -> None:
    for i in range(3):
        spec = make_spec(id=f"servidor-00000{i}", name=f"Servidor {i}", port=25600 + i)
        store.prepare_dirs(spec.id)
        store.save(spec)
    assert store.list_ids() == ["servidor-000000", "servidor-000001", "servidor-000002"]
    assert len(store.load_all()) == 3


def test_listado_ignora_carpetas_sin_meta(store: ServerStore, tmp_path: Path) -> None:
    (store.root / "servidor-viejo1" / "data").mkdir(parents=True)
    assert store.load_all() == []


def test_leer_inexistente(store: ServerStore) -> None:
    with pytest.raises(ServerNotFoundError):
        store.load("no-existe-123")


def test_leer_meta_corrupta(store: ServerStore) -> None:
    spec = make_spec()
    store.prepare_dirs(spec.id)
    store.save(spec)
    store.meta_file(spec.id).write_text("{ esto no es json", encoding="utf-8")
    with pytest.raises(ServerNotFoundError):
        store.load(spec.id)


def test_rechaza_identificadores_con_ruta(store: ServerStore) -> None:
    for malo in ("../fuera", "/etc/passwd", "..", "MAYUS", ""):
        with pytest.raises(ValidationError):
            store.server_dir(malo)


def test_puertos_en_uso(store: ServerStore) -> None:
    store.prepare_dirs("servidor-000001")
    store.save(make_spec(id="servidor-000001", port=25600, rcon_port=25601))
    store.prepare_dirs("servidor-000002")
    store.save(make_spec(id="servidor-000002", port=25610, rcon_port=25611))
    assert store.used_ports() == {25600, 25601, 25610, 25611}
    assert store.used_ports(exclude="servidor-000001") == {25610, 25611}


def test_asignar_puerto_libre(store: ServerStore) -> None:
    store.prepare_dirs("servidor-000001")
    store.save(make_spec(id="servidor-000001", port=25565, rcon_port=25575))
    assert store.allocate_port(25565) == 25566
    assert store.allocate_rcon_port(25565) == 26565


def test_asignar_puerto_respeta_los_limites(store: ServerStore) -> None:
    assert store.allocate_port(65535) == 65535
    # Un puerto fuera de rango vuelve al valor por defecto en lugar de fallar.
    assert store.allocate_port(80) == 25565
    # Y uno reservado se salta.
    store.prepare_dirs("servidor-000002")
    store.save(make_spec(id="servidor-000002", port=25600))
    assert store.allocate_port(25600) == 25601


def test_delete_sin_datos(store: ServerStore) -> None:
    spec = make_spec()
    store.prepare_dirs(spec.id)
    store.save(spec)
    store.delete(spec.id, remove_data=False)
    assert not store.meta_file(spec.id).exists()
    assert store.data_dir(spec.id).is_dir()


def test_delete_con_datos(store: ServerStore) -> None:
    spec = make_spec()
    store.prepare_dirs(spec.id)
    store.save(spec)
    (store.data_dir(spec.id) / "mundo").mkdir()
    store.delete(spec.id, remove_data=True)
    assert not store.server_dir(spec.id).exists()


def test_identificador_aleatorio_unico() -> None:
    identificadores = {make_spec(id=f"servidor-abc{i:03d}").id for i in range(50)}
    assert len(identificadores) == 50


def test_configuracion_por_defecto() -> None:
    spec = make_spec(type=ServerType.FORGE, memory_mb=4096, version="1.20.1")
    assert json.loads(json.dumps(spec.to_dict()))["type"] == "FORGE"


def test_una_carpeta_con_nombre_invalido_no_tumba_el_listado(store: ServerStore) -> None:
    """Una copia manual de la carpeta de un servidor (con espacios) se ignora."""
    spec = make_spec()
    store.prepare_dirs(spec.id)
    store.save(spec)
    copia = store.root / "Copia de prueba"
    copia.mkdir()
    (copia / "meta.json").write_text("{}", encoding="utf-8")

    cargados = store.load_all()
    assert [s.id for s in cargados] == [spec.id]
