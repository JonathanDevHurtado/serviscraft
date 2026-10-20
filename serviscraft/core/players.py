"""Gestion de jugadores de un servidor (consola RCON y ficheros del servidor).

La lista de jugadores conectados solo se puede consultar con el servidor en
marcha (comando ``list`` por RCON). La lista blanca y los operadores, en cambio,
estan guardados en ``whitelist.json`` y ``ops.json`` dentro de la carpeta del
servidor, asi que se pueden mostrar aunque el servidor este detenido.

Ninguna orden se construye con texto libre del usuario: los comandos disponibles
son una lista cerrada y el nombre del jugador se valida antes de componerlos.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import ServerStateError, ValidationError
from .logging_setup import get_logger
from .validation import atomic_write_text

logger = get_logger("players")

#: Nombres de Minecraft: letras, numeros y guion bajo. Se admite un punto
#: inicial porque GeyserMC lo anade a los jugadores de Bedrock.
_PLAYER_NAME = re.compile(r"^\.?[A-Za-z0-9_]{1,32}$")

#: Respuestas posibles de ``list``:
#: ``There are 2 of a max of 20 players online: Ana, Luis``
#: ``There are 2/20 players online: Ana, Luis``
_LIST_PATTERN = re.compile(
    r"There are\s+(\d+)\s*(?:of a max of\s+|/)\s*(\d+)\s+players online:?\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)
#: Respuesta de ``whitelist list``.
_WHITELIST_PATTERN = re.compile(r"whitelisted players?:?\s*(.*)", re.IGNORECASE | re.DOTALL)


def validate_player_name(name: str) -> str:
    """Valida el nombre de un jugador antes de usarlo en un comando."""
    cleaned = str(name or "").strip()
    if not cleaned:
        raise ValidationError("player", "Escribe el nombre del jugador.")
    if not _PLAYER_NAME.match(cleaned):
        raise ValidationError(
            "player",
            "Nombre de jugador no valido: usa solo letras, numeros y guion bajo (maximo 32 caracteres).",
        )
    return cleaned


def split_names(text: str) -> list[str]:
    """Separa una lista de nombres separados por comas."""
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


def parse_player_list(response: str) -> tuple[list[str], int]:
    """Interpreta la respuesta de ``list``: devuelve (jugadores, maximo)."""
    match = _LIST_PATTERN.search(str(response or ""))
    if not match:
        return [], 0
    players = split_names(match.group(3))
    try:
        maximum = int(match.group(2))
    except (TypeError, ValueError):  # pragma: no cover - respuesta inesperada
        maximum = 0
    return players, maximum


def parse_whitelist(response: str) -> list[str]:
    """Interpreta la respuesta de ``whitelist list``."""
    match = _WHITELIST_PATTERN.search(str(response or ""))
    if not match:
        return []
    return split_names(match.group(1))


#: Fichero de cada lista que mantiene el servidor dentro de su carpeta.
LIST_FILES: dict[str, str] = {
    "whitelist": "whitelist.json",
    "ops": "ops.json",
    "banned": "banned-players.json",
}

#: Acciones que se pueden aplicar sin servidor, editando las listas del servidor.
OFFLINE_ACTIONS: dict[str, tuple[str, bool]] = {
    # accion: (lista, anadir)
    "op": ("ops", True),
    "deop": ("ops", False),
    "whitelist_add": ("whitelist", True),
    "whitelist_remove": ("whitelist", False),
    "ban": ("banned", True),
    "pardon": ("banned", False),
}


def offline_uuid(name: str) -> str:
    """UUID que usa el juego para un jugador sin cuenta premium.

    Es el mismo calculo que hace Java (``UUID.nameUUIDFromBytes`` sobre
    ``OfflinePlayer:<nombre>``): el fichero de la lista queda valido aunque el
    servidor este en ``online-mode=false``.
    """
    digest = hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest, version=3))


def read_entries(path: Path) -> list[dict]:
    """Lee ``whitelist.json``/``ops.json``/``banned-players.json`` como entradas.

    Se conservan los campos que no se conocen: el servidor guarda ahi datos suyos
    (nivel de operador, caducidad del bloqueo...) que no deben perderse al
    anadir o quitar a otra persona.
    """
    target = Path(path)
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        logger.warning("No se pudo leer %s; se empieza una lista nueva", target)
        return []
    if not isinstance(data, list):
        return []
    entradas: list[dict] = []
    for entry in data:
        if isinstance(entry, dict) and str(entry.get("name") or "").strip():
            entradas.append(dict(entry))
        elif isinstance(entry, str) and entry.strip():
            entradas.append({"name": entry.strip()})
    return entradas


def write_entries(path: Path, entries: list[dict]) -> None:
    """Guarda una lista de jugadores de forma atomica y sin seguir enlaces."""
    atomic_write_text(
        Path(path),
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        role=Path(path).name,
    )


def _index_of(entries: list[dict], name: str) -> int | None:
    buscado = name.lower()
    for indice, entry in enumerate(entries):
        if str(entry.get("name") or "").strip().lower() == buscado:
            return indice
    return None


def add_list_entry(path: Path, name: str, *, extra: dict | None = None) -> bool:
    """Anade un jugador a una lista. Devuelve ``False`` si ya estaba."""
    validado = validate_player_name(name)
    entries = read_entries(path)
    if _index_of(entries, validado) is not None:
        return False
    entrada = {"uuid": offline_uuid(validado), "name": validado}
    entrada.update(extra or {})
    entries.append(entrada)
    write_entries(path, entries)
    return True


def remove_list_entry(path: Path, name: str) -> bool:
    """Quita un jugador de una lista. Devuelve ``False`` si no estaba."""
    validado = validate_player_name(name)
    entries = read_entries(path)
    indice = _index_of(entries, validado)
    if indice is None:
        return False
    del entries[indice]
    write_entries(path, entries)
    return True


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def apply_offline_action(data_dir: Path, action: str, player: str) -> str:
    """Aplica una accion editando las listas, con el servidor detenido.

    Es lo mismo que hace el comando de consola, pero escrito directamente en
    ``whitelist.json``, ``ops.json`` o ``banned-players.json``. Asi la pestana de
    jugadores sirve tambien con el servidor apagado, que es cuando se prepara la
    lista de invitados. ``kick`` necesita el servidor encendido.
    """
    selected = ACTIONS_BY_KEY.get(str(action or "").strip())
    if selected is None:
        raise ValidationError("player", "Accion de jugador desconocida.")
    if selected.key == "kick":
        raise ServerStateError(
            "Para expulsar a alguien el servidor tiene que estar encendido: la orden "
            "se envia a su consola."
        )
    dato = OFFLINE_ACTIONS.get(selected.key)
    if dato is None:  # pragma: no cover - todas las acciones estan cubiertas
        raise ValidationError("player", "Accion de jugador desconocida.")
    lista, anadir = dato
    path = Path(data_dir) / LIST_FILES[lista]
    nombre = validate_player_name(player)
    if anadir:
        extra: dict = {}
        if lista == "ops":
            extra = {"level": 4, "bypassesPlayerLimit": False}
        elif lista == "banned":
            extra = {
                "created": _now(),
                "source": "Serviscraft",
                "expires": "forever",
                "reason": "Bloqueado desde Serviscraft",
            }
        nuevo = add_list_entry(path, nombre, extra=extra)
        if lista == "whitelist":
            return (
                f"«{nombre}» anadido a la lista blanca."
                if nuevo
                else f"«{nombre}» ya estaba en la lista blanca."
            )
        if lista == "ops":
            return (
                f"«{nombre}» ahora es operador (se aplica al arrancar)."
                if nuevo
                else f"«{nombre}» ya era operador."
            )
        return (
            f"«{nombre}» queda bloqueado (se aplica al arrancar)."
            if nuevo
            else f"«{nombre}» ya estaba bloqueado."
        )
    quitado = remove_list_entry(path, nombre)
    if lista == "whitelist":
        return (
            f"«{nombre}» quitado de la lista blanca."
            if quitado
            else f"«{nombre}» no estaba en la lista blanca."
        )
    if lista == "ops":
        return (
            f"«{nombre}» ya no es operador."
            if quitado
            else f"«{nombre}» no era operador."
        )
    return (
        f"«{nombre}» perdonado: ya puede volver a entrar."
        if quitado
        else f"«{nombre}» no estaba bloqueado."
    )


def read_names_file(path: Path) -> list[str]:
    """Lee los nombres de ``whitelist.json`` u ``ops.json``.

    Son ficheros que escribe el propio servidor dentro de su carpeta de datos;
    si estan danados o no existen se devuelve una lista vacia (no es un error
    para la interfaz: solo significa que todavia no hay nadie apuntado).
    """
    target = Path(path)
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        logger.warning("No se pudo leer %s", target)
        return []
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for entry in data:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
        else:
            name = str(entry or "").strip()
        if name:
            names.append(name)
    return sorted(names, key=str.lower)


@dataclass(frozen=True)
class PlayerAction:
    """Una accion que se puede aplicar a un jugador desde la interfaz."""

    key: str
    label: str
    #: Comando de consola; ``{player}`` se sustituye por el nombre validado.
    command: str
    #: Aviso para el usuario (vacio si la accion es inocua).
    warning: str = ""
    destructive: bool = False


#: Acciones disponibles. El orden es el que se muestra en la interfaz.
PLAYER_ACTIONS: tuple[PlayerAction, ...] = (
    PlayerAction("op", "Dar OP", "op {player}"),
    PlayerAction("deop", "Quitar OP", "deop {player}"),
    PlayerAction("whitelist_add", "Anadir a la lista", "whitelist add {player}"),
    PlayerAction("whitelist_remove", "Quitar de la lista", "whitelist remove {player}"),
    PlayerAction("kick", "Expulsar", "kick {player}"),
    PlayerAction(
        "ban",
        "Bloquear",
        "ban {player}",
        warning="El jugador quedara bloqueado y no podra volver a entrar hasta que lo perdones.",
        destructive=True,
    ),
    PlayerAction("pardon", "Perdonar", "pardon {player}"),
)

ACTIONS_BY_KEY: dict[str, PlayerAction] = {action.key: action for action in PLAYER_ACTIONS}


def build_command(action: str, player: str | None = None) -> str:
    """Compone el comando de consola de una accion, validando sus datos."""
    selected = ACTIONS_BY_KEY.get(str(action or "").strip())
    if selected is None:
        raise ValidationError("player", "Accion de jugador desconocida.")
    if "{player}" not in selected.command:
        return selected.command
    return selected.command.format(player=validate_player_name(player or ""))


@dataclass(frozen=True)
class PlayersSnapshot:
    """Estado de los jugadores de un servidor en un momento dado."""

    online: tuple[str, ...] = ()
    max_players: int = 0
    whitelist: tuple[str, ...] = ()
    ops: tuple[str, ...] = ()
    #: Jugadores bloqueados (``banned-players.json``).
    banned: tuple[str, ...] = ()
    whitelist_enabled: bool = False
    running: bool = False
    #: Texto explicativo cuando la informacion en vivo no esta disponible.
    note: str = ""

    @property
    def known(self) -> tuple[str, ...]:
        """Todos los jugadores conocidos (conectados, en lista blanca, operadores o bloqueados)."""
        names: dict[str, str] = {}
        for name in (*self.online, *self.whitelist, *self.ops, *self.banned):
            names.setdefault(name.lower(), name)
        return tuple(sorted(names.values(), key=str.lower))

    def is_online(self, name: str) -> bool:
        return name.lower() in {p.lower() for p in self.online}

    def in_whitelist(self, name: str) -> bool:
        return name.lower() in {p.lower() for p in self.whitelist}

    def is_op(self, name: str) -> bool:
        return name.lower() in {p.lower() for p in self.ops}

    def is_banned(self, name: str) -> bool:
        return name.lower() in {p.lower() for p in self.banned}

    def to_dict(self) -> dict:
        return {
            "online": list(self.online),
            "max_players": self.max_players,
            "whitelist": list(self.whitelist),
            "ops": list(self.ops),
            "banned": list(self.banned),
            "whitelist_enabled": self.whitelist_enabled,
            "running": self.running,
            "note": self.note,
            "known": list(self.known),
        }
