"""Dialogo de ajustes de un servidor existente y de preferencias globales."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import paths
from ..core.appconfig import AppConfig
from ..core.errors import ValidationError
from ..core.manager import ServerManager, jvm_overhead_mb
from ..core.models import ServerSpec, format_bytes
from ..core.paths import JAVA_TAGS, MAX_MEMORY_MB, MIN_MEMORY_MB
from ..core.validation import (
    validate_java_tag,
    validate_memory_mb,
    validate_minecraft_version,
    validate_name,
    validate_port,
)
from ..core.versions import FALLBACK_VERSIONS, fetch_versions, recommended_java_tag, version_choices
from .common import NumberBox, NumberSlider, hint_label, make_button
from .dialogs import confirm, show_error
from .tasks import TaskRunner


class ServerSettingsDialog(QDialog):
    """Cambia los ajustes de un servidor detenido y recrea su contenedor."""

    def __init__(
        self,
        manager: ServerManager,
        spec: ServerSpec,
        parent: QWidget | None = None,
        *,
        runner: TaskRunner | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.spec = spec
        self.runner = runner
        self._java_manual = False
        self.setWindowTitle(f"Ajustes de «{spec.name}»")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(
            hint_label(
                "El servidor debe estar detenido. Al guardar se vuelve a crear el contenedor "
                "con los nuevos valores; los mundos y el contenido no se tocan."
            )
        )

        # Las secciones van dentro de un area con barra de desplazamiento para que
        # el cuadro quepa en pantallas bajas (y en una ventana con mosaico).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # ---------------------------------------------------------- identidad
        identity = QGroupBox("Identidad")
        identity_form = QFormLayout(identity)
        identity_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.name = QLineEdit(spec.name)
        self.name.setMaxLength(32)
        self.name.setToolTip("El nombre se puede cambiar sin tocar el mundo ni el contenido")
        identity_form.addRow("Nombre", self.name)

        info = QLabel(spec.type.label)
        info.setObjectName("Hint")
        info.setToolTip("El tipo de servidor no se puede cambiar sin crear otro servidor")
        identity_form.addRow("Tipo", info)
        content_layout.addWidget(identity)

        # ---------------------------------------------------------- minecraft
        minecraft = QGroupBox("Minecraft")
        minecraft_form = QFormLayout(minecraft)
        minecraft_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        version_row = QHBoxLayout()
        self.version_combo = QComboBox()
        # Solo se eligen versiones de la lista: escribir a mano dejaba valores
        # que Mojang no reconoce y el servidor fallaba al arrancar.
        self.version_combo.setEditable(False)
        self.version_combo.addItems(list(FALLBACK_VERSIONS))
        self.version_combo.setCurrentText(spec.version)
        self.version_combo.setToolTip(
            "Elige una version de la lista. «Actualizar lista...» consulta las que "
            "publica Mojang (la lista incluida sirve sin conexion)."
        )
        version_row.addWidget(self.version_combo, 1)
        self.load_versions_button = make_button(
            "Actualizar lista...",
            icon_names=("view-refresh", "download"),
            tooltip="Consultar la lista oficial de versiones de Mojang",
        )
        self.load_versions_button.clicked.connect(self._load_versions)
        self.load_versions_button.setEnabled(runner is not None)
        if runner is None:
            self.load_versions_button.setVisible(False)
        version_row.addWidget(self.load_versions_button)
        minecraft_form.addRow("Version de Minecraft", self._wrap(version_row))
        self.version_note = hint_label("")
        minecraft_form.addRow("", self.version_note)

        self.java_combo = QComboBox()
        self.java_combo.addItems(list(JAVA_TAGS))
        self.java_combo.setCurrentText(spec.java_tag)
        self.java_combo.setToolTip(
            "Version de Java del contenedor. Se elige sola al cambiar de version de "
            "Minecraft, pero aqui puedes fijarla a mano."
        )
        self.java_combo.activated.connect(self._mark_java_manual)
        minecraft_form.addRow("Java", self.java_combo)
        minecraft_form.addRow(
            "",
            hint_label(
                "Java se elige automaticamente segun la version de Minecraft; si lo cambias "
                "a mano se respeta aunque cambies de version."
            ),
        )
        content_layout.addWidget(minecraft)

        # ------------------------------------------------------------ recursos
        resources = QGroupBox("Recursos")
        resources_form = QFormLayout(resources)
        resources_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.memory = NumberSlider(
            minimum=MIN_MEMORY_MB,
            maximum=MAX_MEMORY_MB,
            step=512,
            value=spec.memory_mb,
            suffix=" MB",
        )
        self.memory.setToolTip(
            "Memoria para el servidor (heap de Java). El contenedor recibe ademas un "
            "margen para la maquina virtual."
        )
        self.memory.valueChanged.connect(self._update_memory_note)
        resources_form.addRow("Memoria (RAM)", self.memory)
        self.memory_note = hint_label("")
        resources_form.addRow("", self.memory_note)
        self._update_memory_note()

        port_row = QHBoxLayout()
        self.port = NumberBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(spec.port)
        self.port.setToolTip("Puerto por el que se conectan los jugadores (1024-65535)")
        self.port.valueChanged.connect(self._update_summary)
        port_row.addWidget(self.port)
        port_row.addStretch(1)
        resources_form.addRow("Puerto", self._wrap(port_row))
        self.port_note = hint_label("")
        resources_form.addRow("", self.port_note)
        self.port_note.setText(
            "Si el puerto esta ocupado por otro programa, elige otro antes de guardar."
        )
        content_layout.addWidget(resources)

        # ----------------------------------------------------------------- red
        network = QGroupBox("Red")
        network_form = QFormLayout(network)
        network_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lan = QCheckBox("Permitir la conexion desde la red local")
        self.lan.setChecked(spec.lan)
        network_form.addRow("", self.lan)
        network_form.addRow(
            "",
            hint_label(
                "Recuerda: Serviscraft no abre puertos en el cortafuegos. "
                "La consola RCON siempre queda limitada a este equipo."
            ),
        )
        content_layout.addWidget(network)
        content_layout.addStretch(1)

        self.version_combo.currentTextChanged.connect(self._on_version_changed)
        self._update_version_note()

        self.summary = QLabel("")
        self.summary.setObjectName("SectionTitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("Guardar y recrear", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("accent", "true")
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self._on_accept)
        layout.addWidget(buttons)

        self._update_summary()

    @staticmethod
    def _wrap(layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _mark_java_manual(self) -> None:
        """El usuario ha elegido Java a mano: no lo pisamos al cambiar de version."""
        self._java_manual = True

    def _on_version_changed(self) -> None:
        if not hasattr(self, "java_combo"):
            return
        version = self.version_combo.currentText().strip() or "latest"
        recommended = self.spec.java_tag if version == self.spec.version else recommended_java_tag(version)
        if not self._java_manual and self.java_combo.currentText() != recommended:
            self.java_combo.blockSignals(True)
            self.java_combo.setCurrentText(recommended)
            self.java_combo.blockSignals(False)
        self._update_version_note()
        self._update_summary()

    def _update_version_note(self) -> None:
        if not hasattr(self, "version_combo"):
            return
        version = self.version_combo.currentText().strip() or "latest"
        recommended = recommended_java_tag(version)
        if version == self.spec.version:
            self.version_note.setText(f"Version actual. Java recomendado: {recommended}.")
            return
        self.version_note.setText(
            f"Cambiaras de {self.spec.version} a {version}. Se recreara el contenedor; "
            f"el mundo y el contenido se conservan. Si vuelves a una version anterior, "
            f"haz antes una copia de seguridad: los mundos no siempre son compatibles. "
            f"Java recomendado: {recommended}."
        )

    def _load_versions(self) -> None:
        if self.runner is None:
            return
        self.load_versions_button.setEnabled(False)
        self.load_versions_button.setText("Consultando...")

        def work(*, context):
            context.progress("Consultando las versiones disponibles...")
            return fetch_versions()

        def done(versions) -> None:
            self.load_versions_button.setEnabled(True)
            self.load_versions_button.setText("Actualizar lista...")
            current = self.version_combo.currentText()
            self.version_combo.clear()
            self.version_combo.addItems(version_choices(versions))
            index = self.version_combo.findText(current)
            if index >= 0:
                self.version_combo.setCurrentIndex(index)
            elif current:
                # La version actual ya no aparece en la lista de Mojang (raro,
                # pero posible con una version muy antigua): se conserva.
                self.version_combo.insertItem(0, current)
                self.version_combo.setCurrentIndex(0)

        def failed(message: str, details: str) -> None:
            self.load_versions_button.setEnabled(True)
            self.load_versions_button.setText("Actualizar lista...")
            show_error(
                self,
                "No se pudo consultar la lista de versiones",
                "Se mantiene la lista que ya habia en el desplegable.\n\n" + message,
                details,
            )

        self.runner.submit("Consultando versiones", work, on_finished=done, on_failed=failed)

    def _update_memory_note(self) -> None:
        memory = self.memory.value()
        overhead = jvm_overhead_mb(self.spec.type)
        self.memory_note.setText(
            f"{format_bytes(memory * 1024 * 1024)} de heap; el contenedor tendra un limite de "
            f"{format_bytes((memory + overhead) * 1024 * 1024)}."
        )
        self._update_summary()

    def _update_summary(self) -> None:
        try:
            memory = self.memory.value()
            port = self.port.value()
        except AttributeError:  # pragma: no cover - durante la construccion
            return
        scope = "red local" if self.lan.isChecked() else "solo este equipo"
        version = self.version_combo.currentText().strip() or "latest"
        self.summary.setText(
            f"{self.name.text().strip() or self.spec.name} · {self.spec.type.label} {version} · "
            f"{format_bytes(memory * 1024 * 1024)} · puerto {port} · {scope}"
        )

    def _on_accept(self) -> None:
        try:
            name = validate_name(self.name.text())
            memory = validate_memory_mb(self.memory.value())
            version = validate_minecraft_version(self.version_combo.currentText().strip() or "latest")
            java_tag = validate_java_tag(self.java_combo.currentText())
            port = validate_port(self.port.value(), reserved=self.manager.store.used_ports(exclude=self.spec.id))
        except ValidationError as exc:
            show_error(self, "Revisa los datos", exc.message)
            return
        if port != self.spec.port:
            ok, message = self.manager.check_port_available(port, exclude=self.spec.id)
            if not ok:
                show_error(self, "Puerto no disponible", message)
                return
        if version != self.spec.version and not confirm(
            self,
            "Cambiar la version de Minecraft",
            f"El servidor pasara de la version {self.spec.version} a la {version}.\n\n"
            "El mundo y el contenido se conservan, pero los mundos no siempre son "
            "compatibles entre versiones. Si vuelves a una version anterior, haz antes "
            "una copia de seguridad.\n\n¿Continuar?",
            confirm_label="Cambiar version",
        ):
            return
        self._values = {
            "name": name,
            "memory_mb": memory,
            "port": port,
            "lan": self.lan.isChecked(),
            "version": version,
            "java_tag": java_tag,
        }
        self.accept()

    def values(self) -> dict:
        return getattr(self, "_values", {})


class PreferencesDialog(QDialog):
    """Preferencias globales de la aplicacion."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Preferencias de Serviscraft")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        engine = QGroupBox("Motor de contenedores")
        engine_form = QFormLayout(engine)
        self.engine_binary = QLineEdit(config.engine_binary)
        engine_form.addRow("Ejecutable", self.engine_binary)
        self.image = QLineEdit(config.image)
        engine_form.addRow("Imagen OCI", self.image)
        self.java_tag = QComboBox()
        self.java_tag.addItems(list(JAVA_TAGS))
        self.java_tag.setCurrentText(config.default_java_tag)
        engine_form.addRow("Java por defecto", self.java_tag)
        self.userns = QCheckBox("Mapear el usuario del host dentro del contenedor (recomendado)")
        self.userns.setChecked(config.userns_keep_id)
        engine_form.addRow("", self.userns)
        engine_form.addRow(
            "",
            hint_label(
                "Serviscraft usa siempre Podman en modo rootless, sin sudo y sin exponer la API "
                "por TCP."
            ),
        )
        layout.addWidget(engine)

        behaviour = QGroupBox("Comportamiento")
        behaviour_form = QFormLayout(behaviour)
        self.default_memory = NumberBox()
        self.default_memory.setRange(MIN_MEMORY_MB, MAX_MEMORY_MB)
        self.default_memory.setSingleStep(512)
        self.default_memory.setValue(config.default_memory_mb)
        self.default_memory.setSuffix(" MB")
        behaviour_form.addRow("Memoria por defecto", self.default_memory)

        self.default_port = NumberBox()
        self.default_port.setRange(1024, 65535)
        self.default_port.setValue(config.default_port)
        behaviour_form.addRow("Puerto por defecto", self.default_port)

        self.stop_timeout = NumberBox()
        self.stop_timeout.setRange(10, 600)
        self.stop_timeout.setValue(config.stop_timeout_s)
        self.stop_timeout.setSuffix(" s")
        self.stop_timeout.setToolTip("Tiempo de espera para que el servidor guarde el mundo al apagarse")
        behaviour_form.addRow("Espera al detener", self.stop_timeout)

        self.stats_interval = NumberBox()
        self.stats_interval.setRange(1000, 60000)
        self.stats_interval.setSingleStep(500)
        self.stats_interval.setValue(config.stats_interval_ms)
        self.stats_interval.setSuffix(" ms")
        behaviour_form.addRow("Actualizar estadisticas cada", self.stats_interval)

        self.console_tail = NumberBox()
        self.console_tail.setRange(50, 5000)
        self.console_tail.setValue(config.console_tail_lines)
        behaviour_form.addRow("Lineas de consola al abrir", self.console_tail)

        self.warn_orphans = QCheckBox("Avisar si quedaron servidores en ejecucion al arrancar")
        self.warn_orphans.setChecked(config.warn_orphan_containers)
        behaviour_form.addRow("", self.warn_orphans)

        self.debug = QCheckBox("Registro detallado (depuracion)")
        self.debug.setChecked(config.debug_logging)
        behaviour_form.addRow("", self.debug)
        layout.addWidget(behaviour)

        # ------------------------------------------------------------ copias
        backups = QGroupBox("Copias de seguridad")
        backups_form = QFormLayout(backups)

        self.safety_backup = QCheckBox("Crear una copia antes de restaurar otra")
        self.safety_backup.setChecked(config.safety_backup_before_restore)
        backups_form.addRow("", self.safety_backup)

        self.stop_backup = QCheckBox("Copiar cada servidor automaticamente al detenerlo")
        self.stop_backup.setChecked(config.backup_on_stop)
        self.stop_backup.setToolTip(
            "Se copia justo despues de apagarse el servidor, cuando el mundo ya esta guardado"
        )
        backups_form.addRow("", self.stop_backup)

        self.scheduled_backup = NumberBox()
        self.scheduled_backup.setRange(0, 1440)
        self.scheduled_backup.setSingleStep(30)
        self.scheduled_backup.setValue(config.scheduled_backup_minutes)
        self.scheduled_backup.setSuffix(" min")
        self.scheduled_backup.setSpecialValueText("desactivada")
        self.scheduled_backup.setToolTip("Copia periodica de los servidores que esten en ejecucion")
        backups_form.addRow("Copia automatica cada", self.scheduled_backup)

        self.automatic_keep = NumberBox()
        self.automatic_keep.setRange(0, 200)
        self.automatic_keep.setValue(config.automatic_backup_keep)
        self.automatic_keep.setSpecialValueText("conservar todas")
        self.automatic_keep.setToolTip(
            "Se guardan las N copias automaticas mas recientes, contando juntas las de «al detener» "
            "y las programadas. Las copias que crees tu a mano nunca se borran."
        )
        backups_form.addRow("Conservar copias automaticas", self.automatic_keep)

        backups_form.addRow(
            "",
            hint_label(
                "Cada servidor guarda sus copias en su propia carpeta:\n"
                f"{paths.servers_dir()}/<identificador-del-servidor>/backups/\n"
                "Puedes abrirla desde el menu «Servidor» o desde la pestana «Copias»."
            ),
        )
        layout.addWidget(backups)

        layout.addWidget(
            hint_label(
                "Los servidores nunca se inician automaticamente al abrir la aplicacion: "
                "se mantienen detenidos hasta que tu lo decidas."
            )
        )

        buttons = QDialogButtonBox()
        save = buttons.addButton("Guardar", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("accent", "true")
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        save.clicked.connect(self._on_accept)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        from ..core.validation import validate_image, validate_java_tag

        try:
            image = validate_image(self.image.text())
            java_tag = validate_java_tag(self.java_tag.currentText())
        except ValidationError as exc:
            show_error(self, "Revisa los datos", exc.message)
            return
        self.config.image = image
        self.config.engine_binary = self.engine_binary.text().strip() or "podman"
        self.config.default_java_tag = java_tag
        self.config.default_memory_mb = self.default_memory.value()
        self.config.default_port = self.default_port.value()
        self.config.stop_timeout_s = self.stop_timeout.value()
        self.config.stats_interval_ms = self.stats_interval.value()
        self.config.console_tail_lines = self.console_tail.value()
        self.config.safety_backup_before_restore = self.safety_backup.isChecked()
        self.config.backup_on_stop = self.stop_backup.isChecked()
        self.config.scheduled_backup_minutes = self.scheduled_backup.value()
        self.config.automatic_backup_keep = self.automatic_keep.value()
        self.config.warn_orphan_containers = self.warn_orphans.isChecked()
        self.config.userns_keep_id = self.userns.isChecked()
        self.config.debug_logging = self.debug.isChecked()
        try:
            self.config.save()
        except OSError as exc:
            show_error(self, "No se pudieron guardar las preferencias", str(exc))
            return
        self.accept()
