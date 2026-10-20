"""Configuracion global de la aplicacion (no de los servidores)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from . import paths
from .logging_setup import get_logger
from .validation import validate_image, validate_java_tag, validate_memory_mb

logger = get_logger("config")


@dataclass
class AppConfig:
    """Preferencias de Serviscraft. Todo tiene valores por defecto sensatos."""

    engine_binary: str = paths.DEFAULT_ENGINE
    image: str = paths.DEFAULT_IMAGE
    default_java_tag: str = paths.DEFAULT_JAVA_TAG
    default_memory_mb: int = paths.DEFAULT_MEMORY_MB
    default_port: int = paths.DEFAULT_PORT
    #: Segundos que se espera al apagar un servidor antes de forzar la parada.
    stop_timeout_s: int = 90
    #: Frecuencia de actualizacion de las estadisticas (milisegundos).
    stats_interval_ms: int = 3000
    #: Numero de lineas de registro que se recuperan al abrir la consola.
    console_tail_lines: int = 300
    #: Pedir confirmacion escrita en acciones destructivas (borrar servidor/copias).
    confirm_destructive: bool = True
    #: Comprobar si quedaron servidores en ejecucion al arrancar la aplicacion.
    warn_orphan_containers: bool = True
    #: Copia de seguridad automatica antes de restaurar otra copia.
    safety_backup_before_restore: bool = True
    #: Crear una copia de seguridad cada vez que un servidor se detiene.
    backup_on_stop: bool = True
    #: Copia de seguridad periodica de los servidores en ejecucion, en minutos
    #: (0 desactiva esta programacion).
    scheduled_backup_minutes: int = 0
    #: Cuantas copias automaticas se conservan por servidor (0 = todas).
    automatic_backup_keep: int = 8
    #: Mapear el usuario del host dentro del contenedor (recomendado en rootless).
    #: Desactivarlo solo si el sistema de ficheros no lo admite.
    userns_keep_id: bool = True
    #: Nivel de registro detallado.
    debug_logging: bool = False

    # ------------------------------------------------------------------ carga
    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        target = path or paths.config_file()
        if not target.is_file():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("No se pudo leer la configuracion (%s); se usan los valores por defecto", exc)
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in raw.items() if k in known}
        try:
            return cls(**data)
        except TypeError as exc:  # pragma: no cover - datos corruptos
            logger.warning("Configuracion invalida (%s); se usan los valores por defecto", exc)
            return cls()

    def save(self, path: Path | None = None) -> None:
        target = path or paths.config_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)
        logger.debug("Configuracion guardada en %s", target)

    # ------------------------------------------------------------- ajustes
    def validated(self) -> "AppConfig":
        """Devuelve una copia con los valores normalizados y dentro de rango."""
        try:
            memory = validate_memory_mb(self.default_memory_mb)
        except Exception:
            memory = paths.DEFAULT_MEMORY_MB
        try:
            image = validate_image(self.image)
        except Exception:
            image = paths.DEFAULT_IMAGE
        try:
            java_tag = validate_java_tag(self.default_java_tag)
        except Exception:
            java_tag = paths.DEFAULT_JAVA_TAG
        return replace(
            self,
            image=image,
            default_java_tag=java_tag,
            default_memory_mb=memory,
            default_port=min(max(int(self.default_port), paths.MIN_PORT), paths.MAX_PORT),
            stop_timeout_s=min(max(int(self.stop_timeout_s), 10), 600),
            stats_interval_ms=min(max(int(self.stats_interval_ms), 1000), 60000),
            console_tail_lines=min(max(int(self.console_tail_lines), 50), 5000),
            scheduled_backup_minutes=min(max(int(self.scheduled_backup_minutes), 0), 1440),
            automatic_backup_keep=min(max(int(self.automatic_backup_keep), 0), 200),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
