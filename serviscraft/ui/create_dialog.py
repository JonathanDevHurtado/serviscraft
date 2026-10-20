"""Asistente de creacion de servidores."""

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
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.appconfig import AppConfig
from ..core.errors import ServiscraftError, ValidationError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager, jvm_overhead_mb
from ..core.models import ServerType, format_bytes
from ..core.paths import JAVA_TAGS, MAX_MEMORY_MB, MIN_MEMORY_MB
from ..core.validation import validate_memory_mb, validate_minecraft_version, validate_name, validate_port
from ..core.versions import FALLBACK_VERSIONS, fetch_versions, recommended_java_tag, version_choices
from .common import NumberBox, NumberSlider, hint_label, make_button
from .dialogs import show_error
from .tasks import TaskRunner

logger = get_logger("ui.create")


class CreateServerDialog(QDialog):
    """Recoge los datos de un servidor nuevo y los valida antes de crearlo."""

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
        self._java_manual = False
        self._modpack = None
        self.setWindowTitle("Nuevo servidor de Minecraft")
        self.setMinimumWidth(620)

        # El contenido va en un area desplazable para que el cuadro quepa en
        # pantallas bajas o en una ventana con mosaico automatico; los botones de
        # abajo se quedan siempre a la vista.
        contenido = QWidget(self)
        layout = QVBoxLayout(contenido)
        layout.setSpacing(12)
        layout.addWidget(
            hint_label(
                "Serviscraft descargara la imagen del servidor y creara un contenedor rootless "
                "con Podman. El servidor se creara detenido: podras iniciarlo cuando quieras."
            )
        )

        # ------------------------------------------------------------- basico
        basic = QGroupBox("Datos del servidor")
        form = QFormLayout(basic)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Mi servidor")
        self.name.setMaxLength(32)
        form.addRow("Nombre", self.name)

        self.type_combo = QComboBox()
        for server_type in ServerType:
            self.type_combo.addItem(f"{server_type.label}", server_type.value)
        # Paper es la opcion recomendada para empezar (como en Aternos):
        # admite pluguins y funciona con las versiones modernas.
        self.type_combo.setCurrentIndex(self.type_combo.findData(ServerType.PAPER.value))
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Tipo", self.type_combo)

        self.type_description = hint_label("")
        form.addRow("", self.type_description)

        version_row = QHBoxLayout()
        self.version_combo = QComboBox()
        # Sin texto libre: la version se elige de la lista (asi no se cuelan
        # valores que la imagen no entiende). «latest» es la primera opcion.
        self.version_combo.addItems(list(FALLBACK_VERSIONS))
        self.version_combo.setCurrentText("latest")
        self.version_combo.setToolTip(
            "Version de Minecraft. «latest» deja que la imagen use la ultima estable."
        )
        version_row.addWidget(self.version_combo, 1)
        self.load_versions_button = make_button(
            "Actualizar lista...",
            icon_names=("view-refresh", "download"),
            tooltip="Consultar la lista oficial de versiones de Mojang y rellenar la lista",
        )
        self.load_versions_button.clicked.connect(self._load_versions)
        version_row.addWidget(self.load_versions_button)
        form.addRow("Version de Minecraft", self._wrap(version_row))

        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(60)
        self.notes.setPlaceholderText("Notas opcionales (por ejemplo: servidor para amigos)")
        form.addRow("Notas", self.notes)
        layout.addWidget(basic)

        # ------------------------------------------------------------ modpack
        modpack_box = QGroupBox("Modpack (opcional)")
        modpack_form = QFormLayout(modpack_box)
        modpack_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.modpack_check = QCheckBox("Usar un modpack de Modrinth (trae sus mods y su cargador)")
        self.modpack_check.toggled.connect(self._on_modpack_toggled)
        modpack_form.addRow("", self.modpack_check)

        modpack_row = QHBoxLayout()
        self.modpack_button = make_button(
            "Elegir modpack...",
            icon_names=("system-search", "package-x-generic"),
            tooltip="Buscar modpacks en Modrinth (por ejemplo Cobblemon, Better MC)",
        )
        self.modpack_button.setEnabled(False)
        self.modpack_button.clicked.connect(self._choose_modpack)
        modpack_row.addWidget(self.modpack_button)
        modpack_row.addStretch(1)
        modpack_form.addRow("", self._wrap(modpack_row))

        self.modpack_label = hint_label("Ningun modpack elegido. Si no marcas la casilla, eliges el tipo arriba.")
        modpack_form.addRow("", self.modpack_label)
        layout.addWidget(modpack_box)

        # ----------------------------------------------------------- recursos
        resources = QGroupBox("Recursos y red")
        resources_form = QFormLayout(resources)
        resources_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        memory_row = QHBoxLayout()
        self.memory = NumberSlider(
            minimum=MIN_MEMORY_MB,
            maximum=MAX_MEMORY_MB,
            step=512,
            value=config.default_memory_mb,
            suffix=" MB",
        )
        self.memory.valueChanged.connect(self._update_summary)
        memory_row.addWidget(self.memory, 1)
        self.memory_label = QLabel("")
        self.memory_label.setObjectName("Hint")
        memory_row.addWidget(self.memory_label)
        resources_form.addRow("Memoria (RAM)", self._wrap(memory_row))

        self.memory_container = hint_label("")
        resources_form.addRow("", self.memory_container)

        port_row = QHBoxLayout()
        self.port = NumberBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(config.default_port)
        self.port.setMinimumWidth(112)
        self.port.valueChanged.connect(self._update_summary)
        port_row.addWidget(self.port)
        suggest = make_button("Buscar puerto libre", icon_names=("system-search",))
        suggest.clicked.connect(self._suggest_port)
        port_row.addWidget(suggest)
        port_row.addStretch(1)
        resources_form.addRow("Puerto", self._wrap(port_row))
        self.port_status = hint_label("")
        resources_form.addRow("", self.port_status)
        self.port.valueChanged.connect(self._check_port)

        self.lan = QCheckBox("Permitir la conexion desde la red local")
        self.lan.setChecked(True)
        self.lan.setToolTip("Publica el puerto en todas las interfaces del equipo")
        self.lan.toggled.connect(self._update_summary)
        resources_form.addRow("", self.lan)
        resources_form.addRow(
            "",
            hint_label(
                "Serviscraft no modifica el cortafuegos. Si el servidor debe ser accesible desde "
                "otros equipos, tendras que abrir el puerto tu mismo (por ejemplo con firewalld)."
            ),
        )

        self.java_combo = QComboBox()
        self.java_combo.addItems(list(JAVA_TAGS))
        self.java_combo.setCurrentText(config.default_java_tag)
        self.java_combo.activated.connect(self._mark_java_manual)
        resources_form.addRow("Java", self.java_combo)
        self.java_note = hint_label("")
        resources_form.addRow("", self.java_note)

        self.bedrock = QCheckBox("Tambien jugadores de Bedrock (movil, tablet, consola)")
        self.bedrock.setToolTip(
            "Instala los pluguins Geyser y Floodgate y abre el puerto UDP 19132.\n"
            "Solo esta disponible para servidores Paper (o modpacks con pluguins)."
        )
        self.bedrock.toggled.connect(self._update_summary)
        resources_form.addRow("", self.bedrock)
        self.bedrock_note = hint_label(
            "Los jugadores de movil o consola entran por Geyser. El resto de jugadores "
            "no nota nada: siguen entrando por Java."
        )
        resources_form.addRow("", self.bedrock_note)
        layout.addWidget(resources)

        # ------------------------------------------------------------ resumen
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
        ventana.setSpacing(12)
        ventana.addWidget(scroll, 1)

        buttons = QDialogButtonBox()
        self.create_button = buttons.addButton("Crear servidor", QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setProperty("accent", "true")
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        self.create_button.clicked.connect(self._on_accept)
        ventana.addWidget(buttons)

        self._on_type_changed()
        self.version_combo.currentTextChanged.connect(self._on_version_changed)
        self._on_version_changed()
        self._update_summary()
        # La comprobacion inicial del puerto necesita que el boton ya exista
        # (``_check_port`` lo habilita o lo deshabilita).
        self._check_port()
        self.name.setFocus()

    # ============================================================== ayudas
    @staticmethod
    def _wrap(layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    @property
    def server_type(self) -> ServerType:
        return ServerType.from_value(self.type_combo.currentData())

    def _bedrock_activo(self) -> bool:
        """Bedrock solo tiene sentido (y solo se puede marcar) en Paper."""
        return self.server_type.supports_plugins and self.bedrock.isChecked()

    def _mark_java_manual(self) -> None:
        """El usuario ha elegido Java a mano: no lo pisamos al cambiar de version."""
        self._java_manual = True

    # ================================================================ modpack
    def _on_modpack_toggled(self, enabled: bool) -> None:
        """Activar el modpack fija el tipo de servidor en Modrinth."""
        self.modpack_button.setEnabled(enabled)
        if enabled:
            index = self.type_combo.findData(ServerType.MODRINTH.value)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            # El tipo lo fija el modpack: no se cambia a mano mientras este activo.
            self.type_combo.setEnabled(False)
            self.modpack_label.setText(
                "Elige el modpack con el boton «Elegir modpack...». "
                "La primera descarga puede tardar: la imagen instala el pack al iniciar el servidor."
            )
        else:
            self._modpack = None
            self.type_combo.setEnabled(True)
            self.version_combo.setEnabled(True)
            self.load_versions_button.setEnabled(True)
            index = self.type_combo.findData(ServerType.PAPER.value)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            self.modpack_label.setText("Ningun modpack elegido. Si no marcas la casilla, eliges el tipo arriba.")
        self._update_summary()

    def _choose_modpack(self) -> None:
        from .modpack_dialog import ModpackDialog

        dialog = ModpackDialog(self.runner, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        plan = dialog.values()
        if plan is None:
            return
        self._modpack = plan
        # La version de Minecraft la fija el pack: se muestra pero no se edita.
        self.version_combo.setCurrentText(plan.minecraft_version)
        self.version_combo.setEnabled(False)
        self.load_versions_button.setEnabled(False)
        self.modpack_label.setText(
            f"Modpack «{plan.title or plan.slug}» {plan.version_number}: "
            f"cargador {plan.loader}, Minecraft {plan.minecraft_version}."
        )
        self._update_summary()

    def _on_version_changed(self) -> None:
        if not hasattr(self, "java_combo"):
            return
        recommended = recommended_java_tag(self.version_combo.currentText().strip() or "latest")
        if not self._java_manual and self.java_combo.currentText() != recommended:
            self.java_combo.blockSignals(True)
            self.java_combo.setCurrentText(recommended)
            self.java_combo.blockSignals(False)
        self._update_summary()

    def _on_type_changed(self) -> None:
        server_type = self.server_type
        self.type_description.setText(server_type.description)
        if server_type in {ServerType.VANILLA, ServerType.PAPER}:
            # Vanilla y Paper modernos funcionan bien con Java 21.
            if self.java_combo.currentText() == "java8":
                self.java_combo.setCurrentText(self.config.default_java_tag)
        # Bedrock necesita Geyser, que solo existe para Paper.
        soporta_bedrock = server_type.supports_plugins
        if not soporta_bedrock and self.bedrock.isChecked():
            self.bedrock.setChecked(False)
        self.bedrock.setEnabled(soporta_bedrock)
        self.bedrock_note.setVisible(soporta_bedrock)
        self._update_summary()

    def _update_summary(self) -> None:
        memory = self.memory.value()
        self.memory_label.setText(f"= {format_bytes(memory * 1024 * 1024)}")
        overhead = jvm_overhead_mb(self.server_type)
        self.memory_container.setText(
            f"{memory} MB de memoria para el juego mas {overhead} MB para Java: el contenedor "
            f"tendra un limite de {format_bytes((memory + overhead) * 1024 * 1024)}."
        )
        version = self.version_combo.currentText().strip() or "latest"
        scope = "red local" if self.lan.isChecked() else "solo este equipo"
        pack = ""
        if self._modpack is not None:
            pack = f" · modpack «{self._modpack.title or self._modpack.slug}»"
        bedrock = " · tambien Bedrock" if self._bedrock_activo() else ""
        self.summary.setText(
            f"{self.server_type.label} {version} · {format_bytes(memory * 1024 * 1024)} de RAM · "
            f"puerto {self.port.value()} · {scope}{pack}{bedrock}"
        )
        if hasattr(self, "java_note"):
            recommended = recommended_java_tag(version)
            current = self.java_combo.currentText()
            note = f"Java recomendado para {version}: {recommended}."
            if current != recommended:
                note += f" Ahora esta seleccionado {current}."
            self.java_note.setText(note)

    def _check_port(self) -> None:
        ok, message = self.manager.check_port_available(self.port.value())
        self.port_status.setText("" if ok else message)
        self.create_button.setEnabled(ok)

    def _suggest_port(self) -> None:
        self.port.setValue(self.manager.next_free_port(self.port.value()))

    def _load_versions(self) -> None:
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
                # La version elegida no viene en la lista oficial: se conserva
                # delante para no cambiarle la eleccion al usuario.
                self.version_combo.insertItem(0, current)
                self.version_combo.setCurrentIndex(0)

        def failed(message: str, details: str) -> None:
            self.load_versions_button.setEnabled(True)
            self.load_versions_button.setText("Actualizar lista...")
            logger.warning("No se pudieron consultar las versiones: %s", message)
            show_error(
                self,
                "No se pudo consultar la lista de versiones",
                "Se mantiene la lista que ya tenias (incluye las versiones mas usadas, "
                "desde la mas nueva hacia atras).\n\n" + message,
                details,
            )

        self.runner.submit("Consultando versiones", work, on_finished=done, on_failed=failed)

    # =============================================================== validar
    def _on_accept(self) -> None:
        try:
            self.values()
        except (ValidationError, ServiscraftError) as exc:
            message = getattr(exc, "message", str(exc))
            show_error(self, "Revisa los datos", message)
            return
        except OSError as exc:
            show_error(self, "No se pudo comprobar el puerto", str(exc))
            return
        self.accept()

    def values(self) -> dict:
        """Devuelve los valores validados del formulario."""
        name = validate_name(self.name.text())
        if self.modpack_check.isChecked() and self._modpack is None:
            raise ValidationError(
                "modpack",
                "Has activado la casilla del modpack: pulsa «Elegir modpack...» o desmarca la opcion.",
            )
        if self._modpack is not None:
            server_type = ServerType.MODRINTH
            version = validate_minecraft_version(self._modpack.minecraft_version)
        else:
            server_type = self.server_type
            version = validate_minecraft_version(self.version_combo.currentText().strip() or "latest")
        memory = validate_memory_mb(self.memory.value())
        port = validate_port(self.port.value(), reserved=self.manager.store.used_ports())
        ok, message = self.manager.check_port_available(port)
        if not ok:
            raise ValidationError("port", message)
        values = {
            "name": name,
            "type": server_type,
            "version": version,
            "memory_mb": memory,
            "port": port,
            "java_tag": self.java_combo.currentText(),
            "lan": self.lan.isChecked(),
            "notes": self.notes.toPlainText().strip(),
            "bedrock": self._bedrock_activo(),
        }
        if self._modpack is not None:
            values["extra_env"] = self._modpack.extra_env()
        return values
