"""Pruebas de la gestion de jugadores (RCON + ficheros del servidor).

No hay red ni servidor real: se sustituyen la consola RCON y el motor de
contenedores por dobles, de modo que se comprueba el analisis de respuestas, la
validacion de nombres y la composicion de los comandos.
"""

from __future__ import annotations

import json

import pytest

from serviscraft.core.appconfig import AppConfig
from serviscraft.core.errors import ServerStateError, ValidationError
from serviscraft.core.manager import ServerManager
from serviscraft.core.models import ServerState
from serviscraft.core.players import (
    ACTIONS_BY_KEY,
    PLAYER_ACTIONS,
    PlayersSnapshot,
    add_list_entry,
    apply_offline_action,
    build_command,
    offline_uuid,
    parse_player_list,
    parse_whitelist,
    read_entries,
    read_names_file,
    remove_list_entry,
    validate_player_name,
)
from serviscraft.core.store import ServerStore

from .conftest import make_spec


class TestValidacionDeNombres:
    def test_acepta_nombres_normales_y_de_bedrock(self) -> None:
        assert validate_player_name("  Ana_1  ") == "Ana_1"
        assert validate_player_name(".JugadorBedrock") == ".JugadorBedrock"

    @pytest.mark.parametrize(
        "nombre",
        ["", "   ", "Ana Luis", "Ana;rm -rf /", "Ana\nlist", "comillas\"", "a" * 40, "Ana$USER"],
    )
    def test_rechaza_nombres_peligrosos_o_invalidos(self, nombre: str) -> None:
        with pytest.raises(ValidationError):
            validate_player_name(nombre)


class TestComandos:
    def test_todas_las_acciones_componen_un_comando_seguro(self) -> None:
        for action in PLAYER_ACTIONS:
            comando = build_command(action.key, "Ana_1")
            assert "Ana_1" in comando or "{player}" not in action.command
            assert "\n" not in comando

    def test_una_accion_desconocida_falla(self) -> None:
        with pytest.raises(ValidationError):
            build_command("autodestruir", "Ana_1")

    def test_un_nombre_invalido_nunca_llega_al_comando(self) -> None:
        with pytest.raises(ValidationError):
            build_command("ban", "Ana; stop")

    def test_bloquear_esta_marcado_como_destructivo(self) -> None:
        assert ACTIONS_BY_KEY["ban"].destructive is True
        assert ACTIONS_BY_KEY["op"].destructive is False


class TestAnalisisDeRespuestas:
    def test_lista_moderna_y_antigua(self) -> None:
        assert parse_player_list("There are 2 of a max of 20 players online: Ana, Luis") == (["Ana", "Luis"], 20)
        assert parse_player_list("There are 1/10 players online: Ana") == (["Ana"], 10)
        assert parse_player_list("There are 0 of a max of 20 players online:") == ([], 20)

    def test_respuesta_desconocida_no_rompe(self) -> None:
        assert parse_player_list("Unknown command") == ([], 0)

    def test_lista_blanca(self) -> None:
        assert parse_whitelist("There are 2 whitelisted players: Ana, Luis") == ["Ana", "Luis"]
        assert parse_whitelist("There are no whitelisted players") == []


class TestFicherosDeJugadores:
    def test_lee_whitelist_y_ops(self, tmp_path) -> None:
        whitelist = tmp_path / "whitelist.json"
        whitelist.write_text(json.dumps([{"uuid": "1", "name": "Ana"}, {"uuid": "2", "name": "luis"}]), encoding="utf-8")
        ops = tmp_path / "ops.json"
        ops.write_text(json.dumps([{"uuid": "1", "name": "Ana", "level": 4}]), encoding="utf-8")

        assert read_names_file(whitelist) == ["Ana", "luis"]
        assert read_names_file(ops) == ["Ana"]

    def test_fichero_danado_o_ausente_devuelve_lista_vacia(self, tmp_path) -> None:
        roto = tmp_path / "whitelist.json"
        roto.write_text("{no es json", encoding="utf-8")
        assert read_names_file(roto) == []
        assert read_names_file(tmp_path / "no-existe.json") == []


