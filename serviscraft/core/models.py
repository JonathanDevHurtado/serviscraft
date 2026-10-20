"""Modelos de datos de Serviscraft."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from . import ddns
from .paths import (
    CONTAINER_BEDROCK_PORT,
    CONTAINER_PREFIX,
    FLOODGATE_PLUGIN_URL,
    GEYSER_PLUGIN_URL,
    DEFAULT_BEDROCK_PORT,
)
from .validation import (
    ValidationError,
    format_memory,
    slugify,
    validate_image,
    validate_java_tag,
    validate_memory_mb,
    validate_minecraft_version,
    validate_name,
    validate_password,
    validate_port,
    validate_server_id,
    validate_slug,
)


class ServerType(str, Enum):
    """Tipo de servidor soportado por la imagen universal ``itzg/minecraft-server``."""

    VANILLA = "VANILLA"
    PAPER = "PAPER"
    FABRIC = "FABRIC"
    FORGE = "FORGE"
    #: Modpack de Modrinth: la imagen descarga el pack y su cargador.
    MODRINTH = "MODRINTH"

    @property
    def label(self) -> str:
        return {
            ServerType.VANILLA: "Vanilla",
            ServerType.PAPER: "Paper",
            ServerType.FABRIC: "Fabric",
            ServerType.FORGE: "Forge",
            ServerType.MODRINTH: "Modpack (Modrinth)",
        }[self]

    @property
    def description(self) -> str:
        return {
            ServerType.VANILLA: "Servidor oficial de Mojang, sin pluguins ni mods.",
            ServerType.PAPER: "Alto rendimiento, compatible con pluguins de Bukkit/Spigot.",
            ServerType.FABRIC: "Cargador ligero de mods del lado del servidor.",
            ServerType.FORGE: "Cargador clasico de mods, compatible con la mayoria.",
            ServerType.MODRINTH: "Un modpack completo de Modrinth: se instala con su cargador y sus mods.",
        }[self]

    @property
    def supports_plugins(self) -> bool:
        return self in {ServerType.PAPER}

    @property
    def supports_mods(self) -> bool:
        return self in {ServerType.FABRIC, ServerType.FORGE, ServerType.MODRINTH}

    @classmethod
    def from_value(cls, value: str | "ServerType") -> "ServerType":
        if isinstance(value, ServerType):
            return value
        return cls(str(value).strip().upper())


class ServerState(str, Enum):
    """Estado del contenedor del servidor."""

    RUNNING = "running"
    EXITED = "exited"
    CREATED = "created"
    PAUSED = "paused"
    MISSING = "missing"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            ServerState.RUNNING: "En ejecucion",
            ServerState.EXITED: "Detenido",
            ServerState.CREATED: "Creado (sin iniciar)",
            ServerState.PAUSED: "Pausado",
            ServerState.MISSING: "Sin contenedor",
            ServerState.UNKNOWN: "Desconocido",
        }[self]

    @property
    def is_running(self) -> bool:
        return self is ServerState.RUNNING

    @property
    def is_transitional(self) -> bool:
        return self in {ServerState.PAUSED}


@dataclass(frozen=True)
class ServerStats:
    """Consumo instantaneo de recursos del contenedor."""

    cpu_percent: float = 0.0
    #: Nucleos logicos del equipo con los que se normaliza ``cpu_percent``.
    cpu_cores: int = 0
    memory_bytes: int = 0
    memory_limit_bytes: int = 0
    pids: int = 0
    network_input_bytes: int = 0
    network_output_bytes: int = 0
    block_input_bytes: int = 0
    block_output_bytes: int = 0
    available: bool = False

    @property
    def cpu_cores_used(self) -> float:
        """Nucleos ocupados (Podman mide el 100 % por nucleo)."""
        if self.cpu_cores <= 0:
            return self.cpu_percent / 100.0
        return self.cpu_percent * self.cpu_cores / 100.0

    @property
    def memory_percent(self) -> float:
        if self.memory_limit_bytes <= 0:
            return 0.0
        return min(100.0, self.memory_bytes * 100.0 / self.memory_limit_bytes)

    def memory_label(self, limit_mb: int | None = None) -> str:
        used = format_bytes(self.memory_bytes)
        # La memoria asignada al servidor manda sobre la que informe el motor:
        # Podman suele dar la del equipo entero, que no es la referencia util.
        limit = (limit_mb * 1024 * 1024 if limit_mb else 0) or self.memory_limit_bytes
        if limit:
            return f"{used} / {format_bytes(limit)}"
        return used


def format_bytes(value: float) -> str:
    """Formatea bytes con unidad legible (base 1024)."""
    size = float(max(0.0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TiB"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_server_id(name: str) -> str:
    """Genera un identificador unico y seguro a partir del nombre."""
    slug = validate_slug(slugify(name))
    suffix = uuid.uuid4().hex[:6]
    return validate_server_id(f"{slug}-{suffix}")


@dataclass
class ServerSpec:
    """Definicion completa y persistente de un servidor."""

    id: str
    name: str
    type: ServerType
    version: str
    memory_mb: int
    port: int
    rcon_port: int
    rcon_password: str
    image: str
    java_tag: str = "java21"
    lan: bool = True
    notes: str = ""
    created_at: str = field(default_factory=_utcnow)
    last_started_at: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    #: Tambien acepta jugadores de Minecraft Bedrock (Geyser + Floodgate).
    bedrock: bool = False
    #: Puerto UDP del host para Bedrock (dentro del contenedor siempre es 19132).
    bedrock_port: int = DEFAULT_BEDROCK_PORT
    #: Nombre personalizado para entrar (DuckDNS): subdominio, token y si la
    #: aplicacion debe refrescar la direccion sola cuando cambie la IP publica.
    ddns_subdomain: str = ""
    ddns_token: str = ""
    ddns_auto: bool = False
    #: Ultima IP publica que se le comunico a DuckDNS (para no llamar de mas).
    ddns_last_ip: str = ""
    #: Claves de ``meta.json`` que esta version no conoce. Se conservan al
    #: guardar para que una version anterior de la aplicacion no borre datos de
    #: una posterior (ida y vuelta sin perdidas).
    _extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    # ------------------------------------------------------------------ utils
    @property
    def container_name(self) -> str:
        return f"{CONTAINER_PREFIX}-{self.id}"

    @property
    def image_ref(self) -> str:
        return f"{self.image}:{self.java_tag}"

    @property
    def memory_label(self) -> str:
        return format_memory(self.memory_mb)

    @property
    def supports_plugins(self) -> bool:
        return self.type.supports_plugins

    @property
    def supports_mods(self) -> bool:
        return self.type.supports_mods

    @property
    def modpack(self) -> str:
        """Slug del modpack de Modrinth que usa el servidor (vacio si no usa)."""
        return str((self.extra_env or {}).get("MODRINTH_MODPACK") or "")

    def bind_address(self) -> str:
        return "0.0.0.0" if self.lan else "127.0.0.1"

    def connection_address(self, host_ip: str = "localhost") -> str:
        return f"{host_ip}:{self.port}"

    @property
    def ddns_configured(self) -> bool:
        """True si hay un nombre personalizado configurado."""
        return bool(str(self.ddns_subdomain or "").strip())

    def public_address(self) -> str:
        """Direccion que se comparte con quien juega desde fuera de casa.

        Con nombre personalizado no hace falta dar la IP; sin el, se deja vacia
        porque la IP publica solo se puede averiguar preguntando a internet.
        """
        if not self.ddns_configured:
            return ""
        try:
            return f"{ddns.hostname(self.ddns_subdomain)}:{self.port}"
        except ValidationError:  # pragma: no cover - ya validado al guardar
            return ""

    # ------------------------------------------------------------ validacion
    def validated(self) -> "ServerSpec":
        """Devuelve una copia con todos los campos validados."""
        return replace(
            self,
            id=validate_server_id(self.id),
            name=validate_name(self.name),
            type=ServerType.from_value(self.type),
            version=validate_minecraft_version(self.version),
            memory_mb=validate_memory_mb(self.memory_mb),
            port=validate_port(self.port),
            rcon_port=validate_port(self.rcon_port),
            rcon_password=validate_password(self.rcon_password),
            image=validate_image(self.image),
            java_tag=validate_java_tag(self.java_tag),
            bedrock_port=validate_port(self.bedrock_port),
            # El nombre puede estar vacio (no configurado), pero si hay algo tiene
            # que ser un subdominio valido. El token solo se comprueba si existe:
            # una entrada vieja sin token se sigue pudiendo cargar.
            ddns_subdomain=(
                ddns.validate_subdomain(self.ddns_subdomain) if str(self.ddns_subdomain).strip() else ""
            ),
            ddns_token=ddns.validate_token(self.ddns_token),
        )

    # ------------------------------------------------------- (de)serializacion
    def to_dict(self) -> dict[str, Any]:
        # Se parte de las claves desconocidas para que una version anterior de
        # la aplicacion no borre lo que haya escrito una version posterior.
        datos: dict[str, Any] = dict(self._extra)
        datos.update(
            {
                "id": self.id,
                "name": self.name,
                "type": self.type.value,
                "version": self.version,
                "memory_mb": self.memory_mb,
                "port": self.port,
                "rcon_port": self.rcon_port,
                "rcon_password": self.rcon_password,
                "image": self.image,
                "java_tag": self.java_tag,
                "lan": self.lan,
                "notes": self.notes,
                "created_at": self.created_at,
                "last_started_at": self.last_started_at,
                "extra_env": dict(self.extra_env),
                "bedrock": self.bedrock,
                "bedrock_port": self.bedrock_port,
                "ddns_subdomain": self.ddns_subdomain,
                "ddns_token": self.ddns_token,
                "ddns_auto": self.ddns_auto,
                "ddns_last_ip": self.ddns_last_ip,
            }
        )
        return datos

    #: Claves que esta version entiende. El resto se conserva en ``_extra``.
    KNOWN_KEYS: frozenset[str] = frozenset(
        {
            "id",
            "name",
            "type",
            "version",
            "memory_mb",
            "port",
            "rcon_port",
            "rcon_password",
            "image",
            "java_tag",
            "lan",
            "notes",
            "created_at",
            "last_started_at",
            "extra_env",
            "bedrock",
            "bedrock_port",
            "ddns_subdomain",
            "ddns_token",
            "ddns_auto",
            "ddns_last_ip",
            "meta_version",
        }
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerSpec":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            type=ServerType.from_value(data.get("type", "VANILLA")),
            version=str(data.get("version", "latest")),
            memory_mb=int(data.get("memory_mb", 2048)),
            port=int(data.get("port", 25565)),
            rcon_port=int(data.get("rcon_port", 25575)),
            rcon_password=str(data.get("rcon_password", "")),
            image=str(data.get("image", "")),
            java_tag=str(data.get("java_tag", "java21")),
            lan=bool(data.get("lan", True)),
            notes=str(data.get("notes", "")),
            created_at=str(data.get("created_at", _utcnow())),
            last_started_at=data.get("last_started_at"),
            extra_env={str(k): str(v) for k, v in (data.get("extra_env") or {}).items()},
            bedrock=bool(data.get("bedrock", False)),
            bedrock_port=int(data.get("bedrock_port", 19132)),
            ddns_subdomain=str(data.get("ddns_subdomain", "") or ""),
            ddns_token=str(data.get("ddns_token", "") or ""),
            ddns_auto=bool(data.get("ddns_auto", False)),
            ddns_last_ip=str(data.get("ddns_last_ip", "") or ""),
            _extra={
                str(k): v
                for k, v in (data or {}).items()
                if str(k) not in cls.KNOWN_KEYS
            },
        )

    @property
    def bedrock_enabled(self) -> bool:
        """Hay jugadores de Bedrock? Solo los servidores con pluguins pueden."""
        return bool(self.bedrock) and self.type.supports_plugins

    @property
    def platform_label(self) -> str:
        """Plataformas que acepta el servidor, para textos e insignias."""
        return "Java y Bedrock" if self.bedrock_enabled else "Java"

    @property
    def plugins_env(self) -> str:
        """Valor de ``PLUGINS`` para la imagen (vacio si no hay Bedrock).

        Se usan las descargas oficiales de GeyserMC, que es justo lo que
        documenta la imagen: Geyser traduce Bedrock a Java y Floodgate permite
        entrar a quien no tiene cuenta de Java.
        """
        if not self.bedrock_enabled:
            return ""
        return f"{GEYSER_PLUGIN_URL}\n{FLOODGATE_PLUGIN_URL}"

    # -------------------------------------------------------------- variables
    def container_env(self, *, run_uid: int | None = None, run_gid: int | None = None) -> dict[str, str]:
        """Variables de entorno que se pasan a ``itzg/minecraft-server``.

        ``UID``/``GID`` indican con que usuario debe ejecutar el servidor dentro
        del contenedor. Se ajustan al usuario del host para que los mundos queden
        en su sitio y sean legibles desde la aplicacion (Podman rootless).
        """
        env: dict[str, str] = {
            "EULA": "TRUE",  # el usuario la acepta al crear el servidor en la interfaz
            "TYPE": self.type.value,
            "VERSION": self.version,
            "MEMORY": self.memory_label,
            "ENABLE_RCON": "true",
            "RCON_PASSWORD": self.rcon_password,
            "RCON_PORT": "25575",
            "SERVER_PORT": "25565",
        }
        if run_uid is not None:
            env["UID"] = str(run_uid)
        if run_gid is not None:
            env["GID"] = str(run_gid)
        plugins = self.plugins_env
        if plugins:
            env["PLUGINS"] = plugins
        env.update(self.safe_extra_env)
        return env

    #: Variables que la aplicacion controla y que ningun dato externo (por
    #: ejemplo el manifiesto de un modpack descargado) puede sobrescribir.
    #: Cambiar ``TYPE``, ``VERSION`` o ``PLUGINS`` a capricho rompe el servidor;
    #: tocar ``RCON_PASSWORD`` o ``ENABLE_RCON`` le quitaria la consola a la app.
    RESTRICTED_ENV: frozenset[str] = frozenset(
        {
            "EULA",
            "TYPE",
            "VERSION",
            "MEMORY",
            "ENABLE_RCON",
            "RCON_PASSWORD",
            "RCON_PORT",
            "SERVER_PORT",
            "UID",
            "GID",
            "PLUGINS",
        }
    )

    @property
    def safe_extra_env(self) -> dict[str, str]:
        """``extra_env`` sin las variables reservadas por la aplicacion."""
        limpio: dict[str, str] = {}
        for clave, valor in (self.extra_env or {}).items():
            nombre = str(clave).strip().upper()
            if not nombre or nombre in self.RESTRICTED_ENV:
                continue
            if not re.match(r"^[A-Z][A-Z0-9_]{0,63}$", nombre):
                continue
            limpio[nombre] = str(valor)
        return limpio


@dataclass(frozen=True)
class ServerView:
    """Vista combinada de la definicion y el estado real del contenedor."""

    spec: ServerSpec
    state: ServerState
    container_id: str = ""
    stats: ServerStats | None = None
    #: Icono propio del servidor (PNG de 64x64) para la lista de la aplicacion.
    icon: bytes = b""

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def running(self) -> bool:
        return self.state.is_running
