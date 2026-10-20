"""Pruebas del soporte de Bedrock: Geyser/Floodgate, puerto UDP y manifiesto.

Se comprueba que activar Bedrock no toca el mundo ni los mods, que solo se
permite en servidores con pluguins, que el puerto va por UDP y que el manifiesto
de mods recuerda de que proyecto salio cada fichero (sin romper los antiguos).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from serviscraft.core import bedrock, mods
from serviscraft.core.appconfig import AppConfig
from serviscraft.core.errors import ValidationError
from serviscraft.core.manager import ServerManager
from serviscraft.core.models import ServerState, ServerType
from serviscraft.core.podman import PodmanClient
from serviscraft.core.store import ServerStore

from .conftest import make_spec


@pytest.fixture
def manager(store: ServerStore, config: AppConfig, monkeypatch: pytest.MonkeyPatch) -> ServerManager:
    instance = ServerManager(store=store, config=config)
    monkeypatch.setattr(instance, "_ensure_image", lambda *a, **k: "imagen")
    monkeypatch.setattr(instance, "_create_container", lambda spec: "contenedor-falso")
    monkeypatch.setattr(instance.client, "container_state", lambda name: ServerState.EXITED)
    monkeypatch.setattr(instance.client, "container_exists", lambda name: False)
    monkeypatch.setattr(instance.client, "remove", lambda name, force=False: None)
    return instance


# =========================================================== manifiesto de mods
class TestManifiestoDeProyectos:
    def _inventario(self, store: ServerStore, spec) -> mods.ModsInventory:
        store.prepare_dirs(spec.id)
        store.save(spec)
        return mods.ModsInventory(store, spec.id, folder="plugins")

    def test_recuerda_de_que_proyecto_salio_cada_fichero(self, store: ServerStore) -> None:
        spec = make_spec(type=ServerType.PAPER)
        inventario = self._inventario(store, spec)
        (inventario.folder_path).mkdir(parents=True, exist_ok=True)
        (inventario.folder_path / "EssentialsX.jar").write_bytes(b"jar")

        inventario.remember_project(
            "EssentialsX.jar",
            slug="essentialsx",
            title="EssentialsX",
            icon="https://cdn.modrinth.com/data/abc/icon.png",
        )
        datos = inventario.project_for("EssentialsX.jar")
        assert datos["slug"] == "essentialsx"
        assert datos["titulo"] == "EssentialsX"
        assert datos["icono"].endswith("icon.png")

        entrada = inventario.list_mods()[0]
        assert entrada.title == "EssentialsX"
        assert entrada.icon_url.endswith("icon.png")

    def test_al_desactivar_sigue_sabiendo_cual_era(self, store: ServerStore) -> None:
        spec = make_spec(type=ServerType.PAPER)
        inventario = self._inventario(store, spec)
        inventario.folder_path.mkdir(parents=True, exist_ok=True)
        (inventario.folder_path / "Vault.jar").write_bytes(b"jar")
        inventario.remember_project("Vault.jar", title="Vault", icon="https://x/icono.png")

        inventario.set_enabled("Vault.jar", False)
        entrada = inventario.list_mods()[0]
        assert not entrada.enabled
        # El fichero se renombro, pero los datos del proyecto siguen ahi.
        assert entrada.icon_url == "https://x/icono.png"

    def test_conserva_la_lista_de_personalizados(self, store: ServerStore) -> None:
        spec = make_spec(type=ServerType.PAPER)
        inventario = self._inventario(store, spec)
        inventario.folder_path.mkdir(parents=True, exist_ok=True)
        inventario.mark_custom("a.jar")
        inventario.remember_project("a.jar", title="A", icon="https://x/a.png")

        datos = json.loads(inventario.manifest_path.read_text(encoding="utf-8"))
        assert datos["personalizados"] == ["a.jar"]
        assert datos["proyectos"]["a.jar"]["titulo"] == "A"

    def test_un_manifiesto_antiguo_sigue_valiendo(self, store: ServerStore) -> None:
        spec = make_spec(type=ServerType.PAPER)
        inventario = self._inventario(store, spec)
        inventario.folder_path.mkdir(parents=True, exist_ok=True)
        (inventario.folder_path / "viejo.jar").write_bytes(b"jar")
        inventario.manifest_path.write_text(
            json.dumps({"personalizados": ["viejo.jar"]}), encoding="utf-8"
        )

        entrada = inventario.list_mods()[0]
        assert entrada.custom
        assert entrada.icon_url == ""  # no hay datos de proyecto, no falla
        assert inventario.project_for("viejo.jar") == {}

    def test_un_manifiesto_roto_no_rompe_la_lista(self, store: ServerStore) -> None:
        spec = make_spec(type=ServerType.PAPER)
        inventario = self._inventario(store, spec)
        inventario.folder_path.mkdir(parents=True, exist_ok=True)
        (inventario.folder_path / "x.jar").write_bytes(b"jar")
        inventario.manifest_path.write_text("{ esto no es json", encoding="utf-8")
        assert len(inventario.list_mods()) == 1


# ================================================== Geyser (auth de Floodgate)
CONFIG_GEYSER = """# Configuracion de Geyser
bedrock:
  port: 19132
