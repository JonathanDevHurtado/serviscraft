"""Catalogo de pluguins y mods de Modrinth para instalarlos desde la interfaz.

La busqueda filtra en Modrinth por la version de Minecraft y por los cargadores
que admite el servidor. La ventana se organiza como el catalogo de un launcher:
busqueda, orden, filtro de lado, lista de proyectos y una ficha con los datos del
proyecto elegido.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import icons as iconos_remotos
from ..core import modrinth
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec, ServerType
from ..core.modrinth import ContentSelection, Project, Release
from .common import (
    Chip,
    FlowRow,
    WrappingLabel,
    escape_text,
    make_button,
    polish_table_header,
)
from .dialogs import show_error, show_info
from .mc_icons import icono_mod, icono_plugin, pixmap_de_bytes
from .mc_widgets import IconSlot, MinecraftHero
from .tasks import TaskRunner

logger = get_logger("ui.catalog")

#: Filtros por lado del juego.
FILTROS_LADO: tuple[tuple[str, str | None], ...] = (
    ("Sirve en servidor", "servidor"),
    ("Cliente o servidor", None),
    ("Solo cliente", "cliente"),
)

#: Ordenes que ofrece el catalogo, con el nombre que entiende Modrinth.
ORDENES: tuple[tuple[str, str], ...] = (
    ("Relevancia", "relevance"),
    ("Mas descargados", "downloads"),
    ("Mas seguidos", "follows"),
    ("Actualizados", "updated"),
    ("Novedades", "newest"),
)

#: Categorias de Modrinth traducidas. Se envian a la API en ingles.
CATEGORIAS: tuple[tuple[str, str], ...] = (
    ("Todas las categorias", ""),
    ("Optimizacion", "optimization"),
    ("Utilidad", "utility"),
    ("Bibliotecas", "library"),
    ("Aventura", "adventure"),
    ("Decoracion", "decoration"),
    ("Mundos", "worldgen"),
    ("Criaturas", "mobs"),
    ("Equipamiento", "equipment"),
    ("Magia", "magic"),
    ("Tecnologia", "technology"),
    ("Transporte", "transportation"),
    ("Comida", "food"),
    ("Mecanicas", "game-mechanics"),
    ("Gestion", "management"),
    ("Minijuegos", "minigame"),
    ("Economia", "economy"),
    ("Almacenamiento", "storage"),
)

#: Cuantos proyectos se piden a Modrinth en cada tanda.
SEARCH_LIMIT = 40

_AYUDA = (
    "Busca en <b>Modrinth</b> el contenido que quieras anadir al servidor. La "
    "busqueda ya tiene en cuenta la version de Minecraft y el cargador del "
    "servidor, asi que los resultados que aparecen pueden funcionar.<br><br>"
    "«Ordenar» cambia el criterio de la lista. «Lado» permite ocultar los "
    "proyectos que solo funcionan en el cliente y «Categoria» limita la "
    "busqueda a un tipo de contenido.<br><br>"
    "Al elegir un proyecto se cargan <b>todas sus versiones</b>: las "
    "compatibles se pueden instalar y las demas aparecen en gris para que sepas "
    "que existen. «Cargar mas resultados» sigue bajando por la lista."
)


class CatalogDialog(QDialog):
    """Catalogo de Modrinth reutilizable como dialogo, pestana o selector.

    - Como dialogo normal instala contenido en un servidor.
    - Con ``embedded=True`` se puede meter dentro de una pestana (Plugins).
    - Con ``selection=True`` no descarga nada: emite ``content_selected`` para
      que el asistente de creacion guarde la eleccion y la instale al final.
    """

    #: Proyecto y version elegidos (modo seleccion, para crear servidores).
    content_selected = Signal(object)
    #: Nombre del fichero instalado en el servidor.
    content_installed = Signal(str)

    def __init__(
        self,
        manager: ServerManager | None,
        runner: TaskRunner,
        spec: ServerSpec | None,
        mode: str,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
        selection: bool = False,
        server_type: ServerType | None = None,
        version: str = "",
        loaders: tuple[str, ...] | None = None,
        context_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CatalogDialog")
        if embedded:
            # Un QDialog es una ventana por defecto. Dentro de una pestana o de
            # otro cuadro tiene que ser un widget normal: si no, el catalogo se
            # queda flotando fuera y la pestana aparece vacia.
            self.setWindowFlags(Qt.WindowType.Widget)
        self.manager = manager
        self.runner = runner
        self.spec = spec
        self.mode = "plugins" if mode == "plugins" else "mods"
        self.embedded = embedded
        self.selection = selection
        self.installed: list[str] = []
        self._projects: list[Project] = []
        self._busy = False
        self._has_searched = False
        self._auto_loaded = False
        self._auto_timer = QTimer(self)
        self._search_timer = QTimer(self)
        #: Si se escribe mientras una busqueda esta en marcha, al terminar se
        #: lanza otra con el texto definitivo (como en un launcher).
        self._pending_search = False
        #: Tarea en curso (busqueda, versiones o instalacion) y estado de la
        #: ventana. Al cerrar se cancela y sus avisos ya no tocan la interfaz.
        self._task = None
        self._versions_task = None
        self._closed = False
        #: Se incrementa al cambiar de servidor/proyecto: las respuestas viejas
        #: de una busqueda anterior no deben pintar la lista nueva.
        self._generation = 0
        self._offset = 0
        self._loaded_count = 0
        self._has_more = False
        self._versions_loading = False
        self._versions_for: Project | None = None
        self._version_releases: list[Release] = []
        self._selected_release: Release | None = None

        self.server_type = server_type or (spec.type if spec is not None else None)
        self.version = version or (spec.version if spec is not None else "")
        if loaders is None:
            loaders = modrinth.loaders_for_spec(spec) if spec is not None else ()
        self.loaders = tuple(loaders)
        self.context_name = context_name or (spec.name if spec is not None else "")
        self._kind = "pluguins" if self.mode == "plugins" else "mods"
        self._kind_one = "pluguin" if self.mode == "plugins" else "mod"

        if not embedded:
            self.setWindowTitle(f"Instalar {self._kind} en «{self.context_name}»")
            self.setMinimumSize(640, 600)
            self.resize(1100, 780)

        layout = QVBoxLayout(self)
        margen = 0 if embedded else 14
        layout.setContentsMargins(margen, margen, margen, 0 if embedded else 12)
        layout.setSpacing(10)

        self.hero = MinecraftHero(
            f"Instalar {self._kind}",
            "",
            pixmap=icono_plugin(44) if self.mode == "plugins" else icono_mod(44),
            accent="blue" if self.mode == "plugins" else "gold",
            help_title="Catalogo de Modrinth",
            help_text=_AYUDA,
        )
        layout.addWidget(self.hero)

        contexto = FlowRow(spacing=8)
        self.chip_minecraft = Chip("Minecraft")
        self.chip_loader = Chip("Cargador")
        self.chip_kind = Chip(self._kind_one.capitalize())
        self.chip_source = Chip("Fuente: Modrinth")
        for chip in (self.chip_minecraft, self.chip_loader, self.chip_kind, self.chip_source):
            contexto.add(chip)
        layout.addWidget(contexto)
        self._update_context()

        busqueda = QFrame()
        busqueda.setObjectName("CatalogToolbar")
        busqueda.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        barra = QHBoxLayout(busqueda)
        barra.setContentsMargins(10, 8, 10, 8)
        barra.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("CatalogSearch")
        self.search_input.setPlaceholderText(
            "Buscar en Modrinth por nombre, por ejemplo EssentialsX o Sodium"
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(250)
        self.search_input.returnPressed.connect(self.search)
        # Busqueda mientras se escribe, con una pausa: es lo que hace un
        # launcher y evita tener que pulsar «Buscar» en cada intento.
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(320)
        self._search_timer.timeout.connect(self.search)
        # Carga inicial con un pequeno retraso para que la ventana se pinte
        # antes de consultar la red. Es un temporizador hijo (no un
        # ``singleShot`` suelto): si se cierra el catalogo, se cancela.
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(120)
        self._auto_timer.timeout.connect(self.search)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        barra.addWidget(self.search_input, 1)

        self.search_button = make_button(
            "Buscar",
            icon_names=("system-search",),
            accent=True,
            tooltip="Buscar en Modrinth con la version y el cargador de este servidor",
        )
        self.search_button.clicked.connect(self.search)
        barra.addWidget(self.search_button)

        barra.addWidget(QLabel("Ordenar"))
        self.sort_combo = QComboBox()
        self.sort_combo.setToolTip("Criterio con el que se ordenan los resultados")
        for etiqueta, valor in ORDENES:
            self.sort_combo.addItem(etiqueta, valor)
        self.sort_combo.currentIndexChanged.connect(self._on_order_changed)
        barra.addWidget(self.sort_combo)
        layout.addWidget(busqueda)

        filtros = QHBoxLayout()
        filtros.setSpacing(8)
        filtros.addWidget(QLabel("Lado"))
        self.side_combo = QComboBox()
        for etiqueta, valor in FILTROS_LADO:
            self.side_combo.addItem(etiqueta, valor)
        self.side_combo.setToolTip(
            "Modrinth marca algunos proyectos como «solo cliente»: no sirven en un "
            "servidor. Aqui puedes ocultarlos (por defecto) o verlos."
        )
        self.side_combo.currentIndexChanged.connect(self._aplicar_filtros)
        filtros.addWidget(self.side_combo, 1)

        filtros.addWidget(QLabel("Categoria"))
        self.category_combo = QComboBox()
        for etiqueta, valor in CATEGORIAS:
            self.category_combo.addItem(etiqueta, valor)
        self.category_combo.setToolTip(
            "Limita la busqueda a un tipo de contenido (optimizacion, utilidad, "
            "aventura...). Se aplica al buscar de nuevo."
        )
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        filtros.addWidget(self.category_combo, 1)

        self.open_button = make_button(
            "Ver en Modrinth",
            icon_names=("internet-web-browser",),
            tooltip="Abrir en el navegador la pagina del proyecto elegido",
        )
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_page)
        filtros.addWidget(self.open_button)
        layout.addLayout(filtros)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("CatalogTable")
        self.table.setProperty("catalogMode", self.mode)
        self.table.setHorizontalHeaderLabels(
            ["Proyecto", "Cargador", "Minecraft", "Descargas", "Actualizado", "Descripcion"]
        )
        cabecera = self.table.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setIconSize(QSize(28, 28))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_project_selected)
        self.table.doubleClicked.connect(self._install_selected)
        # Sin un minimo, la ficha y las versiones se quedan con todo el alto y
        # la lista de resultados se reduce a una sola fila.
        self.table.setMinimumHeight(250)
        polish_table_header(self.table)
        layout.addWidget(self.table, 1)

        self.details_frame = QFrame()
        self.details_frame.setObjectName("CatalogDetails")
        self.details_frame.setProperty("catalogMode", self.mode)
        self.details_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ficha = QHBoxLayout(self.details_frame)
        ficha.setContentsMargins(10, 9, 10, 9)
        ficha.setSpacing(12)

        self.details_icon = IconSlot(None, size=50, icon_size=34, parent=self.details_frame)
        ficha.addWidget(self.details_icon, 0, Qt.AlignmentFlag.AlignTop)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.details_title = QLabel("Selecciona un proyecto")
        self.details_title.setObjectName("CatalogDetailsTitle")
        self.details_title.setTextFormat(Qt.TextFormat.PlainText)
        textos.addWidget(self.details_title)
        self.details_meta = QLabel("Los datos del proyecto apareceran aqui.")
        self.details_meta.setObjectName("CatalogDetailsMeta")
        self.details_meta.setTextFormat(Qt.TextFormat.PlainText)
        self.details_meta.setWordWrap(True)
        textos.addWidget(self.details_meta)
        self.details = WrappingLabel("")
        self.details.setObjectName("CatalogDetailsText")
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        textos.addWidget(self.details)
        ficha.addLayout(textos, 1)
        layout.addWidget(self.details_frame)

        # --------------------------------------------------------- versiones
        # Todas las versiones del proyecto elegido, no solo la ultima: las
        # compatibles se pueden instalar y las demas se ven en gris.
        self.versions_frame = QFrame()
        self.versions_frame.setObjectName("CatalogVersions")
        self.versions_frame.setProperty("catalogMode", self.mode)
        self.versions_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        versiones = QVBoxLayout(self.versions_frame)
        versiones.setContentsMargins(10, 8, 10, 8)
        versiones.setSpacing(6)

        cabecera_versiones = QHBoxLayout()
        cabecera_versiones.setSpacing(8)
        self.versions_title = QLabel("Versiones publicadas")
        self.versions_title.setObjectName("CatalogVersionsTitle")
        cabecera_versiones.addWidget(self.versions_title, 1)
        self.load_versions_button = make_button(
            "Ver todas las versiones",
            icon_names=("view-refresh", "download"),
            tooltip="Consultar todas las versiones publicadas del proyecto elegido",
        )
        self.load_versions_button.clicked.connect(self._load_versions)
        cabecera_versiones.addWidget(self.load_versions_button)
        versiones.addLayout(cabecera_versiones)

        self.versions_table = QTableWidget(0, 5)
        self.versions_table.setObjectName("CatalogVersionsTable")
        self.versions_table.setProperty("catalogMode", self.mode)
        self.versions_table.setHorizontalHeaderLabels(
            ["Version", "Minecraft", "Cargador", "Tipo", "Publicada"]
        )
        cabecera_v = self.versions_table.horizontalHeader()
        for columna in range(5):
            cabecera_v.setSectionResizeMode(columna, QHeaderView.ResizeMode.ResizeToContents)
        cabecera_v.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.versions_table.verticalHeader().setVisible(False)
        self.versions_table.verticalHeader().setDefaultSectionSize(28)
        self.versions_table.setAlternatingRowColors(True)
        self.versions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.versions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.versions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.versions_table.itemSelectionChanged.connect(self._on_version_selected)
        self.versions_table.doubleClicked.connect(self._install_selected)
        self.versions_table.setMinimumHeight(118)
        self.versions_table.setMaximumHeight(190)
        polish_table_header(self.versions_table)
        versiones.addWidget(self.versions_table)
        self.versions_frame.setVisible(False)
        layout.addWidget(self.versions_frame)

        estado = QHBoxLayout()
        estado.setSpacing(8)
        self.status = QLabel(
            "Al abrir el catalogo se muestran los proyectos populares; escribe para buscar otro."
        )
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        estado.addWidget(self.status, 1)
        self.load_more_button = make_button(
            "Cargar mas resultados",
            icon_names=("view-refresh", "go-down"),
            tooltip="Pedir a Modrinth la siguiente tanda de resultados",
        )
        self.load_more_button.setVisible(False)
        self.load_more_button.clicked.connect(self._load_more)
        estado.addWidget(self.load_more_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.setVisible(False)
        estado.addWidget(self.progress)
        layout.addLayout(estado)

        buttons = QDialogButtonBox()
        self.install_button = buttons.addButton(
            "Anadir a la lista" if self.selection else "Instalar version",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.install_button.setObjectName("CatalogInstall")
        self.install_button.setProperty("accent", "true")
        self.install_button.setProperty("catalogMode", self.mode)
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self._install_selected)
        self.close_button = buttons.addButton(
            "Cerrar", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.close_button.setVisible(not embedded)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Tambien se emite al pulsar «Cerrar» (no solo al cerrar la ventana):
        # deja de haber busquedas pendientes y se cancela lo que este en curso.
        self.finished.connect(self._on_finished)

        if not embedded:
            self.search_input.setFocus()
        self._fit_columns()

    # ================================================================ contexto
    def _update_context(self) -> None:
        """Pinta la cabecera y los chips con el servidor o destino actual."""
        if self.server_type is None:
            self.hero.set_title(
                f"Anadir {self._kind}" if self.selection else f"Catalogo de {self._kind}"
            )
            self.hero.set_subtitle(
                "Elige un servidor para ver solo el contenido compatible."
            )
            self.chip_minecraft.set_text("Minecraft sin definir")
            self.chip_loader.set_text("Cargador sin definir")
            return
        tipo = self.server_type.label
        version = self.version or "sin version"
        nombre = f"«{self.context_name}»" if self.context_name else tipo
        if self.selection:
            titulo = f"Anadir {self._kind}"
        elif self.embedded and self.context_name:
            titulo = f"{'Plugins' if self.mode == 'plugins' else 'Mods'} de {nombre}"
        else:
            titulo = f"Instalar {self._kind}"
        self.hero.set_title(titulo)
        self.hero.set_subtitle(
            f"Contenido para {tipo} {version} · Fuente: Modrinth."
        )
        self.chip_minecraft.set_text(f"Minecraft {version}")
        cargador = ", ".join(self.loaders) if self.loaders else "el del servidor"
        self.chip_loader.set_text(f"Cargador: {cargador}")
        self.chip_kind.set_text(self._kind_one.capitalize())
        self.setWindowTitle(f"Instalar {self._kind} en «{self.context_name}»")

    def set_server(self, spec: ServerSpec | None) -> None:
        """Cambia de servidor sin dejar respuestas del anterior en pantalla."""
        anterior = self.spec
        if anterior is not None and spec is not None and anterior.id == spec.id:
            if anterior.version != spec.version or anterior.type is not spec.type:
                anterior = None
            else:
                self.spec = spec
                return
        self._cancelar_tarea()
        self._generation += 1
        self.spec = spec
        self.server_type = spec.type if spec is not None else None
        self.version = spec.version if spec is not None else ""
        self.loaders = modrinth.loaders_for_spec(spec) if spec is not None else ()
        self.context_name = spec.name if spec is not None else ""
        self._projects = []
        self._offset = 0
        self._loaded_count = 0
        self._has_more = False
        self._has_searched = False
        self._auto_loaded = False
        self._pending_search = False
        self._versions_for = None
        self._version_releases = []
        self._selected_release = None
        self._versions_loading = False
        self.table.setRowCount(0)
        self.versions_table.setRowCount(0)
        self.versions_frame.setVisible(False)
        self.load_more_button.setVisible(False)
        self._limpiar_seleccion()
        self._update_context()
        if spec is not None and self.isVisible():
            self._auto_timer.start()

    def _target_ready(self) -> bool:
        if self.server_type is None:
            return False
        if self.mode == "plugins":
            return self.server_type.supports_plugins
        return self.server_type.supports_mods

    def activate(self) -> None:
        """Carga los populares la primera vez que se ve esta pestana."""
        if not self._auto_loaded and self._target_ready():
            self._auto_loaded = True
            self._auto_timer.start()

    # ================================================================ busqueda
    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Quita columnas secundarias cuando la ventana se estrecha.

        La descripcion y la fecha siguen estando en la ficha de abajo, asi que
        la tabla puede prescindir de ellas antes que dejar el texto cortado.
        """
        if not hasattr(self, "table"):
            return
        ancho = self.width()
        for columna, visible in ((5, ancho >= 900), (4, ancho >= 660)):
            if self.table.isColumnHidden(columna) == visible:
                self.table.setColumnHidden(columna, not visible)
        # Sin la columna de descripcion, el nombre del proyecto ocupa el sitio
        # libre para que la tabla no acabe en una franja gris vacia.
        cabecera = self.table.horizontalHeader()
        modo = (
            QHeaderView.ResizeMode.ResizeToContents
            if ancho >= 900
            else QHeaderView.ResizeMode.Stretch
        )
        if cabecera.sectionResizeMode(0) != modo:
            cabecera.setSectionResizeMode(0, modo)

    def showEvent(self, event) -> None:  # noqa: N802 - API de Qt
        """Carga los proyectos populares la primera vez que se abre."""
        super().showEvent(event)
        self._closed = False
        if not self._auto_loaded and self._target_ready():
            self.activate()
        # Si se eligio un proyecto antes de que la ventana se viera, ahora que
        # esta a la vista se consultan sus versiones.
        if (
            self._selected_project() is not None
            and not self._version_releases
            and not self._versions_loading
        ):
            self._load_versions()

    def shutdown(self) -> None:
        """Detiene temporizadores y tareas (al cerrar o cambiar de servidor)."""
        self._closed = True
        self._auto_timer.stop()
        self._search_timer.stop()
        self._cancelar_tarea()

    def closeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        self.shutdown()
        super().closeEvent(event)

    def _on_finished(self, _result: int) -> None:
        self.shutdown()

    def _cancelar_tarea(self) -> None:
        if self._busy and self._task is not None:
            self._task.cancel()
        self._task = None
        if self._versions_task is not None:
            self._versions_task.cancel()
        self._versions_task = None
        self._versions_loading = False
        self._busy = False
        self.progress.setVisible(False)

    def _on_search_text_changed(self, _texto: str) -> None:
        # Si el usuario escribe enseguida, no hace falta la carga inicial.
        self._auto_timer.stop()
        if self._busy:
            self._pending_search = True
            return
        self._search_timer.start()

    def _on_order_changed(self) -> None:
        if self._has_searched or self._auto_loaded:
            if not self._busy:
                self.search()
        else:
            self._search_timer.start()

    def _on_category_changed(self) -> None:
        if self._busy:
            self._pending_search = True
        elif self._has_searched or self._auto_loaded:
            self.search()

    def search(self) -> None:
        self._run_search(append=False)

    def _load_more(self) -> None:
        if self._has_more and not self._busy:
            self._run_search(append=True)

    def _run_search(self, *, append: bool) -> None:
        self._auto_timer.stop()
        self._search_timer.stop()
        if self._closed:
            return
        if self._busy:
            self._pending_search = True
            return
        if self.server_type is None:
            self.status.setText("Elige un servidor para buscar contenido compatible.")
            return
        if not self._target_ready():
            if self.mode == "plugins":
                self.status.setText(
                    f"{self.server_type.label} no admite plugins. Crea un servidor Paper "
                    "para usar esta seccion."
                )
            else:
                self.status.setText(
                    f"{self.server_type.label} no admite mods. Usa Fabric, Forge o un modpack."
                )
            return
        self._pending_search = False
        project_type = (
            modrinth.PROJECT_TYPE_PLUGIN if self.mode == "plugins" else modrinth.PROJECT_TYPE_MOD
        )
        query = self.search_input.text().strip()
        index = self.sort_combo.currentData() or "relevance"
        category = self.category_combo.currentData() or ""
        offset = self._offset if append else 0
        generation = self._generation
        self._set_busy(
            True,
            "Cargando mas resultados..." if append else "Buscando en Modrinth...",
        )

        def work(*, context):
            context.progress("Consultando Modrinth...")
            proyectos = modrinth.search_projects(
                query,
                project_type=project_type,
                game_version=self.version,
                loaders=self.loaders,
                only_server_side=False,
                limit=SEARCH_LIMIT,
                offset=offset,
                index=index,
                category=category,
            )
            # Los iconos se descargan aqui (en el hilo de trabajo) y quedan en la
            # cache: la tabla los pinta al instante y sin volver a la red.
            if proyectos:
                context.progress("Descargando los iconos de los proyectos...")
                iconos_remotos.prefetch(proyecto.icon_url for proyecto in proyectos)
            return proyectos

        def done(projects: list[Project]) -> None:
            self._set_busy(False)
            if self._closed or generation != self._generation:
                return
            self._has_searched = True
            if append:
                existentes = {project.id for project in self._projects}
                nuevos = [project for project in projects if project.id not in existentes]
                self._projects.extend(nuevos)
                self._offset = offset + len(projects)
                self._has_more = len(projects) >= SEARCH_LIMIT
                if nuevos:
                    self._fill(self._projects)
                    self.status.setText(
                        f"Mostrando {len(self._projects)} resultados. "
                        "Selecciona uno para ver e instalar sus versiones."
                    )
                elif self._has_more:
                    self.status.setText(
                        "Modrinth devolvio resultados repetidos. Pulsa otra vez "
                        "«Cargar mas resultados»."
                    )
                else:
                    self.status.setText("No hay mas resultados para esta busqueda.")
            else:
                self._projects = list(projects)
                self._offset = len(projects)
                self._has_more = len(projects) >= SEARCH_LIMIT
                self._fill(self._projects)
                label = "resultados" if len(projects) != 1 else "resultado"
                if projects:
                    if query:
                        self.status.setText(
                            f"{len(projects)} {label} para «{query}». Selecciona uno "
                            "para ver todas sus versiones."
                        )
                    else:
                        self.status.setText(
                            f"{len(projects)} proyectos populares. Selecciona uno para "
                            "ver todas sus versiones."
                        )
                    if self.table.rowCount():
                        self.table.selectRow(0)
                else:
                    self.status.setText(
                        f"No se encontro contenido compatible con {self.server_type.label} "
                        f"{self.version}. Prueba con otro nombre, categoria o revision "
                        "de la version del servidor."
                    )
            self.load_more_button.setVisible(self._has_more)
            self._search_again_if_pending()

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            if self._closed or generation != self._generation:
                return
            self.status.setText(f"No se pudo buscar: {message}")
            show_error(self, "No se pudo consultar Modrinth", message, details)
            self._search_again_if_pending()

        self._task = self.runner.submit(
            "Buscando pluguins y mods", work, on_finished=done, on_failed=failed
        )

    def _search_again_if_pending(self) -> None:
        """Lanza la busqueda que se quedo esperando mientras se escribia."""
        if not self._pending_search or self._closed:
            return
        self._pending_search = False
        QTimer.singleShot(0, self.search)

    def _pasa_filtros(self, project: Project) -> bool:
        lado = self.side_combo.currentData()
        if lado == "servidor" and not project.works_on_server:
            return False
        if lado == "cliente" and project.works_on_server:
            return False
        return True

    def _fill(self, projects: list[Project]) -> None:
        self._projects = list(projects)
        self._aplicar_filtros()

    def _aplicar_filtros(self) -> None:
        """Repinta la tabla con el filtro de lado sin perder la seleccion."""
        seleccionado = self._selected_project()
        visibles = 0
        restaurada = False
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            for project in self._projects:
                if not self._pasa_filtros(project):
                    continue
                self._add_row(project)
                if seleccionado is not None and project == seleccionado:
                    self.table.selectRow(visibles)
                    restaurada = True
                visibles += 1
        finally:
            self.table.blockSignals(False)
        total = len(self._projects)
        if total and visibles < total:
            self.status.setText(f"Mostrando {visibles} de {total} resultados (filtros activos).")
        if seleccionado is not None and not restaurada:
            self._limpiar_seleccion()
        self._update_install_button()

    def _icono_proyecto(self, project: Project) -> QIcon:
        """Icono del proyecto (el de Modrinth) o el generico de su tipo."""
        if project.icon_url:
            datos = iconos_remotos.cached_bytes(project.icon_url)
            if datos:
                real = pixmap_de_bytes(datos, 26)
                if not real.isNull():
                    return QIcon(real)
        return QIcon(icono_plugin(26) if self.mode == "plugins" else icono_mod(26))

    def _add_row(self, project: Project) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        title = QTableWidgetItem(self._icono_proyecto(project), project.title)
        title.setData(Qt.ItemDataRole.UserRole, project)
        descripcion = project.description or "Sin descripcion."
        # Los datos vienen de la API de Modrinth: se escapan antes de usarlos en
        # una ayuda emergente (Qt las interpreta como HTML si "parecen" HTML).
        title.setToolTip(
            "<br>".join(
                escape_text(parte)
                for parte in (project.title, descripcion, "", project.page_url)
            )
        )
        if not project.works_on_server:
            title.setForeground(Qt.GlobalColor.gray)
            title.setToolTip(f"{title.toolTip()}\n\nSolo cliente: no sirve en un servidor.")
        self.table.setItem(row, 0, title)

        cargador = QTableWidgetItem(project.loader_label)
        cargador.setToolTip(
            "Cargadores que anuncia el proyecto. El servidor usa "
            + (", ".join(self.loaders) if self.loaders else "los de su tipo")
            + "."
        )
        self.table.setItem(row, 1, cargador)

        minecraft = QTableWidgetItem(project.minecraft_label)
        minecraft.setToolTip("Versiones de Minecraft que anuncia el proyecto.")
        self.table.setItem(row, 2, minecraft)

        downloads = QTableWidgetItem(f"{project.downloads:,}".replace(",", "."))
        downloads.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        downloads.setToolTip(f"{project.downloads} descargas")
        self.table.setItem(row, 3, downloads)

        actualizado = QTableWidgetItem(project.updated_label)
        actualizado.setToolTip(f"Ultima publicacion: {project.updated or 'sin datos'}")
        self.table.setItem(row, 4, actualizado)

        descripcion_celda = QTableWidgetItem(descripcion)
        descripcion_celda.setToolTip(escape_text(descripcion))
        self.table.setItem(row, 5, descripcion_celda)

    def _limpiar_seleccion(self) -> None:
        self.table.clearSelection()
        self.details_icon.set_pixmap(None)
        self.details_title.setText("Selecciona un proyecto")
        self.details_meta.setText("Los datos del proyecto apareceran aqui.")
        self.details.setText("")
        self.open_button.setEnabled(False)
        self.versions_frame.setVisible(False)
        self.versions_table.setRowCount(0)
        self._versions_for = None
        self._version_releases = []
        self._selected_release = None
        self._update_install_button()

    def _open_page(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        QDesktopServices.openUrl(QUrl(project.page_url))

    def _on_project_selected(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        self.open_button.setEnabled(True)
        self.details_icon.set_pixmap(
            self._icono_proyecto(project).pixmap(34, 34)
        )
        self.details_title.setText(project.title)
        partes = [
            project.author or "autor desconocido",
            f"{project.downloads:,} descargas".replace(",", "."),
            project.side_label,
        ]
        if project.follows:
            partes.append(f"{project.follows:,} seguimientos".replace(",", "."))
        if project.updated_label:
            partes.append(f"Actualizado: {project.updated_label}")
        self.details_meta.setText("  ·  ".join(partes))
        self.details.setText(project.description or "Sin descripcion.")
        self._prepare_versions(project)
        self._update_install_button()

    # ================================================================ versiones
    def _prepare_versions(self, project: Project) -> None:
        """Prepara la lista de versiones del proyecto recien elegido."""
        self._versions_for = project
        self._version_releases = []
        self._selected_release = None
        self._versions_loading = False
        self.versions_table.setRowCount(0)
        self.versions_frame.setVisible(True)
        self.versions_title.setText(f"Versiones de «{project.title}»")
        self.load_versions_button.setText("Ver todas las versiones")
        self.load_versions_button.setEnabled(True)
        # La consulta se lanza sola al elegir el proyecto, pero solo cuando el
        # catalogo esta a la vista: las pruebas no tocan la red sin querer.
        if self.isVisible():
            self._load_versions()
        else:
            self.status.setText(
                "Proyecto elegido. Pulsa «Ver todas las versiones» para consultarlas."
            )

    def _load_versions(self) -> None:
        project = self._selected_project()
        if project is None:
            self.status.setText("Selecciona antes un proyecto de la lista.")
            return
        if self._versions_loading and self._versions_for is project:
            return
        # Si se salta de un proyecto a otro mientras carga, la consulta anterior
        # ya no interesa: se cancela para no gastar red ni pisar el estado.
        if self._versions_task is not None:
            self._versions_task.cancel()
            self._versions_task = None
        self._versions_for = project
        self._version_releases = []
        self._selected_release = None
        self._versions_loading = True
        self.versions_table.setRowCount(0)
        self.versions_frame.setVisible(True)
        self.versions_title.setText(f"Consultando las versiones de «{project.title}»...")
        self.load_versions_button.setEnabled(False)
        self._update_install_button()
        generation = self._generation

        def work(*, context):
            context.progress("Consultando todas las versiones publicadas...")
            return modrinth.fetch_releases(project.id)

        def done(releases: list[Release]) -> None:
            self._versions_loading = False
            self.load_versions_button.setEnabled(True)
            if self._closed or generation != self._generation or self._versions_for is not project:
                return
            self._fill_versions(releases)
            self._update_install_button()

        def failed(message: str, details: str) -> None:
            self._versions_loading = False
            self.load_versions_button.setEnabled(True)
            self.versions_title.setText(f"Versiones de «{project.title}»")
            self.status.setText(f"No se pudieron consultar las versiones: {message}")
            show_error(self, "No se pudieron consultar las versiones", message, details)
            self._update_install_button()

        self._versions_task = self.runner.submit(
            f"Consultando versiones de {project.title}",
            work,
            on_finished=done,
            on_failed=failed,
        )

    @staticmethod
    def _release_mc_label(release: Release) -> str:
        valores = [str(v) for v in release.game_versions if str(v).strip()]
        if not valores:
            return "sin datos"
        visible = ", ".join(valores[:3])
        if len(valores) > 3:
            visible += f" (+{len(valores) - 3})"
        return visible

    @staticmethod
    def _release_loader_label(release: Release) -> str:
        return ", ".join(release.loaders) if release.loaders else "sin datos"

    def _fill_versions(self, releases: list[Release]) -> None:
        self._version_releases = list(releases)
        self.versions_frame.setVisible(True)
        self.versions_table.blockSignals(True)
        self.versions_table.setRowCount(0)
        compatibles = 0
        primera_compatible = -1
        try:
            for release in releases:
                compatible = modrinth.release_is_compatible(
                    release,
                    game_version=self.version,
                    loaders=self.loaders,
                )
                if compatible:
                    compatibles += 1
                row = self.versions_table.rowCount()
                self.versions_table.insertRow(row)
                nombre = QTableWidgetItem(
                    release.version_number or release.name or "sin nombre"
                )
                nombre.setData(Qt.ItemDataRole.UserRole, release)
                nombre.setData(Qt.ItemDataRole.UserRole + 1, compatible)
                nombre.setToolTip(
                    f"{release.name or release.version_number}\n"
                    f"Fichero: {release.filename}\n"
                    f"Minecraft: {', '.join(release.game_versions) or 'sin datos'}\n"
                    f"Cargador: {self._release_loader_label(release)}\n"
                    f"Tipo: {release.type_label}\n"
                    f"Publicada: {release.published_label}\n"
                    + (
                        "Compatible con este servidor."
                        if compatible
                        else "No compatible con la version o el cargador del servidor."
                    )
                )
                if not compatible:
                    nombre.setForeground(Qt.GlobalColor.gray)
                self.versions_table.setItem(row, 0, nombre)

                minecraft = QTableWidgetItem(self._release_mc_label(release))
                minecraft.setToolTip(", ".join(release.game_versions) or "sin datos")
                cargador = QTableWidgetItem(self._release_loader_label(release))
                cargador.setToolTip(", ".join(release.loaders) or "sin datos")
                tipo = QTableWidgetItem(release.type_label)
                publicada = QTableWidgetItem(release.published_label)
                publicada.setToolTip(release.published or "sin datos")
                for columna, item in ((1, minecraft), (2, cargador), (3, tipo), (4, publicada)):
                    if not compatible:
                        item.setForeground(Qt.GlobalColor.gray)
                    self.versions_table.setItem(row, columna, item)
                if compatible and primera_compatible < 0:
                    primera_compatible = row
        finally:
            self.versions_table.blockSignals(False)

        total = len(releases)
        if total:
            etiqueta = "compatible" if compatibles == 1 else "compatibles"
            self.versions_title.setText(
                f"{total} versiones publicadas · {compatibles} {etiqueta} con "
                f"{self.server_type.label if self.server_type else 'el servidor'} {self.version}"
            )
            self.load_versions_button.setText("Recargar versiones")
            if primera_compatible >= 0:
                self.versions_table.selectRow(primera_compatible)
                self._on_version_selected()
            else:
                self.status.setText(
                    f"Ninguna de las {total} versiones de «{self._versions_for.title if self._versions_for else 'este proyecto'}» "
                    f"es compatible con {self.version}. Prueba otra version del servidor."
                )
        else:
            self.versions_title.setText("Este proyecto no publica ninguna version")
            self.status.setText("El proyecto elegido no tiene versiones publicadas.")

    def _version_seleccionada(self) -> tuple[Release | None, bool]:
        # ``isHidden`` (no ``isVisible``) para que funcione tambien mientras la
        # ventana esta construida pero aun no se ha mostrado (pruebas, pestana
        # en segundo plano).
        if self.versions_frame.isHidden():
            return None, False
        row = self.versions_table.currentRow()
        if row < 0:
            return None, False
        item = self.versions_table.item(row, 0)
        if item is None:
            return None, False
        release = item.data(Qt.ItemDataRole.UserRole)
        compatible = bool(item.data(Qt.ItemDataRole.UserRole + 1))
        return (release if isinstance(release, Release) else None), compatible

    def _on_version_selected(self) -> None:
        release, compatible = self._version_seleccionada()
        if release is None:
            self._selected_release = None
            self._update_install_button()
            return
        self._selected_release = release
        if not compatible:
            self.status.setText(
                f"«{release.version_number}» no es compatible con "
                f"{self.server_type.label if self.server_type else 'este servidor'} "
                f"{self.version}. Elige una version en negro."
            )
        elif not self._busy and not self._versions_loading:
            self.status.setText(
                f"«{release.version_number}»: Minecraft "
                f"{self._release_mc_label(release)}, cargador "
                f"{self._release_loader_label(release)}. Lista para instalar."
            )
        self._update_install_button()

    # ================================================================ instalacion
    def _selected_project(self) -> Project | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, Project) else None

    def _update_install_button(self) -> None:
        project = self._selected_project()
        habilitado = not self._busy and project is not None
        if self._versions_loading:
            habilitado = False
        else:
            release, compatible = self._version_seleccionada()
            if release is not None:
                habilitado = habilitado and compatible
            elif self._version_releases:
                habilitado = habilitado and any(
                    modrinth.release_is_compatible(
                        item, game_version=self.version, loaders=self.loaders
                    )
                    for item in self._version_releases
                )
        self.install_button.setEnabled(habilitado)

    def _install_selected(self) -> None:
        if self._busy or self._closed:
            return
        project = self._selected_project()
        if project is None:
            self.status.setText("Selecciona antes un proyecto de la lista.")
            return
        release, compatible = self._version_seleccionada()
        if release is not None and not compatible:
            self.status.setText(
                "Esa version no es compatible con el servidor. Elige una en negro."
            )
            return

        if self.selection:
            if release is None:
                self.status.setText(
                    "Espera a que carguen las versiones y elige una compatible."
                )
                return
            self.content_selected.emit(ContentSelection(project, release))
            self.status.setText(
                f"Anadido «{project.title}» {release.version_number}. Puedes seguir "
                "buscando o cerrar la ventana."
            )
            return

        if self.manager is None or self.spec is None:
            self.status.setText("Este catalogo no tiene un servidor donde instalar.")
            return
        destination = self.mode
        spec = self.spec
        manager = self.manager
        loaders = self.loaders
        game_version = self.version
        elegida = release
        self._set_busy(
            True,
            (
                f"Descargando «{project.title}» {elegida.version_number}..."
                if elegida is not None
                else f"Buscando una version compatible de «{project.title}»..."
            ),
        )

        def work(*, context):
            version = elegida
            if version is None:
                releases = modrinth.fetch_releases(project.id)
                version = modrinth.choose_compatible_release(
                    releases, game_version=game_version, loaders=loaders
                )
            if version is None:
                raise modrinth.ModrinthError(
                    f"No hay una version de «{project.title}» compatible con "
                    f"{spec.type.label} {game_version}."
                )
            if project.icon_url:
                context.progress("Guardando el icono del proyecto...")
                iconos_remotos.prefetch([project.icon_url])
            context.progress(f"Descargando {version.filename}...")
            path = modrinth.install_release(
                manager.files(spec.id),
                manager.mods_inventory(spec.id),
                ContentSelection(project, version),
                destination,
                on_progress=lambda done, total: context.progress_step(done, total),
                should_cancel=lambda: context.cancelled,
            )
            return version, path.name

        def done(result) -> None:
            version, filename = result
            self._set_busy(False)
            # Se apunta aunque la ventana se haya cerrado: el fichero ya esta
            # descargado en el servidor.
            self.installed.append(filename)
            self.content_installed.emit(filename)
            if self._closed:
                return
            self.status.setText(
                f"Instalado «{filename}» ({project.title} {version.version_number})."
            )
            note = ""
            if version.dependencies:
                note = (
                    "\n\nEste proyecto indica dependencias obligatorias. Si el servidor no "
                    "arranca, instala tambien los proyectos que aparecen en su pagina de Modrinth."
                )
            # En la pestana Plugins el aviso modal seria molesto: basta con el
            # estado y con el refresco de la lista de instalados.
            if not self.embedded:
                show_info(
                    self,
                    "Contenido instalado",
                    f"Se ha instalado «{project.title}» {version.version_number}:\n\n"
                    f"{filename}\n\nReinicia el servidor para aplicarlo.{note}",
                )
            # Si se escribio en el buscador mientras se instalaba, ahora que la
            # ventana vuelve a estar libre se lanza esa busqueda.
            self._search_again_if_pending()

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            if self._closed:
                return
            self.status.setText(f"No se pudo instalar: {message}")
            show_error(self, "No se pudo instalar el contenido", message, details)
            self._search_again_if_pending()

        self._task = self.runner.submit(
            f"Instalando {project.title}", work, on_finished=done, on_failed=failed
        )

    # ================================================================ utilidades
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.search_button.setEnabled(not busy)
        # El campo sigue activo mientras se busca: asi se puede corregir el
        # texto y la busqueda se relanza al terminar la consulta en curso.
        self.sort_combo.setEnabled(not busy)
        self.side_combo.setEnabled(not busy)
        self.category_combo.setEnabled(not busy)
        self.load_more_button.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.versions_table.setEnabled(not busy)
        self.load_versions_button.setEnabled(not busy and not self._versions_loading)
        self.progress.setVisible(busy)
        if message:
            self.status.setText(message)
        self._update_install_button()
