"""Pestana de jugadores: quien esta conectado, lista blanca y operadores.

La consulta de jugadores conectados y las acciones (OP, expulsar, lista blanca)
se hacen por consola RCON, que solo responde con el servidor en marcha. La lista
blanca y los operadores se leen ademas de los ficheros del servidor, asi que la
pestana sigue mostrando informacion util cuando el servidor esta detenido.

La pantalla esta pensada para que la entienda cualquiera, tambien un niño:

* Arriba se explica con una frase si puede entrar cualquiera o solo los
  invitados, y hay **un boton grande** para activar o desactivar la lista blanca.
* Los botones de cada jugador cambian segun lo que se pueda hacer: invitar,
  quitar la invitacion, hacer administrador, bloquear o sacar del juego. Asi no
  aparecen diez botones a la vez ni palabras tecnicas como «OP» o «whitelist».
* El boton «?» guarda la explicacion larga para quien quiera leer mas.

Desde aqui tambien se abre el **inventario** de un jugador conectado: el servidor
lo cuenta por su consola (``data get entity``) y se enseña con la misma
disposicion que la mochila del juego.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
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
from .common import (
    Chip,
    FlowRow,
    HelpButton,
    SectionCard,
    WrappingLabel,
    hint_label,
    make_button,
    plural,
    polish_table_header,
)
from .dialogs import confirm, show_error
from .inventory_dialog import InventoryDialog
from .mc_icons import (
    icono_candado,
    icono_corona,
    icono_escudo,
    icono_jugador,
    icono_lista,
    icono_mochila,
    icono_no,
    icono_pase,
    icono_salida,
    icono_si,
)
from .players_manager_dialog import PlayersManagerDialog
from .tasks import TaskRunner

logger = get_logger("ui.players")

#: Color con el que se marca lo bueno (conectado, operador...) y lo malo (bloqueado).
_BUENO = "#2e7d32"
_MALO = "#b3261e"

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

#: Dibujo propio de cada accion. No se depende del tema de iconos del escritorio:
#: asi cada boton tiene siempre su icono, tambien al ejecutar el AppImage.
_ACTION_PIXMAPS = {
    "op": icono_corona,
    "deop": icono_corona,
    "whitelist_add": icono_pase,
    "whitelist_remove": icono_pase,
    "kick": icono_salida,
    "ban": icono_candado,
    "pardon": icono_pase,
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
)


class PlayersPanel(QWidget):
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_access_card())
        layout.addWidget(self._build_players_card(), 1)

        self.empty = QLabel("Selecciona un servidor para ver sus jugadores.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None, running=False)

    # ============================================================== construccion
    def _build_hero(self) -> QWidget:
        """Cabecera con sabor a Minecraft: bloque, titulo y explicacion corta."""
        self.hero = QFrame()
        self.hero.setObjectName("PlayersHero")
        # Sin esto, Qt pinta el fondo del estilo nativo y se pierde el degradado
        # verde de la cabecera en algunos temas (por ejemplo Breeze).
        self.hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        fila = QHBoxLayout(self.hero)
        fila.setContentsMargins(16, 12, 14, 12)
        fila.setSpacing(12)

        icono = QLabel()
        icono.setObjectName("PlayersHeroIcon")
        icono.setPixmap(icono_jugador(42))
        icono.setFixedSize(44, 44)
        fila.addWidget(icono)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        self.hero_title = QLabel("Jugadores")
        self.hero_title.setObjectName("PlayersHeroTitle")
        # El color se fija tambien aqui: algunos estilos nativos (Breeze) ignoran
        # el color heredado de la hoja de estilos en las etiquetas de un QFrame.
        self.hero_title.setStyleSheet("color: #ffffff;")
        textos.addWidget(self.hero_title)
        self.hero_subtitle = QLabel("Decide quien entra y que puede hacer cada uno")
        self.hero_subtitle.setObjectName("PlayersHeroSubtitle")
        self.hero_subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.86);")
        self.hero_subtitle.setWordWrap(True)
        textos.addWidget(self.hero_subtitle)
        fila.addLayout(textos, 1)

        self.hero_help = HelpButton(
            "Jugadores: quien entra y que puede hacer", _AYUDA, self.hero
        )
        fila.addWidget(self.hero_help, 0, Qt.AlignmentFlag.AlignTop)
        return self.hero

    def _build_access_card(self) -> SectionCard:
        """Lista blanca: el interruptor grande y la invitacion rapida."""
        self.card = SectionCard(
            "Quien puede entrar",
            pixmap=icono_escudo(18),
            help_title="Lista blanca: invitar y bloquear jugadores",
            help_text=_AYUDA,
        )
        cuerpo = self.card.body()

        # Resumen de un vistazo: cuantos hay conectados, invitados, operadores...
        self.chips = FlowRow(spacing=8)
        self.chip_online = Chip("Conectados: ?", tone="info", pixmap=icono_jugador(14))
        self.chip_whitelist = Chip("Lista blanca: ?")
        self.chip_ops = Chip("Operadores: ?")
        self.chip_banned = Chip("Bloqueados: 0", tone="bad")
        for chip in (self.chip_online, self.chip_whitelist, self.chip_ops, self.chip_banned):
            self.chips.add(chip)
        cuerpo.addWidget(self.chips)

        self.whitelist_banner = QFrame()
        self.whitelist_banner.setObjectName("WhitelistBanner")
        self.whitelist_banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        banner = QVBoxLayout(self.whitelist_banner)
        banner.setContentsMargins(12, 8, 12, 10)
        banner.setSpacing(8)

        fila = QHBoxLayout()
        fila.setSpacing(10)
        escudo = QLabel()
        escudo.setPixmap(icono_escudo(28))
        escudo.setFixedSize(30, 30)
        fila.addWidget(escudo)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        titulo = QLabel("Lista blanca")
        titulo.setObjectName("WhitelistTitle")
        textos.addWidget(titulo)
        self.whitelist_state = WrappingLabel("Comprobando...")
        self.whitelist_state.setObjectName("WhitelistState")
        self.whitelist_state.setWordWrap(True)
        textos.addWidget(self.whitelist_state)
        fila.addLayout(textos, 1)
        banner.addLayout(fila)

        # Boton grande y con el texto completo: se entiende de un vistazo y se
        # puede pulsar sin apuntar a una zona pequena.
        self.whitelist_button = make_button(
            "Activar lista blanca",
            accent=True,
            tooltip="Solo podran entrar los jugadores que invites",
        )
        self.whitelist_button.setObjectName("WhitelistToggle")
        self.whitelist_button.setCheckable(True)
        self.whitelist_button.setMinimumHeight(40)
        self.whitelist_button.setIcon(QIcon(icono_escudo(16)))
        self.whitelist_button.clicked.connect(self._on_whitelist_clicked)
        banner.addWidget(self.whitelist_button)
        cuerpo.addWidget(self.whitelist_banner)

        self.whitelist_note = hint_label("")
        cuerpo.addWidget(self.whitelist_note)

        # Invitacion rapida: escribir un nombre y pulsar un solo boton.
        # Se usa una fila que envuelve: en ventanas estrechas los controles
        # pasan a la linea siguiente en vez de recortarse.
        self.invite_box = FlowRow(spacing=8)
        etiqueta = QLabel("Invitar a un amigo:")
        self.invite_box.add(etiqueta)
        self.invite_input = QLineEdit()
        self.invite_input.setPlaceholderText("Escribe su nombre de Minecraft")
        self.invite_input.setClearButtonEnabled(True)
        self.invite_input.setMaxLength(32)
        self.invite_input.setMinimumWidth(230)
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
            icon_names=("system-users", "preferences-system-users"),
            tooltip="Ver y cambiar invitados, bloqueados y administradores",
        )
        self.manage_button.setIcon(QIcon(icono_lista(16)))
        self.manage_button.clicked.connect(self._abrir_gestion)
        self._action_buttons: dict[str, QWidget] = {"gestion": self.manage_button}
        self.invite_box.add(self.manage_button)
        cuerpo.addWidget(self.invite_box)

        return self.card

    def _build_players_card(self) -> SectionCard:
        """Tabla de jugadores y acciones que cambian segun el elegido."""
        self.players_card = SectionCard(
            "Jugadores del servidor",
            pixmap=icono_jugador(18),
            help_title="Acciones de cada jugador",
            help_text=_AYUDA,
        )
        cuerpo = self.players_card.body()

        # Nombre del jugador + refrescar.
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.player_input = QLineEdit()
        self.player_input.setPlaceholderText("Busca o escribe el nombre de un jugador")
        self.player_input.setClearButtonEnabled(True)
        self.player_input.setMaxLength(32)
        self.player_input.textChanged.connect(self._on_name_changed)
        self.player_input.returnPressed.connect(self._on_op)
        name_row.addWidget(self.player_input, 1)
        self.refresh_button = make_button(
            "Refrescar", icon_names=("view-refresh",), tooltip="Volver a leer quien esta jugando"
        )
        self.refresh_button.setIcon(QIcon(icono_si(16)))
        self.refresh_button.clicked.connect(self.refresh)
        name_row.addWidget(self.refresh_button)
        cuerpo.addLayout(name_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Jugador", "En el juego", "Invitado", "Administrador", "Bloqueado"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setAlternatingRowColors(True)
        polish_table_header(self.table)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(150)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(lambda _index: self._ver_inventario())
        cuerpo.addWidget(self.table, 1)

        self.actions_title = QLabel("Acciones del jugador elegido")
        self.actions_title.setObjectName("SectionTitle")
        cuerpo.addWidget(self.actions_title)

        # Acciones. Cada boton se muestra solo cuando tiene sentido para el
        # jugador elegido (invitar o quitar invitacion, no las dos a la vez).
        self.actions_row = FlowRow(spacing=8)
        for action in PLAYER_ACTIONS:
            button = make_button(
                _ACTION_LABELS.get(action.key, action.label),
                danger=action.destructive,
                tooltip=_ACTION_TIPS.get(action.key, f"Envia «{action.command}»"),
            )
            button.setProperty("playerAction", "true")
            pixmap = _ACTION_PIXMAPS.get(action.key)
            if pixmap is not None:
                button.setIcon(QIcon(pixmap(16)))
            button.clicked.connect(lambda _checked=False, a=action: self._apply(a))
            self._action_buttons[action.key] = button
            self.actions_row.add(button)

        self.inventory_button = make_button(
            "Ver inventario",
            tooltip="Ensenar la mochila, la armadura y la barra rapida del jugador elegido",
        )
        self.inventory_button.setIcon(QIcon(icono_mochila(16)))
        self.inventory_button.clicked.connect(self._ver_inventario)
        self._action_buttons["inventario"] = self.inventory_button
        self.actions_row.add(self.inventory_button)
        cuerpo.addWidget(self.actions_row)

        self.actions_note = hint_label("Elige un jugador de la tabla para ver lo que puedes hacer.")
        cuerpo.addWidget(self.actions_note)

        self.status = self._hint("")
        cuerpo.addWidget(self.status)

        self.warning = hint_label("")
        cuerpo.addWidget(self.warning)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(180)
        footer.addWidget(self.progress)
        footer.addStretch(1)
        cuerpo.addLayout(footer)
        return self.players_card

    def _hint(self, texto: str) -> QLabel:
        etiqueta = hint_label(texto)
        return etiqueta

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
            self._snapshot = None
            self._ocultar_inventario()
            self._cerrar_gestion()
            self._fallo_avisado = False
        self._spec = spec
        self._running = running
        has_server = spec is not None
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
            self.actions_title,
            self.actions_row,
            self.actions_note,
            self.status,
            self.warning,
        ):
            widget.setVisible(has_server)
        self.empty.setVisible(not has_server)
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
                return
            self._fallo_avisado = False
            self._on_snapshot(snapshot)

        def failed(message: str, details: str) -> None:
            self._consultando = False
            if not self._fallo_avisado:
                logger.warning("No se pudieron consultar los jugadores: %s", message)
                self._fallo_avisado = True
            if self._spec is not None and self._spec.id == server_id:
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
        self.table.setRowCount(0)
        for name in snapshot.known:
            fila = self.table.rowCount()
            self.table.insertRow(fila)
            conectado = snapshot.is_online(name)
            bloqueado = snapshot.is_banned(name)
            item = QTableWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setIcon(QIcon(icono_jugador(16)))
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
            )
            self.table.setItem(fila, 0, item)
            self.table.setItem(
                fila, 1, self._celda(conectado, bueno=True, activo_pixmap=icono_si)
            )
            self.table.setItem(
                fila, 2, self._celda(snapshot.in_whitelist(name), bueno=True, activo_pixmap=icono_pase)
            )
            self.table.setItem(
                fila, 3, self._celda(snapshot.is_op(name), bueno=True, activo_pixmap=icono_corona)
            )
            self.table.setItem(
                fila, 4, self._celda(bloqueado, bueno=False, activo_pixmap=icono_candado)
            )
        self._actualizar_chips(snapshot)
        self.status.setText(self._summary(snapshot))
        self.warning.setText(snapshot.note)
        self.warning.setVisible(bool(snapshot.note))
        if snapshot.known:
            self.table.selectRow(0)
        self._update_actions()

    @staticmethod
    def _celda(activo: bool, *, bueno: bool, activo_pixmap=None) -> QTableWidgetItem:
        """Casilla «Si»/«No» de la tabla, con icono y color."""
        celda = QTableWidgetItem("Si" if activo else "No")
        celda.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if activo:
            celda.setForeground(QColor(_BUENO if bueno else _MALO))
            pixmap = activo_pixmap(14) if activo_pixmap is not None else icono_si(14)
        else:
            pixmap = icono_no(14)
        celda.setIcon(QIcon(pixmap))
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
        self._actualizar_lista_blanca(snapshot.whitelist_enabled)

    def _actualizar_lista_blanca(self, activada: bool) -> None:
        """Pinta el estado de la lista blanca y el boton grande de encender/apagar."""
        self.whitelist_button.blockSignals(True)
        self.whitelist_button.setChecked(activada)
        self.whitelist_button.setText(
            "Desactivar lista blanca" if activada else "Activar lista blanca"
        )
        self.whitelist_button.blockSignals(False)
        self.whitelist_button.setToolTip(
            "Ahora solo entran los invitados. Pulsa para permitir la entrada a cualquiera."
            if activada
            else "Ahora puede entrar cualquiera. Pulsa para que solo entren los invitados."
        )
        if activada:
            self.whitelist_state.setText("Activada: solo entran los amigos que invites.")
            self.whitelist_note.setText(
                "Solo pueden entrar los jugadores de la lista. Si un amigo no aparece, "
                "invitalo con el campo de abajo."
            )
        else:
            self.whitelist_state.setText("Desactivada: puede entrar cualquiera que tenga la direccion.")
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
        self._set_busy(True, f"Aplicando «{_ACTION_LABELS.get(action.key, action.label)}» a {player}...")

        def work(*, context) -> str:
            context.progress("Aplicando el cambio en las listas del servidor...")
            return self.manager.run_player_action(spec.id, action.key, player)

        def done(response: str) -> None:
            self._set_busy(False)
            if limpiar_invitacion:
                self.invite_input.clear()
            text = str(response or "").strip()
            self.status.setText(text or f"Accion aplicada a «{player}».")
            self.refresh()

        def failed(message: str, details: str) -> None:
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
        """Enciende o apaga la lista blanca con el boton grande."""
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
        self.whitelist_button.setEnabled(False)
        self.status.setText(
            "Activando la lista blanca..." if activar else "Desactivando la lista blanca..."
        )

        def work(*, context) -> bool:
            context.progress("Guardando el cambio...")
            return self.manager.set_whitelist_enabled(spec.id, activar)

        def done(_valor: bool) -> None:
            self.whitelist_button.setEnabled(True)
            self.status.setText(
                "Listo: solo entran los invitados."
                if activar
                else "Listo: ahora puede entrar cualquiera."
            )
            self.refresh()

        def failed(message: str, details: str) -> None:
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
        self._set_busy(True, f"Leyendo el inventario de {player}...")

        def work(*, context) -> PlayerInventory:
            context.progress("Preguntando al servidor...")
            return self.manager.player_inventory(spec.id, player)

        def done(inventario: PlayerInventory) -> None:
            self._set_busy(False)
            self.status.setText(
                f"«{player}» lleva {plural(inventario.total_items, 'objeto', 'objetos')} "
                f"en {plural(inventario.stacks, 'hueco', 'huecos')}."
            )
            self._mostrar_inventario(inventario)

        def failed(message: str, details: str) -> None:
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
            self.actions_title.setText(f"Acciones para «{name}»")
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
