"""Ventana para importar un servidor que ya existia (Aternos y compania).

Se elige la carpeta del servidor (o el ``.zip`` que da Aternos) y la aplicacion
lo reconoce: tipo, version, mundo, plugins, mods, puerto y de donde viene. Antes
de copiar nada se ensena todo, y la copia se hace con barra de progreso y se
puede cancelar sin dejar un servidor a medias.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from ..core.appconfig import AppConfig
from ..core.errors import ServiscraftError, ValidationError
from ..core.import_server import ServerSourceInfo, inspect_source
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerType, format_bytes
from ..core.paths import JAVA_TAGS, MAX_MEMORY_MB, MIN_MEMORY_MB
from ..core.validation import (
    validate_memory_mb,
    validate_minecraft_version,
    validate_name,
    validate_port,
)
from ..core.versions import FALLBACK_VERSIONS, recommended_java_tag
from .common import NumberBox, NumberSlider, hint_label, make_button
from .dialogs import show_error
from .tasks import Task, TaskRunner

logger = get_logger("ui.import")


class ImportServerDialog(QDialog):
    """Trae a Serviscraft un servidor que ya estaba funcionando en otro sitio."""

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        config: AppConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self.config = config
        self._info: ServerSourceInfo | None = None
        self._task: Task | None = None
        self._importando = False
        self._java_manual = False
        #: Servidor creado, para que la ventana principal lo seleccione.
        self.imported = None

        self.setWindowTitle("Importar un servidor de Minecraft")
        self.setMinimumSize(480, 420)
        self.resize(640, 620)

        contenido = QWidget(self)
        layout = QVBoxLayout(contenido)
        layout.setSpacing(12)
        layout.addWidget(
            hint_label(
                "Elige la carpeta de un servidor que ya tenias (o el .zip que se descarga "
                "de Aternos). Se copian el mundo, los plugins o mods y la configuracion: "
                "no se toca nada del original."
            )
        )

        # ------------------------------------------------------------- origen
        origen_box = QGroupBox("Carpeta o archivo del servidor")
        origen_layout = QVBoxLayout(origen_box)
        origen_layout.setSpacing(8)
        botones = QHBoxLayout()
        botones.setSpacing(8)
        self.pick_folder_button = make_button(
            "Elegir carpeta...",
            icon_names=("folder-open", "document-open"),
            tooltip="La carpeta que tiene server.properties y la carpeta del mundo",
        )
        self.pick_folder_button.clicked.connect(self._choose_folder)
        botones.addWidget(self.pick_folder_button)
        self.pick_zip_button = make_button(
            "Elegir archivo .zip...",
            icon_names=("package-x-generic", "application-zip"),
            tooltip="El .zip que da Aternos al descargar el servidor",
        )
        self.pick_zip_button.clicked.connect(self._choose_zip)
        botones.addWidget(self.pick_zip_button)
        botones.addStretch(1)
        origen_layout.addLayout(botones)
        self.path_label = QLabel("Todavia no has elegido nada.")
        self.path_label.setWordWrap(True)
        self.path_label.setObjectName("Hint")
        origen_layout.addWidget(self.path_label)
        layout.addWidget(origen_box)

        # ---------------------------------------------------------- reconocido
        self.detect_card = QFrame()
        self.detect_card.setObjectName("SectionCard")
        detect_layout = QVBoxLayout(self.detect_card)
        detect_layout.setContentsMargins(12, 10, 12, 12)
        detect_layout.setSpacing(6)
        self.origin_label = QLabel("")
        self.origin_label.setObjectName("SectionTitle")
        self.origin_label.setWordWrap(True)
        detect_layout.addWidget(self.origin_label)
        self.detect_label = QLabel("")
        self.detect_label.setWordWrap(True)
        detect_layout.addWidget(self.detect_label)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setObjectName("Hint")
        detect_layout.addWidget(self.notes_label)
        self.detect_card.setVisible(False)
        layout.addWidget(self.detect_card)

        # -------------------------------------------------------------- datos
        datos = QGroupBox("Datos del servidor nuevo")
        form = QFormLayout(datos)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setVerticalSpacing(6)
        form.setHorizontalSpacing(10)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Mi servidor importado")
        self.name.setMaxLength(40)
        form.addRow("Nombre", self.name)

        self.type_combo = QComboBox()
        for server_type in ServerType:
            if server_type is ServerType.MODRINTH:
                continue
            self.type_combo.addItem(server_type.label, server_type.value)
        form.addRow("Tipo", self.type_combo)

        self.version_combo = QComboBox()
        self.version_combo.setEditable(True)
        self.version_combo.addItems(list(FALLBACK_VERSIONS))
        self.version_combo.setCurrentText("latest")
        self.version_combo.setToolTip(
            "Se deduce del servidor importado. Si no se pudo averiguar, se usa la ultima."
        )
        self.version_combo.currentTextChanged.connect(self._on_version_changed)
        form.addRow("Version de Minecraft", self.version_combo)

        self.memory = NumberSlider(
            minimum=MIN_MEMORY_MB,
            maximum=MAX_MEMORY_MB,
            step=512,
            value=config.default_memory_mb,
            suffix=" MB",
        )
        form.addRow("Memoria (RAM)", self.memory)
        self.memory.valueChanged.connect(self._update_memory_label)

        self.port = NumberBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(config.default_port)
        self.port.setMinimumWidth(112)
        self.port.valueChanged.connect(self._check_port)
        self.port.valueChanged.connect(self._update_summary)
        form.addRow("Puerto", self.port)
        self.keep_port = QCheckBox("Usar el puerto original si esta libre")
        self.keep_port.setChecked(True)
        self.keep_port.toggled.connect(self._check_port)
        self.keep_port.toggled.connect(self._update_summary)
        form.addRow("", self.keep_port)
        self.port_status = hint_label("")
        form.addRow("", self.port_status)

        self.java_combo = QComboBox()
        self.java_combo.addItems(list(JAVA_TAGS))
        self.java_combo.setCurrentText(config.default_java_tag)
        self.java_combo.activated.connect(self._mark_java_manual)
        form.addRow("Java", self.java_combo)

        self.lan = QCheckBox("Permitir la conexion desde la red local")
        self.lan.setChecked(True)
        form.addRow("", self.lan)
        layout.addWidget(datos)

        self.summary = QLabel("")
        self.summary.setObjectName("SectionTitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(contenido)

        ventana = QVBoxLayout(self)
        ventana.setSpacing(10)
        ventana.addWidget(scroll, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        ventana.addWidget(self.progress)
        self.status = hint_label("")
        self.status.setWordWrap(True)
        ventana.addWidget(self.status)

        self.buttons = QDialogButtonBox()
        self.import_button = self.buttons.addButton(
            "Importar servidor", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.import_button.setProperty("accent", "true")
        self.import_button.setEnabled(False)
        self.cancel_button = self.buttons.addButton(
            "Cancelar", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.buttons.rejected.connect(self.reject)
        self.import_button.clicked.connect(self._on_accept)
        ventana.addWidget(self.buttons)

        self._update_memory_label()
        self.memory.valueChanged.connect(self._update_summary)

    # ================================================================ origen
    def _choose_folder(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(
            self,
            "Elegir la carpeta del servidor",
            str(Path.home()),
        )
        if carpeta:
            self._inspect(Path(carpeta))

    def _choose_zip(self) -> None:
        archivo, _filtro = QFileDialog.getOpenFileName(
            self,
            "Elegir el archivo del servidor",
            str(Path.home()),
            "Servidores comprimidos (*.zip);;Todos los archivos (*)",
        )
        if archivo:
            self._inspect(Path(archivo))

    def _inspect(self, path: Path) -> None:
        self.path_label.setText(str(path))
        self.detect_card.setVisible(False)
        self.import_button.setEnabled(False)
        self.status.setText("Mirando que hay dentro del servidor...")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        def work(*, context) -> ServerSourceInfo:
            context.progress("Reconociendo el servidor...")
            return inspect_source(path)

        def done(info: ServerSourceInfo) -> None:
            self.progress.setVisible(False)
            self.status.setText("")
            self._on_inspected(info)

        def failed(message: str, details: str) -> None:
            self.progress.setVisible(False)
            self.status.setText("")
            self._info = None
            self.import_button.setEnabled(False)
            show_error(self, "Esa carpeta no es un servidor", message, details)

        self.runner.submit(
            "Reconociendo el servidor", work, on_finished=done, on_failed=failed
        )

    def _on_inspected(self, info: ServerSourceInfo) -> None:
        self._info = info
        self.name.setText(info.name)
        index = self.type_combo.findData(info.server_type.value)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        if info.version_known:
            if self.version_combo.findText(info.version) < 0:
                self.version_combo.insertItem(0, info.version)
            self.version_combo.setCurrentText(info.version)
        else:
            self.version_combo.setCurrentText("latest")
        self.port.setValue(info.port)
        self.keep_port.setChecked(True)

        self.origin_label.setText(
            f"Origen: {info.origin_label}"
            if info.origin
            else "Servidor reconocido (no viene de un hosting conocido)"
        )
        detalles = [
            f"Tipo: {info.server_type.label} {info.version}",
            f"Mundo: «{info.world}»" if info.world else "Mundo: no se ha encontrado",
            f"Archivos: {info.files} ({format_bytes(info.total_bytes)})",
        ]
        if info.plugins:
            detalles.append(f"Plugins: {info.plugins}")
        if info.mods:
            detalles.append(f"Mods: {info.mods}")
        if info.motd:
            detalles.append(f"Descripcion (MOTD): {info.motd}")
        if info.has_icon:
            detalles.append("Imagen del servidor: incluida")
        self.detect_label.setText("  ·  ".join(detalles))
        self.notes_label.setText("\n".join(f"· {nota}" for nota in info.notes))
        self.notes_label.setVisible(bool(info.notes))
        self.detect_card.setVisible(True)
        self.import_button.setEnabled(True)
        self._check_port()
        self._update_summary()

    # ================================================================ formulario
    def _mark_java_manual(self) -> None:
        self._java_manual = True

    def _on_version_changed(self) -> None:
        version = self.version_combo.currentText().strip() or "latest"
        recomendado = recommended_java_tag(version)
        if not self._java_manual and self.java_combo.currentText() != recomendado:
            self.java_combo.blockSignals(True)
            self.java_combo.setCurrentText(recomendado)
            self.java_combo.blockSignals(False)
        self._update_summary()

    def _update_memory_label(self) -> None:
        # El resumen ya dice la memoria en GiB; aqui basta con el detalle exacto.
        self.memory.setToolTip(
            f"= {format_bytes(self.memory.value() * 1024 * 1024)} de RAM"
        )
        self._update_summary()

    def _update_summary(self) -> None:
        if not hasattr(self, "summary"):
            return
        if self._info is None:
            self.summary.setText("")
            return
        version = self.version_combo.currentText().strip() or "latest"
        origen = f" desde {self._info.origin}" if self._info.origin else ""
        self.summary.setText(
            f"{self.type_combo.currentText()} {version} · mundo «{self._info.world}» · "
            f"{format_bytes(self.memory.value() * 1024 * 1024)} de RAM · "
            f"puerto {self.port.value()}{origen}"
        )

    def _check_port(self) -> None:
        libre, motivo = self.manager.check_port_available(self.port.value())
        if self.keep_port.isChecked():
            # Se conserva el puerto del servidor original; si esta ocupado, la
            # aplicacion elige otro libre sin molestar.
            self.port_status.setText(
                "" if libre else f"{motivo} Se usara el siguiente puerto libre."
            )
            ok = True
        else:
            self.port_status.setText("" if libre else motivo)
            ok = libre
        self.import_button.setEnabled(ok and self._info is not None and not self._importando)

    # ================================================================== validar
    def values(self) -> dict:
        """Datos ya validados para crear el servidor importado."""
        name = validate_name(self.name.text())
        version = validate_minecraft_version(self.version_combo.currentText().strip() or "latest")
        memory = validate_memory_mb(self.memory.value())
        port = None
        if not self.keep_port.isChecked():
            # Puerto escrito a mano: tiene que estar libre. Si se conserva el del
            # servidor original, la aplicacion busca otro libre si hace falta.
            port = validate_port(self.port.value(), reserved=self.manager.store.used_ports())
            ok, message = self.manager.check_port_available(port)
            if not ok:
                raise ValidationError("port", message)
        return {
            "name": name,
            "server_type": ServerType.from_value(self.type_combo.currentData()),
            "version": version,
            "memory_mb": memory,
            "port": port,
            "java_tag": self.java_combo.currentText(),
            "lan": self.lan.isChecked(),
        }

    # ================================================================ importar
    def _on_accept(self) -> None:
        if self._info is None:
            show_error(
                self,
                "Falta elegir el servidor",
                "Pulsa «Elegir carpeta...» o «Elegir archivo .zip...» y elige el servidor "
                "que quieres traer.",
            )
            return
        try:
            values = self.values()
        except ServiscraftError as exc:
            show_error(self, "Revisa los datos", getattr(exc, "message", str(exc)))
            return
        info = self._info
        self._importando = True
        self._set_enabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.status.setText("Copiando el servidor. Puede tardar unos minutos...")

        def work(*, context):
            return self.manager.import_server(
                info.path,
                on_progress=context.progress,
                on_files=context.progress_step,
                should_cancel=lambda: context.cancelled,
                **values,
            )

        def done(result) -> None:
            spec, _info = result
            self.imported = spec
            self.accept()

        def failed(message: str, details: str) -> None:
            self._importando = False
            self._set_enabled(True)
            self.progress.setVisible(False)
            self.progress.setRange(0, 0)
            if "cancelada" in message.lower():
                self.status.setText(
                    "Importacion cancelada. No se ha anadido ningun servidor ni se ha "
                    "tocado el original."
                )
                return
            show_error(self, "No se pudo importar el servidor", message, details)

        def progress_value(done_count: int, total: int) -> None:
            if total > 0:
                self.progress.setRange(0, total)
                self.progress.setValue(done_count)
                self.status.setText(
                    f"Copiando: {done_count} de {total} archivos..."
                )

        self._task = self.runner.submit(
            "Importando servidor",
            work,
            on_finished=done,
            on_failed=failed,
            on_progress=self.status.setText,
            on_progress_value=progress_value,
        )

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.pick_folder_button,
            self.pick_zip_button,
            self.name,
            self.type_combo,
            self.version_combo,
            self.memory,
            self.port,
            self.keep_port,
            self.java_combo,
            self.lan,
        ):
            widget.setEnabled(enabled)
        self.import_button.setEnabled(enabled and self._info is not None)
        self.cancel_button.setText("Cancelar" if enabled else "Cancelar importacion")

    # =================================================================== cierre
    def reject(self) -> None:
        if self._task is not None and self._importando:
            # Se pide parar y se deja la ventana abierta hasta que la copia
            # termine de cancelarse (asi no queda un servidor a medias).
            self.status.setText("Cancelando la importacion...")
            self._task.context.cancel()
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if self._task is not None and self._importando:
            self._task.context.cancel()
        super().closeEvent(event)


__all__ = ["ImportServerDialog"]
