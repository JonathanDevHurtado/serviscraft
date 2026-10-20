"""Administracion de ficheros de un servidor: pluguins, mods y mundos.

Todas las rutas se validan contra la carpeta ``data`` del servidor para impedir
que una entrada manipulada escriba fuera de su sitio.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import shutil
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPResponse
from pathlib import Path

from .errors import ServiscraftError, ValidationError
from .logging_setup import get_logger
from .properties import ServerProperties
from .store import ServerStore, remove_tree
from .validation import ensure_within, reject_symlink, validate_basename

logger = get_logger("files")

#: Extensiones aceptadas al importar o descargar contenido.
ARCHIVE_SUFFIXES = (".jar", ".zip", ".mrpack")
#: Tamano maximo admitido en una descarga (200 MiB).
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
_ALLOWED_SCHEMES = {"http", "https"}
_MAGIC_ZIP = (b"PK\x03\x04", b"PK\x05\x06")


class FilesError(ServiscraftError):
    """Fallo al operar con ficheros del servidor."""


#: Directorios que nunca son un mundo (contenido propio del servidor).
NON_WORLD_DIRS = frozenset(
    {
        "plugins",
        "mods",
        "config",
        "configs",
        "logs",
        "cache",
        ".cache",
        "libraries",
        "versions",
        "crash-reports",
        "datapacks",
        "playerdata",
        "defaultconfigs",
        "kubejs",
        "scripts",
        "backups",
        "session.lock",
    }
)
#: Ficheros y carpetas que indican que un directorio es un mundo de Minecraft.
WORLD_MARKERS = ("level.dat", "session.lock", "uid.dat", "region", "DIM-1", "DIM1")


@dataclass(frozen=True)
class FileEntry:
    """Entrada de un directorio del servidor."""

    name: str
    relative_path: str
    is_dir: bool
    size_bytes: int
    modified: float

    @property
    def size_label(self) -> str:
        from .models import format_bytes

        return "-" if self.is_dir else format_bytes(self.size_bytes)


@dataclass(frozen=True)
class WorldInfo:
    """Mundo detectado en la carpeta del servidor."""

    name: str
    size_bytes: int
    modified: float
    active: bool

    @property
    def size_label(self) -> str:
        from .models import format_bytes

        return format_bytes(self.size_bytes)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Manejador que vuelve a validar cada salto de redireccion.

    ``urllib`` sigue las redirecciones por su cuenta: una URL publica podia
    responder ``302`` hacia ``http://127.0.0.1:8080`` y la peticion acababa en
    un servicio del propio equipo. Aqui se valida el destino antes de seguirlo.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        ServerFiles.validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_safely(request: urllib.request.Request) -> HTTPResponse:
    """Abre la URL comprobando **cada** salto de redireccion."""
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    return opener.open(request, timeout=30)


class ServerFiles:
    """Operaciones de ficheros sobre la carpeta ``data`` de un servidor."""

    def __init__(self, store: ServerStore, server_id: str) -> None:
        self.store = store
        self.server_id = server_id

    # ---------------------------------------------------------------- rutas
    @property
    def data_dir(self) -> Path:
        return self.store.data_dir(self.server_id)

    def resolve(self, relative: str = "") -> Path:
        """Ruta absoluta dentro de ``data`` a partir de una ruta relativa."""
        if not relative:
            return self.data_dir
        return ensure_within(Path(relative), self.data_dir)

    def subdir(self, name: str, *, create: bool = False) -> Path:
        target = ensure_within(Path(name), self.data_dir)
        if create:
            target.mkdir(parents=True, exist_ok=True)
        return target

    def plugins_dir(self, *, create: bool = False) -> Path:
        return self.subdir("plugins", create=create)

    def mods_dir(self, *, create: bool = False) -> Path:
        return self.subdir("mods", create=create)

    # --------------------------------------------------------------- listado
    def list_entries(self, relative: str = "", *, include_hidden: bool = False) -> list[FileEntry]:
        directory = self.resolve(relative)
        if not directory.is_dir():
            return []
        entries: list[FileEntry] = []
        for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if not include_hidden and item.name.startswith("."):
                continue
            # La carpeta la escribe el servidor: un enlace puede apuntar fuera.
            # No se muestra (y por tanto no se puede descargar ni borrar a traves).
            if item.is_symlink():
                logger.debug("Se ignora el enlace simbolico %s", item)
                continue
            try:
                stat = item.stat()
            except OSError:  # pragma: no cover - fichero desaparecido/enlazado roto
                continue
            entries.append(
                FileEntry(
                    name=item.name,
                    relative_path=str(item.relative_to(self.data_dir)),
                    is_dir=item.is_dir(),
                    size_bytes=stat.st_size,
                    modified=stat.st_mtime,
                )
            )
        return entries

    def directory_size(self, path: Path) -> int:
        total = 0
        for root, _dirs, files in os.walk(path, followlinks=False):
            for name in files:
                target = Path(root) / name
                try:
                    if not target.is_symlink():
                        total += target.stat().st_size
                except OSError:  # pragma: no cover
                    continue
        return total

    # ---------------------------------------------------------------- mundos
    def _is_world_dir(self, path: Path) -> bool:
        """Decide si un directorio es un mundo de Minecraft."""
        if not path.is_dir() or path.name in NON_WORLD_DIRS or path.name.startswith("."):
            return False
        return any((path / marker).exists() for marker in WORLD_MARKERS)

    def list_worlds(self) -> list[WorldInfo]:
        """Detecta los mundos: carpetas con ``level.dat`` u otros marcadores.

        Las dimensiones ``<mundo>_nether`` y ``<mundo>_the_end`` se agrupan con
        su mundo principal para no duplicar entradas.
        """
        active = self.active_world()
        worlds: list[WorldInfo] = []
        if not self.data_dir.is_dir():
            return worlds
        for item in sorted(self.data_dir.iterdir()):
            if not item.is_dir():
                continue
            if item.name.endswith(("_nether", "_the_end")):
                parent_name = item.name.rsplit("_", 1)[0]
                if self._is_world_dir(self.data_dir / parent_name):
                    continue
            if not self._is_world_dir(item):
                continue
            try:
                stat = item.stat()
            except OSError:  # pragma: no cover
                continue
            worlds.append(
                WorldInfo(
                    name=item.name,
                    size_bytes=self.directory_size(item),
                    modified=stat.st_mtime,
                    active=item.name == active,
                )
            )
        return worlds

    def world_related_dirs(self, world_name: str) -> list[Path]:
        """Carpetas que componen un mundo (principal, Nether y End)."""
        name = validate_basename(world_name)
        related: list[Path] = []
        for candidate in (name, f"{name}_nether", f"{name}_the_end"):
            path = ensure_within(Path(candidate), self.data_dir)
            if path.is_dir():
                related.append(path)
        return related

    def active_world(self) -> str:
        try:
            props = ServerProperties.load(self.data_dir / "server.properties")
        except Exception:  # pragma: no cover - fichero ilegible
            return "world"
        return props.get("level-name", "world") or "world"

    def set_active_world(self, world_name: str) -> None:
        """Cambia el mundo activo editando ``level-name`` (requiere reinicio)."""
        name = validate_basename(world_name)
        target = ensure_within(Path(name), self.data_dir)
        if not target.is_dir():
            raise FilesError(f"El mundo '{name}' no existe en este servidor.")
        props_path = self.data_dir / "server.properties"
        props = ServerProperties.load(props_path)
        props.set("level-name", name)
        props.save(props_path)
        logger.info("Mundo activo de %s cambiado a %s", self.server_id, name)

    def delete_world(self, world_name: str) -> int:
        """Elimina un mundo y sus dimensiones asociadas. Devuelve el espacio liberado."""
        related = self.world_related_dirs(world_name)
        if not related:
            raise FilesError(f"El mundo '{world_name}' no existe.")
        # Defensa en profundidad: la interfaz ya lo impide, pero el nucleo tampoco
        # debe permitir quedarse sin el mundo que carga el servidor.
        if self.active_world() == world_name:
            raise FilesError(
                f"El mundo '{world_name}' esta en uso por el servidor. "
                "Activa otro mundo antes de eliminarlo."
            )
        freed = 0
        for directory in related:
            freed += self.directory_size(directory)
            remove_tree(directory)
        logger.warning("Mundo %s eliminado de %s (%s bytes)", world_name, self.server_id, freed)
        return freed

    def rename_world(self, world_name: str, new_name: str) -> None:
        new = validate_basename(new_name)
        if new != world_name and ensure_within(Path(new), self.data_dir).exists():
            raise FilesError(f"Ya existe un mundo llamado '{new}'.")
        for directory in self.world_related_dirs(world_name):
            suffix = directory.name[len(world_name) :]
            directory.rename(directory.with_name(f"{new}{suffix}"))
        if self.active_world() == world_name:
            self.set_active_world(new)

    def copy_world(self, world_name: str) -> str:
        """Duplica un mundo (con sus dimensiones) para hacer pruebas o copias.

        Devuelve el nombre del mundo nuevo.
        """
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        new_name = validate_basename(f"{world_name}-copia-{stamp}")
        related = self.world_related_dirs(world_name)
        if not related:
            raise FilesError(f"El mundo '{world_name}' no existe.")
        for directory in related:
            suffix = directory.name[len(world_name) :]
            destination = ensure_within(Path(f"{new_name}{suffix}"), self.data_dir)
            if destination.exists():
                raise FilesError(f"Ya existe '{destination.name}'.")
            shutil.copytree(directory, destination, symlinks=False)
        logger.info("Mundo %s copiado a %s en %s", world_name, new_name, self.server_id)
        return new_name

    # ------------------------------------------------------------- importar
    def create_folder(self, parent_relative: str, name: str) -> Path:
        """Crea una subcarpeta dentro del servidor."""
        parent = self.resolve(parent_relative)
        parent.mkdir(parents=True, exist_ok=True)
        target = ensure_within(Path(validate_basename(name)), parent)
        if target.exists():
            raise FilesError(f"Ya existe un elemento llamado '{name}'.")
        target.mkdir()
        logger.info("Carpeta creada: %s", target)
        return target

    def import_files(self, sources: Iterable[Path], subdir: str) -> list[Path]:
        """Copia ficheros locales a ``subdir`` (por ejemplo ``plugins`` o ``mods``)."""
        destination = self.subdir(subdir, create=True)
        imported: list[Path] = []
        for source in sources:
            src = Path(source)
            if not src.is_file():
                continue
            name = validate_basename(src.name)
            target = ensure_within(Path(name), destination)
            reject_symlink(target, role="El fichero importado")
            shutil.copy2(src, target)
            imported.append(target)
        if imported:
            logger.info("Importados %d ficheros en %s/%s", len(imported), self.server_id, subdir)
        return imported

    def delete_entry(self, relative: str) -> None:
        target = self.resolve(relative)
        if target == self.data_dir:
            raise ValidationError("path", "No se puede eliminar la carpeta raiz del servidor.")
        if target.is_dir():
            remove_tree(target)
        elif target.is_file():
            target.unlink()
        else:
            raise FilesError("La entrada indicada no existe.")
        logger.info("Eliminado %s de %s", relative, self.server_id)

    # ------------------------------------------------------------ descargas
    @staticmethod
    def validate_download_url(url: str) -> str:
        """Comprueba que la URL es http/https y apunta a un recurso publico.

        Se rechazan las direcciones locales (loopback, link-local, multicast):
        una URL pegada a mano no puede usarse para hablar con servicios del
        propio equipo. Los rangos privados (192.168.x…) si se permiten porque
        descargar de un servidor de la red local es un uso legitimo.
        """
        cleaned = str(url or "").strip()
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise ValidationError("url", "Solo se admiten direcciones http o https.")
        if not parsed.netloc:
            raise ValidationError("url", "La direccion no es valida.")
        if parsed.username or parsed.password:
            raise ValidationError("url", "La direccion no puede incluir credenciales.")
        host = (parsed.hostname or "").strip()
        if host.lower() in {"localhost", "localhost.localdomain"}:
            raise ValidationError("url", "No se permiten direcciones locales.")
        ServerFiles._reject_local_addresses(host)
        return cleaned

    @staticmethod
    def _reject_local_addresses(host: str) -> None:
        """Resuelve el nombre y rechaza loopback, link-local y multicast.

        Se comprueba la IP y no solo el texto: ``127.0.0.1.nip.io`` o
        ``[::ffff:127.0.0.1]`` resolvian a la propia maquina sin coincidir con
        la lista de nombres prohibidos.
        """
        if not host:
            return
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
        except OSError:
            # Si no resuelve, la descarga fallara con un error claro; aqui no
            # se puede afirmar que sea insegura.
            return
        for address in addresses:
            limpia = address.split("%", 1)[0]
            try:
                ip = ipaddress.ip_address(limpia)
            except ValueError:  # pragma: no cover - getaddrinfo devuelve IPs
                continue
            if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                raise ValidationError("url", "No se permiten direcciones locales o internas.")

    @staticmethod
    def filename_from_url(url: str, override: str | None = None) -> str:
        if override:
            return validate_basename(override)
        path = urllib.parse.urlparse(url).path
        candidate = urllib.parse.unquote(Path(path).name)
        if not candidate:
            raise ValidationError("url", "No se pudo determinar el nombre del fichero.")
        return validate_basename(candidate, allowed_suffixes=ARCHIVE_SUFFIXES)

    def download(
        self,
        url: str,
        subdir: str,
        *,
        filename: str | None = None,
        expected_sha512: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        """Descarga un pluguin o mod desde una URL a la carpeta indicada.

        Si se indica ``expected_sha512`` se comprueba la integridad del fichero
        antes de moverlo a su sitio definitivo.
        """
        cleaned_url = self.validate_download_url(url)
        name = self.filename_from_url(cleaned_url, filename)
        destination_dir = self.subdir(subdir, create=True)
        target = ensure_within(Path(name), destination_dir)
        # El fichero descargado vive en la carpeta del servidor (que escribe el
        # propio servidor): si alguien planto un enlace, no se sigue.
        reject_symlink(target, role="El fichero de destino")

        request = urllib.request.Request(
            cleaned_url,
            headers={"User-Agent": "Serviscraft/0.1 (+podman-manager)", "Accept": "*/*"},
        )
        hasher = hashlib.sha512()
        logger.info("Descargando %s -> %s", cleaned_url, target)
        descriptor, nombre_temporal = tempfile.mkstemp(
            dir=str(destination_dir), prefix=f".{target.name}.", suffix=".part"
        )
        partial = Path(nombre_temporal)
        try:
            with os.fdopen(descriptor, "wb") as handle, _open_safely(request) as response:
                total = int(response.headers.get("Content-Length") or 0)
                if total > MAX_DOWNLOAD_BYTES:
                    raise FilesError("El fichero remoto es demasiado grande.")
                downloaded = 0
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise FilesError("La descarga supera el tamano maximo permitido.")
                    if should_cancel is not None and should_cancel():
                        raise FilesError("Descarga cancelada.")
                    handle.write(chunk)
                    hasher.update(chunk)
                    if on_progress is not None:
                        on_progress(downloaded, total)
            if expected_sha512 and hasher.hexdigest().lower() != expected_sha512.lower():
                raise FilesError(
                    "La descarga no coincide con la suma de comprobacion publicada. "
                    "No se ha instalado nada."
                )
            self._verify_archive(partial)
            if target.exists() and target.is_symlink():  # pragma: no cover - ya rechazado
                raise FilesError("El fichero de destino es un enlace simbolico.")
            os.replace(partial, target)
        except urllib.error.URLError as exc:
            raise FilesError(f"No se pudo descargar el fichero: {exc.reason}") from exc
        except OSError as exc:
            raise FilesError(f"Error de red al descargar: {exc}") from exc
        finally:
            # Pase lo que pase (error de red, suma que no cuadra, ZIP invalido,
            # cancelacion) no se deja basura con datos remotos dentro del
            # servidor: el servidor podria leer ese fichero.
            partial.unlink(missing_ok=True)
        logger.info("Descarga completada: %s", target)
        return target

    @staticmethod
    def _verify_archive(path: Path) -> None:
        """Comprueba la firma del fichero descargado (evita descargar HTML de error)."""
        try:
            with path.open("rb") as handle:
                header = handle.read(4)
        except OSError as exc:
            raise FilesError(f"No se pudo leer el fichero descargado: {exc}") from exc
        if path.suffix.lower() == ".mrpack":
            return
        if header not in _MAGIC_ZIP:
            raise FilesError(
                "El fichero descargado no es un JAR/ZIP valido. "
                "Comprueba el enlace (puede requerir iniciar sesion o estar caducado)."
            )

    # ------------------------------------------------------------ utilidades
    def total_size(self) -> int:
        return self.directory_size(self.data_dir) if self.data_dir.is_dir() else 0

    def open_path(self, relative: str = "") -> Path:
        """Devuelve la ruta absoluta validada (para abrirla con la aplicacion externa)."""
        return self.resolve(relative)
