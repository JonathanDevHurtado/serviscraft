"""Vista previa de la entrada del servidor en la lista de Minecraft.

La lista de servidores del juego ensena, por cada servidor, una entrada de 36
pixeles con: el **icono** a la izquierda (32x32), el **nombre** en blanco y, en
dos lineas, la **descripcion** (el ``motd``) con sus colores. Dibujar esa misma
entrada aqui permite ver como quedara antes de entrar, sin abrir Minecraft.

Es una pintura a mano con ``QPainter`` (no un estilo de Qt) porque imita la
interfaz del juego: fondo oscuro, tipografia pequena y las barras de conexion a
la derecha.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core import appearance
from .mc_icons import pixmap_de_bytes

#: Color del nombre del servidor en la lista del juego.
NAME_COLOR = "#ffffff"
#: Color del texto de la descripcion cuando no se indica ninguno.
DEFAULT_TEXT_COLOR = "#aaaaaa"
#: Colores de las barras de conexion (de mejor a peor).
PING_COLORS = ("#00ff00", "#55ff55", "#ffff55", "#ffaa00", "#ff5555")
#: Color de las barras apagadas.
PING_OFF = "#2b2b2b"


def icon_pixmap(data: bytes, size: int) -> QPixmap:
    """Icono del servidor listo para pintar (vacio si los datos no son una imagen)."""
    if not data:
        return QPixmap()
    return pixmap_de_bytes(data, size)


class McListEntry(QWidget):
    """Entrada de la lista de servidores, tal y como la pinta Minecraft."""

    def __init__(self, *, scale: int = 2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("McListEntry")
        self._scale = max(1, int(scale))
        self._name = ""
        self._motd = ""
        self._icon = QPixmap()
        self._ping = 5
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.entry_height())

    # ================================================================ medidas
    def _baselines(self) -> list[int]:
        """Altura de la linea base de cada linea (nombre y dos de descripcion).

        Se calcula en un solo sitio para que el alto del widget y lo que se pinta
        no puedan discrepar: cuando discrepan, la ultima linea se corta.
        """
        nombre = QFontMetrics(self._fuente(bold=True, puntos=9 * self._scale))
        motd = QFontMetrics(self._fuente(puntos=8 * self._scale))
        primera = self._pad() + nombre.ascent() + 1
        paso = motd.height() + 1
        return [primera, primera + paso, primera + 2 * paso]

    def entry_height(self) -> int:
        """Alto de la entrada: el nombre y las dos lineas de la descripcion.

        Se mide con la fuente real en vez de usar los 36 pixeles fijos del
        juego: con la fuente del sistema las tres lineas necesitan algun pixel
        mas y, si no, la ultima se corta por abajo.
        """
        motd = QFontMetrics(self._fuente(puntos=8 * self._scale))
        return self._baselines()[-1] + (motd.height() - motd.ascent()) + self._pad()

    def _pad(self) -> int:
        return 2 * self._scale

    def _icon_size(self) -> int:
        return 32 * self._scale

    def _text_x(self) -> int:
        return self._pad() + self._icon_size() + 4 * self._scale

    # =================================================================== datos
    def set_data(
        self,
        name: str,
        motd: str,
        icon: QPixmap | None = None,
        *,
        ping: int | None = None,
    ) -> None:
        self._name = str(name or "")
        self._motd = str(motd or "")
        if icon is not None:
            self._icon = icon
        if ping is not None:
            self._ping = max(0, min(5, int(ping)))
        self.update()

    def set_icon(self, icon: QPixmap | None) -> None:
        self._icon = icon if icon is not None else QPixmap()
        self.update()

    # =================================================================== pintura
    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        borde = 1
        zona = QRectF(
            borde / 2.0, borde / 2.0, self.width() - borde, self.height() - borde
        )
        painter.setPen(QPen(QColor("#000000"), borde))
        painter.setBrush(QColor(0, 0, 0, 205))
        painter.drawRect(zona)

        self._pintar_icono(painter)
        self._pintar_textos(painter)
        self._pintar_ping(painter)
        painter.end()

    def _pintar_icono(self, painter: QPainter) -> None:
        pad = self._pad()
        lado = self._icon_size()
        marco = QRectF(pad, pad, lado, lado)
        if self._icon.isNull():
            # Sin icono propio: la piedra que ensena el juego por defecto.
            painter.setPen(QPen(QColor("#3b3b41"), 1))
            painter.setBrush(QColor("#8b8b90"))
            painter.drawRect(marco)
            painter.setPen(QPen(QColor("#5a5a60"), max(1, self._scale)))
            paso = max(2, lado // 8)
            for indice in range(0, lado, paso * 2):
                painter.drawLine(
                    int(pad + indice), int(pad), int(pad + indice), int(pad + lado)
                )
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(marco.toRect(), self._icon)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(marco)

    def _pintar_textos(self, painter: QPainter) -> None:
        x = self._text_x()
        disponible = max(10, self.width() - x - 7 * self._scale)

        lineas_base = self._baselines()

        # 1. Nombre del servidor, en blanco y en negrita (como en el juego).
        fuente_nombre = self._fuente(bold=True, puntos=9 * self._scale)
        painter.setFont(fuente_nombre)
        painter.setPen(QColor(NAME_COLOR))
        metricas_nombre = QFontMetrics(fuente_nombre)
        painter.drawText(
            x,
            lineas_base[0],
            metricas_nombre.elidedText(
                self._name or "Servidor", Qt.TextElideMode.ElideRight, disponible
            ),
        )

        # 2. Descripcion: hasta dos lineas, cada una con sus colores.
        fuente = self._fuente(puntos=8 * self._scale)
        for indice, linea in enumerate(
            appearance.parse(self._motd)[: appearance.MAX_LINES]
        ):
            self._pintar_linea(
                painter, fuente, linea, x, lineas_base[indice + 1], disponible
            )

    def _pintar_linea(
        self, painter: QPainter, base: QFont, tramos, x: int, y: int, disponible: int
    ) -> None:
        """Pinta una linea de la descripcion respetando el color de cada tramo."""
        if not tramos:
            return
        cursor = float(x)
        limite = float(x + disponible)
        for tramo in tramos:
            fuente = QFont(base)
            fuente.setBold(tramo.bold)
            fuente.setItalic(tramo.italic)
            fuente.setUnderline(tramo.underline)
            fuente.setStrikeOut(tramo.strike)
            painter.setFont(fuente)
            painter.setPen(QColor(tramo.color or DEFAULT_TEXT_COLOR))
            metricas = QFontMetrics(fuente)
            for caracter in tramo.shown:
                ancho = metricas.horizontalAdvance(caracter)
                if cursor + ancho > limite:
                    # El juego corta lo que no cabe: la vista previa tambien.
                    return
                painter.drawText(int(cursor), y, caracter)
                cursor += ancho

    def _pintar_ping(self, painter: QPainter) -> None:
        """Barras de conexion de la derecha (aquí, red local: todas verdes)."""
        lado = max(1, self._scale)
        ancho = 2 * self._scale
        hueco = 1 * self._scale
        total = 5
        base_y = self.height() / 2.0 + 6 * self._scale
        x_final = self.width() - self._pad() - 2 * self._scale
        # En el juego todas las barras encendidas son del mismo color: el que
        # resume la conexion.
        # Cinco barras = conexion perfecta (verde): el indice va al reves que la
        # calidad, de ahi la resta.
        encendido = PING_COLORS[
            max(0, min(len(PING_COLORS) - 1, len(PING_COLORS) - self._ping))
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        for indice in range(total):
            alto = (indice + 2) * 3 * self._scale
            color = encendido if indice < self._ping else PING_OFF
            painter.setBrush(QColor(color))
            x = x_final - (total - 1 - indice) * (ancho + hueco) - ancho
            painter.drawRect(QRectF(x, base_y - alto, ancho, alto))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _fuente(self, *, bold: bool = False, puntos: int) -> QFont:
        fuente = QFont(self.font())
        fuente.setPixelSize(max(6, puntos))
        fuente.setBold(bold)
        return fuente


__all__ = ["McListEntry", "icon_pixmap"]
