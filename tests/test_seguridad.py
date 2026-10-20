"""Pruebas de endurecimiento (auditoria de seguridad de la version 0.6.0).

Cubren los puntos que mas importan en este programa: que un enlace simbolico
plantado en la carpeta ``data/`` (que escribe el propio servidor y sus plugins)
no permita leer ni escribir ficheros de fuera, que las descargas no puedan
apuntar a servicios locales, que las respuestas de la consola tengan tope, que
no se filtren contrasenas en el registro y que el contenedor se cree sin
privilegios. Todo son pruebas de unidad: no se toca la red ni el motor real.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from serviscraft.core import icons, logging_setup, paths
from serviscraft.core.errors import BackupError, RconError, ValidationError
from serviscraft.core.models import ServerType
from serviscraft.core.podman import PodmanClient
from serviscraft.core.properties import ServerProperties
from serviscraft.core.store import ServerStore
from serviscraft.core.validation import (
    atomic_write_text,
    ensure_within,
    read_text_inside,
    reject_symlink,
)

from .conftest import make_spec


# --------------------------------------------------------------------- symlinks
class TestEnlacesSimbolicos:
    """La carpeta del servidor es entrada no confiable: nunca se siguen enlaces."""

    def test_reject_symlink_avisa_con_un_enlace(self, tmp_path: Path) -> None:
        enlace = tmp_path / "enlace"
        os.symlink("/etc/passwd", enlace)
        with pytest.raises(ValidationError):
            reject_symlink(enlace)

    def test_reject_symlink_deja_pasar_un_fichero_normal(self, tmp_path: Path) -> None:
        fichero = tmp_path / "normal.txt"
        fichero.write_text("hola", encoding="utf-8")
        assert reject_symlink(fichero) == fichero

    def test_no_se_lee_a_traves_de_un_enlace(self, tmp_path: Path) -> None:
        secreto = tmp_path / "secreto.txt"
        secreto.write_text("no deberias verme", encoding="utf-8")
        root = tmp_path / "data"
        root.mkdir()
        os.symlink(secreto, root / "server.properties")
        with pytest.raises(ValidationError):
            read_text_inside(root / "server.properties", root)

    def test_escribir_no_sigue_el_enlace(self, tmp_path: Path) -> None:
        victima = tmp_path / "victima.txt"
        victima.write_text("original", encoding="utf-8")
        enlace = tmp_path / "destino.txt"
        os.symlink(victima, enlace)
        # Escribir un enlace se rechaza: jamas se toca el fichero apuntado.
        with pytest.raises(ValidationError):
            atomic_write_text(enlace, "sobrescrito")
        assert victima.read_text(encoding="utf-8") == "original"

    def test_escritura_atomica_sustituye_a_un_enlace_roto(self, tmp_path: Path) -> None:
        enlace = tmp_path / "roto.txt"
        os.symlink(tmp_path / "no-existe.txt", enlace)
        with pytest.raises(ValidationError):
            atomic_write_text(enlace, "datos")
        assert not (tmp_path / "no-existe.txt").exists()

    def test_escritura_atomica_no_deja_temporales(self, tmp_path: Path) -> None:
        destino = tmp_path / "f.txt"
        atomic_write_text(destino, "contenido")
        assert destino.read_text(encoding="utf-8") == "contenido"
        sobrantes = [p.name for p in tmp_path.iterdir() if p.name != "home"]
        assert sobrantes == ["f.txt"]

    def test_ensure_within_sigue_rechazando_la_travesia(self, tmp_path: Path) -> None:
        root = tmp_path / "data"
        root.mkdir()
        with pytest.raises(ValidationError):
            ensure_within(Path("../fuera.txt"), root)


class TestPropiedadesSeguras:
    def test_load_con_root_rechaza_el_enlace(self, populated_server, store: ServerStore) -> None:
        data = store.data_dir(populated_server.id)
        fuera = data.parent / "fuera.properties"
        fuera.write_text("motd=Robado\n", encoding="utf-8")
        (data / "server.properties").unlink()
        os.symlink(fuera, data / "server.properties")
        with pytest.raises(ValidationError):
            ServerProperties.load(data / "server.properties", root=data)

    def test_save_no_sobrescribe_a_traves_de_un_enlace(self, store: ServerStore) -> None:
        from serviscraft.core.properties import PropertiesError

        data = store.data_dir("srv-seguro01")
        data.mkdir(parents=True, exist_ok=True)
        props = ServerProperties(path=data / "server.properties", entries=[])
        # El fichero real se sustituye por un enlace despues de tener las
        # propiedades cargadas: guardar no debe escribir en el destino.
        victima = data.parent / "victima.properties"
        victima.write_text("motd=Original\n", encoding="utf-8")
        os.symlink(victima, data / "server.properties")
        props.set("motd", "Nuevo")
        with pytest.raises(PropertiesError):
            props.save()
        assert "Original" in victima.read_text(encoding="utf-8")


class TestManifiestoDeMods:
    def test_el_manifiesto_no_escribe_fuera(self, store: ServerStore, spec) -> None:
        from serviscraft.core import mods as mods_mod

        data = store.data_dir(spec.id)
        victima = data.parent / "victima.json"
        victima.write_text('{"yo": "original"}', encoding="utf-8")
        enlace = data / mods_mod.MANIFEST_NAME
        if enlace.exists():
            enlace.unlink()
        os.symlink(victima, enlace)
        inventario = mods_mod.ModsInventory(store, spec.id, folder="plugins")
        # No debe propagar la excepcion (se registra y se sigue) pero tampoco
        # debe tocar el fichero apuntado por el enlace.
        inventario._save_manifest({"algo.jar"})
        assert json.loads(victima.read_text(encoding="utf-8")) == {"yo": "original"}


# --------------------------------------------------------------------- descargas
class TestUrlsDeDescarga:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/algo.jar",
            "http://127.0.0.1:8080/algo.jar",
            "http://[::1]/algo.jar",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "ftp://ejemplo.com/algo.jar",
            "https://usuario:clave@ejemplo.com/algo.jar",
            "",
        ],
    )
    def test_se_rechazan_las_direcciones_peligrosas(self, url: str) -> None:
        from serviscraft.core.server_files import ServerFiles

        with pytest.raises(ValidationError):
            ServerFiles.validate_download_url(url)

    def test_se_acepta_una_direccion_publica(self) -> None:
        from serviscraft.core.server_files import ServerFiles

        url = "https://cdn.example.com/mods/algo.jar"
        assert ServerFiles.validate_download_url(url) == url

    def test_los_iconos_rechazan_destinos_locales(self) -> None:
        for url in (
            "http://localhost/icono.png",
            "http://127.0.0.1/icono.png",
            "http://10.0.0.5/icono.png",
            "http://192.168.1.7/icono.png",
            "http://cuaderno.local/icono.png",
            "file:///etc/passwd",
            "",
        ):
            assert icons.download(url) is None, url

    def test_los_iconos_no_siguen_una_redireccion_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Respuesta:
            headers = {"Content-Length": "8"}

            def read(self, limite: int = -1) -> bytes:
                return b"\x89PNG\r\n\x1a\n"

            def geturl(self) -> str:
                return "http://127.0.0.1:8080/icono.png"

            def __enter__(self):
                return self

            def __exit__(self, *args) -> None:
                return None

        monkeypatch.setattr(
            icons.urllib.request, "urlopen", lambda *a, **k: Respuesta()
        )
        assert icons.download("https://cdn.modrinth.com/data/abc/icono.png") is None

    def test_la_redireccion_a_una_maquina_local_se_rechaza(self) -> None:
        from serviscraft.core.server_files import _SafeRedirectHandler

        manejador = _SafeRedirectHandler()
        for destino in (
            "http://127.0.0.1:8080/algo.jar",
            "http://localhost/algo.jar",
            "file:///etc/passwd",
        ):
            with pytest.raises(ValidationError):
                manejador.redirect_request(None, None, 302, "", {}, destino)

    def test_una_redireccion_publica_se_acepta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from serviscraft.core import server_files

        manejador = server_files._SafeRedirectHandler()
        visto: list[str] = []
        original = server_files.urllib.request.HTTPRedirectHandler.redirect_request

        def falso(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            visto.append(newurl)
            return "peticion"

        monkeypatch.setattr(
            server_files.urllib.request.HTTPRedirectHandler, "redirect_request", falso
        )
        try:
            resultado = manejador.redirect_request(
                None, None, 302, "", {}, "https://cdn.example.com/algo.jar"
            )
        finally:
            monkeypatch.setattr(
                server_files.urllib.request.HTTPRedirectHandler,
                "redirect_request",
                original,
            )
        assert resultado == "peticion"
        assert visto == ["https://cdn.example.com/algo.jar"]


class TestContenedorSinPrivilegios:
    def test_los_argumentos_quitan_privilegios(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        capturado: list[list[str]] = []
        cliente = PodmanClient()

        def falso(args, **kwargs):  # noqa: ANN001
            capturado.append([str(a) for a in args])
            return subprocess.CompletedProcess(
                args=[str(a) for a in args], returncode=0, stdout="abc123\n", stderr=""
            )

        monkeypatch.setattr(cliente, "run", falso)
        cliente.create(
            name="serviscraft-prueba",
            image="docker.io/itzg/minecraft-server",
            env={"EULA": "TRUE"},
            published_ports=(("127.0.0.1", 25565, 25565),),
            volumes=(("/tmp/datos", "/data", "Z"),),
            labels={},
        )
        argumentos = capturado[0]
        assert "--security-opt=no-new-privileges" in argumentos
        assert "--cap-drop=ALL" in argumentos
        assert any(a.startswith("--pids-limit=") for a in argumentos)
        assert "--privileged" not in argumentos


# ------------------------------------------------------------------------- rcon
class TestConsolaConTope:
    def _cliente(self, rcon, respuesta: bytes | str):  # noqa: ANN001, ANN202
        class Socket:
            def settimeout(self, valor: float) -> None:
                pass

            def sendall(self, datos: bytes) -> None:
                pass

        cliente = rcon.RconClient("127.0.0.1", 25575, "contrasena-larga")
        cliente._socket = Socket()  # type: ignore[assignment]
        cliente._id = 7

        def mentira() -> tuple[int, int, str]:
            return 8, 0, respuesta if isinstance(respuesta, str) else respuesta.decode()

        return cliente, mentira

    def test_una_respuesta_gigante_se_corta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from serviscraft.core import rcon

        cliente, mentira = self._cliente(rcon, "x" * (2 * 1024 * 1024))
        monkeypatch.setattr(cliente, "_receive", mentira)
        with pytest.raises(RconError):
            cliente.command("list")

    def test_una_lluvia_de_paquetes_ajenos_se_corta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from serviscraft.core import rcon

        # Identificador que no es el de la peticion: antes esto giraba sin fin.
        cliente, mentira = self._cliente(rcon, "ruido")
        monkeypatch.setattr(cliente, "_receive", mentira)
        with pytest.raises(RconError):
            cliente.command("list")


# --------------------------------------------------------------------- registro
class TestRegistroSinSecretos:
    def test_se_depuran_contrasenas_y_tokens(self) -> None:
        texto = "rcon.password=SuperSecreta123 token=abc123def456"
        limpio = logging_setup.redact(texto)
        assert "SuperSecreta123" not in limpio
        assert "abc123def456" not in limpio
        assert limpio.count("***") == 2

    def test_el_formateador_limpia_la_traza(self) -> None:
        registro = logging.LogRecord(
            name="prueba",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="fallo con password=%s",
            args=("MiClaveSecreta",),
            exc_info=None,
        )
        formateador = logging_setup._RedactingFormatter("%(message)s")
        salida = formateador.format(registro)
        assert "MiClaveSecreta" not in salida
        assert "***" in salida

    def test_las_carpetas_privadas_quedan_en_0700(self) -> None:
        paths.ensure_base_dirs()
        for carpeta in (paths.data_root(), paths.servers_dir(), paths.logs_dir()):
            assert (carpeta.stat().st_mode & 0o777) == 0o700


# ------------------------------------------------------------------ entorno
class TestVariablesReservadas:
    def test_no_se_puede_sobrescribir_lo_que_gestiona_la_app(self) -> None:
        servidor = make_spec(
            extra_env={
                "TYPE": "VANILLA",
                "RCON_PASSWORD": "otra",
                "ENABLE_RCON": "false",
                "MODRINTH_PROJECTS": "sodium",
            }
        )
        entorno = servidor.container_env()
        assert entorno["TYPE"] == "PAPER" or entorno["TYPE"] == servidor.type.value
        assert entorno["RCON_PASSWORD"] == servidor.rcon_password
        assert entorno["ENABLE_RCON"] == "true"
        # Las variables legitimas de un modpack si pasan.
        assert entorno["MODRINTH_PROJECTS"] == "sodium"

    def test_las_claves_raras_se_descartan(self) -> None:
        servidor = make_spec(extra_env={"--privileged": "1", "bien_ok": "x", "BIEN_2": "y"})
        limpio = servidor.safe_extra_env
        assert "--privileged" not in limpio
        assert "bien_ok" not in limpio  # en minusculas no es una variable valida
        assert limpio["BIEN_2"] == "y"


# --------------------------------------------------------------------- backups
def _copia_con(nombre_interno: str) -> "Path":
    """Crea un ``.tar.gz`` con un unico miembro de nombre arbitrario."""
    import io
    import tarfile
    import tempfile

    ruta = Path(tempfile.mkdtemp(prefix="serviscraft-copia-")) / "copia.tar.gz"
    datos = b"contenido"
    with tarfile.open(ruta, "w:gz") as archivo:
        info = tarfile.TarInfo(name=nombre_interno)
        info.size = len(datos)
        archivo.addfile(info, io.BytesIO(datos))
    return ruta


class TestCopiasSeguras:
    def test_no_se_importa_a_traves_de_un_enlace(
        self, store: ServerStore, populated_server
    ) -> None:
        from serviscraft.core.backup import BackupManager

        origen = _copia_con("dentro/mundo/level.dat")
        gestor = BackupManager(store)
        backups = store.backups_dir(populated_server.id)
        backups.mkdir(parents=True, exist_ok=True)
        victima = backups.parent / "victima.txt"
        victima.write_text("original", encoding="utf-8")
        enlace = backups / origen.name
        os.symlink(victima, enlace)
        with pytest.raises((BackupError, ValidationError)):
            gestor.import_backup(populated_server.id, origen)
        assert victima.read_text(encoding="utf-8") == "original"

    def test_una_copia_con_rutas_absolutas_se_rechaza(
        self, store: ServerStore, populated_server
    ) -> None:
        from serviscraft.core.backup import BackupManager

        gestor = BackupManager(store)
        copia = store.backups_dir(populated_server.id) / "maliciosa.tar.gz"
        copia.parent.mkdir(parents=True, exist_ok=True)
        copia.write_bytes(_copia_con("../../etc/passwd").read_bytes())
        with pytest.raises(BackupError):
            gestor.restore_backup(populated_server.id, copia)
        # El contenido original sigue intacto (reversion correcta).
        assert (store.data_dir(populated_server.id) / "world" / "level.dat").is_file()


# --------------------------------------------------------------------- varios
class TestVarios:
    def test_el_servidor_cargado_se_valida(self, store: ServerStore, spec) -> None:
        cargado = store.load(spec.id)
        assert cargado.type is ServerType.PAPER
        assert cargado.rcon_password == spec.rcon_password
        assert cargado.extra_env == spec.extra_env

    def test_una_definicion_fuera_de_rango_no_desaparece(self, store: ServerStore, spec) -> None:
        meta = store.meta_file(spec.id)
        datos = json.loads(meta.read_text(encoding="utf-8"))
        datos["memory_mb"] = 1  # fuera de rango: define una version antigua o editada
        meta.write_text(json.dumps(datos), encoding="utf-8")
        cargado = store.load(spec.id)
        assert cargado.id == spec.id
        assert cargado.name == spec.name

    def test_las_listas_ignoran_los_enlaces(
        self, store: ServerStore, populated_server
    ) -> None:
        from serviscraft.core.server_files import ServerFiles

        data = store.data_dir(populated_server.id)
        os.symlink("/etc/passwd", data / "trampa.txt")
        entradas = ServerFiles(store, populated_server.id).list_entries()
        nombres = {entrada.name for entrada in entradas}
        assert "trampa.txt" not in nombres
