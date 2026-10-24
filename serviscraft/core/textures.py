"""Texturas ligeras de objetos y skins de jugadores, con cache en disco.

Las texturas no se empaquetan en la aplicacion (pesarian y no son nuestras): se
descargan **una sola vez** de un espejo publico de los recursos del juego y se
guardan en ``~/.cache/serviscraft/texturas``. Cada PNG ocupa uno o dos KB, asi
que un inventario entero ocupa menos que una foto.

Sin conexion no pasa nada: la ventana del inventario dibuja sus propios iconos y
la cara del jugador por defecto, y cuando la descarga termina se repinta sola.

Reglas de seguridad:

* solo ``https`` y solo contra los servidores de la lista blanca (nada de
  ``file://`` ni de direcciones que lleven a la red local);
* tamano maximo por fichero y tiempo de espera corto;
* el nombre del objeto y el del jugador se validan antes de formar la direccion;
* lo descargado tiene que ser un PNG de las medidas esperadas (16x16, 64x64...).
"""

from __future__ import annotations

import os
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .logging_setup import get_logger
from .paths import APP_VERSION, cache_dir

logger = get_logger("textures")

#: Rama del espejo de recursos de Minecraft que se usa para los objetos.
ASSETS_REF = "1.21.4"
#: Direccion de cada objeto. Se prueba primero ``item/`` y luego ``block/``.
ITEM_URL = (
    "https://raw.githubusercontent.com/InventivetalentDev/minecraft-assets/"
    f"{ASSETS_REF}/assets/minecraft/textures/{{folder}}/{{name}}.png"
)
#: Cara y skin del jugador (64x64). Devuelve una skin por defecto si no existe.
SKIN_URL = "https://mc-heads.net/skin/{player}"

#: Tamano maximo de una textura (una skin normal ronda 1-4 KB).
MAX_TEXTURE_BYTES = 256 * 1024
#: Espera maxima de cada descarga, en segundos.
TIMEOUT = 4.0
#: Servidores a los que se permite pedir ficheros.
ALLOWED_HOSTS = frozenset({"raw.githubusercontent.com", "mc-heads.net"})

_ITEM_NAME = re.compile(r"^[a-z0-9_]{1,64}$")
_PLAYER = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Medidas aceptadas para cada tipo de imagen.
_ITEM_SIZES = {(16, 16), (32, 32), (16, 32), (32, 64)}
_SKIN_SIZES = {(64, 64), (64, 32)}


def offline() -> bool:
    """True si se ha pedido no salir a internet (pruebas o equipo sin red)."""
    return os.environ.get("SERVISCRAFT_OFFLINE", "").strip().lower() in {"1", "true", "si"}


def item_name(item_id: str) -> str:
    """``minecraft:diamond_sword`` -> ``diamond_sword`` (validado)."""
    name = str(item_id or "").split(":")[-1].strip().lower()
    return name if _ITEM_NAME.match(name) else ""


def player_name(player: str) -> str:
    """Nombre de jugador valido para pedir su skin (sin puntos de Bedrock).

    Floodgate presenta a los jugadores de Bedrock con un punto delante del
    nombre (``.Steve``). Ese punto sirve para los comandos del servidor, pero no
    forma parte del nombre con el que se buscan las skins, asi que aqui se quita
    solo si va al principio. Un punto en medio sigue siendo invalido.
    """
    name = str(player or "").strip()
    if name.startswith("."):
        name = name[1:]
    return name if _PLAYER.match(name) else ""


def textures_root() -> Path:
    return cache_dir() / "texturas"


def item_cache_path(item_id: str) -> Path | None:
    name = item_name(item_id)
    if not name:
        return None
    return textures_root() / "objetos" / ASSETS_REF / f"{name}.png"


def skin_cache_path(player: str) -> Path | None:
    name = player_name(player)
    if not name:
        return None
    return textures_root() / "skins" / f"{name.lower()}.png"


# =================================================================== descarga
class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Solo sigue redirecciones a https de la lista blanca."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(
                newurl, code, "Redireccion no permitida", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect)


def _download(url: str) -> bytes | None:
    """Descarga un fichero pequeno de la lista blanca."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        logger.warning("Se rechaza una direccion fuera de la lista blanca: %s", url)
        return None
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"Serviscraft/{APP_VERSION} (+https://serviscraft.local)",
            "Accept": "image/png",
        },
    )
    try:
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return None
            data = response.read(MAX_TEXTURE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("No se pudo descargar %s: %s", url, exc)
        return None
    if len(data) > MAX_TEXTURE_BYTES:
        logger.warning("La imagen de %s es demasiado grande; se descarta", url)
        return None
    return data


def _png_size(data: bytes) -> tuple[int, int] | None:
    """Medidas de un PNG sin cargarlo entero (cabecera IHDR)."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        return None
    if data[12:16] != b"IHDR":
        return None
    try:
        ancho, alto = struct.unpack(">II", data[16:24])
    except struct.error:  # pragma: no cover - ya se comprueba el tamano
        return None
    if not (0 < ancho <= 4096 and 0 < alto <= 65536):
        return None
    return ancho, alto


def valid_png(data: bytes, *, kind: str) -> bool:
    """True si son los bytes de un PNG del tamano que se espera."""
    medidas = _png_size(data)
    if medidas is None:
        return False
    return medidas in (_ITEM_SIZES if kind == "item" else _SKIN_SIZES)


def _read_cached(path: Path | None, *, kind: str) -> bytes | None:
    if path is None or not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if valid_png(data, kind=kind) else None


def _write_cached(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporal = path.with_suffix(".tmp")
        temporal.write_bytes(data)
        os.replace(temporal, path)
    except OSError as exc:  # pragma: no cover - disco lleno o permisos
        logger.warning("No se pudo guardar la textura %s: %s", path, exc)


def cached_item_texture(item_id: str) -> bytes | None:
    """Textura ya guardada (nunca sale a internet)."""
    return _read_cached(item_cache_path(item_id), kind="item")


def cached_skin(player: str) -> bytes | None:
    return _read_cached(skin_cache_path(player), kind="skin")


def fetch_item_texture(item_id: str) -> bytes | None:
    """Textura de un objeto: de la cache o, si hace falta, de internet."""
    name = item_name(item_id)
    if not name:
        return None
    path = item_cache_path(item_id)
    cacheada = _read_cached(path, kind="item")
    if cacheada is not None:
        return cacheada
    if offline() or path is None:
        return None
    for folder in ("item", "block"):
        data = _download(ITEM_URL.format(folder=folder, name=name))
        if data is not None and valid_png(data, kind="item"):
            _write_cached(path, data)
            return data
    logger.info("No hay textura publicada para %s", item_id)
    return None


def fetch_skin(player: str) -> bytes | None:
    """Skin (64x64) del jugador, buscada por su nombre."""
    name = player_name(player)
    if not name:
        return None
    path = skin_cache_path(name)
    cacheada = _read_cached(path, kind="skin")
    if cacheada is not None:
        return cacheada
    if offline() or path is None:
        return None
    data = _download(SKIN_URL.format(player=urllib.parse.quote(name, safe="")))
    if data is not None and valid_png(data, kind="skin"):
        _write_cached(path, data)
        return data
    return None


__all__ = [
    "ALLOWED_HOSTS",
    "ASSETS_REF",
    "ITEM_URL",
    "MAX_TEXTURE_BYTES",
    "SKIN_URL",
    "cached_item_texture",
    "cached_skin",
    "fetch_item_texture",
    "fetch_skin",
    "item_cache_path",
    "item_name",
    "offline",
    "player_name",
    "skin_cache_path",
    "valid_png",
]
