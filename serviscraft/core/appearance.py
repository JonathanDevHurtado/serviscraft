"""Aspecto del servidor: el icono y la descripcion de la lista de servidores.

Cuando alguien abre Minecraft y mira la lista de servidores ve, por cada uno, dos
cosas que lo distinguen de los demas:

* un **icono** de 64x64 pixeles (``server-icon.png``, dentro de la carpeta de
  datos del servidor);
* un **mensaje del dia** (``motd`` en ``server.properties``) de hasta dos lineas
  que admite **codigos de color** (el caracter de seccion ``§``, tambien escrito
  como ``\\u00a7`` dentro del fichero, porque Java lee las propiedades en
  ISO-8859-1).

Este modulo concentra las dos cosas: validar el texto con colores, traducirlo a
lo que espera el fichero de propiedades y guardar el icono sin seguir enlaces
simbolicos. No depende de Qt, de modo que se puede probar sin ventana.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, replace
from pathlib import Path

from .logging_setup import get_logger
from .validation import ValidationError, atomic_write_bytes, read_bytes_inside

logger = get_logger("appearance")

#: Caracter de seccion: el que usa Minecraft para los codigos de color.
SECTION = "\u00a7"
#: Forma escrita en ``server.properties`` (Java lee el fichero en ISO-8859-1).
SECTION_ESCAPE = "\\u00a7"
#: Alternativa amable que escribe mucha gente (``&a``) y que aqui se acepta.
ALT_CODE = "&"

#: Nombre del fichero que lee Minecraft para el icono de la lista.
ICON_NAME = "server-icon.png"
#: Tamano exacto que espera Minecraft.
ICON_SIZE = 64
#: Tope del fichero del icono (un PNG de 64x64 nunca se acerca).
MAX_ICON_BYTES = 64 * 1024
#: Firma de un PNG.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: Lineas que muestra la lista de Minecraft.
MAX_LINES = 2
#: Caracteres utiles por linea que caben sin que el juego las corte.
MAX_LINE_LENGTH = 45
#: Tope absoluto de texto utiles, sumando las dos lineas.
MAX_LENGTH = 90

#: Los 16 colores de Minecraft, de mas oscuro a mas claro, tal y como los pinta
#: el juego. El nombre va en espanol para los botones de la paleta.
COLORS: dict[str, tuple[str, str]] = {
    "0": ("Negro", "#000000"),
    "1": ("Azul oscuro", "#0000aa"),
    "2": ("Verde oscuro", "#00aa00"),
    "3": ("Turquesa", "#00aaaa"),
    "4": ("Rojo oscuro", "#aa0000"),
    "5": ("Morado", "#aa00aa"),
    "6": ("Dorado", "#ffaa00"),
    "7": ("Gris", "#aaaaaa"),
    "8": ("Gris oscuro", "#555555"),
    "9": ("Azul", "#5555ff"),
    "a": ("Verde", "#55ff55"),
    "b": ("Cian", "#55ffff"),
    "c": ("Rojo", "#ff5555"),
    "d": ("Rosa", "#ff55ff"),
    "e": ("Amarillo", "#ffff55"),
    "f": ("Blanco", "#ffffff"),
}

#: Codigos que no son color: negrita, cursiva, subrayado, tachado, oculto y
#: volver al estilo normal.
FORMATS: dict[str, str] = {
    "l": "Negrita",
    "o": "Cursiva",
    "n": "Subrayado",
    "m": "Tachado",
    "k": "Oculto",
    "r": "Normal",
}

#: Cualquier codigo valido: color o formato.
VALID_CODES = frozenset(COLORS) | frozenset(FORMATS)
#: Color por defecto del texto de la lista de servidores (blanco).
DEFAULT_COLOR = COLORS["f"][1]

#: Codigos que hay que quitar para ver el texto "limpio".
_CODE_RE = re.compile(f"{re.escape(SECTION)}[0-9a-fk-orA-FK-OR]")
#: Escapes que entiende ``java.util.Properties``.
_ESCAPE_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|n|t|r|\\)")
#: Un caracter valido de un codigo de color.
_CODE_CHARS = "0123456789abcdefklmnorABCDEFKLMNOR"


@dataclass(frozen=True)
class Segment:
    """Trozo de texto con el estilo que le toca (para pintar la vista previa)."""

    text: str
    color: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    obfuscated: bool = False

    @property
    def shown(self) -> str:
        """Texto legible: si el tramo va oculto se sustituye por puntos."""
        return "•" * len(self.text) if self.obfuscated else self.text


# --------------------------------------------------------------------- texto
def normalize(text: str) -> str:
    """Deja el texto en la forma interna: ``§`` y saltos de linea reales.

    Se acepta lo que escribe la gente a mano (``&a`` para el color verde,
    ``\\u00a7`` pegado de un manual, ``\\n`` para separar las dos lineas) y lo
    que devuelve el fichero de propiedades.
    """
    value = str(text or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # Escapes de ``server.properties`` primero: ``\n`` es un salto de linea.
    value = _ESCAPE_RE.sub(_unescape, value)
    # ``&`` solo cuenta como codigo si le sigue un codigo de verdad.
    value = re.sub(
        f"{re.escape(ALT_CODE)}([{_CODE_CHARS}])",
        lambda match: f"{SECTION}{match.group(1)}",
        value,
    )
    # Un ``§`` suelto sin codigo valido detras solo ensucia el texto.
    value = re.sub(f"{re.escape(SECTION)}(?![{_CODE_CHARS}])", "", value)
    return value


def _unescape(match: re.Match[str]) -> str:
    token = match.group(1)
    if token.startswith(("u", "U")):
        try:
            return chr(int(token[1:], 16))
        except ValueError:  # pragma: no cover - la expresion regular lo impide
            return match.group(0)
    return {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(token, match.group(0))


def strip_codes(text: str) -> str:
    """Texto sin codigos de color (para contadores y busquedas)."""
    return _CODE_RE.sub("", normalize(text))


def split_lines(text: str, *, max_lines: int | None = None) -> list[str]:
    """Lineas del mensaje (vacio cuando no hay texto)."""
    value = normalize(text)
    if not value:
        return [""]
    lines = value.split("\n")
    if max_lines is not None:
        lines = lines[:max_lines]
    return lines


def useful_lines(text: str, *, max_lines: int | None = None) -> list[str]:
    """Lineas que cuentan: sin saltos de linea vacios por delante o por detras.

    El editor puede dejar un salto de mas (al pegar, por ejemplo) y eso no es
    una tercera linea: el mensaje se guarda sin esos saltos sobrantes.
    """
    value = normalize(text).strip("\n")
    lines = value.split("\n") if value else [""]
    if max_lines is not None:
        lines = lines[:max_lines]
    return lines


def validate_text(text: str) -> str:
    """Comprueba el mensaje del dia y lo devuelve normalizado.

    Se admiten dos lineas de hasta :data:`MAX_LINE_LENGTH` caracteres utiles
    (los codigos de color no cuentan). Mas de eso no se ve en la lista: el juego
    lo corta, asi que es mejor avisar antes que dejar trabajo a medias.
    """
    value = normalize(text).strip("\n")
    if "\t" in value:
        raise ValidationError("motd", "El mensaje no puede llevar tabuladores.")
    lines = useful_lines(value)
    if len(lines) > MAX_LINES:
        raise ValidationError(
            "motd",
            f"El mensaje puede tener como mucho {MAX_LINES} lineas y tiene {len(lines)}.",
        )
    for numero, line in enumerate(lines, start=1):
        visible = strip_codes(line)
        if len(visible) > MAX_LINE_LENGTH:
            raise ValidationError(
                "motd",
                f"La linea {numero} tiene {len(visible)} caracteres y el maximo es "
                f"{MAX_LINE_LENGTH}.",
            )
    total = len(strip_codes(value))
    if total > MAX_LENGTH:
        raise ValidationError(
            "motd", f"El mensaje es demasiado largo ({total} caracteres, maximo {MAX_LENGTH})."
        )
    return "\n".join(lines)


def parse(text: str) -> list[list[Segment]]:
    """Divide el mensaje en lineas y tramos con su color y su estilo.

    Es lo que necesita la vista previa (y lo que hace el propio juego): cada
    codigo de color cambia el estilo de todo lo que viene despues, hasta el
    siguiente codigo.
    """
    lines: list[list[Segment]] = []
    for line in useful_lines(text, max_lines=MAX_LINES):
        segments: list[Segment] = []
        style = Segment(text="")
        buffer: list[str] = []
        index = 0
        while index < len(line):
            char = line[index]
            if char == SECTION and index + 1 < len(line):
                code = line[index + 1].lower()
                if code in VALID_CODES:
                    if buffer:
                        segments.append(replace(style, text="".join(buffer)))
                        buffer = []
                    style = _apply_code(style, code)
                    index += 2
                    continue
                index += 1
                continue
            buffer.append(char)
            index += 1
        if buffer:
            segments.append(replace(style, text="".join(buffer)))
        lines.append([s for s in segments if s.text])
    return lines


def _apply_code(style: Segment, code: str) -> Segment:
    """Aplica un codigo al estilo actual (como hace Minecraft)."""
    if code in COLORS:
        # Un color nuevo borra los formatos: en Minecraft, ``§a`` y despues ``§l``
        # es verde en negrita, pero ``§l§a`` es verde y sin negrita.
        return Segment(text="", color=COLORS[code][1])
    if code == "r":
        return Segment(text="")
    if code == "l":
        return replace(style, bold=True)
    if code == "o":
        return replace(style, italic=True)
    if code == "n":
        return replace(style, underline=True)
    if code == "m":
        return replace(style, strike=True)
    if code == "k":
        return replace(style, obfuscated=True)
    return style  # pragma: no cover - ``code`` ya viene filtrado


def to_file_value(text: str) -> str:
    """Texto listo para ``server.properties`` (una linea, con escapes de Java)."""
    value = normalize(text).strip("\n") if text else ""
    lines = value.split("\n") if value else [""]
    return "\\n".join(_escape(line) for line in lines)


def from_file_value(value: str) -> str:
    """Texto de ``server.properties`` en la forma interna (con ``§`` y saltos)."""
    return normalize(value) if value else ""


def _escape(line: str) -> str:
    # Primero la barra invertida: si no, se escaparian los escapes recien puestos.
    return line.replace("\\", "\\\\").replace(SECTION, SECTION_ESCAPE)


def describe(text: str) -> str:
    """Resumen en una linea para las fichas del servidor (sin colores)."""
    parts = [line for line in useful_lines(text, max_lines=MAX_LINES) if line.strip()]
    return " / ".join(strip_codes(line).strip() for line in parts)


# ------------------------------------------------------------------- propiedades
def motd_of(props) -> str:
    """Mensaje del dia guardado en un :class:`ServerProperties`."""
    return from_file_value(props.get("motd", ""))


def apply_motd(props, text: str) -> str:
    """Guarda el mensaje normalizado en las propiedades y lo devuelve."""
    value = validate_text(text)
    props.set("motd", to_file_value(value))
    return value


# ------------------------------------------------------------------------ icono
def icon_file(data_dir: Path) -> Path:
    """Ruta del icono dentro de la carpeta de datos del servidor."""
    return Path(data_dir) / ICON_NAME


def read_icon(data_dir: Path) -> bytes:
    """Bytes del icono del servidor (vacio si no tiene uno propio)."""
    path = icon_file(data_dir)
    if not path.is_file():
        return b""
    try:
        return read_bytes_inside(path, Path(data_dir), limit=MAX_ICON_BYTES)
    except ValidationError as exc:
        logger.warning("Icono del servidor ignorado: %s", exc)
        return b""


def png_size(data: bytes) -> tuple[int, int]:
    """Anchura y altura de un PNG leyendo su cabecera."""
    if len(data) < 24 or data[:8] != PNG_MAGIC:
        raise ValidationError("icono", "El fichero no es una imagen PNG valida.")
    if data[12:16] != b"IHDR":
        raise ValidationError("icono", "El PNG no tiene cabecera de imagen (IHDR).")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def validate_icon(data: bytes, *, expected: int = ICON_SIZE) -> bytes:
    """Comprueba que el icono es un PNG cuadrado del tamano que lee Minecraft."""
    if not data:
        raise ValidationError("icono", "No se ha elegido ninguna imagen.")
    if len(data) > MAX_ICON_BYTES:
        raise ValidationError(
            "icono",
            f"La imagen ocupa {len(data) // 1024} KiB y el maximo es {MAX_ICON_BYTES // 1024} KiB.",
        )
    width, height = png_size(data)
    if width != height:
        raise ValidationError(
            "icono", f"La imagen tiene que ser cuadrada (esta es de {width}x{height})."
        )
    if width != expected:
        raise ValidationError(
            "icono", f"La imagen tiene que medir {expected}x{expected} (esta mide {width}x{height})."
        )
    return data


def save_icon(data_dir: Path, data: bytes) -> Path:
    """Guarda el icono ya validado en la carpeta de datos del servidor."""
    validate_icon(data)
    target = atomic_write_bytes(icon_file(data_dir), data, role="El icono del servidor")
    logger.info("Icono del servidor guardado en %s", target)
    return target


def remove_icon(data_dir: Path) -> bool:
    """Quita el icono del servidor (el juego vuelve al icono generico)."""
    path = icon_file(data_dir)
    if not path.exists():
        return False
    try:
        if path.is_symlink():
            raise ValidationError(
                "icono", "El icono es un enlace simbolico; no se borra por seguridad."
            )
        path.unlink()
    except ValidationError:
        raise
    except OSError as exc:  # pragma: no cover - permisos
        raise ValidationError("icono", f"No se pudo quitar el icono: {exc}") from exc
    logger.info("Icono del servidor eliminado: %s", path)
    return True


__all__ = [
    "ALT_CODE",
    "COLORS",
    "DEFAULT_COLOR",
    "FORMATS",
    "ICON_NAME",
    "ICON_SIZE",
    "MAX_ICON_BYTES",
    "MAX_LENGTH",
    "MAX_LINES",
    "MAX_LINE_LENGTH",
    "SECTION",
    "Segment",
    "apply_motd",
    "describe",
    "from_file_value",
    "icon_file",
    "motd_of",
    "normalize",
    "parse",
    "png_size",
    "read_icon",
    "remove_icon",
    "save_icon",
    "split_lines",
    "strip_codes",
    "to_file_value",
    "useful_lines",
    "validate_icon",
    "validate_text",
]
