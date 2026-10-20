"""Pestana de registros: lo que ha escrito el servidor, con filtro y seguimiento.

Se puede leer la salida del contenedor (cuando el servidor esta en marcha) o los
ficheros que Minecraft deja en ``logs`` y ``crash-reports``. El filtro busca
dentro de las lineas y el boton de seguimiento vuelve a leer cada dos segundos.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core import logs
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from .common import FlowRow, hint_label, make_button
from .dialogs import show_error
from .tasks import TaskRunner

logger = get_logger("ui.logs")

#: Clave del elemento «salida del contenedor» en el selector de registros.
CONTAINER_KEY = "__contenedor__"


class LogsPanel(QWidget):
    """Muestra los registros del servidor seleccionado."""

    #: El usuario quiere ver los mods que faltan (se abre la pestana de mods).
    missing_mods_requested = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._running = False
        self._texto = ""
        self._cargando = False
        #: La pestana esta a la vista (solo entonces se relee el registro).
        self._visible = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.intro = hint_label("")
        layout.addWidget(self.intro)

        # La fila de la fuente tambien envuelve: en una ventana estrecha el
        # desplegable y los botones no caben en una sola linea.
        self.source_row = FlowRow(spacing=8)
        self.source_row.add(QLabel("Registro"))
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(140)
        self.source_combo.currentIndexChanged.connect(lambda _index: self._load())
        self.source_row.add(self.source_combo)
        self.follow = QCheckBox("Seguir en vivo")
        self.follow.setToolTip(
            "Vuelve a leer el registro cada dos segundos. Desmarca la casilla para "
            "dejar de seguirlo y poder leerlo con tranquilidad."
        )
        self.follow.setChecked(True)
        self.follow.toggled.connect(self._on_follow_toggled)
        self.source_row.add(self.follow)
        self.refresh_button = make_button("Refrescar", icon_names=("view-refresh",))
        self.refresh_button.clicked.connect(self._load)
        self.source_row.add(self.refresh_button)
        layout.addWidget(self.source_row)

        self.actions = FlowRow(spacing=8)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filtrar lineas (por ejemplo error, warn o un mod)")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(lambda _texto: self._render())
        self.filter_input.setMinimumWidth(160)
        self.actions.add(self.filter_input)
        self.copy_button = make_button("Copiar todo", icon_names=("edit-copy",))
        self.copy_button.clicked.connect(self._copy_all)
        self.actions.add(self.copy_button)
        self.open_folder_button = make_button("Abrir carpeta de registros", icon_names=("folder-open",))
        self.open_folder_button.clicked.connect(self._open_folder)
        self.actions.add(self.open_folder_button)
        self.missing_button = make_button(
            "Buscar mods que faltan",
            icon_names=("system-search",),
            tooltip="Analiza el registro y abre la pestana «Mods» con lo que falta",
        )
        self.missing_button.clicked.connect(self.missing_mods_requested.emit)
        self.actions.add(self.missing_button)
        layout.addWidget(self.actions)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.view.setPlaceholderText("Aqui aparece el registro del servidor.")
        layout.addWidget(self.view, 1)

        self.status = hint_label("")
        layout.addWidget(self.status)

        self.empty = QLabel("Selecciona un servidor para ver sus registros.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self._load)

        self.set_server(None, running=False)

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._running != running
        if cambio:
            self._texto = ""
            self.view.setPlainText("")
            self.filter_input.clear()
        self._spec = spec
        self._running = running
        has_server = spec is not None
        for widget in (self.intro, self.source_row, self.actions, self.view, self.status):
            widget.setVisible(has_server)
        self.empty.setVisible(not has_server)
        if has_server and cambio_estado:
            self._fill_sources()
        elif not has_server:
            self.status.clear()
        self._sync_timer()

    def set_activo(self, activo: bool) -> None:
        """Marca la pestana como visible u oculta.

        Al ocultarla solo se para el temporizador: la casilla «Seguir en vivo»
        conserva lo que eligio el usuario, de modo que al volver a la pestana
        sigue actualizandose sin tener que activarla otra vez.
        """
        self._visible = activo
        self._sync_timer()
        if activo and self._spec is not None:
            self._load()

    def _sync_timer(self) -> None:
        if self._visible and self.follow.isChecked() and self._spec is not None:
            self.timer.start()
        else:
            self.timer.stop()

    def refresh(self) -> None:
        if self._spec is None:
            return
        self._fill_sources()

    # ================================================================ fuentes
    def _fill_sources(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        actual = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        if self._running:
            self.source_combo.addItem("Salida del contenedor", CONTAINER_KEY)
            self.intro.setText(
                f"El servidor «{spec.name}» esta en marcha: se muestra la salida del contenedor."
            )
        else:
            self.intro.setText(
                f"Registros guardados por el servidor «{spec.name}» en su carpeta de datos."
            )
        for log in logs.list_logs(self.manager.files(spec.id)):
            self.source_combo.addItem(f"{log.name} ({log.size_label})", log.relative_path)
        self.source_combo.blockSignals(False)
        if self.source_combo.count() == 0:
            self.status.setText(
                "Todavia no hay registros: se crean cuando el servidor arranca por primera vez."
            )
            self.view.setPlainText("")
            return
        index = self.source_combo.findData(actual)
        self.source_combo.blockSignals(True)
        self.source_combo.setCurrentIndex(max(0, min(index if index >= 0 else 0, self.source_combo.count() - 1)))
        self.source_combo.blockSignals(False)
        self._load()

    def _load(self) -> None:
        if self._spec is None or self._cargando:
            return
        fuente = self.source_combo.currentData()
        if fuente is None:
            return
        spec = self._spec
        self._cargando = True
        try:
            if fuente == CONTAINER_KEY:
                self._texto = self.manager.recent_logs(spec.id)
                self.status.setText("Salida del contenedor (las ultimas lineas).")
            else:
                self._texto = logs.read_log(self.manager.files(spec.id), str(fuente))
                self.status.setText(f"Registro «{fuente}».")
        except ServiscraftError as exc:
            self._texto = ""
            self.status.setText(f"No se pudo leer el registro: {exc}")
        finally:
            self._cargando = False
        self._render()

    def _render(self) -> None:
        filtro = self.filter_input.text().strip().lower()
        if not filtro:
            self.view.setPlainText(self._texto)
        else:
            lineas = [linea for linea in self._texto.splitlines() if filtro in linea.lower()]
            if lineas:
                self.view.setPlainText("\n".join(lineas))
                self.view.appendPlainText("")
                self.view.appendPlainText(f"[{len(lineas)} linea(s) con «{filtro}»]")
            else:
                self.view.setPlainText(f"Ninguna linea contiene «{filtro}».")
        barra = self.view.verticalScrollBar()
        barra.setValue(barra.maximum())

    # =============================================================== acciones
    def _on_follow_toggled(self, activo: bool) -> None:
        self._sync_timer()
        if activo and self._spec is not None:
            self._load()
        elif not activo:
            self.status.setText("Seguimiento en vivo desactivado: pulsa «Refrescar» para actualizar.")

    def _copy_all(self) -> None:
        QApplication.clipboard().setText(self.view.toPlainText())
        self.status.setText("Registro copiado al portapapeles.")

    def _open_folder(self) -> None:
        if self._spec is None:
            return
        carpeta = self.manager.files(self._spec.id).data_dir / "logs"
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            show_error(self, "No se pudo abrir la carpeta", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta)))
