"""Pestana de plugins: catalogo de Modrinth integrado en la ventana.

Es la misma busqueda del catalogo (version de Minecraft, cargador, orden,
categorias y todas las versiones de cada proyecto), pero sin abrir un cuadro
aparte. La pestana solo se muestra en servidores que admiten plugins (Paper).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core.manager import ServerManager
from ..core.models import ServerSpec
from .catalog_dialog import CatalogDialog
from .mc_icons import icono_plugin
from .mc_widgets import CenteredEmpty, TexturedPage
from .tasks import TaskRunner


class PluginsPanel(TexturedPage):
    """Catalogo de plugins del servidor seleccionado."""

    #: Aviso para que la ventana refresque la lista de plugins instalados.
    changed = Signal()

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PluginsPanel")
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.catalog = CatalogDialog(
            manager,
            runner,
            None,
            "plugins",
            self,
            embedded=True,
        )
        self.catalog.hero.set_title("Plugins")
        self.catalog.content_installed.connect(self._on_installed)
        layout.addWidget(self.catalog, 1)

        self.empty = CenteredEmpty(
            "Este servidor no usa plugins",
            "Los plugins necesitan un servidor Paper. Los servidores Vanilla no "
            "admiten contenido y Fabric o Forge usan mods (pestana Mods).",
            pixmap=icono_plugin(64),
        )
        layout.addWidget(self.empty, 1)
        self.empty.setVisible(False)

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        self._spec = spec
        compatible = spec is not None and spec.supports_plugins
        self.catalog.setVisible(compatible)
        self.empty.setVisible(not compatible)
        if compatible:
            self.catalog.set_server(spec)
        else:
            self.catalog.set_server(None)
            if spec is None:
                self.empty.set_texts(
                    "Elige un servidor",
                    "Selecciona un servidor Paper en la lista para buscar plugins "
                    "en Modrinth e instalarlos con un clic.",
                )
                self.empty.title.setText("Elige un servidor")
                self.empty.icon.set_pixmap(icono_plugin(64))
            else:
                self.empty.set_texts(
                    "Este servidor no usa plugins",
                    f"{spec.name} es de tipo {spec.type.label}. Los plugins necesitan "
                    "Paper; en Fabric, Forge o un modpack el contenido esta en la "
                    "pestana Mods.",
                )

    def activate(self) -> None:
        """Carga la lista la primera vez que se abre la pestana."""
        if self._spec is not None and self._spec.supports_plugins:
            self.catalog.activate()

    def _on_installed(self, _filename: str) -> None:
        # La lista de plugins instalados de la pestana «Mods» se refresca sola
        # mediante la senal ``changed``.
        self.changed.emit()

    def shutdown(self) -> None:
        self.catalog.shutdown()
