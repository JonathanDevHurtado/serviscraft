"""Pruebas del orquestador: creacion, ajustes y cambio de version.

Estas pruebas no lanzan Podman: se sustituyen la descarga de la imagen y la
creacion del contenedor por dobles, de modo que se comprueba toda la logica
(validacion, carpetas, propiedades y definicion guardada).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from serviscraft.core.appconfig import AppConfig
from serviscraft.core.backup import ORIGEN_AL_DETENER, ORIGEN_PROGRAMADA, ORIGENES_AUTOMATICOS
from serviscraft.core.errors import BackupError, ServerStateError, ValidationError
from serviscraft.core.manager import ServerManager
from serviscraft.core.models import ServerSpec, ServerState, ServerType
from serviscraft.core.store import ServerStore

from .conftest import make_spec


@pytest.fixture
def manager(
    store: ServerStore,
    config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> ServerManager:
    """Gestor con Podman simulado (no crea contenedores reales)."""
    instance = ServerManager(store=store, config=config)
    monkeypatch.setattr(instance, "_ensure_image", lambda *a, **k: "imagen")
    monkeypatch.setattr(instance, "_create_container", lambda spec: "contenedor-falso")
    monkeypatch.setattr(instance.client, "container_state", lambda name: ServerState.EXITED)
    monkeypatch.setattr(instance.client, "container_exists", lambda name: False)
    return instance


class TestCrearServidor:
    def test_guarda_la_definicion_las_carpetas_y_las_propiedades(self, manager: ServerManager) -> None:
        spec = manager.create_server(
            name="Mundo de prueba",
            type=ServerType.PAPER,
            version="1.21.4",
            memory_mb=2048,
        )

        assert spec.version == "1.21.4"
        assert spec.type is ServerType.PAPER
        assert spec.memory_mb == 2048
        assert manager.store.load(spec.id).version == "1.21.4"

        data = manager.store.data_dir(spec.id)
        assert data.is_dir()
        assert (data / "server.properties").is_file()
        properties = (data / "server.properties").read_text(encoding="utf-8")
        assert "motd=Mundo de prueba" in properties
        assert "rcon.password=" in properties
        assert "level-name=world" in properties

    def test_rechaza_una_version_con_caracteres_peligrosos(self, manager: ServerManager) -> None:
        with pytest.raises(ValidationError):
            manager.create_server(
                name="Malo",
                type=ServerType.PAPER,
                version="../../etc/passwd",
                memory_mb=1024,
            )

    def test_rechaza_un_nombre_vacio(self, manager: ServerManager) -> None:
        with pytest.raises(ValidationError):
            manager.create_server(name="   ", type=ServerType.PAPER, version="1.21.4")


class TestCambiarVersion:
    def test_cambia_la_version_y_recrea_el_contenedor(
        self,
        manager: ServerManager,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec = make_spec(type="PAPER", version="1.21.4")
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "world").mkdir()
        (store.data_dir(spec.id) / "world" / "level.dat").write_bytes(b"mundo")

        eliminados: list[str] = []
        monkeypatch.setattr(manager.client, "container_exists", lambda name: True)
        monkeypatch.setattr(manager.client, "remove", lambda name, force=False: eliminados.append(name))

        cambiado = manager.change_version(spec.id, "1.20.1", java_tag="java17")

        assert cambiado.version == "1.20.1"
        assert cambiado.java_tag == "java17"
        assert store.load(spec.id).version == "1.20.1"
        assert eliminados == [spec.container_name]
        # El mundo no se toca.
        assert (store.data_dir(spec.id) / "world" / "level.dat").read_bytes() == b"mundo"

    def test_no_permite_cambiar_la_version_con_el_servidor_encendido(
        self,
        manager: ServerManager,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec = make_spec(version="1.21.4")
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.RUNNING)

        with pytest.raises(ServerStateError):
            manager.change_version(spec.id, "1.20.1")

        assert store.load(spec.id).version == "1.21.4"

    def test_no_acepta_una_version_invalida(
        self,
        manager: ServerManager,
        store: ServerStore,
    ) -> None:
        spec = make_spec(version="1.21.4")
        store.prepare_dirs(spec.id)
        store.save(spec)

        with pytest.raises(ValidationError):
            manager.change_version(spec.id, "../../etc/passwd")

        assert store.load(spec.id).version == "1.21.4"


class TestAjustes:
    def test_update_settings_cambia_memoria_puerto_y_java(
        self,
        manager: ServerManager,
        store: ServerStore,
    ) -> None:
        spec = make_spec(memory_mb=1024, port=25565)
        store.prepare_dirs(spec.id)
        store.save(spec)

        actualizado = manager.update_settings(
            spec.id,
            name="Renombrado",
            memory_mb=3072,
            lan=False,
            java_tag="java17",
        )

        assert actualizado.name == "Renombrado"
        assert actualizado.memory_mb == 3072
        assert actualizado.lan is False
        assert actualizado.java_tag == "java17"
        assert store.load(spec.id).memory_mb == 3072


@pytest.fixture
def manager_en_marcha(
    store: ServerStore,
    config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> ServerManager:
    """Gestor con un contenedor que responde «en ejecucion» (sin Podman real)."""
    instance = ServerManager(store=store, config=config)
    monkeypatch.setattr(instance, "_ensure_image", lambda *a, **k: "imagen")
    monkeypatch.setattr(instance, "_create_container", lambda spec: "contenedor-falso")
    monkeypatch.setattr(instance.client, "container_exists", lambda name: True)
    monkeypatch.setattr(instance.client, "container_state", lambda name: ServerState.RUNNING)
    monkeypatch.setattr(instance.client, "stop", lambda name, timeout=90: None)
    monkeypatch.setattr(instance.client, "kill", lambda name: None)
    return instance


def _preparado(manager: ServerManager, store: ServerStore, **overrides) -> ServerSpec:
    """Servidor con datos reales para poder copiarlo."""
    spec = make_spec(**overrides)
    store.prepare_dirs(spec.id)
    store.save(spec)
    data = store.data_dir(spec.id)
    (data / "world").mkdir(exist_ok=True)
    (data / "world" / "level.dat").write_bytes(b"mundo")
    return spec


class TestCopiasAutomaticas:
    def test_al_detener_se_crea_una_copia(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        """El mundo queda copiado en la carpeta del propio servidor."""
        spec = _preparado(manager_en_marcha, store)
        pasos: list[str] = []

        manager_en_marcha.stop_server(spec.id, on_progress=pasos.append)

        copias = manager_en_marcha.backups.list_backups(spec.id)
        assert len(copias) == 1
        assert copias[0].origin == "al-detener"
        assert Path(copias[0].path).is_file()
        assert str(store.backups_dir(spec.id)) in copias[0].path
        assert any("copia" in paso.lower() for paso in pasos)

    def test_se_puede_desactivar_en_las_preferencias(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        spec = _preparado(manager_en_marcha, store)
        manager_en_marcha.config.backup_on_stop = False

        manager_en_marcha.stop_server(spec.id)

        assert manager_en_marcha.backups.list_backups(spec.id) == []

    def test_un_fallo_al_copiar_no_impide_detener(
        self,
        manager_en_marcha: ServerManager,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec = _preparado(manager_en_marcha, store)
        pasos: list[str] = []

        def falla(*_args, **_kwargs):
            raise BackupError("no hay espacio")

        monkeypatch.setattr(manager_en_marcha.backups, "create_backup", falla)

        # No lanza: apagar el servidor es lo prioritario.
        manager_en_marcha.stop_server(spec.id, on_progress=pasos.append)
        assert any("no se pudo" in paso.lower() for paso in pasos)

    def test_la_retencion_solo_borra_copias_automaticas(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        spec = _preparado(manager_en_marcha, store)
        manual = manager_en_marcha.backups.create_backup(spec.id, label="mia", origin="manual")
        for _ in range(4):
            manager_en_marcha.backups.create_backup(spec.id, origin="al-detener")
        manager_en_marcha.config.automatic_backup_keep = 2

        manager_en_marcha.prune_automatic_backups(spec.id)

        restantes = manager_en_marcha.backups.list_backups(spec.id)
        automaticas = [info for info in restantes if info.origin in ORIGENES_AUTOMATICOS]
        assert len(automaticas) == 2
        assert any(info.path == manual.path for info in restantes), "la copia manual nunca se borra"

    def test_conservar_todas_desactiva_la_retencion(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        spec = _preparado(manager_en_marcha, store)
        for _ in range(4):
            manager_en_marcha.backups.create_backup(spec.id, origin="programada")
        manager_en_marcha.config.automatic_backup_keep = 0

        assert manager_en_marcha.prune_automatic_backups(spec.id) == 0
        assert len(manager_en_marcha.backups.list_backups(spec.id)) == 4

    def test_la_copia_programada_solo_toca_los_servidores_en_marcha(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        encendido = _preparado(manager_en_marcha, store)
        apagado = _preparado(manager_en_marcha, store, id="servidor-test02", port=25566)
        encendido_name = encendido.container_name

        original = manager_en_marcha.client.managed_containers
        manager_en_marcha.client.managed_containers = lambda: [
            {"Names": [encendido_name], "State": "running"},
            {"Names": [apagado.container_name], "State": "exited"},
        ]

        creadas = manager_en_marcha.backup_running_servers()

        assert len(creadas) == 1
        assert creadas[0].origin == ORIGEN_PROGRAMADA
        assert len(manager_en_marcha.backups.list_backups(encendido.id)) == 1
        assert manager_en_marcha.backups.list_backups(apagado.id) == []
        manager_en_marcha.client.managed_containers = original

    def test_sin_servidores_en_marcha_no_hace_nada(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        _preparado(manager_en_marcha, store)
        manager_en_marcha.client.managed_containers = lambda: [
            {"Names": ["serviscraft-servidor-test01"], "State": "exited"}
        ]
        assert manager_en_marcha.backup_running_servers() == []

    def test_eliminar_un_servidor_no_duplica_la_copia_de_parada(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        spec = _preparado(manager_en_marcha, store)
        manager_en_marcha.client.remove = lambda name, force=False: None

        # Sin copia previa: al detener para eliminar tampoco se copia.
        manager_en_marcha.delete_server(spec.id, delete_data=False, make_backup=False)
        assert manager_en_marcha.backups.list_backups(spec.id) == []

    def test_eliminar_con_copia_crea_una_sola(
        self, manager_en_marcha: ServerManager, store: ServerStore
    ) -> None:
        spec = _preparado(manager_en_marcha, store)
        manager_en_marcha.client.remove = lambda name, force=False: None

        copia = manager_en_marcha.delete_server(spec.id, delete_data=False, make_backup=True)

        assert copia is not None
        assert copia.origin == "automatica"
        assert len(manager_en_marcha.backups.list_backups(spec.id)) == 1

    def test_reiniciar_guarda_el_mundo_y_lo_copia(
        self,
        manager_en_marcha: ServerManager,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec = _preparado(manager_en_marcha, store)
        monkeypatch.setattr(manager_en_marcha, "check_port_available", lambda port, **k: (True, ""))
        arrancados: list[str] = []
        # Al detener, el contenedor pasa a estar apagado: asi el arranque
        # posterior es realista (no «ya estaba en ejecucion»).
        estado = {"valor": ServerState.RUNNING}
        monkeypatch.setattr(manager_en_marcha.client, "container_state", lambda name: estado["valor"])

        def detener(name, timeout=90):
            estado["valor"] = ServerState.EXITED

        def arrancar(name):
            arrancados.append(name)
            estado["valor"] = ServerState.RUNNING

        monkeypatch.setattr(manager_en_marcha.client, "stop", detener)
        monkeypatch.setattr(manager_en_marcha.client, "start", arrancar)

        manager_en_marcha.restart_server(spec.id)

        assert arrancados == [spec.container_name]
        assert estado["valor"] is ServerState.RUNNING
        copias = manager_en_marcha.backups.list_backups(spec.id)
        assert [info.origin for info in copias] == [ORIGEN_AL_DETENER]

    def test_copiar_varios_servidores_sigue_aunque_uno_falle(
        self,
        manager_en_marcha: ServerManager,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uno = _preparado(manager_en_marcha, store)
        dos = _preparado(manager_en_marcha, store, id="servidor-test03", port=25567)

        original = manager_en_marcha.backups.create_backup

        def copia_selectiva(server_id, **kwargs):
            if server_id == uno.id:
                raise BackupError("disco lleno")
            return original(server_id, **kwargs)

        monkeypatch.setattr(manager_en_marcha.backups, "create_backup", copia_selectiva)

        creadas = manager_en_marcha.backup_servers([uno.id, dos.id], origin="manual")

        assert len(creadas) == 1
        assert creadas[0].path == str(manager_en_marcha.backups.list_backups(dos.id)[0].path)
        assert manager_en_marcha.backups.list_backups(uno.id) == []
