"""Copias de seguridad de servidores (crear, listar, restaurar y borrar)."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .errors import BackupError, ValidationError
from .logging_setup import get_logger
from .models import format_bytes
from .store import ServerStore, remove_tree
from .validation import atomic_write_text, ensure_within, reject_symlink, validate_basename

logger = get_logger("backup")

#: Fichero con la metainformacion de la copia.
METADATA_SUFFIX = ".json"
BACKUP_SUFFIX = ".tar.gz"
#: Espacio libre minimo que se exige antes de crear una copia (margen de seguridad).
FREE_SPACE_MARGIN = 64 * 1024 * 1024
#: Longitud maxima de la etiqueta de una copia (se ve en la tabla).
MAX_LABEL_LENGTH = 60
#: Limites defensivos al leer un archivo que no controlamos (p. ej. importado
#: de otra persona): una copia pequeña podia descomprimirse a un tamaño enorme.
MAX_ARCHIVE_MEMBERS = 500_000
MAX_BACKUP_SOURCE_BYTES = 20 * 1024 * 1024 * 1024


def _free_bytes(path: Path) -> int:
    """Espacio libre en el disco que contiene ``path`` (0 si no se sabe)."""
    try:
        return int(shutil.disk_usage(path).free)
    except OSError:  # pragma: no cover - depende del sistema de ficheros
        return 0

#: Origen de las copias que crea la aplicacion sola: la que se hace al detener
#: un servidor y la programada. Son las unicas que la limpieza automatica puede
#: retirar jamas: las manuales, las de seguridad y las importadas se conservan.
ORIGEN_AL_DETENER = "al-detener"
ORIGEN_PROGRAMADA = "programada"
ORIGENES_AUTOMATICOS: tuple[str, ...] = (ORIGEN_AL_DETENER, ORIGEN_PROGRAMADA)


@dataclass
class BackupInfo:
    """Descripcion de una copia de seguridad existente."""

    filename: str
    path: str
    size_bytes: int
    created_at: str
    label: str = ""
    origin: str = "manual"
    app_version: str = ""

    @property
    def size_label(self) -> str:
        return format_bytes(self.size_bytes)

    @property
    def display_name(self) -> str:
        return self.label or self.filename

    def to_dict(self) -> dict:
        return asdict(self)


class BackupManager:
    """Crea y restaura copias de la carpeta ``data`` de un servidor."""

    def __init__(self, store: ServerStore) -> None:
        self.store = store
        # Un servidor no se copia dos veces a la vez: la copia programada y una
        # manual pueden coincidir, y comprimir el mismo mundo en paralelo solo
        # hace que las dos tarden mas. La segunda espera a que acabe la primera.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, server_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(server_id, threading.Lock())

    # ---------------------------------------------------------------- rutas
    def backups_dir(self, server_id: str) -> Path:
        directory = self.store.backups_dir(server_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _metadata_path(self, backup_path: Path) -> Path:
        return backup_path.with_name(backup_path.name + METADATA_SUFFIX)

    # -------------------------------------------------------------- listado
    def list_backups(self, server_id: str) -> list[BackupInfo]:
        """Copias del servidor, de la mas nueva a la mas vieja.

        El orden es el **cronologico real** (fecha de modificacion con precision
        de nanosegundos), no el alfabetico del nombre: varias copias pueden caer
        en el mismo segundo (por ejemplo, «copiar todos los servidores» seguido
        de una manual) y la retencion debe conservar las ultimas de verdad.
        """
        directory = self.store.backups_dir(server_id)
        if not directory.is_dir():
            return []
        entradas: list[tuple[int, str, os.stat_result]] = []
        for entry in directory.glob(f"*{BACKUP_SUFFIX}"):
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except OSError:  # pragma: no cover
                continue
            entradas.append((stat.st_mtime_ns, entry.name, stat))
        entradas.sort(key=lambda item: (item[0], item[1]), reverse=True)

        items: list[BackupInfo] = []
        for _, name, stat in entradas:
            entry = directory / name
            meta: dict = {}
            meta_file = self._metadata_path(entry)
            if meta_file.is_file():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}
            items.append(
                BackupInfo(
                    filename=entry.name,
                    path=str(entry),
                    size_bytes=stat.st_size,
                    created_at=meta.get("created_at") or datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    label=meta.get("label", ""),
                    origin=meta.get("origin", "manual"),
                    app_version=meta.get("app_version", ""),
                )
            )
        return items

    def backup_path(self, server_id: str, backup_path: str | Path) -> Path:
        """Valida que una copia pertenece al servidor indicado."""
        return ensure_within(Path(backup_path), self.backups_dir(server_id))

    # ---------------------------------------------------------------- crear
    def _free_destination(self, server_id: str, filename: str) -> Path:
        """Nombre libre dentro de ``backups/``.

        El nombre lleva la fecha al segundo: dos copias seguidas (por ejemplo
        «copiar todos los servidores» y luego una manual) caerian en el mismo
        fichero y una pisaria a la otra. Si ya existe se anade un contador.
        """
        directory = self.backups_dir(server_id)
        base = filename[: -len(BACKUP_SUFFIX)] if filename.endswith(BACKUP_SUFFIX) else filename
        candidate = directory / filename
        counter = 2
        while candidate.exists() or candidate.with_name(candidate.name + ".part").exists():
            candidate = directory / f"{base}-{counter}{BACKUP_SUFFIX}"
            counter += 1
        return candidate

    def create_backup(
        self,
        server_id: str,
        *,
        label: str = "",
        origin: str = "manual",
        on_progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> BackupInfo:
        """Comprime la carpeta ``data`` del servidor en ``backups/``.

        Las copias de un mismo servidor se hacen de una en una, aunque las pidan
        a la vez el temporizador de copias programadas y una accion tuya.
        """
        with self._lock_for(server_id):
            return self._create_backup(
                server_id,
                label=label,
                origin=origin,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )

    def _create_backup(
        self,
        server_id: str,
        *,
        label: str = "",
        origin: str = "manual",
        on_progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> BackupInfo:
        """Copia de verdad (siempre dentro del cerrojo de ``create_backup``)."""
        data_dir = self.store.data_dir(server_id)
        if not data_dir.is_dir():
            raise BackupError("El servidor no tiene datos que copiar todavia.")

        self._check_free_space(data_dir)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_label = "".join(ch for ch in label if ch.isalnum() or ch in "-_")[:32]
        filename = f"backup-{timestamp}{'-' + safe_label if safe_label else ''}{BACKUP_SUFFIX}"
        destination = self._free_destination(server_id, filename)
        partial = destination.with_name(destination.name + ".part")

        total_bytes = self._total_bytes(data_dir)
        logger.info("Creando copia %s de %s (%s)", filename, server_id, format_bytes(total_bytes))

        written = 0
        try:
            with tarfile.open(partial, "w:gz", compresslevel=6) as archive:
                for path in self._iter_files(data_dir):
                    if should_cancel is not None and should_cancel():
                        raise BackupError("Copia cancelada.")
                    arcname = str(path.relative_to(data_dir))
                    info = archive.gettarinfo(str(path), arcname=arcname)
                    # Nunca guardamos enlaces simbolicos: evita rutas fuera del archivo.
                    if info.issym() or info.islnk():
                        continue
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)
                    written += info.size
                    if on_progress is not None:
                        on_progress(written, total_bytes)
        except (OSError, tarfile.TarError) as exc:
            partial.unlink(missing_ok=True)
            raise BackupError(f"No se pudo crear la copia: {exc}") from exc
        except BaseException:
            # Cancelacion o interrupcion: nunca se deja una copia a medias.
            partial.unlink(missing_ok=True)
            raise

        partial.replace(destination)
        stat = destination.stat()
        info = BackupInfo(
            filename=destination.name,
            path=str(destination),
            size_bytes=stat.st_size,
            created_at=datetime.now().isoformat(timespec="seconds"),
            label=label,
            origin=origin,
            app_version=_app_version(),
        )
        atomic_write_text(
            self._metadata_path(destination),
            json.dumps(info.to_dict(), indent=2, ensure_ascii=False) + "\n",
            role="La ficha de la copia",
        )
        logger.info("Copia creada: %s (%s)", destination, info.size_label)
        return info

    def import_backup(self, server_id: str, source: str | Path, *, label: str = "") -> BackupInfo:
        """Copia una copia de seguridad externa a la carpeta del servidor.

        Permite recuperar copias guardadas en otro equipo o pertenecientes a un
        servidor ya eliminado de la lista.
        """
        origin = Path(source).expanduser()
        if not origin.is_file():
            raise BackupError("El fichero indicado no existe.")
        try:
            tamano = origin.stat().st_size
        except OSError as exc:
            raise BackupError(f"No se pudo leer el fichero: {exc}") from exc
        if tamano > MAX_BACKUP_SOURCE_BYTES:
            raise BackupError(
                "La copia es demasiado grande para importarla desde la aplicacion."
            )
        if not tarfile.is_tarfile(origin):
            raise BackupError("El fichero no es una copia de seguridad valida (.tar.gz).")
        name = validate_basename(origin.name, allowed_suffixes=(BACKUP_SUFFIX, ".tgz"))
        self.backups_dir(server_id).mkdir(parents=True, exist_ok=True)
        destination = self.backups_dir(server_id) / name
        reject_symlink(destination, role="La copia de destino")
        counter = 1
        while destination.exists():
            stem = name[: -len(BACKUP_SUFFIX)]
            destination = self.backups_dir(server_id) / f"{stem}-{counter}{BACKUP_SUFFIX}"
            counter += 1
        shutil.copy2(origin, destination)
        stat = destination.stat()
        info = BackupInfo(
            filename=destination.name,
            path=str(destination),
            size_bytes=stat.st_size,
            created_at=datetime.now().isoformat(timespec="seconds"),
            label=label or "importada",
            origin="importada",
            app_version=_app_version(),
        )
        atomic_write_text(
            self._metadata_path(destination),
            json.dumps(info.to_dict(), indent=2, ensure_ascii=False) + "\n",
            role="La ficha de la copia",
        )
        logger.info("Copia importada: %s", destination)
        return info

    def rename_backup(self, server_id: str, backup_path: str | Path, label: str) -> BackupInfo:
        """Cambia la etiqueta de una copia sin tocar el archivo comprimido.

        El nombre del fichero se queda igual (es el que usan la restauracion y
        las copias de otros equipos); lo que cambia es el nombre que se ve en la
        lista, que vive en la ficha ``.json`` de al lado.
        """
        target = self.backup_path(server_id, backup_path)
        if not target.is_file():
            raise BackupError("La copia de seguridad no existe.")
        clean = " ".join(str(label or "").split())
        if len(clean) > MAX_LABEL_LENGTH:
            raise ValidationError(
                "label",
                f"El nombre de la copia no puede superar {MAX_LABEL_LENGTH} caracteres.",
            )
        meta_file = self._metadata_path(target)
        meta: dict = {}
        if meta_file.is_file():
            try:
                loaded = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta = loaded
            except (OSError, json.JSONDecodeError):
                meta = {}
        stat = target.stat()
        meta.update(
            {
                "filename": target.name,
                "path": str(target),
                "size_bytes": stat.st_size,
                "label": clean,
            }
        )
        meta.setdefault(
            "created_at",
            datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        )
        meta.setdefault("origin", "manual")
        meta.setdefault("app_version", _app_version())
        atomic_write_text(
            meta_file,
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            role="La ficha de la copia",
        )
        logger.info("Copia %s renombrada a «%s»", target.name, clean)
        for info in self.list_backups(server_id):
            if info.filename == target.name:
                return info
        return BackupInfo(
            filename=target.name,
            path=str(target),
            size_bytes=stat.st_size,
            created_at=meta["created_at"],
            label=clean,
            origin=meta["origin"],
            app_version=meta["app_version"],
        )

    # ------------------------------------------------------------- restaurar
    def restore_backup(
        self,
        server_id: str,
        backup_path: str | Path,
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Restaura una copia sobre la carpeta ``data`` del servidor.

        El contenido actual se mueve temporalmente a un directorio provisional y
        solo se elimina si la extraccion termina bien; si algo falla, se
        restaura el contenido anterior.
        """
        archive_path = self.backup_path(server_id, backup_path)
        if not archive_path.is_file():
            raise BackupError("La copia de seguridad no existe.")

        data_dir = self.store.data_dir(server_id)
        data_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="serviscraft-restore-", dir=str(self.store.backups_dir(server_id))))
        current = staging / "anterior"

        try:
            if any(data_dir.iterdir()):
                data_dir.rename(current)
                data_dir.mkdir(parents=True, exist_ok=True)
            self._extract(archive_path, data_dir, on_progress=on_progress)
        except Exception as exc:
            # Reversion: devolvemos el contenido original.
            logger.exception("Fallo al restaurar la copia; revirtiendo")
            if current.exists():
                remove_tree(data_dir)
                current.rename(data_dir)
            shutil.rmtree(staging, ignore_errors=True)
            raise BackupError(f"No se pudo restaurar la copia: {exc}") from exc

        shutil.rmtree(staging, ignore_errors=True)
        logger.info("Copia %s restaurada en %s", archive_path.name, server_id)

    def _extract(
        self,
        archive_path: Path,
        destination: Path,
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Extrae el archivo comprobando cada entrada."""
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                members = archive.getmembers()
                if len(members) > MAX_ARCHIVE_MEMBERS:
                    raise BackupError(
                        "La copia contiene demasiados ficheros; no se extrae por seguridad."
                    )
                total = sum(max(0, member.size) for member in members if member.isfile())
                libre = _free_bytes(destination)
                if total > libre:
                    raise BackupError(
                        "La copia ocuparia mas espacio del disponible en el disco."
                    )
                done = 0
                for member in members:
                    # Defensa en profundidad frente a rutas maliciosas.
                    if member.name.startswith(("/", "\\")) or ".." in Path(member.name).parts:
                        raise BackupError(f"La copia contiene una ruta no permitida: {member.name}")
                    if member.issym() or member.islnk() or member.isdev():
                        continue
                    try:
                        archive.extract(member, path=destination, filter="data")
                    except TypeError:  # pragma: no cover - Python < 3.12
                        archive.extract(member, path=destination)
                    done += max(0, member.size)
                    if on_progress is not None:
                        on_progress(done, total)
        except (OSError, tarfile.TarError) as exc:
            raise BackupError(f"La copia esta danada o no es valida: {exc}") from exc

    # --------------------------------------------------------------- borrar
    def delete_backup(self, server_id: str, backup_path: str | Path) -> None:
        target = self.backup_path(server_id, backup_path)
        if not target.is_file():
            raise BackupError("La copia de seguridad no existe.")
        target.unlink()
        self._metadata_path(target).unlink(missing_ok=True)
        logger.info("Copia eliminada: %s", target.name)

    def prune(self, server_id: str, *, keep: int, origins: tuple[str, ...] | None = None) -> int:
        """Conserva solo las ``keep`` copias mas recientes. Devuelve cuantas borro.

        ``origins`` limita la limpieza a las copias de esos origenes: es lo que
        usa la retencion automatica para no tocar nunca las copias manuales.
        ``keep=0`` significa «sin limite» y no borra nada.
        """
        if keep < 0:
            raise ValidationError("keep", "El numero de copias a conservar no es valido.")
        items = self.list_backups(server_id)
        if origins is not None:
            allowed = set(origins)
            items = [info for info in items if info.origin in allowed]
        if keep == 0:
            return 0
        removed = 0
        for info in items[keep:]:
            self.delete_backup(server_id, info.path)
            removed += 1
        return removed

    # ------------------------------------------------------------ utilidades
    @staticmethod
    def _iter_files(root: Path) -> list[Path]:
        files: list[Path] = []
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not Path(current, d).is_symlink()]
            for name in names:
                path = Path(current) / name
                if path.is_symlink() or not path.is_file():
                    continue
                files.append(path)
        return files

    @classmethod
    def _total_bytes(cls, root: Path) -> int:
        return sum(p.stat().st_size for p in cls._iter_files(root) if p.exists())

    @staticmethod
    def _check_free_space(data_dir: Path) -> None:
        """Avisa si no hay espacio suficiente para la copia comprimida."""
        try:
            usage = shutil.disk_usage(data_dir)
        except OSError:  # pragma: no cover
            return
        needed = BackupManager._total_bytes(data_dir)
        if usage.free < needed + FREE_SPACE_MARGIN:
            raise BackupError(
                "No hay espacio libre suficiente para crear la copia de seguridad "
                f"(se necesitan al menos {format_bytes(needed)})."
            )


def _app_version() -> str:
    from . import paths

    return paths.APP_VERSION
