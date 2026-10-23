"""Ventana unica para gestionar quien entra y quien manda en el servidor.

Reune en un solo sitio las tres listas que el juego guarda en su carpeta:

* **Lista blanca**: los invitados. Con la lista activada solo entra quien esta
  en ella.
* **Bloqueados**: los que no pueden entrar (la «lista negra»).
* **Operadores**: los administradores, con acceso a los comandos de gestion.

Todo se puede hacer con el servidor encendido o apagado. En marcha se envia la
orden a la consola (el cambio se aplica al momento); detenido se escriben las
mismas listas en disco, que es justo lo que se hace al preparar una partida.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import ValidationError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from ..core.players import PlayersSnapshot, validate_player_name
from .common import SectionCard, hint_label, make_button
from .dialogs import confirm, show_error
from .mc_icons import (
    icono_candado,
    icono_corona,
    icono_jugador,
    icono_lista,
    icono_pase,
)
from .tasks import TaskRunner

logger = get_logger("ui.players_manager")

#: Lo que se puede hacer en cada lista: clave de accion para anadir y quitar.
_LISTAS: dict[str, tuple[str, str, str]] = {
    # clave: (titulo, accion de anadir, accion de quitar)
    "whitelist": ("Invitados", "whitelist_add", "whitelist_remove"),
    "banned": ("Bloqueados", "ban", "pardon"),
    "ops": ("Administradores", "op", "deop"),
}

#: Nombre del boton de quitar de cada lista.
_QUITAR: dict[str, str] = {
    "whitelist": "Quitar invitacion",
    "banned": "Dejar entrar",
    "ops": "Quitar administrador",
}

#: Iconos propios de cada lista y de sus botones de anadir/quitar.
_ICONOS: dict[str, tuple[object, object]] = {
    "whitelist": (icono_pase, icono_lista),
    "banned": (icono_candado, icono_pase),
    "ops": (icono_corona, icono_corona),
}

#: Ayuda que explica de que va todo esto.
_AYUDA = (
    "<b>Invitados (lista blanca):</b> los amigos de confianza. Si la opcion "
    "«Solo pueden entrar los invitados» esta marcada, solo entra quien este en "
    "esta lista; los demas veran que no estan invitados."
    "<br><br><b>Bloqueados:</b> jugadores a los que se les ha cerrado la puerta. "
    "No pueden entrar aunque esten invitados, hasta que les quites el bloqueo."
    "<br><br><b>Administradores:</b> jugadores con poderes especiales dentro del "
    "juego. Pueden cambiar el modo de juego, teletransportarse o dar objetos."
    "<br><br>Con el servidor <b>encendido</b> los cambios se aplican al momento. "
    "Con el servidor <b>detenido</b> se guardan en sus listas y valen desde el "
    "proximo arranque."
)


class PlayersManagerDialog(QDialog):
    """Gestion de la lista blanca, los bloqueados y los operadores."""

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        spec: ServerSpec,
        *,
        parent: QWidget | None = None,
        on_changed=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self.spec = spec
        self._on_changed = on_changed
        self._snapshot: PlayersSnapshot | None = None
        self._consultando = False
        self._aplicando = False
        self._cerrado = False

        self.setWindowTitle(f"Quien puede entrar - {spec.name}")
        self.setObjectName("PlayersManager")
        self.setModal(False)
        self.setMinimumSize(480, 420)
        self.resize(640, 540)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.card = SectionCard(
            "Quien puede entrar",
            help_title="Lista blanca, bloqueados y operadores",
            help_text=_AYUDA,
        )
        cuerpo = self.card.body()

        self.resumen = hint_label("")
        self.resumen.setWordWrap(True)
        cuerpo.addWidget(self.resumen)

        self.whitelist_check = QCheckBox("Solo pueden entrar los invitados (lista blanca)")
        self.whitelist_check.setToolTip(
            "Con esta opcion activada, solo entra quien este en la lista de invitados. "
            "El cambio se guarda en el servidor y se aplica al momento si esta encendido."
        )
        self.whitelist_check.toggled.connect(self._on_toggle_whitelist)
        cuerpo.addWidget(self.whitelist_check)
        self.whitelist_hint = hint_label("")
        cuerpo.addWidget(self.whitelist_hint)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self._lists: dict[str, QListWidget] = {}
        self._inputs: dict[str, QLineEdit] = {}
        self._add_buttons: dict[str, QWidget] = {}
        self._remove_buttons: dict[str, QWidget] = {}
        self._tab_index: dict[str, int] = {}
        for key, (titulo, _add, _remove) in _LISTAS.items():
            indice = self.tabs.addTab(self._build_tab(key), QIcon(_ICONOS[key][0](16)), titulo)
            self._tab_index[key] = indice
        cuerpo.addWidget(self.tabs, 1)

        self.status = hint_label("")
        self.status.setWordWrap(True)
        cuerpo.addWidget(self.status)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Hint")
        self.progress_label.setVisible(False)
        cuerpo.addWidget(self.progress_label)

        outer.addWidget(self.card, 1)

        botones = QHBoxLayout()
        self.refresh_button = make_button(
            "Refrescar", icon_names=("view-refresh",), tooltip="Volver a leer las listas"
        )
        self.refresh_button.clicked.connect(self.refresh)
        botones.addWidget(self.refresh_button)
        botones.addStretch(1)
        self.close_button = make_button("Cerrar", icon_names=("dialog-close",))
        self.close_button.clicked.connect(self.close)
        botones.addWidget(self.close_button)
        outer.addLayout(botones)

        self.refresh()

    # ============================================================== construccion
    def _build_tab(self, key: str) -> QWidget:
        titulo, _add, _remove = _LISTAS[key]
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(10, 10, 10, 10)
        box.setSpacing(8)

        lista = QListWidget()
        lista.setObjectName("PlayersList")
        lista.setAlternatingRowColors(True)
        lista.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        lista.itemDoubleClicked.connect(lambda _item, k=key: self._quitar(k))
        lista.currentItemChanged.connect(lambda _a, _b, k=key: self._update_buttons(k))
        self._lists[key] = lista
        box.addWidget(lista, 1)

        fila = QHBoxLayout()
        fila.setSpacing(8)
        campo = QLineEdit()
        campo.setPlaceholderText("Nombre del jugador")
        campo.setClearButtonEnabled(True)
        campo.setMaxLength(32)
        campo.returnPressed.connect(lambda k=key: self._anadir(k))
        fila.addWidget(campo, 1)
        self._inputs[key] = campo

        anadir = make_button(
            {
                "whitelist": "Invitar",
                "banned": "Bloquear",
                "ops": "Hacer administrador",
            }.get(key, "Anadir"),
            accent=True,
            tooltip=f"Anadir un jugador a «{titulo}»",
        )
        anadir.setIcon(QIcon(_ICONOS[key][0](16)))
        anadir.clicked.connect(lambda _checked=False, k=key: self._anadir(k))
        self._add_buttons[key] = anadir
        fila.addWidget(anadir)

        quitar = make_button(
            _QUITAR[key],
            danger=key == "banned",
            tooltip=f"Quitar al jugador elegido de «{titulo}»",
        )
        quitar.setIcon(QIcon(_ICONOS[key][1](16)))
        quitar.clicked.connect(lambda _checked=False, k=key: self._quitar(k))
        self._remove_buttons[key] = quitar
        fila.addWidget(quitar)
        box.addLayout(fila)
        return page

    # ================================================================= consultas
    def refresh(self) -> None:
        if self._cerrado or self._consultando:
            return
        self._consultando = True
        spec = self.spec
        self.status.setText("Leyendo las listas del servidor...")

        def work(*, context) -> PlayersSnapshot:
            context.progress("Consultando lista blanca, bloqueados y operadores...")
            return self.manager.players_snapshot(spec.id)

        def done(snapshot: PlayersSnapshot) -> None:
            self._consultando = False
            if self._cerrado:
                return
            self._on_snapshot(snapshot)

        def failed(message: str, details: str) -> None:
            self._consultando = False
            if self._cerrado:
                return
            self.status.setText(f"No se pudieron leer las listas: {message}")
            logger.warning("No se pudieron leer las listas de %s: %s", spec.name, message)

        self.runner.submit(
            "Leyendo listas de jugadores",
            work,
            on_finished=done,
            on_failed=failed,
            track_busy=False,
        )

    def _on_snapshot(self, snapshot: PlayersSnapshot) -> None:
        self._snapshot = snapshot
        self.whitelist_check.blockSignals(True)
        self.whitelist_check.setChecked(snapshot.whitelist_enabled)
        self.whitelist_check.blockSignals(False)

        nombres = {
            "whitelist": snapshot.whitelist,
            "banned": snapshot.banned,
            "ops": snapshot.ops,
        }
        for key, (titulo, _add, _remove) in _LISTAS.items():
            lista = self._lists[key]
            lista.clear()
            for name in nombres[key]:
                item = QListWidgetItem(QIcon(icono_jugador(16)), name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                if key == "banned":
                    item.setForeground(QColor("#c94f4f"))
                elif key == "ops":
                    item.setForeground(QColor("#e3b341"))
                lista.addItem(item)
            self.tabs.setTabText(self._tab_index[key], f"{titulo} ({len(nombres[key])})")
            self._update_buttons(key)

        estado = "activada" if snapshot.whitelist_enabled else "desactivada"
        if snapshot.running:
            conectados = ", ".join(snapshot.online) if snapshot.online else "nadie"
            self.resumen.setText(
                f"Servidor encendido. Lista blanca {estado}. Ahora mismo en el juego: {conectados}."
            )
        else:
            self.resumen.setText(
                f"Servidor detenido. Lista blanca {estado}. Los cambios se guardan para el "
                "proximo arranque."
            )
        self.whitelist_hint.setText(
            "Ahora solo entran los invitados. Es la opcion recomendada para jugar con amigos."
            if snapshot.whitelist_enabled
            else "Ahora puede entrar cualquiera que tenga la direccion. Activa esta opcion para "
            "jugar solo con tus invitados."
        )
        self.status.setText(snapshot.note or "Listas al dia.")

    # ================================================================== acciones
    def _player_of(self, key: str) -> str:
        lista = self._lists[key]
        item = lista.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def _update_buttons(self, key: str) -> None:
        hay_seleccion = self._lists[key].currentItem() is not None
        self._remove_buttons[key].setEnabled(hay_seleccion and not self._aplicando)
        self._add_buttons[key].setEnabled(not self._aplicando)
        self._inputs[key].setEnabled(not self._aplicando)

    def _anadir(self, key: str) -> None:
        if self._aplicando:
            return
        texto = self._inputs[key].text().strip()
        try:
            name = validate_player_name(texto)
        except ValidationError as exc:
            show_error(self, "Nombre no valido", exc.message)
            return
        _titulo, accion, _quitar = _LISTAS[key]
        if key == "banned" and not confirm(
            self,
            "Bloquear jugador",
            f"«{name}» no podra entrar al servidor hasta que lo perdones.\n\n"
            "Si esta jugando ahora mismo, lo saca al momento.",
            confirm_label="Bloquear",
            destructive=True,
        ):
            return
        self._aplicar(key, accion, name)

    def _quitar(self, key: str) -> None:
        if self._aplicando:
            return
        name = self._player_of(key)
        if not name:
            self.status.setText("Elige antes un jugador de la lista.")
            return
        _titulo, _add, accion = _LISTAS[key]
        if key == "banned" and not confirm(
            self,
            "Perdonar jugador",
            f"«{name}» podra volver a entrar al servidor.",
            confirm_label="Perdonar",
        ):
            return
        self._aplicar(key, accion, name)

    def _aplicar(self, key: str, accion: str, name: str) -> None:
        self._aplicando = True
        for k in _LISTAS:
            self._update_buttons(k)
        self.whitelist_check.setEnabled(False)
        self.progress_label.setText(f"Aplicando el cambio a «{name}»...")
        self.progress_label.setVisible(True)
        spec = self.spec

        def work(*, context) -> str:
            context.progress("Enviando el cambio...")
            return self.manager.run_player_action(spec.id, accion, name)

        def done(response: str) -> None:
            self._aplicando = False
            self.whitelist_check.setEnabled(True)
            self.progress_label.setVisible(False)
            if self._cerrado:
                return
            self._inputs[key].clear()
            self.status.setText(str(response or "Cambio aplicado.").strip())
            if self._on_changed is not None:
                try:
                    self._on_changed()
                except Exception:  # pragma: no cover - la ventana principal manda
                    logger.exception("No se pudo avisar del cambio de listas")
            self.refresh()

        def failed(message: str, details: str) -> None:
            self._aplicando = False
            self.whitelist_check.setEnabled(True)
            self.progress_label.setVisible(False)
            if self._cerrado:
                return
            for k in _LISTAS:
                self._update_buttons(k)
            show_error(self, "No se pudo aplicar el cambio", message, details)

        self.runner.submit("Cambiando listas de jugadores", work, on_finished=done, on_failed=failed)

    def _on_toggle_whitelist(self, enabled: bool) -> None:
        if self._aplicando or self._snapshot is None:
            return
        if self._snapshot.whitelist_enabled == enabled:
            return
        self._aplicando = True
        self.whitelist_check.setEnabled(False)
        self.progress_label.setText(
            "Activando la lista blanca..." if enabled else "Desactivando la lista blanca..."
        )
        self.progress_label.setVisible(True)
        spec = self.spec

        def work(*, context) -> bool:
            return self.manager.set_whitelist_enabled(spec.id, enabled)

        def done(_value: bool) -> None:
            self._aplicando = False
            self.whitelist_check.setEnabled(True)
            self.progress_label.setVisible(False)
            if self._cerrado:
                return
            self.status.setText(
                "Listo: solo entran los invitados."
                if enabled
                else "Listo: ahora puede entrar cualquiera."
            )
            self.whitelist_hint.setText(
                "Ahora solo entran los invitados. Es la opcion recomendada para jugar con amigos."
                if enabled
                else "Ahora puede entrar cualquiera que tenga la direccion."
            )
            if self._on_changed is not None:
                try:
                    self._on_changed()
                except Exception:  # pragma: no cover
                    logger.exception("No se pudo avisar del cambio de lista blanca")
            self.refresh()

        def failed(message: str, details: str) -> None:
            self._aplicando = False
            self.whitelist_check.setEnabled(True)
            self.progress_label.setVisible(False)
            if self._snapshot is not None:
                self.whitelist_check.blockSignals(True)
                self.whitelist_check.setChecked(self._snapshot.whitelist_enabled)
                self.whitelist_check.blockSignals(False)
            if self._cerrado:
                return
            show_error(self, "No se pudo cambiar la lista blanca", message, details)

        self.runner.submit(
            "Cambiando la lista blanca", work, on_finished=done, on_failed=failed
        )

    # =================================================================== cierre
    def closeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        self._cerrado = True
        super().closeEvent(event)


__all__ = ["PlayersManagerDialog"]
