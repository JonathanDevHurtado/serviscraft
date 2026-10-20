"""Validacion de entradas y utilidades de rutas seguras.

Reglas de oro del proyecto:

* Nunca se construye una linea de comandos de shell. Todos los procesos se
  lanzan con listas de argumentos, por lo que la inyeccion de shell no es
  posible; aun asi se validan todas las entradas para dar mensajes claros y
  evitar valores absurdos o peligrosos.
* Ninguna operacion de ficheros puede salir de la carpeta del servidor: toda
  ruta se resuelve y se comprueba que queda dentro de la raiz permitida.
"""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from .errors import ValidationError
from .paths import MAX_MEMORY_MB, MAX_PORT, MIN_MEMORY_MB, MIN_PORT

#: Caracteres admitidos en el nombre visible de un servidor.
_NAME_ALLOWED = re.compile(r"^[\w\-. ]+$", re.UNICODE)
#: Caracteres admitidos en versiones de Minecraft / cargadores.
_VERSION_ALLOWED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
#: Identificador interno de servidor (generado por la aplicacion).
_SERVER_ID_ALLOWED = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")
_IMAGE_ALLOWED = re.compile(r"^[A-Za-z0-9._/:@-]{1,200}$")

MAX_NAME_LENGTH = 32
MAX_SLUG_LENGTH = 24


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_name(name: str) -> str:
    """Valida y normaliza el nombre visible de un servidor."""
    if name is None:
        raise ValidationError("name", "El nombre es obligatorio.")
    cleaned = collapse_whitespace(str(name))
    if not cleaned:
        raise ValidationError("name", "El nombre es obligatorio.")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError("name", f"El nombre no puede superar {MAX_NAME_LENGTH} caracteres.")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("name", "El nombre no puede contener caracteres de control.")
    if not _NAME_ALLOWED.match(cleaned):
        raise ValidationError(
            "name",
            "El nombre solo puede contener letras, numeros, espacios y los signos . - _",
        )
    return cleaned


