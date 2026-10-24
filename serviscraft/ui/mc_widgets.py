"""Piezas visuales con sabor a Minecraft para las pestanas de contenido.

Reunen lo que ya usa «Propiedades» (degradado con textura de bloques, tarjetas
de piedra con una franja de color y cabecera con boton de ayuda) para que las
demas pestanas se vean como parte del mismo taller y no como formularios de Qt.

Todo se pinta con ``QPainter``: no hay imagenes externas ni emojis.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .common import ElidedLabel, HelpButton, SectionCard, WrappingLabel

#: Colores de cada acento: (claro, oscuro, franja inferior, brillo de la franja).
_HERO_COLORS: dict[str, tuple[str, str, str, str]] = {
    "green": ("#3FA34D", "#2E7D3A", "#8a5a2b", "#6cbb3c"),
    "gold": ("#C79A3A", "#9A7422", "#6b4b14", "#f2c14e"),
    "blue": ("#3C8FBF", "#2C739B", "#3b4a57", "#8fc6e6"),
    "brown": ("#A8703F", "#8A5A2B", "#5a3a1c", "#c99b62"),
}

#: Color de la franja lateral de una tarjeta.
_CARD_ACCENTS: dict[str, str] = {
    "green": "#3FA34D",
    "gold": "#C79A3A",
    "blue": "#3C8FBF",
    "brown": "#A8703F",
}


class TexturedPage(QWidget):
    """Fondo con un damero muy suave, como la piedra de Minecraft."""

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        color = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        color.setAlpha(7)
        paso = 20
        for y in range(0, self.height(), paso):
            for x in range(0, self.width(), paso):
                if ((x // paso) + (y // paso)) % 2 == 0:
                    painter.fillRect(x, y, paso, paso, color)
        painter.end()


class MinecraftHero(QFrame):
    """Cabecera de bloque: degradado, textura, franja inferior y ayuda «?»."""

    _LADO_TEXTURA = 14

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        pixmap: QPixmap | None = None,
        accent: str = "green",
        help_title: str = "",
        help_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MinecraftHero")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(80)
        self._accent = accent if accent in _HERO_COLORS else "green"

        fila = QHBoxLayout(self)
        fila.setContentsMargins(16, 12, 14, 14)
        fila.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("MinecraftHeroIcon")
        if pixmap is not None and not pixmap.isNull():
            self.icon_label.setPixmap(
                pixmap.scaled(
                    40,
                    40,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.icon_label.setFixedSize(48, 48)
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Marco claro tipo ranura de inventario: los iconos oscuros (mod,
            # pluguin) se leen igual sobre el verde que sobre el oro.
            self.icon_label.setStyleSheet(
                "background: rgba(247, 240, 222, 0.92);"
                "border: 2px solid rgba(30, 22, 8, 0.62);"
                "border-radius: 3px;"
            )
        else:
            self.icon_label.setVisible(False)
        fila.addWidget(self.icon_label)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.title = ElidedLabel(title)
        self.title.setObjectName("MinecraftHeroTitle")
        # Algunos estilos nativos (Breeze) ignoran el color de la hoja de
        # estilos en etiquetas dentro de un QFrame; se fija tambien aqui.
        self.title.setStyleSheet(
            "color: #ffffff; font-size: 15pt; font-weight: 800; letter-spacing: 1px;"
        )
        textos.addWidget(self.title)

        self.subtitle = WrappingLabel(subtitle)
        self.subtitle.setObjectName("MinecraftHeroSubtitle")
        self.subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.88); font-size: 9.5pt;")
        self.subtitle.setVisible(bool(subtitle))
        textos.addWidget(self.subtitle)
        fila.addLayout(textos, 1)

        self.help = HelpButton(help_title, help_text, self)
        self.help.setObjectName("MinecraftHeroHelp")
        fila.addWidget(self.help, 0, Qt.AlignmentFlag.AlignTop)

    def set_title(self, title: str) -> None:
        self.title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        marco = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        camino = QPainterPath()
        camino.addRoundedRect(marco, 3.0, 3.0)

        claro, oscuro, franja, brillo = _HERO_COLORS[self._accent]
        degradado = QLinearGradient(marco.topLeft(), marco.bottomRight())
        degradado.setColorAt(0.0, QColor(claro))
        degradado.setColorAt(1.0, QColor(oscuro))
        painter.fillPath(camino, degradado)

        painter.save()
        painter.setClipPath(camino)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        lado = self._LADO_TEXTURA
        for y in range(0, self.height(), lado):
            for x in range(0, self.width(), lado):
                indice = (x // lado) * 5 + (y // lado) * 3
                if indice % 9 == 0:
                    painter.fillRect(x, y, lado, lado, QColor(255, 255, 255, 16))
                elif indice % 13 == 0:
                    painter.fillRect(x, y, lado, lado, QColor(0, 0, 0, 16))

        # Franja inferior: cesped, oro, piedra o madera segun el acento. Es el
        # detalle que convierte una cabecera plana en un bloque del juego.
        alto = 6
        suelo = int(marco.bottom()) - alto
        painter.fillRect(
            int(marco.left()), suelo, int(marco.width()) + 1, alto, QColor(franja)
        )
        for x in range(int(marco.left()), int(marco.right()) + 1, 12):
            painter.fillRect(
                x,
                suelo,
                min(12, int(marco.right()) - x + 1),
                2,
                QColor(brillo),
            )
        painter.restore()

        painter.setPen(QPen(QColor(oscuro).darker(150), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(camino)
        painter.end()


class IconSlot(QLabel):
    """Icono dentro de una ranura de inventario con relieve de piedra.

    Es el detalle que mas acerca la interfaz al juego: cada dato importante
    lleva su objeto (un lingote para la memoria, una brújula para la direccion,
    un pico para el tipo de servidor) dentro de una ranura de 9 x 9.
    """

    def __init__(
        self,
        pixmap: QPixmap | None = None,
        *,
        size: int = 36,
        icon_size: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MinecraftSlot")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pixmap = QPixmap()
        self._icon_size = icon_size or max(16, size - 12)
        self.set_pixmap(pixmap)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is not None and not pixmap.isNull():
            self._pixmap = pixmap.scaled(
                self._icon_size,
                self._icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            self._pixmap = QPixmap()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if not self.isEnabled():
            painter.setOpacity(0.55)
        rect = self.rect().adjusted(0, 0, -1, -1)
        base = self.palette().color(QPalette.ColorRole.Base).darker(112)
        if base.lightness() > 170:
            base = base.darker(108)
        painter.fillRect(rect, base)

        # Bisel de dos pixeles: luz arriba/izquierda y sombra abajo/derecha.
        claro = base.lighter(132)
        oscuro = base.darker(142)
        painter.fillRect(rect.left() + 1, rect.top() + 1, rect.width() - 2, 2, claro)
        painter.fillRect(rect.left() + 1, rect.top() + 1, 2, rect.height() - 2, claro)
        painter.fillRect(rect.left() + 1, rect.bottom() - 2, rect.width() - 2, 2, oscuro)
        painter.fillRect(rect.right() - 2, rect.top() + 1, 2, rect.height() - 2, oscuro)
        painter.setPen(QPen(oscuro.darker(130), 1.0))
        painter.drawRect(rect)

        if not self._pixmap.isNull():
            x = rect.center().x() - self._pixmap.width() // 2
            y = rect.center().y() - self._pixmap.height() // 2
            painter.drawPixmap(x, y, self._pixmap)
        painter.end()


class EmptySlot(QFrame):
    """Aviso amable dentro de una tarjeta, con un objeto y dos lineas.

    Sustituye a la tabla vacia: una tabla sin filas parece un error de carga;
    una ranura con un icono y una frase explica que hacer a continuacion.
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
        self.setObjectName("MinecraftEmpty")
        fila = QHBoxLayout(self)
        fila.setContentsMargins(12, 10, 12, 10)
        fila.setSpacing(12)

        self.icon = IconSlot(pixmap, size=46, icon_size=32, parent=self)
        fila.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("MinecraftEmptyTitle")
        textos.addWidget(self.title)
        self.text = WrappingLabel(text)
        self.text.setObjectName("MinecraftEmptyText")
        textos.addWidget(self.text)
        fila.addLayout(textos, 1)

    def set_texts(self, title: str, text: str) -> None:
        self.title.setText(title)
        self.text.setText(text)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self.icon.set_pixmap(pixmap)


