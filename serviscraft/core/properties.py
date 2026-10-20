"""Lectura y edicion de ``server.properties``.

Se conservan los comentarios, el orden y las lineas desconocidas para no perder
nada de lo que escribe el propio servidor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import ServiscraftError
from .logging_setup import get_logger
from .validation import ValidationError, atomic_write_text, read_text_inside, reject_symlink

logger = get_logger("properties")


class PropertiesError(ServiscraftError):
    """El fichero de propiedades no se pudo leer o interpretar."""


@dataclass
class PropertyMeta:
    """Metadatos para presentar una propiedad en la interfaz."""

    key: str
    label: str
    kind: str = "str"  # str | int | bool | enum
    description: str = ""
    default: str = ""
    choices: tuple[str, ...] = ()
    #: True si la aplicacion gestiona el valor y no debe editarse a mano.
    managed: bool = False


#: Catalogo de las propiedades mas habituales; el resto se muestran en modo "avanzado".
KNOWN_PROPERTIES: dict[str, PropertyMeta] = {
    m.key: m
    for m in (
        PropertyMeta(
            "motd",
            "Mensaje del dia (MOTD)",
            "str",
            "Texto que ven los jugadores en la lista de servidores.",
            "A Minecraft Server",
        ),
        PropertyMeta(
            "max-players",
            "Jugadores maximos",
            "int",
            "Numero maximo de jugadores conectados a la vez.",
            "20",
        ),
        PropertyMeta(
            "difficulty",
            "Dificultad",
            "enum",
            "Dificultad del mundo.",
            "easy",
            ("peaceful", "easy", "normal", "hard"),
        ),
        PropertyMeta(
            "gamemode",
            "Modo de juego",
            "enum",
            "Modo de juego por defecto.",
            "survival",
            ("survival", "creative", "adventure", "spectator"),
        ),
        PropertyMeta("pvp", "Combate entre jugadores", "bool", "Permite el PvP.", "true"),
        PropertyMeta("hardcore", "Modo hardcore", "bool", "Muerte permanente.", "false"),
        PropertyMeta(
            "online-mode",
            "Verificacion de cuentas",
            "bool",
            "Valida las cuentas con Mojang. Desactivarlo permite entrar sin licencia.",
            "true",
        ),
        PropertyMeta(
            "white-list",
            "Lista blanca",
            "bool",
            "Solo pueden entrar jugadores de la lista blanca.",
            "false",
        ),
        PropertyMeta("enforce-whitelist", "Aplicar lista blanca", "bool", "", "false"),
        PropertyMeta(
            "level-name",
            "Mundo activo",
            "str",
            "Carpeta del mundo que se carga. Se puede cambiar desde la pestana Archivos.",
            "world",
        ),
        PropertyMeta("level-seed", "Semilla del mundo", "str", "Semilla para generar el mundo.", ""),
        PropertyMeta("view-distance", "Distancia de vision", "int", "Chunks enviados al cliente.", "10"),
        PropertyMeta("simulation-distance", "Distancia de simulacion", "int", "", "10"),
        PropertyMeta("spawn-protection", "Proteccion del spawn", "int", "Radio protegido alrededor del spawn.", "16"),
        PropertyMeta("enable-command-block", "Bloques de comandos", "bool", "", "false"),
        PropertyMeta("allow-flight", "Permitir vuelo", "bool", "", "false"),
        PropertyMeta("allow-nether", "Permitir el Nether", "bool", "", "true"),
        PropertyMeta("spawn-monsters", "Generar monstruos", "bool", "", "true"),
        PropertyMeta("spawn-animals", "Generar animales", "bool", "", "true"),
        PropertyMeta("spawn-npcs", "Generar aldeanos", "bool", "", "true"),
        PropertyMeta("generate-structures", "Generar estructuras", "bool", "", "true"),
        PropertyMeta("max-world-size", "Tamano maximo del mundo", "int", "", "29999984"),
        PropertyMeta("enable-status", "Mostrar en la lista", "bool", "", "true"),
        PropertyMeta("force-gamemode", "Forzar modo de juego", "bool", "", "false"),
        PropertyMeta("player-idle-timeout", "Expulsion por inactividad", "int", "Minutos (0 = nunca).", "0"),
        PropertyMeta("op-permission-level", "Nivel de operador", "int", "1-4.", "4"),
        PropertyMeta("function-permission-level", "Nivel de funciones", "int", "1-4.", "2"),
        PropertyMeta("query.port", "Puerto de consulta", "int", "", "25565"),
        PropertyMeta("enable-rcon", "Consola RCON", "bool", "Gestionado por Serviscraft.", "true", managed=True),
        PropertyMeta("rcon.port", "Puerto RCON", "int", "Gestionado por Serviscraft.", "25575", managed=True),
        PropertyMeta("rcon.password", "Contrasena RCON", "str", "Gestionado por Serviscraft.", "", managed=True),
        PropertyMeta(
            "server-port",
            "Puerto del servidor",
            "int",
            "Gestionado por Serviscraft; se cambia al editar el servidor.",
            "25565",
            managed=True,
        ),
        PropertyMeta("server-ip", "IP del servidor", "str", "Gestionado por el contenedor.", "", managed=True),
    )
}


@dataclass
class PropertyEntry:
    """Una linea del fichero: comentario, propiedad o linea vacia."""

    kind: str  # comment | property | blank | invalid
    text: str = ""
    key: str = ""
    value: str = ""


@dataclass
class ServerProperties:
    """Representacion editable de ``server.properties``."""

    path: Path
    entries: list[PropertyEntry] = field(default_factory=list)

    # ---------------------------------------------------------------- carga
    @classmethod
    def load(cls, path: Path, *, root: Path | None = None) -> "ServerProperties":
        target = Path(path)
        if not target.is_file():
            return cls(path=target, entries=[])
        try:
            if root is not None:
                # La carpeta del servidor la escribe el propio servidor (y sus
                # plugins): un enlace simbolico ahi no se sigue.
                raw = read_text_inside(target, root)
            else:
                raw = reject_symlink(target).read_text(encoding="utf-8", errors="replace")
        except ValidationError:
            raise
        except OSError as exc:
            raise PropertiesError(f"No se pudo leer {target.name}: {exc}") from exc
        entries = [cls._parse_line(line) for line in raw.splitlines()]
        return cls(path=target, entries=entries)

    @classmethod
    def from_text(cls, path: Path, text: str) -> "ServerProperties":
        """Crea el objeto a partir de un texto editado a mano."""
        entries = [cls._parse_line(line) for line in text.split("\n")]
        # Se descartan las ultimas lineas vacias duplicadas por el salto final.
        while entries and entries[-1].kind == "blank":
            entries.pop()
        return cls(path=Path(path), entries=entries)

    @staticmethod
    def _parse_line(line: str) -> PropertyEntry:
        stripped = line.strip()
        if not stripped:
            return PropertyEntry(kind="blank", text=line)
        if stripped.startswith("#") or stripped.startswith("!"):
            return PropertyEntry(kind="comment", text=line)
        if "=" not in stripped:
            return PropertyEntry(kind="invalid", text=line)
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            return PropertyEntry(kind="invalid", text=line)
        return PropertyEntry(kind="property", key=key, value=value.strip(), text=line)

    # ------------------------------------------------------------ consultas
    def keys(self) -> list[str]:
        return [e.key for e in self.entries if e.kind == "property"]

    def get(self, key: str, default: str = "") -> str:
        for entry in self.entries:
            if entry.kind == "property" and entry.key == key:
                return entry.value
        return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, "").strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
        return default

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)).strip())
        except ValueError:
            return default

    def as_dict(self) -> dict[str, str]:
        return {e.key: e.value for e in self.entries if e.kind == "property"}

    # ------------------------------------------------------------ edicion
    def set(self, key: str, value: str) -> None:
        """Establece una propiedad manteniendo su posicion original."""
        str_value = str(value)
        for entry in self.entries:
            if entry.kind == "property" and entry.key == key:
                entry.value = str_value
                return
        self.entries.append(PropertyEntry(kind="property", key=key, value=str_value))

    def set_many(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            self.set(key, value)

    def remove(self, key: str) -> None:
        self.entries = [e for e in self.entries if not (e.kind == "property" and e.key == key)]

    # ---------------------------------------------------------- serializar
    def to_text(self) -> str:
        lines: list[str] = []
        for entry in self.entries:
            if entry.kind == "property":
                lines.append(f"{entry.key}={entry.value}")
            else:
                lines.append(entry.text)
        return "\n".join(lines).rstrip("\n") + "\n"

    def save(self, path: Path | None = None) -> None:
        target = Path(path or self.path)
        try:
            # Temporal impredecible + renombrado atomico: escribir en un
            # ``.tmp`` con nombre fijo permitia que un enlace simbolico
            # plantado en la carpeta del servidor desviara la escritura.
            atomic_write_text(target, self.to_text(), role="server.properties")
        except ValidationError:
            raise PropertiesError(
                "server.properties es un enlace simbolico; por seguridad no se "
                "sobrescribe. Revisa la pestana Archivos."
            )
        except OSError as exc:
            raise PropertiesError(f"No se pudo guardar {target.name}: {exc}") from exc
        logger.info("Propiedades guardadas en %s", target)


def build_default_properties(spec_motd: str, *, level_name: str = "world") -> ServerProperties:
    """Genera un ``server.properties`` base coherente con la definicion del servidor."""
    props = ServerProperties(path=Path("server.properties"))
    props.set("motd", spec_motd)
    props.set("level-name", level_name)
    for key, meta in KNOWN_PROPERTIES.items():
        if meta.managed or key in {"motd", "level-name"}:
            continue
        if meta.default:
            props.set(key, meta.default)
    return props
