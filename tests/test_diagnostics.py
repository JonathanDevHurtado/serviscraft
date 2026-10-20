"""Pruebas del diagnostico de fallos de arranque y de la reparacion de Java.

El caso real que motiva estas pruebas: un servidor creado con la etiqueta
``java21`` paso a descargar Minecraft 26.3 (que exige Java 25) y murio al
arrancar. La aplicacion debe detectarlo antes de arrancar y, si aun asi muere,
explicar el motivo sin perder el mundo.
"""

from __future__ import annotations


import pytest

from serviscraft.core.appconfig import AppConfig
from serviscraft.core.diagnostics import (
    KIND_JAVA,
    KIND_MEMORY,
    KIND_PORT,
    KIND_UNKNOWN,
    KIND_VERSION,
    diagnose_start_failure,
    required_java_from_log,
)
from serviscraft.core.manager import ServerManager
from serviscraft.core.models import ServerState, ServerType
from serviscraft.core.store import ServerStore

from .conftest import make_spec

#: Linea exacta que escribio el servidor del usuario.
PAPER_26_3 = (
    "[init] Starting the Minecraft server...\n"
    "Minecraft 26.1 and newer requires running the server with Java 25 or above. "
    "For information on how to update Java, see https://docs.papermc.io/misc/java-install\n"
    "mc-server-runner\tMinecraft server failed. Inspect logs above for errors that "
    "indicate cause.\n"
)


class TestDiagnostico:
    def test_detecta_el_java_que_falta_en_el_registro(self) -> None:
        assert required_java_from_log(PAPER_26_3) == 25

    def test_explica_el_fallo_de_java_y_propone_la_etiqueta(self) -> None:
        failure = diagnose_start_failure(
            PAPER_26_3, version="26.3", java_tag="java21"
        )
        assert failure.kind == KIND_JAVA
        assert failure.java_major == 25
        assert failure.suggested_java_tag == "java25"
        assert failure.repairable
        assert "Java 25" in failure.message
        assert "el mundo y el contenido no se tocan" in failure.message

    def test_no_propone_cambiar_java_si_ya_es_suficiente(self) -> None:
        failure = diagnose_start_failure(
            PAPER_26_3, version="26.3", java_tag="java25"
        )
        assert failure.kind != KIND_JAVA

    def test_no_propone_etiquetas_de_java_para_una_imagen_ajena(self) -> None:
        failure = diagnose_start_failure(
            PAPER_26_3,
            version="26.3",
            java_tag="java21",
            image="registry.example.com/mi/minecraft:raro",
        )
        assert failure.kind == KIND_JAVA
        assert not failure.repairable
        assert "Actualiza Serviscraft" in failure.message

    def test_detecta_una_version_inexistente(self) -> None:
        failure = diagnose_start_failure(
            "Failed to download the server jar for version 9.9.9\n",
            version="9.9.9",
            java_tag="java21",
        )
        assert failure.kind == KIND_VERSION
        assert "elige otra version" in failure.message.lower()

    def test_detecta_falta_de_memoria(self) -> None:
        failure = diagnose_start_failure(
            "java.lang.OutOfMemoryError: Java heap space\n",
            version="1.21.4",
            java_tag="java21",
        )
        assert failure.kind == KIND_MEMORY
        assert "Sube la RAM" in failure.message

    def test_detecta_el_puerto_ocupado(self) -> None:
        failure = diagnose_start_failure(
            "java.net.BindException: Address already in use\n",
            version="1.21.4",
            java_tag="java21",
        )
        assert failure.kind == KIND_PORT

    def test_sin_pistas_devuelve_una_explicacion_generica(self) -> None:
        failure = diagnose_start_failure(
            "algo salio mal\n", version="1.21.4", java_tag="java21"
        )
        assert failure.kind == KIND_UNKNOWN
        assert "Registros" in failure.message

    def test_entiende_el_numero_de_clase_de_java(self) -> None:
        texto = "java.lang.UnsupportedClassVersionError: class file version 69.0"
        assert required_java_from_log(texto) == 25


