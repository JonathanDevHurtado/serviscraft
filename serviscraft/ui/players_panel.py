"""Pestana de jugadores: quien esta conectado, lista blanca y operadores.

La consulta de jugadores conectados y las acciones (OP, expulsar, lista blanca)
se hacen por consola RCON, que solo responde con el servidor en marcha. La lista
blanca y los operadores se leen ademas de los ficheros del servidor, asi que la
pestana sigue mostrando informacion util cuando el servidor esta detenido.

La pantalla se organiza como una ficha de servidor:

* La cabecera resume de que servidor se trata.
* «Acceso al servidor» reune la lista blanca y la invitacion rapida.
* «Jugadores» muestra una tabla limpia, con avatares y estados en forma de
  etiquetas, sin repetir el mismo icono en cada celda.
* «Acciones» aparece debajo y cambia segun el jugador elegido.
"""

from __future__ import annotations

from functools import lru_cache
from hashlib import sha1

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import ValidationError
from ..core.inventory import PlayerInventory
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from ..core.players import (
    ACTIONS_BY_KEY,
    PLAYER_ACTIONS,
    PlayersSnapshot,
    PlayerAction,
    validate_player_name,
)
from ..core.textures import cached_skin, fetch_skin, offline
from .common import (
    Chip,
    FlowRow,
    WrappingLabel,
    hint_label,
    make_button,
    plural,
    polish_table_header,
)
from .dialogs import confirm, show_error
from .inventory_dialog import InventoryDialog
from .mc_icons import (
    bloque_bedrock,
    icono_escudo,
    icono_jugador,
    icono_jugador_duda,
    icono_lista,
    icono_pase,
)
from .mc_widgets import (
    AccentCard,
    CenteredEmpty,
    EmptySlot,
    IconSlot,
    MinecraftHero,
    TexturedPage,
)
from .players_manager_dialog import PlayersManagerDialog
from .skin_view import head_pixmap
from .tasks import TaskRunner

logger = get_logger("ui.players")

#: Color con el que se marca lo bueno (conectado, operador...) y lo malo (bloqueado).
_BUENO = "#2e7d32"
_MALO = "#b3261e"


def _is_bedrock(name: str) -> bool:
    """True si el nombre es de un jugador de Bedrock (Floodgate usa un punto)."""
    return str(name or "").startswith(".")

#: Texto de los botones. Se evitan las palabras tecnicas («OP», «whitelist»)
#: salvo en las explicaciones largas, para que la pantalla se entienda sola.
_ACTION_LABELS: dict[str, str] = {
    "op": "Hacer administrador",
    "deop": "Quitar administrador",
    "whitelist_add": "Invitar al servidor",
    "whitelist_remove": "Quitar invitacion",
    "kick": "Sacar del juego",
    "ban": "Bloquear entrada",
    "pardon": "Quitar bloqueo",
}

_ACTION_TIPS: dict[str, str] = {
    "op": "Deja que este jugador use los comandos de administrador del juego",
    "deop": "Quita los permisos de administrador, sin sacarlo del servidor",
    "whitelist_add": "Aparecera en la lista de invitados y podra entrar",
    "whitelist_remove": "Dejara de estar en la lista de invitados",
    "kick": "Lo saca del juego ahora; puede volver a entrar",
    "ban": "No podra volver a entrar hasta que le quites el bloqueo",
    "pardon": "Vuelve a permitirle la entrada",
}

_AYUDA = (
    "<b>En el juego</b> dice quien esta jugando ahora mismo."
    "<br><br><b>Invitado</b> es un jugador apuntado en la lista blanca. Si la "
    "lista blanca esta activada, solo entran los invitados; si esta desactivada, "
    "puede entrar cualquiera que tenga la direccion del servidor."
    "<br><br><b>Administrador</b> es un jugador con poderes especiales dentro "
    "del juego (puede cambiar el modo de juego, teletransportarse o dar objetos). "
    "Da estos permisos solo a personas de confianza."
    "<br><br><b>Bloqueado</b> es un jugador al que se le ha cerrado la puerta: no "
    "puede entrar hasta que le quites el bloqueo."
    "<br><br><b>Los botones de abajo</b> cambian segun el jugador elegido. Con el "
    "servidor encendido los cambios se aplican al momento; con el servidor "
    "detenido se guardan y valen desde el proximo arranque. «Sacar del juego» y "
    "«Ver inventario» necesitan el servidor encendido."
    "<br><br><b>Ver inventario</b> enseña la mochila, la armadura y la barra "
    "rapida del jugador elegido. Solo funciona si esta conectado."
    "<br><br><b>Jugadores de Bedrock</b>: Geyser les pone un punto delante del "
    "nombre (por ejemplo «.Steve»). Es normal y se gestionan igual que los de "
    "Java: el punto forma parte del nombre que entiende el servidor."
)


@lru_cache(maxsize=256)
def _avatar(name: str, size: int = 26) -> QPixmap:
    """Cara de respaldo mientras llega la skin real del jugador.

    Se dibuja como una cabeza de Minecraft, en pixeles y sin suavizado. El
    color del pelo se calcula a partir del nombre, de modo que cada jugador
    tiene una cara estable y reconocible incluso sin conexion. Cuando la skin
    esta en la cache (o termina de descargarse), ocupa su sitio.
    """
    limpio = (name or "?").strip() or "?"
    digest = sha1(limpio.lower().encode("utf-8")).digest()
    pelo = QColor.fromHsv(int(digest[0] * 360 / 255), 120, 112)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    unidad = size / 8.0

    def celda(x: float, y: float, ancho: float, alto: float, color: str) -> None:
        painter.fillRect(
            QRectF(x * unidad, y * unidad, ancho * unidad, alto * unidad),
            QColor(color),
        )

    # Marco oscuro, como la ranura de un inventario.
    celda(0, 0, 8, 8, "#3b2a1a")
    # Cara y pelo (el tono del pelo cambia con el nombre, sin aleatoriedad).
    celda(1, 1, 6, 6, "#c98f66")
    celda(1, 1, 6, 2, pelo.name())
    celda(1, 3, 1, 1, pelo.name())
    celda(6, 3, 1, 1, pelo.name())
    # Ojos y boca.
    celda(2, 4, 1, 1, "#ffffff")
    celda(5, 4, 1, 1, "#ffffff")
    celda(2, 4, 0.5, 0.6, "#2b4a8b")
    celda(5.5, 4, 0.5, 0.6, "#2b4a8b")
    celda(3, 6, 2, 0.7, "#8a5f3f")
    painter.end()
    return pixmap


