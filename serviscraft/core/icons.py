"""Cache local de los iconos de los proyectos de Modrinth.

Los iconos los sirve Modrinth en una direccion (``icon_url``); descargarlos en
cada busqueda seria lento y repetitivo, asi que se guardan en disco la primera
vez y despues se leen de ahi. El fichero se identifica por el resumen (hash) de
su direccion, de modo que no hay que inventar nombres de fichero.

Reglas de seguridad: solo se descarga por ``http``/``https`` (nunca ``file://``,
que permitiria leer ficheros del equipo) y con un tamano maximo, para que un
servidor remoto no pueda llenar el disco ni colgar la aplicacion.
"""

from __future__ import annotations

import hashlib
import ipaddress
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from .logging_setup import get_logger
from .paths import cache_dir

logger = get_logger("icons")

#: Tamano maximo aceptado para un icono (una imagen normal no llega ni de lejos).
MAX_ICON_BYTES = 512 * 1024
#: Espera maxima de cada descarga, en segundos.
DEFAULT_TIMEOUT = 6
#: Extensiones que se conservan al guardar (si no, se guarda como ``.img``).
KNOWN_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")


def icons_cache_dir() -> Path:
    """Carpeta donde se guardan los iconos descargados."""
    return cache_dir() / "iconos"


def cache_key(url: str) -> str:
    """Identificador estable de una direccion de icono."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def cached_path(url: str) -> Path:
    """Ruta del fichero en disco para esa direccion."""
    sufijo = Path(url.split("?", 1)[0]).suffix.lower()
    if sufijo not in KNOWN_SUFFIXES:
        sufijo = ".img"
    return icons_cache_dir() / f"{cache_key(url)}{sufijo}"


def cached_bytes(url: str) -> bytes | None:
    """Contenido del icono si ya esta en la cache (``None`` si no)."""
    if not url:
        return None
    try:
        datos = cached_path(url).read_bytes()
    except OSError:
        return None
    return datos or None


def _is_allowed_host(host: str) -> bool:
    """True si el nombre no apunta a la propia maquina ni a una red interna.

    Se comprueba el texto, sin consultar DNS: asi la comprobacion no depende de
    la red (los iconos los sirve siempre Modrinth, una direccion nunca es un
    icono). Se rechazan ``localhost``, los nombres locales y las direcciones IP
    privadas escritas tal cual.
    """
    nombre = (host or "").strip().strip("[]").lower()
    if not nombre:
        return False
    if nombre in {"localhost", "localhost.localdomain"} or nombre.endswith(
        (".localhost", ".local", ".internal", ".home.arpa")
    ):
        return False
    try:
        ip = ipaddress.ip_address(nombre)
    except ValueError:
        return True
    return not (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_private
        or ip.is_reserved
    )


def _url_is_allowed(url: str) -> bool:
    """Valida esquema y destino. Los iconos siempre vienen de Internet."""
    if not url:
        return False
    partes = urllib.parse.urlparse(url)
    if partes.scheme.lower() not in {"http", "https"}:
        return False
    if partes.username or partes.password:
        return False
    return _is_allowed_host(partes.hostname or "")


def download(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> bytes | None:
    """Devuelve el icono (de la cache o recien descargado). Nunca lanza."""
    datos = cached_bytes(url)
    if datos is not None:
        return datos
    if not _url_is_allowed(url):
        return None
    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": "Serviscraft"})
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:  # noqa: S310 - esquema y host validados
            # ``urlopen`` sigue las redirecciones por su cuenta: si el destino
            # final ya no es publico, la imagen se descarta.
            final = respuesta.geturl() if hasattr(respuesta, "geturl") else url
            if not _url_is_allowed(final):
                logger.debug("Icono descartado: la redireccion no es publica (%s)", url)
                return None
            datos = respuesta.read(MAX_ICON_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.debug("No se pudo descargar el icono %s: %s", url, exc)
        return None
    if not datos or len(datos) > MAX_ICON_BYTES:
        logger.debug("Icono descartado por tamano (%s bytes): %s", len(datos or b""), url)
        return None
    _guardar(url, datos)
    return datos


def prefetch(urls: Iterable[str], *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, bytes]:
    """Descarga varios iconos y los devuelve indexados por direccion.

    Pensado para llamarse desde un hilo de trabajo (el de la busqueda), de modo
    que la ventana siga respondiendo mientras llegan las imagenes.
    """
    resultado: dict[str, bytes] = {}
    for url in dict.fromkeys(str(url or "") for url in urls):
        if not url:
            continue
        datos = download(url, timeout=timeout)
        if datos is not None:
            resultado[url] = datos
    return resultado


def clear_cache() -> int:
    """Borra los iconos guardados. Devuelve cuantos ficheros se han quitado."""
    quitados = 0
    carpeta = icons_cache_dir()
    if not carpeta.is_dir():
        return 0
    for fichero in carpeta.iterdir():
        if not fichero.is_file():
            continue
        try:
            fichero.unlink()
        except OSError:  # pragma: no cover - permisos del sistema
            continue
        quitados += 1
    return quitados


def _guardar(url: str, datos: bytes) -> None:
    try:
        ruta = cached_path(url)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # La cache es del usuario, pero por si acaso: nunca se escribe a traves
        # de un enlace simbolico.
        if ruta.is_symlink():
            ruta.unlink(missing_ok=True)
        ruta.write_bytes(datos)
    except OSError as exc:  # pragma: no cover - disco lleno o permisos
        logger.debug("No se pudo guardar el icono de %s: %s", url, exc)


__all__ = [
    "DEFAULT_TIMEOUT",
    "KNOWN_SUFFIXES",
    "MAX_ICON_BYTES",
    "cache_key",
    "cached_bytes",
    "cached_path",
    "clear_cache",
    "download",
    "icons_cache_dir",
    "prefetch",
]
