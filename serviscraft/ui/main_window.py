"""Ventana principal de Serviscraft."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.appconfig import AppConfig
from ..core.backup import ORIGENES_AUTOMATICOS
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec, ServerState, ServerView, format_bytes
from .appearance_dialog import AppearanceDialog
from .backups_panel import BackupsPanel
from .common import (
    ClickableLabel,
    ElidedLabel,
    FlowRow,
    MetricBar,
    OperationBar,
    StatusBadge,
    empty_state,
    make_button,
    plural,
)
from .console_panel import ConsolePanel
from .create_dialog import CreateServerDialog
from .import_dialog import ImportServerDialog
from .details_panel import DetailsPanel
from .dialogs import ConfirmWithOptions, DetailsDialog, confirm, show_error, show_info
from .files_panel import FilesPanel
from .join_panel import JoinPanel
from .logs_panel import LogsPanel
from .mc_icons import PlatformBadge, icono_cuadro
from .mods_panel import ModsPanel
from .players_panel import PlayersPanel
from .properties_panel import PropertiesPanel
from .server_list import ServerSidebar
from .server_preview import icon_pixmap
from .settings_dialog import PreferencesDialog, ServerSettingsDialog
from .tasks import TaskRunner

logger = get_logger("ui.main")


class PaginaDesplazable(QScrollArea):
    """Pestana con barra vertical cuando el contenido no cabe a lo alto.

    Con el mosaico automatico la ventana puede quedarse con menos alto del que
    necesita una pestana (la de «Mods» es la mas larga). Si no hay barra, Qt
    comprime los paneles por debajo de su tamano minimo y los botones de una
    fila se dibujan encima del texto siguiente.

    El ancho lo manda siempre la ventana (como si no hubiera area): los paneles
    ya saben envolver sus barras y recortar sus textos con puntos suspensivos.
    El alto es el minimo que pide el panel a ese ancho (contando las barras ya
    envueltas) o el de la ventana si sobra sitio. El diseno se activa a mano
    para que funcione tambien cuando la ventana esta oculta (en las pruebas).
    """

    def __init__(self, panel: QWidget) -> None:
        super().__init__()
        self.setWidget(panel)
        self.setWidgetResizable(False)  # el tamano lo pone `_acomodar`
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        panel.setAutoFillBackground(False)
        self._acomodando = False
        panel.installEventFilter(self)

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self._acomodar()

    def eventFilter(self, objeto, evento):  # noqa: N802 - API de Qt
        if objeto is self.widget() and evento.type() in (
            QEvent.Type.LayoutRequest,
            QEvent.Type.Resize,
        ):
            self._acomodar()
        return super().eventFilter(objeto, evento)

    def _acomodar(self) -> None:
        panel = self.widget()
        if panel is None or self._acomodando:
            return
        self._acomodando = True
        try:
            ancho = max(1, self.viewport().width())
            alto_vista = max(1, self.viewport().height())
            diseno = panel.layout()
            # Primero se fija el ancho: las barras de botones (FlowRow) recalculan
            # su alto minimo al envolver. Despues se pide el alto minimo del
            # panel a ese ancho y se estira hasta la ventana si hay sitio.
            if panel.width() != ancho:
                panel.setGeometry(0, 0, ancho, panel.height())
            if diseno is not None:
                diseno.activate()
            necesario = max(panel.minimumSizeHint().height(), 1)
            alto = max(alto_vista, necesario)
            if panel.width() != ancho or panel.height() != alto:
                panel.setGeometry(0, 0, ancho, alto)
            if diseno is not None:
                diseno.activate()
        finally:
            self._acomodando = False


def envolver_en_pagina(panel: QWidget) -> PaginaDesplazable:
    """Mete un panel en su pestana desplazable a lo alto."""
    return PaginaDesplazable(panel)


class MainWindow(QMainWindow):
    """Ventana principal: lista de servidores a la izquierda y panel a la derecha."""

    engine_ready = Signal(str)

    #: Por debajo de este ancho de ventana la barra lateral se aparta sola: el
    #: gestor de ventanas con mosaico automatico puede dar a la ventana un ancho
    #: menor que la lista mas el contenido, y es peor dejar el panel sin sitio que
    #: ocultar la lista (que se recupera con el boton «Servidores» o Ctrl+B).
    _ANCHO_ESTRECHO = 640

    #: Por debajo de este ancho el icono de la cabecera se aparta: el nombre del
    #: servidor es mas importante que el adorno y con poco sitio no caben los dos.
    _ANCHO_ICONO = 760

    #: Por debajo de este ancho los botones de la cabecera bajan a su propia
    #: linea. Con la lista de servidores a la vista el panel es mas estrecho que
    #: la ventana, de ahi que el umbral sea generoso: es preferible una linea
    #: mas que un nombre de servidor sin sitio.
    _ANCHO_ACCIONES = 1000

    def __init__(self, manager: ServerManager, config: AppConfig) -> None:
        super().__init__()
        self.manager = manager
        self.config = config
        self.runner = TaskRunner(self)
        self.views: dict[str, ServerView] = {}
        self.current_id: str | None = None
        self._engine_version = ""
        self._orphans_checked = False
        # Estado de la barra lateral (visibilidad y por que esta asi).
        self._barra_lateral_visible = True
        self._barra_oculta_sola = False
        self._acciones_abajo = False
        self._barra_preferencia_usuario = False

        self.setWindowTitle("Serviscraft — Gestor de servidores de Minecraft")
        self.resize(1280, 820)
        # Minimo pequeno a proposito: los gestores de ventanas con mosaico
        # automatico (Polonium, etc.) ignoran este minimo y dan a la ventana el
        # tamano del mosaico, asi que las barras de botones se envuelven y la
        # barra lateral se aparta cuando falta ancho.
        self.setMinimumSize(480, 420)

        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

        self.runner.busy_changed.connect(self._on_busy_changed)
        self.runner.tracked_started.connect(self.operation.start)
        self.runner.task_progress.connect(self.operation.set_message)
        self.operation.cancel_requested.connect(self._cancel_operations)

        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(config.stats_interval_ms)
        self.stats_timer.timeout.connect(self._on_stats_tick)
        self.stats_timer.start()

        # Copia de seguridad programada: se configura en las preferencias.
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._on_scheduled_backup)
        self._configurar_copia_programada()

        self._refresh_tick = 0
        self._saliendo_tras_detener = False
        self._update_actions()

    # ================================================================ interfaz
    def _build_actions(self) -> None:
        self.action_new = QAction("Nuevo servidor...", self)
        self.action_new.setShortcut(QKeySequence.StandardKey.New)
        self.action_new.triggered.connect(self.create_server)

        self.action_import = QAction("Importar servidor...", self)
        self.action_import.setShortcut("Ctrl+Shift+I")
        self.action_import.setToolTip(
            "Traer un servidor de otra instalacion: su carpeta o el .zip de Aternos"
        )
        self.action_import.triggered.connect(self.import_server)

        self.action_start = QAction("Iniciar", self)
        self.action_start.setShortcut("Ctrl+Return")
        self.action_start.triggered.connect(lambda: self.start_server())

        self.action_stop = QAction("Detener", self)
        self.action_stop.setShortcut("Ctrl+Shift+Return")
        self.action_stop.triggered.connect(lambda: self.stop_server())

        self.action_restart = QAction("Reiniciar", self)
        self.action_restart.setShortcut("Ctrl+R")
        self.action_restart.triggered.connect(lambda: self.restart_server())

        self.action_stop_all = QAction("Detener todos los servidores", self)
        self.action_stop_all.triggered.connect(self.stop_all_servers)

        self.action_delete = QAction("Eliminar servidor...", self)
        self.action_delete.triggered.connect(lambda: self.delete_server())

        self.action_settings = QAction("Ajustes del servidor...", self)
        self.action_settings.triggered.connect(lambda: self.edit_server_settings())

        self.action_appearance = QAction("Aspecto del servidor...", self)
        self.action_appearance.setToolTip(
            "Cambiar la imagen y la descripcion con las que se ve el servidor en Minecraft"
        )
        self.action_appearance.triggered.connect(self.open_appearance)

        self.action_open_folder = QAction("Abrir carpeta del servidor", self)
        self.action_open_folder.triggered.connect(lambda: self.open_server_folder("data"))

        self.action_open_backups = QAction("Abrir carpeta de copias", self)
        self.action_open_backups.triggered.connect(lambda: self.open_server_folder("backups"))

        self.action_backup_all = QAction("Copiar todos los servidores ahora", self)
        self.action_backup_all.setToolTip(
            "Crea una copia de seguridad de cada servidor en ejecucion (lo mismo que hace la copia programada)"
        )
        self.action_backup_all.triggered.connect(self.backup_all_servers)

        self.action_preferences = QAction("Preferencias...", self)
        self.action_preferences.triggered.connect(self.open_preferences)

        self.action_refresh = QAction("Refrescar", self)
        self.action_refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        self.action_refresh.triggered.connect(lambda: self.refresh_servers(force=True))

        self.action_log = QAction("Ver registro de Serviscraft", self)
        self.action_log.triggered.connect(self.show_log)

        self.action_about = QAction("Acerca de Serviscraft", self)
        self.action_about.triggered.connect(self.show_about)

        self.action_quit = QAction("Salir", self)
        self.action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_quit.triggered.connect(self.close)

        self.action_sidebar = QAction("Barra lateral de servidores", self)
        self.action_sidebar.setShortcut("Ctrl+B")
        self.action_sidebar.setCheckable(True)
        self.action_sidebar.setChecked(True)
        self.action_sidebar.triggered.connect(self._alternar_barra_lateral)

    def _build_menu(self) -> None:
        bar = self.menuBar()
        archivo = bar.addMenu("&Archivo")
        archivo.addAction(self.action_new)
        archivo.addAction(self.action_import)
        archivo.addSeparator()
        archivo.addAction(self.action_preferences)
        archivo.addSeparator()
        archivo.addAction(self.action_quit)

        servidor = bar.addMenu("&Servidor")
        servidor.addAction(self.action_start)
        servidor.addAction(self.action_stop)
        servidor.addAction(self.action_restart)
        servidor.addSeparator()
        servidor.addAction(self.action_stop_all)
        servidor.addSeparator()
        servidor.addAction(self.action_settings)
        servidor.addAction(self.action_appearance)
        servidor.addAction(self.action_open_folder)
        servidor.addAction(self.action_open_backups)
        servidor.addSeparator()
        servidor.addAction(self.action_backup_all)
        servidor.addSeparator()
        servidor.addAction(self.action_delete)

        ver = bar.addMenu("&Ver")
        ver.addAction(self.action_refresh)
        ver.addAction(self.action_log)
        ver.addSeparator()
        ver.addAction(self.action_sidebar)

        ayuda = bar.addMenu("A&yuda")
        ayuda.addAction(self.action_about)

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Principal")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # Boton para recuperar la lista de servidores cuando se oculta sola.
        self.sidebar_button = make_button(
            "Servidores",
            icon_names=("view-list-details", "view-list-tree", "view-list-icons"),
            tooltip="Mostrar u ocultar la lista de servidores (Ctrl+B)",
        )
        self.sidebar_button.setCheckable(True)
        self.sidebar_button.setChecked(True)
        self.sidebar_button.toggled.connect(self._alternar_barra_lateral)
        toolbar.addWidget(self.sidebar_button)
        toolbar.addSeparator()

        toolbar.addAction(self.action_import)

        # Iniciar/Detener/Reiniciar **no** van aqui: ya estan en la cabecera del
        # servidor (a la derecha) y en el menu «Servidor». Repetirlos en la barra
        # solo llenaba la esquina superior izquierda de botones.
        toolbar.addSeparator()
        toolbar.addAction(self.action_open_folder)
        toolbar.addAction(self.action_appearance)
        welcome = QLabel("  Serviscraft — servidores de Minecraft con Podman rootless  ")
        welcome.setObjectName("Hint")
        toolbar.addSeparator()
        toolbar.addWidget(welcome)

    def _build_central(self) -> None:
        self.sidebar = ServerSidebar()
        self.sidebar.server_selected.connect(self.select_server)
        self.sidebar.create_requested.connect(self.create_server)
        self.sidebar.import_requested.connect(self.import_server)
        self.sidebar.stop_all_requested.connect(self.stop_all_servers)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty_page())
        self.stack.addWidget(self._build_server_page())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 960])

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter, 1)
        self.operation = OperationBar()
        layout.addWidget(self.operation)
        self.setCentralWidget(container)

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        title = QLabel("Bienvenido a Serviscraft")
        title.setObjectName("ServerTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(
            empty_state(
                "Trae un servidor que ya tenias (aunque venga de Aternos) o crea uno nuevo\n"
                "de Minecraft Vanilla, Paper, Fabric o Forge. Mundos en tu carpeta personal."
            )
        )
        row = QHBoxLayout()
        row.addStretch(1)
        importar = make_button(
            "Importar un servidor",
            icon_names=("document-import", "document-open"),
            accent=True,
            tooltip="Traer el mundo y los plugins de un servidor que ya existia",
        )
        importar.clicked.connect(self.import_server)
        row.addWidget(importar)
        crear = make_button("Crear uno nuevo", icon_names=("list-add",))
        crear.clicked.connect(self.create_server)
        row.addWidget(crear)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _build_server_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ------------------------------------------------------------ cabecera
        self.header = QFrame()
        self.header.setObjectName("ServerHeader")
        header_layout = QVBoxLayout(self.header)
        self._header_layout = header_layout
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(8)

        top = QHBoxLayout()
        self._header_top = top
        top.setSpacing(10)
        # Icono propio del servidor (o un marco generico): al pulsarlo se
        # cambia la imagen y la descripcion, como en un lanzador.
        self.header_icon = ClickableLabel()
        self.header_icon.setObjectName("HeaderIcon")
        self.header_icon.setFixedSize(34, 34)
        self.header_icon.setScaledContents(True)
        self.header_icon.setToolTip("Cambiar la imagen y la descripcion del servidor")
        self.header_icon.clicked.connect(self.open_appearance)
        top.addWidget(self.header_icon)
        self.header_title = ElidedLabel("Servidor")
        self.header_title.setObjectName("ServerTitle")
        top.addWidget(self.header_title)
        # Solo los bloques (sin texto): el nombre del servidor conserva su sitio
        # y el detalle de plataforma se lee en la linea de debajo.
        self.header_platform = PlatformBadge(with_text=False)
        top.addWidget(self.header_platform)
        top.addStretch(1)

        # Los botones de accion van en una fila que se envuelve: cuando la ventana
        # es estrecha (por ejemplo con un gestor de mosaico automatico como
        # Polonium) pasan a la linea siguiente en vez de recortarse.
        self.header_actions = FlowRow(spacing=10)
        self.start_button = make_button("Iniciar", icon_names=("media-playback-start", "system-run"), accent=True)
        self.start_button.clicked.connect(lambda: self.start_server())
        self.header_actions.add(self.start_button)
        self.stop_button = make_button("Detener", icon_names=("media-playback-stop", "process-stop"))
        self.stop_button.clicked.connect(lambda: self.stop_server())
        self.header_actions.add(self.stop_button)
        self.restart_button = make_button("Reiniciar", icon_names=("view-refresh", "system-reboot"))
        self.restart_button.clicked.connect(lambda: self.restart_server())
        self.header_actions.add(self.restart_button)
        self.settings_button = make_button("Ajustes", icon_names=("configure",))
        self.settings_button.clicked.connect(lambda: self.edit_server_settings())
        self.header_actions.add(self.settings_button)
        self.delete_button = make_button("Eliminar", icon_names=("edit-delete", "user-trash"), danger=True)
        self.delete_button.clicked.connect(lambda: self.delete_server())
        self.header_actions.add(self.delete_button)
        top.addWidget(self.header_actions)
        header_layout.addLayout(top)

        # El estado va en la segunda linea, junto al resumen: asi el titulo no
        # compite por el ancho con la insignia (que con «Sin iniciar» es
        # ancha) y el nombre del servidor siempre tiene sitio.
        subtitle_row = QHBoxLayout()
        subtitle_row.setSpacing(10)
        self.header_badge = StatusBadge()
        subtitle_row.addWidget(self.header_badge)
        self.header_subtitle = ElidedLabel("")
        self.header_subtitle.setObjectName("ServerSubtitle")
        subtitle_row.addWidget(self.header_subtitle, 1)
        header_layout.addLayout(subtitle_row)

        metrics = QHBoxLayout()
        metrics.setSpacing(18)
        self.cpu_bar = MetricBar("CPU", "CpuBar")
        self.ram_bar = MetricBar("Memoria", "RamBar")
        metrics.addWidget(self.cpu_bar, 1)
        metrics.addWidget(self.ram_bar, 1)
        self.metrics_extra = QLabel("")
        self.metrics_extra.setObjectName("MetricValue")
        metrics.addWidget(self.metrics_extra)
        header_layout.addLayout(metrics)
        layout.addWidget(self.header)

        # -------------------------------------------------------------- pestanas
        self.tabs = QTabWidget()
        # Con muchas pestanas y una ventana estrecha (mosaico automatico) es
        # mejor que aparezcan las flechas de desplazamiento y que cada titulo se
        # lea entero: recortar los titulos deja pestanas indistinguibles.
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.console = ConsolePanel(self.manager, self.runner)
        self.join = JoinPanel(self.manager, self.runner)
        self.mods = ModsPanel(self.manager, self.runner)
        self.properties = PropertiesPanel(self.manager, self.runner)
        self.files = FilesPanel(self.manager, self.runner)
        self.players = PlayersPanel(self.manager, self.runner)
        self.backups = BackupsPanel(self.manager, self.runner)
        self.logs = LogsPanel(self.manager, self.runner)
        self.details = DetailsPanel(self.manager, self.runner)

        self.tabs.addTab(envolver_en_pagina(self.console), "Consola")
        self.tabs.addTab(envolver_en_pagina(self.join), "Unirse")
        self.tabs.addTab(envolver_en_pagina(self.mods), "Mods")
        self.tabs.addTab(envolver_en_pagina(self.properties), "Propiedades")
        self.tabs.addTab(envolver_en_pagina(self.files), "Archivos")
        self.tabs.addTab(envolver_en_pagina(self.players), "Jugadores")
        self.tabs.addTab(envolver_en_pagina(self.backups), "Copias")
        self.tabs.addTab(envolver_en_pagina(self.logs), "Registros")
        self.tabs.addTab(envolver_en_pagina(self.details), "Detalles")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)
        self.files.files_changed.connect(lambda: self.properties.load(self._spec()))
        self.files.files_changed.connect(lambda: self.mods.refresh())
        self.properties.saved.connect(self.details.refresh_appearance)
        self.backups.changed.connect(lambda: None)
        self.mods.changed.connect(lambda: self.properties.load(self._spec()))
        self.join.changed.connect(lambda: self.refresh_servers(force=True))
        self.logs.missing_mods_requested.connect(self._open_missing_mods)
        self.details.settings_requested.connect(self._open_settings_for)
        self.details.appearance_requested.connect(self.open_appearance)
        self.details.state_changed.connect(lambda: self.refresh_servers(force=True))
        return page

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.status_engine = QLabel("Comprobando Podman...")
        bar.addWidget(self.status_engine)
        self.status_message = QLabel("")
        bar.addPermanentWidget(self.status_message)

    # ============================================== adaptacion al ancho
    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self._ajustar_barra_lateral()

    def _ajustar_barra_lateral(self) -> None:
        """Aparta la lista de servidores cuando la ventana es muy estrecha.

        El gestor de ventanas con mosaico automatico (Polonium y similares) da a
        la ventana el ancho del mosaico, que puede ser menor que el de la lista
        mas el contenido. En ese caso conviene ocultar la lista: el panel se queda
        con todo el ancho y la lista se recupera con el boton «Servidores» o
        Ctrl+B. Si el usuario la oculto o la mostro el mismo, se respeta.
        """
        if not hasattr(self, "sidebar"):
            return
        if (
            self.width() < self._ANCHO_ESTRECHO
            and self._barra_lateral_visible
            and not self._barra_preferencia_usuario
        ):
            self._barra_lateral_visible = False
            self._barra_oculta_sola = True
            self.sidebar.setVisible(False)
            self._sincronizar_boton_barra_lateral()
        elif self.width() >= self._ANCHO_ESTRECHO and self._barra_oculta_sola:
            self._barra_lateral_visible = True
            self._barra_oculta_sola = False
            self.sidebar.setVisible(True)
            self._sincronizar_boton_barra_lateral()
        if hasattr(self, "header_icon"):
            # Con poco ancho, el nombre del servidor manda: el icono (que tambien
            # abre el editor del aspecto) se aparta hasta que hay sitio.
            self.header_icon.setVisible(self.width() >= self._ANCHO_ICONO)
        if hasattr(self, "header_actions"):
            self._mover_acciones(self.width() < self._ANCHO_ACCIONES)

    def _mover_acciones(self, abajo: bool) -> None:
        """Con poco ancho, los botones de la cabecera pasan a su propia linea.

        El nombre del servidor es lo unico que identifica lo que hay en el panel:
        si los botones van a su lado se queda sin ancho y desaparece.
        """
        if abajo == self._acciones_abajo:
            return
        self._acciones_abajo = abajo
        if abajo:
            self._header_top.removeWidget(self.header_actions)
            self._header_layout.insertWidget(1, self.header_actions)
        else:
            self._header_layout.removeWidget(self.header_actions)
            self._header_top.addWidget(self.header_actions)

    def _alternar_barra_lateral(self, visible: bool) -> None:
        """Muestra u oculta la lista de servidores por decision del usuario."""
        self._barra_lateral_visible = bool(visible)
        self._barra_oculta_sola = False
        # Eleccion explicita: a partir de ahora la adaptacion automatica no la
        # cambia, para no pelearse con el usuario.
        self._barra_preferencia_usuario = True
        self.sidebar.setVisible(bool(visible))
        self._sincronizar_boton_barra_lateral()

    def _sincronizar_boton_barra_lateral(self) -> None:
        for control in (self.sidebar_button, self.action_sidebar):
            control.blockSignals(True)
            control.setChecked(self._barra_lateral_visible)
            control.blockSignals(False)

    # ================================================================ arranque
    def start(self) -> None:
        """Comprobaciones iniciales (motor y servidores huerfanos)."""
        self._check_engine()
        self.refresh_servers(force=True)

    def _check_engine(self) -> None:
        def work(*, context) -> tuple[str, bool]:
            context.progress("Comprobando Podman...")
            version = self.manager.check_engine()
            return version, self.manager.engine_rootless()

        self.runner.submit(
            "Comprobando Podman",
            work,
            on_finished=self._on_engine_ready,
            on_failed=self._on_engine_failed,
        )

    def _on_engine_ready(self, result: tuple[str, bool]) -> None:
        version, rootless = result
        self._engine_version = version
        mode = "rootless" if rootless else "sin confirmar rootless"
        self.status_engine.setText(f"Podman {version} ({mode})")
        if not rootless:
            self.status_engine.setToolTip(
                "Serviscraft espera Podman en modo rootless. Comprueba que no se ejecuta como root."
            )
        self.engine_ready.emit(version)
        self._update_actions()

    def _on_engine_failed(self, message: str, details: str) -> None:
        self.status_engine.setText("Podman no disponible")
        self.status_engine.setToolTip(message)
        logger.error("Podman no disponible: %s", message)
        show_error(
            self,
            "Podman no esta disponible",
            message
            + "\n\nServiscraft necesita Podman instalado y funcionando sin privilegios.\n"
            "En Fedora puedes instalarlo con:  sudo dnf install podman",
            details,
        )

    # ================================================================ listado
    def refresh_servers(self, *, force: bool = False) -> None:
        """Recarga la lista de servidores y sus estados."""
        def work(*, context):
            return self.manager.views()

        self.runner.submit(
            "Actualizando servidores",
            work,
            on_finished=self._on_views_ready,
            on_failed=self._on_views_failed,
            track_busy=False,
        )

    def _on_views_ready(self, views: list[ServerView]) -> None:
        self.views = {view.spec.id: view for view in views}
        self.sidebar.set_servers(views, selected=self.current_id)
        if not views:
            # Se vacian los paneles: si se elimina el ultimo servidor no debe
            # quedar a la vista la informacion del que ya no existe.
            self.current_id = None
            self.console.set_server(None, ServerState.MISSING)
            self.join.set_server(None, running=False)
            self.mods.set_server(None, running=False)
            self.properties.set_server(None)
            self.files.set_server(None, running=False)
            self.players.set_server(None, running=False)
            self.backups.set_server(None, running=False)
            self.logs.set_server(None, running=False)
            self.details.set_server(None, ServerState.MISSING)
            self.stack.setCurrentIndex(0)
            self._update_actions()
            return
        if self.current_id not in self.views:
            self.select_server(views[0].spec.id)
        else:
            self._apply_view(self.views[self.current_id])
        self._check_orphans(views)

    def _on_views_failed(self, message: str, details: str) -> None:
        logger.error("No se pudo actualizar la lista: %s", message)
        self.status_message.setText("No se pudo consultar Podman")

    def _check_orphans(self, views: list[ServerView]) -> None:
        """Avisa si quedaron servidores en ejecucion de una sesion anterior."""
        if self._orphans_checked or not self.config.warn_orphan_containers:
            return
        running = [v for v in views if v.running]
        if not running:
            self._orphans_checked = True
            return
        self._orphans_checked = True
        names = "\n".join(f"  • {v.spec.name}" for v in running)
        answer = QMessageBox(self)
        answer.setWindowTitle("Servidores en ejecucion")
        answer.setIcon(QMessageBox.Icon.Information)
        answer.setText(
            f"Hay {plural(len(running), 'servidor', 'servidores')} que ya estaban en "
            f"ejecucion:\n\n{names}\n\n"
            "Serviscraft mantiene los servidores detenidos por defecto. "
            "¿Quieres detenerlos ahora?"
        )
        stop_button = answer.addButton("Detener todos", QMessageBox.ButtonRole.AcceptRole)
        answer.addButton("Dejarlos funcionando", QMessageBox.ButtonRole.RejectRole)
        answer.exec()
        if answer.clickedButton() is stop_button:
            self.stop_all_servers()

    def select_server(self, server_id: str) -> None:
        if server_id not in self.views:
            return
        self.current_id = server_id
        view = self.views[server_id]
        self.stack.setCurrentIndex(1)
        self._apply_view(view)
        self._sync_console()
        self._update_stats()

    def _spec(self) -> ServerSpec | None:
        if self.current_id is None:
            return None
        view = self.views.get(self.current_id)
        return view.spec if view else None

    def _apply_view(self, view: ServerView) -> None:
        spec = view.spec
        self.header_title.setText(spec.name)
        icono = icon_pixmap(view.icon, 34)
        self.header_icon.setPixmap(
            icono if not icono.isNull() else icono_cuadro(34)
        )
        self.header_platform.set_spec(spec)
        self.header_badge.set_state(view.state)
        scope = "accesible desde la red local" if spec.lan else "solo en este equipo"
        pack = f" · modpack {spec.modpack}" if spec.modpack else ""
        bedrock = f" (UDP {spec.bedrock_port})" if spec.bedrock_enabled else ""
        self.header_subtitle.setText(
            f"{spec.type.label} {spec.version}{pack} · plataforma {spec.platform_label}{bedrock} · "
            f"imagen {spec.image_ref} · puerto {spec.port} ({scope}) · contenedor {spec.container_name}"
        )
        data_dir = self.manager.store.data_dir(spec.id)
        self.action_open_folder.setToolTip(f"Abrir en el gestor de archivos:\n{data_dir}")
        self.action_open_backups.setToolTip(
            f"Abrir en el gestor de archivos:\n{self.manager.store.backups_dir(spec.id)}"
        )
        running = view.state.is_running
        self.console.set_server(spec, view.state)
        self.join.set_server(spec, running=running)
        self.mods.set_server(spec, running=running)
        self.properties.set_server(spec)
        self.files.set_server(spec, running=running)
        self.players.set_server(spec, running=running)
        self.backups.set_server(spec, running=running)
        self.logs.set_server(spec, running=running)
        self.details.set_server(spec, view.state)
        self._update_actions()

    # ================================================================ acciones
    def create_server(self) -> None:
        if not self._engine_version:
            show_error(
                self,
                "Podman no esta disponible",
                "No se puede crear un servidor hasta que Podman funcione correctamente.",
            )
            return
        dialog = CreateServerDialog(self.manager, self.runner, self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        logger.info("Creando servidor desde la interfaz: %s", values.get("name"))

        def work(*, context) -> str:
            spec = self.manager.create_server(
                on_progress=context.progress,
                should_cancel=lambda: context.cancelled,
                **values,
            )
            return spec.id

        def done(server_id: str) -> None:
            self.refresh_servers(force=True)
            QTimer.singleShot(250, lambda: self.select_server(server_id))
            spec = self.manager.get(server_id)
            show_info(
                self,
                "Servidor creado",
                f"«{spec.name}» esta listo y detenido.\n\n"
                f"Puedes iniciarlo cuando quieras con el boton «Iniciar».\n"
                f"Puerto: {spec.port}",
            )

        self.operation.start("Creando el servidor...", cancellable=True)
        self.runner.submit(
            "Creando servidor", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def import_server(self) -> None:
        """Trae un servidor que ya existia (carpeta o .zip de Aternos)."""
        dialog = ImportServerDialog(self.manager, self.runner, self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.imported is None:
            return
        spec = dialog.imported
        logger.info("Servidor importado desde la interfaz: %s", spec.id)
        self.refresh_servers(force=True)
        QTimer.singleShot(250, lambda: self.select_server(spec.id))
        show_info(
            self,
            "Servidor importado",
            f"«{spec.name}» ya esta en Serviscraft con su mundo y su configuracion.\n\n"
            f"Puerto: {spec.port}\n"
            "Puedes iniciarlo con el boton «Iniciar». La primera vez la imagen prepara "
            "el servidor y puede tardar unos minutos.",
        )

    def start_server(self, server_id: str | None = None) -> None:
        target = server_id or self.current_id
        if target is None:
            return
        view = self.views.get(target)
        if view is None:
            return
        if view.running:
            return
        try:
            ok, message = self.manager.check_port_available(view.spec.port, exclude=view.spec.id)
        except ServiscraftError as exc:
            show_error(self, "No se pudo comprobar el puerto", str(exc))
            return
        if not ok:
            show_error(self, "Puerto ocupado", message)
            return
        spec = view.spec

        def work(*, context) -> str:
            self.manager.start_server(
                spec.id,
                on_progress=context.progress,
                should_cancel=lambda: context.cancelled,
            )
            return spec.id

        def done(server_id: str) -> None:
            self.refresh_servers(force=True)
            QTimer.singleShot(400, self._sync_console)
            QTimer.singleShot(600, lambda: self.select_server(server_id))
            # Si el servidor muere nada mas arrancar (por ejemplo, porque la
            # version nueva pide mas Java), se explica en vez de dejarlo ahi.
            QTimer.singleShot(6000, lambda: self._comprobar_arranque(server_id))
            QTimer.singleShot(16000, lambda: self._comprobar_arranque(server_id))
            # Geyser crea su configuracion al arrancar: si el servidor tambien
            # acepta Bedrock, se deja lista para Floodgate.
            QTimer.singleShot(20000, self.join.apply_bedrock_config)

        self.operation.start(f"Iniciando «{spec.name}»...", cancellable=True)
        self.runner.submit(
            "Iniciando servidor", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def _comprobar_arranque(self, server_id: str) -> None:
        """Avisa si el servidor se apago a los pocos segundos de arrancar."""
        def work(*, context):
            # Se consulta el estado real (no el de la lista, que puede ir con
            # retraso): asi tambien se detecta un contenedor que ya no existe.
            return self.manager.diagnose_start_failure(server_id)

        def done(failure) -> None:
            if failure is None:
                return
            logger.warning("Arranque fallido de %s: %s", server_id, failure.message)
            if failure.repairable and confirm(
                self,
                "El servidor necesita otro Java",
                failure.message
                + "\n\n¿Quieres cambiarlo ahora y volver a arrancar?",
                confirm_label="Cambiar Java y arrancar",
            ):
                self._reparar_y_arrancar(server_id, failure.suggested_java_tag)
                return
            show_error(self, "El servidor no arranco", failure.message, failure.evidence)

        self.runner.submit(
            "Comprobando el arranque",
            work,
            on_finished=done,
            on_failed=lambda _m, _d: None,
            track_busy=False,
        )

    def _reparar_y_arrancar(self, server_id: str, java_tag: str) -> None:
        """Cambia la etiqueta de Java, recrea el contenedor y vuelve a arrancar."""
        def work(*, context) -> str:
            context.progress(f"Cambiando Java a {java_tag}...")
            self.manager.update_settings(server_id, java_tag=java_tag)
            context.progress("Volviendo a arrancar el servidor...")
            self.manager.start_server(
                server_id,
                on_progress=context.progress,
                should_cancel=lambda: context.cancelled,
            )
            return server_id

        def done(_server_id: str) -> None:
            self.refresh_servers(force=True)
            QTimer.singleShot(400, self._sync_console)
            QTimer.singleShot(600, lambda: self.select_server(server_id))
            self.status_message.setText(f"Java cambiado a {java_tag}; servidor arrancado.")

        self.operation.start("Cambiando Java y arrancando...", cancellable=True)
        self.runner.submit(
            "Cambiando Java y arrancando",
            work,
            on_finished=done,
            on_failed=self._on_operation_failed,
        )

    def stop_server(self, server_id: str | None = None, *, force: bool = False) -> None:
        target = server_id or self.current_id
        if target is None:
            return
        view = self.views.get(target)
        if view is None or not view.running:
            return
        spec = view.spec
        extra = ""
        if self.config.backup_on_stop:
            extra = "\n\nSe creara tambien una copia de seguridad automatica: tu mundo queda a salvo."
        if not force and not confirm(
            self,
            "Detener el servidor",
            f"¿Detener «{spec.name}»?\n\n"
            "Minecraft guardara el mundo antes de apagarse. Puede tardar unos segundos."
            + extra,
            confirm_label="Detener",
        ):
            return

        def work(*, context) -> str:
            self.manager.stop_server(spec.id, force=force, on_progress=context.progress)
            return spec.id

        def done(_server_id: str) -> None:
            self.refresh_servers(force=True)
            QTimer.singleShot(400, self._sync_console)
            self._avisar_copia_automatica(spec)

        self.operation.start(f"Deteniendo «{spec.name}»...", cancellable=False)
        self.runner.submit(
            "Deteniendo servidor", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def _avisar_copia_automatica(self, spec: ServerSpec) -> None:
        """Muestra en la barra de estado donde ha quedado la copia automatica."""
        try:
            copias = self.manager.backups.list_backups(spec.id)
        except ServiscraftError:  # pragma: no cover - listado defensivo
            return
        automaticas = [info for info in copias if info.origin in ORIGENES_AUTOMATICOS]
        if not automaticas:
            return
        ultima = automaticas[0]
        if self._panel_de(self.tabs.currentWidget()) is self.backups and self.current_id == spec.id:
            self.backups.refresh()
        self.status_message.setText(
            f"Copia automatica: {ultima.filename} ({ultima.size_label}) en "
            f"{self.manager.backups_folder(spec.id)}"
        )

    def restart_server(self, server_id: str | None = None) -> None:
        target = server_id or self.current_id
        if target is None:
            return
        view = self.views.get(target)
        if view is None or not view.running:
            return
        spec = view.spec
        if not confirm(
            self,
            "Reiniciar el servidor",
            f"¿Reiniciar «{spec.name}»? Los jugadores conectados se desconectaran.",
            confirm_label="Reiniciar",
        ):
            return

        def work(*, context) -> str:
            self.manager.restart_server(spec.id, on_progress=context.progress)
            return spec.id

        def done(server_id: str) -> None:
            self.refresh_servers(force=True)
            QTimer.singleShot(400, self._sync_console)
            QTimer.singleShot(600, lambda: self.select_server(server_id))

        self.operation.start(f"Reiniciando «{spec.name}»...", cancellable=False)
        self.runner.submit(
            "Reiniciando servidor", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def stop_all_servers(self) -> None:
        running = [v.spec for v in self.views.values() if v.running]
        if not running:
            show_info(self, "Todo detenido", "No hay ningun servidor en ejecucion.")
            return
        names = "\n".join(f"  • {spec.name}" for spec in running)
        extra = ""
        if self.config.backup_on_stop:
            extra = "\n\nDe cada servidor se creara una copia de seguridad automatica antes de cerrar."
        if not confirm(
            self,
            "Detener todos los servidores",
            f"Se detendran {len(running)} servidores:\n\n{names}\n\n"
            "Minecraft guardara cada mundo antes de apagarse." + extra,
            confirm_label="Detener todos",
        ):
            return

        def work(*, context) -> int:
            stopped = self.manager.stop_all(on_progress=context.progress)
            return len(stopped)

        def done(count: int) -> None:
            self.refresh_servers(force=True)
            QTimer.singleShot(400, self._sync_console)
            self.status_message.setText(f"Servidores detenidos: {count}")

        self.operation.start("Deteniendo todos los servidores...")
        self.runner.submit(
            "Deteniendo servidores", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def backup_all_servers(self) -> None:
        """Copia ahora los servidores en ejecucion (misma tarea que la programada)."""
        running = [v.spec for v in self.views.values() if v.running]
        if not running:
            show_info(
                self,
                "Nada que copiar",
                "No hay ningun servidor en ejecucion. Los servidores detenidos ya se copian "
                "automaticamente al apagarse (se puede desactivar en las preferencias).",
            )
            return
        names = "\n".join(f"  • {spec.name}" for spec in running)
        if not confirm(
            self,
            "Copiar todos los servidores",
            f"Se creara una copia de seguridad de "
            f"{plural(len(running), 'servidor', 'servidores')}:\n\n{names}\n\n"
            "Con el servidor en marcha la copia puede contener el mundo a medio guardar.",
            confirm_label="Copiar ahora",
        ):
            return
        ids = [spec.id for spec in running]

        def work(*, context) -> list:
            return self.manager.backup_servers(
                ids,
                label="manual",
                origin="manual",
                on_progress=context.progress,
            )

        def done(created: list) -> None:
            self.refresh_servers(force=True)
            total = sum(info.size_bytes for info in created)
            self.status_message.setText(f"Copias creadas: {len(created)} ({format_bytes(total)})")
            carpetas = "\n".join(f"  • {self.manager.backups_folder(spec.id)}" for spec in running)
            show_info(
                self,
                "Copias creadas",
                f"Se {'ha' if len(created) == 1 else 'han'} creado "
                f"{plural(len(created), 'copia', 'copias')} de seguridad.\n\n"
                f"Carpeta de copias de cada servidor:\n{carpetas}",
            )

        self.operation.start("Creando copias de seguridad...")
        self.runner.submit(
            "Copiando servidores", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def _configurar_copia_programada(self) -> None:
        """Arranca o para el temporizador de copias periodicas."""
        minutes = int(self.config.scheduled_backup_minutes)
        if minutes > 0:
            self.backup_timer.start(minutes * 60_000)
            logger.info("Copias automaticas cada %d minuto(s)", minutes)
        else:
            self.backup_timer.stop()

    def _on_scheduled_backup(self) -> None:
        """Copia periodica de los servidores en ejecucion."""
        running = [view.spec for view in self.views.values() if view.running]
        if not running:
            return
        logger.info("Copia programada de %d servidor(es)", len(running))

        def work(*, context) -> list:
            return self.manager.backup_running_servers(on_progress=context.progress)

        def done(created: list) -> None:
            if not created:
                return
            total = sum(info.size_bytes for info in created)
            self.status_message.setText(
                f"Copia programada: {plural(len(created), 'servidor', 'servidores')}, "
                f"{format_bytes(total)}"
            )
            if self._panel_de(self.tabs.currentWidget()) is self.backups:
                self.backups.refresh()

        def failed(message: str, details: str) -> None:
            logger.warning("La copia programada fallo: %s", message)
            self.status_message.setText(f"La copia programada fallo: {message}")

        # No marca la aplicacion como ocupada: la copia programada no debe
        # bloquear los botones mientras el usuario hace otras cosas.
        self.runner.submit(
            "Copia de seguridad programada",
            work,
            on_finished=done,
            on_failed=failed,
            on_progress=lambda message: self.status_message.setText(message),
            track_busy=False,
        )

    def delete_server(self, server_id: str | None = None) -> None:
        target = server_id or self.current_id
        if target is None:
            return
        view = self.views.get(target)
        if view is None:
            return
        spec = view.spec
        dialog = ConfirmWithOptions(spec.name, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        delete_data = dialog.delete_data
        make_backup = dialog.make_backup

        def work(*, context) -> str:
            self.manager.delete_server(
                spec.id,
                delete_data=delete_data,
                make_backup=make_backup,
                on_progress=context.progress,
            )
            return spec.id

        def done(_server_id: str) -> None:
            self.current_id = None
            self.console.stop_stream()
            self.refresh_servers(force=True)
            show_info(
                self,
                "Servidor eliminado",
                f"«{spec.name}» se ha eliminado."
                + ("" if delete_data else "\n\nSus datos siguen en el disco.")
                + ("\n\nSe guardo una copia de seguridad." if make_backup else ""),
            )

        self.operation.start(f"Eliminando «{spec.name}»...")
        self.runner.submit(
            "Eliminando servidor", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def edit_server_settings(self, server_id: str | None = None) -> None:
        target = server_id or self.current_id
        if target is None:
            return
        self._open_settings_for(target)

    def _open_settings_for(self, server_id: str) -> None:
        view = self.views.get(server_id)
        if view is None:
            return
        if view.running:
            show_error(
                self,
                "Servidor en ejecucion",
                "Deten el servidor antes de cambiar sus ajustes.",
            )
            return
        dialog = ServerSettingsDialog(self.manager, view.spec, self, runner=self.runner)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        spec = view.spec

        def work(*, context) -> str:
            context.progress("Aplicando los ajustes y recreando el contenedor...")
            self.manager.update_settings(spec.id, **values)
            return spec.id

        def done(server_id_: str) -> None:
            self.refresh_servers(force=True)
            QTimer.singleShot(250, lambda: self.select_server(server_id_))
            show_info(self, "Ajustes guardados", "El contenedor se ha recreado con los nuevos ajustes.")

        self.operation.start("Guardando los ajustes...")
        self.runner.submit(
            "Actualizando ajustes", work, on_finished=done, on_failed=self._on_operation_failed
        )

    def open_server_folder(self, kind: str = "data") -> None:
        """Abre la carpeta de datos o la de copias del servidor seleccionado."""
        spec = self._spec()
        if spec is None:
            return
        if kind == "backups":
            path = self.manager.store.backups_dir(spec.id)
        else:
            path = self.manager.store.data_dir(spec.id)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            show_error(self, "No se pudo abrir la carpeta", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_appearance(self, server_id: str | None = None) -> None:
        """Abre el editor de la imagen y la descripcion del servidor."""
        target = server_id or self.current_id
        if target is None:
            return
        view = self.views.get(target)
        if view is None:
            return
        dialog = AppearanceDialog(
            self.manager,
            self.runner,
            view.spec,
            running=view.running,
            parent=self,
        )
        dialog.saved.connect(lambda: self.refresh_servers(force=True))
        dialog.exec()
        # Aunque no se guarde nada, la lista puede haber cambiado desde fuera.
        self.refresh_servers(force=True)

    def open_preferences(self) -> None:
        dialog = PreferencesDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.manager.config = self.config.validated()
            self.manager.client.binary = self.config.engine_binary
            self.stats_timer.setInterval(self.config.stats_interval_ms)
            self._configurar_copia_programada()
            self.status_message.setText("Preferencias guardadas")

    def show_log(self) -> None:
        from ..core import paths

        log = paths.log_file()
        try:
            text = log.read_text(encoding="utf-8", errors="replace")[-200_000:]
        except OSError as exc:
            show_error(self, "No se pudo leer el registro", str(exc))
            return
        dialog = DetailsDialog(
            "Registro de Serviscraft",
            f"Ultimas lineas del registro de la aplicacion.\n\n{log}",
            text,
            parent=self,
        )
        dialog.exec()

    def show_about(self) -> None:
        from .. import __version__
        from ..core import paths

        box = QMessageBox(self)
        box.setWindowTitle("Acerca de Serviscraft")
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<h3>Serviscraft {__version__}</h3>"
            "<p>Gestor grafico de servidores de Minecraft basado en Podman rootless.</p>"
            "<p><b>Seguridad:</b> nunca se usa sudo, la API de Podman no se expone por TCP, "
            "el cortafuegos no se modifica y ninguna accion destructiva se ejecuta sin confirmacion.</p>"
            f"<p>Datos: <code>{paths.data_root()}</code><br>"
            f"Registro: <code>{paths.log_file()}</code></p>"
            "<p>Serviscraft no esta afiliado a Mojang ni a Microsoft. "
            "Minecraft es una marca de Mojang AB.</p>"
        )
        box.exec()

    # ================================================================ estado
    def _on_busy_changed(self, busy: bool) -> None:
        self._update_actions()
        if not busy:
            self.operation.finish()

    def _cancel_operations(self) -> None:
        """Solicita cancelar las tareas en curso (se detienen al terminar el paso actual)."""
        self.runner.cancel_all()
        self.status_message.setText("Cancelando las operaciones en curso...")
        logger.info("El usuario solicito cancelar las operaciones")

    def _on_operation_failed(self, message: str, details: str) -> None:
        self.operation.finish()
        show_error(self, "La operacion no se pudo completar", message, details)
        self.refresh_servers(force=True)

    def _update_actions(self) -> None:
        view = self.views.get(self.current_id) if self.current_id else None
        running = bool(view and view.running)
        has_server = view is not None
        busy = self.runner.busy

        self.action_start.setEnabled(bool(self._engine_version) and has_server and not running and not busy)
        self.action_stop.setEnabled(has_server and running and not busy)
        self.action_restart.setEnabled(has_server and running and not busy)
        self.action_delete.setEnabled(has_server and not busy)
        self.action_settings.setEnabled(has_server and not running and not busy)
        self.action_appearance.setEnabled(has_server and not busy)
        self.action_open_folder.setEnabled(has_server)
        self.action_open_backups.setEnabled(has_server)
        self.action_backup_all.setEnabled(bool(self.views) and not busy)
        self.action_stop_all.setEnabled(any(v.running for v in self.views.values()) and not busy)

        self.start_button.setEnabled(bool(self._engine_version) and has_server and not running and not busy)
        self.stop_button.setEnabled(has_server and running and not busy)
        self.restart_button.setEnabled(has_server and running and not busy)
        self.settings_button.setEnabled(has_server and not running and not busy)
        self.delete_button.setEnabled(has_server and not busy)

    # ================================================================ consola
    @staticmethod
    def _panel_de(pagina: QWidget | None) -> QWidget | None:
        """Devuelve el panel de una pestana (desenvuelve el area desplazable)."""
        if isinstance(pagina, QScrollArea):
            return pagina.widget()
        return pagina

    def _pagina_de(self, panel: QWidget) -> QWidget:
        """Pestana que contiene un panel (su area desplazable)."""
        for indice in range(self.tabs.count()):
            pagina = self.tabs.widget(indice)
            if self._panel_de(pagina) is panel:
                return pagina
        return panel

    def _on_tab_changed(self, index: int) -> None:
        self._sync_console()
        # Se compara por widget (no por indice) para que anadir o mover pestanas
        # no rompa el refresco de ninguna de ellas.
        widget = self._panel_de(self.tabs.widget(index))
        # El seguimiento en vivo solo se pausa al salir de la pestana; la
        # casilla conserva lo que eligio el usuario.
        self.logs.set_activo(widget is self.logs)
        if widget is self.properties:
            self.properties.load(self._spec())
        elif widget is self.files:
            self.files.refresh()
        elif widget is self.players:
            self.players.refresh()
        elif widget is self.backups:
            self.backups.refresh()
        elif widget is self.logs:
            self.logs.refresh()
        elif widget is self.mods:
            self.mods.refresh()
        elif widget is self.join:
            self.join.apply_bedrock_config()
        elif widget is self.details:
            self.details.refresh_disk_usage()

    def _open_missing_mods(self) -> None:
        """Abre la pestana «Mods» y analiza el registro en busca de mods que faltan."""
        self.tabs.setCurrentWidget(self._pagina_de(self.mods))
        self.mods.analyze_logs()

    def _sync_console(self) -> None:
        """Sigue la consola solo cuando es visible y el servidor esta seleccionado."""
        view = self.views.get(self.current_id) if self.current_id else None
        console_visible = (
            view is not None
            and self.stack.currentIndex() == 1
            and self._panel_de(self.tabs.currentWidget()) is self.console
            and self.isVisible()
        )
        if console_visible:
            self.console.start_stream()
        else:
            self.console.stop_stream()

    # ============================================================= estadisticas
    def _on_stats_tick(self) -> None:
        self._refresh_tick += 1
        view = self.views.get(self.current_id) if self.current_id else None
        if view is not None and view.running:
            self._update_stats()
        else:
            self.cpu_bar.reset()
            self.ram_bar.reset()
            self.metrics_extra.setText("")
        # Cada dos ciclos se refrescan los estados de la lista.
        if self._refresh_tick % 2 == 0 and not self.runner.busy:
            self.refresh_servers()

    def _update_stats(self) -> None:
        view = self.views.get(self.current_id) if self.current_id else None
        if view is None or not view.running or self.stack.currentIndex() != 1:
            return
        spec = view.spec

        def work(*, context):
            return self.manager.stats(spec.id)

        self.runner.submit(
            "Consultando estadisticas",
            work,
            on_finished=self._on_stats_ready,
            on_failed=lambda _m, _d: None,
            track_busy=False,
        )

    def _on_stats_ready(self, stats) -> None:
        if stats is None:
            return
        if not stats.available:
            self.cpu_bar.reset()
            self.ram_bar.reset()
            self.metrics_extra.setText("")
            return
        # Nunca se ensena mas del 100 %: si llegase una cifra por nucleo sin
        # normalizar, la barra y el numero siguen teniendo sentido.
        cpu = min(100.0, max(0.0, stats.cpu_percent))
        self.cpu_bar.set_value(cpu, f"{cpu:.0f} %")
        if stats.cpu_cores > 0:
            self.cpu_bar.set_tooltip(
                f"{stats.cpu_cores_used:.1f} de {stats.cpu_cores} nucleos del equipo "
                f"({cpu:.0f} % del total)"
            )
        else:
            self.cpu_bar.set_tooltip("Uso de CPU del servidor")
        view = self.views.get(self.current_id) if self.current_id else None
        asignada_mb = view.spec.memory_mb if view is not None else 0
        limite = asignada_mb * 1024 * 1024
        if limite > 0:
            # El contenedor no lleva limite propio de memoria: el que le importa
            # al usuario es el que tiene asignado el servidor (Xmx).
            porcentaje = min(100.0, stats.memory_bytes * 100.0 / limite)
            self.ram_bar.set_value(
                porcentaje, stats.memory_label(limit_mb=asignada_mb)
            )
            self.ram_bar.set_tooltip(
                f"{stats.memory_label(limit_mb=asignada_mb)} "
                f"({porcentaje:.0f} % de la memoria asignada)"
            )
        else:
            self.ram_bar.set_value(stats.memory_percent, stats.memory_label())
            self.ram_bar.set_tooltip(stats.memory_label())
        self.metrics_extra.setText(f"procesos: {stats.pids}")

    # ================================================================ cierre
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API de Qt
        if self._saliendo_tras_detener:
            # Ya se esta apagando todo en segundo plano: se espera sin reabrir el aviso.
            event.ignore()
            return
        running = [v.spec for v in self.views.values() if v.running]
        if running:
            names = "\n".join(f"  • {spec.name}" for spec in running)
            detalles = ""
            if self.config.backup_on_stop:
                detalles = (
                    "\n\nAntes de salir se creara la copia de seguridad automatica de "
                    "cada servidor (se puede desactivar en las preferencias)."
                )
            box = QMessageBox(self)
            box.setWindowTitle("Servidores en ejecucion")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(
                f"Hay {plural(len(running), 'servidor', 'servidores')} en "
                f"ejecucion:\n\n{names}\n\n"
                "¿Que quieres hacer al cerrar Serviscraft?" + detalles
            )
            stop_button = box.addButton("Detenerlos y salir", QMessageBox.ButtonRole.AcceptRole)
            keep_button = box.addButton("Dejarlos funcionando", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is stop_button:
                self._stop_and_exit(running)
                event.ignore()
                return
            if clicked is not keep_button:
                event.ignore()
                return
        self.console.shutdown()
        self.runner.shutdown(4000)
        logger.info("Serviscraft cerrado")
        event.accept()

    def _stop_and_exit(self, running: list[ServerSpec]) -> None:
        """Detiene los servidores (con su copia) antes de salir, sin bloquear la ventana.

        La parada ordenada y las copias pueden tardar: se hacen en segundo plano
        con la barra de operacion visible y, al terminar, se vuelve a llamar a
        ``close()`` con los servidores ya detenidos.
        """
        ids = [spec.id for spec in running]
        self._saliendo_tras_detener = True
        self.operation.start("Deteniendo los servidores y creando copias de seguridad...", cancellable=False)

        def work(*, context) -> list[str]:
            stopped: list[str] = []
            for server_id in ids:
                try:
                    context.progress("Deteniendo los servidores y copiando sus datos...")
                    self.manager.stop_server(server_id, on_progress=context.progress)
                    stopped.append(server_id)
                except ServiscraftError as exc:
                    logger.error("No se pudo detener %s al salir: %s", server_id, exc)
            return stopped

        def done(stopped: list[str]) -> None:
            # Los servidores ya estan apagados: se marca su estado para que el
            # aviso de cierre no vuelva a aparecer.
            for server_id in stopped:
                view = self.views.get(server_id)
                if view is not None:
                    self.views[server_id] = replace(view, state=ServerState.EXITED)
            self._saliendo_tras_detener = False
            self.close()

        def failed(message: str, details: str) -> None:
            self._saliendo_tras_detener = False
            self._on_operation_failed(message, details)

        self.runner.submit(
            "Deteniendo servidores al salir",
            work,
            on_finished=done,
            on_failed=failed,
            on_progress=self.operation.set_message,
        )


def create_application_window(manager: ServerManager, config: AppConfig) -> MainWindow:
    """Fabrica la ventana principal (facilita las pruebas)."""
    return MainWindow(manager, config)
