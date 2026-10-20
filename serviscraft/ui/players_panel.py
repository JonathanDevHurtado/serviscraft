"""Pestana de jugadores: quien esta conectado, lista blanca y operadores.

La consulta de jugadores conectados y las acciones (OP, expulsar, lista blanca)
se hacen por consola RCON, que solo responde con el servidor en marcha. La lista
blanca y los operadores se leen ademas de los ficheros del servidor, asi que la
pestana sigue mostrando informacion util cuando el servidor esta detenido.

Desde aqui tambien se abre el **inventario** de un jugador conectado: el servidor
lo cuenta por su consola (``data get entity``) y se enseña con la misma
disposicion que la mochila del juego.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
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
from ..core.players import PLAYER_ACTIONS, PlayersSnapshot, PlayerAction, validate_player_name
from .common import Chip, FlowRow, SectionCard, hint_label, make_button, plural, polish_table_header
from .dialogs import confirm, show_error
from .inventory_dialog import InventoryDialog
from .mc_icons import icono_jugador, icono_mochila
from .players_manager_dialog import PlayersManagerDialog
from .tasks import TaskRunner

logger = get_logger("ui.players")

#: Color con el que se marca lo bueno (conectado, operador...) y lo malo (bloqueado).
_BUENO = "#2e7d32"
_MALO = "#b3261e"

#: Icono de cada accion de jugador (del tema del escritorio; si no existe, sin icono).
_ACTION_ICONS: dict[str, tuple[str, ...]] = {
    "op": ("starred", "emblem-favorite"),
    "deop": ("non-starred", "emblem-important"),
    "whitelist_add": ("list-add", "dialog-ok-apply"),
    "whitelist_remove": ("list-remove", "edit-delete"),
    "kick": ("go-out", "process-stop"),
    "ban": ("process-stop", "dialog-error"),
    "pardon": ("edit-undo", "dialog-ok"),
}

_ACTION_TIPS: dict[str, str] = {
    "op": "Dar permisos de administrador al jugador",
    "deop": "Quitarle los permisos de administrador",
    "whitelist_add": "Dejarle entrar aunque la lista blanca este activada",
    "whitelist_remove": "Quitarle el permiso de la lista blanca",
    "kick": "Sacarlo del juego (puede volver a entrar)",
    "ban": "Sacarlo y bloquearlo: no podra volver hasta que lo perdones",
    "pardon": "Levantarle el bloqueo",
}

_AYUDA = (
    "<b>Quien esta jugando:</b> la tabla dice, de cada jugador, si esta dentro del "
    "juego ahora mismo, si esta en la lista blanca, si es operador y si esta "
    "bloqueado."
    "<br><br><b>La lista blanca</b> son los invitados: con la lista activada, solo "
    "entra quien esta en ella."
    "<br><br><b>Operador (OP)</b> es un jugador con poderes de administrador: puede "
    "usar comandos de gestion y de trampas."
    "<br><br><b>Gestionar listas...</b> abre una ventana con la lista blanca, los "
    "bloqueados y los operadores, para anadir y quitar a quien quieras de una vez. "
    "Funciona con el servidor encendido (se aplica al momento) y apagado (se guarda "
    "para el proximo arranque)."
    "<br><br><b>Los botones de cada jugador</b> son atajos para lo mismo: dar o quitar "
    "OP, meter o sacar de la lista, bloquear o perdonar. Expulsar si necesita el "
    "servidor encendido, porque la orden va a su consola."
    "<br><br><b>Ver inventario</b> enseña lo que lleva encima el jugador elegido: su "
    "mochila, su armadura y su barra rapida. Solo funciona si esta conectado."
)


class PlayersPanel(QWidget):
    """Gestiona los jugadores del servidor seleccionado."""

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._running = False
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
        layout.setSpacing(8)

        self.card = SectionCard(
            "Jugadores",
            pixmap=icono_jugador(18),
            help_title="Jugadores: quien entra y que puede hacer",
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

        # Nombre del jugador + refrescar.
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.player_input = QLineEdit()
        self.player_input.setPlaceholderText("Jugador (o selecciona una fila de la tabla)")
        self.player_input.setClearButtonEnabled(True)
        self.player_input.setMaxLength(32)
        self.player_input.returnPressed.connect(self._on_op)
        name_row.addWidget(self.player_input, 1)
        self.refresh_button = make_button(
            "Refrescar", icon_names=("view-refresh",), tooltip="Volver a leer quien esta jugando"
        )
        self.refresh_button.clicked.connect(self.refresh)
        name_row.addWidget(self.refresh_button)
        cuerpo.addLayout(name_row)

        # Acciones. Todo en filas que se envuelven para que ningun boton quede
        # recortado cuando la ventana es estrecha.
        self.actions_row = FlowRow(spacing=8)
        self._action_buttons: dict[str, QWidget] = {}

        self.manage_button = make_button(
            "Gestionar listas...",
            accent=True,
            icon_names=("system-users", "preferences-system-users"),
            tooltip="Lista blanca, bloqueados y operadores en una sola ventana",
        )
        self.manage_button.setIcon(QIcon(icono_jugador(16)))
        self.manage_button.clicked.connect(self._abrir_gestion)
        self._action_buttons["gestion"] = self.manage_button
        self.actions_row.add(self.manage_button)

        for action in PLAYER_ACTIONS:
            button = make_button(
                action.label,
                icon_names=_ACTION_ICONS.get(action.key, ()),
                danger=action.destructive,
                tooltip=action.warning or _ACTION_TIPS.get(action.key, f"Envia «{action.command}»"),
            )
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

        self.status = self._hint("")
        cuerpo.addWidget(self.status)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Jugador", "Conectado", "Lista blanca", "Operador", "Bloqueado"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        polish_table_header(self.table)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(lambda _index: self._ver_inventario())
        cuerpo.addWidget(self.table, 1)

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

        layout.addWidget(self.card, 1)

        self.empty = QLabel("Selecciona un servidor para ver sus jugadores.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None, running=False)

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
            self.status.clear()
            self.warning.clear()
            self.warning.setVisible(False)
            self.table.setRowCount(0)
            self._ocultar_inventario()
            self._cerrar_gestion()
            self._fallo_avisado = False
        self._spec = spec
        self._running = running
        has_server = spec is not None
        # Se ocultan uno a uno (ademas de la tarjeta): asi una ventana sin
        # servidor no deja ningun control suelto.
        for widget in (
            self.card,
            self.chips,
            self.table,
            self.refresh_button,
            self.player_input,
            self.actions_row,
            self.status,
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
        self.table.setRowCount(0)
        for name in snapshot.known:
            fila = self.table.rowCount()
            self.table.insertRow(fila)
            conectado = snapshot.is_online(name)
            item = QTableWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setIcon(QIcon(icono_jugador(16)))
            if conectado:
                fuente = QFont(item.font())
                fuente.setBold(True)
                item.setFont(fuente)
                item.setForeground(QColor(_BUENO))
            self.table.setItem(fila, 0, item)
            self.table.setItem(fila, 1, self._celda(conectado, bueno=True))
            self.table.setItem(fila, 2, self._celda(snapshot.in_whitelist(name), bueno=True))
            self.table.setItem(fila, 3, self._celda(snapshot.is_op(name), bueno=True))
            self.table.setItem(fila, 4, self._celda(snapshot.is_banned(name), bueno=False))
        self._actualizar_chips(snapshot)
        self.status.setText(self._summary(snapshot))
        self.warning.setText(snapshot.note)
        self.warning.setVisible(bool(snapshot.note))
        if snapshot.known:
            self.table.selectRow(0)
        self._update_actions()

    @staticmethod
    def _celda(activo: bool, *, bueno: bool) -> QTableWidgetItem:
        """Casilla «Si»/«No» de la tabla, con el color de lo que significa."""
        celda = QTableWidgetItem("Si" if activo else "No")
        celda.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if activo:
            celda.setForeground(QColor(_BUENO if bueno else _MALO))
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
        if name:
            self.player_input.setText(name)

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
        if not self._running and action.key == "kick":
            show_error(
                self,
                "El servidor esta detenido",
                "Para expulsar a alguien el servidor tiene que estar encendido: la orden "
                "se envia a su consola. Para dejarlo fuera, usa «Bloquear».",
            )
            return
        if action.destructive and not confirm(
            self,
            f"{action.label}?",
            f"Jugador: «{player}».\n\n{action.warning}",
            confirm_label=action.label,
            destructive=True,
        ):
            return

        spec = self._spec
        self._set_busy(True, f"Aplicando «{action.label}» a {player}...")

        def work(*, context) -> str:
            context.progress("Aplicando el cambio en las listas del servidor...")
            return self.manager.run_player_action(spec.id, action.key, player)

        def done(response: str) -> None:
            self._set_busy(False)
            text = str(response or "").strip()
            self.status.setText(text or f"Accion aplicada a «{player}».")
            self.refresh()

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            show_error(self, "No se pudo aplicar la accion", message, details)

        self.runner.submit(action.label, work, on_finished=done, on_failed=failed)

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
        """Las listas se pueden tocar tambien con el servidor apagado.

        Solo «Expulsar» (y el inventario) necesitan la consola del servidor, asi
        que el resto se queda disponible siempre que haya un servidor elegido.
        """
        hay_servidor = self._spec is not None
        for key, button in self._action_buttons.items():
            if key in {"kick", "inventario"}:
                button.setEnabled(hay_servidor and self._running)
            else:
                button.setEnabled(hay_servidor)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.progress.setVisible(busy)
        for key, button in self._action_buttons.items():
            if key in {"kick", "inventario"}:
                habilitado = not busy and self._spec is not None and self._running
            else:
                habilitado = not busy and self._spec is not None
            button.setEnabled(habilitado)
        self.refresh_button.setEnabled(not busy)
        if message:
            self.status.setText(message)