class TestSnapshot:
    def test_conoce_a_todos_los_jugadores_sin_duplicados(self) -> None:
        snapshot = PlayersSnapshot(
            online=("Ana",),
            whitelist=("ana", "Luis"),
            ops=("Luis",),
            max_players=20,
            running=True,
        )
        assert snapshot.known == ("Ana", "Luis")
        assert snapshot.is_online("ana")
        assert snapshot.in_whitelist("ANA")
        assert snapshot.is_op("luis")
        assert not snapshot.is_op("Ana")

    def test_los_bloqueados_tambien_aparecen(self) -> None:
        snapshot = PlayersSnapshot(banned=("Troll",), whitelist=("Ana",))

        assert snapshot.known == ("Ana", "Troll")
        assert snapshot.is_banned("troll")
        assert not snapshot.is_banned("Ana")
        assert snapshot.to_dict()["banned"] == ["Troll"]

    def test_se_puede_serializar(self) -> None:
        datos = PlayersSnapshot(online=("Ana",), running=True).to_dict()
        assert datos["online"] == ["Ana"]
        assert datos["known"] == ["Ana"]


@pytest.fixture
def manager(store: ServerStore, config: AppConfig, monkeypatch: pytest.MonkeyPatch) -> ServerManager:
    instance = ServerManager(store=store, config=config)
    monkeypatch.setattr(instance.client, "container_exists", lambda name: True)
    return instance


