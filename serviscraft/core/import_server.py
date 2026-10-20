"""Importar un servidor que ya existia (por ejemplo, exportado de Aternos).

La gente suele tener su mundo y sus plugins en otra maquina o en un hosting.
Esta parte del programa mira una carpeta (o el ``.zip`` que da Aternos) y
reconoce lo importante sin abrir el juego:

* el tipo de servidor (Vanilla, Paper, Fabric, Forge),
* la version de Minecraft (por ``version_history.json``, el ``latest.log`` o el
  nombre del ``.jar``),
* el mundo (``level.dat``), los plugins, los mods y el puerto,
* si viene de Aternos (o de un hosting parecido), para decirlo en la ventana.

Tambien copia el contenido a la carpeta del servidor nuevo. Dos reglas de
seguridad mandan aqui: no se sigue ningun enlace simbolico y ninguna ruta del
``.zip`` puede salirse de la carpeta de destino (ni ``..``, ni rutas absolutas).
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ServiscraftError
from .logging_setup import get_logger
from .models import ServerType
from .properties import ServerProperties
from .validation import validate_name

logger = get_logger("import_server")

#: Tamano maximo que se acepta importar (un servidor con mundos y mods no llega).
MAX_IMPORT_BYTES = 64 * 1024 * 1024 * 1024
#: Numero maximo de ficheros (un .zip mal hecho podria traer millones).
MAX_IMPORT_FILES = 300_000
#: Tamano maximo de un solo fichero.
MAX_SINGLE_FILE = 12 * 1024 * 1024 * 1024
#: Lo maximo que se lee de un fichero de texto para reconocer el servidor.
MAX_TEXT_BYTES = 512 * 1024

#: Carpetas que no se copian: se regeneran solas y ocupan mucho.
SKIPPED_TOP_DIRS = frozenset(
    {"libraries", "logs", "crash-reports", "cache", ".cache", "versions", ".fabric"}
)

#: Ficheros de texto donde se busca el origen y la version.
_INSPECT_FILES = (
    "server.properties",
    "version_history.json",
    "logs/latest.log",
    "eula.txt",
    "ops.json",
    "whitelist.json",
    "banned-players.json",
    "bukkit.yml",
    "spigot.yml",
    "config/paper-global.yml",
)

#: Hostings reconocidos (marcador que se busca y nombre que se muestra).
_HOSTINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Aternos", ("aternos",)),
    ("exaroton", ("exaroton",)),
    ("Minehut", ("minehut",)),
    ("PloudOS", ("ploudos",)),
    ("FalixNodes", ("falixnodes", "falix")),
    ("PebbleHost", ("pebblehost",)),
)

_VERSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"MC:\s*(\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.\-]+)?)"),
    re.compile(r"minecraft server version\s+(\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.\-]+)?)", re.I),
    re.compile(r"fabric-server-mc\.(\d+\.\d+(?:\.\d+)?)", re.I),
    re.compile(r"\b(?:paper|purpur|spigot|folia)-(\d+\.\d+(?:\.\d+)?)", re.I),
    re.compile(r"\bforge-(\d+\.\d+(?:\.\d+)?)-", re.I),
    re.compile(r"\b(?:server|minecraft_server)[.\-](\d+\.\d+(?:\.\d+)?)\.jar", re.I),
)


class ImportSourceError(ServiscraftError):
    """La carpeta o el archivo elegidos no son un servidor que se pueda importar."""


class ImportCancelled(ServiscraftError):
    """El usuario cancelo la importacion a mitad."""


@dataclass(frozen=True)
class ServerSourceInfo:
    """Lo que se ha reconocido en la carpeta o el ``.zip`` elegidos."""

    path: Path
    #: Prefijo comun dentro del origen ("" si el servidor esta en la raiz).
    prefix: str
    is_archive: bool
    #: Nombre propuesto para el servidor nuevo.
    name: str
    server_type: ServerType
    version: str
    #: Version deducida (la que se propone); ``latest`` si no se pudo saber.
    version_known: bool
    port: int
    world: str
    worlds: tuple[str, ...]
    plugins: int
    mods: int
    origin: str
    motd: str
    has_properties: bool
    has_icon: bool
    has_eula: bool
    files: int
    total_bytes: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def origin_label(self) -> str:
        return self.origin or "Exportado de otro equipo"

    def summary(self) -> str:
        """Frase corta para la ventana de importacion."""
        partes = [f"{self.server_type.label} {self.version}"]
        if self.world:
            partes.append(f"mundo «{self.world}»")
        if self.plugins:
            partes.append(f"{self.plugins} plugins")
        if self.mods:
            partes.append(f"{self.mods} mods")
        return ", ".join(partes)


def _safe_relative(name: str) -> str | None:
    """Normaliza una ruta del archivo y rechaza lo que se salga de la carpeta."""
    clean = str(name).replace("\\", "/").strip()
    while clean.startswith("./"):
        clean = clean[2:]
    if not clean or clean.endswith("/") or clean.startswith("/"):
        return None
    parts = clean.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if re.match(r"^[A-Za-z]:", parts[0]):
        return None
    return "/".join(parts)


def _looks_like_server(files: set[str]) -> bool:
    if "server.properties" in files:
        return True
    if any(name.endswith("/level.dat") for name in files):
        return True
    if any(name.endswith("/server.properties") for name in files):
        return True
    if any(re.search(r"(^|/)(server|paper|spigot|purpur|forge|fabric)[^/]*\.jar$", n) for n in files):
        return True
    if any(name.startswith("plugins/") and name.endswith(".jar") for name in files):
        return True
    if any(name.startswith("mods/") and name.endswith(".jar") for name in files):
        return True
    return False


def _root_is_server(files: set[str]) -> bool:
    """True si el servidor esta en la propia carpeta elegida (sin subcarpeta)."""
    if "server.properties" in files or "eula.txt" in files:
        return True
    if "world/level.dat" in files:
        return True
    return any(
        re.match(r"^(server|paper|purpur|spigot|folia|forge|fabric)[^/]*\.jar$", name, re.I)
        for name in files
    )


def _server_candidates(files: set[str]) -> list[str]:
    """Subcarpetas de primer nivel que contienen un servidor completo."""
    tops = {name.split("/", 1)[0] for name in files if "/" in name}
    candidatos: list[str] = []
    for top in sorted(tops):
        inside = {n[len(top) + 1 :] for n in files if n.startswith(top + "/")}
        if _looks_like_server(inside) and (
            "server.properties" in inside or "eula.txt" in inside or "world/level.dat" in inside
        ):
            candidatos.append(top)
    return candidatos


def _choose_prefix(files: set[str]) -> str:
    """Prefijo comun cuando el servidor viene dentro de una subcarpeta."""
    candidates: set[str] = set()
    for name in files:
        if name in {"server.properties", "eula.txt"} or name.endswith("/level.dat"):
            parts = name.split("/")
            for depth in range(1, len(parts)):
                candidates.add("/".join(parts[:depth]))
    # Se prefiere la carpeta menos profunda que tenga pinta de servidor.
    for candidate in sorted(candidates, key=lambda c: (c.count("/"), c)):
        inside = {n[len(candidate) + 1 :] for n in files if n.startswith(candidate + "/")}
        if _looks_like_server(inside):
            return candidate
    return ""


class _Source:
    """Lectura uniforme de una carpeta o de un ``.zip``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.is_archive = path.is_file() and path.suffix.lower() == ".zip"
        self._zip: zipfile.ZipFile | None = None
        self._root: Path | None = None
        self.entries: dict[str, int] = {}
        self.skipped: list[str] = []
        if self.is_archive:
            self._open_zip()
        else:
            self._scan_folder()
        self.prefix = _choose_prefix(set(self.entries))
        self.files: dict[str, int] = {
            name: size
            for name, size in self.entries.items()
            if not self.prefix or name.startswith(self.prefix + "/")
        }
        if self.prefix:
            self.files = {
                name[len(self.prefix) + 1 :]: size for name, size in self.files.items()
            }

    # ------------------------------------------------------------- apertura
    def _open_zip(self) -> None:
        try:
            self._zip = zipfile.ZipFile(self.path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ImportSourceError(f"El archivo «{self.path.name}» no es un .zip valido.") from exc
        count = 0
        for info in self._zip.infolist():
            if info.is_dir():
                continue
            name = _safe_relative(info.filename)
            if name is None:
                self.skipped.append(info.filename)
                continue
            if info.file_size > MAX_SINGLE_FILE:
                raise ImportSourceError(
                    f"«{name}» es demasiado grande para importarlo de una vez."
                )
            # Un enlace simbolico dentro del .zip no se extrae.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                self.skipped.append(info.filename)
                continue
            count += 1
            if count > MAX_IMPORT_FILES:
                raise ImportSourceError("El archivo tiene demasiados ficheros para importarlo.")
            self.entries[name] = info.file_size
        if self.skipped:
            logger.warning("Se ignoran %s entradas no seguras del .zip", len(self.skipped))

    def _scan_folder(self) -> None:
        root = self.path
        if not root.is_dir():
            raise ImportSourceError(f"«{root}» no es una carpeta.")
        self._root = root
        count = 0
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            # No se entra en carpetas que son enlaces ni en las que no se copian.
            dirs[:] = [
                d
                for d in dirs
                if not (current_path / d).is_symlink()
                and not (
                    current_path == root
                    and d.lower() in SKIPPED_TOP_DIRS
                    and d.lower() not in {"logs"}  # los registros si se leen al reconocer
                )
            ]
            for name in files:
                file_path = current_path / name
                rel = file_path.relative_to(root).as_posix()
                if file_path.is_symlink():
                    self.skipped.append(rel)
                    continue
                try:
                    size = file_path.stat().st_size
                except OSError:
                    continue
                if size > MAX_SINGLE_FILE:
                    raise ImportSourceError(f"«{rel}» es demasiado grande para importarlo.")
                count += 1
                if count > MAX_IMPORT_FILES:
                    raise ImportSourceError("La carpeta tiene demasiados ficheros.")
                self.entries[rel] = size
        if self.skipped:
            logger.warning("Se ignoran %s enlaces simbolicos de la carpeta", len(self.skipped))

    # -------------------------------------------------------------- lectura
    def read_text(self, relative: str) -> str:
        relative = relative.strip("/")
        if not relative:
            return ""
        full = f"{self.prefix}/{relative}" if self.prefix else relative
        if full not in self.entries:
            return ""
        if self._zip is not None:
            try:
                info = self._zip.getinfo(full)
                if info.file_size > MAX_TEXT_BYTES:
                    with self._zip.open(info) as handle:
                        data = handle.read(MAX_TEXT_BYTES)
                else:
                    data = self._zip.read(info)
            except (KeyError, OSError, zipfile.BadZipFile):
                return ""
            return data.decode("utf-8", errors="replace")
        if self._root is None:
            return ""
        path = self._root / full
        try:
            with path.open("rb") as handle:
                data = handle.read(MAX_TEXT_BYTES)
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace")

    def read_bytes(self, relative: str, *, limit: int = MAX_TEXT_BYTES) -> bytes:
        relative = relative.strip("/")
        full = f"{self.prefix}/{relative}" if self.prefix else relative
        if full not in self.entries:
            return b""
        if self._zip is not None:
            try:
                with self._zip.open(full) as handle:
                    return handle.read(limit)
            except (KeyError, OSError, zipfile.BadZipFile):
                return b""
        if self._root is None:
            return b""
        try:
            with (self._root / full).open("rb") as handle:
                return handle.read(limit)
        except OSError:
            return b""

    def has(self, relative: str) -> bool:
        return relative.strip("/") in self.files

    def names(self) -> Iterator[str]:
        return iter(self.files)

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    # --------------------------------------------------------------- copia
    def copy_to(
        self,
        destination: Path,
        *,
        on_progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> int:
        total = len(self.files)
        hechos = 0
        destination.mkdir(parents=True, exist_ok=True)
        for relative, size in self.files.items():
            if should_cancel is not None and should_cancel():
                raise ImportCancelled("Importacion cancelada.")
            if relative.split("/", 1)[0].lower() in SKIPPED_TOP_DIRS:
                continue
            target = destination / relative
            try:
                target.resolve().relative_to(destination.resolve())
            except ValueError as exc:  # pragma: no cover - ya se valida al leer
                raise ImportSourceError(f"Ruta no segura dentro del servidor: «{relative}».") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            if self._zip is not None:
                with self._zip.open(f"{self.prefix}/{relative}" if self.prefix else relative) as src:
                    with target.open("wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
            else:
                origen = (self._root / (f"{self.prefix}/{relative}" if self.prefix else relative))
                shutil.copy2(origen, target)
            hechos += 1
            if on_progress is not None and (hechos % 25 == 0 or hechos == total):
                on_progress(hechos, total)
        if on_progress is not None:
            on_progress(total, total)
        return hechos


def _detect_version(source: _Source, names: list[str]) -> tuple[str, bool, str]:
    """Devuelve (version, se_sabe, de_donde_salio)."""
    history = source.read_text("version_history.json")
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(history)
        if match:
            return _clean_version(match.group(1)), True, "version_history.json"
    log = source.read_text("logs/latest.log")
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(log)
        if match:
            return _clean_version(match.group(1)), True, "logs/latest.log"
    for name in sorted(names, key=len, reverse=True):
        if not name.lower().endswith(".jar"):
            continue
        base = name.rsplit("/", 1)[-1]
        for pattern in _VERSION_PATTERNS:
            match = pattern.search(base)
            if match:
                return _clean_version(match.group(1)), True, base
    return "latest", False, ""


def _clean_version(value: str) -> str:
    limpio = value.strip().strip(".")
    if re.match(r"^\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.\-]+)?$", limpio):
        return limpio
    return "latest"


def _detect_type(names: list[str], files: set[str], version_source: str) -> ServerType:
    lower = {name.lower() for name in names}
    if any(re.match(r"^forge-.*\.jar$", n) for n in lower) or any(
        n.startswith("libraries/net/minecraftforge/") for n in lower
    ):
        return ServerType.FORGE
    if (
        "fabric-server-launch.jar" in lower
        or any(re.match(r"^fabric-server-mc\..*\.jar$", n) for n in lower)
        or any(n.startswith(".fabric/") for n in lower)
    ):
        return ServerType.FABRIC
    if (
        "version_history.json" in files
        or any(re.match(r"^(paper|purpur|folia)-.*\.jar$", n) for n in lower)
        or "config/paper-global.yml" in files
        or "paper.yml" in files
    ):
        return ServerType.PAPER
    if "bukkit.yml" in files or "spigot.yml" in files or any(
        n.startswith("plugins/") for n in lower
    ):
        return ServerType.PAPER
    if version_source.lower().startswith(("paper", "purpur", "folia")):
        return ServerType.PAPER
    return ServerType.VANILLA


def _detect_origin(source: _Source) -> str:
    textos = [source.path.name.lower()]
    for relative in _INSPECT_FILES:
        texto = source.read_text(relative).lower()
        if texto:
            textos.append(texto)
    for nombre, marcadores in _HOSTINGS:
        if any(marcador in texto for texto in textos for marcador in marcadores):
            return nombre
    return ""


def _count_jars(names: list[str], folder: str) -> int:
    prefix = folder + "/"
    return sum(
        1
        for name in names
        if name.startswith(prefix) and name.lower().endswith(".jar") and "/" not in name[len(prefix) :]
    )


def _suggest_name(base: str) -> str:
    base = re.sub(r"(?i)aternos", " ", base)
    base = re.sub(r"[^A-Za-z0-9 ._-]+", " ", base)
    base = " ".join(base.split()).strip(" ._-")
    if not base or base.lower() in {"export", "backup", "copia", "servidor"}:
        base = "Servidor importado"
    base = base[:48].strip()
    try:
        return validate_name(base)
    except ServiscraftError:
        return "Servidor importado"


def inspect_source(path: str | Path) -> ServerSourceInfo:
    """Reconoce un servidor dentro de una carpeta o de un ``.zip``."""
    origen = Path(path).expanduser()
    if not origen.exists():
        raise ImportSourceError("La carpeta o el archivo elegidos no existen.")
    if origen.is_file() and origen.suffix.lower() != ".zip":
        raise ImportSourceError("Elige la carpeta del servidor o el archivo .zip que da Aternos.")

    source = _Source(origen)
    try:
        # ``entries`` es el arbol completo; ``names()`` ya viene recortado al
        # servidor elegido. Los dos servidores se buscan en el arbol completo.
        completos = set(source.entries)
        names = list(source.names())
        files = set(names)
        if not files:
            raise ImportSourceError("La carpeta esta vacia: no hay ningun servidor dentro.")
        if not _root_is_server(completos):
            candidatos = _server_candidates(completos)
            if len(candidatos) > 1:
                raise ImportSourceError(
                    "Dentro de esa carpeta hay varios servidores ("
                    + ", ".join(f"«{c}»" for c in candidatos)
                    + "). Elige la carpeta del que quieras importar."
                )
        if not _looks_like_server(files):
            raise ImportSourceError(
                "No parece la carpeta de un servidor de Minecraft. Debe tener "
                "«server.properties», la carpeta del mundo o los plugins/mods."
            )
        total = sum(size for name, size in source.files.items() if name.split("/", 1)[0].lower() not in SKIPPED_TOP_DIRS)
        if total > MAX_IMPORT_BYTES:
            raise ImportSourceError("El servidor ocupa demasiado para importarlo de una vez.")

        properties_text = source.read_text("server.properties")
        properties = _parse_properties(properties_text)
        world = properties.get("level-name", "world").strip() or "world"
        worlds = tuple(
            sorted(
                {
                    name.split("/level.dat")[0]
                    for name in names
                    if name.endswith("/level.dat") and "/" in name
                }
            )
        )
        if world not in worlds and worlds:
            world = worlds[0]

        version, known, version_source = _detect_version(source, names)
        server_type = _detect_type(names, files, version_source)
        if server_type is ServerType.VANILLA and any(
            n.startswith("mods/") and n.endswith(".jar") for n in files
        ):
            # Mods sin cargador reconocible: Forge es la opcion habitual.
            server_type = ServerType.FORGE
        port = 25565
        try:
            port = int(properties.get("server-port", "25565"))
        except ValueError:
            port = 25565
        if not 1 <= port <= 65535:
            port = 25565

        notas: list[str] = []
        if not known:
            notas.append(
                "No se pudo averiguar la version de Minecraft: se usara la ultima. "
                "Puedes cambiarla antes de importar."
            )
        if source.skipped:
            notas.append(
                f"Se ignoran {len(source.skipped)} enlaces o rutas no seguras del origen."
            )
        origin = _detect_origin(source)
        if origin:
            notas.append(
                f"Se ha reconocido un servidor exportado de {origin}: se conservan el "
                "mundo, los plugins o mods y la configuracion."
            )

        return ServerSourceInfo(
            path=origen,
            prefix=source.prefix,
            is_archive=source.is_archive,
            name=_suggest_name(
                source.prefix.rsplit("/", 1)[-1] if source.prefix else (
                    origen.stem if origen.is_file() else origen.name
                )
            ),
            server_type=server_type,
            version=version,
            version_known=known,
            port=port,
            world=world,
            worlds=worlds,
            plugins=_count_jars(names, "plugins"),
            mods=_count_jars(names, "mods"),
            origin=origin,
            motd=properties.get("motd", ""),
            has_properties="server.properties" in files,
            has_icon="server-icon.png" in files,
            has_eula="eula.txt" in files,
            files=len(files),
            total_bytes=total,
            notes=tuple(notas),
        )
    finally:
        source.close()


def _parse_properties(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for linea in text.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith(("#", "!")):
            continue
        if "=" in limpia:
            clave, valor = limpia.split("=", 1)
        elif ":" in limpia:
            clave, valor = limpia.split(":", 1)
        else:
            continue
        props[clave.strip()] = valor.strip()
    return props


def copy_source(
    info: ServerSourceInfo,
    destination: str | Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> int:
    """Copia el servidor reconocido a ``destination`` (la carpeta ``data``)."""
    source = _Source(info.path)
    try:
        if source.prefix != info.prefix:
            raise ImportSourceError("El contenido del servidor cambio mientras se importaba.")
        return source.copy_to(
            Path(destination), on_progress=on_progress, should_cancel=should_cancel
        )
    finally:
        source.close()


def default_properties_for_import() -> dict[str, str]:
    """Valores que la aplicacion necesita controlar en ``server.properties``."""
    return {
        "server-port": "25565",
        "enable-rcon": "true",
        "rcon.port": "25575",
    }


def read_motd(path: str | Path) -> str:
    """Lee el MOTD de un ``server.properties`` (para la vista previa)."""
    origen = Path(path).expanduser()
    if origen.is_dir():
        origen = origen / "server.properties"
    try:
        props = ServerProperties.load(origen)
    except ServiscraftError:
        return ""
    return props.get("motd", "")


__all__ = [
    "ImportCancelled",
    "ImportSourceError",
    "MAX_IMPORT_BYTES",
    "SKIPPED_TOP_DIRS",
    "ServerSourceInfo",
    "copy_source",
    "default_properties_for_import",
    "inspect_source",
    "read_motd",
]
