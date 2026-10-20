"""Pruebas de los modelos de datos."""

from __future__ import annotations

import pytest

from serviscraft.core.errors import ValidationError
from serviscraft.core.models import (
    ServerSpec,
    ServerState,
    ServerStats,
    ServerType,
    format_bytes,
    new_server_id,
)

from .conftest import make_spec


class TestServerType:
    @pytest.mark.parametrize("valor", ["vanilla", "VANILLA", " Vanilla "])
    def test_from_value(self, valor: str) -> None:
        assert ServerType.from_value(valor) is ServerType.VANILLA

    def test_from_value_invalido(self) -> None:
        with pytest.raises(ValueError):
            ServerType.from_value("bedrock")

    def test_capacidades(self) -> None:
        assert ServerType.PAPER.supports_plugins
        assert not ServerType.PAPER.supports_mods
        assert ServerType.FABRIC.supports_mods
        assert ServerType.FORGE.supports_mods
        assert not ServerType.VANILLA.supports_plugins
        assert not ServerType.VANILLA.supports_mods


class TestServerState:
    def test_etiquetas(self) -> None:
        assert ServerState.RUNNING.label == "En ejecucion"
        assert ServerState.CREATED.label == "Creado (sin iniciar)"

    def test_is_running(self) -> None:
        assert ServerState.RUNNING.is_running
        assert not ServerState.EXITED.is_running
        assert not ServerState.CREATED.is_running


class TestServerSpec:
    def test_nombres_derivados(self) -> None:
        spec = make_spec(name="Mi mundo")
        assert spec.container_name == f"serviscraft-{spec.id}"
        assert spec.image_ref == "docker.io/itzg/minecraft-server:java21"
        assert spec.memory_label == "2G"

    def test_bind_address(self) -> None:
        assert make_spec(lan=True).bind_address() == "0.0.0.0"
        assert make_spec(lan=False).bind_address() == "127.0.0.1"

    def test_container_env(self) -> None:
        spec = make_spec(type="PAPER", version="1.21.4", memory_mb=1024)
        env = spec.container_env(run_uid=1000, run_gid=1000)
        assert env["EULA"] == "TRUE"
        assert env["TYPE"] == "PAPER"
        assert env["VERSION"] == "1.21.4"
        assert env["MEMORY"] == "1G"
        assert env["ENABLE_RCON"] == "true"
        assert env["RCON_PORT"] == "25575"
        assert env["SERVER_PORT"] == "25565"
        assert env["UID"] == "1000"
        assert env["GID"] == "1000"
        assert env["RCON_PASSWORD"] == spec.rcon_password

    def test_extra_env_se_mezcla(self) -> None:
        spec = make_spec(extra_env={"MOTD": "Hola", "ONLINE_MODE": "false"})
        env = spec.container_env()
        assert env["MOTD"] == "Hola"
        assert env["ONLINE_MODE"] == "false"

    def test_serializacion_ida_y_vuelta(self) -> None:
        original = make_spec(lan=False, notes="una nota", extra_env={"X": "1"})
        recuperado = ServerSpec.from_dict(original.to_dict())
        assert recuperado.to_dict() == original.to_dict()

    def test_to_dict_no_expone_password_en_repr(self) -> None:
        spec = make_spec()
        assert spec.rcon_password in spec.to_dict()["rcon_password"]

    def test_validated_corrige_el_tipo(self) -> None:
        spec = ServerSpec(
            id="valida-abc123",
            name="Valida",
            type="paper",  # type: ignore[arg-type]
            version="1.21.4",
            memory_mb=1024,
            port=25565,
            rcon_port=25575,
            rcon_password="contrasena-larga",
            image="docker.io/itzg/minecraft-server",
        )
        assert spec.validated().type is ServerType.PAPER

    def test_validated_rechaza_puerto_malo(self) -> None:
        spec = make_spec()
        spec.port = 99999
        with pytest.raises(ValidationError):
            spec.validated()

    def test_new_server_id(self) -> None:
        primero = new_server_id("Mi Servidor")
        segundo = new_server_id("Mi Servidor")
        assert primero.startswith("mi-servidor-")
        assert primero != segundo


class TestFormatBytes:
    @pytest.mark.parametrize(
        "valor, esperado",
        [
            (0, "0 B"),
            (512, "512 B"),
            (1024, "1.0 KiB"),
            (1024 * 1024, "1.0 MiB"),
            (1536 * 1024, "1.5 MiB"),
            (2 * 1024**3, "2.0 GiB"),
        ],
    )
    def test_formato(self, valor: int, esperado: str) -> None:
        assert format_bytes(valor) == esperado

    def test_negativo(self) -> None:
        assert format_bytes(-10) == "0 B"


class TestServerStats:
    def test_porcentaje_de_memoria(self) -> None:
        stats = ServerStats(memory_bytes=512 * 1024**2, memory_limit_bytes=1024 * 1024**2, available=True)
        assert stats.memory_percent == pytest.approx(50.0)

    def test_porcentaje_sin_limite(self) -> None:
        assert ServerStats(memory_bytes=1024).memory_percent == 0.0

    def test_etiqueta_de_memoria(self) -> None:
        stats = ServerStats(memory_bytes=1024**3, memory_limit_bytes=2 * 1024**3, available=True)
        assert stats.memory_label() == "1.0 GiB / 2.0 GiB"

    def test_etiqueta_con_limite_externo(self) -> None:
        stats = ServerStats(memory_bytes=512 * 1024**2, available=True)
        assert stats.memory_label(limit_mb=2048) == "512.0 MiB / 2.0 GiB"

    def test_porcentaje_no_supera_cien(self) -> None:
        stats = ServerStats(memory_bytes=5 * 1024**3, memory_limit_bytes=1024**3)
        assert stats.memory_percent == 100.0
