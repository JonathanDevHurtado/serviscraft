"""Busqueda e instalacion de pluguins y mods desde Modrinth.

Modrinth ofrece una API publica y sin clave. Se consulta la lista de proyectos
compatibles con la version de Minecraft del servidor y, al instalar, se descarga
el fichero principal de la version mas reciente compatible comprobando su suma
SHA-512.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .errors import ServiscraftError
from .logging_setup import get_logger
from .models import ServerType
from .versions import version_sort_key

logger = get_logger("modrinth")

API_URL = "https://api.modrinth.com/v2"
USER_AGENT = "Serviscraft/0.1 (+podman-manager)"
_TIMEOUT = 15

PROJECT_TYPE_PLUGIN = "plugin"
PROJECT_TYPE_MOD = "mod"
PROJECT_TYPE_MODPACK = "modpack"

#: Cargadores que entiende cada tipo de servidor.
LOADERS_BY_SERVER_TYPE: dict[ServerType, tuple[str, ...]] = {
    ServerType.PAPER: ("paper", "spigot", "bukkit"),
    ServerType.FABRIC: ("fabric",),
    ServerType.FORGE: ("forge",),
    # Un servidor con modpack de Modrinth usa el cargador que exige el propio
    # pack (se guarda en ``MODRINTH_LOADER``); aqui se admiten todos los
    # posibles para poder buscar mods sueltos.
    ServerType.MODRINTH: ("fabric", "forge", "quilt", "neoforge"),
}

#: Cargadores que la imagen acepta en ``MODRINTH_LOADER``.
MODPACK_LOADERS: tuple[str, ...] = ("fabric", "forge", "quilt")

#: Modrinth devuelve el cargador de un proyecto como si fuera una categoria
#: (``fabric``, ``paper``...). Esta es la lista de los que interesan aqui.
LOADER_CATEGORIES: frozenset[str] = frozenset(
    {
        "bukkit",
        "bungeecord",
        "fabric",
        "folia",
        "forge",
        "neoforge",
        "paper",
        "purpur",
        "quilt",
        "spigot",
        "velocity",
        "waterfall",
    }
)


#: Mods que solo funcionan en el cliente no se pueden instalar en el servidor.
_SERVER_UNSUPPORTED = "unsupported"


class ModrinthError(ServiscraftError):
    """Fallo al consultar o descargar contenido de Modrinth."""


@dataclass(frozen=True)
class Project:
    """Resultado de busqueda de Modrinth."""

    id: str
    slug: str
    title: str
    description: str
    downloads: int
    icon_url: str = ""
    project_type: str = ""
    #: Versiones de Minecraft del proyecto (las que anuncia la busqueda).
    game_versions: tuple[str, ...] = ()
    #: Cargadores compatibles deducidos de las categorias de Modrinth.
    loaders: tuple[str, ...] = ()
    client_side: str = ""
    server_side: str = ""
    #: Fecha ISO de la ultima publicacion (``2025-03-04T12:00:00Z``).
    updated: str = ""
    follows: int = 0
    author: str = ""

    @property
    def page_url(self) -> str:
        return f"https://modrinth.com/{self.project_type or 'project'}/{self.slug}"

    @property
    def works_on_server(self) -> bool:
        """``False`` solo si Modrinth dice que es exclusivo del cliente."""
        return self.server_side != _SERVER_UNSUPPORTED

    @property
    def side_label(self) -> str:
        if not self.server_side:
            return "sin datos"
        return "solo cliente" if not self.works_on_server else "servidor y cliente"

    @property
    def loader_label(self) -> str:
        return ", ".join(self.loaders) if self.loaders else "sin datos"

    @property
    def minecraft_label(self) -> str:
        """Las dos versiones de Minecraft mas nuevas (con el resto contado)."""
        if not self.game_versions:
            return "sin datos"
        ordenadas = sorted(self.game_versions, key=version_sort_key, reverse=True)
        visible = ", ".join(ordenadas[:2])
        if len(ordenadas) > 2:
            visible += f" (+{len(ordenadas) - 2})"
        return visible

    @property
    def updated_label(self) -> str:
        """Fecha legible (``04/03/2025``) a partir del ISO de Modrinth."""
        partes = (self.updated or "").strip()[:10].split("-")
        if len(partes) != 3 or not all(parte.isdigit() for parte in partes):
            return "sin datos"
        anio, mes, dia = partes
        return f"{dia}/{mes}/{anio}"


@dataclass(frozen=True)
class Release:
    """Version concreta de un proyecto, con el fichero que hay que descargar."""

    project_id: str
    name: str
    version_number: str
    game_versions: tuple[str, ...]
    loaders: tuple[str, ...]
    download_url: str
    filename: str
    size: int = 0
    sha512: str | None = None
    dependencies: tuple[str, ...] = ()
    #: Identificador interno de la version (lo usa ``MODRINTH_VERSION``).
    version_id: str = ""
    #: ``release``, ``beta`` o ``alpha``.
    version_type: str = ""


def loaders_for_spec(spec) -> tuple[str, ...]:
    """Cargadores validos para un servidor concreto.

    Un servidor con modpack usa el cargador que exige el pack: se guarda en
    ``MODRINTH_LOADER`` al crearlo, asi que se respeta esa eleccion.
    """
    if getattr(spec, "type", None) is ServerType.MODRINTH:
        selected = str((spec.extra_env or {}).get("MODRINTH_LOADER") or "").strip().lower()
        if selected:
            return (selected,)
    return loaders_for(spec.type)



def project_type_for(spec) -> str | None:
    """Tipo de proyecto de Modrinth que corresponde a un servidor."""
    if spec.supports_plugins:
        return PROJECT_TYPE_PLUGIN
    if spec.supports_mods:
        return PROJECT_TYPE_MOD
    return None


def loaders_for(server_type: ServerType) -> tuple[str, ...]:
    """Cargadores que debe aceptar un fichero para este tipo de servidor."""
    return LOADERS_BY_SERVER_TYPE.get(server_type, ())


def search_facets(
    project_type: str, game_version: str | None = None, loaders: tuple[str, ...] = ()
) -> str:
    """Construye el filtro de busqueda de Modrinth (JSON compacto).

    Los filtros van en grupos: fuera se combinan con «y», dentro con «o». Asi un
    servidor Paper pide proyectos de cualquiera de sus cargadores validos.
    """
    facets: list[list[str]] = []
    if project_type:
        facets.append([f"project_type:{project_type}"])
    if game_version and game_version != "latest":
        facets.append([f"versions:{game_version}"])
    limpios = [str(loader).strip().lower() for loader in loaders if str(loader).strip()]
    if limpios:
        facets.append([f"categories:{loader}" for loader in limpios])
    return json.dumps(facets, separators=(",", ":"))


def _request_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 - https
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise ModrinthError(
            f"Modrinth respondio con un error {exc.code}. Intentalo de nuevo en unos minutos."
        ) from exc
    except urllib.error.URLError as exc:
        raise ModrinthError(
            "No se pudo conectar con Modrinth. Comprueba la conexion a internet."
        ) from exc
    except OSError as exc:  # pragma: no cover - fallo de red poco frecuente
        raise ModrinthError(f"Error de red al consultar Modrinth: {exc}") from exc
    try:
        return json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ModrinthError("Modrinth devolvio una respuesta que no se pudo interpretar.") from exc


def parse_project(hit: dict[str, Any]) -> Project:
    """Convierte un resultado JSON de Modrinth en ``Project``."""
    categorias = [str(valor).strip().lower() for valor in hit.get("categories") or []]
    return Project(
        id=str(hit.get("project_id") or hit.get("id") or ""),
        slug=str(hit.get("slug") or ""),
        title=str(hit.get("title") or "Sin titulo"),
        description=str(hit.get("description") or ""),
        downloads=int(hit.get("downloads") or 0),
        icon_url=str(hit.get("icon_url") or ""),
        project_type=str(hit.get("project_type") or ""),
        game_versions=tuple(str(v) for v in hit.get("versions") or [] if str(v).strip()),
        loaders=tuple(categoria for categoria in categorias if categoria in LOADER_CATEGORIES),
        client_side=str(hit.get("client_side") or ""),
        server_side=str(hit.get("server_side") or ""),
        updated=str(hit.get("date_modified") or ""),
        follows=int(hit.get("follows") or 0),
        author=str(hit.get("author") or ""),
    )


def parse_release(project_id: str, data: dict[str, Any]) -> Release | None:
    """Extrae el fichero principal de una version de Modrinth."""
    files = data.get("files") or []
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not isinstance(primary, dict):
        return None
    url = str(primary.get("url") or "").strip()
    filename = str(primary.get("filename") or "").strip()
    if not url or not filename:
        return None
    hashes = primary.get("hashes") or {}
    sha512 = hashes.get("sha512") if isinstance(hashes, dict) else None
    dependencies = tuple(
        str(dep.get("project_id"))
        for dep in data.get("dependencies") or []
        if isinstance(dep, dict)
        and dep.get("dependency_type") == "required"
        and dep.get("project_id")
    )
    return Release(
        project_id=project_id,
        name=str(data.get("name") or filename),
        version_number=str(data.get("version_number") or ""),
        game_versions=tuple(str(v) for v in data.get("game_versions") or []),
        loaders=tuple(str(v) for v in data.get("loaders") or []),
        download_url=url,
        filename=filename,
        size=int(primary.get("size") or 0),
        sha512=str(sha512) if sha512 else None,
        dependencies=dependencies,
        version_id=str(data.get("id") or ""),
        version_type=str(data.get("version_type") or ""),
    )


def search_projects(
    query: str,
    *,
    project_type: str,
    game_version: str | None = None,
    limit: int = 25,
    only_server_side: bool = True,
    loaders: tuple[str, ...] = (),
) -> list[Project]:
    """Busca proyectos compatibles con la version y los cargadores indicados.

    Si la busqueda esta vacia se muestran los mas descargados, de forma que la
    ventana no aparezca en blanco la primera vez.

    ``only_server_side`` descarta los proyectos de cliente, que no sirven en un
    servidor. Los modpacks son la excepcion: Modrinth los marca casi siempre
    como «solo cliente» porque llevan mods de cliente, y aun asi la imagen los
    instala perfectamente.
    """
    cleaned = (query or "").strip()
    params = {
        "query": cleaned,
        "facets": search_facets(project_type, game_version, loaders),
        "limit": str(max(1, min(limit, 50))),
        "index": "relevance" if cleaned else "downloads",
    }
    data = _request_json(f"{API_URL}/search?{urllib.parse.urlencode(params)}")
    if not isinstance(data, dict):
        raise ModrinthError("Modrinth devolvio una respuesta inesperada.")
    projects: list[Project] = []
    for hit in data.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        if only_server_side and hit.get("server_side") == _SERVER_UNSUPPORTED:
            # Un mod de cliente no sirve en el servidor.
            continue
        project = parse_project(hit)
        if project.id:
            projects.append(project)
    return projects


def fetch_releases(
    project_id: str,
    *,
    game_version: str | None = None,
    loaders: tuple[str, ...] = (),
) -> list[Release]:
    """Devuelve las versiones compatibles, la mas reciente primero."""
    params: dict[str, str] = {}
    if game_version and game_version != "latest":
        params["game_versions"] = json.dumps([game_version])
    if loaders:
        params["loaders"] = json.dumps(list(loaders))
    url = f"{API_URL}/project/{urllib.parse.quote(project_id)}/version"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = _request_json(url)
    if not isinstance(data, list):
        raise ModrinthError("Modrinth devolvio una respuesta inesperada.")
    releases: list[Release] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        release = parse_release(project_id, item)
        if release is not None:
            releases.append(release)
    return releases


def choose_release(releases: list[Release]) -> Release | None:
    """Elige el fichero a instalar: Modrinth devuelve primero el mas reciente."""
    return releases[0] if releases else None


# ============================================================== modpacks
def search_modpacks(
    query: str, *, limit: int = 40, loaders: tuple[str, ...] = ()
) -> list[Project]:
    """Busca modpacks en Modrinth (sin filtrar por version de Minecraft).

    Un modpack fija el Minecraft y el cargador que necesita, asi que no tiene
    sentido filtrar la busqueda por la version del servidor actual. Tampoco se
    descartan los «solo cliente»: Modrinth marca asi a casi todos los packs
    (llevan mods de cliente) y la imagen los instala igualmente.

    ``loaders`` se envia como filtro de Modrinth (los cargadores son categorias
    del proyecto); asi se puede pedir, por ejemplo, solo modpacks de Forge.
    """
    return search_projects(
        query,
        project_type=PROJECT_TYPE_MODPACK,
        limit=limit,
        only_server_side=False,
        loaders=loaders,
    )


@dataclass(frozen=True)
class ModpackPlan:
    """Datos que necesita la imagen para instalar un modpack concreto."""

    slug: str
    project_id: str
    version_id: str
    version_number: str
    loader: str
    minecraft_version: str
    title: str = ""

    @property
    def installable(self) -> bool:
        """Un pack solo se puede instalar si usa un cargador conocido."""
        return bool(self.loader) and bool(self.minecraft_version)

    def extra_env(self) -> dict[str, str]:
        """Variables para ``itzg/minecraft-server`` que identifican el pack.

        El tipo de servidor (``TYPE=MODRINTH``) y la version de Minecraft los pone
        el propio servidor, por eso aqui solo van los datos del pack.
        """
        env = {"MODRINTH_MODPACK": self.slug or self.project_id}
        if self.version_id:
            env["MODRINTH_VERSION"] = self.version_id
        if self.loader:
            env["MODRINTH_LOADER"] = self.loader
        return env


def plan_modpack(project: Project, release: Release) -> ModpackPlan | None:
    """Traduce un modpack de Modrinth a los ajustes que entiende la imagen.

    Devuelve ``None`` si la version elegida no usa ningun cargador compatible
    (por ejemplo, modpacks que solo existen para NeoForge en versiones nuevas).
    """
    loader = ""
    for candidate in release.loaders:
        cleaned = str(candidate).strip().lower()
        if cleaned in MODPACK_LOADERS:
            loader = cleaned
            break
    if not loader:
        return None
    versions = [v for v in release.game_versions if str(v).strip()]
    minecraft = max(versions, key=version_sort_key) if versions else ""
    return ModpackPlan(
        slug=project.slug or project.id,
        project_id=project.id,
        version_id=release.version_id,
        version_number=release.version_number,
        loader=loader,
        minecraft_version=minecraft,
        title=project.title,
    )


def choose_modpack_version(releases: list[Release]) -> Release | None:
    """Elige la version mas conveniente del pack.

    Modrinth devuelve las versiones de mas nueva a mas vieja y en los modpacks
    abundan las betas, asi que se prefiere la primera version estable que se
    pueda instalar; si el pack solo publica betas, se usa la mas nueva.
    """
    installable = [
        release
        for release in releases
        if any(str(loader).strip().lower() in MODPACK_LOADERS for loader in release.loaders)
    ]
    if not installable:
        return releases[0] if releases else None
    stable = [
        release
        for release in installable
        if (release.version_type or "release").strip().lower() == "release"
    ]
    return stable[0] if stable else installable[0]



def download_release(
    files,
    release: Release,
    destination: str,
    *,
    on_progress=None,
    should_cancel=None,
):
    """Descarga el fichero de una version en la carpeta del servidor."""
    logger.info(
        "Instalando %s %s (%s) en %s",
        release.name,
        release.version_number,
        release.filename,
        destination,
    )
    return files.download(
        release.download_url,
        destination,
        filename=release.filename,
        expected_sha512=release.sha512,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
