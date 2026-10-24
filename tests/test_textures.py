"""Pruebas de las texturas de objetos y de las skins (sin salir a internet)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from serviscraft.core import textures


def _png(width: int, height: int, color: tuple[int, int, int, int] = (200, 40, 40, 255)) -> bytes:
    """PNG minimo valido (para no depender de Qt en las pruebas del nucleo)."""
    filas = b"".join(b"\x00" + bytes(color) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(filas))
        + chunk(b"IEND", b"")
    )


class TestNombres:
    @pytest.mark.parametrize(
        ("item_id", "esperado"),
        [
            ("minecraft:diamond_sword", "diamond_sword"),
            ("DIAMOND_SWORD", "diamond_sword"),
            ("minecraft:oak_planks", "oak_planks"),
            ("", ""),
            ("../../etc/passwd", ""),
            ("minecraft:diamond sword", ""),
            ("minecraft:espada/../x", ""),
        ],
    )
    def test_nombre_de_objeto(self, item_id: str, esperado: str) -> None:
        assert textures.item_name(item_id) == esperado

    @pytest.mark.parametrize(
        ("player", "valido"),
        [("Ana", True), ("Ana_1", True), ("ana-1", False), ("a.b", False), ("", False)],
    )
    def test_nombre_de_jugador(self, player: str, valido: bool) -> None:
        assert bool(textures.player_name(player)) is valido

    def test_quita_el_punto_de_los_jugadores_de_bedrock(self) -> None:
        """Floodgate antepone un punto; la skin se busca por el nombre limpio."""
        assert textures.player_name(".Steve") == "Steve"
        assert textures.player_name(".Ana_1") == "Ana_1"
        assert textures.player_name("..Steve") == ""
        assert textures.player_name(".a.b") == ""
        assert textures.skin_cache_path(".Steve") == textures.skin_cache_path("Steve")

    def test_las_rutas_no_se_salen_de_la_cache(self, tmp_path: Path) -> None:
        assert textures.item_cache_path("../../x") is None
        assert textures.skin_cache_path("../x") is None
        ruta = textures.item_cache_path("minecraft:diamond_sword")
        assert ruta is not None
        assert "diamond_sword.png" in ruta.name


class TestPng:
    def test_acepta_un_png_del_tamano_esperado(self) -> None:
        assert textures.valid_png(_png(16, 16), kind="item")
        assert textures.valid_png(_png(32, 32), kind="item")
        assert textures.valid_png(_png(64, 64), kind="skin")
        assert textures.valid_png(_png(64, 32), kind="skin")

    def test_rechaza_lo_que_no_es_un_png_o_no_mide_bien(self) -> None:
        assert not textures.valid_png(b"", kind="item")
        assert not textures.valid_png(b"GIF89a" + b"0" * 40, kind="item")
        assert not textures.valid_png(_png(64, 64), kind="item")
        assert not textures.valid_png(_png(16, 16), kind="skin")
        assert not textures.valid_png(_png(16, 16)[:20], kind="item")


class TestDescarga:
    def test_descarga_y_guarda_en_la_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SERVISCRAFT_OFFLINE", raising=False)
        datos = _png(16, 16)
        llamadas: list[str] = []

        def falso(url: str) -> bytes:
            llamadas.append(url)
            if url.endswith("/item/diamond_sword.png"):
                return datos
            return b"no"

        monkeypatch.setattr(textures, "_download", falso)
        assert textures.fetch_item_texture("minecraft:diamond_sword") == datos
        ruta = textures.item_cache_path("minecraft:diamond_sword")
        assert ruta is not None and ruta.is_file()

        # La segunda vez ni se llama a la red.
        llamadas.clear()
        assert textures.fetch_item_texture("minecraft:diamond_sword") == datos
        assert llamadas == []

    def test_si_no_esta_en_item_prueba_en_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SERVISCRAFT_OFFLINE", raising=False)
        datos = _png(16, 16)

        def falso(url: str) -> bytes | None:
            return datos if "/block/" in url else None

        monkeypatch.setattr(textures, "_download", falso)
        assert textures.fetch_item_texture("minecraft:grass_block") == datos

    def test_una_imagen_que_no_vale_no_se_guarda(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SERVISCRAFT_OFFLINE", raising=False)
        monkeypatch.setattr(textures, "_download", lambda url: b"<html>error</html>")
        assert textures.fetch_item_texture("minecraft:stone") is None
        assert textures.cached_item_texture("minecraft:stone") is None

    def test_sin_conexion_no_se_descarga(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVISCRAFT_OFFLINE", "1")

        def prohibido(url: str) -> bytes:  # pragma: no cover - no debe llamarse
            raise AssertionError("no se debe salir a internet")

        monkeypatch.setattr(textures, "_download", prohibido)
        assert textures.fetch_item_texture("minecraft:stone") is None
        assert textures.fetch_skin("Ana") is None

    def test_la_skin_se_guarda_y_se_reutiliza(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SERVISCRAFT_OFFLINE", raising=False)
        datos = _png(64, 64)
        urls: list[str] = []

        def falso(url: str) -> bytes:
            urls.append(url)
            return datos

        monkeypatch.setattr(textures, "_download", falso)
        assert textures.fetch_skin("Ana") == datos
        assert textures.fetch_skin("ana") == datos
        assert len(urls) == 1

    def test_la_skin_de_un_jugador_de_bedrock_quita_el_punto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SERVISCRAFT_OFFLINE", raising=False)
        datos = _png(64, 64)
        urls: list[str] = []

        def falso(url: str) -> bytes:
            urls.append(url)
            return datos

        monkeypatch.setattr(textures, "_download", falso)
        assert textures.fetch_skin(".Steve") == datos
        assert urls == ["https://mc-heads.net/skin/Steve"]
        ruta = textures.skin_cache_path(".Steve")
        assert ruta is not None and ruta.name == "steve.png" and ruta.is_file()
        # La misma cabeza sirve para el nombre con punto y sin el.
        assert textures.fetch_skin("Steve") == datos
        assert len(urls) == 1

    def test_solo_se_aceptan_los_servidores_de_la_lista(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # La comprobacion de la direccion ocurre antes de abrir la conexion.
        assert textures._download("http://raw.githubusercontent.com/x.png") is None
        assert textures._download("https://ejemplo.com/x.png") is None
        assert textures._download("file:///etc/passwd") is None


class TestSkin:
    def test_compone_cara_y_cuerpo(self, qapp) -> None:
        from serviscraft.ui.skin_view import body_pixmap, has_skin, head_pixmap

        datos = _png(64, 64, (40, 200, 120, 255))
        assert has_skin(datos)
        cara = head_pixmap(datos, 32)
        cuerpo = body_pixmap(datos, 96)
        assert not cara.isNull() and cara.width() == 32
        assert not cuerpo.isNull() and cuerpo.height() == 96

    def test_sin_skin_dibuja_un_jugador_generico(self, qapp) -> None:
        from serviscraft.ui.skin_view import body_pixmap, has_skin, head_pixmap

        assert not has_skin(b"")
        assert not head_pixmap(b"", 32).isNull()
        assert not body_pixmap(b"", 96).isNull()

    def test_la_cabeza_desconocida_lleva_un_signo_de_duda(self, qapp) -> None:
        from serviscraft.ui.mc_icons import icono_jugador_duda

        pixmap = icono_jugador_duda(64)
        assert not pixmap.isNull()
        imagen = pixmap.toImage()
        colores = {
            imagen.pixelColor(x, y).name()
            for x in range(imagen.width())
            for y in range(imagen.height())
        }
        # Cara de piedra y signo de interrogacion en blanco hueso.
        assert "#9aa4ad" in colores
        assert "#fff3cf" in colores

    def test_los_iconos_de_objeto_se_dibujan_sin_red(self, qapp) -> None:
        from serviscraft.ui.mc_icons import item_icon

        for item_id in (
            "minecraft:diamond_sword",
            "minecraft:grass_block",
            "minecraft:apple",
            "minecraft:iron_ingot",
            "minecraft:torch",
            "minecraft:oak_planks",
        ):
            assert not item_icon(item_id, 32).isNull(), item_id
