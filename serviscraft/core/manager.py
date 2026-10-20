"""Orquestador: une almacen, motor de contenedores, ficheros y copias.

Esta capa no depende de Qt, por lo que es completamente comprobable con pruebas
automatizadas y reutilizable desde la linea de comandos.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from .appconfig import AppConfig
from .backup import (
    ORIGENES_AUTOMATICOS,
    ORIGEN_AL_DETENER,
    ORIGEN_PROGRAMADA,
    BackupInfo,
    BackupManager,
)
from . import appearance, ddns, netinfo
from .bedrock import ensure_floodgate_auth
from .ddns import validate_subdomain, validate_token
from .diagnostics import StartFailure, diagnose_start_failure
from .errors import (
    EngineError,
    ServerStateError,
    ServiscraftError,
    ValidationError,
)
from .import_server import (
    ImportSourceError,
    ServerSourceInfo,
    copy_source,
    inspect_source,
)
from .inventory import (
    PlayerInventory,
    parse_inventory,
    parse_number,
)
from .logging_setup import get_logger
from .mods import ModsInventory, folder_for
from .models import (
    ServerSpec,
    ServerState,
    ServerStats,
    ServerType,
    ServerView,
    new_server_id,
)
from .paths import (
    CONTAINER_BEDROCK_PORT,
    CONTAINER_GAME_PORT,
    CONTAINER_RCON_PORT,
    DEFAULT_BEDROCK_PORT,
)
from .players import (
    PlayersSnapshot,
    apply_offline_action,
    build_command,
    parse_player_list,
    parse_whitelist,
    read_names_file,
    validate_player_name,
)
from .podman import (
    ID_LABEL,
    MANAGED_LABEL,
    MANAGED_LABEL_VALUE,
    PodmanClient,
    PortMapping,
)
from .properties import ServerProperties
from .rcon import RconClient, validate_console_command
from .server_files import ServerFiles
from .store import ServerStore, remove_tree
from .validation import (
    atomic_write_text,
    port_is_free,
    validate_java_tag,
    validate_memory_mb,
    validate_minecraft_version,
    validate_name,
    validate_password,
    validate_port,
)
from .versions import (
    java_major_of_tag,
    java_tag_for_major,
    recommended_java_tag,
    required_java_major,
)

logger = get_logger("manager")

#: Sobrecarga de memoria reservada al JVM (metaspace, hilos, cache de codigo).
#: Los cargadores de mods necesitan bastante mas margen que Vanilla o Paper.
JVM_OVERHEAD_MB = 768
#: Margen extra segun el tipo de servidor.
TYPE_OVERHEAD_MB = {
    ServerType.VANILLA: 768,
    ServerType.PAPER: 768,
    ServerType.FABRIC: 1024,
    ServerType.FORGE: 2048,
    # Un modpack trae cientos de mods: el cargador necesita mas margen.
    ServerType.MODRINTH: 2048,
}


def jvm_overhead_mb(server_type: ServerType) -> int:
    """Margen de memoria que se suma al heap para fijar el limite del contenedor."""
    return TYPE_OVERHEAD_MB.get(server_type, JVM_OVERHEAD_MB)


class ServerManager:
    """Punto de entrada unico para operar con los servidores."""

    def __init__(
        self,
        *,
        store: ServerStore | None = None,
        client: PodmanClient | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self.config = (config or AppConfig.load()).validated()
        self.store = store or ServerStore()
        self.client = client or PodmanClient(self.config.engine_binary)
        self.backups = BackupManager(self.store)

    # ================================================================= motor
    def check_engine(self) -> str:
        """Comprueba que Podman esta disponible y es rootless."""
        version = self.client.ensure_available()
        if not self.client.is_rootless():
            logger.warning("Podman no esta en modo rootless")
        return version

    def engine_rootless(self) -> bool:
        return self.client.is_rootless()

    # ============================================================== consultas
    def list_servers(self) -> list[ServerSpec]:
        return self.store.load_all()

    def get(self, server_id: str) -> ServerSpec:
        return self.store.load(server_id)

    def state(self, server_id: str) -> ServerState:
        spec = self.store.load(server_id)
        return self.client.container_state(spec.container_name)

    def stats(self, server_id: str) -> ServerStats:
        spec = self.store.load(server_id)
        if self.client.container_state(spec.container_name) is not ServerState.RUNNING:
            return ServerStats(available=False)
        stats = parse_stats(
            self.client.stats(spec.container_name), fallback_limit_mb=spec.memory_mb
        )
        if stats.available:
            # Podman da el 100 % por nucleo: al arrancar, Java usa varios y la
            # cifra pasa de 100 (200 % = dos nucleos). Se pasa a porcentaje del
            # equipo para que la barra y el numero nunca mientan.
            nucleos = host_cpu_count()
            stats = replace(
                stats,
                cpu_cores=nucleos,
                cpu_percent=normalize_cpu_percent(stats.cpu_percent, nucleos),
            )
        return stats

    def views(self) -> list[ServerView]:
        """Lista de servidores con su estado real (una sola consulta a Podman)."""
        states = self._container_states()
        views: list[ServerView] = []
        for spec in self.store.load_all():
            state = states.get(spec.container_name, ServerState.MISSING)
            views.append(ServerView(spec=spec, state=state, icon=self.server_icon(spec.id)))
        return views

    def _container_states(self) -> dict[str, ServerState]:
        """Estados de todos los contenedores gestionados, en una sola llamada."""
        mapping: dict[str, ServerState] = {}
        raw_states = {
            "running": ServerState.RUNNING,
            "exited": ServerState.EXITED,
            "created": ServerState.CREATED,
            "configured": ServerState.CREATED,
            "stopped": ServerState.EXITED,
            "paused": ServerState.PAUSED,
        }
        for item in self.client.managed_containers():
            names = item.get("Names") or item.get("names") or []
            if isinstance(names, str):
                names = [names]
            status = str(item.get("State") or item.get("state") or "").lower()
            for name in names:
                mapping[str(name)] = raw_states.get(status, ServerState.UNKNOWN)
        return mapping

    def files(self, server_id: str) -> ServerFiles:
        return ServerFiles(self.store, server_id)

    def mods_inventory(self, server_id: str) -> ModsInventory:
        """Mods o pluguins del servidor (la carpeta depende de su tipo).

        Se usa, por ejemplo, para recordar de que proyecto de Modrinth salio
        cada fichero y poder enseñar su icono en la lista.
        """
        spec = self.store.load(server_id)
        return ModsInventory(
            self.store,
            spec.id,
            folder=folder_for(spec),
            modpack=bool(spec.modpack) or spec.type.value == "MODRINTH",
        )

    def properties(self, server_id: str) -> ServerProperties:
        data_dir = self.store.data_dir(server_id)
        return ServerProperties.load(data_dir / "server.properties", root=data_dir)

    def save_properties(self, server_id: str, props: ServerProperties) -> None:
        spec = self.store.load(server_id)
        # Blindamos las propiedades que gestiona la aplicacion.
        props.set("server-port", str(CONTAINER_GAME_PORT))
        props.set("enable-rcon", "true")
        props.set("rcon.port", str(CONTAINER_RCON_PORT))
        props.set("rcon.password", spec.rcon_password)
        props.save(self.store.data_dir(server_id) / "server.properties")

    # ================================================================= aspecto
    def motd(self, server_id: str) -> str:
        """Descripcion del servidor que se ve en la lista de Minecraft (con colores)."""
        return appearance.motd_of(self.properties(server_id))

    def save_motd(self, server_id: str, text: str) -> str:
        """Guarda la descripcion del servidor y devuelve el texto normalizado."""
        props = self.properties(server_id)
        value = appearance.apply_motd(props, text)
        self.save_properties(server_id, props)
        logger.info("Descripcion del servidor %s actualizada", server_id)
        return value

    def server_icon(self, server_id: str) -> bytes:
        """Icono propio del servidor (vacio si nunca se ha puesto uno)."""
        return appearance.read_icon(self.store.data_dir(server_id))

    def save_icon(self, server_id: str, data: bytes) -> Path:
        """Guarda el icono de la lista de servidores (PNG de 64x64)."""
        target = appearance.save_icon(self.store.data_dir(server_id), data)
        logger.info("Icono del servidor %s actualizado", server_id)
        return target

    def clear_icon(self, server_id: str) -> bool:
        """Quita el icono propio del servidor."""
        return appearance.remove_icon(self.store.data_dir(server_id))

    def is_running(self, server_id: str) -> bool:
        return self.state(server_id) is ServerState.RUNNING

    def running_servers(self) -> list[ServerSpec]:
        """Servidores que siguen en ejecucion (por ejemplo, de una sesion anterior)."""
        return [v.spec for v in self.views() if v.running]

    # ================================================================ puertos
    def next_free_port(self, preferred: int, *, exclude: str | None = None) -> int:
        return self.store.allocate_port(preferred, exclude=exclude)

    def check_port_available(self, port: int, *, exclude: str | None = None) -> tuple[bool, str]:
        """Comprueba que el puerto no lo usa otro servidor ni otro proceso."""
        try:
            value = validate_port(port, reserved=self.store.used_ports(exclude=exclude))
        except ValidationError as exc:
            return False, exc.message
        if not port_is_free(value):
            return False, f"El puerto {value} esta ocupado por otro programa en el sistema."
        return True, ""

    @staticmethod
    def host_lan_ip() -> str:
        """Direccion IP local del equipo, para conectarse desde la red (sin trafico)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("10.255.255.255", 1))
                return str(sock.getsockname()[0])
        except OSError:  # pragma: no cover - sin red
            return "localhost"

    # ===================================================== compatibilidad de Java
    def outdated_java_tag(self, spec: ServerSpec) -> str:
        """Etiqueta de Java que habria que usar (vacia si la actual ya vale).

        Minecraft sube de vez en cuando el Java que necesita (1.20.5 paso a Java
        21 y el versionado por año, a Java 25). Un servidor creado antes de ese
        cambio se quedaba con la etiqueta antigua y moria al arrancar sin decir
        por que. Esta comprobacion detecta ese caso antes de intentarlo.
        """
        needed = required_java_major(spec.version)
        if not needed or java_major_of_tag(spec.java_tag) >= needed:
            return ""
        if not java_major_of_tag(spec.java_tag):
            # La etiqueta no sigue el esquema ``javaNN``: puede ser una imagen
            # propia con otro significado, asi que no se toca.
            return ""
        tag = java_tag_for_major(needed)
        if java_major_of_tag(tag) < needed or tag == spec.java_tag:
            return ""
        return tag

    def ensure_java_compatible(
        self, spec: ServerSpec, *, report: Callable[[str], None]
    ) -> ServerSpec:
        """Corrige la etiqueta de Java de un servidor que se quedaria corto.

        Solo cambia la definicion y vuelve a crear el contenedor: **nunca** toca
        el mundo, los mods ni los ficheros del servidor.
        """
        tag = self.outdated_java_tag(spec)
        if not tag:
            return spec
        needed = required_java_major(spec.version)
        report(
            f"El servidor usa Minecraft {spec.version} y necesita Java {needed} o "
            f"superior, pero la imagen estaba en {spec.java_tag}: se cambia a {tag}."
        )
        report("Se vuelve a crear el contenedor (el mundo y los mods no se tocan)...")
        spec.java_tag = tag
        spec = self.store.save(spec)
        if self.client.container_exists(spec.container_name):
            self.client.remove(spec.container_name, force=True)
        self._create_container(spec)
        return spec

    def diagnose_start_failure(self, server_id: str) -> StartFailure | None:
        """Explica por que un servidor se apago al arrancar.

        Devuelve ``None`` si el contenedor no esta detenido: solo tiene sentido
        cuando el servidor acaba de morir.
        """
        spec = self.store.load(server_id)
        if self.client.container_state(spec.container_name) is not ServerState.EXITED:
            return None
        if not self.client.container_exists(spec.container_name):
            return None
        texto = self.client.logs_text(spec.container_name, tail=150)
        return diagnose_start_failure(
            texto,
            version=spec.version,
            java_tag=spec.java_tag,
            image=spec.image,
        )

    def repair_start_failure(self, server_id: str, failure: StartFailure | None = None) -> bool:
        """Aplica la reparacion que propone el diagnostico.

        Devuelve ``True`` si de verdad ha cambiado algo (y por tanto merece la
        pena volver a intentar el arranque).
        """
        spec = self.store.load(server_id)
        if failure is None:
            failure = self.diagnose_start_failure(server_id)
        if failure is None or not failure.repairable:
            return False
        if java_major_of_tag(spec.java_tag) >= java_major_of_tag(failure.suggested_java_tag):
            return False
        logger.info(
            "Reparando el arranque de %s: Java %s -> %s",
            spec.id,
            spec.java_tag,
            failure.suggested_java_tag,
        )
        self.update_settings(server_id, java_tag=failure.suggested_java_tag)
        return True

    # ================================================================ Bedrock
    def bedrock_available(self, spec: ServerSpec) -> tuple[bool, str]:
        """Se puede activar Bedrock en este servidor? (``motivo`` si no)."""
        if spec.type.supports_plugins:
            return True, ""
        return (
            False,
            "Los jugadores de Bedrock entran con el pluguin Geyser, que solo existe "
            "para Paper. Crea un servidor Paper (o cambia el tipo) si quieres que "
            "tambien puedan entrar desde el movil o la consola.",
        )

    def check_bedrock_port(self, port: int, *, exclude: str | None = None) -> tuple[bool, str]:
        """Comprueba que el puerto UDP de Bedrock se puede publicar."""
        try:
            value = validate_port(port, reserved=self.store.used_ports(exclude=exclude))
        except ValidationError as exc:
            return False, exc.message
        if not port_is_free(value, protocol="udp"):
            return False, f"El puerto UDP {value} esta ocupado por otro programa."
        return True, ""

    def set_bedrock(
        self, server_id: str, *, enabled: bool, port: int | None = None
    ) -> ServerSpec:
        """Activa o desactiva los jugadores de Bedrock (Geyser + Floodgate).

        Solo cambia la definicion y vuelve a crear el contenedor: el mundo, los
        mods y los ficheros del servidor se quedan como estaban. Los pluguins los
        descarga la propia imagen al arrancar (por eso se reinstala en
        ``data/plugins``).
        """
        spec = self.store.load(server_id)
        if self.client.container_state(spec.container_name) is ServerState.RUNNING:
            raise ServerStateError(
                "Deten el servidor antes de cambiar los jugadores de Bedrock."
            )
        if enabled:
            disponible, motivo = self.bedrock_available(spec)
            if not disponible:
                raise ValidationError("bedrock", motivo)
            elegido = port or spec.bedrock_port or DEFAULT_BEDROCK_PORT
            ok, message = self.check_bedrock_port(elegido, exclude=spec.id)
            if not ok and port is None:
                # Se busca el siguiente libre (19132, 19133, ...).
                for candidato in range(DEFAULT_BEDROCK_PORT, DEFAULT_BEDROCK_PORT + 20):
                    if self.check_bedrock_port(candidato, exclude=spec.id)[0]:
                        elegido, ok, message = candidato, True, ""
                        break
            if not ok:
                raise ValidationError("bedrock", message)
            spec.bedrock = True
            spec.bedrock_port = elegido
        else:
            spec.bedrock = False
        spec = self.store.save(spec)
        logger.info(
            "Bedrock %s en %s (puerto UDP %s)",
            "activado" if spec.bedrock else "desactivado",
            spec.id,
            spec.bedrock_port,
        )
        if self.client.container_exists(spec.container_name):
            self.client.remove(spec.container_name, force=True)
        self._create_container(spec)
        return spec

    def apply_bedrock_config(self, server_id: str) -> bool:
        """Deja Geyser en modo Floodgate si ya genero su configuracion.

        Hace falta porque Geyser crea su ``config.yml`` en el primer arranque y
        por defecto pide cuentas de Java. Devuelve ``True`` si ha cambiado algo
        (y por tanto hay que reiniciar para aplicarlo).
        """
        spec = self.store.load(server_id)
        if not spec.bedrock_enabled:
            return False
        return ensure_floodgate_auth(self.store.data_dir(spec.id))

    # ==================================================== nombre personalizado
    def configure_ddns(
        self,
        server_id: str,
        *,
        subdomain: str,
        token: str | None = None,
        auto: bool | None = None,
    ) -> ServerSpec:
        """Guarda el nombre personalizado (DuckDNS) del servidor.

        ``subdomain`` vacio quita el nombre (se vuelve a entra con la IP). El
        token no se cambia si no se pasa uno nuevo: asi se puede corregir el
        nombre o la casilla de actualizacion automatica sin volver a pegarlo.
        """
        spec = self.store.load(server_id)
        limpio = validate_subdomain(subdomain) if str(subdomain or "").strip() else ""
        if not limpio:
            spec.ddns_subdomain = ""
            spec.ddns_token = ""
            spec.ddns_auto = False
            spec.ddns_last_ip = ""
            guardado = self.store.save(spec)
            logger.info("Nombre personalizado quitado de %s", server_id)
            return guardado
        if token is not None:
            spec.ddns_token = validate_token(token)
        spec.ddns_subdomain = limpio
        if auto is not None:
            spec.ddns_auto = bool(auto)
        if spec.ddns_auto and not spec.ddns_token:
            raise ValidationError(
                "ddns",
                "Para refrescar la direccion sola hace falta el token de DuckDNS.",
            )
        guardado = self.store.save(spec)
        logger.info(
            "Nombre personalizado de %s: %s (automatico=%s)",
            server_id,
            ddns.hostname(limpio),
            guardado.ddns_auto,
        )
        return guardado

    def ddns_status(self, server_id: str, *, public_ip: str = "") -> ddns.DdnsStatus:
        """Comprueba si el nombre del servidor resuelve y apunta a esta casa."""
        spec = self.store.load(server_id)
        return ddns.check(spec.ddns_subdomain, public_ip=public_ip, puerto=spec.port)

    def ddns_update(self, server_id: str, *, public_ip: str = "") -> str:
        """Pide a DuckDNS que apunte el nombre a la IP publica actual.

        Devuelve la respuesta de DuckDNS (``OK``). Si no se conoce la IP publica
        se deja que DuckDNS use la de salida (la peticion la ve el propio
        servicio): asi funciona incluso detras de un operador con IP dinamica.
        """
        spec = self.store.load(server_id)
        if not spec.ddns_configured:
            raise ValidationError("ddns", "Este servidor no tiene un nombre personalizado.")
        direccion = str(public_ip or "").strip()
        respuesta = ddns.update(spec.ddns_subdomain, spec.ddns_token, ip=direccion)
        if direccion:
            spec.ddns_last_ip = direccion
        else:
            # No se conocia la IP: se guarda la que acaba de publicar DuckDNS.
            resueltas = ddns.resolve(ddns.hostname(spec.ddns_subdomain))
            if resueltas:
                spec.ddns_last_ip = sorted(resueltas)[0]
        self.store.save(spec)
        return respuesta

    def ddns_auto_update(self, server_id: str, *, public_ip: str) -> bool:
        """Refresca el nombre al arrancar si la IP publica ha cambiado.

        Devuelve ``True`` si se actualizo. Nunca interrumpe el arranque: si
        DuckDNS no contesta, se avisa en el registro y el servidor sigue
        funcionando con la direccion que ya tenia.
        """
        try:
            spec = self.store.load(server_id)
        except ServiscraftError as exc:  # pragma: no cover - definicion danada
            logger.warning("No se pudo leer %s para actualizar DuckDNS: %s", server_id, exc)
            return False
        if not (spec.ddns_configured and spec.ddns_auto and spec.ddns_token):
            return False
        if not ddns.needs_update(last_ip=spec.ddns_last_ip, current_ip=public_ip):
            return False
        try:
            self.ddns_update(server_id, public_ip=public_ip)
        except ServiscraftError as exc:
            logger.warning("DuckDNS no se pudo actualizar en %s: %s", server_id, exc)
            return False
        return True

    # ================================================================ importar
    def import_server(
        self,
        source: str | os.PathLike[str],
        *,
        name: str | None = None,
        server_type: ServerType | str | None = None,
        version: str | None = None,
        memory_mb: int | None = None,
        port: int | None = None,
        java_tag: str | None = None,
        lan: bool = True,
        notes: str = "",
        on_progress: Callable[[str], None] | None = None,
        on_files: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[ServerSpec, ServerSourceInfo]:
        """Crea un servidor a partir de una carpeta o un ``.zip`` ya existentes.

        El contenedor no se crea aqui: se monta al arrancar, como en cualquier
        otro servidor. Asi importar un servidor exportado de Aternos no obliga a
        descargar su imagen ni a tener internet en ese momento.
        """
        def report(message: str) -> None:
            logger.info("[importar] %s", message)
            if on_progress is not None:
                on_progress(message)

        report("Reconociendo el servidor...")
        info = inspect_source(source)
        clean_name = validate_name(name or info.name)
        tipo = ServerType.from_value(server_type or info.server_type)
        clean_version = validate_minecraft_version(version or info.version)
        memory = validate_memory_mb(
            memory_mb if memory_mb is not None else self.config.default_memory_mb
        )

        if port is None:
            # Se conserva el puerto del servidor original si sigue libre: asi los
            # jugadores de siempre no tienen que cambiar la direccion.
            selected_port = self.store.allocate_port(info.port)
        else:
            ok, message = self.check_port_available(port)
            if not ok:
                raise ValidationError("port", message)
            selected_port = validate_port(port, reserved=self.store.used_ports())

        raiz = self.store.root if self.store.root.exists() else self.store.root.parent
        libre = shutil.disk_usage(raiz).free
        if info.total_bytes and libre < info.total_bytes + 256 * 1024 * 1024:
            raise ImportSourceError(
                "No hay espacio suficiente en el disco para copiar este servidor "
                f"(hacen falta unos {info.total_bytes // (1024 * 1024)} MB mas)."
            )

        server_id = new_server_id(clean_name)
        spec = ServerSpec(
            id=server_id,
            name=clean_name,
            type=tipo,
            version=clean_version,
            memory_mb=memory,
            port=selected_port,
            rcon_port=self.store.allocate_rcon_port(selected_port),
            rcon_password=validate_password(secrets.token_urlsafe(24)),
            image=self.config.image,
            java_tag=java_tag or recommended_java_tag(clean_version),
            lan=lan,
            notes=notes,
        ).validated()

        data_dir = self.store.prepare_dirs(spec.id)
        try:
            if info.origin:
                report(
                    f"Servidor de {info.origin} reconocido ({info.summary()}). Copiando sus datos..."
                )
            else:
                report(f"Servidor reconocido ({info.summary()}). Copiando sus datos...")
            copiados = copy_source(
                info,
                data_dir,
                on_progress=on_files,
                should_cancel=should_cancel,
            )
            report(f"Copiados {copiados} ficheros. Ajustando la configuracion...")
            self._prepare_imported_data(spec)
            self.store.save(spec)
        except BaseException:
            # Solo se borra lo que se acaba de crear para esta importacion.
            remove_tree(self.store.server_dir(spec.id))
            raise
        logger.info(
            "Servidor %s importado desde %s (%s ficheros)",
            spec.id,
            info.path,
            copiados,
        )
        return spec, info

    def _prepare_imported_data(self, spec: ServerSpec) -> None:
        """Deja ``server.properties`` y ``eula.txt`` como los necesita el contenedor.

        Los puertos de dentro del contenedor son siempre los mismos (25565 y
        25575), y RCON necesita la contrasena que ha generado la aplicacion. El
        resto de la configuracion importada se respeta tal cual, y el EULA se
        acepta porque el servidor ya venia funcionando.
        """
        data_dir = self.store.data_dir(spec.id)
        properties_path = data_dir / "server.properties"
        if properties_path.is_file():
            try:
                properties = ServerProperties.load(properties_path, root=data_dir)
            except ServiscraftError:
                properties = ServerProperties(path=properties_path)
            properties.set("server-port", str(CONTAINER_GAME_PORT))
            properties.set("enable-rcon", "true")
            properties.set("rcon.port", str(CONTAINER_RCON_PORT))
            properties.set("rcon.password", spec.rcon_password)
            properties.save(properties_path)
        else:
            self._write_initial_properties(spec)
        try:
            atomic_write_text(data_dir / "eula.txt", "eula=true\n", role="eula.txt")
        except ServiscraftError as exc:  # pragma: no cover - permisos raros
            logger.warning("No se pudo escribir eula.txt: %s", exc)
        icon = data_dir / "server-icon.png"
        if icon.is_file():
            try:
                # El contenedor lo lee con el mismo usuario; 0600 es de sobra.
                os.chmod(icon, 0o600)
            except OSError:  # pragma: no cover
                pass

    # ================================================================ creacion
    def create_server(
        self,
        *,
        name: str,
        type: ServerType | str,  # noqa: A002 - nombre de parametro requerido por la API
        version: str,
        memory_mb: int | None = None,
        port: int | None = None,
        java_tag: str | None = None,
        lan: bool = True,
        rcon_password: str | None = None,
        image: str | None = None,
        notes: str = "",
        extra_env: dict[str, str] | None = None,
        bedrock: bool = False,
        bedrock_port: int | None = None,
        on_progress: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ServerSpec:
        """Crea un servidor nuevo (contenedor creado pero **detenido**)."""
        def report(message: str) -> None:
            logger.info("[crear] %s", message)
            if on_progress is not None:
                on_progress(message)

        server_type = ServerType.from_value(type)
        clean_name = validate_name(name)
        clean_version = validate_minecraft_version(version)
        memory = validate_memory_mb(memory_mb if memory_mb is not None else self.config.default_memory_mb)

        if port is None:
            selected_port = self.store.allocate_port(self.config.default_port)
        else:
            ok, message = self.check_port_available(port)
            if not ok:
                raise ValidationError("port", message)
            selected_port = validate_port(port, reserved=self.store.used_ports())

        password = validate_password(rcon_password or secrets.token_urlsafe(24))
        server_id = new_server_id(clean_name)
        spec = ServerSpec(
            id=server_id,
            name=clean_name,
            type=server_type,
            version=clean_version,
            memory_mb=memory,
            port=selected_port,
            rcon_port=self.store.allocate_rcon_port(selected_port),
            rcon_password=password,
            image=image or self.config.image,
            java_tag=java_tag or recommended_java_tag(clean_version),
            lan=lan,
            notes=notes,
            extra_env=dict(extra_env or {}),
        ).validated()

        if bedrock:
            # Los jugadores de Bedrock necesitan Geyser (solo existe para Paper).
            disponible, motivo = self.bedrock_available(spec)
            if not disponible:
                raise ValidationError("bedrock", motivo)
            elegido = bedrock_port or DEFAULT_BEDROCK_PORT
            ok, message = self.check_bedrock_port(elegido, exclude=spec.id)
            if not ok and bedrock_port is None:
                for candidato in range(DEFAULT_BEDROCK_PORT, DEFAULT_BEDROCK_PORT + 20):
                    if self.check_bedrock_port(candidato, exclude=spec.id)[0]:
                        elegido, ok, message = candidato, True, ""
                        break
            if not ok:
                raise ValidationError("bedrock", message)
            spec.bedrock = True
            spec.bedrock_port = elegido

        report(f"Preparando el servidor «{spec.name}»...")
        self.store.prepare_dirs(spec.id)
        self.store.save(spec)
        self._write_initial_properties(spec)

        try:
            self._ensure_image(spec, report=report, should_cancel=should_cancel)
            report("Creando el contenedor...")
            self._create_container(spec)
        except Exception:
            # No dejamos restos a medias: se conserva la carpeta de datos por si el
            # usuario quiere reintentar, pero se retira la definicion incompleta.
            logger.exception("Fallo creando el servidor %s", spec.id)
            if self.client.container_exists(spec.container_name):
                self.client.remove(spec.container_name, force=True)
            raise

        report("Servidor creado y detenido. Pulsa Iniciar para arrancarlo.")
        return spec

    def _write_initial_properties(self, spec: ServerSpec) -> None:
        path = self.store.data_dir(spec.id) / "server.properties"
        if path.is_file():
            return
        props = ServerProperties(path=path)
        props.set("motd", f"{spec.name} - Serviscraft")
        props.set("level-name", "world")
        props.set("difficulty", "easy")
        props.set("gamemode", "survival")
        props.set("max-players", "20")
        props.set("online-mode", "true")
        props.set("white-list", "false")
        props.set("view-distance", "10")
        props.set("simulation-distance", "10")
        props.set("server-port", str(CONTAINER_GAME_PORT))
        props.set("enable-rcon", "true")
        props.set("rcon.port", str(CONTAINER_RCON_PORT))
        props.set("rcon.password", spec.rcon_password)
        props.save(path)

    # ================================================================= imagenes
    def image_reference(self, spec: ServerSpec) -> str:
        return spec.image_ref

    def _ensure_image(
        self,
        spec: ServerSpec,
        *,
        report: Callable[[str], None],
        should_cancel: Callable[[], bool] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        reference = self.image_reference(spec)
        if self.client.image_exists(reference):
            report(f"La imagen {reference} ya esta descargada.")
            return
        report(f"Descargando la imagen {reference} (puede tardar unos minutos)...")
        self.client.pull_streaming(
            reference,
            on_line=on_line,
            should_cancel=should_cancel,
        )
        report("Imagen descargada.")

    def ensure_image(
        self,
        spec: ServerSpec,
        *,
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        """Garantiza que la imagen OCI del servidor esta disponible en local."""

        def report(message: str) -> None:
            logger.info("[imagen] %s", message)
            if on_progress is not None:
                on_progress(message)

        self._ensure_image(spec, report=report, should_cancel=should_cancel, on_line=on_line)

    # =============================================================== contenedor
    def _container_runtime(self, spec: ServerSpec) -> tuple[str | None, dict[str, str]]:
        """Calcula el mapeo de usuario y las variables ``UID``/``GID``.

        Podman rootless no mapea por defecto el usuario del host al mismo UID
        dentro del contenedor, por lo que un servidor que escribe como uid 1000
        dejaria los mundos con un propietario ajeno (ilegibles desde la
        aplicacion). Con ``--userns=keep-id`` el UID del host se conserva dentro
        del contenedor y los ficheros siguen siendo nuestros.
        """
        if not self.config.userns_keep_id:
            return None, {}

        # Si la imagen ya define un usuario numerico distinto de root, ese es el
        # UID al que hay que mapear; en caso contrario usamos el del host (la
        # imagen oficial de Minecraft cambia al usuario ``minecraft`` segun UID).
        container_uid = os.getuid()
        container_gid = os.getgid()
        image_user = (self.client.image_default_user(spec.image_ref) or "").strip()
        primary = image_user.split(":")[0].strip() if image_user else ""
        if primary.isdigit() and primary != "0":
            container_uid = int(primary)
            secondary = image_user.split(":")[1].strip() if ":" in image_user else ""
            container_gid = int(secondary) if secondary.isdigit() else container_uid

        userns = f"keep-id:uid={container_uid},gid={container_gid}"
        return userns, {"UID": str(container_uid), "GID": str(container_gid)}

    def container_user(self) -> tuple[int, int]:
        """Usuario y grupo con los que se ejecuta el servidor dentro del contenedor."""
        uid = os.getuid()
        return uid, os.getgid()

    def _create_container(self, spec: ServerSpec) -> str:
        """Crea el contenedor del servidor (sin iniciarlo)."""
        if self.client.container_exists(spec.container_name):
            return self.client.container_id(spec.container_name)

        data_dir = self.store.data_dir(spec.id)
        data_dir.mkdir(parents=True, exist_ok=True)

        userns, runtime_env = self._container_runtime(spec)
        run_uid, run_gid = self.container_user()

        published: list[PortMapping] = [
            (spec.bind_address(), spec.port, CONTAINER_GAME_PORT),
            # La consola RCON solo se publica en el bucle local: nunca en la red.
            ("127.0.0.1", spec.rcon_port, CONTAINER_RCON_PORT),
        ]
        if spec.bedrock_enabled:
            # Los jugadores de Bedrock entran por UDP; Geyser escucha en 19132
            # dentro del contenedor y se publica el puerto elegido en el host.
            published.append(
                (spec.bind_address(), spec.bedrock_port, CONTAINER_BEDROCK_PORT, "udp")
            )
        volumes = [(str(data_dir), "/data", "Z")]
        labels = {
            MANAGED_LABEL: MANAGED_LABEL_VALUE,
            ID_LABEL: spec.id,
        }
        extra_args = ("--memory", f"{spec.memory_mb + jvm_overhead_mb(spec.type)}m")

        env = spec.container_env(
            run_uid=int(runtime_env.get("UID", run_uid)),
            run_gid=int(runtime_env.get("GID", run_gid)),
        )
        container_id = self.client.create(
            name=spec.container_name,
            image=spec.image_ref,
            env=env,
            published_ports=published,
            volumes=volumes,
            labels=labels,
            userns=userns,
            extra_args=extra_args,
        )
        logger.info("Contenedor %s creado (%s) con userns=%s", spec.container_name, container_id[:12], userns)
        return container_id

    # ================================================================ arranque
    def start_server(
        self,
        server_id: str,
        *,
        on_progress: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        wait_ready: bool = False,
        wait_timeout: float = 300.0,
    ) -> ServerSpec:
        """Descarga la imagen si hace falta, crea el contenedor y lo inicia."""
        spec = self.store.load(server_id)

        def report(message: str) -> None:
            logger.info("[iniciar %s] %s", spec.name, message)
            if on_progress is not None:
                on_progress(message)

        state = self.client.container_state(spec.container_name)
        if state is ServerState.RUNNING:
            report("El servidor ya estaba en ejecucion.")
            return spec

        # Antes de nada: si la version de Minecraft pide mas Java que la imagen
        # configurada, se corrige aqui (un servidor antiguo se quedaba con la
        # etiqueta vieja y no arrancaba).
        spec = self.ensure_java_compatible(spec, report=report)

        ok, message = self.check_port_available(spec.port, exclude=spec.id)
        if not ok:
            raise ValidationError("port", message)

        self._ensure_image(spec, report=report, should_cancel=should_cancel)
        if not self.client.container_exists(spec.container_name):
            report("El contenedor no existia; se vuelve a crear.")
            self._create_container(spec)

        report("Iniciando el servidor...")
        if not self.data_dir_writable(spec.id):
            report("AVISO: no se puede escribir en la carpeta del servidor. " + self.ownership_hint(spec.id))
        try:
            self.client.start(spec.container_name)
        except EngineError as exc:
            if "already running" in str(exc).lower():
                report("El servidor ya estaba en ejecucion.")
            else:
                raise

        spec.last_started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.store.save(spec)

        # Nombre personalizado: si esta activado, se aprovecha el arranque para
        # comprobar que la direccion sigue apuntando a casa. Nunca impide jugar:
        # cualquier fallo se queda en el registro.
        if spec.ddns_configured and spec.ddns_auto:
            report("Comprobando el nombre personalizado del servidor...")
            actual = netinfo.public_ip()
            if self.ddns_auto_update(spec.id, public_ip=actual):
                report("La direccion del servidor se ha actualizado sola.")

        if wait_ready:
            report("Esperando a que el servidor termine de arrancar...")
            if not self.client.wait_healthy(spec.container_name, timeout=wait_timeout):
                report("El servidor no confirmo el arranque todavia; revisa la consola.")
        return spec

    def stop_server(
        self,
        server_id: str,
        *,
        force: bool = False,
        make_backup: bool = True,
        on_progress: Callable[[str], None] | None = None,
    ) -> ServerSpec:
        """Detiene el servidor de forma ordenada (guardando el mundo).

        Si ``make_backup`` y la preferencia ``backup_on_stop`` estan activas, se
        crea una copia de seguridad justo despues de apagarse: es el momento en
        el que el mundo esta guardado y coherente. Un fallo al copiar **nunca**
        impide detener el servidor.
        """
        spec = self.store.load(server_id)

        def report(message: str) -> None:
            logger.info("[detener %s] %s", spec.name, message)
            if on_progress is not None:
                on_progress(message)

        state = self.client.container_state(spec.container_name)
        if state is ServerState.MISSING:
            report("El servidor no tiene contenedor; nada que detener.")
            return spec
        if state is not ServerState.RUNNING:
            report("El servidor ya estaba detenido.")
            return spec

        if force:
            report("Forzando la parada del servidor...")
            self.client.kill(spec.container_name)
            self._backup_after_stop(spec, report=report, make_backup=make_backup)
            return spec

        report("Guardando el mundo y deteniendo el servidor (puede tardar)...")
        try:
            self.client.stop(spec.container_name, timeout=self.config.stop_timeout_s)
        except EngineError as exc:
            logger.warning("Parada ordenada fallida: %s", exc)
            report("La parada ordenada fallo; se fuerza el cierre.")
            self.client.kill(spec.container_name)
        report("Servidor detenido.")
        self._backup_after_stop(spec, report=report, make_backup=make_backup)
        return spec

    def _backup_after_stop(
        self,
        spec: ServerSpec,
        *,
        report: Callable[[str], None],
        make_backup: bool,
    ) -> BackupInfo | None:
        """Copia de seguridad automatica tras apagar un servidor (si esta activada)."""
        if not make_backup or not self.config.backup_on_stop:
            return None
        report("Creando la copia de seguridad automatica...")
        try:
            info = self.backups.create_backup(
                spec.id,
                label="al-detener",
                origin=ORIGEN_AL_DETENER,
            )
        except ServiscraftError as exc:
            # Que no se pueda copiar no debe impedir apagar el servidor.
            logger.warning("No se pudo crear la copia automatica de %s: %s", spec.name, exc)
            report(f"AVISO: no se pudo crear la copia de seguridad automatica ({exc})")
            return None
        self.prune_automatic_backups(spec.id)
        report(f"Copia automatica creada en {info.path}")
        return info

    def restart_server(
        self,
        server_id: str,
        *,
        make_backup: bool = True,
        on_progress: Callable[[str], None] | None = None,
    ) -> ServerSpec:
        """Reinicia el servidor guardando el mundo y copiandolo antes de arrancar.

        Se hace parada ordenada + arranque (en vez de un reinicio brusco del
        contenedor) para que el mundo se guarde bien y la copia automatica de
        seguridad sea coherente.
        """
        spec = self.store.load(server_id)

        def report(message: str) -> None:
            logger.info("[reiniciar %s] %s", spec.name, message)
            if on_progress is not None:
                on_progress(message)

        if not self.client.container_exists(spec.container_name):
            return self.start_server(server_id, on_progress=on_progress)

        report("Reiniciando el servidor...")
        if self.client.container_state(spec.container_name) is ServerState.RUNNING:
            self.stop_server(server_id, make_backup=make_backup, on_progress=on_progress)
        return self.start_server(server_id, on_progress=on_progress)

    def stop_all(self, *, on_progress: Callable[[str], None] | None = None) -> list[str]:
        """Detiene todos los servidores en ejecucion. Devuelve sus identificadores."""
        stopped: list[str] = []
        for spec in self.running_servers():
            try:
                self.stop_server(spec.id, on_progress=on_progress)
                stopped.append(spec.id)
            except ServiscraftError as exc:
                logger.error("No se pudo detener %s: %s", spec.name, exc)
        return stopped

    # ============================================================ copias varias
    def backup_server(
        self,
        server_id: str,
        *,
        label: str = "",
        origin: str = "manual",
        on_progress: Callable[[int, int], None] | None = None,
    ) -> BackupInfo | None:
        """Crea una copia de un servidor. Devuelve ``None`` si no se pudo."""
        try:
            info = self.backups.create_backup(
                server_id,
                label=label,
                origin=origin,
                on_progress=on_progress,
            )
        except ServiscraftError as exc:
            logger.warning("No se pudo copiar %s: %s", server_id, exc)
            return None
        if origin in ORIGENES_AUTOMATICOS:
            self.prune_automatic_backups(server_id)
        return info

    def backup_servers(
        self,
        server_ids: list[str],
        *,
        label: str = "",
        origin: str = "manual",
        on_progress: Callable[[str], None] | None = None,
    ) -> list[BackupInfo]:
        """Copia varios servidores seguidos. Los fallos no detienen el resto."""
        created: list[BackupInfo] = []
        for server_id in server_ids:
            try:
                spec = self.store.load(server_id)
            except ServiscraftError as exc:
                logger.warning("Servidor desconocido al copiar %s: %s", server_id, exc)
                continue
            if on_progress is not None:
                on_progress(f"Copiando «{spec.name}»...")
            info = self.backup_server(server_id, label=label, origin=origin)
            if info is not None:
                created.append(info)
        return created

    def backup_running_servers(
        self,
        *,
        label: str = "programada",
        origin: str = ORIGEN_PROGRAMADA,
        on_progress: Callable[[str], None] | None = None,
    ) -> list[BackupInfo]:
        """Copia los servidores que estan en ejecucion (copia programada)."""
        ids = [view.spec.id for view in self.views() if view.running]
        if not ids:
            return []
        logger.info("Copia automatica programada de %d servidor(es)", len(ids))
        return self.backup_servers(ids, label=label, origin=origin, on_progress=on_progress)

    def prune_automatic_backups(self, server_id: str, *, keep: int | None = None) -> int:
        """Aplica la retencion configurada a las copias automaticas del servidor."""
        limit = self.config.automatic_backup_keep if keep is None else keep
        if limit <= 0:
            return 0
        return self.backups.prune(server_id, keep=limit, origins=ORIGENES_AUTOMATICOS)

    def backups_folder(self, server_id: str) -> str:
        """Ruta de la carpeta donde se guardan las copias de un servidor."""
        return str(self.store.backups_dir(server_id))

    # ================================================================== borrado
    def delete_server(
        self,
        server_id: str,
        *,
        delete_data: bool,
        make_backup: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> BackupInfo | None:
        """Elimina un servidor. Requiere confirmacion previa en la interfaz."""
        spec = self.store.load(server_id)

        def report(message: str) -> None:
            logger.info("[eliminar %s] %s", spec.name, message)
            if on_progress is not None:
                on_progress(message)

        backup: BackupInfo | None = None
        if make_backup:
            report("Creando una copia de seguridad antes de eliminar...")
            backup = self.backups.create_backup(server_id, label="antes-de-eliminar", origin="automatica")

        if self.client.container_exists(spec.container_name):
            state = self.client.container_state(spec.container_name)
            if state is ServerState.RUNNING:
                report("Deteniendo el servidor...")
                # Ya se ha hecho (o se va a hacer) la copia «antes-de-eliminar»:
                # no tiene sentido crear ademas la copia automatica de parada.
                self.stop_server(server_id, make_backup=False, on_progress=on_progress)
            report("Eliminando el contenedor...")
            self.client.remove(spec.container_name, force=True)

        if delete_data and backup is None:
            report("Eliminando los ficheros del servidor...")
            self.store.delete(server_id, remove_data=True)
        elif delete_data:
            # Conservamos la carpeta con las copias de seguridad: el usuario podra
            # restaurarlas mas adelante desde la pestana de copias.
            report("Eliminando los datos (las copias de seguridad se conservan)...")
            data_dir = self.store.data_dir(server_id)
            if data_dir.is_dir():
                for item in data_dir.iterdir():
                    if item.is_dir():
                        remove_tree(item)
                    else:
                        item.unlink(missing_ok=True)
            note = self.store.server_dir(server_id) / "SERVIDOR-ELIMINADO.txt"
            note.write_text(
                "Este servidor se elimino desde Serviscraft.\n"
                "Sus copias de seguridad siguen en la subcarpeta 'backups' y pueden\n"
                "restaurarse con la accion «Importar copia» de la pestana Copias.\n",
                encoding="utf-8",
            )
            self.store.delete(server_id, remove_data=False)
        else:
            self.store.delete(server_id, remove_data=False)

        report("Servidor eliminado.")
        return backup

    def recreate_container(
        self,
        server_id: str,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> ServerSpec:
        """Recrea el contenedor conservando los datos (util si la definicion cambio)."""
        spec = self.store.load(server_id)
        if self.client.container_state(spec.container_name) is ServerState.RUNNING:
            raise ServerStateError("Deten el servidor antes de recrear el contenedor.")
        if self.client.container_exists(spec.container_name):
            self.client.remove(spec.container_name, force=True)
        self._create_container(spec)
        if on_progress is not None:
            on_progress("Contenedor recreado.")
        return spec

    # ================================================================== consola
    def send_command(self, server_id: str, command: str, *, timeout: float = 8.0) -> str:
        """Envia un comando a la consola del servidor por RCON."""
        spec = self.store.load(server_id)
        cleaned = validate_console_command(command)
        if self.client.container_state(spec.container_name) is not ServerState.RUNNING:
            raise ServerStateError("El servidor no esta en ejecucion.")
        with RconClient("127.0.0.1", spec.rcon_port, spec.rcon_password, timeout=timeout) as client:
            return client.command(cleaned)

    # ============================================================== jugadores
    def players_snapshot(self, server_id: str) -> PlayersSnapshot:
        """Estado de los jugadores: conectados, lista blanca y operadores.

        Los conectados solo se pueden saber con el servidor en marcha (comando
        ``list`` por RCON). La lista blanca y los operadores se leen ademas de
        ``whitelist.json`` y ``ops.json``, asi que la pestana sigue siendo util
        con el servidor detenido.
        """
        spec = self.store.load(server_id)
        data_dir = self.store.data_dir(spec.id)
        whitelist = tuple(read_names_file(data_dir / "whitelist.json"))
        ops = tuple(read_names_file(data_dir / "ops.json"))
        banned = tuple(read_names_file(data_dir / "banned-players.json"))
        running = self.client.container_state(spec.container_name) is ServerState.RUNNING
        enabled = self.properties(spec.id).get_bool("white-list", False)

        online: tuple[str, ...] = ()
        maximum = 0
        note = ""
        if running:
            try:
                players, maximum = parse_player_list(self.send_command(server_id, "list"))
                online = tuple(players)
                response = self.send_command(server_id, "whitelist list")
                live_whitelist = parse_whitelist(response)
                if live_whitelist:
                    whitelist = tuple(sorted(set(live_whitelist), key=str.lower))
            except ServiscraftError as exc:
                note = f"No se pudo consultar la consola del servidor: {exc}"
                logger.warning("Sin datos en vivo de jugadores de %s: %s", spec.name, exc)
        else:
            note = (
                "El servidor esta detenido: las listas se pueden cambiar igualmente y se "
                "guardan para el proximo arranque. Para ver quien esta conectado, inicia "
                "el servidor."
            )

        return PlayersSnapshot(
            online=online,
            max_players=maximum,
            whitelist=whitelist,
            ops=ops,
            banned=banned,
            whitelist_enabled=enabled,
            running=running,
            note=note,
        )

    def run_player_action(self, server_id: str, action: str, player: str | None = None) -> str:
        """Aplica una accion de jugador, con el servidor encendido o apagado.

        En marcha se usa la consola (el servidor actualiza sus listas al momento
        y el cambio surte efecto ya). Detenido se escriben las mismas listas en
        disco, de modo que preparar la lista blanca o bloquear a alguien no
        obliga a tener el servidor encendido. Expulsar si necesita la consola.
        """
        spec = self.store.load(server_id)
        running = self.client.container_state(spec.container_name) is ServerState.RUNNING
        if not running:
            logger.info(
                "Accion de jugador sin servidor en %s: %s %s",
                server_id,
                action,
                player or "",
            )
            return apply_offline_action(self.store.data_dir(spec.id), action, player or "")
        command = build_command(action, player)
        logger.info("Accion de jugador en %s: %s", server_id, command)
        return self.send_command(server_id, command)

    def set_whitelist_enabled(self, server_id: str, enabled: bool) -> bool:
        """Activa o desactiva la lista blanca y lo aplica si el servidor esta vivo."""
        spec = self.store.load(server_id)
        properties = self.properties(spec.id)
        properties.set("white-list", "true" if enabled else "false")
        data_dir = self.store.data_dir(spec.id)
        properties.save(data_dir / "server.properties")
        if self.client.container_state(spec.container_name) is ServerState.RUNNING:
            try:
                self.send_command(server_id, "whitelist on" if enabled else "whitelist off")
            except ServiscraftError as exc:  # pragma: no cover - consola ocupada
                logger.warning("No se pudo aplicar la lista blanca en vivo: %s", exc)
        logger.info("Lista blanca de %s: %s", spec.name, "activada" if enabled else "desactivada")
        return enabled

    # ================================================================ inventario
    def player_inventory(self, server_id: str, player: str) -> PlayerInventory:
        """Lee lo que lleva encima un jugador conectado (vida, comida, mochila).

        Se pregunta al servidor con ``data get entity`` a traves de la consola
        (RCON, en el bucle local). El jugador tiene que estar **conectado**: si no
        lo esta, el servidor responde que no encuentra la entidad y se avisa con
        un mensaje claro.
        """
        spec = self.store.load(server_id)
        name = validate_player_name(player)
        if self.client.container_state(spec.container_name) is not ServerState.RUNNING:
            raise ServerStateError("El servidor no esta en ejecucion.")
        respuesta = self.send_command(server_id, f"data get entity {name} Inventory")
        if "entity data" not in respuesta:
            raise ServerStateError(
                f"No se pudo leer el inventario de «{name}»: tiene que estar conectado "
                "al servidor en este momento. El servidor respondio: "
                f"{respuesta.strip() or 'sin respuesta'}"
            )
        items, recortado = parse_inventory(respuesta)
        nota = (
            "El inventario es muy largo y el servidor no lo devolvio entero: "
            "se muestran los primeros objetos."
            if recortado
            else ""
        )
        return PlayerInventory(
            player=name,
            items=tuple(items),
            health=self._player_number(server_id, name, "Health"),
            food=self._player_number(server_id, name, "foodLevel"),
            level=self._player_number(server_id, name, "XpLevel"),
            truncated=recortado,
            note=nota,
        )

    def _player_number(self, server_id: str, name: str, campo: str) -> float | None:
        """Lee un dato numerico suelto del jugador (no es grave si falla)."""
        try:
            return parse_number(self.send_command(server_id, f"data get entity {name} {campo}"))
        except ServiscraftError as exc:  # pragma: no cover - el inventario ya se leyo
            logger.debug("No se pudo leer %s de %s: %s", campo, name, exc)
            return None

    # ================================================================== consola
    def recent_logs(self, server_id: str, *, tail: int | None = None) -> str:
        """Ultimas lineas visibles de la consola del servidor."""
        spec = self.store.load(server_id)
        if not self.client.container_exists(spec.container_name):
            return ""
        return self.client.logs_text(spec.container_name, tail=tail or self.config.console_tail_lines)

    def console_command(self, server_id: str, *, tail: int | None = None) -> list[str]:
        """Argumentos para seguir la consola en tiempo real (usado con QProcess)."""
        spec = self.store.load(server_id)
        return self.client.logs_args(spec.container_name, tail=tail or self.config.console_tail_lines)

    # ============================================================== servidores
    def update_settings(
        self,
        server_id: str,
        *,
        name: str | None = None,
        memory_mb: int | None = None,
        port: int | None = None,
        lan: bool | None = None,
        notes: str | None = None,
        version: str | None = None,
        java_tag: str | None = None,
    ) -> ServerSpec:
        """Actualiza los ajustes de un servidor detenido y recrea su contenedor.

        ``version`` permite cambiar la version de Minecraft sin perder el mundo
        ni el contenido. El contenedor se vuelve a crear para que la imagen
        prepare el servidor de la version elegida en el siguiente arranque.
        """
        spec = self.store.load(server_id)
        if self.client.container_state(spec.container_name) is ServerState.RUNNING:
            raise ServerStateError("Deten el servidor antes de cambiar sus ajustes.")

        if name is not None:
            spec.name = validate_name(name)
        if memory_mb is not None:
            spec.memory_mb = validate_memory_mb(memory_mb)
        if notes is not None:
            spec.notes = notes
        if lan is not None:
            spec.lan = lan
        if version is not None:
            spec.version = validate_minecraft_version(version)
        if java_tag is not None:
            spec.java_tag = validate_java_tag(java_tag)
        if port is not None:
            ok, message = self.check_port_available(port, exclude=spec.id)
            if not ok:
                raise ValidationError("port", message)
            spec.port = validate_port(port, reserved=self.store.used_ports(exclude=spec.id))
            spec.rcon_port = self.store.allocate_rcon_port(spec.port, exclude=spec.id)

        spec = self.store.save(spec)
        if self.client.container_exists(spec.container_name):
            self.client.remove(spec.container_name, force=True)
        self._create_container(spec)
        return spec

    def change_version(
        self,
        server_id: str,
        version: str,
        *,
        java_tag: str | None = None,
    ) -> ServerSpec:
        """Cambia la version de Minecraft de un servidor detenido.

        No toca los mundos ni el contenido: solo actualiza la definicion y
        recrea el contenedor. Si se indica ``java_tag`` tambien cambia la
        version de Java (necesario al pasar de una version antigua a una
        moderna o al contrario).
        """
        return self.update_settings(server_id, version=version, java_tag=java_tag)

    def total_disk_usage(self, server_id: str) -> int:
        return self.files(server_id).total_size()

    # ====================================================== diagnostico
    def data_dir_writable(self, server_id: str) -> bool:
        """Comprueba que la aplicacion puede escribir en la carpeta del servidor.

        Sirve para detectar el caso (poco frecuente) de ficheros creados con un
        usuario ajeno, por ejemplo si el servidor se creo antes de activar el
        mapeo de usuario.
        """
        directory = self.store.data_dir(server_id)
        if not directory.is_dir():
            return True
        probe = directory / ".serviscraft-write-test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False

    @staticmethod
    def ownership_hint(server_id: str) -> str:
        """Instruccion para recuperar la propiedad de los ficheros del servidor."""
        return (
            "Los ficheros del servidor pertenecen a otro usuario. "
            "Puedes recuperarlos (sin sudo) con:\n\n"
            f"    podman unshare chown -R $(id -u):$(id -g) ~/.local/share/serviscraft/servers/{server_id}/data"
        )


# =========================================================== ayudas de parseo
_CPU_RE = re.compile(r"([0-9]*\.?[0-9]+)")


def _first_value(raw: dict, *keys: str) -> object:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def parse_percent(value: object) -> float:
    if value is None:
        return 0.0
    match = _CPU_RE.search(str(value))
    return float(match.group(1)) if match else 0.0


_SIZE_UNITS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "k": 1024,
    "m": 1024**2,
    "g": 1024**3,
    "t": 1024**4,
}


def parse_size(value: object) -> int:
    """Interpreta cadenas del estilo ``1.234GiB`` o ``512MB``."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(" ", "")
    if not text:
        return 0
    match = re.match(r"^([0-9]*\.?[0-9]+)\s*([A-Za-z]*)$", text)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2).lower() or "b"
    return int(number * _SIZE_UNITS.get(unit, 1))


def _split_pair(value: object) -> tuple[object, object]:
    if value is None:
        return None, None
    parts = str(value).split("/")
    if len(parts) != 2:
        return value, None
    return parts[0].strip(), parts[1].strip()


def host_cpu_count() -> int:
    """Nucleos logicos disponibles para este proceso (al menos uno)."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def normalize_cpu_percent(raw_percent: float, cores: int) -> float:
    """Pasa un porcentaje por nucleo (Podman) a porcentaje del equipo."""
    return min(100.0, max(0.0, float(raw_percent)) / max(1, int(cores)))


def parse_stats(raw: dict | None, *, fallback_limit_mb: int = 0) -> ServerStats:
    """Convierte la salida JSON de ``podman stats`` en :class:`ServerStats`."""
    if not raw:
        return ServerStats(available=False)

    # Podman 5 llama a este campo ``cpu_percent`` (con ``avg_cpu`` como
    # media); las versiones antiguas usaban ``cpu``/``CPUPerc``.
    cpu = parse_percent(
        _first_value(raw, "cpu_percent", "avg_cpu", "cpu", "CPU", "CPUPerc", "cpu_perc")
    )
    pids = int(parse_size(_first_value(raw, "pids", "PIDS", "Pids")))

    used = int(parse_size(_first_value(raw, "mem_usage_bytes", "MemUsageBytes", "mem_bytes")))
    limit = int(parse_size(_first_value(raw, "mem_limit_bytes", "MemLimitBytes", "mem_max")))
    mem_usage_text = _first_value(raw, "mem_usage", "MemUsage")
    if not used or not limit:
        used_text, limit_text = _split_pair(mem_usage_text)
        used = used or parse_size(used_text)
        limit = limit or parse_size(limit_text)

    net_in, net_out = _split_pair(_first_value(raw, "net_io", "NetIO"))
    blk_in, blk_out = _split_pair(_first_value(raw, "block_io", "BlockIO"))

    if limit <= 0 and fallback_limit_mb:
        # Si el motor no informa del limite, mostramos el asignado al servidor.
        limit = fallback_limit_mb * 1024 * 1024

    return ServerStats(
        cpu_percent=cpu,
        memory_bytes=used,
        memory_limit_bytes=limit,
        pids=pids,
        network_input_bytes=parse_size(net_in),
        network_output_bytes=parse_size(net_out),
        block_input_bytes=parse_size(blk_in),
        block_output_bytes=parse_size(blk_out),
        available=True,
    )
