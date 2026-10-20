"""Almacen de servidores: lectura y escritura de la metainformacion en disco."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

from . import paths
from .errors import ServerNotFoundError, ServiscraftError, ValidationError
from .logging_setup import get_logger
from .models import ServerSpec
from .paths import DEFAULT_BEDROCK_PORT, DEFAULT_IMAGE
from .validation import MIN_PASSWORD_LENGTH, atomic_write_text, validate_port, validate_server_id
from .versions import recommended_java_tag

logger = get_logger("store")


def remove_tree(path: Path) -> None:
    """Elimina un arbol de directorios aunque tenga un propietario ajeno.

    Si el servidor se creo con una version anterior a la aplicacion (o con otro
    mapeo de usuario) los ficheros pueden pertenecer a un UID de subusuario. En
    ese caso se recurre a ``podman unshare``, que los ve como propios y puede
    borrarlos sin privilegios.
    """
    target = Path(path)
    if not target.exists():
        return
    try:
        shutil.rmtree(target)
        return
    except PermissionError:
        logger.warning("Sin permisos sobre %s; se intenta con 'podman unshare'", target)
    except OSError as exc:
        raise ServiscraftError(f"No se pudieron eliminar los ficheros: {exc}") from exc

    result = subprocess.run(  # noqa: S603 - argumentos en lista, sin shell
        ["podman", "unshare", "rm", "-rf", "--", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or target.exists():
        detail = (result.stderr or "").strip()
        raise ServiscraftError(
            "No se pudieron eliminar los ficheros del servidor"
            + (f": {detail}" if detail else ".")
        )

#: Permisos restrictivos: ``meta.json`` contiene la contrasena de RCON.
_FILE_MODE = 0o600
_DIR_MODE = 0o700

#: Version del esquema de ``meta.json``. Se sube al añadir campos nuevos.
META_VERSION = 3


def migrate_meta(raw: dict) -> tuple[dict, bool]:
    """Pone al dia una definicion antigua sin perder ni un dato.

    Devuelve ``(definicion, ha_cambiado)``. Las claves que esta version no
    conoce se dejan intactas (asi una version futura de la aplicacion puede
    añadir campos sin que una anterior los borre) y **nunca** se toca el
    contenido de ``data/``: los mundos no se leen ni se escriben aqui.
    """
    datos = dict(raw)
    # ``meta_version`` no existia en las primeras versiones: todo lo que no lo
    # trae es un servidor creado por ellas.
    datos.setdefault("bedrock", False)
    try:
        puerto = int(datos.get("bedrock_port") or DEFAULT_BEDROCK_PORT)
    except (TypeError, ValueError):
        puerto = DEFAULT_BEDROCK_PORT
    datos["bedrock_port"] = puerto
    if not str(datos.get("image") or "").strip():
        datos["image"] = DEFAULT_IMAGE
    if not str(datos.get("java_tag") or "").strip():
        # Un servidor muy antiguo pudo guardarse sin etiqueta de Java: se elige
        # la que pide su version para que arranque a la primera.
        datos["java_tag"] = recommended_java_tag(str(datos.get("version") or "latest"))
    if not isinstance(datos.get("extra_env"), dict):
        datos["extra_env"] = {}
    # Esquema 3: nombre personalizado para entrar (DuckDNS). Los servidores
    # creados antes simplemente no lo tienen configurado.
    for clave, defecto in (
        ("ddns_subdomain", ""),
        ("ddns_token", ""),
        ("ddns_last_ip", ""),
    ):
        if not isinstance(datos.get(clave), str):
            datos[clave] = defecto
    if not isinstance(datos.get("ddns_auto"), bool):
        valor = datos.get("ddns_auto", False)
        datos["ddns_auto"] = str(valor).strip().lower() in {"1", "true", "si", "yes"}
    # Una version antigua pudo guardar una contrasena de RCON demasiado corta;
    # sin esto el servidor se cargaria pero ya no se podria volver a guardar
    # (la validacion actual lo rechaza). Se genera una nueva: es un dato interno
    # y solo obliga a recrear el contenedor, nunca a tocar el mundo.
    if len(str(datos.get("rcon_password") or "")) < MIN_PASSWORD_LENGTH:
        datos["rcon_password"] = secrets.token_urlsafe(24)
    datos["meta_version"] = META_VERSION
    return datos, datos != raw


def _write_private_json(path: Path, payload: dict) -> None:
    """Escritura atomica con permisos restrictivos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, _DIR_MODE)
    except OSError:  # pragma: no cover - sistemas sin permisos POSIX
        pass
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        mode=_FILE_MODE,
        role="La definicion del servidor",
    )