@pytest.fixture
def manager(
    store: ServerStore,
    config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> ServerManager:
    instance = ServerManager(store=store, config=config)
    monkeypatch.setattr(instance, "_ensure_image", lambda *a, **k: "imagen")
    monkeypatch.setattr(instance, "_create_container", lambda spec: "contenedor-falso")
    monkeypatch.setattr(instance.client, "container_state", lambda name: ServerState.EXITED)
    monkeypatch.setattr(instance.client, "container_exists", lambda name: False)
    monkeypatch.setattr(instance.client, "start", lambda name: None)
    return instance


class TestReparacionDeJava:
    def test_un_servidor_antiguo_se_corrige_solo_al_arrancar(
        self, manager: ServerManager, store: ServerStore, populated_server
    ) -> None:
        """Regresion: «Prueba» (Minecraft 26.3 + java21) moria al arrancar."""
        spec = populated_server
        spec.version = "26.3"
        spec.java_tag = "java21"
        store.save(spec)
        mensajes: list[str] = []

        manager.start_server(spec.id, on_progress=mensajes.append)

        guardado = store.load(spec.id)
        assert guardado.java_tag == "java25"
        assert any("necesita Java 25" in mensaje for mensaje in mensajes)
        assert any("no se tocan" in mensaje for mensaje in mensajes)

    def test_la_reparacion_no_toca_el_mundo(
        self, manager: ServerManager, store: ServerStore, populated_server
    ) -> None:
        spec = populated_server
        spec.version = "26.3"
        store.save(spec)
        data = store.data_dir(spec.id)

        manager.start_server(spec.id)

        assert (data / "world" / "level.dat").read_bytes() == b"nivel"
        assert (data / "world" / "region" / "r.0.0.mca").stat().st_size == 512
        assert (data / "plugins" / "ejemplo.jar").read_bytes() == b"jar"

    def test_no_cambia_java_si_la_etiqueta_ya_vale(
        self, manager: ServerManager, store: ServerStore
    ) -> None:
        spec = make_spec(version="1.21.4", java_tag="java21")
        store.prepare_dirs(spec.id)
        store.save(spec)
        mensajes: list[str] = []

        manager.start_server(spec.id, on_progress=mensajes.append)

        assert store.load(spec.id).java_tag == "java21"
        assert not any("se cambia a" in mensaje for mensaje in mensajes)

    def test_java_obsoleto_se_detecta_sin_arrancar(self, manager: ServerManager) -> None:
        spec = make_spec(version="26.3", java_tag="java21")
        assert manager.outdated_java_tag(spec) == "java25"

    def test_una_imagen_ajena_no_se_toca(self, manager: ServerManager) -> None:
        """Si la etiqueta no es ``javaNN`` no se adivina: la imagen es otra cosa."""
        spec = make_spec(
            version="26.3",
            java_tag="mi-etiqueta",
            image="registry.example.com/mi/minecraft",
        )
        assert manager.outdated_java_tag(spec) == ""

    def test_diagnostico_solo_cuando_el_servidor_esta_detenido(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(
            manager.client, "container_state", lambda name: ServerState.RUNNING
        )
        assert manager.diagnose_start_failure(spec.id) is None

    def test_repara_y_dice_que_si_cuando_el_fallo_es_de_java(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec(version="26.3", java_tag="java21")
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_exists", lambda name: True)
        monkeypatch.setattr(manager.client, "logs_text", lambda name, tail=150: PAPER_26_3)
        fallo = manager.diagnose_start_failure(spec.id)
        assert fallo is not None and fallo.kind == KIND_JAVA

        assert manager.repair_start_failure(spec.id, fallo) is True
        assert store.load(spec.id).java_tag == "java25"
        # La segunda vez ya no hay nada que reparar.
        assert manager.repair_start_failure(spec.id, fallo) is False


def test_la_etiqueta_de_java_se_guarda_en_la_definicion(
    manager: ServerManager, store: ServerStore
) -> None:
    spec = manager.create_server(
        name="Nuevo",
        type=ServerType.PAPER,
        version="26.3",
        memory_mb=2048,
    )
    assert spec.java_tag == "java25"
    assert store.load(spec.id).java_tag == "java25"