class _RoleBadgeDelegate(QStyledItemDelegate):
    """Pinta las columnas de estado como etiquetas de color.

    El texto real del elemento sigue siendo «Si» o «No» (la tabla se puede leer
    y probar como antes), pero en pantalla se muestra una etiqueta corta y
    legible: «En juego», «Invitado», «Operador» o «Bloqueado».
    """

    _LABELS = {
        1: ("En juego", "Ausente"),
        2: ("Invitado", "No"),
        3: ("Operador", "Jugador"),
        4: ("Bloqueado", "—"),
    }
    _COLORS = {
        1: "#2E7D32",
        2: "#2C739B",
        3: "#9A7422",
        4: "#B3261E",
    }

    def __init__(self, column: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.column = column

    def _font(self, option: QStyleOptionViewItem, activo: bool) -> QFont:
        font = QFont(option.font)
        font.setBold(activo)
        font.setPointSizeF(max(8.0, font.pointSizeF() - 0.5))
        return font

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802 - API de Qt
        """Reserva sitio para la etiqueta, no solo para el «Si»/«No» interno."""
        pista = super().sizeHint(option, index)
        activo = index.data(Qt.ItemDataRole.DisplayRole) == "Si"
        etiqueta = self._LABELS[self.column][0 if activo else 1]
        ancho = QFontMetrics(self._font(option, activo)).horizontalAdvance(etiqueta) + 30
        pista.setWidth(max(pista.width(), ancho))
        return pista

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()

        # Primero se deja que el estilo pinte el fondo (seleccion, filas
        # alternas), pero sin el texto ni el icono originales.
        opt.text = ""
        opt.icon = QIcon()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        activo = index.data(Qt.ItemDataRole.DisplayRole) == "Si"
        etiqueta = self._LABELS[self.column][0 if activo else 1]
        # Solo se colorea lo que esta activo. Si no, cuatro columnas de colores
        # a la vez convierten la tabla en un semaforo y cuesta leer lo importante.
        color = QColor(self._COLORS[self.column] if activo else "#6B7280")
        oscuro = opt.palette.window().color().lightness() < 128
        if oscuro:
            color = color.lighter(138)
        # Sobre la fila seleccionada el fondo ya es azul: una etiqueta blanca se
        # lee mejor que el color propio mezclado con el resaltado.
        seleccionado = bool(opt.state & QStyle.StateFlag.State_Selected)
        if seleccionado:
            color = QColor("#ffffff")
        fondo = QColor(color)
        fondo.setAlpha(38 if seleccionado else (34 if activo else 20))
        borde = QColor(color)
        borde.setAlpha(150 if seleccionado else (105 if activo else 55))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = self._font(opt, activo)
        painter.setFont(font)
        metrica = painter.fontMetrics()
        ancho = metrica.horizontalAdvance(etiqueta) + 18
        alto = 22
        caja = QRectF(
            opt.rect.left() + 6,
            opt.rect.center().y() - alto / 2 + 1,
            ancho,
            alto,
        )
        painter.setPen(QPen(borde, 1.0))
        painter.setBrush(fondo)
        painter.drawRoundedRect(caja, 6.0, 6.0)
        painter.setPen(color)
        painter.drawText(caja, Qt.AlignmentFlag.AlignCenter, etiqueta)
        painter.restore()


class PlayersPanel(TexturedPage):
    """Gestiona los jugadores del servidor seleccionado."""

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlayersPanel")
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._running = False
        self._snapshot: PlayersSnapshot | None = None
        #: Hay una consulta en curso (evita que se acumulen tareas si el RCON
        #: tarda o el servidor no responde).
        self._consultando = False
        #: Ya se aviso del ultimo fallo (para no repetirlo cada dos segundos).
        self._fallo_avisado = False
        #: Ventana del inventario abierta (se reutiliza para no llenar la pantalla).
        self._inventario: InventoryDialog | None = None
        #: Ventana de gestion de listas abierta.
        self._gestion: PlayersManagerDialog | None = None
        #: Skins ya disponibles (nombre en minusculas -> PNG de 64x64), las que
        #: se estan descargando y las que fallaron para no repetir la peticion.
        self._skins: dict[str, bytes] = {}
        self._skins_pendientes: set[str] = set()
        self._skins_fallidas: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_access_card())
        layout.addWidget(self._build_players_card(), 1)

        self.empty = CenteredEmpty(
            "Elige un servidor",
            "Selecciona uno en la lista de la izquierda para ver quien esta "
            "jugando, invitar a tus amigos y preparar la lista blanca.",
            pixmap=icono_jugador_duda(64),
        )
        layout.addWidget(self.empty)

        self.set_server(None, running=False)

    # ============================================================== construccion
    def _build_hero(self) -> QWidget:
        """Cabecera con el mismo lenguaje visual que Detalles y Mods."""
        self.hero = MinecraftHero(
            "Jugadores",
            "Decide quien entra y que puede hacer cada uno.",
            pixmap=icono_jugador(44),
            accent="blue",
            help_title="Jugadores: quien entra y que puede hacer",
            help_text=_AYUDA,
        )
        return self.hero

    def _build_access_card(self) -> AccentCard:
        """Lista blanca: el interruptor y la invitacion rapida."""
        self.card = AccentCard(
            "Acceso al servidor",
            pixmap=icono_escudo(20),
            help_title="Lista blanca: invitar y bloquear jugadores",
            help_text=_AYUDA,
            accent="gold",
        )
        cuerpo = self.card.body()
        cuerpo.setSpacing(9)

        # Resumen de un vistazo: cuantos hay conectados, invitados, operadores...
        self.chips = FlowRow(spacing=8)
        self.chip_online = Chip("Conectados: ?", tone="info")
        self.chip_whitelist = Chip("Lista blanca: ?")
        self.chip_ops = Chip("Operadores: ?")
        self.chip_banned = Chip("Bloqueados: 0", tone="bad")
        self.chip_bedrock = Chip(
            "Bedrock: 0",
            tone="info",
            pixmap=bloque_bedrock(12),
            tooltip="Jugadores que entran desde movil, tablet o consola con Geyser",
        )
        self.chip_bedrock.setVisible(False)
        for chip in (
            self.chip_online,
            self.chip_whitelist,
            self.chip_ops,
            self.chip_banned,
            self.chip_bedrock,
        ):
            self.chips.add(chip)
        cuerpo.addWidget(self.chips)

        self.whitelist_banner = QFrame()
        self.whitelist_banner.setObjectName("WhitelistBanner")
        self.whitelist_banner.setProperty("active", False)
        self.whitelist_banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        banner = QHBoxLayout(self.whitelist_banner)
        banner.setContentsMargins(12, 10, 12, 10)
        banner.setSpacing(10)

        self.whitelist_slot = IconSlot(icono_escudo(24), size=38, icon_size=24, parent=self.whitelist_banner)
        banner.addWidget(self.whitelist_slot, 0, Qt.AlignmentFlag.AlignVCenter)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        titulo = QLabel("Lista blanca")
        titulo.setObjectName("WhitelistTitle")
        textos.addWidget(titulo)
        self.whitelist_state = WrappingLabel("Comprobando...")
        self.whitelist_state.setObjectName("WhitelistState")
        self.whitelist_state.setWordWrap(True)
        textos.addWidget(self.whitelist_state)
        banner.addLayout(textos, 1)

        # Un interruptor compacto, no una barra enorme: la accion se entiende
        # por el texto y el estado se lee en la frase de la izquierda.
        self.whitelist_button = make_button(
            "Activada",
            accent=True,
            tooltip="Pulsa para permitir la entrada a cualquiera",
        )
        self.whitelist_button.setObjectName("WhitelistToggle")
        self.whitelist_button.setCheckable(True)
        self.whitelist_button.setMinimumWidth(126)
        self.whitelist_button.setMinimumHeight(34)
        self.whitelist_button.clicked.connect(self._on_whitelist_clicked)
        banner.addWidget(self.whitelist_button, 0, Qt.AlignmentFlag.AlignVCenter)
        cuerpo.addWidget(self.whitelist_banner)

        self.whitelist_note = hint_label("")
        cuerpo.addWidget(self.whitelist_note)

        # Invitacion rapida: escribir un nombre y pulsar un solo boton.
        # Se usa una fila que envuelve: en ventanas estrechas los controles
        # pasan a la linea siguiente en vez de recortarse.
        self.invite_box = FlowRow(spacing=10)
        etiqueta = QLabel("Invitar a un amigo:")
        self.invite_box.add(etiqueta)
        self.invite_input = QLineEdit()
        self.invite_input.setPlaceholderText("Escribe su nombre de Minecraft")
        self.invite_input.setClearButtonEnabled(True)
        self.invite_input.setMaxLength(33)
        self.invite_input.setMinimumWidth(230)
        self.invite_input.setToolTip(
            "Escribe el nombre tal y como aparece en el juego. Los jugadores de "
            "Bedrock llevan un punto delante (por ejemplo .Steve)."
        )
        self.invite_input.returnPressed.connect(self._invitar)
        self.invite_box.add(self.invite_input)

        self.invite_button = make_button(
            "Invitar",
            accent=True,
            tooltip="Anade a este amigo a la lista de invitados",
        )
        self.invite_button.setObjectName("InviteButton")
        self.invite_button.setIcon(QIcon(icono_pase(16)))
        self.invite_button.clicked.connect(self._invitar)
        self.invite_box.add(self.invite_button)

        self.manage_button = make_button(
            "Todas las listas...",
            tooltip="Ver y cambiar invitados, bloqueados y administradores",
        )
        self.manage_button.setObjectName("ManagePlayersButton")
        self.manage_button.setProperty("panelRole", "list")
        self.manage_button.setIcon(QIcon(icono_lista(16)))
        self.manage_button.clicked.connect(self._abrir_gestion)
        self._action_buttons: dict[str, QWidget] = {"gestion": self.manage_button}
        self.invite_box.add(self.manage_button)
        cuerpo.addWidget(self.invite_box)

        return self.card

    def _build_players_card(self) -> AccentCard:
        """Tabla de jugadores y acciones que cambian segun el elegido."""
        self.players_card = AccentCard(
            "Jugadores del servidor",
            pixmap=icono_lista(20),
            help_title="Acciones de cada jugador",
            help_text=_AYUDA,
            accent="blue",
        )
        cuerpo = self.players_card.body()
        cuerpo.setSpacing(8)

        # Nombre del jugador + refrescar.
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.player_input = QLineEdit()
        self.player_input.setPlaceholderText("Busca o escribe el nombre de un jugador")
        self.player_input.setClearButtonEnabled(True)
        self.player_input.setMaxLength(33)
        self.player_input.setToolTip(
            "Nombre del jugador: letras, numeros y guion bajo. Los jugadores de "
            "Bedrock llevan un punto delante (por ejemplo .Steve)."
        )
        self.player_input.textChanged.connect(self._on_name_changed)
        self.player_input.returnPressed.connect(self._on_op)
        name_row.addWidget(self.player_input, 1)
        self.refresh_button = make_button(
            "Actualizar",
            icon_names=("view-refresh",),
            tooltip="Volver a leer quien esta jugando",
        )
        self.refresh_button.setProperty("panelRole", "stone")
        self.refresh_button.clicked.connect(self.refresh)
        name_row.addWidget(self.refresh_button)
        cuerpo.addLayout(name_row)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("PlayersTable")
        self.table.setHorizontalHeaderLabels(
            ["Jugador", "Estado", "Acceso", "Permisos", "Bloqueo"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setMinimumSectionSize(78)
        for column in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
            self.table.setItemDelegateForColumn(column, _RoleBadgeDelegate(column, self.table))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setIconSize(QSize(28, 28))
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(190)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(lambda _index: self._ver_inventario())
        polish_table_header(self.table)
        cuerpo.addWidget(self.table, 1)

        # Cuando no hay nadie apuntado, la tabla vacia no explica nada: debajo
        # aparece una ranura con la cabeza desconocida y una pista.
        self.players_empty = EmptySlot(
            "Todavia no hay jugadores",
            "Cuando alguien entre, este en la lista de invitados o tenga "
            "permisos, aparecera aqui con su cabeza.",
            pixmap=icono_jugador_duda(32),
        )
        self.players_empty.setVisible(False)
        cuerpo.addWidget(self.players_empty)

        # Panel de acciones: separado de la tabla para que la ficha no parezca
        # una lista de botones suelta.
        self.actions_panel = QFrame()
        self.actions_panel.setObjectName("PlayerActionsPanel")
        self.actions_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        acciones = QVBoxLayout(self.actions_panel)
        acciones.setContentsMargins(12, 10, 12, 10)
        acciones.setSpacing(9)

        seleccion = QHBoxLayout()
        seleccion.setSpacing(12)
        self.selection_slot = IconSlot(None, size=38, icon_size=28, parent=self.actions_panel)
        seleccion.addWidget(self.selection_slot, 0, Qt.AlignmentFlag.AlignTop)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        self.actions_title = WrappingLabel("Acciones del jugador elegido")
        self.actions_title.setObjectName("SectionTitle")
        textos.addWidget(self.actions_title)
        self.actions_note = hint_label(
            "Elige un jugador de la tabla para ver lo que puedes hacer."
        )
        textos.addWidget(self.actions_note)
        self.bedrock_chip = Chip(
            "Jugador de Bedrock",
            tone="info",
            pixmap=bloque_bedrock(12),
            tooltip="Entra desde movil, tablet o consola con Geyser; el punto del "
            "nombre lo pone Floodgate.",
        )
        self.bedrock_chip.setVisible(False)
        textos.addWidget(self.bedrock_chip, 0, Qt.AlignmentFlag.AlignLeft)
        seleccion.addLayout(textos, 1)
        acciones.addLayout(seleccion)

        self.actions_row = FlowRow(spacing=12)
        for action in PLAYER_ACTIONS:
            button = make_button(
                _ACTION_LABELS.get(action.key, action.label),
                danger=action.destructive,
                tooltip=_ACTION_TIPS.get(action.key, f"Envia «{action.command}»"),
            )
            # Cada accion lleva su propio color en la hoja de estilos: permisos
            # (oro), acceso (verde), sanciones (naranja/rojo) e inventario (azul).
            button.setProperty("playerAction", action.key)
            button.setMinimumHeight(32)
            button.clicked.connect(lambda _checked=False, a=action: self._apply(a))
            self._action_buttons[action.key] = button
            self.actions_row.add(button)

        self.inventory_button = make_button(
            "Ver inventario",
            tooltip="Ensenar la mochila, la armadura y la barra rapida del jugador elegido",
        )
        self.inventory_button.setProperty("playerAction", "inventario")
        self.inventory_button.setMinimumHeight(32)
        self.inventory_button.clicked.connect(self._ver_inventario)
        self._action_buttons["inventario"] = self.inventory_button
        self.actions_row.add(self.inventory_button)
        acciones.addWidget(self.actions_row)

        self.status = self._hint("")
        acciones.addWidget(self.status)

        self.warning = hint_label("")
        acciones.addWidget(self.warning)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(180)
        footer.addWidget(self.progress)
        footer.addStretch(1)
        acciones.addLayout(footer)

        cuerpo.addWidget(self.actions_panel)
        return self.players_card

    def _hint(self, texto: str) -> QLabel:
        etiqueta = hint_label(texto)
        return etiqueta

    # =============================================================== cabezas
    def _head_pixmap(self, name: str, size: int = 28) -> QPixmap:
        """Cara real del jugador o, mientras no haya skin, una cabeza dibujada."""
        datos = self._skins.get((name or "").strip().lower())
        if datos:
            return head_pixmap(datos, size)
        return _avatar(name, size)

    def _prepare_skins(self, names: tuple[str, ...]) -> None:
        """Lee las skins guardadas y pide en segundo plano las que falten.

        La descarga nunca bloquea la interfaz: primero se ve la cabeza dibujada
        y, cuando llega la skin, se cambia el icono de esa fila.
        """
        faltan: list[str] = []
        for name in names:
            key = name.lower()
            if (
                key in self._skins
                or key in self._skins_pendientes
                or key in self._skins_fallidas
            ):
                continue
            guardada = cached_skin(name)
            if guardada:
                self._skins[key] = guardada
            else:
                faltan.append(name)
        if not faltan:
            return
        if offline():
            # Sin conexion no se sale a internet: queda la cabeza dibujada.
            self._skins_fallidas.update(name.lower() for name in faltan)
            return
        for name in faltan:
            self._request_skin(name)

    def _request_skin(self, name: str) -> None:
        """Pide la skin de un jugador y actualiza su cabeza al recibirla."""
        key = name.lower()
        if key in self._skins_pendientes:
            return
        self._skins_pendientes.add(key)

        def work(*, context) -> bytes | None:
            return fetch_skin(name)

        def done(datos: bytes | None) -> None:
            self._skins_pendientes.discard(key)
            if datos:
                self._skins[key] = datos
                self._apply_head(name)
            else:
                self._skins_fallidas.add(key)

        def failed(_message: str, _details: str) -> None:
            self._skins_pendientes.discard(key)
            self._skins_fallidas.add(key)

        self.runner.submit(
            f"Skin de {name}",
            work,
            on_finished=done,
            on_failed=failed,
            track_busy=False,
        )

    def _apply_head(self, name: str) -> None:
        """Sustituye la cabeza dibujada por la skin que acaba de llegar."""
        icono = QIcon(self._head_pixmap(name, 28))
        for fila in range(self.table.rowCount()):
            item = self.table.item(fila, 0)
            if item is None:
                continue
            fila_name = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if fila_name.lower() == name.lower():
                item.setIcon(icono)
        if self._target_name().lower() == name.lower():
            self._update_actions()

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        # Al cambiar de servidor se olvida lo del anterior: si no, quedaria a la
        # vista (y listo para enviar) el nombre de un jugador de otro servidor.
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._running != running
        if cambio:
            self.player_input.clear()
            self.invite_input.clear()
            self.status.clear()
            self.warning.clear()
            self.warning.setVisible(False)
            self.table.setRowCount(0)
            self.table.setMinimumHeight(190)
            self.table.setMaximumHeight(16777215)
            self._snapshot = None
            self.players_empty.setVisible(False)
            self.selection_slot.set_pixmap(icono_jugador_duda(28))
            self.selection_slot.setToolTip("Ningun jugador elegido")
            self._ocultar_inventario()
            self._cerrar_gestion()
            self._fallo_avisado = False
        self._spec = spec
        self._running = running
        if cambio:
            # Una accion del servidor anterior pudo dejar la barra de progreso
            # o los botones desactivados; la ficha nueva empieza limpia.
            self._set_busy(False)
        has_server = spec is not None
        if has_server:
            self.hero.set_title(f"Jugadores de «{spec.name}»")
            self.hero.set_subtitle(
                "Quien esta conectado, quien puede entrar y que permisos tiene cada uno."
            )
        else:
            self.hero.set_title("Jugadores")
            self.hero.set_subtitle("Selecciona un servidor para ver a sus jugadores.")
        # Se ocultan uno a uno (ademas de las tarjetas): asi una ventana sin
        # servidor no deja ningun control suelto.
        for widget in (
            self.hero,
            self.card,
            self.players_card,
            self.chips,
            self.whitelist_banner,
            self.whitelist_note,
            self.invite_box,
            self.table,
            self.refresh_button,
            self.player_input,
            self.actions_panel,
            self.actions_title,
            self.actions_row,
            self.actions_note,
            self.bedrock_chip,
            self.status,
            self.warning,
        ):
            widget.setVisible(has_server)
        self.empty.setVisible(not has_server)
        if has_server:
            self.bedrock_chip.setVisible(_is_bedrock(self._target_name()))
        # Solo se consulta cuando hay algo nuevo que contar: el refresco
        # periodico de la ventana llamaba a esta funcion cada pocos segundos y
        # las consultas al RCON (con su espera) se acumulaban hasta dejar la
        # aplicacion sin respuesta.
        if has_server and cambio_estado:
            self.refresh()

    # ================================================================= listado
    def refresh(self) -> None:
        if self._spec is None or self._consultando:
            return
        spec = self._spec
        server_id = spec.id
        self._consultando = True

        def work(*, context) -> PlayersSnapshot:
            context.progress("Consultando los jugadores del servidor...")
            return self.manager.players_snapshot(server_id)

        def done(snapshot: PlayersSnapshot) -> None:
            self._consultando = False
            if self._spec is None or self._spec.id != server_id:
                # Se cambio de servidor mientras respondia el anterior. Su
                # consulta dejo la bandera ocupada, asi que hay que lanzar la
                # del servidor que esta seleccionado ahora.
                self.refresh()
                return
            self._fallo_avisado = False
            self._on_snapshot(snapshot)

        def failed(message: str, details: str) -> None:
            self._consultando = False
            if self._spec is None or self._spec.id != server_id:
                self.refresh()
                return
            if not self._fallo_avisado:
                logger.warning("No se pudieron consultar los jugadores: %s", message)
                self._fallo_avisado = True
            self.status.setText(f"No se pudieron consultar los jugadores: {message}")

        def progress(message: str) -> None:
            if self._spec is not None and self._spec.id == server_id:
                self.status.setText(message)

        self.runner.submit(
            "Consultando jugadores",
            work,
            on_finished=done,
            on_failed=failed,
            on_progress=progress,
            track_busy=False,
        )

    def _on_snapshot(self, snapshot: PlayersSnapshot) -> None:
        self._snapshot = snapshot
        # Primero se recuperan las skins ya guardadas: la tabla nace con la
        # cara correcta y solo las que falten se piden en segundo plano.
        self._prepare_skins(snapshot.known)
        self.table.setRowCount(0)
        for name in snapshot.known:
            fila = self.table.rowCount()
            self.table.insertRow(fila)
            conectado = snapshot.is_online(name)
            bloqueado = snapshot.is_banned(name)
            item = QTableWidgetItem(QIcon(self._head_pixmap(name, 28)), name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if conectado:
                fuente = QFont(item.font())
                fuente.setBold(True)
                item.setFont(fuente)
                item.setForeground(QColor(_BUENO))
            elif bloqueado:
                item.setForeground(QColor(_MALO))
            item.setToolTip(
                f"{name}: "
                + ("en el juego" if conectado else "sin conexion")
                + (" · invitado" if snapshot.in_whitelist(name) else "")
                + (" · administrador" if snapshot.is_op(name) else "")
                + (" · bloqueado" if bloqueado else "")
                + (
                    " · jugador de Bedrock (Geyser) — el punto forma parte del nombre"
                    if _is_bedrock(name)
                    else ""
                )
            )
            self.table.setItem(fila, 0, item)
            self.table.setItem(fila, 1, self._celda(conectado))
            self.table.setItem(fila, 2, self._celda(snapshot.in_whitelist(name)))
            self.table.setItem(fila, 3, self._celda(snapshot.is_op(name)))
            self.table.setItem(fila, 4, self._celda(bloqueado))
        self._actualizar_chips(snapshot)
        self.status.setText(self._summary(snapshot))
        self.warning.setText(snapshot.note)
        self.warning.setVisible(bool(snapshot.note))
        # Sin jugadores la tabla se queda solo con la cabecera: una tabla vacia
        # y alta parece un fallo de carga y empuja las acciones fuera de vista.
        if snapshot.known:
            self.table.setMinimumHeight(190)
            self.table.setMaximumHeight(16777215)
        else:
            self.table.setMinimumHeight(0)
            self.table.setMaximumHeight(52)
        self.players_empty.setVisible(not snapshot.known and self._spec is not None)
        if snapshot.known:
            self.table.selectRow(0)
        self._update_actions()

    @staticmethod
    def _celda(activo: bool) -> QTableWidgetItem:
        """Casilla «Si»/«No»; el delegado la pinta como etiqueta de color."""
        celda = QTableWidgetItem("Si" if activo else "No")
        celda.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        celda.setToolTip("Si" if activo else "No")
        return celda

    def _actualizar_chips(self, snapshot: PlayersSnapshot) -> None:
        """Pone al dia las fichas de resumen (conectados, lista, operadores...)."""
        # El maximo de plazas solo se conoce con el servidor encendido: sin el,
        # «0 de ?» se lee peor que un simple «0».
        conectados = len(snapshot.online)
        if snapshot.max_players:
            texto_online = f"Conectados: {conectados} de {snapshot.max_players}"
        else:
            texto_online = f"Conectados: {conectados}"
        self.chip_online.set_text(texto_online)
        self.chip_online.set_tone("ok" if snapshot.online else "info")
        estado_lista = "activada" if snapshot.whitelist_enabled else "desactivada"
        self.chip_whitelist.set_text(f"Lista blanca: {len(snapshot.whitelist)} ({estado_lista})")
        self.chip_whitelist.set_tone("info" if snapshot.whitelist_enabled else "")
        self.chip_ops.set_text(f"Operadores: {len(snapshot.ops)}")
        self.chip_banned.set_text(f"Bloqueados: {len(snapshot.banned)}")
        self.chip_banned.setVisible(bool(snapshot.banned))
        bedrock = sum(1 for name in snapshot.known if _is_bedrock(name))
        self.chip_bedrock.set_text(f"Bedrock: {bedrock}")
        self.chip_bedrock.setVisible(bool(bedrock))
        self._actualizar_lista_blanca(snapshot.whitelist_enabled)

    def _actualizar_lista_blanca(self, activada: bool) -> None:
        """Pinta el estado de la lista blanca y el interruptor."""
        self.whitelist_banner.setProperty("active", activada)
        estilo = self.whitelist_banner.style()
        estilo.unpolish(self.whitelist_banner)
        estilo.polish(self.whitelist_banner)
        self.whitelist_button.blockSignals(True)
        self.whitelist_button.setChecked(activada)
        self.whitelist_button.setText("Activada" if activada else "Desactivada")
        self.whitelist_button.blockSignals(False)
        self.whitelist_button.setToolTip(
            "Ahora solo entran los invitados. Pulsa para permitir la entrada a cualquiera."
            if activada
            else "Ahora puede entrar cualquiera. Pulsa para que solo entren los invitados."
        )
        if activada:
            self.whitelist_state.setText("Solo entran los amigos que invites.")
            self.whitelist_note.setText(
                "La lista esta activada. Si un amigo no aparece, invitalo con el campo de abajo."
            )
        else:
            self.whitelist_state.setText("Puede entrar cualquiera que tenga la direccion.")
            self.whitelist_note.setText(
                "La lista blanca esta apagada. Activala para jugar solo con tus amigos."
            )

    def _summary(self, snapshot: PlayersSnapshot) -> str:
        # Los bloqueos solo se mencionan si hay alguno: si no, la frase se llena
        # de ceros y cuesta leer lo importante.
        banned = f" Bloqueados: {len(snapshot.banned)}." if snapshot.banned else ""
        if not snapshot.running:
            state = "activada" if snapshot.whitelist_enabled else "desactivada"
            return (
                f"Servidor detenido. Lista blanca: {state}. "
                f"{plural(len(snapshot.whitelist), 'jugador', 'jugadores')} en la lista y "
                f"{plural(len(snapshot.ops), 'operador', 'operadores')}."
                + banned
            )
        maximum = f"{snapshot.max_players}" if snapshot.max_players else "?"
        return (
            f"Conectados: {len(snapshot.online)} de {maximum}. "
            f"Lista blanca: {plural(len(snapshot.whitelist), 'jugador', 'jugadores')}. "
            f"Operadores: {len(snapshot.ops)}."
            + banned
        )

    def _target_name(self) -> str:
        """Nombre escrito a mano o el de la fila seleccionada."""
        typed = self.player_input.text().strip()
        if typed:
            return typed
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            if item is not None:
                return item.text()
        return ""

    def _on_selection_changed(self) -> None:
        name = self._target_name()
        if name and name != self.player_input.text():
            self.player_input.setText(name)
        self._update_actions()

    def _on_name_changed(self, _texto: str) -> None:
        self._update_actions()

    # ================================================================= acciones
    def _on_op(self) -> None:
        self._apply(PLAYER_ACTIONS[0])

    def _apply(self, action: PlayerAction) -> None:
        if self._spec is None:
            return
        try:
            player = validate_player_name(self._target_name())
        except ValidationError as exc:
            show_error(self, "Falta el nombre del jugador", exc.message)
            return
        self._run_action(action, player)

    def _run_action(
        self,
        action: PlayerAction,
        player: str,
        *,
        limpiar_invitacion: bool = False,
    ) -> None:
        """Aplica una accion ya validada (la usan la tabla y la invitacion rapida)."""
        if self._spec is None:
            return
        if not self._running and action.key == "kick":
            show_error(
                self,
                "El servidor esta detenido",
                "Para sacar a alguien del juego el servidor tiene que estar encendido: "
                "la orden se envia a su consola. Para dejarlo fuera, usa «Bloquear entrada».",
            )
            return
        if action.destructive and not confirm(
            self,
            f"{_ACTION_LABELS.get(action.key, action.label)}?",
            f"Jugador: «{player}».\n\n{action.warning}",
            confirm_label=_ACTION_LABELS.get(action.key, action.label),
            destructive=True,
        ):
            return

        spec = self._spec
        server_id = spec.id
        self._set_busy(True, f"Aplicando «{_ACTION_LABELS.get(action.key, action.label)}» a {player}...")

        def work(*, context) -> str:
            context.progress("Aplicando el cambio en las listas del servidor...")
            return self.manager.run_player_action(spec.id, action.key, player)

        def done(response: str) -> None:
            if self._spec is None or self._spec.id != server_id:
                return
            self._set_busy(False)
            if limpiar_invitacion:
                self.invite_input.clear()
            text = str(response or "").strip()
            self.status.setText(text or f"Accion aplicada a «{player}».")
            self.refresh()

        def failed(message: str, details: str) -> None:
            if self._spec is None or self._spec.id != server_id:
                return
            self._set_busy(False)
            show_error(self, "No se pudo aplicar la accion", message, details)

        self.runner.submit(action.label, work, on_finished=done, on_failed=failed)

    def _invitar(self) -> None:
        """Invita al nombre escrito en el campo rapido."""
        if self._spec is None:
            return
        try:
            player = validate_player_name(self.invite_input.text())
        except ValidationError as exc:
            show_error(self, "Falta el nombre del jugador", exc.message)
            return
        self._run_action(ACTIONS_BY_KEY["whitelist_add"], player, limpiar_invitacion=True)

    # ============================================================ lista blanca
    def _on_whitelist_clicked(self) -> None:
        """Enciende o apaga la lista blanca con el interruptor."""
        if self._spec is None:
            return
        activar = self.whitelist_button.isChecked()
        if not activar and not confirm(
            self,
            "Desactivar la lista blanca",
            "Ahora podra entrar cualquiera que tenga la direccion del servidor.\n\n"
            "Si quieres jugar solo con tus amigos, deja la lista blanca activada.",
            confirm_label="Permitir a todos",
            destructive=True,
        ):
            self.whitelist_button.blockSignals(True)
            self.whitelist_button.setChecked(True)
            self.whitelist_button.blockSignals(False)
            return

        spec = self._spec
        server_id = spec.id
        self.whitelist_button.setEnabled(False)
        self.status.setText(
            "Activando la lista blanca..." if activar else "Desactivando la lista blanca..."
        )

        def work(*, context) -> bool:
            context.progress("Guardando el cambio...")
            return self.manager.set_whitelist_enabled(spec.id, activar)

        def done(_valor: bool) -> None:
            if self._spec is None or self._spec.id != server_id:
                return
            self.whitelist_button.setEnabled(True)
            self.status.setText(
                "Listo: solo entran los invitados."
                if activar
                else "Listo: ahora puede entrar cualquiera."
            )
            self.refresh()

        def failed(message: str, details: str) -> None:
            if self._spec is None or self._spec.id != server_id:
                return
            self.whitelist_button.setEnabled(True)
            # Se devuelve el boton al estado que tenia el servidor.
            if self._snapshot is not None:
                self._actualizar_lista_blanca(self._snapshot.whitelist_enabled)
            show_error(self, "No se pudo cambiar la lista blanca", message, details)

        self.runner.submit("Cambiando la lista blanca", work, on_finished=done, on_failed=failed)

    # ============================================================ gestion de listas
    def _abrir_gestion(self) -> None:
        """Abre la ventana unica con lista blanca, bloqueados y operadores."""
        if self._spec is None:
            return
        if self._gestion is not None:
            try:
                self._gestion.refresh()
                self._gestion.show()
                self._gestion.raise_()
                self._gestion.activateWindow()
                return
            except RuntimeError:  # pragma: no cover - la ventana ya no existe
                self._gestion = None
        self._gestion = PlayersManagerDialog(
            self.manager,
            self.runner,
            self._spec,
            parent=self.window(),
            on_changed=self.refresh,
        )
        self._gestion.finished.connect(lambda _result: self.refresh())
        self._gestion.show()
        self._gestion.raise_()
        self._gestion.activateWindow()

    def _cerrar_gestion(self) -> None:
        if self._gestion is not None:
            try:
                self._gestion.close()
            except RuntimeError:  # pragma: no cover
                pass
            self._gestion = None

    # ============================================================== inventario
    def _ver_inventario(self) -> None:
        """Pide al servidor lo que lleva encima el jugador elegido."""
        if self._spec is None:
            return
        try:
            player = validate_player_name(self._target_name())
        except ValidationError as exc:
            show_error(self, "Falta el nombre del jugador", exc.message)
            return
        if not self._running:
            show_error(
                self,
                "El servidor esta detenido",
                "El inventario se pregunta a la consola del servidor (RCON), asi que el "
                "servidor tiene que estar iniciado y el jugador conectado.",
            )
            return
        spec = self._spec
        server_id = spec.id
        self._set_busy(True, f"Leyendo el inventario de {player}...")

        def work(*, context) -> PlayerInventory:
            context.progress("Preguntando al servidor...")
            return self.manager.player_inventory(spec.id, player)

        def done(inventario: PlayerInventory) -> None:
            if self._spec is None or self._spec.id != server_id:
                return
            self._set_busy(False)
            self.status.setText(
                f"«{player}» lleva {plural(inventario.total_items, 'objeto', 'objetos')} "
                f"en {plural(inventario.stacks, 'hueco', 'huecos')}."
            )
            self._mostrar_inventario(inventario)

        def failed(message: str, details: str) -> None:
            if self._spec is None or self._spec.id != server_id:
                return
            self._set_busy(False)
            show_error(self, "No se pudo leer el inventario", message, details)

        self.runner.submit("Leyendo el inventario", work, on_finished=done, on_failed=failed)

    def _mostrar_inventario(self, inventario: PlayerInventory) -> None:
        if self._inventario is None:
            self._inventario = InventoryDialog(
                inventario,
                on_refresh=self._ver_inventario,
                runner=self.runner,
                parent=self.window(),
            )
        else:
            self._inventario.set_inventory(inventario)
        self._inventario.show()
        self._inventario.raise_()
        self._inventario.activateWindow()

    def _ocultar_inventario(self) -> None:
        """Al cambiar de servidor se cierra la mochila del anterior."""
        if self._inventario is not None:
            try:
                self._inventario.close()
            except RuntimeError:  # pragma: no cover - la ventana ya no existe
                pass
            self._inventario = None

    # ================================================================ estado
    def _update_actions(self) -> None:
        """Muestra solo las acciones que tienen sentido para el jugador elegido.

        Las listas se pueden tocar tambien con el servidor apagado. «Sacar del
        juego» y el inventario necesitan la consola del servidor, de modo que se
        quedan desactivados hasta que este en marcha.
        """
        snapshot = self._snapshot
        name = self._target_name()
        hay_servidor = self._spec is not None
        hay_jugador = bool(name)

        if snapshot is not None and name:
            invitado = snapshot.in_whitelist(name)
            administrador = snapshot.is_op(name)
            bloqueado = snapshot.is_banned(name)
            conectado = snapshot.is_online(name)
        else:
            # Antes de la primera consulta no se sabe nada: se ofrecen las
            # acciones normales (invitar y dar permisos) en vez de dejar la
            # botonera vacia.
            invitado = administrador = bloqueado = False
            conectado = True

        visibles = {
            "op": hay_jugador and not administrador,
            "deop": hay_jugador and administrador,
            "whitelist_add": hay_jugador and not invitado,
            "whitelist_remove": hay_jugador and invitado,
            "kick": hay_jugador and conectado,
            "ban": hay_jugador and not bloqueado,
            "pardon": hay_jugador and bloqueado,
            "inventario": hay_jugador,
        }
        for key, button in self._action_buttons.items():
            if key == "gestion":
                button.setEnabled(hay_servidor)
                continue
            if key in {"kick", "inventario"}:
                # Antes de la primera consulta aun no se sabe si el servidor
                # esta en marcha: se deja pulsable para explicar por que no se
                # puede hacer nada, en vez de mostrar un boton muerto.
                button.setEnabled(
                    hay_servidor and (self._running or snapshot is None)
                )
            else:
                button.setEnabled(hay_servidor)
            button.setVisible(visibles.get(key, hay_jugador))

        if name:
            self.selection_slot.set_pixmap(self._head_pixmap(name, 28))
            self.selection_slot.setToolTip(f"Cabeza de {name}")
        else:
            # Sin jugador elegido no se deja una ranura vacia: se muestra la
            # cabeza con el signo de duda, que invita a elegir una fila.
            self.selection_slot.set_pixmap(icono_jugador_duda(28))
            self.selection_slot.setToolTip("Ningun jugador elegido")
        es_bedrock = _is_bedrock(name)
        self.bedrock_chip.setVisible(bool(name) and es_bedrock)
        if name:
            self.actions_title.setText(f"Acciones para «{name}»")
            if es_bedrock:
                self.actions_note.setText(
                    "Es un jugador de Bedrock (movil, tablet o consola): Geyser le pone "
                    "un punto delante del nombre y se gestiona igual que los de Java. "
                    "Los cambios se aplican al momento con el servidor encendido; con "
                    "el servidor detenido se guardan para el proximo arranque."
                )
            else:
                self.actions_note.setText(
                    "Los cambios se aplican al momento con el servidor encendido; con el "
                    "servidor detenido se guardan para el proximo arranque."
                )
        else:
            self.actions_title.setText("Acciones del jugador elegido")
            self.actions_note.setText(
                "Elige un jugador de la tabla para ver lo que puedes hacer."
            )
        # La fila de botones cambia de alto al ocultar o mostrar acciones.
        self.actions_row.updateGeometry()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.progress.setVisible(busy)
        self.refresh_button.setEnabled(not busy)
        self.invite_button.setEnabled(not busy and self._spec is not None)
        self.whitelist_button.setEnabled(not busy and self._spec is not None)
        if busy:
            for button in self._action_buttons.values():
                button.setEnabled(False)
        else:
            self._update_actions()
        if message:
            self.status.setText(message)
