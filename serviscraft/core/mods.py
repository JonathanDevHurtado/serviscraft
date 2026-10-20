"""Inventario de los mods o pluguins instalados en un servidor.

Los ficheros viven en ``data/mods`` (Fabric, Forge y modpacks) o en
``data/plugins`` (Paper). Aqui se listan, se activan o desactivan (renombrando
``.jar`` a ``.jar.desactivado``, sin borrar nada) y se añaden desde el catalogo,
desde un fichero local o desde una URL.

Para saber que ficheros añadio el usuario y cuales trae el modpack se guarda un
manifiesto oculto (``.serviscraft-mods.json``) con los nombres añadidos a mano.
Un fichero que no esta en el manifiesto de un servidor con modpack se considera
parte del modpack.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import ServiscraftError
from .logging_setup import get_logger
from .store import ServerStore
from .validation import ValidationError, atomic_write_text, ensure_within, validate_basename

logger = get_logger("mods")

#: Sufijo que marca un mod desactivado (el fichero sigue en el disco).
DISABLED_SUFFIX = ".desactivado"
#: Nombre del manifiesto que anota los ficheros añadidos a mano.
MANIFEST_NAME = ".serviscraft-mods.json"
#: Extensiones que se consideran contenido instalable.
CONTENT_SUFFIXES = (".jar", ".zip", ".mrpack")


class ModsError(ServiscraftError):
    """Fallo al manipular los mods de un servidor."""


@dataclass(frozen=True)
class ModEntry:
    """Un mod o pluguin dentro de la carpeta del servidor."""

    filename: str
    size_bytes: int
    modified: float
    enabled: bool
    custom: bool
    #: Direccion del icono del proyecto del que salio (vacia si no se sabe).
    icon_url: str = ""
    #: Nombre del proyecto (para la descripcion), si se conoce.
    title: str = ""

    @property
    def base_name(self) -> str:
        """Nombre sin la extension ni el sufijo de desactivado."""
        name = self.filename
        if name.lower().endswith(DISABLED_SUFFIX):
            name = name[: -len(DISABLED_SUFFIX)]
        for suffix in CONTENT_SUFFIXES:
            if name.lower().endswith(suffix):
                return name[: -len(suffix)]
        return name

    @property
    def size_label(self) -> str:
        from .models import format_bytes

        return format_bytes(self.size_bytes)

    @property
    def origin_label(self) -> str:
        return "personalizado" if self.custom else "del modpack"


class ModsInventory:
    """Operaciones sobre la carpeta de mods (o pluguins) de un servidor."""

    def __init__(
        self,
        store: ServerStore,
        server_id: str,
        *,
        folder: str = "mods",
        modpack: bool = False,
    ) -> None:
        self.store = store
        self.server_id = server_id
        self.folder = folder
        self.modpack = modpack

    # ------------------------------------------------------------------ rutas
    @property
    def data_dir(self) -> Path:
        return self.store.data_dir(self.server_id)

    @property
    def folder_path(self) -> Path:
        return ensure_within(Path(self.folder), self.data_dir)

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / MANIFEST_NAME

    def _resolve(self, filename: str) -> Path:
        name = validate_basename(filename)
        return ensure_within(Path(name), self.folder_path)

    # -------------------------------------------------------------- manifiesto
    def _load_manifest(self) -> set[str]:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if not isinstance(data, dict):
            return set()
        values = data.get("personalizados") or []
        if not isinstance(values, list):
            return set()
        return {str(value) for value in values}

    def _save_manifest(self, names: set[str]) -> None:
        """Guarda la lista de personalizados conservando los datos de proyectos."""
        proyectos = self._load_projects()
        self._write_manifest(names, proyectos)

    def _write_manifest(self, names: set[str], proyectos: dict[str, dict[str, str]]) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            datos: dict[str, object] = {"personalizados": sorted(names)}
            if proyectos:
                datos["proyectos"] = {
                    nombre: valor for nombre, valor in sorted(proyectos.items())
                }
            # La carpeta la escribe el servidor: nada de seguir enlaces.
            atomic_write_text(
                self.manifest_path,
                json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                role="El manifiesto de mods",
            )
        except (OSError, ValidationError) as exc:  # pragma: no cover - disco lleno o permisos
            logger.warning("No se pudo guardar el manifiesto de mods: %s", exc)

    def _load_projects(self) -> dict[str, dict[str, str]]:
        """Datos de los proyectos instalados desde el catalogo (por fichero).

        Formato: ``{"nombre.jar": {"slug": ..., "titulo": ..., "icono": ...}}``.
        Si el manifiesto es de una version anterior y no tiene estos datos, se
        devuelve un diccionario vacio: nunca se pierde nada de lo que habia.
        """
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        valores = data.get("proyectos")
        if not isinstance(valores, dict):
            return {}
        proyectos: dict[str, dict[str, str]] = {}
        for nombre, datos in valores.items():
            if not isinstance(datos, dict):
                continue
            limpio = {
                clave: str(datos.get(clave) or "")
                for clave in ("slug", "titulo", "icono")
                if datos.get(clave)
            }
            if limpio:
                proyectos[str(nombre)] = limpio
        return proyectos

    def project_for(self, filename: str) -> dict[str, str]:
        """Datos del proyecto del que salio un fichero (vacio si no se sabe)."""
        return self._load_projects().get(filename, {})

    def remember_project(
        self,
        filename: str,
        *,
        slug: str = "",
        title: str = "",
        icon: str = "",
    ) -> None:
        """Recuerda de que proyecto de Modrinth salio un fichero.

        Asi la lista de mods puede enseñar su icono (como Prism Launcher) sin
        volver a consultar la red cada vez.
        """
        nombre = str(filename or "").strip()
        if not nombre:
            return
        proyectos = self._load_projects()
        previo = proyectos.get(nombre, {})
        datos = {
            "slug": slug or previo.get("slug", ""),
            "titulo": title or previo.get("titulo", ""),
            "icono": icon or previo.get("icono", ""),
        }
        proyectos[nombre] = {clave: valor for clave, valor in datos.items() if valor}
        self._write_manifest(self._load_manifest(), proyectos)

    def mark_custom(self, filename: str) -> None:
        """Anota un fichero como añadido a mano (no forma parte del modpack)."""
        nombres = self._load_manifest()
        nombres.add(filename)
        self._save_manifest(nombres)

    def forget_custom(self, filename: str) -> None:
        nombres = self._load_manifest()
        if filename in nombres:
            nombres.discard(filename)
            self._save_manifest(nombres)

    # ----------------------------------------------------------------- listado
    def list_mods(self) -> list[ModEntry]:
        """Mods activos y desactivados, ordenados por nombre."""
        directory = self.folder_path
        if not directory.is_dir():
            return []
        personalizados = self._load_manifest()
        proyectos = self._load_projects()
        entries: list[ModEntry] = []
        for item in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if not item.is_file() or item.name.startswith("."):
                continue
            lower = item.name.lower()
            enabled = not lower.endswith(DISABLED_SUFFIX)
            base = lower[: -len(DISABLED_SUFFIX)] if not enabled else lower
            if not base.endswith(CONTENT_SUFFIXES):
                continue
            try:
                stat = item.stat()
            except OSError:  # pragma: no cover - fichero desaparecido
                continue
            # Al desactivar, el fichero se renombra: los datos del proyecto
            # siguen guardados con el nombre original.
            original = item.name if enabled else item.name[: -len(DISABLED_SUFFIX)]
            datos_proyecto = proyectos.get(original) or proyectos.get(item.name) or {}
            entries.append(
                ModEntry(
                    filename=item.name,
                    size_bytes=stat.st_size,
                    modified=stat.st_mtime,
                    enabled=enabled,
                    # En un servidor sin modpack todo lo que hay lo puso el usuario.
                    custom=(not self.modpack) or item.name in personalizados,
                    icon_url=datos_proyecto.get("icono", ""),
                    title=datos_proyecto.get("titulo", ""),
                )
            )
        return entries

    def installed_names(self) -> list[str]:
        return [entry.filename for entry in self.list_mods()]

    # ---------------------------------------------------------------- cambios
    def set_enabled(self, filename: str, enabled: bool) -> Path:
        """Activa o desactiva un mod renombrandolo (nunca lo borra)."""
        current = self._resolve(filename)
        if not current.is_file():
            raise ModsError(f"No existe el fichero «{filename}».")
        if enabled and not current.name.lower().endswith(DISABLED_SUFFIX):
            return current
        if not enabled and current.name.lower().endswith(DISABLED_SUFFIX):
            return current
        if enabled:
            target = current.with_name(current.name[: -len(DISABLED_SUFFIX)])
        else:
            target = current.with_name(current.name + DISABLED_SUFFIX)
        target = ensure_within(Path(target.name), self.folder_path)
        if target.exists():
            raise ModsError(f"Ya existe «{target.name}»: no se puede renombrar.")
        current.rename(target)
        logger.info("Mod %s de %s %s", target.name, self.server_id, "activado" if enabled else "desactivado")
        return target

    def delete(self, filename: str) -> None:
        target = self._resolve(filename)
        if not target.is_file():
            raise ModsError(f"No existe el fichero «{filename}».")
        target.unlink()
        self.forget_custom(filename)
        logger.info("Mod %s eliminado de %s", filename, self.server_id)

    def add_file(self, source: Path) -> Path:
        """Copia un fichero local a la carpeta de mods y lo anota como propio."""
        origen = Path(source)
        if not origen.is_file():
            raise ModsError(f"No existe el fichero «{origen}».")
        name = validate_basename(origen.name, allowed_suffixes=CONTENT_SUFFIXES)
        self.folder_path.mkdir(parents=True, exist_ok=True)
        target = ensure_within(Path(name), self.folder_path)
        if target.exists():
            raise ModsError(
                f"Ya hay un fichero llamado «{name}». Borra o desactiva el anterior antes de añadir otro."
            )
        shutil.copy2(origen, target)
        self.mark_custom(target.name)
        logger.info("Mod %s copiado a %s", origen, target)
        return target

    def add_url(
        self,
        url: str,
        *,
        files,
        filename: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        """Descarga un mod desde una URL http/https a la carpeta de mods."""
        destination = files.download(
            url,
            self.folder,
            filename=filename,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        self.mark_custom(destination.name)
        return destination

    def missing_folder(self) -> bool:
        return not self.folder_path.is_dir()


def find_installed(name: str, filenames: list[str]) -> str | None:
    """Busca un mod por su nombre entre los ficheros instalados.

    Compara solo letras y numeros, de modo que «JourneyMap» encuentra
    ``journeymap-1.21.1-6.0.0.jar``. Devuelve el fichero encontrado o ``None``.
    """
    objetivo = _normalizar(name)
    if len(objetivo) < 3:
        return None
    for filename in filenames:
        if objetivo in _normalizar(filename):
            return filename
    return None


def _normalizar(texto: str) -> str:
    return "".join(ch for ch in str(texto).lower() if ch.isalnum())


def folder_for(spec) -> str:
    """Carpeta de contenido que corresponde a un servidor."""
    return "plugins" if getattr(spec, "supports_plugins", False) else "mods"


__all__ = [
    "CONTENT_SUFFIXES",
    "DISABLED_SUFFIX",
    "MANIFEST_NAME",
    "ModEntry",
    "ModsError",
    "ModsInventory",
    "find_installed",
    "folder_for",
]
