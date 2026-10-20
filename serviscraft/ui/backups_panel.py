"""Panel de copias de seguridad: crear, restaurar, importar y eliminar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.backup import BackupInfo
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from .common import ElidedLabel, FlowRow, NumberBox, hint_label, make_button, polish_table_header
from .dialogs import ask_text, confirm, show_error, show_info
from .tasks import TaskRunner

logger = get_logger("ui.backups")

#: Nombre legible del origen de cada copia (el que se guarda es tecnico).
ETIQUETAS_ORIGEN = {
    "manual": "manual",
    "automatica": "automatica",
    "al-detener": "al detener",
    "programada": "programada",
    "importada": "importada",
}


class BackupsPanel(QWidget):
    """Gestion de copias de seguridad del servidor seleccionado."""

    changed = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Las acciones van en dos grupos que se envuelven por separado: la fila se
        # parte cuando la ventana se estrecha y nada queda recortado.
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.backups_actions = FlowRow()
        self.create_button = make_button(
            "Crear copia ahora",
            icon_names=("document-save", "archive-insert"),
            accent=True,
            tooltip="Comprime los mundos, pluguins y mods del servidor",
        )
        self.create_button.clicked.connect(self._create_backup)
        self.backups_actions.add(self.create_button)

        self.restore_button = make_button(
            "Restaurar seleccionada",
            icon_names=("document-revert", "edit-undo"),
            tooltip="Sustituye los datos actuales por los de la copia (requiere el servidor detenido)",
        )
        self.restore_button.clicked.connect(self._restore_backup)
        self.backups_actions.add(self.restore_button)

        import_button = make_button("Importar copia...", icon_names=("document-open", "archive-extract"),
                                    tooltip="Traer una copia de otro equipo o de un servidor eliminado")
        import_button.clicked.connect(self._import_backup)
        self.backups_actions.add(import_button)

        export_button = make_button("Exportar...", icon_names=("document-save-as",),
                                    tooltip="Guardar una copia del listado en otra ubicacion")
        export_button.clicked.connect(self._export_backup)
        self.backups_actions.add(export_button)

        refresh_button = make_button("Refrescar", icon_names=("view-refresh",))
        refresh_button.clicked.connect(self.refresh)
        self.backups_actions.add(refresh_button)
        toolbar.addWidget(self.backups_actions)
        toolbar.addStretch(1)

        self.keep_actions = FlowRow()
        self.keep_actions.add(QLabel("Conservar"))
        self.keep_spin = NumberBox()
        self.keep_spin.setRange(1, 100)
        self.keep_spin.setValue(5)
        self.keep_spin.setToolTip("Numero de copias que se conservaran al limpiar")
        self.keep_actions.add(self.keep_spin)
        prune_button = make_button("Limpiar antiguas", icon_names=("edit-clear-history",),
                                   tooltip="Borra las copias mas antiguas dejando las mas recientes")
        prune_button.clicked.connect(self._prune)
        self.keep_actions.add(prune_button)
        toolbar.addWidget(self.keep_actions)
        layout.addLayout(toolbar)

        # Donde vive cada copia: la carpeta del servidor, siempre a la vista (es
        # la duda mas habitual: «¿donde ha quedado el respaldo?»).
        location_row = FlowRow(spacing=8)
        location_row.add(QLabel("Carpeta de copias:"))
        self.location = ElidedLabel("—")
        self.location.setObjectName("Hint")
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location_row.add(self.location)
        self.open_folder_button = make_button(
            "Abrir carpeta",
            icon_names=("folder-open", "system-file-manager"),
            tooltip="Abrir la carpeta de copias en el gestor de archivos",
        )
        self.open_folder_button.clicked.connect(self._open_folder)
        location_row.add(self.open_folder_button)
        self.copy_path_button = make_button(
            "Copiar ruta",
            icon_names=("edit-copy",),
            tooltip="Copiar la ruta de la carpeta al portapapeles",
        )
        self.copy_path_button.clicked.connect(self._copy_path)
        location_row.add(self.copy_path_button)
        self.location_row = location_row
        layout.addWidget(location_row)

        self.warning = hint_label("")
        layout.addWidget(self.warning)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Copia", "Fecha", "Tamano", "Origen"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        polish_table_header(self.table)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _index: self._restore_backup())
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(180)
        footer.addWidget(self.progress)
        footer.addStretch(1)

        self.rename_button = make_button(
            "Renombrar...",
            icon_names=("edit-rename", "document-edit"),
            tooltip="Ponerle un nombre propio a la copia (el archivo no se toca)",
        )
        self.rename_button.clicked.connect(self._rename_backup)
        footer.addWidget(self.rename_button)

        self.delete_button = make_button("Eliminar copia", icon_names=("edit-delete",), danger=True)
        self.delete_button.clicked.connect(self._delete_backup)
        footer.addWidget(self.delete_button)
        layout.addLayout(footer)

        self.empty = QLabel("Selecciona un servidor para gestionar sus copias.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None, running=False)

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._running != running
        self._spec = spec
        self._running = running
        has_server = spec is not None
        # Sin servidor seleccionado solo se ve el mensaje de estado vacio: nada de
        # botones que no harian nada.
        for widget in (
            self.backups_actions,
            self.keep_actions,
            self.location_row,
            self.warning,
            self.table,
            self.rename_button,
            self.delete_button,
        ):
            widget.setVisible(has_server)
        self.empty.setVisible(not has_server)
        self._update_location()
        self._update_warning()
        if has_server and cambio_estado:
            self.refresh()

    def _update_location(self) -> None:
        if self._spec is None:
            self.location.setText("")
            self.location.setToolTip("")
            return
        folder = self.manager.backups_folder(self._spec.id)
        self.location.setText(folder)
        self.location.setToolTip(
            f"Las copias de «{self._spec.name}» se guardan en:\n{folder}\n\n"
            "Cada servidor tiene su propia carpeta; las copias automaticas (al detener y "
            "programadas) se limpian segun la retencion de las preferencias."
        )

    def _open_folder(self) -> None:
        if self._spec is None:
            return
        folder = self.manager.store.backups_dir(self._spec.id)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            show_error(self, "No se pudo abrir la carpeta", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _copy_path(self) -> None:
        if self._spec is None:
            return
        path = self.manager.backups_folder(self._spec.id)
        QApplication.clipboard().setText(path)
        self.warning.setText(f"Ruta copiada al portapapeles: {path}")

    def set_running(self, running: bool) -> None:
        self._running = running
        self._update_warning()

    def _update_warning(self) -> None:
        if self._spec is None:
            self.warning.setText("")
            return
        if self._running:
            self.warning.setText(
                "El servidor esta en ejecucion. Una copia hecha ahora puede contener el mundo a "
                "medio guardar: lo recomendable es detener el servidor antes de copiar o restaurar. "
                "Restaurar esta deshabilitado mientras el servidor funciona."
            )
        else:
            self.warning.setText("El servidor esta detenido: es el momento ideal para copiar o restaurar.")
        self.restore_button.setEnabled(not self._running)

    # ================================================================= listado
    def refresh(self) -> None:
        if self._spec is None:
            return
        try:
            backups = self.manager.backups.list_backups(self._spec.id)
        except ServiscraftError as exc:
            show_error(self, "No se pudieron listar las copias", str(exc))
            return
        self.table.setRowCount(0)
        for info in backups:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(info.display_name)
            item.setData(Qt.ItemDataRole.UserRole, info)
            item.setToolTip(f"{info.filename}\n{info.path}")
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(_format_date(info.created_at)))
            self.table.setItem(row, 2, QTableWidgetItem(info.size_label))
            self.table.setItem(row, 3, QTableWidgetItem(ETIQUETAS_ORIGEN.get(info.origin, info.origin)))

    def _selected(self) -> BackupInfo | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, BackupInfo) else None

    # ================================================================= acciones
    def _create_backup(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        if self._running and not confirm(
            self,
            "El servidor esta en ejecucion",
            "Crear una copia con el servidor en marcha puede guardar el mundo a medias.\n\n"
            "¿Quieres crearla de todas formas? Podras restaurarla despues.",
            confirm_label="Copiar ahora",
        ):
            return
        label = ask_text(
            self,
            "Nueva copia de seguridad",
            "Etiqueta de la copia (opcional):",
            placeholder="por ejemplo: antes-de-instalar-mods",
        )
        if label is None:
            return
        self._set_busy(True, "Preparando la copia...")

        def work(*, context) -> BackupInfo:
            context.progress("Comprimiendo los datos del servidor...")
            return self.manager.backups.create_backup(
                spec.id,
                label=label,
                origin="manual",
                on_progress=lambda done, total: context.progress_step(done, total or 1),
            )

        self.runner.submit(
            "Creando copia de seguridad",
            work,
            on_finished=self._on_created,
            on_failed=self._on_error,
            on_progress=self._on_progress_message,
            on_progress_value=self._on_progress_value,
        )

    def _on_created(self, info: BackupInfo) -> None:
        self._set_busy(False)
        self.refresh()
        self.changed.emit()
        show_info(self, "Copia creada", f"Se ha creado «{info.display_name}» ({info.size_label}).")

    def _restore_backup(self) -> None:
        info = self._selected()
        if self._spec is None or info is None:
            show_info(self, "Nada seleccionado", "Selecciona una copia de la lista.")
            return
        if self._running:
            show_error(
                self,
                "Servidor en ejecucion",
                "Deten el servidor antes de restaurar una copia de seguridad.",
            )
            return
        safety = "Se creara antes una copia de seguridad del estado actual." if self.manager.config.safety_backup_before_restore else ""
        if not confirm(
            self,
            "Restaurar copia de seguridad",
            f"Se sustituiran los datos actuales del servidor por los de «{info.display_name}» "
            f"({info.size_label}).\n\n{safety}",
            confirm_label="Restaurar",
            destructive=True,
        ):
            return
        spec = self._spec
        make_safety = self.manager.config.safety_backup_before_restore
        self._set_busy(True, "Restaurando la copia...")

        def work(*, context) -> str:
            if make_safety:
                context.progress("Creando una copia del estado actual...")
                self.manager.backups.create_backup(spec.id, label="antes-de-restaurar", origin="automatica")
            context.progress("Extrayendo la copia...")
            self.manager.backups.restore_backup(
                spec.id,
                info.path,
                on_progress=lambda done, total: context.progress_step(done, total or 1),
            )
            return info.display_name

        self.runner.submit(
            "Restaurando copia de seguridad",
            work,
            on_finished=self._on_restored,
            on_failed=self._on_error,
            on_progress=self._on_progress_message,
            on_progress_value=self._on_progress_value,
        )

    def _on_restored(self, name: str) -> None:
        self._set_busy(False)
        self.refresh()
        self.changed.emit()
        show_info(self, "Copia restaurada", f"El servidor vuelve al estado de «{name}».")

    def _import_backup(self) -> None:
        if self._spec is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar copia de seguridad",
            str(Path.home()),
            "Copias de Serviscraft (*.tar.gz *.tgz);;Todos los ficheros (*)",
        )
        if not path:
            return
        spec = self._spec

        def work(*, context) -> BackupInfo:
            context.progress("Importando la copia...")
            return self.manager.backups.import_backup(spec.id, path)

        self.runner.submit(
            "Importando copia de seguridad",
            work,
            on_finished=self._on_imported,
            on_failed=self._on_error,
        )

    def _on_imported(self, info: BackupInfo) -> None:
        self.refresh()
        show_info(
            self,
            "Copia importada",
            f"Se ha importado «{info.display_name}».\nUsa «Restaurar seleccionada» para aplicarla.",
        )

    def _export_backup(self) -> None:
        info = self._selected()
        if info is None:
            show_info(self, "Nada seleccionado", "Selecciona una copia de la lista.")
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar copia de seguridad",
            str(Path.home() / info.filename),
            "Copias de Serviscraft (*.tar.gz)",
        )
        if not destination:
            return
        try:
            import shutil

            shutil.copy2(info.path, destination)
        except OSError as exc:
            show_error(self, "No se pudo exportar", str(exc))
            return
        show_info(self, "Copia exportada", f"Guardada en:\n{destination}")

    def _rename_backup(self) -> None:
        info = self._selected()
        if self._spec is None or info is None:
            show_info(self, "Nada seleccionado", "Selecciona una copia de la lista para ponerle nombre.")
            return
        label = ask_text(
            self,
            "Renombrar copia de seguridad",
            "Nombre de la copia (vacio = usar el nombre del archivo):",
            placeholder="por ejemplo: antes de instalar la 1.21",
            initial=info.label or info.filename,
        )
        if label is None:
            return
        try:
            actualizada = self.manager.backups.rename_backup(self._spec.id, info.path, label)
        except ServiscraftError as exc:
            show_error(self, "No se pudo renombrar", str(exc))
            return
        self.refresh()
        self.warning.setText(f"Copia renombrada: «{actualizada.display_name}».")

    def _delete_backup(self) -> None:
        info = self._selected()
        if self._spec is None or info is None:
            show_info(self, "Nada seleccionado", "Selecciona una copia de la lista.")
            return
        if not confirm(
            self,
            "Eliminar copia de seguridad",
            f"¿Eliminar «{info.display_name}» ({info.size_label}) de forma permanente?",
            confirm_label="Eliminar",
            destructive=True,
        ):
            return
        try:
            self.manager.backups.delete_backup(self._spec.id, info.path)
        except ServiscraftError as exc:
            show_error(self, "No se pudo eliminar", str(exc))
            return
        self.refresh()

    def _prune(self) -> None:
        if self._spec is None:
            return
        keep = self.keep_spin.value()
        if not confirm(
            self,
            "Limpiar copias antiguas",
            f"Se conservaran las {keep} copias mas recientes y se borraran las demas.\n\n"
            "Esta accion no se puede deshacer.",
            confirm_label="Limpiar",
            destructive=True,
        ):
            return
        try:
            removed = self.manager.backups.prune(self._spec.id, keep=keep)
        except ServiscraftError as exc:
            show_error(self, "No se pudo limpiar", str(exc))
            return
        self.refresh()
        show_info(self, "Limpieza completada", f"Se han eliminado {removed} copias.")

    # ================================================================ progreso
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
        self.create_button.setEnabled(not busy)
        self.restore_button.setEnabled(not busy and not self._running)
        self.rename_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy)
        if message:
            self.warning.setText(message)

    def _on_progress_message(self, message: str) -> None:
        self.warning.setText(message)

    def _on_progress_value(self, done: int, total: int) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(int(min(100, done * 100 / total)))

    def _on_error(self, message: str, details: str) -> None:
        self._set_busy(False)
        self._update_warning()
        show_error(self, "La operacion no se pudo completar", message, details)


def _format_date(value: str) -> str:
    text = (value or "").replace("T", " ")
    return text[:16] if len(text) >= 16 else text
