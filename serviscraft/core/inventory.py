"""Inventario y estado de un jugador, leidos de la consola del servidor.

El servidor de Java (vanilla y Paper) deja consultar los datos de un jugador con
``data get entity <jugador> <campo>`` a traves de la consola. De ahi salen el
inventario (``Inventory``), la vida (``Health``), la comida (``foodLevel``) y el
nivel de experiencia (``XpLevel``): no hay que instalar nada dentro del servidor
ni tocar el mundo, y funciona con cualquier version moderna.

El servidor responde con texto NBT en una sola linea. Se lee aqui con cuidado
porque **puede venir recortado**: la respuesta de la consola tiene un tamano
maximo y un inventario lleno de objetos con encantamientos lo supera. Cuando
esto ocurre se avisa en la interfaz en vez de ensenar datos a medias.

Nada se construye con texto libre del usuario: el nombre del jugador se valida
antes de componer el comando (ver :func:`serviscraft.core.players.validate_player_name`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Huecos de la lista ``Inventory`` del jugador (los mismos numeros que usa NBT).
ARMOR_SLOTS: dict[int, str] = {
    103: "Casco",
    102: "Peto",
    101: "Pantalones",
    100: "Botas",
    -106: "Mano secundaria",
}

#: Campos del compuesto de cada objeto: ``Slot``, ``id`` y ``Count`` (hasta la
#: 1.20.4) o ``count`` (desde la 1.20.5). Las claves pueden venir entre comillas
#: segun la version, asi que se aceptan las dos formas.
_SLOT_RE = re.compile(r"""["']?Slot["']?\s*:\s*(-?\d+)""")
_ID_RE = re.compile(r'''["']?id["']?\s*:\s*"([^"]*)"''')
_COUNT_RE = re.compile(r"""["']?[Cc]ount["']?\s*:\s*(\d+)""")
#: Dato suelto: ``Ana has the following entity data: 20.0f``.
_NUMBER_RE = re.compile(r"entity data:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ItemStack:
    """Un objeto dentro de la mochila de un jugador."""

    slot: int
    item_id: str
    count: int = 1

    @property
    def name(self) -> str:
        """Nombre legible del objeto («Diamond sword»)."""
        return pretty_item(self.item_id)

    @property
    def slot_label(self) -> str:
        """Nombre del hueco («Barra rapida 3», «Peto»...)."""
        return slot_label(self.slot)


@dataclass(frozen=True)
class PlayerInventory:
    """Lo que lleva encima un jugador en este momento."""

    player: str
    items: tuple[ItemStack, ...] = ()
    health: float | None = None
    food: int | None = None
    level: int | None = None
    #: El servidor devolvio el inventario incompleto (respuesta recortada).
    truncated: bool = False
    note: str = ""

    def at(self, slot: int) -> ItemStack | None:
        """Objeto de un hueco concreto (``None`` si esta vacio)."""
        for item in self.items:
            if item.slot == slot:
                return item
        return None

    @property
    def stacks(self) -> int:
        """Numero de huecos ocupados."""
        return len(self.items)

    @property
    def total_items(self) -> int:
        """Suma de todos los objetos (lo que se ve en «objetos en total»)."""
        return sum(item.count for item in self.items)

    def to_dict(self) -> dict:
        return {
            "player": self.player,
            "items": [
                {"slot": item.slot, "id": item.item_id, "count": item.count}
                for item in self.items
            ],
            "health": self.health,
            "food": self.food,
            "level": self.level,
            "truncated": self.truncated,
        }


def pretty_item(item_id: str) -> str:
    """«minecraft:diamond_sword» -> «Diamond sword»."""
    nombre = str(item_id or "").split(":")[-1].replace("_", " ").strip()
    if not nombre:
        return "Objeto desconocido"
    return nombre[0].upper() + nombre[1:]


def slot_label(slot: int) -> str:
    """Nombre del hueco, con los mismos nombres que usa Minecraft."""
    if 0 <= slot <= 8:
        return f"Barra rapida {slot + 1}"
    if 9 <= slot <= 35:
        return f"Inventario {slot - 8}"
    return ARMOR_SLOTS.get(slot, f"Hueco {slot}")


def split_items(texto: str) -> tuple[list[str], bool]:
    """Trocea la lista NBT en sus compuestos de primer nivel.

    Devuelve los trozos y si el texto venia **recortado** (un compuesto a medias
    o la lista sin cerrar). Se recorre caracter a caracter porque dentro de un
    objeto puede haber otros compuestos y listas anidadas (encantamientos,
    componentes...) que no deben confundirse con el siguiente objeto.
    """
    inicio = texto.find("[")
    if inicio < 0:
        return [], True
    trozos: list[str] = []
    actual: list[str] = []
    profundidad = 0
    comillas = False
    escape = False
    for caracter in texto[inicio + 1 :]:
        if comillas:
            actual.append(caracter)
            if escape:
                escape = False
            elif caracter == "\\":
                escape = True
            elif caracter == '"':
                comillas = False
            continue
        if caracter == '"':
            comillas = True
            actual.append(caracter)
        elif caracter == "{":
            profundidad += 1
            if profundidad == 1:
                actual = []
            actual.append(caracter)
        elif caracter == "}":
            profundidad -= 1
            actual.append(caracter)
            if profundidad <= 0:
                trozos.append("".join(actual))
                actual = []
                profundidad = 0
        elif profundidad > 0:
            actual.append(caracter)
    # La lista puede haber terminado bien aunque el ultimo objeto quedara a
    # medias; en los dos casos lo que falta es informacion.
    recortado = profundidad > 0 or texto.rfind("]") < inicio
    return trozos, recortado


def parse_inventory(texto: str) -> tuple[list[ItemStack], bool]:
    """Interpreta la respuesta de ``data get entity <jugador> Inventory``.

    Devuelve los objetos ordenados por hueco y si la respuesta venia recortada.
    """
    trozos, recortado = split_items(str(texto or ""))
    objetos: list[ItemStack] = []
    for trozo in trozos:
        identificador = _ID_RE.search(trozo)
        hueco = _SLOT_RE.search(trozo)
        if identificador is None or hueco is None:
            continue
        cantidad = _COUNT_RE.search(trozo)
        objetos.append(
            ItemStack(
                slot=int(hueco.group(1)),
                item_id=identificador.group(1),
                count=max(1, int(cantidad.group(1))) if cantidad else 1,
            )
        )
    objetos.sort(key=lambda item: item.slot)
    return objetos, recortado


def parse_number(texto: str) -> float | None:
    """Lee un dato suelto de ``data get entity`` (vida, comida, nivel...)."""
    encontrado = _NUMBER_RE.search(str(texto or ""))
    if encontrado is None:
        return None
    try:
        return float(encontrado.group(1))
    except ValueError:  # pragma: no cover - el patron ya garantiza el numero
        return None


__all__ = [
    "ARMOR_SLOTS",
    "ItemStack",
    "PlayerInventory",
    "parse_inventory",
    "parse_number",
    "pretty_item",
    "slot_label",
    "split_items",
]
