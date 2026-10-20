"""Consulta de versiones de Minecraft disponibles.

Se usa la lista oficial de versiones de Mojang (launchermeta). Es opcional: si
no hay conexion, el usuario puede escribir la version a mano.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .logging_setup import get_logger
from .paths import DEFAULT_JAVA_TAG, JAVA_TAGS

logger = get_logger("versions")

VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
_TIMEOUT = 12

#: Versiones que se ofrecen aunque no haya conexion.
FALLBACK_VERSIONS: tuple[str, ...] = (
    "latest",
    "1.21.4",
    "1.21.3",
    "1.21.1",
    "1.21",
    "1.20.6",
    "1.20.4",
    "1.20.1",
    "1.19.4",
    "1.18.2",
    "1.17.1",
    "1.16.5",
    "1.12.2",
    "1.8.9",
    "1.7.10",
)


@dataclass(frozen=True)
class VersionInfo:
    """Version de Minecraft con su tipo (estable o snapshot)."""

    id: str
    type: str

    @property
    def label(self) -> str:
        return self.id if self.type == "release" else f"{self.id} (snapshot)"


def parse_manifest(payload: str) -> list[VersionInfo]:
    """Extrae las versiones del manifiesto oficial."""
    data = json.loads(payload)
    versions: list[VersionInfo] = []
    for item in data.get("versions", []):
        identifier = str(item.get("id", "")).strip()
        kind = str(item.get("type", "release"))
        if identifier:
            versions.append(VersionInfo(id=identifier, type=kind))
    return versions


def fetch_versions(*, include_snapshots: bool = True, limit: int = 400) -> list[VersionInfo]:
    """Descarga la lista de versiones. Lanza la excepcion si falla la red."""
    request = urllib.request.Request(
        VERSION_MANIFEST_URL,
        headers={"User-Agent": "Serviscraft/0.1 (+podman-manager)"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 - URL fija https
        payload = response.read().decode("utf-8", errors="replace")
    versions = parse_manifest(payload)
    if not include_snapshots:
        versions = [v for v in versions if v.type == "release"]
    logger.info("Obtenidas %d versiones de Minecraft", len(versions))
    return versions[:limit]


def version_choices(versions: list[VersionInfo]) -> list[str]:
    """Lista ordenada para el desplegable, con ``latest`` al principio."""
    ids = [v.id for v in versions]
    if "latest" not in ids:
        ids.insert(0, "latest")
    return ids


def version_sort_key(value: str) -> tuple[int, ...]:
    """Clave para ordenar versiones de Minecraft (``1.21.4`` > ``1.20.6``).

    Las snapshots (``24w14a``) no siguen el esquema numerico: se ordenan por
    debajo de cualquier version con numero para no elegirlas por error.
    """
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", (value or "").strip())
    if match is None:
        return (0,)
    return (1, int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def newest_version(versions: object) -> str:
    """Devuelve la version mas reciente de una lista (o cadena vacia)."""
    candidates = [str(v).strip() for v in versions or () if str(v).strip()]  # type: ignore[union-attr]
    if not candidates:
        return ""
    return max(candidates, key=version_sort_key)


#: Java que exige cada version de Minecraft, de la mas antigua a la mas nueva.
#:
#: Cada entrada es ``(version_minima, java_mayor)`` y se aplica la ultima que
#: cumpla. La lista es la unica fuente de verdad: si Mojang vuelve a subir el
#: requisito, se añade una linea aqui y los servidores antiguos se corrigen
#: solos la proxima vez que se arrancan (sin tocar nunca sus mundos).
JAVA_REQUIREMENTS: tuple[tuple[str, int], ...] = (
    ("1.0", 8),
    ("1.17", 17),
    ("1.20.5", 21),
    ("25.1", 25),
)

#: Java que se usa cuando no se puede deducir de la version (por ejemplo
#: ``latest`` o una version futura que esta aplicacion todavia no conoce).
NEWEST_JAVA_MAJOR = 25


def _version_key(version: str) -> tuple[int, ...] | None:
    """Convierte una version en una tupla comparable (``None`` si no se puede)."""
    cleaned = (version or "").strip().lower()
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", cleaned)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _snapshot_year(version: str) -> int | None:
    """Año de una snapshot con el formato ``24w14a`` (``None`` si no lo es)."""
    match = re.match(r"^(\d{2})w\d{1,2}[a-z]$", (version or "").strip().lower())
    if match is None:
        return None
    return 2000 + int(match.group(1))


def required_java_major(version: str) -> int:
    """Version mayor de Java que necesita Minecraft ``version``.

    Devuelve ``0`` cuando no se puede saber, para que quien llame decida.
    """
    cleaned = (version or "").strip().lower()
    if not cleaned or cleaned == "latest":
        return NEWEST_JAVA_MAJOR

    year = _snapshot_year(cleaned)
    if year is not None:
        # Las snapshots de 2026 en adelante van con el Minecraft nuevo.
        return 25 if year >= 2026 else 21

    key = _version_key(cleaned)
    if key is None:
        return 0

    major = key[0]
    if major >= 25:
        # Versionado por año (26.1, 26.3...): el Minecraft nuevo pide Java 25.
        return 25
    if major > 1:
        # Version futura que esta aplicacion no conoce: se pide lo mas nuevo.
        return NEWEST_JAVA_MAJOR

    elegido = 8
    for minimo, java_mayor in JAVA_REQUIREMENTS:
        minimo_key = _version_key(minimo)
        if minimo_key is not None and key >= minimo_key:
            elegido = java_mayor
    return elegido


def java_tag_for_major(major: int) -> str:
    """Etiqueta de imagen disponible que cubre una version de Java.

    Se elige la etiqueta mas pequeña que sea igual o superior a la pedida: asi
    un servidor que necesita Java 25 no acaba en una imagen ``java21``.
    """
    disponibles = sorted(
        (int(tag[4:]), tag) for tag in JAVA_TAGS if re.match(r"^java\d+$", tag)
    )
    if not disponibles:
        return DEFAULT_JAVA_TAG  # pragma: no cover - paths siempre define etiquetas
    if major <= 0:
        return disponibles[-1][1]
    for numero, tag in disponibles:
        if numero >= major:
            return tag
    # Pide mas Java del que ofrecemos: se usa la mas nueva disponible.
    return disponibles[-1][1]


def java_major_of_tag(tag: str) -> int:
    """Numero de Java de una etiqueta (``0`` si no se puede deducir)."""
    match = re.search(r"java(\d+)", str(tag or ""))
    return int(match.group(1)) if match else 0


def recommended_java_tag(version: str) -> str:
    """Etiqueta de Java recomendada para una version de Minecraft.

    La imagen ``itzg/minecraft-server`` elige la version del juego segun
    ``VERSION``; el usuario (o la aplicacion) solo tiene que acertar con Java:

    * Versionado por año (26.1, 26.3...) y ``latest``: Java 25.
    * 1.20.5 a 1.21.x: Java 21.
    * 1.17 a 1.20.4: Java 17.
    * 1.16.5 y anteriores: Java 8.
    """
    return java_tag_for_major(required_java_major(version))
