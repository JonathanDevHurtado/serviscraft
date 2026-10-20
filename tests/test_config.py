"""Pruebas de la configuracion global, las rutas y el registro."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from serviscraft.core import paths
from serviscraft.core.appconfig import AppConfig


class TestRutas:
    def test_usa_serviscraft_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVISCRAFT_HOME", str(tmp_path / "datos"))
        assert paths.data_root() == (tmp_path / "datos").resolve()
        assert paths.servers_dir() == (tmp_path / "datos" / "servers")
        assert paths.logs_dir() == (tmp_path / "datos" / "logs")

    def test_rutas_de_un_servidor(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVISCRAFT_HOME", str(tmp_path))
        assert paths.server_dir("abc-123") == tmp_path / "servers" / "abc-123"
        assert paths.server_data_dir("abc-123") == tmp_path / "servers" / "abc-123" / "data"
        assert paths.server_backups_dir("abc-123") == tmp_path / "servers" / "abc-123" / "backups"
        assert paths.server_meta_file("abc-123").name == "meta.json"

    @pytest.mark.parametrize("malo", ["../fuera", "/etc", "..", "con/barra", ""])
    def test_rechaza_identificadores_de_ruta(self, malo: str) -> None:
        with pytest.raises(ValueError):
            paths.server_dir(malo)

    def test_crea_las_carpetas_base(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVISCRAFT_HOME", str(tmp_path / "nuevo"))
        monkeypatch.setenv("SERVISCRAFT_CONFIG_HOME", str(tmp_path / "conf"))
        paths.ensure_base_dirs()
        for carpeta in (
            paths.data_root(),
            paths.servers_dir(),
            paths.logs_dir(),
            paths.config_dir(),
        ):
            assert carpeta.is_dir()

    def test_recursos_empaquetados(self) -> None:
        icono = paths.bundled_resource("icons", "serviscraft.svg")
        assert icono.is_file()
        assert "<svg" in icono.read_text(encoding="utf-8")


class TestAppConfig:
    def test_valores_por_defecto(self) -> None:
        config = AppConfig.load()
        assert config.engine_binary == "podman"
        assert config.image == paths.DEFAULT_IMAGE
        assert config.default_memory_mb >= 512
        assert config.stats_interval_ms >= 1000

    def test_guardar_y_leer(self, tmp_path: Path) -> None:
        destino = tmp_path / "config.json"
        config = AppConfig(default_memory_mb=4096)
        config.save(destino)
        assert destino.is_file()
        assert AppConfig.load(destino).default_memory_mb == 4096

    def test_fichero_corrupto(self, tmp_path: Path) -> None:
        destino = tmp_path / "config.json"
        destino.write_text("{ esto no es json", encoding="utf-8")
        assert AppConfig.load(destino).default_memory_mb == paths.DEFAULT_MEMORY_MB

    def test_claves_desconocidas_se_ignoran(self, tmp_path: Path) -> None:
        destino = tmp_path / "config.json"
        destino.write_text(json.dumps({"default_memory_mb": 3072, "inventada": 1}), encoding="utf-8")
        config = AppConfig.load(destino)
        assert config.default_memory_mb == 3072
        assert not hasattr(config, "inventada")

    def test_validated_corrige_valores_absurdos(self) -> None:
        config = AppConfig(default_memory_mb=1, stats_interval_ms=1).validated()
        assert config.default_memory_mb >= 512
        assert config.stats_interval_ms >= 1000

    def test_validated_no_toca_lo_correcto(self) -> None:
        config = AppConfig(default_memory_mb=2048, stats_interval_ms=3000).validated()
        assert config.default_memory_mb == 2048
        assert config.stats_interval_ms == 3000

    def test_imagen_invalida_vuelve_al_valor_por_defecto(self) -> None:
        config = AppConfig(image="imagen con espacios").validated()
        assert config.image == paths.DEFAULT_IMAGE

    def test_por_defecto_no_se_avisa_de_contenedores_huerfanos(self) -> None:
        """Los servidores nunca arrancan solos: solo se avisa de los que ya corrian."""
        assert AppConfig().warn_orphan_containers is True


class TestRegistro:
    @staticmethod
    def _reconfigurar(debug: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Vuelve a configurar el registro en una carpeta nueva.

        ``setup_logging`` solo se aplica una vez por proceso (es intencionado),
        asi que en las pruebas se reinicia explicitamente.
        """
        from serviscraft.core import logging_setup

        monkeypatch.setenv("SERVISCRAFT_HOME", str(tmp_path))
        logger = logging.getLogger(logging_setup.LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logging_setup._configured = False
        return logging_setup.setup_logging(debug=debug, console=False)

    def test_escribe_en_el_fichero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger = self._reconfigurar(False, tmp_path, monkeypatch)
        logger.info("mensaje de prueba del registro")
        for handler in logger.handlers:
            handler.flush()
        contenido = paths.log_file().read_text(encoding="utf-8", errors="replace")
        assert "mensaje de prueba del registro" in contenido
        assert paths.log_file().is_file()

    def test_nivel_normal_oculta_el_detalle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger = self._reconfigurar(False, tmp_path, monkeypatch)
        assert logger.level == logging.INFO
        logger.debug("esto no debe guardarse")
        for handler in logger.handlers:
            handler.flush()
        assert "esto no debe guardarse" not in paths.log_file().read_text(
            encoding="utf-8", errors="replace"
        )

    def test_nivel_detallado(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        logger = self._reconfigurar(True, tmp_path, monkeypatch)
        assert logger.level == logging.DEBUG
        logger.debug("detalle visible")
        for handler in logger.handlers:
            handler.flush()
        assert "detalle visible" in paths.log_file().read_text(encoding="utf-8", errors="replace")

    def test_solo_se_configura_una_vez(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from serviscraft.core import logging_setup

        logger = self._reconfigurar(False, tmp_path, monkeypatch)
        manejadores = list(logger.handlers)
        assert logging_setup.setup_logging(debug=True, console=False) is logger
        # La segunda llamada no cambia el nivel ni duplica los manejadores.
        assert logger.handlers == manejadores
        assert logger.level == logging.INFO
