"""Componentes reutilizables de la interfaz."""

from __future__ import annotations

import html
import os
import shutil
import subprocess
from collections.abc import Iterable

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import ServerState

#: Colores de cada estado del servidor.
STATE_COLORS: dict[ServerState, str] = {
    ServerState.RUNNING: "#2e7d32",
    ServerState.EXITED: "#6b7280",
    ServerState.CREATED: "#2563eb",
    ServerState.PAUSED: "#b45309",
    ServerState.MISSING: "#9ca3af",
    ServerState.UNKNOWN: "#9ca3af",
}


def themed_icon(*names: str, fallback: QIcon | None = None) -> QIcon:
    """Devuelve el primer icono disponible del tema (o el de reserva)."""
    for name in names:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return fallback if fallback is not None else QIcon()


def plural(cantidad: int, singular: str, plural_: str) -> str:
    """«1 servidor», «3 servidores»: el numero y la palabra concuerdan.

    Evita el feo «1 servidor(es)» de los mensajes que lee el usuario.
    """
    return f"{cantidad} {singular if cantidad == 1 else plural_}"


def copiar_al_portapapeles(texto: str) -> bool:
    """Copia texto y confirma que el portapapeles lo acepto.

    En Wayland, Qt puede dejar el texto solo en su portapapeles interno si la
    ventana no tiene foco o si el compositor no publica la seleccion. ``wl-copy``
    habla directamente con el compositor, asi que se usa como respaldo cuando
    esta disponible. En las pruebas ``offscreen`` nunca se llama a programas
    externos: se comprueba solo el portapapeles de Qt.
    """
    if not texto:
        return False
    app = QApplication.instance()
    if app is None:
        return False

    portapapeles = app.clipboard()
    portapapeles.setText(texto)

    plataforma = app.platformName().lower()
    if plataforma == "offscreen":
        return portapapeles.text() == texto

    # En Wayland el respaldo nativo es mas fiable y, ademas, mantiene el texto
    # disponible aunque Serviscraft se cierre antes de pegar.
    if plataforma == "wayland" and os.environ.get("WAYLAND_DISPLAY"):
        wl_copy = shutil.which("wl-copy")
        if wl_copy:
            try:
                resultado = subprocess.run(
                    [wl_copy],
                    input=texto,
                    text=True,
                    timeout=2,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                resultado = None
            if resultado is not None and resultado.returncode == 0:
                return True

    if portapapeles.text() == texto:
        return True

    # Ultimo recurso en X11: xsel/xclip suelen estar instalados en KDE/XFCE.
    if os.environ.get("DISPLAY"):
        xsel = shutil.which("xsel")
        comando = [xsel, "--clipboard", "--input"] if xsel else None
        if comando is None:
            xclip = shutil.which("xclip")
            comando = [xclip, "-selection", "clipboard"] if xclip else None
        if comando:
            try:
                resultado = subprocess.run(
                    comando,
                    input=texto,
                    text=True,
                    timeout=2,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                return False
            return resultado.returncode == 0

    return False


def icon_pixmap(*names: str, size: int = 16) -> QPixmap | None:
    """Pixmap del primer icono del tema que exista (o ``None`` si no hay).

    Se usa donde hace falta un ``QPixmap`` (por ejemplo, el icono de un titulo
    de seccion) en vez de un ``QIcon``.
    """
    icon = themed_icon(*names)
    if icon.isNull():
        return None
    return icon.pixmap(size, size)


class ClickableLabel(QLabel):
    """Etiqueta que se puede pulsar (por ejemplo, el icono del servidor).

    Se usa en sitios donde un boton con texto no cabe: el icono hace de boton y
    el ``tooltip`` explica que hace.
    """

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def parece_texto_con_formato(texto: str) -> bool:
    """Aproxima ``Qt::mightBeRichText`` (PySide6 no lo expone).

    Solo se usa para decidir si el texto lo puede medir la metrica de la fuente
    (texto normal) o si hay que dejar que lo mida Qt (con formato).
    """
    return "<" in texto and ">" in texto


def make_button(
    text: str,
    *,
    icon_names: Iterable[str] = (),
    tooltip: str = "",
    accent: bool = False,
    danger: bool = False,
) -> QPushButton:
    """Crea un boton coherente con el tema."""
    button = QPushButton(text)
    icon = themed_icon(*icon_names)
    if not icon.isNull():
        button.setIcon(icon)
    if tooltip:
        button.setToolTip(tooltip)
    if accent:
        button.setProperty("accent", "true")
    if danger:
        button.setProperty("danger", "true")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


#: Margen (en pixeles) que se anade al ancho del texto completo de una
#: `ElidedLabel` para que `elidedText` no recorte por diferencias de redondeo
#: entre `horizontalAdvance` y la maquetacion real del texto.
_ELIDE_SLACK = 2

#: Caracteres reales (sin contar los puntos suspensivos) que debe conservar un
#: recorte para mostrarse: por debajo de esta cifra no se muestra nada, en vez de
#: dejar un resto sin sentido como «C».
_MIN_VISIBLE_CHARS = 2


class ElidedLabel(QLabel):
    """Etiqueta de una sola linea que se recorta con puntos suspensivos.

    Una ``QLabel`` normal exige el ancho completo de su texto como *ancho
    minimo*, de modo que una linea larga (por ejemplo el resumen del servidor)
    obliga a ensanchar toda la ventana y acaba recortando los botones de al
    lado.

    Esta variante puede encogerse hasta cero y recorta el texto. Su ``sizeHint``
    se calcula siempre a partir del texto **completo** (no del ya recortado), de
    modo que la etiqueta vuelve a crecer cuando hay sitio: si dependiera del
    texto mostrado, el primer recorte la dejaria encogida para siempre.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - API de Qt
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._apply_elide()
        self.updateGeometry()

    def full_text(self) -> str:
        """Texto completo, sin recortar."""
        return self._full_text

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        hint = super().sizeHint()
        return QSize(self._width_for(self._full_text) + _ELIDE_SLACK, hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self._apply_elide()

    def showEvent(self, event) -> None:  # noqa: N802 - API de Qt
        # Al pasar a una pestana visible (o al mostrar la ventana) el ancho puede
        # no cambiar, de modo que hay que recalcular el recorte aqui.
        super().showEvent(event)
        self._apply_elide()

    def changeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.updateGeometry()
            self._apply_elide()

    def _width_for(self, text: str) -> int:
        """Ancho que ocuparia ``text`` con la fuente y el relleno actuales."""
        if not text:
            return 0
        hint = super().sizeHint().width()
        padding = max(0, hint - self.fontMetrics().horizontalAdvance(self.text()))
        return self.fontMetrics().horizontalAdvance(text) + padding

    def _apply_elide(self) -> None:
        width = self.width()
        # Si la etiqueta no esta visible (pestana oculta o ventana aun sin
        # mostrar) su ancho es degenerado y ``elidedText`` devolveria una cadena
        # vacia; en ese caso se conserva el texto completo, que el propio widget
        # ya recorta al pintarse.
        if not (self.isVisible() and width > 0):
            elided = self._full_text
        else:
            elided = self.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, width
            )
            # Con muy poco sitio ``elidedText`` devuelve un resto sin sentido
            # (una sola letra): es preferible no mostrar nada.
            if elided != self._full_text and self._es_resto(elided):
                elided = ""
        if elided != self.text():
            super().setText(elided)

    @staticmethod
    def _es_resto(elided: str) -> bool:
        """Indica si el recorte conserva menos caracteres de los que se muestran."""
        return len(elided.replace("…", "").rstrip()) < _MIN_VISIBLE_CHARS


#: Espaciado por defecto entre los elementos de un `FlowRow`.
_FLOW_SPACING = 8


class FlowLayout(QLayout):
    """Reparte los elementos en fila y los pasa a la siguiente si no caben.

    Adaptación del ejemplo oficial ``FlowLayout`` de Qt: a diferencia de un
    ``QHBoxLayout``, que o recorta los botones o ensancha la ventana, este
    diseño **envuelve** los elementos, de modo que la interfaz funciona con
    cualquier ancho (por ejemplo el que impone un gestor de ventanas con
    mosaico automático como Polonium).

    Su ``sizeHint`` es el ancho de una sola fila y su ``minimumSize`` el del
    elemento más ancho: así, con sitio, todo queda en una fila como siempre y,
    cuando falta, el contenedor se encoge y los elementos se reparten en varias.
    """

    def __init__(
        self, parent: QWidget | None = None, *, margin: int = 0, spacing: int = _FLOW_SPACING
    ) -> None:
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []

    # ------------------------------------------------------- API de QLayout
    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - API de Qt
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - API de Qt
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - API de Qt
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 - API de Qt
        """No expande: el ancho lo decide el contenedor y el alto las filas."""
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - API de Qt
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - API de Qt
        return self._layout(QRect(0, 0, width, 0), only_test=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - API de Qt
        super().setGeometry(rect)
        self._layout(rect, only_test=False)

    def _visibles(self) -> list[QLayoutItem]:
        """Elementos que se deben colocar: los ocultos no ocupan sitio.

        Las acciones de jugador aparecen y desaparecen segun quien este elegido
        (dar o quitar permisos, invitar o bloquear...). Si la fila reservase el
        hueco de los botones ocultos quedarian agujeros en medio de la botonera.
        """
        return [
            item
            for item in self._items
            if item.widget() is None or not item.widget().isHidden()
        ]

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        """Tamaño con todo en una sola fila (el aspecto de siempre)."""
        margins = self.contentsMargins()
        items = self._visibles()
        if not items:
            return QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        width = sum(item.sizeHint().width() for item in items)
        width += self._spacing() * (len(items) - 1)
        height = max(item.sizeHint().height() for item in items)
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    def minimumSize(self) -> QSize:  # noqa: N802 - API de Qt
        """Lo más estrecho posible: el elemento más ancho (los demás envuelven)."""
        margins = self.contentsMargins()
        items = self._visibles()
        if not items:
            return QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        width = max(item.minimumSize().width() for item in items)
        height = max(item.sizeHint().height() for item in items)
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    # ---------------------------------------------------------------- interna
    def _spacing(self) -> int:
        return max(0, self.spacing())

    def _layout(self, rect: QRect, *, only_test: bool) -> int:
        """Coloca los elementos y devuelve el alto necesario para ``rect``."""
        margins = self.contentsMargins()
        x = rect.x() + margins.left()
        y = rect.y() + margins.top()
        # Borde derecho exclusivo: con ``rect.right()`` (que es inclusivo) una fila
        # que encajase justo de ancho se partia por un pixel de mas.
        right = rect.x() + rect.width() - margins.right()
        line_height = 0
        for item in self._visibles():
            size = item.sizeHint()
            # Se cambia de fila si el elemento no cabe y ya hay algo en la actual.
            if x + size.width() > right and line_height > 0:
                x = rect.x() + margins.left()
                y = y + line_height + self._spacing()
                line_height = 0
            if not only_test:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self._spacing()
            line_height = max(line_height, size.height())
        return y + line_height - rect.y() + margins.bottom()


class FlowRow(QWidget):
    """Contenedor fino para un grupo de botones que debe envolverse.

    Sustituye a la fila simple de botones: con espacio se ve igual que siempre
    (una sola línea) y, cuando la ventana se estrecha, los botones pasan a la
    línea siguiente en lugar de recortarse.

    El alto se recalcula al cambiar el ancho para que el diseño funcione aunque
    el contenedor padre no propague ``heightForWidth``.
    """

    def __init__(self, parent: QWidget | None = None, *, spacing: int = _FLOW_SPACING) -> None:
        super().__init__(parent)
        self.setObjectName("FlowRow")
        self.flow = FlowLayout(self, margin=0, spacing=spacing)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def add(self, widget: QWidget) -> QWidget:
        """Añade un widget a la fila y lo devuelve (para encadenar)."""
        self.flow.addWidget(widget)
        return widget

    def clear(self) -> None:
        """Quita todos los widgets de la fila, para volver a llenarla."""
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.setMinimumHeight(0)

    def widgets(self) -> list[QWidget]:
        return [
            item.widget()
            for item in (self.flow.itemAt(i) for i in range(self.flow.count()))
            if item is not None and item.widget() is not None
        ]

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - API de Qt
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - API de Qt
        return self.flow.heightForWidth(width)

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        needed = self.flow.heightForWidth(self.width())
        if self.minimumHeight() != needed:
            self.setMinimumHeight(needed)


class StatusBadge(QLabel):
    """Etiqueta coloreada con el estado del servidor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_state(ServerState.MISSING)

    def set_state(self, state: ServerState) -> None:
        color = QColor(STATE_COLORS.get(state, "#9ca3af"))
        if color.lightness() > 140:
            text_color = "#1f2937"
        else:
            text_color = "#ffffff"
        self.setText(state.label)
        self.setStyleSheet(
            f"#StatusBadge {{ background: {color.name()}; color: {text_color}; }}"
        )


class MinecraftBar(QProgressBar):
    """Barra con el aspecto de la barra de experiencia de Minecraft.

    Se pinta a mano, sin suavizado, con el fondo oscuro, el relleno verde en
    degradado y las marcas de pixel que separan cada tramo.
    """

    def __init__(self, parent: QWidget | None = None, *, color: str = "#7ee22b") -> None:
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._claro = QColor(color).lighter(128)
        self._medio = QColor(color)
        self._oscuro = QColor(color).darker(150)
        self._fondo = QColor("#202020")
        self._marco = QColor("#0a0a0a")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        ancho, alto = self.width(), self.height()
        if ancho <= 0 or alto <= 0:
            return
        painter.fillRect(0, 0, ancho, alto, self._marco)
        painter.fillRect(1, 1, ancho - 2, alto - 2, self._fondo)
        painter.fillRect(1, 1, ancho - 2, 1, QColor(255, 255, 255, 22))

        rango = max(1, self.maximum() - self.minimum())
        fraccion = (self.value() - self.minimum()) / rango
        fraccion = max(0.0, min(1.0, fraccion))
        relleno = int((ancho - 4) * fraccion)
        if relleno > 0:
            degradado = QLinearGradient(0, 2, 0, alto - 2)
            degradado.setColorAt(0.0, self._claro)
            degradado.setColorAt(0.35, self._medio)
            degradado.setColorAt(0.75, self._oscuro)
            degradado.setColorAt(1.0, self._oscuro.darker(115))
            painter.fillRect(2, 2, relleno, alto - 4, degradado)
            painter.fillRect(2, 2, relleno, 1, QColor(255, 255, 255, 95))
            painter.fillRect(2, alto - 3, relleno, 1, QColor(0, 0, 0, 85))
            # Marcas verticales cada seis pixeles: el relieve de la barra del juego.
            painter.setPen(QColor(0, 0, 0, 50))
            x = 2 + 6
            while x < 2 + relleno:
                painter.drawLine(x, 2, x, alto - 3)
                x += 6
            painter.setPen(QColor(255, 255, 255, 150))
            painter.drawLine(2 + relleno - 1, 2, 2 + relleno - 1, alto - 3)
        painter.end()


class MetricBar(QWidget):
    """Barra etiquetada con valor (usada para CPU y RAM)."""

    def __init__(self, title: str, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("MetricLabel")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("MetricValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.value_label)
        layout.addLayout(header)

        self.bar = MinecraftBar()
        self.bar.setObjectName(object_name)
        layout.addWidget(self.bar)

    def set_value(self, percent: float, text: str) -> None:
        self.bar.setValue(int(max(0.0, min(100.0, percent))))
        self.value_label.setText(text)

    def set_tooltip(self, text: str) -> None:
        for widget in (self, self.bar, self.title_label, self.value_label):
            widget.setToolTip(text)

    def reset(self) -> None:
        self.bar.setValue(0)
        self.value_label.setText("—")


class Card(QFrame):
    """Contenedor con borde redondeado y titulo opcional."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            self._layout.addWidget(label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_row(self, widgets: Iterable[QWidget]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        for widget in widgets:
            row.addWidget(widget)
        self._layout.addLayout(row)
        return row


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setStyleSheet("color: rgba(128,128,128,0.35);")
    return line


class WrappingLabel(QLabel):
    """Etiqueta que se ajusta en varias lineas y reserva el alto que necesita.

    ``QLabel`` con ``setWordWrap(True)`` **sabe** ajustar el texto, pero los
    disenos de Qt le piden su alto una sola vez, con el ancho de su ``sizeHint``
    (el de una linea larguisima). En una ventana estrecha el texto necesita mas
    lineas de las que el diseno le habia reservado y Qt lo dibuja centrado: se
    recortaba por arriba y se solapaba con lo de abajo.

    Esta etiqueta reserva su **alto minimo** cada vez que cambia de tamano, de
    texto o de fuente, igual que ``FlowRow`` hace con las filas de botones. El
    alto se mide con la fuente que de verdad se pinta: ``QLabel.heightForWidth``
    no es de fiar con la fuente que impone el estilo (daba el alto de otra
    fuente y en la pestana de Mods sobraba casi una linea por etiqueta).
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        # Texto siempre plano: por aqui pasan nombres de objetos, mensajes del
        # servidor y respuestas de la consola. Con el modo automatico, un texto
        # que empiece por "<" se interpretaria como HTML.
        self.setTextFormat(Qt.TextFormat.PlainText)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    # ---------------------------------------------------------------- medidas
    def _alto_del_texto(self, ancho: int) -> int:
        """Alto que pide el texto para ese ancho (0 si no hay nada que medir)."""
        if ancho <= 0 or not self.text():
            return 0
        if parece_texto_con_formato(self.text()):  # el texto con formato lo mide Qt
            return max(0, super().heightForWidth(ancho))
        metrica = self.fontMetrics()
        alto = metrica.boundingRect(
            QRect(0, 0, ancho, 10000), Qt.TextFlag.TextWordWrap, self.text()
        ).height()
        # ``boundingRect`` mide la tinta; se reserva al menos una linea entera.
        return max(alto, metrica.height())

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - API de Qt
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - API de Qt
        return self._alto_del_texto(width) or super().heightForWidth(width)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        base = super().minimumSizeHint()
        if not self.wordWrap() or self.width() <= 0:
            return base
        return QSize(base.width(), max(base.height(), self._alto_del_texto(self.width())))

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        base = super().sizeHint()
        if not self.wordWrap() or self.width() <= 0:
            return base
        return QSize(base.width(), max(base.height(), self._alto_del_texto(self.width())))

    # ---------------------------------------------------------------- eventos
    def setText(self, text: str) -> None:  # noqa: N802 - API de Qt
        super().setText(text)
        self._ajustar_alto()

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self._ajustar_alto()

    def changeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._ajustar_alto()

    def _ajustar_alto(self) -> None:
        """Reserva el alto que el texto necesita para el ancho actual."""
        if not self.wordWrap() or self.width() <= 0 or not self.text():
            return
        necesario = self._alto_del_texto(self.width())
        if necesario > 0 and self.minimumHeight() != necesario:
            self.setMinimumHeight(necesario)


def hint_label(text: str) -> QLabel:
    label = WrappingLabel(text)
    label.setObjectName("Hint")
    return label


def escape_text(value: object) -> str:
    """Escapa un texto que viene de fuera (Modrinth, el servidor, un fichero).

    Qt interpreta como HTML los textos y las ayudas emergentes que "parecen"
    HTML: un nombre de objeto o la descripcion de un mod podian colar etiquetas.
    Se usa en cualquier sitio donde el dato no lo escriba la aplicacion.
    """
    return html.escape(str(value or ""), quote=False)


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def polish_table_header(table) -> None:
    """Alinea a la izquierda las cabeceras (Qt las centra por defecto) y las fija."""
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setSectionsClickable(False)
    for column in range(table.columnCount()):
        item = table.horizontalHeaderItem(column)
        if item is not None:
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


def empty_state(text: str) -> QLabel:
    label = WrappingLabel(text)
    label.setObjectName("EmptyState")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


class NumberBox(QSpinBox):
    """Caja de numeros que se puede escribir de verdad.

    La caja de Qt, tal cual viene, tiene dos manias que estropean el formulario:

    * al hacer clic dentro **no** selecciona el numero, asi que teclear «8192»
      encima de «2048» daba «12048» (o «2048192»). Aqui un clic deja el numero
      listo para reemplazar.
    * la rueda del raton cambia el valor sin querer cuando se baja por el
      formulario. Aqui la rueda se ignora y sigue su camino (el desplazamiento).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # El aviso de al lado se actualiza al terminar de escribir, no en cada
        # tecla (asi no aparecen valores intermedios como «5 MB»).
        self.setKeyboardTracking(False)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        # Con el tabulador, Qt no selecciona el texto: se hace aqui.
        self.selectAll()

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.selectAll()

    def wheelEvent(self, event) -> None:
        event.ignore()


class NumberSlider(QWidget):
    """Caja de numeros con deslizador, sincronizados.

    Se usa para la memoria (RAM): el deslizador permite ir de un extremo a otro
    de un gesto y la caja sigue admitiendo un numero exacto escrito a mano.
    """

    valueChanged = Signal(int)

    def __init__(
        self,
        *,
        minimum: int,
        maximum: int,
        step: int,
        value: int,
        suffix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.step = max(1, step)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(self.step)
        self.slider.setPageStep(self.step * 4)
        self.slider.setMinimumWidth(90)
        self.slider.setToolTip(f"Desliza para elegir; se ajusta de {self.step} en {self.step}")
        layout.addWidget(self.slider, 1)

        self.box = NumberBox()
        self.box.setRange(minimum, maximum)
        self.box.setSingleStep(self.step)
        self.box.setSuffix(suffix)
        self.box.setValue(value)
        self.box.setMinimumWidth(112)
        layout.addWidget(self.box)
        layout.addStretch(0)

        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_slider)
        self.box.valueChanged.connect(self._on_box)

    # ------------------------------------------------------------ sincronia
    def _on_slider(self, value: int) -> None:
        ajustado = min(max(value - (value % self.step), self.box.minimum()), self.box.maximum())
        if ajustado != value:
            # El deslizador tambien se pega al multiplo: si no, la bolita y la caja
            # dirian cosas distintas.
            self.slider.blockSignals(True)
            self.slider.setValue(ajustado)
            self.slider.blockSignals(False)
        self.box.blockSignals(True)
        self.box.setValue(ajustado)
        self.box.blockSignals(False)
        self._emitir()

    def _on_box(self, _value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self.box.value())
        self.slider.blockSignals(False)
        self._emitir()

    def _emitir(self) -> None:
        self.valueChanged.emit(self.value())

    # ----------------------------------------------------------------- API
    def value(self) -> int:
        return self.box.value()

    def setValue(self, value: int) -> None:
        """Cambia el valor sin avisar (para rellenar el formulario al abrirlo)."""
        self.box.blockSignals(True)
        self.box.setValue(value)
        self.box.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setValue(self.box.value())
        self.slider.blockSignals(False)


class OperationBar(QFrame):
    """Barra inferior que informa de operaciones largas en curso."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OperationBar")
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self.title = ElidedLabel("")
        self.title.setObjectName("SectionTitle")
        layout.addWidget(self.title)

        self.message = ElidedLabel("")
        self.message.setObjectName("Hint")
        layout.addWidget(self.message, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(160)
        self.progress.setFixedHeight(10)
        layout.addWidget(self.progress)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self.cancel_button)

    def start(self, title: str, *, cancellable: bool = False, determinate: bool = False) -> None:
        self.title.setText(title)
        self.message.setText("")
        self.progress.setRange(0, 100 if determinate else 0)
        self.progress.setValue(0)
        self.cancel_button.setVisible(cancellable)
        self.setVisible(True)

    def set_message(self, text: str) -> None:
        self.message.setText(text)

    def set_progress(self, percent: int) -> None:
        self.progress.setValue(percent)

    def finish(self) -> None:
        self.setVisible(False)
        self.message.setText("")
        self.title.setText("")


#: Lado (en pixeles) del icono que acompana a un titulo de seccion.
_SECTION_ICON = 18
#: Lado (en pixeles) del icono de una etiqueta de resumen (`Chip`).
_CHIP_ICON = 14


class HelpDialog(QDialog):
    """Explicacion larga de una seccion: para que sirve y que hay que hacer.

    Es el destino del boton «?»: en vez de llenar la pantalla de parrafos, la
    explicacion vive aqui y se abre solo cuando alguien la pide.
    """

    def __init__(
        self,
        title: str,
        text: str,
        *,
        pixmap: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        if pixmap is not None and not pixmap.isNull():
            imagen = QLabel()
            imagen.setPixmap(
                pixmap.scaled(
                    _SECTION_ICON * 2,
                    _SECTION_ICON * 2,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            head.addWidget(imagen, 0, Qt.AlignmentFlag.AlignTop)
        self.title_label = WrappingLabel(title)
        self.title_label.setObjectName("HelpTitle")
        head.addWidget(self.title_label, 1)
        layout.addLayout(head)

        self.body = WrappingLabel(text)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(self.body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.setText("Entendido")
            close.setDefault(True)
        layout.addWidget(buttons)


class HelpButton(QToolButton):
    """Boton redondo «?» que explica lo que tiene al lado.

    Se oculta solo cuando no hay nada que explicar, asi que quien lo coloca
    puede pasarlo con la misma comodidad con texto que sin el.
    """

    def __init__(self, title: str = "", text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HelpButton")
        self.setText("?")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self._titulo = title
        self._texto = text
        self._pixmap: QPixmap | None = None
        self.clicked.connect(self.mostrar)
        self._actualizar()

    def set_help(self, title: str, text: str, *, pixmap: QPixmap | None = None) -> None:
        """Cambia la explicacion (por ejemplo, al abrir otro servidor)."""
        self._titulo = title
        self._texto = text
        self._pixmap = pixmap
        self._actualizar()

    def _actualizar(self) -> None:
        self.setVisible(bool(self._texto))
        self.setToolTip(f"Que es esto: {self._titulo}" if self._titulo else "Que es esto y para que sirve")

    def mostrar(self) -> None:
        """Abre la explicacion (las pruebas la interceptan para no bloquearse)."""
        if not self._texto:
            return
        HelpDialog(self._titulo, self._texto, pixmap=self._pixmap, parent=self.window()).exec()


class SectionCard(QFrame):
    """Recuadro con icono, titulo, boton «?» y un cuerpo donde va el contenido.

    Sustituye a las cajas de grupo de Qt en las pestanas con mas contenido: el
    titulo lleva el mismo icono que el resto de la aplicacion y la explicacion
    queda a un clic, sin ocupar sitio.
    """

    def __init__(
        self,
        title: str,
        *,
        pixmap: QPixmap | None = None,
        help_title: str = "",
        help_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SectionCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("SectionIcon")
        if pixmap is not None and not pixmap.isNull():
            self.icon_label.setPixmap(
                pixmap.scaled(
                    _SECTION_ICON,
                    _SECTION_ICON,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.icon_label.setVisible(False)
        head.addWidget(self.icon_label)

        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("SectionTitle")
        # El titulo se queda con todo el sitio libre: un ``addStretch`` extra
        # le daba solo la mitad y recortaba titulos que si cabian (por ejemplo
        # «Como se ve en Minecraft» en una ventana de 480 px).
        head.addWidget(self.title_label, 1)
        self.help_button = HelpButton(help_title or title, help_text, self)
        self.help_button.set_help(help_title or title, help_text, pixmap=pixmap)
        head.addWidget(self.help_button)
        outer.addLayout(head)

        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        outer.addLayout(self._body)

    def body(self) -> QVBoxLayout:
        """Disposicion vertical donde se anade el contenido de la seccion."""
        return self._body

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._body.addWidget(widget, stretch)
        return widget

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)


class Chip(QFrame):
    """Etiqueta con icono y texto que resume un dato de un vistazo.

    Se usa para los contadores de jugadores (conectados, lista blanca,
    operadores...) y para explicar los colores de la consola.
    """

    def __init__(
        self,
        text: str = "",
        *,
        pixmap: QPixmap | None = None,
        tone: str = "",
        tooltip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Chip")
        fila = QHBoxLayout(self)
        fila.setContentsMargins(9, 3, 11, 3)
        fila.setSpacing(6)

        self.icon_label = QLabel()
        self.icon_label.setVisible(False)
        fila.addWidget(self.icon_label)

        self.text_label = QLabel(text)
        self.text_label.setObjectName("ChipText")
        fila.addWidget(self.text_label)

        if tone:
            self.set_tone(tone)
        if pixmap is not None:
            self.set_pixmap(pixmap)
        if tooltip:
            self.setToolTip(tooltip)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def text(self) -> str:  # noqa: A003 - mismo nombre que Qt
        return self.text_label.text()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self.icon_label.setVisible(False)
            return
        self.icon_label.setPixmap(
            pixmap.scaled(
                _CHIP_ICON,
                _CHIP_ICON,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.icon_label.setVisible(True)

    def set_tone(self, tone: str) -> None:
        """Cambia el color del chip («ok», «warn», «bad», «info» o vacio)."""
        self.setProperty("tone", tone)
        estilo = self.style()
        estilo.unpolish(self)
        estilo.polish(self)


class PaginaDesplazable(QScrollArea):
    """Panel con barra vertical cuando el contenido no cabe a lo alto.

    Con el mosaico automatico la ventana puede quedarse con menos alto del que
    necesita una pestana (la de «Mods» es la mas larga). Si no hay barra, Qt
    comprime los paneles por debajo de su tamano minimo y los botones de una
    fila se dibujan encima del texto siguiente. Lo mismo pasa en el selector de
    contenido, donde el catalogo crece al enseñar todas las versiones.

    El ancho lo manda siempre el contenedor (como si no hubiera area): los
    paneles ya saben envolver sus barras y recortar sus textos con puntos
    suspensivos. El alto es el minimo que pide el panel a ese ancho (contando
    las barras ya envueltas) o el del contenedor si sobra sitio. El diseno se
    activa a mano para que funcione tambien cuando la ventana esta oculta (en
    las pruebas).
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
