"""Pruebas del inventario de jugador leido de la consola del servidor.

Lo que se comprueba aqui es sobre todo la **lectura defensiva**: la respuesta del
servidor viene en texto NBT, puede traer compuestos anidados (encantamientos,
componentes) y puede llegar recortada por el limite de tamano de la consola. El
inventario de un jugador no puede inventarse ni quedarse a medias en silencio.
"""

from __future__ import annotations

import pytest

from serviscraft.core.inventory import (
    ARMOR_SLOTS,
    ItemStack,
    PlayerInventory,
    parse_inventory,
    parse_number,
    pretty_item,
    slot_label,
    split_items,
)

#: Respuesta tipica del servidor para un inventario pequeno.
RESPUESTA = (
    'Ana has the following entity data: ['
    '{Slot: 0b, id: "minecraft:diamond_sword", count: 1}, '
    '{Slot: 1b, id: "minecraft:cooked_beef", count: 5}]'
)


class TestLecturaDeLaRespuesta:
    def test_lee_los_objetos_con_su_hueco_y_su_cantidad(self) -> None:
        objetos, recortado = parse_inventory(RESPUESTA)
        assert recortado is False
        assert [(item.slot, item.item_id, item.count) for item in objetos] == [
            (0, "minecraft:diamond_sword", 1),
            (1, "minecraft:cooked_beef", 5),
        ]

    def test_ordena_por_hueco_aunque_lleguen_desordenados(self) -> None:
        objetos, _ = parse_inventory(
            'datos: [{Slot: 30b, id: "minecraft:stone"}, {Slot: 2b, id: "minecraft:dirt"}]'
        )
        assert [item.slot for item in objetos] == [2, 30]

    def test_acepta_los_dos_nombres_de_cantidad(self) -> None:
        """Hasta la 1.20.4 el campo era ``Count``; despues, ``count``."""
        viejos, _ = parse_inventory('[{"Slot": 0b, "id": "minecraft:stone", "Count": 12}]')
        nuevos, _ = parse_inventory('[{"Slot": 0b, "id": "minecraft:stone", "count": 12}]')
        assert viejos[0].count == nuevos[0].count == 12

    def test_sin_cantidad_se_cuenta_uno(self) -> None:
        objetos, _ = parse_inventory('[{"Slot": 4b, "id": "minecraft:shield"}]')
        assert objetos[0].count == 1

    def test_no_confunde_los_compuestos_anidados_con_el_siguiente_objeto(self) -> None:
        """Los encantamientos traen sus propias llaves y no son otro objeto."""
        respuesta = (
            'datos: ['
            '{Slot: 0b, id: "minecraft:diamond_sword", count: 1, components: '
            '{"minecraft:enchantments": {levels: {"minecraft:sharpness": 5, '
            '"minecraft:unbreaking": 3}}}}, '
            '{Slot: 1b, id: "minecraft:torch", count: 64}]'
        )
        objetos, recortado = parse_inventory(respuesta)
        assert recortado is False
        assert [item.item_id for item in objetos] == [
            "minecraft:diamond_sword",
            "minecraft:torch",
        ]

    def test_una_respuesta_recortada_se_avisa_en_vez_de_mentir(self) -> None:
        recortada = (
            'datos: [{Slot: 0b, id: "minecraft:stone", count: 64}, '
            '{Slot: 1b, id: "minecraft:torch"'
        )
        objetos, recortado = parse_inventory(recortada)
        assert recortado is True
        # Aun asi se devuelve lo que si venia entero.
        assert [item.item_id for item in objetos] == ["minecraft:stone"]

    def test_una_respuesta_sin_lista_no_da_objetos_ni_finge_exito(self) -> None:
        objetos, recortado = parse_inventory("No entity was found")
        assert objetos == []
        assert recortado is True

    @pytest.mark.parametrize("texto", ["", "   ", None])
    def test_texto_vacio_o_ausente(self, texto: str | None) -> None:
        objetos, recortado = parse_inventory(texto)  # type: ignore[arg-type]
        assert objetos == []
        assert recortado is True

    def test_un_objeto_sin_identificador_se_descarta(self) -> None:
        objetos, _ = parse_inventory('[{"Slot": 0b, "count": 3}]')
        assert objetos == []


