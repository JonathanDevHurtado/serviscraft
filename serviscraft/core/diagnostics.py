"""Diagnostico de los fallos de arranque del servidor.

Cuando un servidor se apaga solo a los pocos segundos, el registro del
contenedor suele decir exactamente por que. Este modulo traduce esos mensajes a
una explicacion en castellano y, cuando se puede, a una reparacion automatica
(por ejemplo, subir la etiqueta de Java de la imagen).

Se usa desde el gestor (para comprobar el arranque) y desde la interfaz (para
avisar al usuario en lugar de dejarle con un contenedor muerto sin explicacion).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .paths import DEFAULT_IMAGE
from .versions import java_major_of_tag, java_tag_for_major

#: Papel, Purpur y compania: «requires running the server with Java 25 or above».
_REQUIERE_JAVA = re.compile(
    r"requires(?:\s+running\s+the\s+server\s+with)?\s+Java\s+(\d+)", re.IGNORECASE
)
_JAVA_ABOVE = re.compile(r"Java\s+(\d+)\s+or\s+(?:above|newer|higher)", re.IGNORECASE)
#: Mojang: «UnsupportedClassVersionError ... class file version 69.0».
_CLASS_VERSION = re.compile(r"class file version (\d+)", re.IGNORECASE)

_VERSION_PROBLEMS = (
    re.compile(r"failed to download.*(?:version|jar)", re.IGNORECASE),
    re.compile(r"unknown version", re.IGNORECASE),
    re.compile(r"(?:invalid|unsupported) minecraft version", re.IGNORECASE),
)
_MEMORY_PROBLEMS = (
    re.compile(r"outofmemoryerror", re.IGNORECASE),
    re.compile(r"there is insufficient memory", re.IGNORECASE),
    re.compile(r"could not reserve enough space for object heap", re.IGNORECASE),
)
_PORT_PROBLEMS = (
    re.compile(r"address already in use", re.IGNORECASE),
    re.compile(r"failed to bind to port", re.IGNORECASE),
)

#: Numero de clase de Java para cada version mayor (52 = Java 8, 69 = Java 25).
_CLASS_TO_JAVA = {str(44 + mayor): mayor for mayor in range(8, 40)}

#: Motivo del fallo, para que la interfaz sepa que ofrecer.
KIND_JAVA = "java"
KIND_VERSION = "version"
KIND_MEMORY = "memoria"
KIND_PORT = "puerto"
KIND_UNKNOWN = "desconocido"


@dataclass(frozen=True)
class StartFailure:
    """Explicacion de por que un servidor no llego a arrancar."""

    kind: str
    message: str
    #: Java que pide el servidor, si el fallo es por Java (0 si no aplica).
    java_major: int = 0
    #: Etiqueta de imagen con la que se arreglaria (vacia si no se puede).
    suggested_java_tag: str = ""
    #: Linea del registro que delata el problema (util en el detalle tecnico).
    evidence: str = ""

    @property
    def repairable(self) -> bool:
        return bool(self.suggested_java_tag)


def required_java_from_log(text: str) -> int:
    """Mayor de Java que pide el registro del servidor (``0`` si no lo dice)."""
    for pattern in (_REQUIERE_JAVA, _JAVA_ABOVE):
        match = pattern.search(text or "")
        if match:
            try:
                return int(match.group(1))
            except ValueError:  # pragma: no cover - grupo siempre numerico
                continue
    match = _CLASS_VERSION.search(text or "")
    if match:
        try:
            return _CLASS_TO_JAVA.get(match.group(1), 0)
        except ValueError:  # pragma: no cover
            return 0
    return 0


def _first_line(text: str, patterns) -> str:
    for pattern in patterns:
        for line in (text or "").splitlines():
            if pattern.search(line):
                return line.strip()
    return ""


def diagnose_start_failure(
    log_text: str,
    *,
    version: str,
    java_tag: str,
    image: str = DEFAULT_IMAGE,
) -> StartFailure:
    """Interpreta el registro de un servidor que se apago al arrancar.

    ``version`` y ``java_tag`` son los del servidor, para poder proponer una
    reparacion concreta.
    """
    texto = log_text or ""

    # --- Java demasiado antiguo (el fallo mas habitual tras una actualizacion)
    java = required_java_from_log(texto)
    if java and java_major_of_tag(java_tag) < java:
        linea = _first_line(texto, (_REQUIERE_JAVA, _JAVA_ABOVE, _CLASS_VERSION))
        etiqueta = java_tag_for_major(java) if image == DEFAULT_IMAGE else ""
        if etiqueta and java_major_of_tag(etiqueta) < java:
            etiqueta = ""
        return StartFailure(
            kind=KIND_JAVA,
            message=(
                f"El servidor usa Minecraft {version} y necesita Java {java} o superior, "
                f"pero la imagen configurada usa {java_tag}. "
                + (
                    f"Cambia Java a {etiqueta} y vuelve a iniciarlo: el mundo y el "
                    "contenido no se tocan."
                    if etiqueta
                    else "Actualiza Serviscraft o elige una version de Minecraft mas antigua."
                )
            ),
            java_major=java,
            suggested_java_tag=etiqueta,
            evidence=linea,
        )

    # --- Version de Minecraft inexistente o retirada
    linea = _first_line(texto, _VERSION_PROBLEMS)
    if linea:
        return StartFailure(
            kind=KIND_VERSION,
            message=(
                f"No se pudo preparar Minecraft {version}: la version no existe o ya no "
                "esta disponible para descargar. Elige otra version en «Ajustes del "
                "servidor»; el mundo se conserva."
            ),
            evidence=linea,
        )

    # --- Memoria insuficiente
    linea = _first_line(texto, _MEMORY_PROBLEMS)
    if linea:
        return StartFailure(
            kind=KIND_MEMORY,
            message=(
                "Al servidor no le llega la memoria reservada. Sube la RAM en «Ajustes "
                "del servidor» (los modpacks y Forge necesitan bastante mas)."
            ),
            evidence=linea,
        )

    # --- Puerto ocupado
    linea = _first_line(texto, _PORT_PROBLEMS)
    if linea:
        return StartFailure(
            kind=KIND_PORT,
            message=(
                "El puerto del servidor ya esta ocupado por otro programa. Cierra ese "
                "programa o cambia el puerto en «Ajustes del servidor»."
            ),
            evidence=linea,
        )

    return StartFailure(
        kind=KIND_UNKNOWN,
        message=(
            "El servidor se detuvo nada mas arrancar. Abre la pestana «Registros» para "
            "ver el detalle o pulsa «Buscar mods que faltan» si instalaste mods."
        ),
        evidence="",
    )


__all__ = [
    "KIND_JAVA",
    "KIND_MEMORY",
    "KIND_PORT",
    "KIND_UNKNOWN",
    "KIND_VERSION",
    "StartFailure",
    "diagnose_start_failure",
    "required_java_from_log",
]
