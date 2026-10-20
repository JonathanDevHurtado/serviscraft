"""Rutas y constantes globales.

Todas las rutas siguen la especificacion XDG para integrarse de forma limpia en
un escritorio KDE. Se puede forzar la raiz de datos con la variable de entorno
``SERVISCRAFT_HOME`` (util para pruebas y para el AppImage en modo portatil).
"""

from __future__ import annotations

import os
from pathlib import Path

APP_ID = "serviscraft"
APP_DISPLAY_NAME = "Serviscraft"
APP_SUMMARY = "Gestor grafico de servidores de Minecraft sobre Podman rootless"
APP_VERSION = "0.8.0"

#: Prefijo de los nombres de contenedor que gestiona la aplicacion. Solo se
#: tocan contenedores con este prefijo, nunca contenedores ajenos del usuario.
CONTAINER_PREFIX = "serviscraft"

DEFAULT_ENGINE = "podman"
#: Imagen OCI universal: soporta VANILLA, PAPER, FABRIC y FORGE via la variable
#: de entorno TYPE. Se descarga automaticamente la primera vez.
DEFAULT_IMAGE = "docker.io/itzg/minecraft-server"
DEFAULT_JAVA_TAG = "java21"
#: Etiquetas de Java que publica la imagen, de la mas nueva a la mas antigua.
JAVA_TAGS = ("java25", "java21", "java17", "java8")

#: Pluguins oficiales que convierten un servidor Java (Paper) en un servidor
#: compatible con Minecraft Bedrock. Los descarga la propia imagen porque
#: entiende la variable ``PLUGINS`` (ver docs de itzg/minecraft-server).
GEYSER_PLUGIN_URL = (
    "https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest/downloads/spigot"
)
FLOODGATE_PLUGIN_URL = (
    "https://download.geysermc.org/v2/projects/floodgate/versions/latest/builds/latest/downloads/spigot"
)
#: Puerto (UDP) que usa Bedrock por defecto dentro del contenedor.
CONTAINER_BEDROCK_PORT = 19132
DEFAULT_BEDROCK_PORT = 19132

DEFAULT_PORT = 25565
DEFAULT_RCON_PORT = 25575
RCON_PORT_MIN = 25575
DEFAULT_MEMORY_MB = 2048
MIN_MEMORY_MB = 512
MAX_MEMORY_MB = 32768
MIN_PORT = 1024
MAX_PORT = 65535

#: Puerto interno del contenedor (el estandar de Minecraft).
CONTAINER_GAME_PORT = 25565
CONTAINER_RCON_PORT = 25575


def _env_path(variable: str, default: str) -> Path:
    value = os.environ.get(variable)
    if value:
        return Path(value).expanduser()
    return Path(default).expanduser()


def data_root() -> Path:
    """Raiz de datos persistentes (mundos, configuracion de servidores, copias)."""
    override = os.environ.get("SERVISCRAFT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return _env_path("XDG_DATA_HOME", "~/.local/share") / APP_ID


def servers_dir() -> Path:
    return data_root() / "servers"


def server_dir(server_id: str) -> Path:
    """Carpeta de un servidor concreto."""
    if not server_id or "/" in server_id or "\\" in server_id or server_id in {".", ".."}:
        raise ValueError(f"identificador de servidor no valido: {server_id!r}")
    return servers_dir() / server_id


def server_data_dir(server_id: str) -> Path:
    """Carpeta montada como ``/data`` dentro del contenedor."""
    return server_dir(server_id) / "data"


def server_backups_dir(server_id: str) -> Path:
    return server_dir(server_id) / "backups"


def server_meta_file(server_id: str) -> Path:
    return server_dir(server_id) / "meta.json"


def logs_dir() -> Path:
    return data_root() / "logs"


def log_file() -> Path:
    return logs_dir() / f"{APP_ID}.log"


def config_dir() -> Path:
    override = os.environ.get("SERVISCRAFT_CONFIG_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return _env_path("XDG_CONFIG_HOME", "~/.config") / APP_ID


def config_file() -> Path:
    return config_dir() / "config.json"


def cache_dir() -> Path:
    return _env_path("XDG_CACHE_HOME", "~/.cache") / APP_ID


def icons_dir() -> Path:
    """Iconos propios instalados por el paquete (o los empaquetados en el codigo)."""
    bundled = Path(__file__).resolve().parent.parent / "resources" / "icons"
    if bundled.is_dir():
        return bundled
    return data_root() / "icons"


def bundled_resource(*parts: str) -> Path:
    """Ruta a un recurso empaquetado junto al codigo fuente."""
    return Path(__file__).resolve().parent.parent / "resources" / Path(*parts)


def ensure_base_dirs() -> None:
    """Crea las carpetas base necesarias. No es destructivo."""
    for path in (data_root(), servers_dir(), logs_dir(), config_dir(), cache_dir()):
        path.mkdir(parents=True, exist_ok=True)
    # Las carpetas de datos pueden contener contrasenas (RCON, tokens) y
    # registros con informacion del servidor: solo el usuario.
    for private in (data_root(), servers_dir(), logs_dir(), config_dir()):
        try:
            os.chmod(private, 0o700)
        except OSError:  # pragma: no cover - sistemas sin permisos POSIX
            pass