class TestComillas:
    def test_las_llaves_dentro_de_comillas_no_cuentan_como_compuestos(self) -> None:
        trozos, recortado = split_items('[{nombre: "{raro}", Slot: 0b, id: "minecraft:stone"}]')
        assert recortado is False
        assert len(trozos) == 1

    def test_las_comillas_escapadas_no_cierran_el_texto(self) -> None:
        trozos, recortado = split_items('[{"nombre": "di \\"hola\\"", "Slot": 0b}]')
        assert recortado is False
        assert len(trozos) == 1


class TestDatosSueltos:
    @pytest.mark.parametrize(
        ("respuesta", "esperado"),
        [
            ("Ana has the following entity data: 17.5f", 17.5),
            ("Ana has the following entity data: 20", 20.0),
            ("Ana has the following entity data: -3", -3.0),
        ],
    )
    def test_lee_un_numero_suelto(self, respuesta: str, esperado: float) -> None:
        assert parse_number(respuesta) == esperado

    @pytest.mark.parametrize(
        "respuesta",
        ["No entity was found", "", "Ana has the following entity data: [algo]", None],
    )
    def test_sin_numero_devuelve_nada(self, respuesta: str | None) -> None:
        assert parse_number(respuesta) is None  # type: ignore[arg-type]


class TestNombres:
    @pytest.mark.parametrize(
        ("item_id", "esperado"),
        [
            ("minecraft:diamond_sword", "Diamond sword"),
            ("minecraft:oak_planks", "Oak planks"),
            ("minecraft:stone", "Stone"),
            ("stone", "Stone"),
            ("", "Objeto desconocido"),
        ],
    )
    def test_nombre_legible(self, item_id: str, esperado: str) -> None:
        assert pretty_item(item_id) == esperado

    @pytest.mark.parametrize(
        ("hueco", "esperado"),
        [
            (0, "Barra rapida 1"),
            (8, "Barra rapida 9"),
            (9, "Inventario 1"),
            (35, "Inventario 27"),
            (103, "Casco"),
            (100, "Botas"),
            (-106, "Mano secundaria"),
        ],
    )
    def test_nombre_del_hueco(self, hueco: int, esperado: str) -> None:
        assert slot_label(hueco) == esperado

    def test_la_armadura_usa_los_mismos_numeros_que_minecraft(self) -> None:
        assert ARMOR_SLOTS == {
            103: "Casco",
            102: "Peto",
            101: "Pantalones",
            100: "Botas",
            -106: "Mano secundaria",
        }


class TestPlayerInventory:
    def inventario(self) -> PlayerInventory:
        return PlayerInventory(
            player="Ana",
            items=(
                ItemStack(0, "minecraft:diamond_sword", 1),
                ItemStack(1, "minecraft:torch", 64),
                ItemStack(2, "minecraft:torch", 32),
            ),
            health=17.0,
            food=18,
            level=32,
        )

    def test_cuenta_huecos_y_objetos(self) -> None:
        inventario = self.inventario()
        assert inventario.stacks == 3
        assert inventario.total_items == 97

    def test_encuentra_el_objeto_de_un_hueco(self) -> None:
        inventario = self.inventario()
        encontrado = inventario.at(1)
        assert encontrado is not None
        assert encontrado.item_id == "minecraft:torch"
        assert inventario.at(40) is None

    def test_el_nombre_del_objeto_se_calcula_solo(self) -> None:
        assert ItemStack(0, "minecraft:oak_planks", 4).name == "Oak planks"

    def test_el_hueco_del_objeto_se_calcula_solo(self) -> None:
        assert ItemStack(103, "minecraft:diamond_helmet").slot_label == "Casco"

    def test_se_puede_guardar_como_diccionario(self) -> None:
        datos = self.inventario().to_dict()
        assert datos["player"] == "Ana"
        assert datos["items"][0] == {"slot": 0, "id": "minecraft:diamond_sword", "count": 1}
        assert datos["health"] == 17.0
        assert datos["food"] == 18
        assert datos["level"] == 32
        assert datos["truncated"] is False
