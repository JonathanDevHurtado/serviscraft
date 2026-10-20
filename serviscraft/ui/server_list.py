"""Barra lateral con la lista de servidores."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.models import ServerState, ServerView
from .common import STATE_COLORS, ElidedLabel, FlowRow, StatusBadge, make_button
from .mc_icons import PlatformBadge
from .server_preview import icon_pixmap


#: Lado del icono propio del servidor en la tarjeta de la barra lateral.
CARD_ICON = 22


def state_dot(state: ServerState, size: int = 10) -> QPixmap:
    """Circulo de color que representa el estado del servidor."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(STATE_COLORS.get(state, "#9ca3af")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size - 1, size - 1)
    painter.end()
    return pixmap


class ServerCard(QWidget):
    """Tarjeta de un servidor dentro de la lista."""

    def __init__(self, view: ServerView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ServerCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(1)

        top = QHBoxLayout()
        top.setSpacing(6)
        # Icono propio del servidor (el mismo que se ve en Minecraft).
        self.icon = QLabel()
        self.icon.setObjectName("ServerCardIcon")
        self.icon.setFixedSize(CARD_ICON, CARD_ICON)
        self.icon.setVisible(False)
        top.addWidget(self.icon)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        top.addWidget(self.dot)
        self.title = ElidedLabel(view.spec.name)
        self.title.setObjectName("ServerCardTitle")
        top.addWidget(self.title, 1)
        self.badge = StatusBadge()
        top.addWidget(self.badge)
        layout.addLayout(top)

        # Los iconos van en la segunda linea (que se recorta sola): asi la
        # tarjeta sigue cabiendo en una barra lateral estrecha y el nombre y el
        # estado nunca se quedan sin sitio.
        subtitle_row = QHBoxLayout()
        subtitle_row.setContentsMargins(0, 0, 0, 0)
        subtitle_row.setSpacing(5)
        self.platform = PlatformBadge(13, with_text=False)
        subtitle_row.addWidget(self.platform)
        self.subtitle = ElidedLabel()
        self.subtitle.setObjectName("ServerCardSubtitle")
        subtitle_row.addWidget(self.subtitle, 1)
        layout.addLayout(subtitle_row)

        self.update_view(view)

    def update_view(self, view: ServerView) -> None:
        state = view.state
        self.dot.setPixmap(state_dot(state))
        icono = icon_pixmap(view.icon, CARD_ICON)
        self.icon.setPixmap(icono)
        self.icon.setVisible(not icono.isNull())
        self.title.setText(view.spec.name)
        self.platform.set_spec(view.spec)
        self.badge.set_state(state)
        scope = "red" if view.spec.lan else "local"
        self.subtitle.setText(
            f"{view.spec.type.label} {view.spec.version} · puerto {view.spec.port} · "
            f"{view.spec.memory_label} · {scope}"
        )


class ServerSidebar(QWidget):
    """Lista filtrable de servidores con acceso rapido a las acciones."""

    server_selected = Signal(str)
    create_requested = Signal()
    import_requested = Signal()
    stop_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ServerSidebar")
        # Minimo estrecho a proposito: el gestor de ventanas con mosaico puede
        # dejar poco ancho y es preferible una lista estrecha a que se recorte.
        self.setMinimumWidth(190)
        self._cards: dict[str, ServerCard] = {}
        self._items: dict[str, QListWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel("Servidores")
        header.setObjectName("ServerSidebarHeader")
        layout.addWidget(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar servidor...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setObjectName("ServerList")
        self.list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.list.setUniformItemSizes(False)
        self.list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list, 1)

        # Los dos botones del pie se envuelven cuando la barra lateral es estrecha.
        self.footer_actions = FlowRow(spacing=6)
        self.footer_actions.setContentsMargins(6, 0, 6, 6)
        self.import_button = make_button(
            "Importar servidor",
            icon_names=("document-import", "document-open", "list-add"),
            accent=True,
            tooltip="Traer un servidor que ya tenias: su carpeta o el .zip de Aternos",
        )
        self.import_button.clicked.connect(self.import_requested.emit)
        self.footer_actions.add(self.import_button)
        self.stop_button = make_button(
            "Detener todos",
            icon_names=("media-playback-stop", "process-stop"),
            tooltip="Apagar todos los servidores que esten en marcha ahora mismo",
        )
        self.stop_button.clicked.connect(self.stop_all_requested.emit)
        self.footer_actions.add(self.stop_button)
        layout.addWidget(self.footer_actions)

        self.empty = QLabel(
            "Todavia no hay servidores.\n"
            "Pulsa «Importar servidor» para traer uno que ya tengas.\n"
            "Para empezar de cero: Archivo → Nuevo servidor."
        )
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

    # ================================================================ listado
    def set_servers(self, views: list[ServerView], *, selected: str | None = None) -> None:
        """Reconstruye la lista conservando la seleccion."""
        current = selected or self.current_id()
        self.list.blockSignals(True)
        self.list.clear()
        self._cards.clear()
        self._items.clear()

        for view in views:
            item = QListWidgetItem()
            card = ServerCard(view)
            # Ancho 0: el item se ajusta al ancho visible de la lista. Si se usa el
            # sizeHint de la tarjeta (que crece con el nombre del servidor), la
            # lista saca una barra horizontal y recorta la insignia de estado.
            item.setSizeHint(QSize(0, card.sizeHint().height() + 10))
            self.list.addItem(item)
            self.list.setItemWidget(item, card)
            self._cards[view.spec.id] = card
            self._items[view.spec.id] = item

        self.list.blockSignals(False)
        self.empty.setVisible(not views)
        self.list.setVisible(bool(views))
        self._apply_filter(self.search.text())
        if current and current in self._items:
            self.list.setCurrentItem(self._items[current])
        elif views:
            self.list.setCurrentRow(0)

    def update_states(self, views: list[ServerView]) -> None:
        """Actualiza el estado de las tarjetas ya mostradas."""
        for view in views:
            card = self._cards.get(view.spec.id)
            if card is not None:
                card.update_view(view)

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        for server_id, stored in self._items.items():
            if stored is item:
                return server_id
        return None

    def select(self, server_id: str) -> None:
        item = self._items.get(server_id)
        if item is not None:
            self.list.setCurrentItem(item)

    def _on_current_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        for server_id, stored in self._items.items():
            if stored is current:
                self.server_selected.emit(server_id)
                return

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        visible = 0
        for view_id, item in self._items.items():
            titulo = self._cards[view_id].title
            # El titulo es una ElidedLabel: ``text()`` devuelve el texto ya
            # recortado, asi que la busqueda debe usar el nombre completo.
            nombre = titulo.full_text() if isinstance(titulo, ElidedLabel) else titulo.text()
            hidden = bool(needle) and needle not in view_id and needle not in nombre.lower()
            item.setHidden(hidden)
            if not hidden:
                visible += 1
        if needle:
            self.empty.setVisible(visible == 0)
            self.empty.setText("Ningun servidor coincide con la busqueda.")
