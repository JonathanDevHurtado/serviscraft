"""Pruebas del nombre personalizado (DuckDNS): ``core.ddns`` y el gestor.

No se toca la red: se sustituyen ``urlopen`` y la resolucion de nombres por
dobles, de modo que las pruebas son rapidas y no dependen de tener internet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from serviscraft.core import ddns
from serviscraft.core.errors import DdnsError, ValidationError
from serviscraft.core.manager import ServerManager
from serviscraft.core.models import ServerSpec
from serviscraft.core.store import META_VERSION, ServerStore

from .conftest import make_spec


# ------------------------------------------------------------------ validacion
class TestValidacion:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("reinotrebol", "reinotrebol"),
            ("ReinoTrebol", "reinotrebol"),
            ("  mi-servidor  ", "mi-servidor"),
            ("servidor-1", "servidor-1"),
            ("reinotrebol.duckdns.org", "reinotrebol"),
        ],
    )
    def test_normaliza_el_nombre(self, entrada: str, esperado: str) -> None:
        assert ddns.validate_subdomain(entrada) == esperado

    @pytest.mark.parametrize(
        "entrada",
        ["", "   ", "-empieza", "acaba-", "con espacio", "acentuado-é", "a" * 64, "punto.medio"],
    )
    def test_rechaza_los_nombres_invalidos(self, entrada: str) -> None:
        with pytest.raises(ValidationError):
            ddns.validate_subdomain(entrada)

    def test_el_token_es_opcional(self) -> None:
        assert ddns.validate_token("") == ""

    def test_el_token_se_valida(self) -> None:
        assert ddns.validate_token("abc-123-DEF") == "abc-123-DEF"
        with pytest.raises(ValidationError):
            ddns.validate_token("corto")
        with pytest.raises(ValidationError):
            ddns.validate_token("con espacio y muy largo 1")
        with pytest.raises(ValidationError):
            ddns.validate_token("", obligatorio=True)

    def test_el_nombre_completo(self) -> None:
        assert ddns.hostname("reinotrebol") == "reinotrebol.duckdns.org"

    @pytest.mark.parametrize(
        ("nombre", "esperado"),
        [
            ("Reino Trebol", "reino-trebol.local"),
            ("Acentos y ñ", "acentos-y-n.local"),
            ("///", "serviscraft.local"),
        ],
    )
    def test_nombre_para_la_red_local(self, nombre: str, esperado: str) -> None:
        assert ddns.mdns_hostname(nombre) == esperado


# ------------------------------------------------------------------ comprobar
class TestComprobar:
    def test_sin_nombre_no_hay_nada_que_comprobar(self) -> None:
        estado = ddns.check("")
        assert estado.state == "sin-configurar"
        assert not estado.ok

    def test_avisa_si_el_nombre_no_resuelve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ddns, "resolve", lambda *a, **k: set())
        estado = ddns.check("reinotrebol")
        assert estado.state == "sin-resolver"
        assert not estado.ok

    def test_ok_cuando_apunta_a_tu_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ddns, "resolve", lambda *a, **k: {"83.54.12.7"})
        estado = ddns.check("reinotrebol", public_ip="83.54.12.7", puerto=25565)
        assert estado.state == "ok"
        assert estado.ok
        assert "reinotrebol.duckdns.org:25565" in estado.detail

    def test_avisa_cuando_apunta_a_otra_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ddns, "resolve", lambda *a, **k: {"1.2.3.4"})
        estado = ddns.check("reinotrebol", public_ip="83.54.12.7", puerto=25565)
        assert estado.state == "otra-ip"
        assert "83.54.12.7" in estado.detail

    def test_sin_ip_publica_solo_confirma_que_resuelve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ddns, "resolve", lambda *a, **k: {"83.54.12.7"})
        estado = ddns.check("reinotrebol")
        assert estado.state == "sin-ip"
        assert "83.54.12.7" in estado.detail

    def test_needs_update_solo_si_cambia_la_ip(self) -> None:
        assert ddns.needs_update(last_ip="1.1.1.1", current_ip="2.2.2.2")
        assert not ddns.needs_update(last_ip="1.1.1.1", current_ip="1.1.1.1")
        assert not ddns.needs_update(last_ip="", current_ip="")
        assert not ddns.needs_update(last_ip="1.1.1.1", current_ip="")


# ----------------------------------------------------------------- actualizar
class _Respuesta:
    def __init__(self, cuerpo: bytes) -> None:
        self._cuerpo = cuerpo

    def read(self, limite: int = -1) -> bytes:
        return self._cuerpo if limite < 0 else self._cuerpo[:limite]

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class TestActualizar:
    def test_actualiza_y_devuelve_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        vistas: list[str] = []

        def falso(peticion, timeout=None):  # noqa: ANN001
            vistas.append(peticion.full_url)
            return _Respuesta(b"OK\n")

        monkeypatch.setattr(ddns.urllib.request, "urlopen", falso)
        assert ddns.update("reinotrebol", "token-de-prueba", ip="83.54.12.7") == "OK"
        assert "domains=reinotrebol" in vistas[0]
        assert "ip=83.54.12.7" in vistas[0]
        assert vistas[0].startswith("https://www.duckdns.org/update?")

    def test_si_duckdns_dice_ko_se_avisa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ddns.urllib.request, "urlopen", lambda *a, **k: _Respuesta(b"KO")
        )
        with pytest.raises(DdnsError):
            ddns.update("reinotrebol", "token-de-prueba")

    def test_sin_conexion_se_avisa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error

        def falla(*_args, **_kwargs):
            raise urllib.error.URLError("sin red")

        monkeypatch.setattr(ddns.urllib.request, "urlopen", falla)
        with pytest.raises(DdnsError):
            ddns.update("reinotrebol", "token-de-prueba")

    def test_el_token_no_acaba_en_el_registro(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(
            ddns.urllib.request, "urlopen", lambda *a, **k: _Respuesta(b"KO")
        )
        with caplog.at_level("DEBUG"):
            with pytest.raises(DdnsError):
                ddns.update("reinotrebol", "super-secreto-1234")
        assert "super-secreto-1234" not in caplog.text


# ------------------------------------------------------------------- el modelo
class TestModeloServidor:
    def test_ida_y_vuelta_conserva_el_nombre(self) -> None:
        servidor = make_spec(
            ddns_subdomain="reinotrebol",
            ddns_token="token-de-prueba",
            ddns_auto=True,
            ddns_last_ip="83.54.12.7",
        )
        datos = json.loads(json.dumps(servidor.to_dict()))
        recuperado = ServerSpec.from_dict(datos)
        assert recuperado.ddns_subdomain == "reinotrebol"
        assert recuperado.ddns_token == "token-de-prueba"
        assert recuperado.ddns_auto is True
        assert recuperado.ddns_last_ip == "83.54.12.7"
        assert recuperado.ddns_configured

    def test_la_direccion_publica_lleva_el_puerto(self) -> None:
        servidor = make_spec(ddns_subdomain="reinotrebol", port=2934)
        assert servidor.public_address() == "reinotrebol.duckdns.org:2934"

    def test_sin_nombre_no_hay_direccion_publica(self) -> None:
        assert make_spec().public_address() == ""
        assert not make_spec().ddns_configured

    def test_se_normaliza_al_validar(self) -> None:
        servidor = make_spec(ddns_subdomain="ReinoTrebol")
        assert servidor.validated().ddns_subdomain == "reinotrebol"

    def test_un_nombre_invalido_se_rechaza_al_validar(self) -> None:
        with pytest.raises(ValidationError):
            make_spec(ddns_subdomain="con espacio").validated()


class TestMigracion:
    def test_un_servidor_antiguo_recibe_los_campos_nuevos(self, store: ServerStore, spec) -> None:
        meta = store.meta_file(spec.id)
        datos = json.loads(meta.read_text(encoding="utf-8"))
        for clave in ("ddns_subdomain", "ddns_token", "ddns_auto", "ddns_last_ip"):
            datos.pop(clave, None)
        datos["meta_version"] = 2
        meta.write_text(json.dumps(datos), encoding="utf-8")

        cargado = store.load(spec.id)
        assert cargado.ddns_subdomain == ""
        assert cargado.ddns_auto is False
        assert not cargado.ddns_configured
        # La migracion se guarda para no repetirla en cada arranque.
        datos_nuevos = json.loads(meta.read_text(encoding="utf-8"))
        assert datos_nuevos["meta_version"] == META_VERSION == 3
        assert datos_nuevos["ddns_subdomain"] == ""


# --------------------------------------------------------------- el gestor
class TestGestor:
    @pytest.fixture
    def manager(self, store: ServerStore) -> ServerManager:
        return ServerManager(store=store)

    def test_configura_y_quita_el_nombre(self, manager: ServerManager, spec) -> None:
        guardado = manager.configure_ddns(
            spec.id, subdomain="ReinoTrebol", token="token-de-prueba", auto=True
        )
        assert guardado.ddns_subdomain == "reinotrebol"
        assert guardado.ddns_auto is True
        assert guardado.public_address() == f"reinotrebol.duckdns.org:{spec.port}"

        # Corregir el nombre sin volver a pegar el token.
        otro = manager.configure_ddns(spec.id, subdomain="otro-nombre")
        assert otro.ddns_token == "token-de-prueba"
        assert otro.ddns_auto is True

        vacio = manager.configure_ddns(spec.id, subdomain="")
        assert not vacio.ddns_configured
        assert vacio.ddns_token == ""

    def test_el_modo_automatico_exige_token(self, manager: ServerManager, spec) -> None:
        with pytest.raises(ValidationError):
            manager.configure_ddns(spec.id, subdomain="reinotrebol", token="", auto=True)

    def test_guarda_la_ultima_ip_al_actualizar(
        self, manager: ServerManager, spec, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager.configure_ddns(spec.id, subdomain="reinotrebol", token="token-de-prueba")
        monkeypatch.setattr(ddns, "update", lambda *a, **k: "OK")
        assert manager.ddns_update(spec.id, public_ip="83.54.12.7") == "OK"
        assert manager.store.load(spec.id).ddns_last_ip == "83.54.12.7"

    def test_sin_nombre_no_se_puede_actualizar(self, manager: ServerManager, spec) -> None:
        with pytest.raises(ValidationError):
            manager.ddns_update(spec.id)

    def test_la_actualizacion_automatica_solo_cuando_cambia_la_ip(
        self, manager: ServerManager, spec, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager.configure_ddns(
            spec.id, subdomain="reinotrebol", token="token-de-prueba", auto=True
        )
        llamadas: list[str] = []

        def falso(*_args, **kwargs):  # noqa: ANN003
            llamadas.append(str(kwargs.get("ip", "")))
            return "OK"

        monkeypatch.setattr(ddns, "update", falso)
        assert manager.ddns_auto_update(spec.id, public_ip="1.1.1.1") is True
        # La segunda vez la IP es la misma: no se vuelve a llamar.
        assert manager.ddns_auto_update(spec.id, public_ip="1.1.1.1") is False
        assert llamadas == ["1.1.1.1"]

    def test_sin_automatico_no_se_llama_a_nadie(
        self, manager: ServerManager, spec, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager.configure_ddns(spec.id, subdomain="reinotrebol", token="token-de-prueba")
        monkeypatch.setattr(ddns, "update", lambda *a, **k: pytest.fail("no debia llamarse"))
        assert manager.ddns_auto_update(spec.id, public_ip="1.1.1.1") is False

    def test_un_fallo_de_duckdns_no_rompe_nada(
        self, manager: ServerManager, spec, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager.configure_ddns(
            spec.id, subdomain="reinotrebol", token="token-de-prueba", auto=True
        )

        def falla(*_args, **_kwargs):
            raise DdnsError("sin conexion")

        monkeypatch.setattr(ddns, "update", falla)
        assert manager.ddns_auto_update(spec.id, public_ip="9.9.9.9") is False

    def test_el_estado_del_nombre(self, manager: ServerManager, spec, monkeypatch: pytest.MonkeyPatch) -> None:
        manager.configure_ddns(spec.id, subdomain="reinotrebol", token="token-de-prueba")
        monkeypatch.setattr(ddns, "resolve", lambda *a, **k: {"83.54.12.7"})
        estado = manager.ddns_status(spec.id, public_ip="83.54.12.7")
        assert estado.state == "ok"
        assert estado.hostname == "reinotrebol.duckdns.org"

    def test_sin_nombre_el_estado_lo_dice(self, manager: ServerManager, spec) -> None:
        assert manager.ddns_status(spec.id).state == "sin-configurar"