class TestManagerDeJugadores:
    def test_con_el_servidor_detenido_lee_los_ficheros(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        (store.data_dir(spec.id) / "ops.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        (store.data_dir(spec.id) / "banned-players.json").write_text(
            json.dumps([{"uuid": "3", "name": "Troll"}]), encoding="utf-8"
        )
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.EXITED)

        snapshot = manager.players_snapshot(spec.id)

        assert snapshot.running is False
        assert snapshot.whitelist == ("Ana",)
        assert snapshot.ops == ("Ana",)
        assert snapshot.banned == ("Troll",)
        assert snapshot.online == ()
        assert "detenido" in snapshot.note

    def test_con_el_servidor_en_marcha_consulta_la_consola(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.RUNNING)
        comandos: list[str] = []

        def falso_send_command(server_id: str, command: str, **_kwargs) -> str:
            comandos.append(command)
            if command == "list":
                return "There are 1 of a max of 20 players online: Ana"
            return "There are 2 whitelisted players: Ana, Luis"

        monkeypatch.setattr(manager, "send_command", falso_send_command)

        snapshot = manager.players_snapshot(spec.id)

        assert comandos == ["list", "whitelist list"]
        assert snapshot.online == ("Ana",)
        assert snapshot.max_players == 20
        assert snapshot.whitelist == ("Ana", "Luis")
        assert snapshot.note == ""

    def test_si_la_consola_falla_lo_dice_sin_romper(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from serviscraft.core.errors import RconError

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.RUNNING)

        def falla(*_args, **_kwargs):
            raise RconError("sin conexion")

        monkeypatch.setattr(manager, "send_command", falla)
        snapshot = manager.players_snapshot(spec.id)
        assert snapshot.running is True
        assert "sin conexion" in snapshot.note

    def test_las_listas_funcionan_con_el_servidor_detenido(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dar OP sin servidor ya no es un error: se guarda en ``ops.json``."""
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.EXITED)

        mensaje = manager.run_player_action(spec.id, "op", "Ana")
        assert "operador" in mensaje
        assert (store.data_dir(spec.id) / "ops.json").is_file()

        with pytest.raises(ServerStateError):
            manager.run_player_action(spec.id, "kick", "Ana")

    def test_las_acciones_envian_el_comando_validado(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.RUNNING)
        enviados: list[str] = []
        monkeypatch.setattr(
            manager,
            "send_command",
            lambda server_id, command, **_k: enviados.append(command) or "ok",
        )

        assert manager.run_player_action(spec.id, "whitelist_add", "Ana_1") == "ok"
        assert enviados == ["whitelist add Ana_1"]

        with pytest.raises(ValidationError):
            manager.run_player_action(spec.id, "whitelist_add", "Ana; stop")


class TestListasSinServidor:
    """Las listas se pueden preparar con el servidor apagado."""

    def test_uuid_sin_premium_es_el_que_usa_java(self) -> None:
        # Valor conocido de Java para Notch sin cuenta premium.
        assert offline_uuid("Notch") == "b50ad385-829d-3141-a216-7e7d7539ba7f"
        assert offline_uuid("Ana") == offline_uuid("Ana")
        assert offline_uuid("Ana") != offline_uuid("ana")

    def test_anadir_y_quitar_lista_blanca(
        self, manager: ServerManager, store: ServerStore
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)

        mensaje = apply_offline_action(store.data_dir(spec.id), "whitelist_add", "Ana")
        assert "Ana" in mensaje
        datos = json.loads(
            (store.data_dir(spec.id) / "whitelist.json").read_text(encoding="utf-8")
        )
        assert datos == [{"uuid": offline_uuid("Ana"), "name": "Ana"}]

        repetido = apply_offline_action(store.data_dir(spec.id), "whitelist_add", "ana")
        assert "ya estaba" in repetido
        assert len(read_entries(store.data_dir(spec.id) / "whitelist.json")) == 1

        apply_offline_action(store.data_dir(spec.id), "whitelist_remove", "Ana")
        assert read_entries(store.data_dir(spec.id) / "whitelist.json") == []

    def test_bloquear_y_perdonar(self, manager: ServerManager, store: ServerStore) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        data = store.data_dir(spec.id)

        assert "bloqueado" in apply_offline_action(data, "ban", "Luis")
        entrada = read_entries(data / "banned-players.json")[0]
        assert entrada["name"] == "Luis"
        assert entrada["expires"] == "forever"
        assert entrada["reason"]

        assert "perdonado" in apply_offline_action(data, "pardon", "Luis")
        assert read_entries(data / "banned-players.json") == []

    def test_operadores_conservan_sus_campos(
        self, manager: ServerManager, store: ServerStore
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        data = store.data_dir(spec.id)
        ops = data / "ops.json"
        # Una entrada con campos propios del servidor no se debe perder.
        ops.write_text(
            json.dumps([{"uuid": "u-1", "name": "Ana", "level": 3, "bypassesPlayerLimit": True}]),
            encoding="utf-8",
        )

        assert add_list_entry(ops, "Luis", extra={"level": 4, "bypassesPlayerLimit": False})
        entradas = {e["name"]: e for e in read_entries(ops)}
        assert entradas["Ana"]["level"] == 3
        assert entradas["Luis"]["level"] == 4

        assert remove_list_entry(ops, "Ana")
        assert [e["name"] for e in read_entries(ops)] == ["Luis"]
        assert not remove_list_entry(ops, "Ana")

    def test_expulsar_necesita_el_servidor(
        self, manager: ServerManager, store: ServerStore
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        with pytest.raises(ServerStateError):
            manager.run_player_action(spec.id, "kick", "Ana")

    def test_apagado_escribe_las_listas_sin_rcon(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.EXITED)
        monkeypatch.setattr(
            manager,
            "send_command",
            lambda *_a, **_k: pytest.fail("no se debe usar RCON con el servidor apagado"),
        )

        manager.run_player_action(spec.id, "op", "Ana")
        assert [e["name"] for e in read_entries(store.data_dir(spec.id) / "ops.json")] == ["Ana"]

    def test_activar_la_lista_blanca(
        self, manager: ServerManager, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        monkeypatch.setattr(manager.client, "container_state", lambda name: ServerState.EXITED)

        manager.set_whitelist_enabled(spec.id, True)
        assert manager.properties(spec.id).get_bool("white-list") is True
        manager.set_whitelist_enabled(spec.id, False)
        assert manager.properties(spec.id).get_bool("white-list") is False
