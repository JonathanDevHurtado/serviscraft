"""Registro de errores de Serviscraft.

Escribe en ``$XDG_DATA_HOME/serviscraft/logs/serviscraft.log`` con rotacion y
tambien en la salida de error (util al ejecutar desde terminal o como AppImage).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import traceback
from collections.abc import Callable
from types import TracebackType

from . import paths

LOGGER_NAME = "serviscraft"
_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False

#: Datos que nunca deben acabar en un registro ni en una traza: contrasenas de
#: consola, tokens de DDNS y variables de entorno sensibles pasan por aqui.
_SECRET_PATTERNS = (
    re.compile(r"(?i)(rcon[._-]?password\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(password\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(token\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(authorization\s*[=:]\s*)\S+"),
)


def redact(text: str) -> str:
    """Sustituye contrasenas y tokens por ``***`` antes de registrarlos."""
    limpio = str(text)
    for patron in _SECRET_PATTERNS:
        limpio = patron.sub(lambda m: f"{m.group(1)}***", limpio)
    return limpio


class _RedactingFormatter(logging.Formatter):
    """Formateador que depura contrasenas y tokens de todo lo que se escribe.

    Se redacta el texto **ya formateado** para cubrir tambien los argumentos
    (``logger.info("clave=%s", clave)``) y las trazas de excepcion.
    """

    def format(self, record: logging.LogRecord) -> str:
        try:
            return redact(super().format(record))
        except Exception:  # pragma: no cover - nunca debe romper el registro
            return f"{record.levelname} [registro no disponible]"


def setup_logging(*, debug: bool | None = None, console: bool = True) -> logging.Logger:
    """Configura el registro once-only y devuelve el logger principal."""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)

    if _configured:
        return logger

    if debug is None:
        debug = os.environ.get("SERVISCRAFT_DEBUG", "").strip() not in {"", "0", "false", "no"}

    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    formatter = _RedactingFormatter(_FORMAT, datefmt=_DATE_FORMAT)

    try:
        paths.ensure_base_dirs()
        log_path = paths.log_file()
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        logger.addHandler(file_handler)
        try:
            os.chmod(log_path, 0o600)
        except OSError:  # pragma: no cover - sistemas sin permisos POSIX
            pass
    except OSError as exc:  # pragma: no cover - depende del sistema de ficheros
        print(f"Aviso: no se pudo abrir el fichero de registro: {exc}", file=sys.stderr)

    if console and os.environ.get("SERVISCRAFT_QUIET", "") in {"", "0", "false", "no"}:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.setLevel(logging.DEBUG if debug else logging.WARNING)
        logger.addHandler(stream)

    _configured = True
    logger.debug("Registro inicializado (debug=%s)", debug)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Devuelve un logger hijo del logger principal."""
    if not _configured:
        setup_logging()
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def install_excepthook(on_error: Callable[[str, str], None] | None = None) -> None:
    """Captura excepciones no controladas: las registra y avisa a la interfaz."""
    logger = get_logger("excepthook")

    def _hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Excepcion no controlada", exc_info=(exc_type, exc_value, exc_tb))
        if on_error is not None:
            summary = "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
            detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            try:
                on_error(summary, detail)
            except Exception:  # pragma: no cover - nunca debe romper el manejador
                logger.exception("Fallo el manejador de errores de la interfaz")

    sys.excepthook = _hook
