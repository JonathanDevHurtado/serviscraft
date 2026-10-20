"""Pruebas del aspecto del servidor: descripcion con colores e icono.

No se usa Qt: el modulo ``core.appearance`` es Python puro, asi que se puede
comprobar de verdad que el texto que se guarda es el que espera Minecraft y que
el icono no sigue enlaces simbolicos.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from serviscraft.core import appearance
from serviscraft.core.errors import ValidationError
from serviscraft.core.manager import ServerManager
from serviscraft.core.properties import ServerProperties
from serviscraft.core.store import ServerStore


def png(size: int = 64, width: int | None = None, height: int | None = None, color=(0, 200, 0)) -> bytes:
    """Construye un PNG valido (sin depender de Qt ni de Pillow)."""

    ancho, alto = width or size, height or size

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (
            struct.pack(">I", len(datos))
            + tipo
            + datos
            + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
        )

    cabecera = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    filas = b"".join(b"\x00" + bytes(color) * ancho for _ in range(alto))
    return (
        appearance.PNG_MAGIC
        + trozo(b"IHDR", cabecera)
        + trozo(b"IDAT", zlib.compress(filas))
        + trozo(b"IEND", b"")
    )


# ================================================================ texto
class TestTexto:
    def test_acepta_el_ampersand_como_atajo(self) -> None:
        assert appearance.normalize("&aHola &lFuerte") == "\u00a7aHola \u00a7lFuerte"

    def test_un_ampersand_normal_no_se_toca(self) -> None:
        assert appearance.normalize("Pepsi & Cola") == "Pepsi & Cola"

    def test_entiende_los_escapes_del_fichero(self) -> None:
        assert appearance.from_file_value("\\u00a7aVerde\\nSegunda") == "\u00a7aVerde\nSegunda"

    def test_quita_un_caracter_de_seccion_suelto(self) -> None:
        assert appearance.normalize("Hola \u00a7 mundo") == "Hola  mundo"

    def test_sin_codigos(self) -> None:
        assert appearance.strip_codes("\u00a7aHola \u00a7lque \u00a7rtal") == "Hola que tal"

    def test_cuentan_los_caracteres_utiles(self) -> None:
        texto = "a" * 44 + "\u00a7b" + "b"
        assert appearance.validate_text(texto) == texto
        with pytest.raises(ValidationError):
            appearance.validate_text("a" * 45 + "\u00a7b" + "b" * 1)

    def test_dos_lineas_vale_tres_no(self) -> None:
        assert appearance.validate_text("Una\n Dos") == "Una\n Dos"
        with pytest.raises(ValidationError):
            appearance.validate_text("Una\nDos\nTres")

    def test_una_linea_demasiado_larga_se_rechaza(self) -> None:
        with pytest.raises(ValidationError):
            appearance.validate_text("x" * (appearance.MAX_LINE_LENGTH + 1))

    def test_los_tabuladores_se_rechazan(self) -> None:
        with pytest.raises(ValidationError):
            appearance.validate_text("Hola\tmundo")

    def test_el_mensaje_vacio_vale(self) -> None:
        assert appearance.validate_text("") == ""
        assert appearance.validate_text("   ") == "   "

    def test_la_ida_y_vuelta_al_fichero_no_pierde_nada(self) -> None:
        original = "\u00a7aBienvenido\n\u00a7eDiversion \u00a7lsegura"
        guardado = appearance.to_file_value(original)
        assert "\\u00a7a" in guardado
        assert "\u00a7" not in guardado
        assert "\\n" in guardado
        assert appearance.from_file_value(guardado) == original

    def test_los_escapes_de_verdad_se_respetan(self) -> None:
        # Una barra invertida escrita por el usuario no debe convertirse en escape.
        guardado = appearance.to_file_value("C:\\juegos")
        assert appearance.from_file_value(guardado) == "C:\\juegos"

    def test_describe_una_linea_plana(self) -> None:
        assert appearance.describe("\u00a7aHola\n\u00a7bAdios") == "Hola / Adios"
        assert appearance.describe("") == ""


class TestTramos:
    def test_separa_por_color(self) -> None:
        lineas = appearance.parse("\u00a7aVerde\u00a7cRojo")
        assert len(lineas) == 1
        tramos = lineas[0]
        assert [(t.text, t.color) for t in tramos] == [
            ("Verde", appearance.COLORS["a"][1]),
            ("Rojo", appearance.COLORS["c"][1]),
        ]

    def test_la_negrita_sigue_hasta_el_final(self) -> None:
        tramos = appearance.parse("\u00a7lFuerte normal")[0]
        assert tramos[0].bold is True
        assert tramos[0].text == "Fuerte normal"

    def test_un_color_nuevo_borra_los_formatos(self) -> None:
        # Como en el juego: ``§l§a`` es verde y sin negrita.
        tramos = appearance.parse("\u00a7l\u00a7aVerde")[0]
        assert tramos[0].color == appearance.COLORS["a"][1]
        assert tramos[0].bold is False

    def test_el_texto_oculto_se_tapa(self) -> None:
        tramos = appearance.parse("\u00a7ksecreto")[0]
        assert tramos[0].obfuscated is True
        assert tramos[0].shown == "•" * len("secreto")

    def test_dos_lineas(self) -> None:
        lineas = appearance.parse("Primera\nSegunda")
        assert [[t.text for t in linea] for linea in lineas] == [["Primera"], ["Segunda"]]

    def test_texto_vacio(self) -> None:
        assert appearance.parse("") == [[]]


# ================================================================ propiedades
class TestPropiedades:
    def test_guardar_y_leer_el_mensaje(self) -> None:
        props = ServerProperties.from_text(Path("server.properties"), "motd=Hola\n")
        appearance.apply_motd(props, "\u00a7aBienvenido\n\u00a7eVamos")
        assert "motd=\\u00a7aBienvenido\\n\\u00a7eVamos" in props.to_text()
        assert appearance.motd_of(props) == "\u00a7aBienvenido\n\u00a7eVamos"

    def test_no_rompe_las_demas_propiedades(self) -> None:
        props = ServerProperties.from_text(
            Path("server.properties"), "# comentario\nmotd=Hola\nmax-players=20\n"
        )
        appearance.apply_motd(props, "Adios")
        texto = props.to_text()
        assert "# comentario" in texto
        assert "max-players=20" in texto
        assert "motd=Adios" in texto

    def test_sin_motd_devuelve_vacio(self) -> None:
        props = ServerProperties.from_text(Path("server.properties"), "level-name=world\n")
        assert appearance.motd_of(props) == ""


# ================================================================ icono
class TestIcono:
    def test_reconoce_un_png_correcto(self, tmp_path: Path) -> None:
        datos = png()
        assert appearance.png_size(datos) == (64, 64)
        appearance.save_icon(tmp_path, datos)
        assert appearance.icon_file(tmp_path).read_bytes() == datos
        assert appearance.read_icon(tmp_path) == datos

    def test_rechaza_lo_que_no_es_png(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            appearance.validate_icon(b"GIF89a esto no es un png")

    def test_rechaza_un_png_no_cuadrado(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            appearance.validate_icon(png(width=64, height=32))

    def test_rechaza_un_tamano_distinto_del_que_lee_minecraft(self) -> None:
        with pytest.raises(ValidationError):
            appearance.validate_icon(png(size=32))

    def test_rechaza_un_fichero_enorme(self) -> None:
        with pytest.raises(ValidationError):
            appearance.validate_icon(appearance.PNG_MAGIC + b"\x00" * (appearance.MAX_ICON_BYTES + 1))

    def test_sin_imagen_se_avisa(self) -> None:
        with pytest.raises(ValidationError):
            appearance.validate_icon(b"")

    def test_sin_icono_no_hay_nada_que_leer(self, tmp_path: Path) -> None:
        assert appearance.read_icon(tmp_path) == b""
        assert appearance.remove_icon(tmp_path) is False

    def test_un_enlace_simbolico_no_se_sigue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fuera = tmp_path / "fuera.png"
        fuera.write_bytes(png())
        data = tmp_path / "data"
        data.mkdir()
        (data / appearance.ICON_NAME).symlink_to(fuera)
        # Leer: se ignora (mejor sin icono que leer de fuera).
        assert appearance.read_icon(data) == b""
        # Borrar: no se sigue el enlace.
        with pytest.raises(ValidationError):
            appearance.remove_icon(data)

    def test_quitar_el_icono(self, tmp_path: Path) -> None:
        appearance.save_icon(tmp_path, png())
        assert appearance.remove_icon(tmp_path) is True
        assert not appearance.icon_file(tmp_path).exists()


# ================================================================ gestor
class TestGestor:
    @pytest.fixture
    def manager(self, store: ServerStore) -> ServerManager:
        return ServerManager(store=store)

    def test_guarda_y_lee_la_descripcion(self, manager: ServerManager, spec) -> None:
        manager.save_motd(spec.id, "\u00a7aBienvenido\n\u00a7eQue te diviertas")
        assert manager.motd(spec.id) == "\u00a7aBienvenido\n\u00a7eQue te diviertas"
        # Y queda en el fichero con los escapes que entiende Java.
        texto = (manager.store.data_dir(spec.id) / "server.properties").read_text("utf-8")
        assert "\\u00a7aBienvenido\\n" in texto

    def test_un_mensaje_invalido_no_llega_al_fichero(
        self, manager: ServerManager, spec
    ) -> None:
        with pytest.raises(ValidationError):
            manager.save_motd(spec.id, "Una\nDos\nTres")
        # Nada a medias: el fichero se queda como estaba.
        assert manager.motd(spec.id) == ""

    def test_no_se_pierde_el_resto_de_propiedades(
        self, manager: ServerManager, spec, populated_server
    ) -> None:
        props = manager.properties(spec.id)
        props.set("max-players", "30")
        manager.save_properties(spec.id, props)
        manager.save_motd(spec.id, "Hola")
        assert manager.properties(spec.id).get_int("max-players") == 30
        # Y la contrasena de la consola sigue blindada.
        assert manager.properties(spec.id).get("rcon.password") == spec.rcon_password

    def test_guarda_y_quita_el_icono(self, manager: ServerManager, spec) -> None:
        assert manager.server_icon(spec.id) == b""
        manager.save_icon(spec.id, png())
        assert manager.server_icon(spec.id) == png()
        assert manager.clear_icon(spec.id) is True
        assert manager.server_icon(spec.id) == b""

    def test_los_servidores_llevan_su_icono(self, manager: ServerManager, spec) -> None:
        manager.save_icon(spec.id, png())
        vistas = {v.spec.id: v for v in manager.views()}
        assert vistas[spec.id].icon == png()

    def test_un_icono_ilegible_no_rompe_el_listado(
        self, manager: ServerManager, spec
    ) -> None:
        (manager.store.data_dir(spec.id) / appearance.ICON_NAME).write_bytes(b"\x89PNG")
        vistas = {v.spec.id: v for v in manager.views()}
        assert vistas[spec.id].icon == b"\x89PNG"