class ServerStore:
    """Gestiona la carpeta ``servers/`` y los ficheros ``meta.json``."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else paths.servers_dir()

    # ---------------------------------------------------------------- rutas
    def server_dir(self, server_id: str) -> Path:
        return self.root / validate_server_id(server_id)

    def data_dir(self, server_id: str) -> Path:
        return self.server_dir(server_id) / "data"

    def backups_dir(self, server_id: str) -> Path:
        return self.server_dir(server_id) / "backups"

    def meta_file(self, server_id: str) -> Path:
        return self.server_dir(server_id) / "meta.json"

    # -------------------------------------------------------------- lectura
    def exists(self, server_id: str) -> bool:
        return self.meta_file(server_id).is_file()

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        ids: list[str] = []
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and (entry / "meta.json").is_file():
                ids.append(entry.name)
        return ids

    def load(self, server_id: str) -> ServerSpec:
        target = self.meta_file(server_id)
        if not target.is_file():
            raise ServerNotFoundError(f"El servidor '{server_id}' no existe.")
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ServerNotFoundError(
                f"La definicion del servidor '{server_id}' esta danada: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ServerNotFoundError(
                f"La definicion del servidor '{server_id}' no tiene el formato esperado."
            )
        raw, migrated = migrate_meta(raw)
        if migrated:
            # Se guarda la version migrada (con las claves desconocidas tal cual)
            # para no repetir el trabajo en cada arranque. Si el fichero no se
            # puede escribir, se sigue usando la definicion en memoria.
            try:
                _write_private_json(target, raw)
                logger.info(
                    "Definicion de %s actualizada al esquema %s (datos intactos)",
                    server_id,
                    META_VERSION,
                )
            except (OSError, ValidationError) as exc:  # pragma: no cover - disco lleno, solo lectura o enlace
                logger.warning("No se pudo guardar la migracion de %s: %s", server_id, exc)
        try:
            spec = ServerSpec.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ServerNotFoundError(
                f"La definicion del servidor '{server_id}' esta incompleta: {exc}"
            ) from exc
        try:
            # Se valida al cargar para que el resto de la aplicacion trabaje
            # siempre con datos coherentes (puertos, memoria, imagen...).
            return spec.validated()
        except ServiscraftError as exc:
            # Compatibilidad: una definicion antigua o editada a mano que no pasa
            # la validacion actual no debe hacer desaparecer el servidor de la
            # lista (ni sus mundos). Se avisa y se sigue usando tal cual: cada
            # consumidor vuelve a validar lo que necesita antes de usarlo.
            logger.warning(
                "La definicion de %s tiene valores fuera de rango (%s); se usa tal cual.",
                server_id,
                exc,
            )
            return spec

    def load_all(self) -> list[ServerSpec]:
        """Todos los servidores legibles, ordenados por nombre.

        Una carpeta que no cumple las reglas (por ejemplo, una copia manual de
        la carpeta de un servidor con espacios en el nombre) se ignora con un
        aviso: antes una sola carpeta asi tumbaba el listado entero y la ventana
        se quedaba con los estados de la ultima consulta buena.
        """
        specs: list[ServerSpec] = []
        for server_id in self.list_ids():
            try:
                specs.append(self.load(server_id))
            except ServerNotFoundError as exc:
                logger.warning("Servidor ignorado: %s", exc)
            except ServiscraftError as exc:
                logger.warning("Carpeta de servidor ignorada (%r): %s", server_id, exc)
        specs.sort(key=lambda s: (s.name.lower(), s.id))
        return specs

    # ------------------------------------------------------------ escritura
    def save(self, spec: ServerSpec) -> ServerSpec:
        validated = spec.validated()
        payload = validated.to_dict()
        # El esquema va siempre en el fichero: asi una version futura sabe que
        # migraciones ya estan hechas (y no se pierde al volver a guardar).
        payload["meta_version"] = META_VERSION
        _write_private_json(self.meta_file(validated.id), payload)
        return validated

    def prepare_dirs(self, server_id: str) -> Path:
        """Crea la carpeta del servidor y la subcarpeta ``data`` montada en ``/data``."""
        data = self.data_dir(server_id)
        data.mkdir(parents=True, exist_ok=True)
        self.backups_dir(server_id).mkdir(parents=True, exist_ok=True)
        for directory in (self.server_dir(server_id), data, self.backups_dir(server_id)):
            try:
                os.chmod(directory, _DIR_MODE)
            except OSError:  # pragma: no cover
                pass
        return data

    def delete(self, server_id: str, *, remove_data: bool) -> None:
        """Elimina la definicion y, si se pide, todo el contenido del servidor."""
        directory = self.server_dir(server_id)
        if not directory.is_dir():
            raise ServerNotFoundError(f"El servidor '{server_id}' no existe.")
        if remove_data:
            remove_tree(directory)
            logger.info("Servidor %s eliminado por completo", server_id)
        else:
            meta = self.meta_file(server_id)
            if meta.is_file():
                meta.unlink()
            logger.info("Definicion del servidor %s eliminada (datos conservados)", server_id)

    # --------------------------------------------------------------- puertos
    def used_ports(self, *, exclude: str | None = None) -> set[int]:
        used: set[int] = set()
        for spec in self.load_all():
            if exclude is not None and spec.id == exclude:
                continue
            used.add(spec.port)
            used.add(spec.rcon_port)
            if spec.bedrock_enabled:
                # Bedrock va por UDP, pero se reserva igual para que otro
                # servidor no publique el mismo numero en TCP o al reves.
                used.add(spec.bedrock_port)
        return used

    def allocate_port(self, preferred: int, *, exclude: str | None = None) -> int:
        """Devuelve un puerto libre, empezando por ``preferred``."""
        used = self.used_ports(exclude=exclude)
        try:
            candidate = validate_port(preferred)
        except ValidationError:
            candidate = paths.DEFAULT_PORT
        for port in range(candidate, min(candidate + 500, paths.MAX_PORT + 1)):
            if port not in used:
                return port
        for port in range(paths.MIN_PORT, paths.MAX_PORT + 1):
            if port not in used:
                return port
        raise ValidationError("port", "No hay puertos disponibles.")

    def allocate_rcon_port(self, game_port: int, *, exclude: str | None = None) -> int:
        """Puerto de consola RCON, en bucle local y distinto del puerto de juego."""
        used = self.used_ports(exclude=exclude)
        used.add(game_port)
        candidate = game_port + 1000
        for port in range(candidate, min(candidate + 500, paths.MAX_PORT + 1)):
            if port not in used:
                return port
        for port in range(paths.RCON_PORT_MIN, paths.MAX_PORT + 1):
            if port not in used:
                return port
        raise ValidationError("port", "No hay puertos RCON disponibles.")
