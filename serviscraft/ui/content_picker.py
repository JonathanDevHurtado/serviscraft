"""Selector de mods o plugins para el asistente de creacion.

Reutiliza el catalogo de Modrinth en modo seleccion: no descarga nada, solo
devuelve los proyectos y versiones elegidos. El asistente los instala cuando el
servidor ya existe.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.models import ServerType
from ..core.modrinth import ContentSelection
from .catalog_dialog import CatalogDialog
from .common import PaginaDesplazable, make_button
from .tasks import TaskRunner


class ContentPickerDialog(QDialog):
    """Busca en Modrinth y devuelve una lista de proyectos con su version."""

    def __init__(
        self,
        runner: TaskRunner,
        *,
        mode: str,
        server_type: ServerType,
        version: str,
        loaders: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = "plugins" if mode == "plugins" else "mods"
        self.selected: list[ContentSelection] = []
        self._kind = "plugins" if self.mode == "plugins" else "mods"
        self.setWindowTitle(f"Anadir {self._kind}")
        self.setMinimumSize(700, 620)
        self.resize(1080, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        self.catalog = CatalogDialog(
            None,
            runner,
            None,
            self.mode,
            self,
            embedded=True,
            selection=True,
            server_type=server_type,
            version=version,
            loaders=loaders,
        )
        self.catalog.content_selected.connect(self._add)
        # El catalogo crece al enseñar todas las versiones. Sin esta pagina
        # desplazable, el selector lo comprime por debajo de su minimo y la
        # tabla de versiones se dibuja encima de la lista de proyectos.
        self.catalog_page = PaginaDesplazable(self.catalog)
        self.catalog_page.setObjectName("ContentPickerCatalog")
        self.catalog_page.setMinimumHeight(300)
        layout.addWidget(self.catalog_page, 1)

        seleccion = QHBoxLayout()
        seleccion.setSpacing(8)
        self.selected_label = QLabel("Ningun contenido anadido todavia.")
        self.selected_label.setObjectName("Hint")
        seleccion.addWidget(self.selected_label, 1)
        self.remove_button = make_button(
            "Quitar",
            icon_names=("edit-delete", "user-trash"),
            danger=True,
            tooltip="Quitar de la lista el contenido seleccionado",
        )
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._remove)
        seleccion.addWidget(self.remove_button)
        layout.addLayout(seleccion)

        self.selected_list = QListWidget()
        self.selected_list.setObjectName("ContentSelectedList")
        self.selected_list.setMaximumHeight(104)
        self.selected_list.itemSelectionChanged.connect(
            lambda: self.remove_button.setEnabled(self.selected_list.currentRow() >= 0)
        )
        layout.addWidget(self.selected_list)

        buttons = QDialogButtonBox()
        self.accept_button = buttons.addButton(
            "Listo (0)", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.accept_button.setProperty("accent", "true")
        self.accept_button.setEnabled(False)
        self.accept_button.clicked.connect(self.accept)
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ================================================================ seleccion
    def _add(self, seleccion: ContentSelection) -> None:
        if not isinstance(seleccion, ContentSelection):
            return
        # Un proyecto solo puede aportar una version: si se vuelve a elegir,
        # se actualiza en vez de duplicarlo.
        for indice, actual in enumerate(self.selected):
            if actual.project.id == seleccion.project.id:
                self.selected[indice] = seleccion
                break
        else:
            self.selected.append(seleccion)
        self._refresh()

    def _remove(self) -> None:
        row = self.selected_list.currentRow()
        if 0 <= row < len(self.selected):
            del self.selected[row]
            self._refresh()

    def _refresh(self) -> None:
        self.selected_list.clear()
        for seleccion in self.selected:
            item = QListWidgetItem(
                f"{seleccion.project.title} · {seleccion.release.version_number} "
                f"(Minecraft {', '.join(seleccion.release.game_versions[:2]) or '?'})"
            )
            item.setData(Qt.ItemDataRole.UserRole, seleccion)
            item.setToolTip(
                f"{seleccion.project.title}\n"
                f"Version: {seleccion.release.version_number}\n"
                f"Fichero: {seleccion.release.filename}\n"
                f"Minecraft: {', '.join(seleccion.release.game_versions) or 'sin datos'}\n"
                f"Cargador: {', '.join(seleccion.release.loaders) or 'sin datos'}"
            )
            self.selected_list.addItem(item)
        total = len(self.selected)
        if total:
            self.selected_label.setText(
                f"{total} {'plugin' if total == 1 and self.mode == 'plugins' else 'plugins' if self.mode == 'plugins' else 'mod' if total == 1 else 'mods'} "
                "en la lista. Pulsa «Listo» para anadirlos al servidor."
            )
        else:
            self.selected_label.setText("Ningun contenido anadido todavia.")
        self.accept_button.setText(f"Listo ({total})")
        self.accept_button.setEnabled(total > 0)
        self.remove_button.setEnabled(self.selected_list.currentRow() >= 0)

    def done(self, result: int) -> None:  # noqa: N802 - API de Qt
        # El catalogo comparte el TaskRunner del asistente: si se cierra con una
        # busqueda en marcha, hay que cancelarla para que no avise a la nada.
        # ``done`` cubre «Listo», «Cancelar» y el cierre de la ventana.
        self.catalog.shutdown()
        super().done(result)

    # ================================================================= API
    def values(self) -> list[ContentSelection]:
        return list(self.selected)
