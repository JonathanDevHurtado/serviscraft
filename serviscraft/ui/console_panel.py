"""Panel de consola: registro en tiempo real y envio de comandos.

Se parece a la consola de verdad, pero pensada para no perderse: el estado del
servidor se ve en un punto de color, las lineas importantes van coloreadas (con
su leyenda al lado) y hay un filtro para quedarse solo con los problemas cuando
algo va mal.
"""

from __future__ import annotations

import re
from html import escape

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QIcon, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec, ServerState
from .common import ElidedLabel, FlowRow, SectionCard, WrappingLabel, hint_label, make_button
from .mc_icons import icono_consola, punto_estado
from .tasks import TaskRunner

logger = get_logger("ui.console")

#: Numero maximo de lineas que se conservan en pantalla.
MAX_LINES = 6000

#: Comandos de uso frecuente que se ofrecen en el desplegable.
QUICK_COMMANDS: tuple[tuple[str, str], ...] = (
    ("list", "Jugadores conectados"),
    ("tps", "Rendimiento del servidor (Paper/Spigot)"),
    ("say ", "Enviar un mensaje a todos"),
    ("save-all", "Guardar el mundo en disco"),
    ("whitelist list", "Ver la lista blanca"),
    ("whitelist add ", "Anadir un jugador a la lista blanca"),
    ("op ", "Dar permisos de operador"),
    ("deop ", "Quitar permisos de operador"),
    ("kick ", "Expulsar a un jugador"),
    ("ban ", "Banear a un jugador"),
    ("pardon ", "Perdonar a un jugador"),
    ("time set day", "Poner el dia"),
    ("weather clear", "Despejar el tiempo"),
    ("difficulty peaceful", "Dificultad pacifica"),
    ("stop", "Detener el servidor guardando el mundo"),
)

_ERROR_RE = re.compile(r"\b(ERROR|FATAL|SEVERE|Exception|Caused by|/ERROR)\b")
_WARN_RE = re.compile(r"\b(WARN|WARNING)\b")
_INFO_RE = re.compile(r"\b(INFO)\b")
_CHAT_RE = re.compile(r"\]: <[^>]+> ")
_READY_RE = re.compile(r"Done \(")

#: Que significa cada color del registro, con su cuadradito del color de verdad.
_LEYENDA = (
    '<span style="color:#7fd6a2">■</span> listo &nbsp; '
    '<span style="color:#8ab4f8">■</span> respuesta &nbsp; '
    '<span style="color:#ffcc66">■</span> aviso &nbsp; '
    '<span style="color:#ff6b6b">■</span> error &nbsp; '
    '<span style="color:#e8c6ff">■</span> chat &nbsp; '
    '<span style="color:#a8adb5">■</span> normal'
)

_AYUDA = (
    "La consola es la <b>ventana al servidor</b>: aqui se ve todo lo que va "
    "pasando (quien entra, que carga, que falla) y se pueden escribir las mismas "
    "ordenes que en un servidor de verdad."
    "<br><br>· <b>Seguir en vivo</b>: la consola se actualiza sola, sin pulsar "
    "nada. Si lo desactivas, deja de traer lineas nuevas."
    "<br>· <b>Desplazamiento automatico</b>: baja solo hasta la ultima linea."
    "<br>· <b>Solo problemas</b>: esconde lo normal y deja los avisos y los "
    "errores, para encontrar el fallo rapido."
    "<br>· <b>Comandos...</b>: atajos de las ordenes mas usadas (por ejemplo "
    "<i>list</i> para ver quien esta jugando, o <i>stop</i> para parar el servidor "
    "guardando el mundo)."
    "<br><br>Los comandos se envian por la consola del servidor en el bucle local "
    "(nunca por la red) y el servidor tiene que estar encendido."
)


