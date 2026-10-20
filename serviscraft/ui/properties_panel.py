"""Editor de ``server.properties``.

Se presentan las propiedades mas habituales como formulario y se deja un editor
de texto para el resto. Las propiedades que gestiona la aplicacion (puerto,
RCON, IP) aparecen bloqueadas para no romper el contenedor.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from ..core.properties import KNOWN_PROPERTIES, ServerProperties
from .common import ElidedLabel, FlowRow, NumberBox, hint_label, make_button, polish_table_header
from .dialogs import confirm, show_error
from .tasks import TaskRunner

logger = get_logger("ui.properties")

#: Propiedades que se muestran en la pestana «Basico», en este orden.
BASIC_KEYS: tuple[str, ...] = (
    "motd",
    "max-players",
    "difficulty",
    "gamemode",
    "pvp",
    "hardcore",
    "online-mode",
    "white-list",
    "enforce-whitelist",
    "level-name",
    "level-seed",
    "view-distance",
    "simulation-distance",
    "spawn-protection",
    "allow-flight",
    "enable-command-block",
    "allow-nether",
    "spawn-monsters",
    "spawn-animals",
    "spawn-npcs",
    "generate-structures",
    "enable-status",
    "force-gamemode",
    "player-idle-timeout",
    "op-permission-level",
    "function-permission-level",
)

#: Grupos de la pestana «Basico».
BASIC_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Identidad del servidor", ("motd", "max-players", "difficulty", "gamemode", "enable-status")),
    ("Jugabilidad", ("pvp", "hardcore", "allow-flight", "enable-command-block", "force-gamemode", "player-idle-timeout")),
    ("Acceso", ("online-mode", "white-list", "enforce-whitelist", "op-permission-level", "function-permission-level")),
    (
        "Mundo",
        (
            "level-name",
            "level-seed",
            "view-distance",
            "simulation-distance",
            "spawn-protection",
            "allow-nether",
            "spawn-monsters",
            "spawn-animals",
            "spawn-npcs",
            "generate-structures",
        ),
    ),
)


class PropertiesPanel(QWidget):
    """Formulario y editor de texto para la configuracion del servidor."""

    saved = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._widgets: dict[str, tuple[str, QWidget]] = {}
        self._snapshot: dict[str, str] = {}
        self._raw_loaded: str = ""
        self._loading = True
        self._props: ServerProperties = ServerProperties(path=Path("server.properties"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        # Titulo recortable: en una ventana estrecha debe encogerse el, no los
        # botones que tiene al lado.
        self.title = ElidedLabel("Propiedades del servidor")
        self.title.setObjectName("SectionTitle")
        toolbar.addWidget(self.title)
        toolbar.addStretch(1)

        # Botones en una fila que se envuelve al estrecharse la ventana.
        self.properties_actions = FlowRow()
        self.reload_button = make_button("Recargar", icon_names=("view-refresh",), tooltip="Descartar los cambios y volver a leer el fichero")
        self.reload_button.clicked.connect(lambda: self.load(self._spec))
        self.properties_actions.add(self.reload_button)

        self.save_button = make_button("Guardar cambios", icon_names=("document-save",), accent=True)
        self.save_button.clicked.connect(self._save)
        self.properties_actions.add(self.save_button)
        toolbar.addWidget(self.properties_actions)
        layout.addLayout(toolbar)

        layout.addWidget(
            hint_label(
                "Los cambios se aplican al fichero server.properties del servidor. "
                "Minecraft los lee al arrancar: reinicia el servidor para que surtan efecto."
            )
        )

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), "Basico")
        self.tabs.addTab(self._build_advanced_tab(), "Todas las propiedades")
        self.tabs.addTab(self._build_text_tab(), "Editor de texto")
        layout.addWidget(self.tabs, 1)

        self.empty = QLabel("Selecciona un servidor para editar sus propiedades.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None)

    # ================================================================ construccion
    def _build_basic_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(12)

        for group_title, keys in BASIC_GROUPS:
            box = QGroupBox(group_title)
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            for key in keys:
                meta = KNOWN_PROPERTIES.get(key)
                if meta is None:
                    continue
                widget = self._build_field(meta.kind, meta.choices)
                widget.setToolTip(meta.description or meta.label)
                label = QLabel(meta.label)
                label.setToolTip(f"{key}\n{meta.description}")
                if meta.managed:
                    widget.setEnabled(False)
                else:
                    self._connect_field(key, meta.kind, widget)
                self._widgets[key] = (meta.kind, widget)
                form.addRow(label, widget)
            outer.addWidget(box)

        advanced_hint = hint_label(
            "Para configuraciones que no aparecen aqui, usa la pestana "
            "«Todas las propiedades» o el «Editor de texto»."
        )
        outer.addWidget(advanced_hint)
        outer.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _build_advanced_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(
            hint_label(
                "Todas las claves del fichero. Las propiedades gestionadas por Serviscraft "
                "aparecen bloqueadas (puerto, RCON e IP)."
            )
        )
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Propiedad", "Valor", "Gestionada"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        polish_table_header(self.table)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        add_button = make_button("Anadir propiedad", icon_names=("list-add",))
        add_button.clicked.connect(self._add_row)
        buttons.addWidget(add_button)
        remove_button = make_button("Quitar seleccionada", icon_names=("list-remove",))
        remove_button.clicked.connect(self._remove_selected)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _build_text_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.addWidget(
            hint_label(
                "Editor directo del fichero. Si escribes una clave que gestiona Serviscraft, "
                "se corregira automaticamente al guardar."
            )
        )
        self.text_editor = QPlainTextEdit()
        self.text_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text_editor, 1)
        return page

    @staticmethod
    def _build_field(kind: str, choices: tuple[str, ...]) -> QWidget:
        if kind == "bool":
            return QCheckBox()
        if kind == "int":
            spin = NumberBox()
            spin.setRange(-1, 100_000_000)
            return spin
        if kind == "enum":
            combo = QComboBox()
            combo.addItems(list(choices))
            return combo
        edit = QLineEdit()
        return edit

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None) -> None:
        # Solo se relee el fichero al cambiar de servidor: si se hiciera en cada
        # refresco periodico se perderian los cambios que el usuario este
        # escribiendo en el formulario.
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        self._spec = spec
        has_server = spec is not None
        self.tabs.setVisible(has_server)
        self.empty.setVisible(not has_server)
        self.save_button.setEnabled(has_server)
        self.reload_button.setEnabled(has_server)
        if has_server:
            self.title.setText(f"Propiedades de «{spec.name}»")
            if cambio:
                self.load(spec)

    def load(self, spec: ServerSpec | None) -> None:
        """Lee el fichero del disco y rellena el formulario."""
        if spec is None:
            return
        try:
            props = self.manager.properties(spec.id)
        except ServiscraftError as exc:
            show_error(self, "No se pudo leer la configuracion", str(exc))
            return
        self._props = props
        self._snapshot = props.as_dict()
        self._raw_loaded = props.to_text()
        self._loading = True
        self._fill_table(props)
        self._fill_basic(props)
        self.text_editor.setPlainText(self._raw_loaded)
        self._loading = False
        self.raw_editor_shown()

    def raw_editor_shown(self) -> None:
        """Hook para quien quiera saber que se recargo el texto."""

    def current_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, (kind, widget) in self._widgets.items():
            if kind == "bool":
                values[key] = "true" if widget.isChecked() else "false"  # type: ignore[attr-defined]
            elif kind == "int":
                values[key] = str(widget.value())  # type: ignore[attr-defined]
            elif kind == "enum":
                values[key] = widget.currentText()  # type: ignore[attr-defined]
            else:
                values[key] = widget.text()  # type: ignore[attr-defined]
        return values

    # ================================================================= relleno
    def _connect_field(self, key: str, kind: str, widget: QWidget) -> None:
        """Escritura directa: el formulario y la tabla comparten un unico modelo."""
        if kind == "bool":
            widget.toggled.connect(lambda _checked, k=key: self._sync_field(k))  # type: ignore[attr-defined]
        elif kind == "int":
            widget.valueChanged.connect(lambda _value, k=key: self._sync_field(k))  # type: ignore[attr-defined]
        elif kind == "enum":
            widget.currentTextChanged.connect(lambda _text, k=key: self._sync_field(k))  # type: ignore[attr-defined]
        else:
            widget.textChanged.connect(lambda _text, k=key: self._sync_field(k))  # type: ignore[attr-defined]

    def _field_value(self, key: str) -> str:
        kind, widget = self._widgets[key]
        if kind == "bool":
            return "true" if widget.isChecked() else "false"  # type: ignore[attr-defined]
        if kind == "int":
            return str(widget.value())  # type: ignore[attr-defined]
        if kind == "enum":
            return widget.currentText()  # type: ignore[attr-defined]
        return widget.text()  # type: ignore[attr-defined]

    def _sync_field(self, key: str) -> None:
        if key not in self._widgets or self._loading:
            return
        self._set_table_value(key, self._field_value(key))

    def _set_table_value(self, key: str, value: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text() == key:
                value_item = self.table.item(row, 1)
                if value_item is not None and value_item.text() != value:
                    value_item.setText(value)
                return
        self._append_row(key, value)

    def _fill_basic(self, props: ServerProperties) -> None:
        worlds = self._available_worlds()
        for key, (kind, widget) in self._widgets.items():
            meta = KNOWN_PROPERTIES.get(key)
            default = meta.default if meta else ""
            raw = props.get(key, default)
            if kind == "bool":
                widget.setChecked(str(raw).strip().lower() in {"true", "1", "yes", "on"})  # type: ignore[attr-defined]
            elif kind == "int":
                try:
                    widget.setValue(int(str(raw).strip()))  # type: ignore[attr-defined]
                except ValueError:
                    widget.setValue(int(default or 0))  # type: ignore[attr-defined]
            elif kind == "enum":
                if key == "level-name" and worlds:
                    widget.blockSignals(True)  # type: ignore[attr-defined]
                    widget.clear()  # type: ignore[attr-defined]
                    widget.addItems(worlds)  # type: ignore[attr-defined]
                    widget.blockSignals(False)  # type: ignore[attr-defined]
                    if raw not in worlds:
                        widget.addItem(raw)  # type: ignore[attr-defined]
                index = widget.findText(str(raw))  # type: ignore[attr-defined]
                if index >= 0:
                    widget.setCurrentIndex(index)  # type: ignore[attr-defined]
            else:
                widget.setText(str(raw))  # type: ignore[attr-defined]

    def _available_worlds(self) -> list[str]:
        if self._spec is None:
            return []
        try:
            worlds = [w.name for w in self.manager.files(self._spec.id).list_worlds()]
        except ServiscraftError:
            return []
        active = self._spec and self._props.get("level-name", "world")
        if active and active not in worlds:
            worlds.insert(0, active)
        return worlds

    def _fill_table(self, props: ServerProperties) -> None:
        values = props.as_dict()
        self.table.setRowCount(0)
        for key, value in values.items():
            self._append_row(key, value)
        for key in values:
            meta = KNOWN_PROPERTIES.get(key)
            managed = bool(meta and meta.managed)
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.text() == key:
                    self._set_row_managed(row, managed)

    def _append_row(self, key: str = "", value: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(key))
        self.table.setItem(row, 1, QTableWidgetItem(value))
        flag = QTableWidgetItem("si" if (KNOWN_PROPERTIES.get(key) and KNOWN_PROPERTIES[key].managed) else "")
        flag.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 2, flag)

    def _set_row_managed(self, row: int, managed: bool) -> None:
        key_item = self.table.item(row, 0)
        value_item = self.table.item(row, 1)
        if value_item is None:
            return
        if managed:
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if key_item is not None:
                key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            flag = QTableWidgetItem("si")
        else:
            value_item.setFlags(value_item.flags() | Qt.ItemFlag.ItemIsEditable)
            if key_item is not None:
                key_item.setFlags(key_item.flags() | Qt.ItemFlag.ItemIsEditable)
            flag = QTableWidgetItem("")
        flag.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 2, flag)

    def _add_row(self) -> None:
        from .dialogs import ask_text

        key = ask_text(self, "Nueva propiedad", "Nombre de la propiedad:", placeholder="por ejemplo: allow-flight")
        if not key:
            return
        key = key.strip()
        if not key:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == key:
                self.table.setCurrentCell(row, 1)
                return
        self._append_row(key, "")
        self.table.setCurrentCell(self.table.rowCount() - 1, 1)

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        key = item.text() if item else ""
        if KNOWN_PROPERTIES.get(key) and KNOWN_PROPERTIES[key].managed:
            show_error(self, "Propiedad protegida", "Esta propiedad la gestiona Serviscraft y no se puede quitar.")
            return
        self.table.removeRow(row)

    # ================================================================= guardar
    def _save(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        props = self._current_properties()
        try:
            self.manager.save_properties(spec.id, props)
        except ServiscraftError as exc:
            show_error(self, "No se pudieron guardar las propiedades", str(exc))
            return
        logger.info("Propiedades de %s guardadas desde la interfaz", spec.id)
        self.load(spec)
        self.saved.emit()
        from .dialogs import show_info

        show_info(
            self,
            "Propiedades guardadas",
            "Los cambios se han guardado.\n\n"
            "Reinicia el servidor para que Minecraft los aplique.",
        )

    def _current_properties(self) -> ServerProperties:
        """Construye las propiedades a partir de la vista activa."""
        if self.tabs.currentIndex() == 2:
            # Editor de texto: se usa tal cual lo ha escrito el usuario.
            return ServerProperties.from_text(self._props.path, self.text_editor.toPlainText())

        props = ServerProperties(path=self._props.path, entries=[])
        # Conservamos los comentarios del fichero original para no perderlos.
        for entry in self._props.entries:
            if entry.kind == "comment":
                props.entries.append(entry)
        for key, value in self._table_values(exclude_managed=False).items():
            props.set(key, value)
        return props

    def _table_values(self, *, exclude_managed: bool) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if key_item is None or value_item is None:
                continue
            key = key_item.text().strip()
            if not key:
                continue
            meta = KNOWN_PROPERTIES.get(key)
            if exclude_managed and meta and meta.managed:
                continue
            values[key] = value_item.text()
        return values

    # ================================================================== avisos
    def is_dirty(self) -> bool:
        if self._spec is None:
            return False
        return self.current_values() != {k: v for k, v in self._snapshot.items() if k in self._widgets}

    def confirm_discard(self) -> bool:
        if not self.is_dirty():
            return True
        return confirm(
            self,
            "Cambios sin guardar",
            "Hay cambios sin guardar en las propiedades. ¿Descartarlos?",
            confirm_label="Descartar",
            destructive=True,
        )
