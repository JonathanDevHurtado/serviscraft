"""Administracion de pluguins, mods, mundos y ficheros del servidor."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import ServiscraftError, ValidationError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec, format_bytes
from ..core.server_files import FileEntry, ServerFiles
from .catalog_dialog import CatalogDialog
from .common import ElidedLabel, FlowRow, hint_label, make_button, polish_table_header
from .dialogs import ask_text, confirm, show_error, show_info
from .tasks import TaskRunner

logger = get_logger("ui.files")

MODE_PLUGINS = "plugins"
MODE_MODS = "mods"
MODE_WORLDS = "mundos"
MODE_BROWSE = "ficheros"


class DownloadDialog(QDialog):
    """Pide la direccion de un pluguin o mod para descargarlo."""

    def __init__(self, destination: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Descargar desde una direccion")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        layout.addWidget(
            hint_label(
                "Pega el enlace directo al fichero .jar (por ejemplo, de Modrinth, Hangar o "
                "la pagina del pluguin). Se guardara en la carpeta seleccionada."
            )
        )
        layout.addWidget(QLabel(f"Destino: {destination}"))

        self.url = QLineEdit()
        self.url.setPlaceholderText("https://ejemplo.com/plugin.jar")
        layout.addWidget(self.url)

        self.filename = QLineEdit()
        self.filename.setPlaceholderText("Nombre del fichero (opcional)")
        layout.addWidget(self.filename)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Descargar", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setProperty("accent", "true")
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.url.text().strip(), self.filename.text().strip()


class FilesPanel(QWidget):
    """Explorador del contenido del servidor con acciones de gestion."""

    files_changed = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._relative = ""
        self._current_task = None
        #: Estado del servidor en el ultimo ``set_server`` (para no refrescar de
        #: mas cuando la ventana actualiza los estados periodicamente).
        self._running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ------------------------------------------------------------- toolbar
        # Toda la barra (vista + botones) va en una fila que envuelve: con la
        # ventana estrecha no cabe de una vez y nada debe quedar recortado.
        toolbar = FlowRow(spacing=8)
        toolbar.add(QLabel("Vista:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Ficheros del servidor", MODE_BROWSE)
        self.mode_combo.addItem("Pluguins", MODE_PLUGINS)
        self.mode_combo.addItem("Mods", MODE_MODS)
        self.mode_combo.addItem("Mundos", MODE_WORLDS)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.add(self.mode_combo)

        self.import_button = make_button("Importar ficheros...", icon_names=("document-open",),
                                         tooltip="Copiar pluguins o mods desde el equipo")
        self.import_button.clicked.connect(self._import_files)
        toolbar.add(self.import_button)

        self.catalog_button = make_button(
            "Buscar e instalar...",
            icon_names=("system-search", "document-import"),
            tooltip="Buscar pluguins o mods en Modrinth e instalarlos con un clic",
        )
        self.catalog_button.clicked.connect(self._open_catalog)
        toolbar.add(self.catalog_button)

        self.download_button = make_button("Descargar de una URL...", icon_names=("download", "insert-link"))
        self.download_button.clicked.connect(self._download)
        toolbar.add(self.download_button)

        self.new_folder_button = make_button("Nueva carpeta", icon_names=("folder-new",))
        self.new_folder_button.clicked.connect(self._new_folder)
        toolbar.add(self.new_folder_button)

        self.open_button = make_button("Abrir carpeta", icon_names=("folder-open",),
                                       tooltip="Abrir esta carpeta en el gestor de archivos")
        self.open_button.clicked.connect(self._open_folder)
        toolbar.add(self.open_button)

        refresh_button = make_button("Refrescar", icon_names=("view-refresh",))
        refresh_button.clicked.connect(self.refresh)
        toolbar.add(refresh_button)
        layout.addWidget(toolbar)

        # ------------------------------------------------------------- ruta
        # La ruta puede ser muy larga, asi que se recorta con puntos suspensivos y
        # toda la fila se envuelve si no cabe.
        self.path_row = FlowRow(spacing=6)
        self.up_button = make_button("Subir", icon_names=("go-up", "go-parent"))
        self.up_button.clicked.connect(self._go_up)
        self.path_row.add(self.up_button)
        self.path_label = ElidedLabel("/")
        self.path_label.setObjectName("Hint")
        self.path_row.add(self.path_label)
        self.hidden_check = QCheckBox("Mostrar ficheros ocultos")
        self.hidden_check.toggled.connect(lambda _v: self.refresh())
        self.path_row.add(self.hidden_check)
        layout.addWidget(self.path_row)

        # ------------------------------------------------------------ aviso
        self.warning = hint_label("")
        layout.addWidget(self.warning)

        # ------------------------------------------------------------ tabla
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Nombre", "Tamano", "Modificado"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_double_click)
        polish_table_header(self.table)
        layout.addWidget(self.table, 1)

        # -------------------------------------------------- acciones de mundos
        self.world_actions = FlowRow(spacing=8)
        activate = make_button("Activar", icon_names=("dialog-ok-apply",), accent=True,
                               tooltip="Usar este mundo como mundo activo del servidor")
        activate.clicked.connect(self._activate_world)
        self.world_actions.add(activate)
        rename = make_button("Renombrar", icon_names=("edit-rename",))
        rename.clicked.connect(self._rename_world)
        self.world_actions.add(rename)
        copy_world = make_button("Copiar mundo", icon_names=("edit-copy",),
                                 tooltip="Crear una copia de seguridad solo de este mundo")
        copy_world.clicked.connect(self._copy_world)
        self.world_actions.add(copy_world)
        self.world_actions.setVisible(False)
        layout.addWidget(self.world_actions)

        # -------------------------------------------------------- pie de acciones
        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(180)
        footer.addWidget(self.progress)
        footer.addStretch(1)

        self.delete_button = make_button("Eliminar seleccionado", icon_names=("edit-delete",), danger=True)
        self.delete_button.clicked.connect(self._delete_selected)
        footer.addWidget(self.delete_button)
        layout.addLayout(footer)

        self.empty = QLabel("Selecciona un servidor para ver su contenido.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None, running=False)

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        # Si es el mismo servidor y el mismo estado no se vuelve a leer nada: el
        # refresco periodico de la ventana llamaba a esta funcion cada pocos
        # segundos y devolvia al usuario a la carpeta raiz mientras navegaba.
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._running != running
        self._spec = spec
        self._running = running
        if cambio:
            self._relative = ""
        has_server = spec is not None
        for widget in (
            self.mode_combo,
            self.import_button,
            self.catalog_button,
            self.download_button,
            self.new_folder_button,
            self.open_button,
            self.table,
            self.up_button,
            self.hidden_check,
            self.delete_button,
        ):
            widget.setVisible(has_server)
        self.empty.setVisible(not has_server)
        self.world_actions.setVisible(False)
        if not has_server:
            self.warning.setText("")
            return
        self._configure_modes(spec)
        if running:
            self.warning.setText(
                "El servidor esta en ejecucion. Los cambios en pluguins, mods y mundos "
                "solo se aplican despues de reiniciarlo."
            )
        else:
            self.warning.setText("")
        if cambio_estado:
            self.refresh()

    def _configure_modes(self, spec: ServerSpec) -> None:
        """Activa solo las vistas que tienen sentido para este tipo de servidor."""
        keep = [MODE_BROWSE]
        if spec.supports_plugins:
            keep.append(MODE_PLUGINS)
        if spec.supports_mods:
            keep.append(MODE_MODS)
        keep.append(MODE_WORLDS)

        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        labels = {
            MODE_BROWSE: "Ficheros del servidor",
            MODE_PLUGINS: "Pluguins",
            MODE_MODS: "Mods",
            MODE_WORLDS: "Mundos",
        }
        for mode in keep:
            self.mode_combo.addItem(labels[mode], mode)
        if spec.supports_plugins:
            self.mode_combo.setCurrentIndex(1)
        elif spec.supports_mods:
            self.mode_combo.setCurrentIndex(1)
        self.mode_combo.blockSignals(False)
        self._on_mode_changed()

    @property
    def mode(self) -> str:
        return self.mode_combo.currentData() or MODE_BROWSE

    def _files(self) -> ServerFiles:
        assert self._spec is not None
        return self.manager.files(self._spec.id)

    def _target_dir(self) -> str:
        if self.mode == MODE_PLUGINS:
            return "plugins"
        if self.mode == MODE_MODS:
            return "mods"
        return self._relative

    # ================================================================ listado
    def _on_mode_changed(self) -> None:
        if self._spec is None:
            return
        if self.mode in {MODE_PLUGINS, MODE_MODS}:
            self._relative = self._target_dir()
        else:
            self._relative = ""
        self.world_actions.setVisible(self.mode == MODE_WORLDS)
        self.catalog_button.setVisible(self._spec is not None and self.mode in {MODE_PLUGINS, MODE_MODS})
        self.refresh()

    def refresh(self) -> None:
        if self._spec is None:
            return
        if self.mode == MODE_WORLDS:
            self._fill_worlds()
            return
        self._fill_entries()

    def _fill_entries(self) -> None:
        directory = self._target_dir()
        self._relative = directory
        self.path_label.setText("/" + (directory or ""))
        self.up_button.setEnabled(self.mode == MODE_BROWSE and bool(directory))
        try:
            entries = self._files().list_entries(directory, include_hidden=self.hidden_check.isChecked())
        except ServiscraftError as exc:
            show_error(self, "No se pudo leer la carpeta", str(exc))
            return
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Nombre", "Tamano", "Modificado"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        polish_table_header(self.table)
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = ("📁 " if entry.is_dir else "📄 ") + entry.name
            item = QTableWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(entry.size_label))
            self.table.setItem(row, 2, QTableWidgetItem(_format_time(entry.modified)))

    def _fill_worlds(self) -> None:
        self.path_label.setText("Mundos del servidor")
        self.up_button.setEnabled(False)
        try:
            worlds = self._files().list_worlds()
        except ServiscraftError as exc:
            show_error(self, "No se pudieron listar los mundos", str(exc))
            return
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Mundo", "Tamano", "Estado"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        polish_table_header(self.table)
        self.table.setRowCount(0)
        for world in worlds:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(("🌍 " if world.active else "   ") + world.name)
            item.setData(Qt.ItemDataRole.UserRole, world)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(world.size_label))
            self.table.setItem(row, 2, QTableWidgetItem("Activo" if world.active else "Inactivo"))

    # ================================================================ navegacion
    def _go_up(self) -> None:
        if self.mode != MODE_BROWSE or not self._relative:
            return
        parent = str(PurePosixPath(self._relative).parent)
        self._relative = "" if parent in {".", ""} else parent
        self.refresh()

    def _on_double_click(self, index) -> None:
        item = self.table.item(index.row(), 0)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, FileEntry) and data.is_dir:
            self._relative = data.relative_path
            self.refresh()

    def _selected_entry(self) -> FileEntry | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, FileEntry) else None

    def _selected_world(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    # ================================================================= acciones
    def _import_files(self) -> None:
        if self._spec is None:
            return
        destination = self._target_dir()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            f"Importar a {destination or 'la carpeta del servidor'}",
            str(Path.home()),
            "Contenido de Minecraft (*.jar *.zip *.mrpack);;Todos los ficheros (*)",
        )
        if not paths:
            return
        spec = self._spec

        def work(*, context) -> list[str]:
            context.progress("Copiando ficheros...")
            imported = self.manager.files(spec.id).import_files([Path(p) for p in paths], destination)
            return [p.name for p in imported]

        self.runner.submit(
            "Importando ficheros",
            work,
            on_finished=self._on_imported,
            on_failed=self._on_error,
        )

    def _on_imported(self, names: list[str]) -> None:
        self.refresh()
        self.files_changed.emit()
        if names:
            show_info(self, "Ficheros importados", "Se han copiado:\n\n" + "\n".join(names))

    def _open_catalog(self) -> None:
        if self._spec is None:
            return
        if self.mode not in {MODE_PLUGINS, MODE_MODS}:
            return
        dialog = CatalogDialog(self.manager, self.runner, self._spec, self.mode, self)
        dialog.exec()
        if dialog.installed:
            self.refresh()
            self.files_changed.emit()

    def _download(self) -> None:
        if self._spec is None:
            return
        destination = self._target_dir() or "."
        dialog = DownloadDialog(destination, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url, filename = dialog.values()
        if not url:
            return
        spec = self._spec

        def work(*, context) -> str:
            context.progress("Descargando...")
            path = self.manager.files(spec.id).download(url, destination, filename=filename or None)
            return path.name

        self._set_busy(True)
        self.runner.submit(
            "Descargando fichero",
            work,
            on_finished=self._on_downloaded,
            on_failed=self._on_error,
        )

    def _on_downloaded(self, name: str) -> None:
        self._set_busy(False)
        self.refresh()
        self.files_changed.emit()
        show_info(self, "Descarga completada", f"Se ha guardado «{name}».")

    def _new_folder(self) -> None:
        if self._spec is None:
            return
        name = ask_text(self, "Nueva carpeta", "Nombre de la carpeta:", placeholder="mi-carpeta")
        if not name:
            return
        try:
            self._files().create_folder(self._target_dir(), name)
        except (ServiscraftError, OSError) as exc:
            show_error(self, "No se pudo crear la carpeta", str(exc))
            return
        self.refresh()

    def _open_folder(self) -> None:
        if self._spec is None:
            return
        try:
            path = self._files().resolve(self._target_dir())
        except ServiscraftError as exc:
            show_error(self, "Ruta no valida", str(exc))
            return
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _delete_selected(self) -> None:
        if self._spec is None:
            return
        if self.mode == MODE_WORLDS:
            self._delete_world()
            return
        entry = self._selected_entry()
        if entry is None:
            show_info(self, "Nada seleccionado", "Selecciona antes un fichero o una carpeta.")
            return
        kind = "la carpeta" if entry.is_dir else "el fichero"
        if not confirm(
            self,
            "Eliminar contenido",
            f"¿Eliminar {kind} «{entry.name}» de forma permanente?",
            confirm_label="Eliminar",
            destructive=True,
        ):
            return
        try:
            self._files().delete_entry(entry.relative_path)
        except ServiscraftError as exc:
            show_error(self, "No se pudo eliminar", str(exc))
            return
        self.refresh()
        self.files_changed.emit()

    # ================================================================ mundos
    def _activate_world(self) -> None:
        world = self._selected_world()
        if world is None:
            show_info(self, "Nada seleccionado", "Selecciona un mundo de la lista.")
            return
        if world.active:
            return
        if not confirm(
            self,
            "Cambiar el mundo activo",
            f"El servidor pasara a usar el mundo «{world.name}».\n\n"
            "Reinicia el servidor para que se aplique el cambio.",
            confirm_label="Activar",
        ):
            return
        try:
            self._files().set_active_world(world.name)
        except ServiscraftError as exc:
            show_error(self, "No se pudo activar el mundo", str(exc))
            return
        self.refresh()
        self.files_changed.emit()

    def _rename_world(self) -> None:
        world = self._selected_world()
        if world is None:
            show_info(self, "Nada seleccionado", "Selecciona un mundo de la lista.")
            return
        new_name = ask_text(self, "Renombrar mundo", "Nuevo nombre del mundo:", initial=world.name)
        if not new_name or new_name == world.name:
            return
        try:
            self._files().rename_world(world.name, new_name)
        except (ServiscraftError, ValidationError) as exc:
            show_error(self, "No se pudo renombrar", str(exc))
            return
        self.refresh()
        self.files_changed.emit()

    def _copy_world(self) -> None:
        world = self._selected_world()
        if world is None:
            show_info(self, "Nada seleccionado", "Selecciona un mundo de la lista.")
            return
        if self._spec is None:
            return
        spec = self._spec

        def work(*, context) -> str:
            context.progress(f"Copiando el mundo {world.name}...")
            return self.manager.files(spec.id).copy_world(world.name)

        self._set_busy(True)
        self.runner.submit(
            f"Copia del mundo {world.name}",
            work,
            on_finished=self._on_world_copied,
            on_failed=self._on_error,
        )

    def _on_world_copied(self, name: str) -> None:
        self._set_busy(False)
        self.refresh()
        show_info(self, "Mundo copiado", f"Se ha creado la copia «{name}».")

    def _delete_world(self) -> None:
        world = self._selected_world()
        if world is None:
            show_info(self, "Nada seleccionado", "Selecciona un mundo de la lista.")
            return
        if world.active:
            show_error(
                self,
                "Mundo activo",
                "No se puede eliminar el mundo activo. Activa otro mundo antes de borrarlo.",
            )
            return
        if not confirm(
            self,
            "Eliminar mundo",
            f"¿Eliminar el mundo «{world.name}» ({world.size_label}) de forma permanente?\n\n"
            "Esta accion no se puede deshacer.",
            confirm_label="Eliminar mundo",
            destructive=True,
        ):
            return
        try:
            freed = self._files().delete_world(world.name)
        except ServiscraftError as exc:
            show_error(self, "No se pudo eliminar el mundo", str(exc))
            return
        self.refresh()
        self.files_changed.emit()
        show_info(self, "Mundo eliminado", f"Se han liberado {format_bytes(freed)}.")

    # ================================================================ utilidades
    def _set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.import_button.setEnabled(not busy)
        self.catalog_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy)

    def _on_error(self, message: str, details: str) -> None:
        self._set_busy(False)
        show_error(self, "La operacion no se pudo completar", message, details)

    def set_running(self, running: bool) -> None:
        if self._spec is None:
            return
        if running:
            self.warning.setText(
                "El servidor esta en ejecucion. Los cambios en pluguins, mods y mundos "
                "solo se aplican despues de reiniciarlo."
            )
        else:
            self.warning.setText("")


def _format_time(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M")
    except (OSError, OverflowError, ValueError):  # pragma: no cover
        return "-"
