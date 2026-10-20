"""Serviscraft - Gestor grafico de servidores de Minecraft sobre Podman rootless."""

from __future__ import annotations

from .core import paths

APP_ID = paths.APP_ID
APP_NAME = paths.APP_DISPLAY_NAME
__version__ = paths.APP_VERSION

__all__ = ["APP_ID", "APP_NAME", "__version__"]
