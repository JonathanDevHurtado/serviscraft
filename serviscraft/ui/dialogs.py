"""Dialogos de confirmacion, avisos y detalles tecnicos.

Regla del proyecto: ninguna accion destructiva se ejecuta sin una confirmacion
explicita del usuario.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def confirm(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    confirm_label: str = "Continuar",
    cancel_label: str = "Cancelar",
    destructive: bool = False,
) -> bool:
    """Pregunta si/no. Devuelve ``True`` solo si el usuario confirma."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question)
    confirm_button = box.addButton(confirm_label, QMessageBox.ButtonRole.AcceptRole)
    box.addButton(cancel_label, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(confirm_button if not destructive else box.buttons()[1])
    if destructive:
        confirm_button.setProperty("danger", "true")
    box.exec()
    return box.clickedButton() is confirm_button


class ConfirmWithOptions(QDialog):
    """Confirmacion con opciones y verificacion por texto.

    Se usa antes de eliminar un servidor: el usuario decide si quiere una copia
    de seguridad y, si va a borrar los datos, debe escribir el nombre exacto.
    """

    def __init__(
        self,
        server_name: str,
        *,
        parent: QWidget | None = None,
        show_backup_option: bool = True,
        show_data_option: bool = True,
        require_typed_name: bool = True,
    ) -> None:
        super().__init__(parent)
        self.server_name = server_name
        self.setWindowTitle("Eliminar servidor")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        warning = QLabel(
            f"Vas a eliminar el servidor <b>{server_name}</b>.<br>"
            "Esta accion no se puede deshacer."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.backup_check = QCheckBox("Crear una copia de seguridad antes de eliminar")
        self.backup_check.setChecked(True)
        if show_backup_option:
            layout.addWidget(self.backup_check)

        self.data_check = QCheckBox("Eliminar tambien los mundos, pluguins y mods del disco")
        self.data_check.setChecked(True)
        if show_data_option:
            layout.addWidget(self.data_check)

        note = QLabel(
            "Si no eliminas los datos, se conservaran en "
            "<code>~/.local/share/serviscraft/servers/</code> y podras recuperarlos a mano."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.typed = QLineEdit()
        self.typed.setPlaceholderText(server_name)
        self.require_typed_name = require_typed_name
        if require_typed_name:
            label = QLabel(f"Escribe <b>{server_name}</b> para confirmar:")
            layout.addWidget(label)
            layout.addWidget(self.typed)

        buttons = QDialogButtonBox()
        self.delete_button = buttons.addButton("Eliminar", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setProperty("danger", "true")
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        self.delete_button.clicked.connect(self.accept)
        layout.addWidget(buttons)

        self.typed.textChanged.connect(self._validate)
        self.data_check.toggled.connect(self._validate)
        self._validate()

    def _validate(self) -> None:
        typed_ok = (not self.require_typed_name) or self.typed.text().strip() == self.server_name
        data_warning = self.data_check.isChecked() and not self.backup_check.isChecked()
        self.delete_button.setEnabled(typed_ok)
        self.delete_button.setText(
            "Eliminar sin copia de seguridad" if data_warning else "Eliminar"
        )

    @property
    def make_backup(self) -> bool:
        return self.backup_check.isChecked()

    @property
    def delete_data(self) -> bool:
        return self.data_check.isChecked()


class DetailsDialog(QDialog):
    """Muestra un texto largo (errores, registros) con opcion de copiar."""

    def __init__(self, title: str, summary: str, details: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 460)
        layout = QVBoxLayout(self)

        headline = QLabel(summary)
        headline.setWordWrap(True)
        layout.addWidget(headline)

        self.view = QPlainTextEdit(details)
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        copy_button = QPushButton("Copiar detalles")
        copy_button.clicked.connect(self._copy)
        buttons.addWidget(copy_button)
        buttons.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.setProperty("accent", "true")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.view.toPlainText())


def show_error(parent: QWidget | None, title: str, message: str, details: str = "") -> None:
    """Muestra un error con posibilidad de ver el detalle tecnico."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setText(message if len(message) < 800 else message[:800] + "...")
    if details:
        box.setDetailedText(details)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()


def show_info(parent: QWidget | None, title: str, message: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(message)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()


def ask_text(
    parent: QWidget | None,
    title: str,
    label: str,
    *,
    placeholder: str = "",
    initial: str = "",
) -> str | None:
    """Pide una linea de texto. Devuelve ``None`` si se cancela."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(420)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(label))
    field = QLineEdit(initial)
    field.setPlaceholderText(placeholder)
    layout.addWidget(field)
    buttons = QDialogButtonBox()
    ok = buttons.addButton("Aceptar", QDialogButtonBox.ButtonRole.AcceptRole)
    ok.setProperty("accent", "true")
    buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    field.setFocus()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return field.text()


__all__ = [
    "ConfirmWithOptions",
    "DetailsDialog",
    "ask_text",
    "confirm",
    "show_error",
    "show_info",
]
