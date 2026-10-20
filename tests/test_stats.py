"""Pruebas del analisis de estadisticas del motor de contenedores."""

from __future__ import annotations

import pytest

from serviscraft.core.manager import (
    host_cpu_count,
    jvm_overhead_mb,
    normalize_cpu_percent,
    parse_percent,
    parse_size,
    parse_stats,
)
from serviscraft.core.models import ServerStats, ServerType


class TestParseSize:
    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            (None, 0),
            ("", 0),
            ("0", 0),
            (1024, 1024),
            ("512B", 512),
            ("1KiB", 1024),
            ("1.5MiB", int(1.5 * 1024**2)),
            ("2GiB", 2 * 1024**3),
            ("1MB", 1000**2),
            ("1G", 1024**3),
            ("  3.5 MiB  ", int(3.5 * 1024**2)),
            ("basura", 0),
        ],
    )
    def test_parsea(self, entrada, esperado: int) -> None:
        assert parse_size(entrada) == esperado


class TestParsePercent:
    @pytest.mark.parametrize(
        "entrada, esperado",
        [(None, 0.0), ("", 0.0), ("12.5%", 12.5), ("--", 0.0), ("0.00%", 0.0), ("250%", 250.0)],
    )
    def test_parsea(self, entrada, esperado: float) -> None:
        assert parse_percent(entrada) == pytest.approx(esperado)


class TestParseStats:
    def test_sin_datos(self) -> None:
        stats = parse_stats(None)
        assert not stats.available
        assert stats.cpu_percent == 0.0

    def test_diccionario_vacio(self) -> None:
        assert not parse_stats({}).available

    def test_formato_de_podman_cli(self) -> None:
        """Lo que devuelve ``podman stats --format json``."""
        stats = parse_stats(
            {
                "cpu": "12.50%",
                "mem_usage": "512MiB / 1GiB",
                "net_io": "1.5kB / 2.5kB",
                "block_io": "4kB / 8kB",
                "pids": "42",
            }
        )
        assert stats.available
        assert stats.cpu_percent == pytest.approx(12.5)
        assert stats.memory_bytes == 512 * 1024**2
        assert stats.memory_limit_bytes == 1024**3
        assert stats.pids == 42
        assert stats.network_input_bytes == 1500
        assert stats.network_output_bytes == 2500
        assert stats.memory_percent == pytest.approx(50.0)

    def test_formato_de_podman_5(self) -> None:
        """Podman 5 llama al campo ``cpu_percent`` (y usa ``avg_cpu``)."""
        stats = parse_stats(
            {
                "id": "bf1265c16650",
                "name": "servidor",
                "cpu_time": "7.907ms",
                "cpu_percent": "12.50%",
                "avg_cpu": "12.50%",
                "mem_usage": "512MiB / 2GiB",
                "mem_percent": "25.00%",
                "net_io": "1kB / 2kB",
                "block_io": "0B / 0B",
                "pids": "42",
            }
        )
        assert stats.cpu_percent == pytest.approx(12.5)
        assert stats.pids == 42
        assert stats.memory_bytes == 512 * 1024**2
        assert stats.memory_limit_bytes == 2 * 1024**3

    def test_formato_de_podman_api(self) -> None:
        """Lo que devuelve ``podman stats --format json`` con el nombre largo."""
        stats = parse_stats(
            {
                "CPUPerc": "0.00%",
                "MemUsage": "0B / 0B",
                "MemUsageBytes": 0,
                "MemLimitBytes": 0,
                "PIDS": 0,
            }
        )
        assert stats.available
        assert stats.cpu_percent == 0.0
        assert stats.pids == 0

    def test_limite_de_reserva(self) -> None:
        stats = parse_stats({"cpu": "1%", "mem_usage_bytes": 100, "mem_limit_bytes": 0}, fallback_limit_mb=1024)
        assert stats.memory_limit_bytes == 1024 * 1024 * 1024

    def test_el_limite_real_manda_sobre_la_reserva(self) -> None:
        stats = parse_stats(
            {"cpu": "1%", "mem_usage_bytes": 100, "mem_limit_bytes": 512 * 1024**2},
            fallback_limit_mb=4096,
        )
        assert stats.memory_limit_bytes == 512 * 1024**2

    def test_datos_parciales_no_revientan(self) -> None:
        stats = parse_stats({"cpu": "%%%", "mem_usage": "sin sentido"})
        assert stats.available
        assert stats.cpu_percent == 0.0
        assert stats.memory_bytes == 0

    def test_entradas_desconocidas(self) -> None:
        stats = parse_stats({"otra_cosa": 5, "cpu": "3.5%", "pids": 7})
        assert stats.cpu_percent == pytest.approx(3.5)
        assert stats.pids == 7


class TestJvmOverhead:
    def test_vanilla_y_paper(self) -> None:
        assert jvm_overhead_mb(ServerType.VANILLA) == 768
        assert jvm_overhead_mb(ServerType.PAPER) == 768

    def test_los_mods_necesitan_mas(self) -> None:
        assert jvm_overhead_mb(ServerType.FABRIC) > jvm_overhead_mb(ServerType.PAPER)
        assert jvm_overhead_mb(ServerType.FORGE) > jvm_overhead_mb(ServerType.FABRIC)


class TestCpuDelEquipo:
    """Podman cuenta el 100 % por nucleo: la interfaz usa el total del equipo."""

    def test_host_cpu_count_siempre_positivo(self) -> None:
        assert host_cpu_count() >= 1

    @pytest.mark.parametrize(
        "bruto, nucleos, esperado",
        [
            (200.0, 8, 25.0),
            (100.0, 1, 100.0),
            (50.0, 4, 12.5),
            (200.0, 1, 100.0),  # nunca pasa del 100 %
            (-5.0, 4, 0.0),
            (12.0, 0, 12.0),  # un equipo sin datos se trata como un nucleo
        ],
    )
    def test_normaliza(self, bruto: float, nucleos: int, esperado: float) -> None:
        assert normalize_cpu_percent(bruto, nucleos) == pytest.approx(esperado)

    def test_nucleos_ocupados(self) -> None:
        stats = ServerStats(cpu_percent=25.0, cpu_cores=8, available=True)
        assert stats.cpu_cores_used == pytest.approx(2.0)

    def test_sin_nucleos_conocidos(self) -> None:
        assert ServerStats(cpu_percent=50.0).cpu_cores_used == pytest.approx(0.5)


class TestStatsDelGestor:
    """``ServerManager.stats`` reparte la CPU de Podman entre los nucleos."""

    def test_200_por_ciento_en_ocho_nucleos_es_25(
        self, store, config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from serviscraft.core.manager import ServerManager
        from serviscraft.core.models import ServerState, ServerType

        from .conftest import make_spec

        spec = make_spec(type=ServerType.PAPER)
        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)
        monkeypatch.setattr(
            manager.client, "container_state", lambda name: ServerState.RUNNING
        )
        monkeypatch.setattr(
            manager.client,
            "stats",
            lambda name: {
                "cpu_percent": "200%",
                "mem_usage_bytes": 512 * 1024**2,
                "mem_limit_bytes": 0,
                "pids": 30,
            },
        )
        monkeypatch.setattr(
            "serviscraft.core.manager.host_cpu_count", lambda: 8
        )

        stats = manager.stats(spec.id)

        assert stats.available
        assert stats.cpu_percent == pytest.approx(25.0)
        assert stats.cpu_cores == 8
        assert stats.cpu_cores_used == pytest.approx(2.0)
