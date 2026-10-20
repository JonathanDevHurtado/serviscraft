"""Ajustes de Geyser/Floodgate para que entren jugadores de Bedrock.

La imagen ``itzg/minecraft-server`` descarga los dos pluguins oficiales cuando se
le pasa la variable ``PLUGINS`` (lo hacen ``ServerSpec.plugins_env`` y el gestor).
Geyser genera su ``config.yml`` la primera vez que el servidor arranca, y por
defecto pide autenticacion ``online``: eso obligaria a los jugadores de Bedrock a
tener tambien cuenta de Java. Con Floodgate instalado basta con poner
``auth-type: floodgate`` para que entren sin cuenta de Java.

Como el fichero no existe hasta el primer arranque, este modulo solo retoca la
linea concreta cuando ya esta generado (nunca inventa el fichero entero) y avisa
de que hace falta reiniciar el servidor para que surta efecto.
"""

from __future__ import annotations

import re
from pathlib import Path

from .logging_setup import get_logger
from .validation import ValidationError, atomic_write_text, reject_symlink

logger = get_logger("bedrock")

#: Carpeta de pluguins dentro de ``data``.
PLUGINS_FOLDER = "plugins"
#: Nombre con el que Geyser genera su carpeta y su configuracion.
GEYSER_FOLDER = "Geyser-Spigot"
#: Nombre del fichero de Floodgate (sirve para saber si esta instalado).
FLOODGATE_JAR = "floodgate-spigot.jar"

#: Linea ``auth-type: <valor>`` del config.yml de Geyser.
_AUTH_TYPE = re.compile(r"^(\s*)auth-type\s*:\s*(?P<valor>[^\s#]+)", re.MULTILINE)


def geyser_config_path(data_dir: Path) -> Path:
    """Ruta del ``config.yml`` que genera Geyser (puede no existir todavia)."""
    return Path(data_dir) / PLUGINS_FOLDER / GEYSER_FOLDER / "config.yml"


def floodgate_installed(data_dir: Path) -> bool:
    """Hay Floodgate descargado en la carpeta de pluguins?"""
    return (Path(data_dir) / PLUGINS_FOLDER / FLOODGATE_JAR).is_file()


def needs_floodgate_auth(data_dir: Path) -> bool:
    """True si el config.yml generado no esta en modo Floodgate."""
    path = geyser_config_path(data_dir)
    try:
        texto = reject_symlink(path, role="El config de Geyser").read_text(encoding="utf-8")
    except (OSError, ValidationError):
        return False
    match = _AUTH_TYPE.search(texto)
    return bool(match) and match.group("valor") != "floodgate"


def ensure_floodgate_auth(data_dir: Path) -> bool:
    """Pone ``auth-type: floodgate`` en el config.yml de Geyser.

    Devuelve ``True`` solo si ha cambiado algo (y por tanto hay que reiniciar el
    servidor para aplicarlo). Si el fichero aun no existe no hace nada: se
    revisara en el siguiente arranque.
    """
    path = geyser_config_path(data_dir)
    try:
        texto = reject_symlink(path, role="El config de Geyser").read_text(encoding="utf-8")
    except (OSError, ValidationError):
        return False
    match = _AUTH_TYPE.search(texto)
    if match is None or match.group("valor") == "floodgate":
        return False
    nuevo = _AUTH_TYPE.sub(
        lambda m: f"{m.group(1)}auth-type: floodgate",
        texto,
        count=1,
    )
    try:
        atomic_write_text(path, nuevo, role="El config de Geyser")
    except (OSError, ValidationError) as exc:  # pragma: no cover - permisos del sistema
        logger.warning("No se pudo ajustar el config de Geyser: %s", exc)
        return False
    logger.info("Geyser configurado con auth-type=floodgate en %s", path)
    return True


__all__ = [
    "GEYSER_FOLDER",
    "PLUGINS_FOLDER",
    "ensure_floodgate_auth",
    "floodgate_installed",
    "geyser_config_path",
    "needs_floodgate_auth",
]