class CenteredEmpty(QWidget):
    """Pagina vacia con una ranura grande y una frase que orienta.

    Se usa cuando no hay ningun servidor seleccionado. En vez de una linea de
    texto perdida en mitad del panel, hay un objeto, un titulo y una pista.
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
        caja = QVBoxLayout(self)
        caja.setContentsMargins(12, 24, 12, 24)
        caja.setSpacing(10)
        caja.addStretch(1)

        self.icon = IconSlot(pixmap, size=64, icon_size=44, parent=self)
        caja.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)

        self.title = QLabel(title)
        self.title.setObjectName("MinecraftEmptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caja.addWidget(self.title)

        self.text = WrappingLabel(text)
        self.text.setObjectName("MinecraftEmptyText")
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setMaximumWidth(480)
        caja.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)
        caja.addStretch(1)

    def set_texts(self, title: str, text: str) -> None:
        self.title.setText(title)
        self.text.setText(text)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self.icon.set_pixmap(pixmap)


class DropZone(QFrame):
    """Zona grande para arrastrar ficheros, con brillo al pasar por encima.

    Ademas de arrastrar, se puede pulsar: abre el selector de siempre. Asi el
    gesto mas comodo (soltar un ``.jar`` descargado) y el de toda la vida
    conviven sin esconderse en un menu.
    """

    files_dropped = Signal(list)
    clicked = Signal()

    _SUFFIXES = frozenset({".jar", ".zip", ".mrpack"})

    def __init__(
        self,
        title: str,
        hint: str,
        *,
        pixmap: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MinecraftDropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("dragActive", False)

        fila = QHBoxLayout(self)
        fila.setContentsMargins(12, 8, 12, 8)
        fila.setSpacing(12)

        self.icon = IconSlot(pixmap, size=42, icon_size=28, parent=self)
        fila.addWidget(self.icon)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("MinecraftDropTitle")
        textos.addWidget(self.title)
        self.hint = WrappingLabel(hint)
        self.hint.setObjectName("MinecraftDropHint")
        textos.addWidget(self.hint)
        fila.addLayout(textos, 1)

    def set_texts(self, title: str, hint: str) -> None:
        self.title.setText(title)
        self.hint.setText(hint)

    def _paths(self, mime) -> list[str]:
        if not mime.hasUrls():
            return []
        rutas: list[str] = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            ruta = Path(url.toLocalFile())
            if ruta.is_file() and ruta.suffix.lower() in self._SUFFIXES:
                rutas.append(str(ruta))
        return rutas

    def _set_active(self, active: bool) -> None:
        if bool(self.property("dragActive")) == active:
            return
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if self.isEnabled() and self._paths(event.mimeData()):
            event.acceptProposedAction()
            self._set_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if self.isEnabled() and self._paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - API de Qt
        self._set_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - API de Qt
        self._set_active(False)
        rutas = self._paths(event.mimeData())
        if not rutas or not self.isEnabled():
            event.ignore()
            return
        event.acceptProposedAction()
        self.files_dropped.emit(rutas)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if (
            self.isEnabled()
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class AccentCard(SectionCard):
    """Tarjeta con textura de piedra y una franja del color de la seccion."""

    def __init__(
        self,
        title: str,
        *,
        pixmap: QPixmap | None = None,
        help_title: str = "",
        help_text: str = "",
        accent: str = "green",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            title,
            pixmap=pixmap,
            help_title=help_title,
            help_text=help_text,
            parent=parent,
        )
        self.setProperty("accent", accent)
        self._accent = QColor(_CARD_ACCENTS.get(accent, _CARD_ACCENTS["green"]))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setClipRect(self.rect().adjusted(2, 2, -2, -2))

        texto = self.palette().color(QPalette.ColorRole.WindowText)
        claro = QColor(texto)
        claro.setAlpha(9)
        oscuro = QColor(0, 0, 0)
        oscuro.setAlpha(8)
        paso = 12
        for y in range(2, self.height(), paso):
            for x in range(2, self.width(), paso):
                indice = (x // paso) * 3 + (y // paso) * 5
                if indice % 11 == 0:
                    painter.fillRect(x, y, paso, paso, claro)
                elif indice % 17 == 0:
                    painter.fillRect(x, y, paso, paso, oscuro)

        franja = QColor(self._accent)
        franja.setAlpha(150)
        painter.fillRect(2, 2, 4, self.height() - 4, franja)
        painter.end()
