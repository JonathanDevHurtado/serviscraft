"""Pruebas de la cache de iconos de los proyectos (``core.icons``).

No se toca la red: se sustituye ``urllib.request.urlopen`` por un doble, y todas
las pruebas trabajan sobre la cache temporal (``$XDG_CACHE_HOME``).
"""

from __future__ import annotations

import pytest

from serviscraft.core import icons

URL = "https://cdn.modrinth.com/data/abc/icon.png"


class _RespuestaFalsa:
    """Respuesta minima que imita lo que devuelve ``urlopen``."""

    def __init__(self, datos: bytes) -> None:
        self._datos = datos

    def read(self, limite: int = -1) -> bytes:
        return self._datos if limite < 0 else self._datos[:limite]

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


@pytest.fixture
def urlopen_falso(monkeypatch: pytest.MonkeyPatch):
    """Sustituye la descarga y lleva la cuenta de las llamadas."""
    llamadas: list[str] = []

    def falso(peticion, timeout=None):
        url = peticion.full_url if hasattr(peticion, "full_url") else str(peticion)
        llamadas.append(url)
        if "roto" in url:
            raise OSError("sin conexion")
        return _RespuestaFalsa(b"\x89PNG\r\n\x1a\n" + b"x" * 32)

    monkeypatch.setattr(icons.urllib.request, "urlopen", falso)
    return llamadas


class TestCache:
    def test_la_clave_es_estable_y_distinta_por_direccion(self) -> None:
        assert icons.cache_key(URL) == icons.cache_key(URL)
        assert icons.cache_key(URL) != icons.cache_key(URL + "?v=2")

    def test_conserva_la_extension_del_fichero(self) -> None:
        assert icons.cached_path(URL).suffix == ".png"
        assert icons.cached_path("https://x/y.webp?cache=1&v=2").suffix == ".webp"
        # Sin extension conocida se guarda como .img (nunca se ejecuta nada).
        assert icons.cached_path("https://x/icono").suffix == ".img"

    def test_sin_cache_devuelve_none(self) -> None:
        assert icons.cached_bytes(URL) is None


class TestDescarga:
    def test_descarga_guarda_en_la_cache(self, urlopen_falso) -> None:
        datos = icons.download(URL)
        assert datos and datos.startswith(b"\x89PNG")
        assert icons.cached_bytes(URL) == datos
        # Siempre dentro de la carpeta de cache de la aplicacion.
        assert icons.cached_path(URL).parent == icons.icons_cache_dir()

    def test_la_segunda_vez_no_vuelve_a_la_red(self, urlopen_falso) -> None:
        icons.download(URL)
        assert len(urlopen_falso) == 1
        icons.download(URL)
        assert len(urlopen_falso) == 1

    def test_rechaza_esquemas_que_no_son_http(self, urlopen_falso) -> None:
        assert icons.download("file:///etc/passwd") is None
        assert icons.download("") is None
        assert urlopen_falso == []

    def test_descarta_un_fichero_demasiado_grande(self, monkeypatch: pytest.MonkeyPatch) -> None:
        enorme = icons.MAX_ICON_BYTES + 10

        def falso(peticion, timeout=None):
            return _RespuestaFalsa(b"a" * enorme)

        monkeypatch.setattr(icons.urllib.request, "urlopen", falso)
        assert icons.download(URL) is None
        assert icons.cached_bytes(URL) is None

    def test_si_falla_la_red_no_lanza(self, urlopen_falso) -> None:
        assert icons.download("https://roto.example/icono.png") is None

    def test_prefetch_ignora_los_que_fallan(self, urlopen_falso) -> None:
        resultado = icons.prefetch([URL, "https://roto.example/x.png", URL, ""])
        assert list(resultado) == [URL]

    def test_limpiar_la_cache(self, urlopen_falso) -> None:
        icons.download(URL)
        assert icons.cached_bytes(URL) is not None
        assert icons.clear_cache() == 1
        assert icons.cached_bytes(URL) is None
        assert icons.clear_cache() == 0
