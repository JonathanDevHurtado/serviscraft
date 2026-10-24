"""Pestana de mods: lo que hay instalado y lo que falta por conseguir.

Muestra la carpeta de mods (o pluguins) del servidor, permite activar y
desactivar sin borrar nada, eliminar, y anadir contenido desde el catalogo de
Modrinth, desde un fichero ``.jar`` del equipo o desde una URL.

Ademas analiza el registro del servidor para detectar los mods que el modpack no
pudo descargar: de cada uno ofrece el enlace a Modrinth, avisa en verde cuando el
fichero ya esta dentro del servidor y permite copiar el ``.jar`` descargado para
poder borrar la descarga original.

La pestana se presenta como dos tarjetas de piedra con una cabecera de bloque:
una para el contenido instalado y otra para lo que falta. Los chips de arriba
resumen de un vistazo cuantos ficheros hay, cuantos estan activos y cuanto ocupan.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import logs, mods
from ..core import icons as iconos_remotos
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.missing_mods import MissingMod, parse_missing_mods
from ..core.models import ServerSpec, format_bytes
from .catalog_dialog import CatalogDialog
from .common import (
    Chip,
    FlowRow,
    hint_label,
    make_button,
    plural,
    polish_table_header,
)
from .dialogs import ask_text, confirm, show_error, show_info
from .mc_icons import (
    icono_lista,
    icono_mod,
    icono_no,
    icono_pack,
    icono_plugin,
    icono_si,
    marcar_desactivado,
    pixmap_de_bytes,
)
from .mc_widgets import (
    AccentCard,
    CenteredEmpty,
    DropZone,
    EmptySlot,
    MinecraftHero,
    TexturedPage,
)
from .tasks import TaskRunner

logger = get_logger("ui.mods")

#: Color del texto de los mods que ya estan dentro del servidor.
_VERDE = QColor("#3fa34d")

_AYUDA_GENERAL = (
    "<b>Que hay en esta pestana</b><br>"
    "El contenido del servidor, separado en dos tarjetas: lo que ya esta "
    "instalado y lo que no se pudo descargar.<br><br>"
    "<b>Lo basico</b><br>"
    "«Catalogo...» busca en Modrinth y lo instala con un clic. Tambien puedes "
    "<b>arrastrar un .jar</b> a la zona de arriba, abrirlo con «Desde archivo...» "
    "o pegar una URL con «Desde enlace...».<br><br>"
    "Selecciona un fichero de la lista para activarlo o desactivarlo. "
    "<b>Desactivar no borra nada</b>: el fichero se queda en la carpeta con la "
    "terminacion «.desactivado» y puedes volver a activarlo cuando quieras.<br><br>"
    "Si el servidor esta en marcha, detenlo antes de cambiar el contenido."
)

_AYUDA_INSTALADOS = (
    "<b>Contenido instalado</b><br>"
    "Cada fila es un fichero de la carpeta «mods» o «plugins» del servidor. El "
    "icono de la izquierda es el del proyecto en Modrinth; si no se conoce, se "
    "usa el simbolo generico de mod o pluguin.<br><br>"
    "<b>Estado</b><br>"
    "«activo» significa que el servidor lo cargara al arrancar. «desactivado» "
    "significa que el fichero sigue en el disco pero no se carga.<br><br>"
    "<b>Origen</b><br>"
    "«del modpack» son los que instaló el paquete; «personalizado» los que "
    "anadiste tu. Si borras uno del modpack, puede volver en el siguiente arranque."
)

_AYUDA_FALTAN = (
    "<b>Contenido que falta</b><br>"
    "El servidor apunta en el registro que parte del contenido no se pudo "
    "descargar. «Buscar los que faltan» lee ese registro y lo reune aqui.<br><br>"
    "De cada uno se muestra su enlace de Modrinth. Abrelo, descarga el fichero y "
    "pulsa «Copiar aqui...» para dejarlo dentro del servidor. Cuando ya esta "
    "dentro, la fila se pone en verde.<br><br>"
    "El servidor debe estar detenido para copiar ficheros."
)


class ModsPanel(TexturedPage):
    """Mods instalados y mods que faltan del servidor seleccionado."""

    #: Aviso para que la ventana refresque lo que dependa de los ficheros.
    changed = Signal()

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        parent: QWidget | None = None,
        *,
        files_provider=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModsPanel")
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._running = False
        self._inventory: mods.ModsInventory | None = None
        self._missing: list[MissingMod] = []
        self._missing_analyzed = False
        self._missing_base_title = "Mods que faltan"
        #: Permite a las pruebas inyectar un selector de ficheros.
        self._files_dialog = files_provider or QFileDialog.getOpenFileName

        # La pestana «Mods» es la mas larga de la ventana (tarjetas, listas y
        # avisos). Se le da su propia area desplazable y un alto minimo comodo
        # para que el area exterior de MainWindow no anada una segunda barra:
        # el contenido crece y se desplaza aqui dentro.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("ModsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self.scroll)

        self._page = TexturedPage()
        self._page.setObjectName("ModsContent")
        self._page.setAutoFillBackground(False)
        self.scroll.setWidget(self._page)
        layout = QVBoxLayout(self._page)
        layout.setContentsMargins(12, 12, 12, 12)
        # Un poco mas de aire entre tarjetas: cada bloque (instalados, pendientes
        # y estados vacios) se lee como una seccion distinta.
        layout.setSpacing(14)
        #: Se guarda para repartir el alto entre las dos tarjetas segun tengan
        #: contenido: una tarjeta vacia no debe dejar un hueco enorme.
        self._layout = layout

        # ------------------------------------------------------------ cabecera
        self.hero = MinecraftHero(
            "Mods y complementos",
            "Anade contenido, activa lo que quieras y guarda lo demas sin borrar nada.",
            pixmap=icono_mod(44),
            accent="gold",
            help_title="Mods: como se organiza esta pestana",
            help_text=_AYUDA_GENERAL,
        )
        layout.addWidget(self.hero)

        # -------------------------------------------------------------- resumen
        self.summary_row = FlowRow(spacing=8)
        self.chip_folder = Chip("Carpeta: ?", pixmap=icono_pack(14))
        self.chip_files = Chip("Ficheros: ?", pixmap=icono_mod(14))
        self.chip_active = Chip("Activos: ?", tone="ok")
        self.chip_disabled = Chip("Desactivados: ?")
        self.chip_size = Chip("Ocupan: ?")
        self.chip_running = Chip(
            "Servidor en marcha: detenlo para cambiar",
            tone="warn",
            tooltip="Los cambios de mods se aplican al reiniciar el servidor",
        )
        for chip in (
            self.chip_folder,
            self.chip_files,
            self.chip_active,
            self.chip_disabled,
            self.chip_size,
            self.chip_running,
        ):
            self.summary_row.add(chip)
        layout.addWidget(self.summary_row)

        # ------------------------------------------------------ contenido actual
        self.card_installed = AccentCard(
            "Contenido instalado",
            pixmap=icono_pack(20),
            help_title="Mods instalados: activar, desactivar y eliminar",
            help_text=_AYUDA_INSTALADOS,
            accent="gold",
        )
        self.card_installed.body().setSpacing(9)
        self.installed_hint = hint_label(
            "Arrastra un .jar, abre el Catalogo o usa un enlace. Doble clic en "
            "un fichero para activarlo o desactivarlo: desactivar no borra nada."
        )
        self.card_installed.body().addWidget(self.installed_hint)

        self.actions_row = FlowRow(spacing=8)
        self.refresh_button = make_button(
            "Refrescar",
            icon_names=("view-refresh",),
            tooltip="Volver a leer la carpeta de mods del servidor",
        )
        self.refresh_button.clicked.connect(self.refresh)

        self.catalog_button = make_button(
            "Catalogo...",
            icon_names=("system-search", "download"),
            accent=True,
            tooltip="Buscar contenido en Modrinth e instalarlo con un clic",
        )
        self.catalog_button.clicked.connect(self._open_catalog)
        self.actions_row.add(self.catalog_button)

        self.local_button = make_button(
            "Desde archivo...",
            icon_names=("document-open",),
            tooltip="Copiar un .jar, .zip o .mrpack que ya tengas en el equipo",
        )
        self.local_button.clicked.connect(self._add_local)
        self.actions_row.add(self.local_button)

        self.url_button = make_button(
            "Desde enlace...",
            icon_names=("insert-link",),
            tooltip="Descargar el archivo desde una direccion http o https",
        )
        self.url_button.clicked.connect(self._add_url)
        self.actions_row.add(self.url_button)

        self.actions_row.add(self.refresh_button)

        self.toggle_button = make_button(
            "Activar",
            icon_names=("object-select",),
            tooltip="Activar o desactivar sin borrar el fichero",
        )
        self.toggle_button.clicked.connect(self._toggle_selected)
        self.actions_row.add(self.toggle_button)

        self.delete_button = make_button(
            "Eliminar",
            icon_names=("edit-delete", "user-trash"),
            danger=True,
            tooltip="Borrar el fichero del disco (no se puede deshacer)",
        )
        self.delete_button.clicked.connect(self._delete_selected)
        self.actions_row.add(self.delete_button)
        self.card_installed.body().addWidget(self.actions_row)

        # Arrastrar y soltar: el gesto mas rapido para instalar un .jar que se
        # acaba de descargar. La zona tambien abre el selector al pulsarla.
        self.drop_zone = DropZone(
            "Arrastra aqui tus .jar",
            "Suelta uno o varios ficheros, o pulsa para elegirlos. Tambien vale .zip y .mrpack.",
            pixmap=icono_mod(42),
        )
        self.drop_zone.clicked.connect(self._add_local)
        self.drop_zone.files_dropped.connect(self._add_dropped)
        self.card_installed.body().addWidget(self.drop_zone)

        # Leyenda con los iconos de verdad: la lista se entiende de un vistazo.
        self.legend = FlowRow(spacing=14)
        self.card_installed.body().addWidget(self.legend)

        self.status = hint_label("")
        self.card_installed.body().addWidget(self.status)

        # El estado vacio va en su propio bloque, separado de las herramientas
        # con una linea: no parece un aviso pegado a los botones.
        self.installed_separator = self._separador("ModsInstalledSeparator")
        self.card_installed.body().addWidget(self.installed_separator)
        self.installed_empty = EmptySlot(
            "Todavia no hay contenido",
            "Arrastra un .jar a la zona de arriba o abre el Catalogo para instalar "
            "un mod de Modrinth.",
            pixmap=icono_mod(46),
        )
        self.card_installed.body().addWidget(self.installed_empty)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("ModsTable")
        self.table.setHorizontalHeaderLabels(["Fichero", "Estado", "Origen", "Tamano"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        # Cada fila lleva el icono del proyecto (o el del tipo de contenido), asi
        # que las filas son un poco mas altas que el texto.
        self.table.setIconSize(QSize(24, 24))
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(lambda _index: self._toggle_selected())
        polish_table_header(self.table)
        self.table.setMinimumHeight(170)
        self.card_installed.body().addWidget(self.table, 1)
        layout.addWidget(self.card_installed, 1)

        # ------------------------------------------------------- mods que faltan
        self.card_missing = AccentCard(
            "Mods que faltan",
            pixmap=icono_lista(20),
            help_title="Contenido que el servidor no pudo descargar",
            help_text=_AYUDA_FALTAN,
            accent="blue",
        )
        self.missing_title = self.card_missing.title_label
        self.card_missing.body().setSpacing(9)
        self.missing_hint = hint_label(
            "Analiza el registro del servidor para ver que contenido no se pudo "
            "descargar. De cada uno se muestra su enlace de Modrinth y se avisa en "
            "verde cuando el fichero ya esta dentro del servidor."
        )
        self.card_missing.body().addWidget(self.missing_hint)

        self.missing_actions = FlowRow(spacing=8)
        self.analyze_button = make_button(
            "Buscar los que faltan",
            icon_names=("system-search",),
            tooltip="Lee el registro del servidor y busca el contenido que no se pudo descargar",
        )
        self.analyze_button.clicked.connect(self.analyze_logs)
        self.missing_actions.add(self.analyze_button)

        self.open_link_button = make_button(
            "Ver en Modrinth",
            icon_names=("internet-web-browser",),
            tooltip="Abrir en el navegador la pagina del mod que falta",
        )
        self.open_link_button.clicked.connect(self._open_missing_link)
        self.missing_actions.add(self.open_link_button)

        self.copy_button = make_button(
            "Copiar aqui...",
            icon_names=("document-save",),
            accent=True,
            tooltip="Copiar el .jar descargado dentro del servidor (y poder borrar la descarga)",
        )
        self.copy_button.clicked.connect(self._copy_missing_file)
        self.missing_actions.add(self.copy_button)
        self.card_missing.body().addWidget(self.missing_actions)

        self.missing_separator = self._separador("ModsMissingSeparator")
        self.card_missing.body().addWidget(self.missing_separator)
        self.missing_empty = EmptySlot(
            "Sin mods pendientes por ahora",
            "Pulsa «Buscar los que faltan» y Serviscraft revisara el registro del "
            "servidor para ver si no se pudo descargar algo.",
            pixmap=icono_si(46),
        )
        self.card_missing.body().addWidget(self.missing_empty)

        self.missing_table = QTableWidget(0, 3)
        self.missing_table.setObjectName("MissingModsTable")
        self.missing_table.setHorizontalHeaderLabels(["Mod", "Estado", "Enlace"])
        self.missing_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.missing_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.missing_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.missing_table.verticalHeader().setVisible(False)
        self.missing_table.setIconSize(QSize(20, 20))
        self.missing_table.verticalHeader().setDefaultSectionSize(30)
        self.missing_table.setAlternatingRowColors(True)
        self.missing_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.missing_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.missing_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.missing_table.setMaximumHeight(170)
        self.missing_table.setMinimumHeight(90)
        self.missing_table.itemSelectionChanged.connect(self._update_missing_actions)
        self.missing_table.doubleClicked.connect(lambda _index: self._open_missing_link())
        polish_table_header(self.missing_table)
        self.card_missing.body().addWidget(self.missing_table, 1)
        layout.addWidget(self.card_missing, 1)

        self.empty = CenteredEmpty(
            "Elige un servidor",
            "Selecciona uno en la lista de la izquierda para ver sus mods, "
            "arrastrar ficheros nuevos y activar o desactivar lo que ya tiene.",
            pixmap=icono_pack(64),
        )
        layout.addWidget(self.empty, 1)

        self.set_server(None, running=False)

    @staticmethod
    def _separador(nombre: str) -> QFrame:
        """Linea fina que separa el contenido de un estado vacio."""
        linea = QFrame()
        linea.setObjectName(nombre)
        linea.setFixedHeight(1)
        linea.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        linea.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        return linea

    def _leyenda(self, icono: QPixmap, texto: str) -> QWidget:
        """Icono + palabra: explica la lista de un vistazo (tambien para niños)."""
        caja = QWidget()
        fila = QHBoxLayout(caja)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(6)
        imagen = QLabel()
        imagen.setPixmap(icono)
        fila.addWidget(imagen)
        letra = QLabel(texto)
        letra.setObjectName("Hint")
        fila.addWidget(letra)
        return caja

    def _rellenar_leyenda(self, es_pluguins: bool) -> None:
        """Explica solo los iconos que puede tener este servidor."""
        self.legend.clear()
        if es_pluguins:
            self.legend.add(self._leyenda(icono_plugin(), "pluguin"))
        else:
            self.legend.add(self._leyenda(icono_mod(), "mod"))
        self.legend.add(self._leyenda(marcar_desactivado(icono_mod()), "desactivado (no se borra)"))

    def _poner_icono_hero(self, pixmap: QPixmap) -> None:
        if pixmap is None or pixmap.isNull():
            return
        self.hero.icon_label.setPixmap(
            pixmap.scaled(
                40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )
        self.hero.icon_label.setVisible(True)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        """Alto minimo comodo: el area exterior no necesita otra barra.

        La barra vertical vive dentro de esta pestana. Si el panel pidiera todo
        el alto de sus tarjetas, MainWindow anadiria una segunda barra exterior
        y el contenido se desplazaria dos veces. Con 430 px la ventana normal
        usa solo la barra interior; en ventanas muy bajas sigue habiendo barra
        exterior para llegar al panel completo.
        """
        hint = super().minimumSizeHint()
        return QSize(hint.width(), max(hint.height(), 430))

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        """En ventanas estrechas deja sitio al nombre del fichero.

        «Estado», «Origen» y «Tamano» ocupaban tanto que los nombres se
        quedaban en «create-...». Por debajo de 620 px se ocultan las columnas
        secundarias (el dato sigue en el tooltip de la fila) y la primera
        columna se queda con el ancho. Al ensanchar vuelven a aparecer.
        """
        super().resizeEvent(event)
        # Qt puede enviar el primer resize mientras se construye el panel; las
        # tablas de «faltan» todavia no existen en ese momento.
        if not hasattr(self, "missing_table"):
            return
        estrecho = self.width() < 620
        self.table.setColumnHidden(2, estrecho)
        self.table.setColumnHidden(3, estrecho)
        self.missing_table.setColumnHidden(2, estrecho)
        self.missing_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch
            if estrecho
            else QHeaderView.ResizeMode.ResizeToContents,
        )

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._running != running
        if cambio:
            self.table.setRowCount(0)
            self.missing_table.setRowCount(0)
            self._missing = []
            self._missing_analyzed = False
            self.status.clear()
        self._spec = spec
        self._running = running
        if spec is None:
            self._inventory = None
        else:
            self._inventory = mods.ModsInventory(
                self.manager.store,
                spec.id,
                folder=mods.folder_for(spec),
                modpack=bool(spec.modpack) or spec.type.value == "MODRINTH",
            )
        has_server = spec is not None
        if has_server:
            es_pluguins = mods.folder_for(spec) == "plugins"
            self._rellenar_leyenda(es_pluguins)
            self._poner_icono_hero(icono_plugin(44) if es_pluguins else icono_mod(44))
            nombre_carpeta = "plugins" if es_pluguins else "mods"
            tipo = "Pluguins" if es_pluguins else "Mods"
            self.hero.set_title(f"{tipo} de «{spec.name}»")
            self.hero.set_subtitle(
                f"Contenido de la carpeta «{nombre_carpeta}»: anade, activa o elimina sin miedo."
            )
            self.card_installed.set_title(f"{tipo} instalados")
            self._missing_base_title = f"{tipo} que faltan"
            self.card_missing.set_title(self._missing_base_title)
            self.chip_folder.set_text(f"Carpeta: {nombre_carpeta}")
            self.chip_folder.setToolTip(f"El servidor guarda el contenido en la carpeta «{nombre_carpeta}»")
        else:
            self.hero.set_title("Mods y complementos")
            self.hero.set_subtitle("Selecciona un servidor a la izquierda para ver su contenido.")
            self._missing_base_title = "Mods que faltan"
            self.card_missing.set_title(self._missing_base_title)
            self._reset_resumen()
        self.hero.setVisible(True)
        self.summary_row.setVisible(has_server)
        self.card_installed.setVisible(has_server)
        self.card_missing.setVisible(has_server)
        self.empty.setVisible(not has_server)
        if has_server and cambio_estado:
            self.refresh()

    def _reset_resumen(self) -> None:
        self.chip_folder.set_text("Carpeta: ?")
        self.chip_files.set_text("Ficheros: ?")
        self.chip_active.set_text("Activos: ?")
        self.chip_active.set_tone("ok")
        self.chip_disabled.set_text("Desactivados: ?")
        self.chip_disabled.set_tone("")
        self.chip_size.set_text("Ocupan: ?")
        self.chip_running.setVisible(False)

    def refresh(self) -> None:
        """Vuelve a leer la carpeta de mods del servidor."""
        if self._inventory is None or self._spec is None:
            return
        inventario = self._inventory
        try:
            entradas = inventario.list_mods()
        except ServiscraftError as exc:  # pragma: no cover - carpeta ilegible
            show_error(self, "No se pudieron leer los mods", str(exc))
            return
        self.table.setRowCount(0)
        es_pluguins = mods.folder_for(self._spec) == "plugins"
        for entrada in entradas:
            row = self.table.rowCount()
            self.table.insertRow(row)
            nombre = QTableWidgetItem(self._icono_entrada(entrada, es_pluguins), entrada.filename)
            nombre.setData(Qt.ItemDataRole.UserRole, entrada.filename)
            detalle = entrada.title or entrada.base_name
            nombre.setToolTip(
                f"{entrada.filename}\n{detalle}\n"
                f"{'Activo' if entrada.enabled else 'Desactivado (el fichero sigue en el disco)'}\n"
                f"Origen: {entrada.origin_label}. Tamano: {entrada.size_label}."
            )
            if not entrada.enabled:
                nombre.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 0, nombre)
            estado = QTableWidgetItem(
                QIcon(icono_si(16) if entrada.enabled else icono_no(16)),
                "activo" if entrada.enabled else "desactivado",
            )
            estado.setForeground(QColor("#2E7D3A") if entrada.enabled else QColor("#A87B24"))
            fuente = estado.font()
            fuente.setBold(True)
            estado.setFont(fuente)
            self.table.setItem(row, 1, estado)
            origen = QTableWidgetItem(entrada.origin_label)
            origen.setForeground(
                self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            )
            self.table.setItem(row, 2, origen)
            tamano = QTableWidgetItem(entrada.size_label)
            tamano.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tamano.setForeground(
                self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            )
            self.table.setItem(row, 3, tamano)
        self._update_status(entradas)
        self._update_actions()
        self._update_missing_rows()

    def _icono_entrada(self, entrada, es_pluguins: bool) -> QIcon:
        """Icono del fichero: el del proyecto si se conoce, si no el del tipo.

        Es lo mismo que hace Prism Launcher: cada mod o pluguin se ve con su
        icono en la lista, y los que no se han instalado desde el catalogo llevan
        el simbolo generico (pieza de puzle para mods, enchufe para pluguins).
        """
        tamano = 24
        generico = icono_plugin(tamano) if es_pluguins else icono_mod(tamano)
        icono = generico
        if entrada.icon_url:
            datos = iconos_remotos.cached_bytes(entrada.icon_url)
            if datos:
                real = pixmap_de_bytes(datos, tamano)
                if not real.isNull():
                    icono = real
        if not entrada.enabled:
            icono = marcar_desactivado(icono)
        return QIcon(icono)

    def _update_status(self, entradas) -> None:
        if self._spec is None:
            return
        carpeta = mods.folder_for(self._spec)
        activos = sum(1 for entrada in entradas if entrada.enabled)
        desactivados = len(entradas) - activos
        total = sum(entrada.size_bytes for entrada in entradas)
        partes = [
            f"{plural(len(entradas), 'fichero', 'ficheros')} en «{carpeta}»: "
            f"{plural(activos, 'activo', 'activos')}, "
            f"{plural(desactivados, 'desactivado', 'desactivados')} "
            f"({format_bytes(total)})."
        ]
        if not entradas:
            partes.append(
                "La carpeta esta vacia. Pulsa «Catalogo...» para instalar contenido de Modrinth."
            )
        if self._running:
            partes.append(
                "El servidor esta en marcha: detenlo para que los cambios surtan efecto."
            )
        self.status.setText(" ".join(partes))

        # Resumen de un vistazo: los mismos numeros, en chips faciles de leer.
        self.chip_files.set_text(f"Ficheros: {len(entradas)}")
        self.chip_files.setToolTip(
            f"{plural(len(entradas), 'fichero', 'ficheros')} en la carpeta «{carpeta}»"
        )
        self.chip_active.set_text(f"Activos: {activos}")
        self.chip_active.set_tone("ok" if activos else "")
        self.chip_active.setToolTip(f"{plural(activos, 'fichero activo', 'ficheros activos')}")
        self.chip_disabled.set_text(f"Desactivados: {desactivados}")
        self.chip_disabled.set_tone("warn" if desactivados else "")
        self.chip_disabled.setToolTip(
            f"{plural(desactivados, 'fichero desactivado', 'ficheros desactivados')}; "
            "los ficheros siguen en el disco"
        )
        self.chip_size.set_text(f"Ocupan: {format_bytes(total)}")
        self.chip_size.setToolTip(f"Espacio total que ocupa el contenido: {format_bytes(total)}")
        self.chip_running.setVisible(self._running)

        # Una tabla sin filas parece un fallo de carga: se cambia por un aviso
        # con un objeto y una pista de que hacer.
        es_pluguins = mods.folder_for(self._spec) == "plugins"
        hay_contenido = bool(entradas)
        self.table.setVisible(hay_contenido)
        # Con la carpeta vacia sobran la leyenda, el resumen duplicado y la
        # pista de doble clic: el estado vacio ya dice que hacer. Asi el aviso
        # queda como una seccion propia y no como un apano bajo los botones.
        self.installed_hint.setVisible(hay_contenido)
        self.legend.setVisible(hay_contenido)
        self.status.setVisible(hay_contenido)
        self.installed_separator.setVisible(not hay_contenido)
        self.installed_empty.setVisible(not hay_contenido)
        self.installed_empty.set_texts(
            "Todavia no hay pluguins" if es_pluguins else "Todavia no hay mods",
            "Arrastra un .jar a la zona de arriba o abre el Catalogo para instalar "
            + ("un pluguin de Modrinth." if es_pluguins else "un mod de Modrinth."),
        )
        self.installed_empty.set_pixmap(icono_plugin(46) if es_pluguins else icono_mod(46))
        self._ajustar_reparto()

    def _ajustar_reparto(self) -> None:
        """Da el alto sobrante solo a las tarjetas que tienen lista.

        Sin esto, la tarjeta «Mods que faltan» vacia se quedaba con media
        ventana y dejaba una tabla en blanco enorme.
        """
        self._layout.setStretchFactor(
            self.card_installed, 1 if self.table.rowCount() else 0
        )
        self._layout.setStretchFactor(
            self.card_missing, 1 if self.missing_table.rowCount() else 0
        )

    # =============================================================== acciones
    def _selected_filename(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole) or item.text()

    def _update_actions(self) -> None:
        hay_seleccion = self._selected_filename() is not None
        permitido = hay_seleccion and not self._running
        self.toggle_button.setEnabled(permitido)
        self.delete_button.setEnabled(permitido)
        self.catalog_button.setEnabled(not self._running)
        self.local_button.setEnabled(not self._running)
        self.url_button.setEnabled(not self._running)
        self.refresh_button.setEnabled(True)
        self.drop_zone.setEnabled(not self._running)
        if self._running:
            self.drop_zone.set_texts(
                "El servidor esta en marcha",
                "Detenlo para arrastrar, elegir o quitar contenido.",
            )
        else:
            self.drop_zone.set_texts(
                "Arrastra aqui tus .jar",
                "Suelta uno o varios ficheros, o pulsa para elegirlos. Tambien vale .zip y .mrpack.",
            )
        # El boton dice lo que va a hacer con el fichero elegido: mas claro que
        # un «Activar o desactivar» que obliga a pensar.
        if not hay_seleccion:
            self.toggle_button.setText("Activar/Desactivar")
        else:
            self.toggle_button.setText("Desactivar" if self._selected_enabled() else "Activar")
        self.toggle_button.setToolTip(
            "Deten el servidor para cambiar los mods."
            if self._running
            else "Activar o desactivar sin borrar el fichero"
        )

    def _selected_enabled(self) -> bool:
        """Esta activo el fichero elegido? (para que el boton diga que hara)."""
        fila = self.table.currentRow()
        if fila < 0:
            return True
        estado = self.table.item(fila, 1)
        return estado is None or estado.text().strip().lower() == "activo"

    def _open_catalog(self) -> None:
        if self._spec is None:
            return
        mode = mods.folder_for(self._spec)
        dialog = CatalogDialog(self.manager, self.runner, self._spec, mode, self)
        dialog.exec()
        if dialog.installed:
            show_info(
                self,
                "Contenido instalado",
                "Se ha instalado:\n\n"
                + "\n".join(f"  • {nombre}" for nombre in dialog.installed)
                + "\n\nReinicia el servidor para aplicarlo.",
            )
        self.refresh()
        self.changed.emit()

    def _add_local(self) -> None:
        if self._inventory is None:
            return
        ruta, _filtro = self._files_dialog(
            self,
            "Elige el mod o pluguin que quieres copiar",
            "",
            "Contenido de Minecraft (*.jar *.zip *.mrpack);;Todos los ficheros (*)",
        )
        if not ruta:
            return
        try:
            destino = self._inventory.add_file(Path(ruta))
        except ServiscraftError as exc:
            show_error(self, "No se pudo anadir el fichero", str(exc))
            return
        logger.info("Mod local anadido: %s", destino)
        self.refresh()
        self.changed.emit()

    def _add_dropped(self, rutas: list[str]) -> None:
        """Copia los ficheros soltados sobre la zona de arrastre."""
        if self._inventory is None or not rutas:
            return
        if self._running:
            show_info(
                self,
                "El servidor esta en marcha",
                "Deten el servidor antes de anadir mods o pluguins.",
            )
            return
        inventario = self._inventory
        anadidos: list[str] = []
        errores: list[str] = []
        for ruta in rutas:
            try:
                destino = inventario.add_file(Path(ruta))
            except ServiscraftError as exc:
                errores.append(f"{Path(ruta).name}: {exc}")
                continue
            anadidos.append(destino.name)
        self.refresh()
        self.changed.emit()
        if anadidos:
            lista = "\n".join(f"  • {nombre}" for nombre in anadidos)
            show_info(
                self,
                "Contenido anadido",
                f"Se han copiado {plural(len(anadidos), 'fichero', 'ficheros')}:\n\n"
                f"{lista}\n\nReinicia el servidor para aplicarlo.",
            )
        if errores:
            show_error(
                self,
                "No se pudieron copiar todos los ficheros",
                "\n".join(errores),
            )

    def _add_url(self) -> None:
        if self._inventory is None:
            return
        url = ask_text(
            self,
            "Anadir un mod desde una URL",
            "Direccion http o https del fichero .jar:\n\n"
            "Se descarga directamente a la carpeta del servidor y se comprueba que "
            "sea un JAR o ZIP valido.",
            placeholder="https://ejemplo.com/mi-mod.jar",
        )
        if not url:
            return
        inventario = self._inventory
        spec = self._spec
        assert spec is not None

        def work(*, context) -> str:
            context.progress("Descargando el mod...")
            destino = inventario.add_url(
                url,
                files=self.manager.files(spec.id),
                on_progress=lambda hecho, total: context.progress_step(hecho, total),
                should_cancel=lambda: context.cancelled,
            )
            return destino.name

        def done(nombre: str) -> None:
            if self._spec is None or self._spec.id != spec.id:
                return
            self.status.setText(f"Anadido «{nombre}». Reinicia el servidor para aplicarlo.")
            self.refresh()
            self.changed.emit()

        def failed(message: str, details: str) -> None:
            if self._spec is not None and self._spec.id == spec.id:
                show_error(self, "No se pudo descargar el mod", message, details)

        self.runner.submit("Descargando mod", work, on_finished=done, on_failed=failed)

    def _toggle_selected(self) -> None:
        nombre = self._selected_filename()
        if nombre is None or self._inventory is None or self._running:
            return
        try:
            entradas = {entrada.filename: entrada for entrada in self._inventory.list_mods()}
            entrada = entradas.get(nombre)
            if entrada is None:
                return
            self._inventory.set_enabled(nombre, not entrada.enabled)
        except ServiscraftError as exc:
            show_error(self, "No se pudo cambiar el mod", str(exc))
            return
        self.refresh()
        self.changed.emit()

    def _delete_selected(self) -> None:
        nombre = self._selected_filename()
        if nombre is None or self._inventory is None or self._running:
            return
        try:
            entradas = {entrada.filename: entrada for entrada in self._inventory.list_mods()}
        except ServiscraftError as exc:
            show_error(self, "No se pudieron leer los mods", str(exc))
            return
        entrada = entradas.get(nombre)
        aviso = ""
        if entrada is not None and not entrada.custom and self._inventory.modpack:
            aviso = (
                "\n\nOjo: este fichero vino con el modpack. Si lo eliminas, el modpack "
                "volvera a instalarlo en el siguiente arranque."
            )
        if not confirm(
            self,
            "Eliminar el mod",
            f"¿Eliminar «{nombre}» de la carpeta del servidor?{aviso}\n\n"
            "Si solo quieres dejarlo inactivo, usa «Activar o desactivar» (no borra nada).",
            confirm_label="Eliminar",
            destructive=True,
        ):
            return
        try:
            self._inventory.delete(nombre)
        except ServiscraftError as exc:
            show_error(self, "No se pudo eliminar el mod", str(exc))
            return
        self.refresh()
        self.changed.emit()

    # ==================================================== mods que faltan
    def analyze_logs(self) -> None:
        """Lee el registro del servidor y busca mods que no se pudieron descargar."""
        if self._spec is None or self.manager is None:
            return
        spec = self._spec
        self.status.setText("Analizando el registro del servidor...")

        def work(*, context) -> str:
            context.progress("Leyendo el registro del servidor...")
            partes: list[str] = []
            try:
                partes.append(self.manager.recent_logs(spec.id, tail=4000))
            except ServiscraftError as exc:
                logger.debug("Sin registro del contenedor: %s", exc)
            try:
                partes.append(logs.latest_log(self.manager.files(spec.id)))
            except ServiscraftError as exc:  # pragma: no cover - defensivo
                logger.debug("Sin latest.log: %s", exc)
            return "\n".join(parte for parte in partes if parte)

        def done(texto: str) -> None:
            # Si se cambio de servidor mientras se leia el registro, el
            # resultado pertenece al anterior y no debe pisar el nuevo.
            if self._spec is None or self._spec.id != spec.id:
                return
            self._missing = parse_missing_mods(texto)
            self._missing_analyzed = True
            self._update_missing_rows()
            es_pluguins = mods.folder_for(spec) == "plugins"
            singular = "pluguin" if es_pluguins else "mod"
            plural_ = "pluguins" if es_pluguins else "mods"
            if self._missing:
                faltan = sum(1 for mod in self._missing if not self._esta_instalado(mod))
                self.status.setText(
                    f"El registro menciona {plural(len(self._missing), singular, plural_)}: "
                    f"{faltan} por conseguir. Abre el enlace, descarga el fichero y usa "
                    "«Copiar el .jar aqui»."
                )
            else:
                self.status.setText(
                    f"El registro no menciona {plural_} que falten. Si el servidor no "
                    "arranca, revisa el registro completo en la pestana «Registros»."
                )

        def failed(message: str, details: str) -> None:
            if self._spec is not None and self._spec.id == spec.id:
                self.status.setText(f"No se pudo analizar el registro: {message}")

        self.runner.submit(
            "Analizando el registro",
            work,
            on_finished=done,
            on_failed=failed,
            track_busy=False,
        )

    def _esta_instalado(self, mod: MissingMod) -> bool:
        if self._inventory is None:
            return False
        try:
            instalados = self._inventory.installed_names()
        except ServiscraftError:  # pragma: no cover - carpeta ilegible
            return False
        return mods.find_installed(mod.name, instalados) is not None

    def _update_missing_rows(self) -> None:
        self.missing_table.setRowCount(0)
        for mod in self._missing:
            row = self.missing_table.rowCount()
            self.missing_table.insertRow(row)
            instalado = self._esta_instalado(mod)
            nombre = QTableWidgetItem(
                QIcon(icono_si(16) if instalado else icono_no(16)), mod.name
            )
            nombre.setData(Qt.ItemDataRole.UserRole, mod)
            nombre.setToolTip(
                f"{mod.detail or mod.name}\nEnlace: {mod.link}"
            )
            if instalado:
                nombre.setForeground(_VERDE)
            self.missing_table.setItem(row, 0, nombre)

            estado = QTableWidgetItem("ya esta en el servidor" if instalado else "falta")
            estado.setForeground(_VERDE if instalado else QColor("#A87B24"))
            fuente = estado.font()
            fuente.setBold(True)
            estado.setFont(fuente)
            self.missing_table.setItem(row, 1, estado)

            enlace = QTableWidgetItem(mod.link)
            enlace.setToolTip(f"Abrir en el navegador:\n{mod.link}")
            enlace.setForeground(
                self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            )
            self.missing_table.setItem(row, 2, enlace)
        if self._missing:
            self.card_missing.set_title(
                f"{self._missing_base_title} ({len(self._missing)})"
            )
        else:
            self.card_missing.set_title(self._missing_base_title)

        # Sin resultados no se enseña una tabla vacia: se explica que hacer.
        hay_pendientes = bool(self._missing)
        self.missing_table.setVisible(hay_pendientes)
        self.missing_hint.setVisible(hay_pendientes)
        self.missing_separator.setVisible(not hay_pendientes)
        self.missing_empty.setVisible(not hay_pendientes)
        es_pluguins = self._spec is not None and mods.folder_for(self._spec) == "plugins"
        sustantivo = "pluguins" if es_pluguins else "mods"
        if self._missing_analyzed:
            self.missing_empty.set_texts(
                "Todo en orden",
                f"El registro no menciona {sustantivo} que falten. Si el servidor no "
                "arranca, revisa el registro completo en la pestana «Registros».",
            )
            self.missing_empty.set_pixmap(icono_si(46))
        else:
            self.missing_empty.set_texts(
                f"Sin {sustantivo} pendientes por ahora",
                "Pulsa «Buscar los que faltan» y Serviscraft revisara el registro del "
                "servidor para ver si no se pudo descargar algo.",
            )
            self.missing_empty.set_pixmap(icono_lista(46))
        self._update_missing_actions()
        self._ajustar_reparto()

    def _selected_missing(self) -> MissingMod | None:
        row = self.missing_table.currentRow()
        if row < 0:
            return None
        item = self.missing_table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, MissingMod) else None

    def _update_missing_actions(self) -> None:
        permitido = self._selected_missing() is not None
        self.open_link_button.setEnabled(permitido)
        self.copy_button.setEnabled(permitido and not self._running)
        self.copy_button.setToolTip(
            "Deten el servidor para copiar ficheros." if self._running else "Copia el .jar descargado"
        )

    def _open_missing_link(self) -> None:
        mod = self._selected_missing()
        if mod is None:
            return
        QDesktopServices.openUrl(QUrl(mod.link))

    def _copy_missing_file(self) -> None:
        """Copia dentro del servidor un .jar descargado a mano."""
        mod = self._selected_missing()
        if mod is None or self._inventory is None or self._running:
            return
        ruta, _filtro = self._files_dialog(
            self,
            f"Elige el fichero de «{mod.name}» que has descargado",
            "",
            "Mods (*.jar *.zip);;Todos los ficheros (*)",
        )
        if not ruta:
            return
        try:
            destino = self._inventory.add_file(Path(ruta))
        except ServiscraftError as exc:
            show_error(self, "No se pudo copiar el fichero", str(exc))
            return
        logger.info("Mod %s copiado al servidor desde %s", destino.name, ruta)
        self.refresh()
        self.changed.emit()
        show_info(
            self,
            "Mod copiado al servidor",
            f"«{destino.name}» ya esta en la carpeta «{self._inventory.folder}» del servidor.\n\n"
            "Ya puedes borrar el fichero que habias descargado. Reinicia el servidor "
            "para que lo cargue.",
        )
