"""Configuracion comun de las pruebas.

Todas las pruebas trabajan en una carpeta temporal: nunca tocan los datos
reales del usuario (``~/.local/share/serviscraft``).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# El registro se configura al importar ``serviscraft`` (``get_logger`` llama a
# ``setup_logging``). Se apunta a una carpeta temporal ANTES de importar para
# que las pruebas no escriban en el registro real del usuario.
_LOG_ROOT = Path(tempfile.mkdtemp(prefix="serviscraft-pruebas-"))
os.environ["SERVISCRAFT_HOME"] = str(_LOG_ROOT / "data")
os.environ["SERVISCRAFT_CONFIG_HOME"] = str(_LOG_ROOT / "config")
os.environ["XDG_CACHE_HOME"] = str(_LOG_ROOT / "cache")

from serviscraft.core.appconfig import AppConfig  # noqa: E402
from serviscraft.core.models import ServerSpec, ServerType  # noqa: E402
from serviscraft.core.store import ServerStore  # noqa: E402


#: Resultado de la sesión, para poder salir sin destruir QApplication.
_SESSION_STATUS: int | None = None


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Guarda el resultado antes de que Qt empiece a destruir objetos."""
    global _SESSION_STATUS
    _SESSION_STATUS = int(exitstatus)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Termina el proceso sin destruir QApplication.

    Con ``QT_QPA_PLATFORM=offscreen``, Qt 6.11 se queda girando al destruir la
    aplicación después de la sesión: el resumen ya está impreso, pero el proceso
    no termina. Se sale de forma explícita con el código calculado por pytest;
    las pruebas y sus ``finalizers`` ya se han ejecutado.
    """
    if _SESSION_STATUS is not None and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_SESSION_STATUS)


@pytest.fixture(scope="session", autouse=True)
def _limpiar_registro_de_pruebas():
    """Borra la carpeta temporal usada por el registro al terminar la sesion."""
    yield
    import shutil

    shutil.rmtree(_LOG_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aisla toda la aplicacion en una carpeta temporal."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SERVISCRAFT_HOME", str(home / "data"))
    monkeypatch.setenv("SERVISCRAFT_CONFIG_HOME", str(home / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "cache"))
    # Se quitan por si el entorno del usuario apunta a un motor remoto.
    for variable in ("CONTAINER_HOST", "DOCKER_HOST", "CONTAINER_CONNECTION"):
        monkeypatch.delenv(variable, raising=False)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    # Las pruebas no salen a internet: las texturas y las skins usan los iconos
    # dibujados (y las pruebas de descarga simulan la red).
    monkeypatch.setenv("SERVISCRAFT_OFFLINE", "1")
    return home


@pytest.fixture
def store(tmp_path: Path) -> ServerStore:
    """Almacen aislado en una carpeta temporal."""
    return ServerStore(tmp_path / "servers")


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig()


@pytest.fixture
def spec(store: ServerStore) -> ServerSpec:
    """Un servidor de ejemplo ya guardado en el almacen."""
    server = ServerSpec(
        id="prueba-abc123",
        name="Prueba",
        type=ServerType.PAPER,
        version="1.21.4",
        memory_mb=1024,
        port=25565,
        rcon_port=25575,
        rcon_password="contrasena-segura",
        image="docker.io/itzg/minecraft-server",
    ).validated()
    store.prepare_dirs(server.id)
    store.save(server)
    return server


@pytest.fixture
def populated_server(store: ServerStore, spec: ServerSpec) -> ServerSpec:
    """Un servidor con contenido realista en ``data``."""
    data = store.data_dir(spec.id)
    (data / "world").mkdir(parents=True, exist_ok=True)
    (data / "world" / "level.dat").write_bytes(b"nivel")
    (data / "world" / "region").mkdir(exist_ok=True)
    (data / "world" / "region" / "r.0.0.mca").write_bytes(b"x" * 512)
    (data / "world_nether").mkdir(exist_ok=True)
    (data / "world_nether" / "level.dat").write_bytes(b"inframundo")
    (data / "plugins").mkdir(exist_ok=True)
    (data / "plugins" / "ejemplo.jar").write_bytes(b"jar")
    (data / "server.properties").write_text("motd=Hola\nlevel-name=world\n", encoding="utf-8")
    (data / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (data / "server-icon.png").write_bytes(b"\x89PNG")
    return spec


def make_spec(**overrides) -> ServerSpec:
    """Fabrica rapida de servidores para las pruebas."""
    base = {
        "id": "servidor-test01",
        "name": "Servidor test",
        "type": ServerType.VANILLA,
        "version": "1.21.4",
        "memory_mb": 2048,
        "port": 25565,
        "rcon_port": 25575,
        "rcon_password": "contrasena-larga",
        "image": "docker.io/itzg/minecraft-server",
    }
    base.update(overrides)
    return ServerSpec(**base).validated()