def slugify(name: str) -> str:
    """Convierte un nombre en un identificador seguro para nombres de contenedor."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "server")[:MAX_SLUG_LENGTH].strip("-") or "server"


def validate_slug(slug: str) -> str:
    if not _SERVER_ID_ALLOWED.match(slug or ""):
        raise ValidationError("slug", "El identificador generado no es valido.")
    return slug


def validate_server_id(server_id: str) -> str:
    if not _SERVER_ID_ALLOWED.match(server_id or ""):
        raise ValidationError("id", "Identificador de servidor no valido.")
    return server_id


def validate_port(port: int | str, *, reserved: Iterable[int] = ()) -> int:
    """Valida un puerto TCP del host disponible para el servidor."""
    try:
        value = int(str(port).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError("port", "El puerto debe ser un numero entero.") from exc
    if not MIN_PORT <= value <= MAX_PORT:
        raise ValidationError("port", f"El puerto debe estar entre {MIN_PORT} y {MAX_PORT}.")
    if value in set(reserved):
        raise ValidationError("port", f"El puerto {value} ya esta en uso por otro servidor.")
    return value


def port_is_free(port: int, *, host: str = "0.0.0.0", protocol: str = "tcp") -> bool:
    """Comprueba (mejor esfuerzo) si un puerto esta libre en el host.

    ``protocol`` es ``"tcp"`` (Minecraft Java) o ``"udp"`` (Bedrock/Geyser).
    """
    import socket

    if protocol == "udp":
        kind = socket.SOCK_DGRAM
    else:
        kind = socket.SOCK_STREAM
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, kind) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def validate_memory_mb(memory_mb: int | str) -> int:
    try:
        value = int(str(memory_mb).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError("memory", "La memoria debe ser un numero entero de MB.") from exc
    if not MIN_MEMORY_MB <= value <= MAX_MEMORY_MB:
        raise ValidationError(
            "memory",
            f"La memoria debe estar entre {MIN_MEMORY_MB} y {MAX_MEMORY_MB} MB.",
        )
    return value


def format_memory(memory_mb: int) -> str:
    """Devuelve la memoria en el formato que espera la imagen (``2G``, ``512M``)."""
    value = validate_memory_mb(memory_mb)
    if value % 1024 == 0:
        return f"{value // 1024}G"
    return f"{value}M"


def validate_minecraft_version(version: str) -> str:
    if version is None:
        raise ValidationError("version", "La version es obligatoria.")
    cleaned = str(version).strip()
    if not _VERSION_ALLOWED.match(cleaned):
        raise ValidationError(
            "version",
            "Version no valida. Usa por ejemplo 1.21.4, latest o 1.20.1.",
        )
    return cleaned


def validate_image(image: str) -> str:
    cleaned = (image or "").strip()
    if not _IMAGE_ALLOWED.match(cleaned):
        raise ValidationError("image", "Nombre de imagen OCI no valido.")
    return cleaned


def validate_java_tag(tag: str) -> str:
    cleaned = (tag or "").strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", cleaned):
        raise ValidationError("java", "Etiqueta de Java no valida.")
    return cleaned


#: Longitud minima de la contrasena de RCON.
MIN_PASSWORD_LENGTH = 8


def validate_password(password: str, *, minimum: int = MIN_PASSWORD_LENGTH) -> str:
    cleaned = str(password or "")
    if len(cleaned) < minimum:
        raise ValidationError("password", f"La contrasena debe tener al menos {minimum} caracteres.")
    if any(ch.isspace() for ch in cleaned):
        raise ValidationError("password", "La contrasena no puede contener espacios.")
    if len(cleaned) > 128:
        raise ValidationError("password", "La contrasena es demasiado larga.")
    return cleaned


def validate_basename(name: str, *, allowed_suffixes: Iterable[str] | None = None) -> str:
    """Valida el nombre de un fichero recibido del usuario o de la red.

    Rechaza rutas, separadores y nombres reservados para evitar salir de la
    carpeta del servidor.
    """
    cleaned = str(name or "").strip()
    if not cleaned or cleaned in {".", ".."}:
        raise ValidationError("file", "Nombre de fichero no valido.")
    if "/" in cleaned or "\\" in cleaned or os.sep in cleaned:
        raise ValidationError("file", "El nombre de fichero no puede contener rutas.")
    if cleaned != Path(cleaned).name:
        raise ValidationError("file", "El nombre de fichero no puede contener rutas.")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("file", "El nombre de fichero no puede contener caracteres de control.")
    if len(cleaned) > 255:
        raise ValidationError("file", "El nombre de fichero es demasiado largo.")
    if allowed_suffixes is not None:
        suffixes = tuple(allowed_suffixes)
        if not cleaned.lower().endswith(suffixes):
            raise ValidationError(
                "file",
                f"El fichero debe terminar en: {', '.join(suffixes)}.",
            )
    return cleaned


def ensure_within(path: Path, root: Path) -> Path:
    """Resuelve ``path`` y garantiza que queda dentro de ``root``.

    Protege frente a ataques de travesia de directorios (``..``) y enlaces
    simbolicos que apunten fuera de la carpeta permitida.
    """
    root_resolved = Path(root).expanduser().resolve()
    candidate = Path(path).expanduser()
    resolved = (root_resolved / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValidationError("path", "La ruta solicitada esta fuera de la carpeta permitida.")
    return resolved


def validate_relative_subpath(subpath: str, root: Path) -> Path:
    """Valida una ruta relativa introducida por el usuario dentro de ``root``."""
    cleaned = str(subpath or "").strip().replace("\\", "/")
    if not cleaned or cleaned in {".", ".."}:
        raise ValidationError("path", "Ruta no valida.")
    if cleaned.startswith("/") or cleaned.startswith("~"):
        raise ValidationError("path", "Usa una ruta relativa dentro de la carpeta del servidor.")
    parts = [p for p in cleaned.split("/") if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise ValidationError("path", "La ruta no puede contener '..'.")
    return ensure_within(Path(*parts), root)


def reject_symlink(path: Path, *, role: str = "El fichero") -> Path:
    """Devuelve la ruta, pero rechaza los enlaces simbolicos.

    La carpeta ``data/`` del servidor la puede escribir el propio servidor (y
    sus plugins), asi que se trata como entrada no confiable: un enlace
    simbolico plantado ahi podria hacer que la aplicacion leyera o escribiera
    un fichero de fuera de la carpeta del servidor.
    """
    candidate = Path(path)
    try:
        if candidate.is_symlink():
            raise ValidationError(
                "path",
                f"{role} es un enlace simbolico. Por seguridad no se sigue; "
                "borralo desde la pestana Archivos si no lo creaste tu.",
            )
    except OSError as exc:  # pragma: no cover - sistema de ficheros raro
        raise ValidationError("path", f"No se pudo comprobar {role.lower()}: {exc}") from exc
    return candidate


def read_text_inside(path: Path, root: Path, *, encoding: str = "utf-8", errors: str = "replace") -> str:
    """Lee un texto comprobando que la ruta (ya resuelta) queda dentro de ``root``."""
    candidate = reject_symlink(path)
    resolved = ensure_within(candidate, root)
    try:
        return resolved.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        raise ValidationError("path", f"No se pudo leer {resolved.name}: {exc}") from exc


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    role: str = "El fichero",
    mode: int | None = None,
) -> Path:
    """Escribe un texto de forma atomica y sin seguir enlaces simbolicos.

    El temporal se crea con :func:`tempfile.mkstemp` (nombre impredecible y
    ``O_EXCL``) en la misma carpeta y despues se renombra encima con
    ``os.replace``. Un enlace plantado de antemano ya no puede desviar la
    escritura: o se rechaza, o el renombrado sustituye al enlace.
    """
    target = reject_symlink(path, role=role)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            try:
                os.chmod(temporal, mode)
            except OSError:  # pragma: no cover - sistemas sin permisos POSIX
                pass
        os.replace(temporal, target)
    except BaseException:
        try:
            Path(temporal).unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass
        raise
    return target


def read_bytes_inside(path: Path, root: Path, *, limit: int | None = None) -> bytes:
    """Lee un binario comprobando que la ruta queda dentro de ``root``.

    Se usa para el icono del servidor (``server-icon.png``), que vive en la
    carpeta ``data/`` que escribe el propio servidor: un enlace simbolico
    plantado ahi no se sigue.
    """
    candidate = reject_symlink(path)
    resolved = ensure_within(candidate, root)
    try:
        if limit is not None and resolved.stat().st_size > limit:
            raise ValidationError(
                "size", f"{resolved.name} es demasiado grande para ser un icono."
            )
        return resolved.read_bytes()
    except ValidationError:
        raise
    except OSError as exc:
        raise ValidationError("path", f"No se pudo leer {resolved.name}: {exc}") from exc


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    role: str = "El fichero",
    mode: int | None = None,
) -> Path:
    """Version binaria de :func:`atomic_write_text` (mismo cuidado con enlaces)."""
    target = reject_symlink(path, role=role)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            try:
                os.chmod(temporal, mode)
            except OSError:  # pragma: no cover - sistemas sin permisos POSIX
                pass
        os.replace(temporal, target)
    except BaseException:
        try:
            Path(temporal).unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass
        raise
    return target
