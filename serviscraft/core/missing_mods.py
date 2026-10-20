"""Deteccion de mods que faltan leyendo el registro del servidor.

Cuando un modpack no puede descargar un mod (porque el proyecto ya no existe,
porque el fichero se borro o porque falla la red), el servidor arranca pero los
mods que lo necesitan se quejan en el registro: Fabric y Forge dicen «Missing or
unsupported mandatory dependencies» y el instalador de modpacks deja lineas de
«Failed to download». Aqui se extraen esos nombres y enlaces para poder
ofrecer al usuario el enlace de Modrinth, comprobar si el fichero ya esta y
copiarlo dentro del servidor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

#: Enlaces de proyecto de Modrinth (``/mod/<slug>``, ``/project/<id>``...).
_URL_PROYECTO = re.compile(
    r"https?://(?:www\.)?modrinth\.com/(?:mod|plugin|datapack|modpack|project|shader|resourcepack)"
    r"/(?P<nombre>[A-Za-z0-9_!.+,\-]+)",
    re.IGNORECASE,
)
#: Enlaces al CDN: ``cdn.modrinth.com/data/<id-del-proyecto>/...``.
_URL_CDN = re.compile(r"https?://cdn\.modrinth\.com/data/(?P<id>[A-Za-z0-9]+)(?:/[^\s\"'<>]*)?", re.I)
#: Palabras que indican que algo fue mal en esa linea.
_FALLO = re.compile(
    r"fail|error|could ?n[o']?t|could not|unable|missing|not found|404|denied|no such file|"
    r"no se pudo|fall[oó]",
    re.IGNORECASE,
)
#: Cabecera del bloque de dependencias obligatorias de Fabric y Forge.
_CABECERA_DEPENDENCIAS = re.compile(
    r"missing or unsupported mandatory dependenc|incompatible mods found|"
    r"missing requirements|mod resolution failed",
    re.IGNORECASE,
)
#: Linea con el identificador del mod dentro del bloque anterior.
_MOD_ID = re.compile(r"mod id[:\s]+['\"]?(?P<id>[A-Za-z0-9_.\-]+)", re.IGNORECASE)
#: Frases del instalador o del cargador que traen el nombre detras.
_FRASE_FALTANTE = re.compile(
    r"(?:failed to (?:download|install|fetch)|unable to download|could not download|"
    r"no se pudo descargar|missing (?:required )?mod(?:s)?(?: file)?|mod file missing)"
    r"[\s:]+(?:the\s+|el\s+|la\s+)?(?:mod\s+|mods\s+)?[\"']?(?P<nombre>[^\"'\n]{2,90})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MissingMod:
    """Un mod del que el registro dice que falta."""

    name: str
    url: str = ""
    detail: str = ""

    @property
    def search_url(self) -> str:
        """Busqueda del mod en Modrinth (cuando no se conoce su enlace directo)."""
        return f"https://modrinth.com/mods?q={quote_plus(self.name)}"

    @property
    def link(self) -> str:
        return self.url or self.search_url


def _limpiar_nombre(valor: str) -> str:
    """Quita restos de la linea de registro alrededor del nombre."""
    nombre = valor.strip().strip("'\".,;:!()[]")
    # Un fichero descargado: se queda el nombre sin extension.
    for suffix in (".jar", ".zip", ".mrpack"):
        if nombre.lower().endswith(suffix):
            nombre = nombre[: -len(suffix)]
            break
    # Restos tipicos: «create-1.20.1» deja el identificador util.
    nombre = re.sub(r"\s+(?:from|at|in|on)\s+https?://\S+$", "", nombre, flags=re.IGNORECASE)
    return nombre.strip()


def _clave(nombre: str) -> str:
    return "".join(ch for ch in nombre.lower() if ch.isalnum())


def parse_missing_mods(text: str) -> list[MissingMod]:
    """Extrae del registro los mods que faltan o no se pudieron descargar."""
    encontrados: dict[str, MissingMod] = {}

    def anotar(nombre: str, *, url: str = "", detalle: str = "") -> None:
        limpio = _limpiar_nombre(nombre)
        clave = _clave(limpio)
        if len(clave) < 2:
            return
        # Una direccion no es un nombre de mod: de eso se encargan los enlaces.
        if limpio.lower().startswith(("http://", "https://")):
            return
        # Se ignoran los mensajes genéricos sin nombre de mod.
        if clave in {"the", "mod", "mods", "dependencies", "dependency", "null", "unknown"}:
            return
        anterior = encontrados.get(clave)
        if anterior is None:
            encontrados[clave] = MissingMod(name=limpio, url=url, detail=detalle.strip())
        elif url and not anterior.url:
            encontrados[clave] = MissingMod(name=anterior.name, url=url, detail=anterior.detail)

    en_bloque = False
    for linea in text.splitlines():
        if not linea.strip():
            continue
        minuscula = linea.lower()

        if _CABECERA_DEPENDENCIAS.search(linea):
            en_bloque = True
            continue

        if en_bloque:
            coincidencia = _MOD_ID.search(linea)
            if coincidencia and ("missing" in minuscula or "requested by" in minuscula):
                anotar(coincidencia.group("id"), detalle=linea)
                continue
            if not re.search(r"mod id|requested by|actual version|expected range", linea, re.I):
                en_bloque = False

        for coincidencia in _URL_PROYECTO.finditer(linea):
            if _FALLO.search(linea):
                anotar(coincidencia.group("nombre"), url=coincidencia.group(0), detalle=linea)

        for coincidencia in _URL_CDN.finditer(linea):
            if _FALLO.search(linea):
                proyecto = coincidencia.group("id")
                anotar(proyecto, url=f"https://modrinth.com/project/{proyecto}", detalle=linea)

        for coincidencia in _FRASE_FALTANTE.finditer(linea):
            nombre = _limpiar_nombre(coincidencia.group("nombre"))
            # El resto de la frase puede traer la version o el motivo: se corta
            # en el primer separador claro.
            nombre = re.split(r"\s+(?:is|was|due|cause|reason|because)\s+", nombre, maxsplit=1)[0]
            anotar(nombre, detalle=linea)

    return list(encontrados.values())