class ConsolePanel(QWidget):
    """Consola del servidor seleccionado."""

    command_sent = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._process: QProcess | None = None
        #: Ultimo estado conocido del servidor (lo fija la ventana principal).
        #: Se guarda para poder repintar (al filtrar o limpiar) sin volver a
        #: preguntar: una consulta a destiempo diria «detenido» mientras arranca.
        self._state: ServerState = ServerState.MISSING
        self._history: list[str] = []
        self._history_index = 0
        self._follow = True
        #: Lineas recibidas (para poder volver a pintarlas al cambiar el filtro).
        self._lines: list[str] = []
        #: Lineas escondidas por el filtro «Solo problemas».
        self._hidden = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.card = SectionCard(
            "Consola del servidor",
            pixmap=icono_consola(18),
            help_title="La consola: para que sirve y como se usa",
            help_text=_AYUDA,
        )
        cuerpo = self.card.body()

        # ---------------------------------------------------------- barra superior
        # El resumen de estado va en su propia linea: asi siempre se lee entero
        # (se recorta con puntos suspensivos si falta sitio) y los botones tienen
        # toda la linea siguiente para ellos, donde se envuelven si no caben.
        estado = QHBoxLayout()
        estado.setSpacing(6)
        self.state_dot = QLabel()
        self.state_dot.setFixedSize(12, 12)
        self.state_dot.setPixmap(punto_estado("#6b7280"))
        estado.addWidget(self.state_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_label = ElidedLabel("Sin servidor seleccionado")
        self.status_label.setObjectName("Hint")
        estado.addWidget(self.status_label, 1)
        cuerpo.addLayout(estado)

        # La casilla y los botones van en una fila que se envuelve cuando la
        # ventana se estrecha.
        self.console_actions = FlowRow()
        self.autoscroll = QCheckBox("Desplazamiento automatico")
        self.autoscroll.setChecked(True)
        self.console_actions.add(self.autoscroll)

        self.follow_button = make_button(
            "Seguir en vivo",
            icon_names=("media-playback-start", "system-run"),
            tooltip="Mostrar la consola en tiempo real",
        )
        self.follow_button.setCheckable(True)
        self.follow_button.setChecked(True)
        self.follow_button.toggled.connect(self._on_follow_toggled)
        self.console_actions.add(self.follow_button)

        self.only_problems = QCheckBox("Solo problemas")
        self.only_problems.setToolTip(
            "Esconder las lineas normales y dejar solo los avisos y los errores"
        )
        self.only_problems.toggled.connect(self._on_filter_toggled)
        self.console_actions.add(self.only_problems)

        clear_button = make_button(
            "Limpiar",
            icon_names=("edit-clear", "edit-clear-history"),
            tooltip="Vaciar la consola en pantalla (el servidor no se toca)",
        )
        clear_button.clicked.connect(self._clear)
        self.console_actions.add(clear_button)

        copy_button = make_button(
            "Copiar todo",
            icon_names=("edit-copy",),
            tooltip="Copiar lo que se ve a la memoria, para pegarlo donde quieras",
        )
        copy_button.clicked.connect(self._copy_all)
        self.console_actions.add(copy_button)

        save_button = make_button(
            "Guardar registro",
            icon_names=("document-save", "document-save-as"),
            tooltip="Guardar la consola en un fichero de texto",
        )
        save_button.clicked.connect(self._save_log)
        self.console_actions.add(save_button)
        cuerpo.addWidget(self.console_actions)

        # Leyenda de colores: la consola se entiende sin manual. Va en una sola
        # linea ajustable (no en fichas) para no robarle alto al registro, que es
        # lo que de verdad se mira.
        self.legend = WrappingLabel(_LEYENDA)
        # La leyenda si lleva formato propio (los cuadraditos de color); el
        # resto de textos de la consola se pintan siempre en plano.
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setText(_LEYENDA)
        self.legend.setObjectName("Hint")
        cuerpo.addWidget(self.legend)

        # ----------------------------------------------------------------- salida
        self.output = QPlainTextEdit()
        self.output.setObjectName("ConsoleOutput")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(MAX_LINES)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.output.setFont(font)
        cuerpo.addWidget(self.output, 1)

        # ---------------------------------------------------------------- entrada
        entry = QHBoxLayout()
        entry.setSpacing(8)

        self.input = QLineEdit()
        self.input.setObjectName("ConsoleInput")
        self.input.setPlaceholderText("Escribe un comando y pulsa Intro (por ejemplo: list)")
        self.input.returnPressed.connect(self._send)
        self.input.installEventFilter(self)
        entry.addWidget(self.input, 1)

        self.quick = QComboBox()
        self.quick.setToolTip("Comandos frecuentes, con lo que hace cada uno")
        self.quick.addItem("Comandos...", "")
        for command, description in QUICK_COMMANDS:
            self.quick.addItem(command, command)
            self.quick.setItemData(self.quick.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        self.quick.activated.connect(self._use_quick_command)
        entry.addWidget(self.quick)

        self.send_button = make_button(
            "Enviar",
            icon_names=("document-send", "go-next"),
            accent=True,
            tooltip="Enviar el comando al servidor",
        )
        self.send_button.setIcon(QIcon.fromTheme("document-send"))
        self.send_button.clicked.connect(self._send)
        entry.addWidget(self.send_button)
        cuerpo.addLayout(entry)

        self.hint = hint_label(
            "Los comandos se envian a la consola del servidor por RCON en el bucle local "
            "(nunca por la red). El servidor debe estar en ejecucion."
        )
        cuerpo.addWidget(self.hint)

        layout.addWidget(self.card, 1)

        self.set_server(None, ServerState.MISSING)

    # ============================================================ API publica
    def set_server(self, spec: ServerSpec | None, state: ServerState) -> None:
        """Cambia el servidor mostrado y reinicia el seguimiento del registro."""
        changed = self._spec is None or spec is None or (self._spec.id != spec.id)
        self._spec = spec
        self.stop_stream()
        if changed:
            self._lines.clear()
            self._hidden = 0
            self.output.clear()
            self._history.clear()
            self._history_index = 0
        self.refresh_state(state)

    def refresh_state(self, state: ServerState) -> None:
        """Ajusta la interfaz al estado actual del servidor."""
        self._state = state
        running = state.is_running
        self.input.setEnabled(running and self._spec is not None)
        self.send_button.setEnabled(running and self._spec is not None)
        self.quick.setEnabled(running and self._spec is not None)
        self.state_dot.setPixmap(punto_estado("#2e7d32" if running else "#6b7280"))
        if self._spec is None:
            base = "Sin servidor seleccionado"
        elif running:
            base = f"Consola de «{self._spec.name}» — en directo"
        else:
            base = (
                f"Consola de «{self._spec.name}» — servidor detenido "
                "(se muestran los ultimos mensajes)"
            )
        self.status_label.setText(base + self._filtro_nota())

    def _filtro_nota(self) -> str:
        """Aviso que acompana al estado cuando hay lineas escondidas."""
        if not self.only_problems.isChecked():
            return ""
        if not self._hidden:
            return " · solo problemas"
        return f" · solo problemas ({self._hidden} lineas ocultas)"

    def load_history(self) -> None:
        """Carga las ultimas lineas del registro del contenedor."""
        if self._spec is None:
            return
        spec = self._spec
        try:
            text = self.manager.recent_logs(spec.id, tail=250)
        except ServiscraftError as exc:
            logger.warning("No se pudieron leer los registros: %s", exc)
            return
        if self._spec is None or self._spec.id != spec.id:
            return
        for line in text.splitlines():
            self._append(line)

    def set_running(self, running: bool) -> None:
        if self._spec is None:
            return
        self.refresh_state(ServerState.RUNNING if running else ServerState.EXITED)

    # =============================================================== streaming
    def start_stream(self) -> None:
        if self._spec is None or self._process is not None:
            return
        if not self._follow:
            return
        try:
            argv = self.manager.console_command(self._spec.id, tail=200)
        except ServiscraftError as exc:
            logger.warning("No se pudo seguir la consola: %s", exc)
            return
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        for variable in ("CONTAINER_HOST", "DOCKER_HOST", "CONTAINER_CONNECTION"):
            environment.remove(variable)
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._read_output)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        logger.debug("Siguiendo la consola: %s", " ".join(argv))
        process.start(argv[0], argv[1:])

    def stop_stream(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            try:
                process.readyReadStandardOutput.disconnect()
                process.finished.disconnect()
                process.errorOccurred.disconnect()
            except (RuntimeError, TypeError):  # pragma: no cover - senales ya desconectadas
                pass
            if process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(1500):
                    process.kill()
                    process.waitForFinished(1500)
            process.deleteLater()

    def _read_output(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._append(line)

    def _on_process_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        logger.debug("Seguimiento de consola finalizado (codigo %s)", exit_code)
        self._process = None
        # Si el servidor sigue en ejecucion, reintentamos el seguimiento.
        if self._spec is not None and self._follow and self.isVisible():
            if self.manager.state(self._spec.id).is_running:
                self.start_stream()

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        logger.warning("Error del proceso de consola: %s", error)
        self._append("[Serviscraft] No se pudo seguir la consola del contenedor.")

    def _on_follow_toggled(self, checked: bool) -> None:
        self._follow = checked
        if checked:
            self.follow_button.setToolTip(
                "La consola se actualiza sola en tiempo real. Pulsa para dejar de seguirla."
            )
            self.start_stream()
        else:
            self.follow_button.setToolTip(
                "Seguimiento en vivo desactivado. Pulsa para volver a ver la consola en directo."
            )
            self.stop_stream()

    # ================================================================== salida
    def _append(self, line: str) -> None:
        """Anade una linea al registro (y a la pantalla, si pasa el filtro)."""
        self._lines.append(line)
        if len(self._lines) > MAX_LINES:
            del self._lines[: len(self._lines) - MAX_LINES]
        if self._pasa_filtro(line):
            self._paint(line)
        else:
            self._hidden += 1

    def _pasa_filtro(self, line: str) -> bool:
        """Con «Solo problemas» se conservan avisos, errores y lo nuestro."""
        if not self.only_problems.isChecked():
            return True
        if line.startswith("[Serviscraft]") or line.startswith("> "):
            return True
        return bool(_ERROR_RE.search(line) or _WARN_RE.search(line))

    def _paint(self, line: str) -> None:
        if not line.strip():
            self.output.appendPlainText("")
            return
        color = self._color_for(line)
        self.output.appendHtml(
            f'<span style="color:{color};font-family:monospace">{_preserve_indent(escape(line))}</span>'
        )
        if self.autoscroll.isChecked():
            self.output.moveCursor(QTextCursor.MoveOperation.End)

    def _render(self) -> None:
        """Vuelve a pintar todo (al cambiar el filtro)."""
        self.output.clear()
        self._hidden = 0
        for line in self._lines:
            if self._pasa_filtro(line):
                self._paint(line)
            else:
                self._hidden += 1
        self.refresh_state(self._state)

    def _on_filter_toggled(self, _activo: bool) -> None:
        self._render()

    def _clear(self) -> None:
        """Vacia la consola en pantalla (sin tocar el servidor)."""
        self._lines.clear()
        self._hidden = 0
        self.output.clear()
        self.refresh_state(self._state)

    @staticmethod
    def _color_for(line: str) -> str:
        if line.startswith("[Serviscraft]"):
            return "#8ab4f8"
        if line.startswith("> "):
            return "#7fd6a2"
        if _ERROR_RE.search(line):
            return "#ff6b6b"
        if _WARN_RE.search(line):
            return "#ffcc66"
        if _CHAT_RE.search(line):
            return "#e8c6ff"
        if _READY_RE.search(line):
            return "#7fd6a2"
        if _INFO_RE.search(line):
            return "#c8ccd2"
        return "#a8adb5"

    # ================================================================== comandos
    def _send(self) -> None:
        if self._spec is None:
            return
        command = self.input.text().strip()
        if not command:
            return
        self.input.clear()
        self._history.append(command)
        self._history_index = len(self._history)
        self._append(f"> {command}")
        spec = self._spec

        def work(*, context) -> str:
            context.progress("Enviando comando...")
            return self.manager.send_command(spec.id, command)

        self.runner.submit(
            f"Comando «{command}»",
            work,
            on_finished=lambda response: self._on_command_response(response),
            on_failed=self._on_command_failed,
        )
        self.command_sent.emit()

    def _on_command_response(self, response: str) -> None:
        if response:
            for line in response.splitlines():
                self._append(f"[Serviscraft] {line}")
        else:
            self._append("[Serviscraft] Comando enviado.")

    def _on_command_failed(self, message: str, details: str) -> None:
        logger.debug("Fallo el comando: %s\n%s", message, details)
        self._append(f"[Serviscraft] Error: {message}")

    def _use_quick_command(self, index: int) -> None:
        command = self.quick.itemData(index) or ""
        if not command:
            return
        self.input.setText(command)
        self.input.setFocus()
        self.quick.setCurrentIndex(0)

    # ================================================================== historial
    def eventFilter(self, source: object, event: QKeyEvent) -> bool:
        """Recall de comandos con las flechas arriba/abajo."""
        if source is self.input and event.type() == QKeyEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up and self._history:
                self._history_index = max(0, self._history_index - 1)
                self.input.setText(self._history[self._history_index])
                return True
            if event.key() == Qt.Key.Key_Down and self._history:
                self._history_index = min(len(self._history), self._history_index + 1)
                if self._history_index == len(self._history):
                    self.input.clear()
                else:
                    self.input.setText(self._history[self._history_index])
                return True
        return super().eventFilter(source, event)

    # ================================================================== guardar
    def _copy_all(self) -> None:
        """Copia lo que se ve a la memoria (util para pedir ayuda con un fallo)."""
        QApplication.clipboard().setText(self.output.toPlainText())
        # El aviso dura un momento y luego vuelve el estado de siempre: el texto
        # de estado es informacion, no un sitio donde dejar mensajes pegados.
        anterior = self.status_label.full_text()
        self.status_label.setText("Consola copiada a la memoria.")
        QTimer.singleShot(1500, lambda: self.status_label.setText(anterior))

    def _save_log(self) -> None:
        if self._spec is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar registro de la consola",
            f"serviscraft-{self._spec.id}.log",
            "Ficheros de registro (*.log *.txt);;Todos los ficheros (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.output.toPlainText())
        except OSError as exc:
            from .dialogs import show_error

            show_error(self, "No se pudo guardar", f"No se pudo escribir el fichero: {exc}")

    # =================================================================== cierre
    def shutdown(self) -> None:
        self.stop_stream()


def _preserve_indent(text: str) -> str:
    """Convierte la indentacion inicial (trazas de error) en espacios duros."""
    match = re.match(r"^[ \t]+", text)
    if not match:
        return text
    prefix = match.group(0).replace("\t", "    ").replace(" ", "&nbsp;")
    return prefix + text[len(match.group(0)) :]