remote:
  address: auto
auth-type: online
"""


class TestConfigDeGeyser:
    def test_cambia_la_autenticacion_a_floodgate(self, tmp_path: Path) -> None:
        ruta = bedrock.geyser_config_path(tmp_path)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(CONFIG_GEYSER, encoding="utf-8")

        assert bedrock.needs_floodgate_auth(tmp_path)
        assert bedrock.ensure_floodgate_auth(tmp_path)
        assert "auth-type: floodgate" in ruta.read_text(encoding="utf-8")
        # Al volver a mirarlo ya no hay nada que cambiar.
        assert not bedrock.needs_floodgate_auth(tmp_path)
        assert not bedrock.ensure_floodgate_auth(tmp_path)

    def test_no_toca_los_demas_ajustes(self, tmp_path: Path) -> None:
        ruta = bedrock.geyser_config_path(tmp_path)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(CONFIG_GEYSER, encoding="utf-8")
        bedrock.ensure_floodgate_auth(tmp_path)
        texto = ruta.read_text(encoding="utf-8")
        assert "port: 19132" in texto
        assert "address: auto" in texto

    def test_si_no_existe_el_fichero_no_hace_nada(self, tmp_path: Path) -> None:
        assert not bedrock.ensure_floodgate_auth(tmp_path)
        assert not bedrock.needs_floodgate_auth(tmp_path)
        assert not bedrock.geyser_config_path(tmp_path).exists()

    def test_detecta_si_floodgate_esta_instalado(self, tmp_path: Path) -> None:
        assert not bedrock.floodgate_installed(tmp_path)
        carpeta = tmp_path / "plugins"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / bedrock.FLOODGATE_JAR).write_bytes(b"jar")
        assert bedrock.floodgate_installed(tmp_path)


# =================================================================== el gestor
class TestActivarBedrock:
    def test_solo_lo_admiten_los_servidores_con_pluguis(self, manager: ServerManager) -> None:
        spec = manager.create_server(name="Vanilla", type=ServerType.VANILLA, version="1.21.4")
        disponible, motivo = manager.bedrock_available(spec)
        assert not disponible
        assert "Paper" in motivo
        with pytest.raises(ValidationError):
            manager.set_bedrock(spec.id, enabled=True)

    def test_activa_el_puerto_udp_y_guarda_la_definicion(self, manager: ServerManager) -> None:
        spec = manager.create_server(name="Con Bedrock", type=ServerType.PAPER, version="1.21.4")
        actualizado = manager.set_bedrock(spec.id, enabled=True, port=19132)
        assert actualizado.bedrock
        assert actualizado.bedrock_port == 19132
        assert actualizado.bedrock_enabled
        assert manager.store.load(spec.id).bedrock_enabled
        # La imagen recibe los pluguins que hay que descargar.
        assert "geyser" in actualizado.plugins_env
        assert "floodgate" in actualizado.plugins_env

    def test_desactivar_lo_deja_como_estaba(self, manager: ServerManager) -> None:
        spec = manager.create_server(name="Con Bedrock", type=ServerType.PAPER, version="1.21.4")
        manager.set_bedrock(spec.id, enabled=True)
        apagado = manager.set_bedrock(spec.id, enabled=False)
        assert not apagado.bedrock_enabled
        assert apagado.plugins_env == ""

    def test_si_el_puerto_esta_ocupado_busca_el_siguiente(self, manager: ServerManager) -> None:
        primero = manager.create_server(name="Uno", type=ServerType.PAPER, version="1.21.4")
        segundo = manager.create_server(name="Dos", type=ServerType.PAPER, version="1.21.4")
        manager.set_bedrock(primero.id, enabled=True, port=19132)
        # El 19132 ya lo reservo el primero: el segundo toma el siguiente libre.
        otro = manager.set_bedrock(segundo.id, enabled=True)
        assert otro.bedrock_port != 19132
        # Los dos servidores quedan con puertos distintos y reservados.
        assert otro.bedrock_port in manager.store.used_ports()

    def test_el_puerto_de_bedrock_queda_reservado(self, manager: ServerManager) -> None:
        spec = manager.create_server(name="Con Bedrock", type=ServerType.PAPER, version="1.21.4")
        manager.set_bedrock(spec.id, enabled=True, port=19133)
        assert 19133 in manager.store.used_ports()

    def test_no_se_puede_cambiar_con_el_servidor_en_marcha(
        self, manager: ServerManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from serviscraft.core.errors import ServerStateError

        spec = manager.create_server(name="Con Bedrock", type=ServerType.PAPER, version="1.21.4")
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.RUNNING)
        with pytest.raises(ServerStateError):
            manager.set_bedrock(spec.id, enabled=True)

    def test_crear_directamente_con_bedrock(self, manager: ServerManager) -> None:
        spec = manager.create_server(
            name="Desde el asistente",
            type=ServerType.PAPER,
            version="1.21.4",
            bedrock=True,
        )
        assert spec.bedrock_enabled
        assert spec.bedrock_port == 19132

    def test_crear_con_bedrock_en_vanilla_es_un_error(self, manager: ServerManager) -> None:
        with pytest.raises(ValidationError):
            manager.create_server(
                name="Vanilla", type=ServerType.VANILLA, version="1.21.4", bedrock=True
            )

    def test_aplica_la_configuracion_de_geyser_al_arrancar(self, manager: ServerManager) -> None:
        spec = manager.create_server(
            name="Con Bedrock", type=ServerType.PAPER, version="1.21.4", bedrock=True
        )
        data = manager.store.data_dir(spec.id)
        ruta = bedrock.geyser_config_path(data)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(CONFIG_GEYSER, encoding="utf-8")

        assert manager.apply_bedrock_config(spec.id) is True
        assert "auth-type: floodgate" in ruta.read_text(encoding="utf-8")
        # Sin Bedrock activado no se toca nada.
        manager.set_bedrock(spec.id, enabled=False)
        ruta.write_text(CONFIG_GEYSER, encoding="utf-8")
        assert manager.apply_bedrock_config(spec.id) is False
        assert "auth-type: online" in ruta.read_text(encoding="utf-8")


class TestPuertoUDP:
    def test_el_contenedor_publica_el_puerto_de_bedrock_en_udp(
        self, store: ServerStore, config: AppConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instancia = ServerManager(store=store, config=config)
        capturado: dict[str, list] = {}

        def falso_create(*, published_ports=(), **resto):
            capturado["puertos"] = list(published_ports)
            return "contenedor"

        monkeypatch.setattr(instancia.client, "create", falso_create)
        monkeypatch.setattr(instancia.client, "container_exists", lambda name: False)
        monkeypatch.setattr(instancia, "_container_runtime", lambda spec: ({}, {}))
        spec = make_spec(type=ServerType.PAPER, bedrock=True)
        store.prepare_dirs(spec.id)
        store.save(spec)

        instancia._create_container(spec)

        puertos = capturado["puertos"]
        assert (spec.bind_address(), spec.port, 25565) in puertos
        assert (spec.bind_address(), spec.bedrock_port, 19132, "udp") in puertos

    def test_sin_bedrock_no_se_publica_ningun_udp(
        self, store: ServerStore, config: AppConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instancia = ServerManager(store=store, config=config)
        capturado: dict[str, list] = {}
        monkeypatch.setattr(
            instancia.client,
            "create",
            lambda *, published_ports=(), **resto: capturado.setdefault("puertos", list(published_ports)),
        )
        monkeypatch.setattr(instancia.client, "container_exists", lambda name: False)
        monkeypatch.setattr(instancia, "_container_runtime", lambda spec: ({}, {}))
        spec = make_spec(type=ServerType.PAPER)
        store.prepare_dirs(spec.id)
        store.save(spec)

        instancia._create_container(spec)
        assert all(len(puerto) == 3 for puerto in capturado["puertos"])

    def test_la_orden_de_podman_lleva_el_sufijo_udp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cliente = PodmanClient()
        ordenes: list[tuple[str, ...]] = []

        def falso_run(args, **kwargs):
            ordenes.append(tuple(args))

            class _Resultado:
                stdout = "abc123"
                returncode = 0

            return _Resultado()

        monkeypatch.setattr(cliente, "run", falso_run)
        cliente.create(
            name="c",
            image="imagen",
            env={},
            published_ports=[("0.0.0.0", 25565, 25565), ("0.0.0.0", 19132, 19132, "udp")],
            volumes=[],
            labels={},
        )
        argumentos = ordenes[0]
        assert "0.0.0.0:25565:25565" in argumentos
        assert "0.0.0.0:19132:19132/udp" in argumentos
