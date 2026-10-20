"""Panel de detalles del servidor con acciones de mantenimiento."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import appearance
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager, jvm_overhead_mb
from ..core.models import ServerSpec, ServerState, format_bytes
from .common import FlowRow, StatusBadge, hint_label, make_button
from .dialogs import confirm, show_error, show_info
from .mc_icons import PlatformBadge
from .server_preview import McListEntry, icon_pixmap
from .tasks import TaskRunner

logger = get_logger("ui.details")


def _make_form(parent: QWidget | None) -> QFormLayout:
    """Crea un formulario cuyas etiquetas de valor se estiran y ajustan bien.

    Importante: el estilo Breeze usa ``ExpandingFieldsGrow``, que **no** estira los
    ``QLabel`` (su politica es ``Preferred``). Con ese ajuste, una etiqueta con
    ``setWordWrap(True)`` conserva la altura de una sola linea y su texto se
    superpone a la fila siguiente. ``AllNonFixedFieldsGrow`` la estira al ancho de
    la columna, de modo que Qt calcula la altura real del texto ajustado.
    """
    form = QFormLayout(parent)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return form


class DetailsPanel(QWidget):
    """Ficha tecnica del servidor y operaciones de mantenimiento."""

    settings_requested = Signal(str)
    appearance_requested = Signal(str)
    state_changed = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._state = ServerState.MISSING
        self._labels: dict[str, QLabel | QLineEdit] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # --------------------------------------------------------------- ficha
        identity = QGroupBox("Identidad")
        identity_form = _make_form(identity)
        for key, label in (
            ("name", "Nombre"),
            ("id", "Identificador"),
            ("type", "Tipo"),
            ("version", "Minecraft"),
            ("image", "Imagen"),
            ("java", "Java"),
        ):
            self._add_row(identity_form, key, label)
        self.badge = StatusBadge()
        identity_form.addRow("Estado", self.badge)
        # Insignia con los bloques: cesped (Java) y piedra (Bedrock).
        self.platform = PlatformBadge(14)
        identity_form.addRow("Plataforma", self.platform)
        layout.addWidget(identity)

        # --------------------------------------------------------------- aspecto
        aspect_box = QGroupBox("Aspecto en la lista de Minecraft")
        aspect_layout = QVBoxLayout(aspect_box)
        # La misma entrada que pinta el juego, para verla antes de entrar.
        self.mc_preview = McListEntry(scale=1)
        aspect_layout.addWidget(self.mc_preview)
        aspect_row = QHBoxLayout()
        self.appearance_button = make_button(
            "Cambiar aspecto...",
            icon_names=("preferences-desktop-theme", "image-x-generic"),
            tooltip="Elegir el icono y el mensaje con colores que se ven en la lista de Minecraft",
        )
        self.appearance_button.clicked.connect(
            lambda: self._spec and self.appearance_requested.emit(self._spec.id)
        )
        aspect_row.addWidget(self.appearance_button)
        aspect_row.addStretch(1)
        aspect_layout.addLayout(aspect_row)
        self.appearance_note = hint_label("")
        aspect_layout.addWidget(self.appearance_note)
        layout.addWidget(aspect_box)

        # ----------------------------------------------------------- recursos
        resources = QGroupBox("Recursos y puertos")
        # El formulario y el boton van en el mismo QVBoxLayout, no dentro del
        # formulario: una fila con dos columnas suma el ancho de la etiqueta mas
        # el del boton, y en una ventana estrecha eso empujaba el panel fuera de
        # la ventana. Como fila aparte, el minimo es el mayor de los dos.
        resources_layout = QVBoxLayout(resources)
        resources_form = _make_form(None)
        resources_layout.addLayout(resources_form)
        for key, label in (
            ("memory", "Memoria (heap)"),
            ("memory_limit", "Limite"),
            ("port", "Puerto"),
            ("rcon", "Consola (local)"),
            ("bedrock", "Bedrock"),
            ("address", "Direccion"),
            ("disk", "En disco"),
        ):
            self._add_row(resources_form, key, label)

        copy_button = make_button("Copiar direccion", icon_names=("edit-copy",))
        copy_button.clicked.connect(self._copy_address)
        resources_layout.addWidget(copy_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(resources)

        # --------------------------------------------------------------- tiempos
        times = QGroupBox("Fechas y rutas")
        times_form = _make_form(times)
        for key, label in (
            ("created", "Creado"),
            ("started", "Arranque"),
            ("container", "Contenedor"),
            ("data_path", "Datos"),
            ("backups_path", "Copias"),
        ):
            self._add_row(times_form, key, label, selectable=True)
        layout.addWidget(times)

        # --------------------------------------------------------------- notas
        notes_box = QGroupBox("Notas")
        notes_layout = QVBoxLayout(notes_box)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Recordatorios sobre este servidor (versiones, mods pendientes...)")
        self.notes.setFixedHeight(90)
        notes_layout.addWidget(self.notes)
        notes_row = QHBoxLayout()
        save_notes = make_button("Guardar notas", icon_names=("document-save",))
        save_notes.clicked.connect(self._save_notes)
        notes_row.addWidget(save_notes)
        notes_row.addStretch(1)
        notes_layout.addLayout(notes_row)
        layout.addWidget(notes_box)

        # ------------------------------------------------------------ acciones
        actions = QGroupBox("Mantenimiento")
        actions_layout = QVBoxLayout(actions)
        # Dos filas que se envuelven al estrecharse la ventana.
        self.maintenance_row1 = FlowRow()
        edit_button = make_button("Editar ajustes...", icon_names=("document-edit", "configure"),
                                  tooltip="Cambiar nombre, memoria, puerto o acceso desde la red")
        edit_button.clicked.connect(lambda: self._spec and self.settings_requested.emit(self._spec.id))
        self.maintenance_row1.add(edit_button)

        recreate_button = make_button("Recrear contenedor", icon_names=("view-refresh", "system-reboot"),
                                      tooltip="Vuelve a crear el contenedor con la configuracion actual")
        recreate_button.clicked.connect(self._recreate)
        self.maintenance_row1.add(recreate_button)
        actions_layout.addWidget(self.maintenance_row1)

        self.maintenance_row2 = FlowRow()
        data_button = make_button("Abrir carpeta de datos", icon_names=("folder-open",))
        data_button.clicked.connect(lambda: self._open_path("data"))
        self.maintenance_row2.add(data_button)
        backups_button = make_button("Abrir carpeta de copias", icon_names=("folder-", "archive-insert-directory"))
        backups_button.clicked.connect(lambda: self._open_path("backups"))
        self.maintenance_row2.add(backups_button)
        log_button = make_button(
            "Ver registro",
            icon_names=("text-x-generic",),
            tooltip="Abrir el registro de Serviscraft",
        )
        log_button.clicked.connect(self._open_log)
        self.maintenance_row2.add(log_button)
        actions_layout.addWidget(self.maintenance_row2)

        actions_layout.addWidget(
            hint_label(
                "Serviscraft nunca ejecuta Podman con sudo y no abre puertos en el cortafuegos. "
                "Si expones el servidor en la red, revisa tu cortafuegos por tu cuenta."
            )
        )
        layout.addWidget(actions)
        layout.addStretch(1)

        self.set_server(None, ServerState.MISSING)

    # ================================================================ ayudas
    def _wrap(self, layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _add_row(self, form: QFormLayout, key: str, label: str, *, selectable: bool = False) -> None:
        if selectable:
            # Una ruta larga en una QLabel obliga a ensanchar toda la ficha: la
            # etiqueta no puede partir el texto y su ancho minimo es el de la
            # ruta entera. Un campo de solo lectura se desplaza, se puede
            # seleccionar y no impone ese ancho.
            campo = QLineEdit()
            campo.setReadOnly(True)
            campo.setFrame(False)
            campo.setStyleSheet("QLineEdit { background: transparent; border: 0; padding: 0; }")

            def _sincronizar(texto: str) -> None:
                campo.setCursorPosition(0)
                campo.setToolTip(texto)

            campo.textChanged.connect(_sincronizar)
            value: QLabel | QLineEdit = campo
        else:
            value = QLabel("—")
            value.setWordWrap(True)
        form.addRow(label, value)
        self._labels[key] = value

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, state: ServerState) -> None:
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._state != state
        self._spec = spec
        self._state = state
        if spec is None:
            for label in self._labels.values():
                label.setText("—")
            self.badge.set_state(ServerState.MISSING)
            self.platform.set_spec(None)
            self.notes.setPlainText("")
            self.notes.setEnabled(False)
            self.mc_preview.set_data("", "", icon_pixmap(b"", 32))
            self.appearance_note.setText("")
            return
        self.notes.setEnabled(True)
        self.badge.set_state(state)
        self.platform.set_spec(spec)
        self._labels["name"].setText(spec.name)
        self._labels["id"].setText(spec.id)
        self._labels["type"].setText(f"{spec.type.label} — {spec.type.description}")
        self._labels["version"].setText(spec.version)
        self._labels["image"].setText(spec.image_ref)
        self._labels["java"].setText(spec.java_tag)
        self._labels["memory"].setText(f"{spec.memory_label} (JVM -Xmx)")
        self._labels["memory_limit"].setText(
            f"{format_bytes((spec.memory_mb + jvm_overhead_mb(spec.type)) * 1024 * 1024)} asignados al contenedor"
        )
        self._labels["port"].setText(str(spec.port))
        self._labels["rcon"].setText(
            f"{spec.rcon_port} — publicado solo en 127.0.0.1, protegido con contrasena"
        )
        self._labels["bedrock"].setText(
            f"activados — movil, tablet y consola entran por el puerto UDP {spec.bedrock_port}"
            if spec.bedrock_enabled
            else "no — solo entran jugadores de Java"
        )
        if spec.lan:
            address = f"{self.manager.host_lan_ip()}:{spec.port}"
            self._labels["address"].setText(f"{address} (red local) — tambien localhost:{spec.port}")
        else:
            self._labels["address"].setText(f"localhost:{spec.port} (solo este equipo)")
        self._labels["created"].setText(_format_date(spec.created_at))
        self._labels["started"].setText(_format_date(spec.last_started_at) if spec.last_started_at else "nunca")
        self._labels["container"].setText(spec.container_name)
        self._labels["data_path"].setText(str(self.manager.store.data_dir(spec.id)))
        self._labels["backups_path"].setText(str(self.manager.store.backups_dir(spec.id)))
        if self.notes.toPlainText() != spec.notes:
            self.notes.setPlainText(spec.notes)
        if cambio_estado:
            self.refresh_disk_usage()
            self.refresh_appearance()

    def set_state(self, state: ServerState) -> None:
        self._state = state
        self.badge.set_state(state)

    def refresh_appearance(self) -> None:
        """Lee el icono y la descripcion con los que se ve el servidor."""
        if self._spec is None:
            return
        spec = self._spec
        self.mc_preview.set_data(
            spec.name, "", icon_pixmap(self.manager.server_icon(spec.id), 32)
        )

        def work(*, context):
            return self.manager.motd(spec.id)

        def done(motd: str) -> None:
            if self._spec is None or self._spec.id != spec.id:
                return
            self.mc_preview.set_data(spec.name, motd)
            if appearance.strip_codes(motd).strip():
                self.appearance_note.setText(
                    "Asi lo ven tus amigos antes de entrar. Minecraft lee la imagen y la "
                    "descripcion al arrancar: el cambio se aplica al reiniciar el servidor."
                )
            else:
                self.appearance_note.setText(
                    "Todavia no tiene descripcion propia. Ponle una (con colores) para "
                    "distinguirlo de otros servidores en la lista."
                )

        self.runner.submit(
            "Leyendo el aspecto del servidor",
            work,
            on_finished=done,
            on_failed=lambda _m, _d: None,
            track_busy=False,
        )

    def refresh_disk_usage(self) -> None:
        if self._spec is None:
            return
        spec = self._spec

        def work(*, context):
            return self.manager.total_disk_usage(spec.id)

        self.runner.submit(
            "Calculando el uso de disco",
            work,
            on_finished=self._on_disk_usage,
            on_failed=lambda _m, _d: self._labels["disk"].setText("no disponible"),
            track_busy=False,
        )

    def _on_disk_usage(self, size: int) -> None:
        if self._spec is not None:
            self._labels["disk"].setText(format_bytes(size))

    # ============================================================== acciones
    def _copy_address(self) -> None:
        from PySide6.QtWidgets import QApplication

        if self._spec is None:
            return
        address = f"localhost:{self._spec.port}"
        if self._spec.lan:
            address = f"{self.manager.host_lan_ip()}:{self._spec.port}"
        QApplication.clipboard().setText(address)
        show_info(self, "Direccion copiada", f"Se ha copiado al portapapeles:\n\n{address}")

    def _open_path(self, kind: str) -> None:
        if self._spec is None:
            return
        if kind == "data":
            path = self.manager.store.data_dir(self._spec.id)
        else:
            path = self.manager.store.backups_dir(self._spec.id)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_log(self) -> None:
        from ..core import paths

        log = paths.log_file()
        if not log.is_file():
            show_info(self, "Registro vacio", "Todavia no hay registro de la aplicacion.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log)))

    def _save_notes(self) -> None:
        if self._spec is None:
            return
        spec = self.manager.get(self._spec.id)
        spec.notes = self.notes.toPlainText()
        try:
            self.manager.store.save(spec)
        except ServiscraftError as exc:
            show_error(self, "No se pudieron guardar las notas", str(exc))
            return
        self._spec = spec
        show_info(self, "Notas guardadas", "Las notas del servidor se han guardado.")

    def _recreate(self) -> None:
        if self._spec is None:
            return
        if self._state.is_running:
            show_error(self, "Servidor en ejecucion", "Deten el servidor antes de recrear el contenedor.")
            return
        if not confirm(
            self,
            "Recrear contenedor",
            "Se volvera a crear el contenedor del servidor con la configuracion actual.\n\n"
            "Los mundos, pluguins y mods no se tocan.",
            confirm_label="Recrear",
        ):
            return
        spec = self._spec
        self.state_changed.emit()

        def work(*, context) -> str:
            context.progress("Recreando el contenedor...")
            self.manager.recreate_container(spec.id, on_progress=context.progress)
            return spec.id

        self.runner.submit(
            "Recreando contenedor",
            work,
            on_finished=lambda _r: show_info(self, "Contenedor recreado", "El contenedor se ha recreado correctamente."),
            on_failed=lambda message, details: show_error(self, "No se pudo recrear", message, details),
        )


def _format_date(value: str | None) -> str:
    if not value:
        return "—"
    text = str(value).replace("T", " ")
    return text[:19]
