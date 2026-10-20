"""Lectura de los registros (logs) de un servidor.

Minecraft escribe ``logs/latest.log`` en cada arranque y guarda los fallos en
``crash-reports``. Cuando el servidor esta en marcha, la consola del contenedor
tiene la salida mas reciente; cuando esta parado, lo que queda en el disco es
el historial util. Aqui se listan esos ficheros y se leen solo los ultimos
bytes, para no cargar en memoria un registro de cientos de megabytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import ServiscraftError
from .validation import ensure_within

#: Como maximo se leen 2 MiB por fichero (suficiente para diagnosticar).
MAX_READ_BYTES = 2 * 1024 * 1024

#: Carpetas del servidor donde se buscan registros.
LOG_FOLDERS = ("logs", "crash-reports")


class LogsError(ServiscraftError):
    """Fallo al leer los registros del servidor."""


@dataclass(frozen=True)
class LogFile:
    """Un fichero de registro disponible."""

    name: str
    relative_path: str
    size_bytes: int
    modified: float

    @property
    def size_label(self) -> str:
        from .models import format_bytes

        return format_bytes(self.size_bytes)


def list_logs(files) -> list[LogFile]:
    """Registros del servidor, los mas recientes primero.

    ``files`` es un ``ServerFiles`` (duck typing para poder probarlo sin disco).
    """
    data_dir = Path(files.data_dir)
    encontrados: list[LogFile] = []
    for folder in LOG_FOLDERS:
        base = data_dir / folder
        if not base.is_dir():
            continue
        try:
            items = list(base.iterdir())
        except OSError:  # pragma: no cover - carpeta ilegible
            continue
        for item in items:
            if not item.is_file() or item.suffix.lower() not in {".log", ".txt", ".gz"}:
                continue
            try:
                stat = item.stat()
            except OSError:  # pragma: no cover
                continue
            encontrados.append(
                LogFile(
                    name=item.name,
                    relative_path=f"{folder}/{item.name}",
                    size_bytes=stat.st_size,
                    modified=stat.st_mtime,
                )
            )
    encontrados.sort(key=lambda log: (log.modified, log.name), reverse=True)
    return encontrados


def read_log(files, relative_path: str, *, max_bytes: int = MAX_READ_BYTES) -> str:
    """Lee el final de un registro, validando que esta dentro del servidor."""
    data_dir = Path(files.data_dir)
    limpio = str(relative_path or "").strip().replace("\\", "/")
    if not limpio or limpio.startswith("/") or ".." in limpio.split("/"):
        raise LogsError("Ruta de registro no valida.")
    target = ensure_within(Path(limpio), data_dir)
    if not target.is_file():
        raise LogsError("Ese registro ya no existe.")
    try:
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                # Se descarta la primera linea (puede estar cortada).
                handle.readline()
            raw = handle.read()
    except OSError as exc:
        raise LogsError(f"No se pudo leer el registro: {exc}") from exc
    if target.suffix.lower() == ".gz":
        return "El registro esta comprimido: abrelo con la carpeta de registros."
    if size > max_bytes:
        return f"[... se muestran los ultimos {max_bytes // 1024} KiB ...]\n" + raw.decode(
            "utf-8", errors="replace"
        )
    return raw.decode("utf-8", errors="replace")


def latest_log(files) -> str:
    """Contenido de ``logs/latest.log``, o cadena vacia si no existe."""
    try:
        return read_log(files, "logs/latest.log")
    except LogsError:
        return ""
