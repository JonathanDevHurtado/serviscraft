"""Iconos dibujados con Qt para distinguir Java y Bedrock, mods y pluguins.

No se descarga ningun fichero: los bloques (cesped para Java, piedra para
Bedrock) y los simbolos de mod y pluguin se pintan aqui mismo, de modo que la
aplicacion funciona igual sin conexion y sin depender de iconos externos.

Estos son los iconos «de categoria». El icono propio de cada proyecto de
Modrinth (el que ve el jugador en Prism Launcher) se guarda en ``core.icons`` y
lo pinta :func:`pixmap_de_bytes`.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

#: Tamano por defecto de los iconos, en pixeles.
SIZE = 16

#: Colores del bloque de cesped (Minecraft Java).
GRASS_TOP = "#6cbb3c"
GRASS_LEFT = "#8a5a2b"
GRASS_RIGHT = "#6f4620"
GRASS_BORDER = "#2f5c19"

#: Colores del bloque de piedra (Minecraft Bedrock).
STONE_TOP = "#a3a3a8"
STONE_LEFT = "#86868c"
STONE_RIGHT = "#616167"
STONE_BORDER = "#3b3b41"

#: Colores de los simbolos de mod y pluguin.
MOD_COLOR = "#d99a2b"
MOD_BORDER = "#8a5c0d"
PLUGIN_COLOR = "#2f9fd0"
PLUGIN_BORDER = "#1a6a8c"

#: Simbolos que dibuja la insignia de plataforma.
_ICONO_JAVA = "java"
_ICONO_BEDROCK = "bedrock"


def _lienzo(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _pincel(painter: QPainter, color: str, *, grosor: float = 1.0) -> None:
    painter.setBrush(QColor(color))
    lapiz = painter.pen()
    lapiz.setWidthF(grosor)
    painter.setPen(lapiz)


def _lapiz(painter: QPainter, color: str, *, grosor: float = 1.0) -> None:
    """Prepara el lapiz (color y grosor) y deja el relleno vacio.

    ``_pincel`` solo cambia el **relleno**: sirve para pintar caras, pero una
    linea dibujada despues de ``setPen(Qt.PenStyle.NoPen)`` no se veria. Las
    figuras con contorno necesitan las dos cosas por separado.
    """
    lapiz = QPen(QColor(color))
    lapiz.setWidthF(grosor)
    lapiz.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    lapiz.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(lapiz)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _relleno(painter: QPainter, color: str) -> None:
    """Deja el pincel relleno de ese color y sin borde (manchas y bloques)."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))


def _bloque(
    size: int,
    *,
    superior: str,
    izquierda: str,
    derecha: str,
    borde: str,
    motas: str = "",
) -> QPixmap:
    """Pinta un cubo en perspectiva con las tres caras de un color."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    extremo = float(size - 1)
    cuarto = extremo / 4.0
    mitad = extremo / 2.0

    caras = (
        (
            superior,
            [
                QPointF(0, cuarto),
                QPointF(mitad, 0),
                QPointF(extremo, cuarto),
                QPointF(mitad, 2 * cuarto),
            ],
        ),
        (
            izquierda,
            [
                QPointF(0, cuarto),
                QPointF(mitad, 2 * cuarto),
                QPointF(mitad, extremo),
                QPointF(0, extremo - cuarto),
            ],
        ),
        (
            derecha,
            [
                QPointF(extremo, cuarto),
                QPointF(mitad, 2 * cuarto),
                QPointF(mitad, extremo),
                QPointF(extremo, extremo - cuarto),
            ],
        ),
    )
    for color, puntos in caras:
        _pincel(painter, color)
        painter.drawPolygon(QPolygonF(puntos))

    if motas and size >= 12:
        # Motas fijas (nunca al azar) para que el dibujo sea siempre igual.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(motas))
        lado = max(1.0, extremo / 8.0)
        for x_ratio, y_ratio in ((0.32, 0.18), (0.62, 0.28), (0.22, 0.62), (0.7, 0.7), (0.46, 0.86)):
            painter.drawRect(
                QRectF(x_ratio * extremo, y_ratio * extremo, lado, lado)
            )

    _pincel(painter, borde, grosor=max(1.0, size / 16.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0, cuarto),
                QPointF(mitad, 0),
                QPointF(extremo, cuarto),
                QPointF(extremo, extremo - cuarto),
                QPointF(mitad, extremo),
                QPointF(0, extremo - cuarto),
            ]
        )
    )
    painter.drawLine(QPointF(mitad, 2 * cuarto), QPointF(mitad, extremo))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def bloque_java(size: int = SIZE) -> QPixmap:
    """Bloque de cesped: Minecraft Java (PC, Mac y Linux)."""
    return _bloque(
        size,
        superior=GRASS_TOP,
        izquierda=GRASS_LEFT,
        derecha=GRASS_RIGHT,
        borde=GRASS_BORDER,
    )


@lru_cache(maxsize=32)
def bloque_bedrock(size: int = SIZE) -> QPixmap:
    """Bloque de piedra: Minecraft Bedrock (movil, tablet y consola)."""
    return _bloque(
        size,
        superior=STONE_TOP,
        izquierda=STONE_LEFT,
        derecha=STONE_RIGHT,
        borde=STONE_BORDER,
        motas="#4a4a50",
    )


@lru_cache(maxsize=32)
def icono_mod(size: int = SIZE) -> QPixmap:
    """Pieza de puzle: contenido de la carpeta ``mods``."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # Pieza de puzle: cuerpo cuadrado, saliente arriba y hueco a la derecha.
    camino = QPainterPath()
    camino.moveTo(0.18 * s, 0.22 * s)
    camino.lineTo(0.40 * s, 0.22 * s)
    camino.cubicTo(0.42 * s, 0.06 * s, 0.58 * s, 0.06 * s, 0.60 * s, 0.22 * s)
    camino.lineTo(0.82 * s, 0.22 * s)
    camino.lineTo(0.82 * s, 0.40 * s)
    camino.cubicTo(0.66 * s, 0.42 * s, 0.66 * s, 0.58 * s, 0.82 * s, 0.60 * s)
    camino.lineTo(0.82 * s, 0.82 * s)
    camino.lineTo(0.18 * s, 0.82 * s)
    camino.closeSubpath()

    painter.setBrush(QColor(MOD_COLOR))
    _pincel(painter, MOD_BORDER, grosor=max(1.0, size / 14.0))
    painter.drawPath(camino)
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_plugin(size: int = SIZE) -> QPixmap:
    """Enchufe: contenido de la carpeta ``plugins``."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grosor = max(1.0, size / 14.0)

    # Patillas arriba (dos), cuerpo y cable abajo: asi se reconoce un enchufe.
    _pincel(painter, PLUGIN_BORDER, grosor=grosor * 1.4)
    painter.drawLine(QPointF(0.38 * s, 0.10 * s), QPointF(0.38 * s, 0.34 * s))
    painter.drawLine(QPointF(0.62 * s, 0.10 * s), QPointF(0.62 * s, 0.34 * s))

    cuerpo = QRectF(0.24 * s, 0.32 * s, 0.52 * s, 0.42 * s)
    painter.setBrush(QColor(PLUGIN_COLOR))
    painter.drawRoundedRect(cuerpo, 0.12 * s, 0.12 * s)

    _pincel(painter, PLUGIN_BORDER, grosor=grosor * 1.2)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(0.5 * s, 0.74 * s), QPointF(0.5 * s, 0.92 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_pack(size: int = SIZE) -> QPixmap:
    """Caja de modpack: contenido que viene con el paquete completo."""
    return _bloque(
        size,
        superior="#c9a227",
        izquierda="#a5821c",
        derecha="#7c6014",
        borde="#4f3c0a",
    )


def marcar_desactivado(pixmap: QPixmap) -> QPixmap:
    """Version apagada del icono: velo blanco y barra roja diagonal."""
    if pixmap.isNull():
        return pixmap
    resultado = QPixmap(pixmap)
    painter = QPainter(resultado)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(resultado.width())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 110))
    painter.drawRect(QRectF(0, 0, s, s))
    _pincel(painter, "#c0392b", grosor=max(1.5, s / 9.0))
    painter.drawLine(QPointF(0.18 * s, 0.82 * s), QPointF(0.82 * s, 0.18 * s))
    painter.end()
    return resultado


@lru_cache(maxsize=64)
def pixmap_de_bytes(datos: bytes, size: int = SIZE) -> QPixmap:
    """Convierte los bytes de una imagen (icono de Modrinth) en un ``QPixmap``.

    Si el fichero no es una imagen valida devuelve un pixmap vacio, para que
    quien lo use pueda enseñar el icono generico.
    """
    if not datos:
        return QPixmap()
    pixmap = QPixmap()
    if not pixmap.loadFromData(datos):
        return QPixmap()
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


@lru_cache(maxsize=32)
def icono_jugador(size: int = SIZE) -> QPixmap:
    """Cabeza de jugador: la cara de Steve, como en la lista de jugadores."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    cara = QRectF(0.12 * s, 0.14 * s, 0.76 * s, 0.72 * s)
    grosor = max(1.0, size / 16.0)

    _relleno(painter, "#c98f66")
    painter.drawRect(cara)
    _relleno(painter, "#3b2a1a")
    painter.drawRect(QRectF(cara.x(), cara.y(), cara.width(), cara.height() * 0.26))

    _relleno(painter, "#ffffff")
    painter.drawRect(QRectF(0.28 * s, 0.44 * s, 0.14 * s, 0.12 * s))
    painter.drawRect(QRectF(0.58 * s, 0.44 * s, 0.14 * s, 0.12 * s))
    _relleno(painter, "#2b4a8b")
    painter.drawRect(QRectF(0.32 * s, 0.46 * s, 0.07 * s, 0.09 * s))
    painter.drawRect(QRectF(0.62 * s, 0.46 * s, 0.07 * s, 0.09 * s))

    _lapiz(painter, "#8a5f3f", grosor=grosor)
    painter.drawLine(QPointF(0.36 * s, 0.72 * s), QPointF(0.64 * s, 0.72 * s))

    _lapiz(painter, "#5d3f28", grosor=grosor)
    painter.drawRect(cara)
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_consola(size: int = SIZE) -> QPixmap:
    """Ventanita de terminal con el simbolo «>»: la pestana de consola."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    cuerpo = QRectF(0.06 * s, 0.16 * s, 0.88 * s, 0.68 * s)
    radio = 0.12 * s

    _relleno(painter, "#1e2126")
    painter.drawRoundedRect(cuerpo, radio, radio)
    _relleno(painter, "#3a3f47")
    painter.drawRoundedRect(
        QRectF(cuerpo.x(), cuerpo.y(), cuerpo.width(), cuerpo.height() * 0.22),
        radio,
        radio,
    )

    _lapiz(painter, "#7fd6a2", grosor=max(1.0, size / 9.0))
    painter.drawLine(QPointF(0.2 * s, 0.44 * s), QPointF(0.33 * s, 0.54 * s))
    painter.drawLine(QPointF(0.33 * s, 0.54 * s), QPointF(0.2 * s, 0.64 * s))
    painter.drawLine(QPointF(0.44 * s, 0.64 * s), QPointF(0.72 * s, 0.64 * s))

    _lapiz(painter, "#5a6068", grosor=max(1.0, size / 16.0))
    painter.drawRoundedRect(cuerpo, radio, radio)
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_mundo(size: int = SIZE) -> QPixmap:
    """Planeta: jugar con gente de otros sitios (internet)."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    esfera = QRectF(0.08 * s, 0.08 * s, 0.84 * s, 0.84 * s)

    _relleno(painter, "#2f6fbf")
    painter.drawEllipse(esfera)
    _relleno(painter, "#4fae3a")
    painter.drawEllipse(QRectF(0.22 * s, 0.20 * s, 0.30 * s, 0.22 * s))
    painter.drawEllipse(QRectF(0.50 * s, 0.40 * s, 0.28 * s, 0.32 * s))
    painter.drawEllipse(QRectF(0.18 * s, 0.56 * s, 0.26 * s, 0.20 * s))

    _lapiz(painter, "#1b4a85", grosor=max(1.0, size / 16.0))
    painter.drawEllipse(esfera)
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_escudo(size: int = SIZE) -> QPixmap:
    """Escudo con un visto: cuentas, permisos y seguridad."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    camino = QPainterPath()
    camino.moveTo(0.50 * s, 0.06 * s)
    camino.lineTo(0.90 * s, 0.20 * s)
    camino.lineTo(0.90 * s, 0.52 * s)
    camino.cubicTo(0.90 * s, 0.74 * s, 0.70 * s, 0.90 * s, 0.50 * s, 0.96 * s)
    camino.cubicTo(0.30 * s, 0.90 * s, 0.10 * s, 0.74 * s, 0.10 * s, 0.52 * s)
    camino.lineTo(0.10 * s, 0.20 * s)
    camino.closeSubpath()

    _lapiz(painter, "#24507f", grosor=max(1.0, size / 14.0))
    painter.setBrush(QColor("#4a7fb5"))
    painter.drawPath(camino)

    _lapiz(painter, "#ffffff", grosor=max(1.2, size / 8.0))
    painter.drawLine(QPointF(0.32 * s, 0.50 * s), QPointF(0.45 * s, 0.63 * s))
    painter.drawLine(QPointF(0.45 * s, 0.63 * s), QPointF(0.70 * s, 0.36 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_cuadro(size: int = SIZE) -> QPixmap:
    """Cuadro con un paisaje dentro: el aspecto del servidor (icono y descripcion)."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    _relleno(painter, "#2b6cb0")
    painter.drawRect(QRectF(0.16 * s, 0.18 * s, 0.68 * s, 0.54 * s))
    _relleno(painter, "#6cbb3c")
    painter.drawRect(QRectF(0.16 * s, 0.50 * s, 0.68 * s, 0.22 * s))
    _relleno(painter, "#ffe08a")
    painter.drawEllipse(QRectF(0.60 * s, 0.24 * s, 0.14 * s, 0.14 * s))

    _lapiz(painter, "#7a4a1e", grosor=max(1.0, size / 8.0))
    painter.drawRect(QRectF(0.14 * s, 0.16 * s, 0.72 * s, 0.58 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_mochila(size: int = SIZE) -> QPixmap:
    """Mochila: el inventario de un jugador."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    _lapiz(painter, "#5d3a17", grosor=max(1.2, size / 9.0))
    painter.drawArc(QRectF(0.34 * s, 0.10 * s, 0.32 * s, 0.28 * s), 0, 180 * 16)

    _lapiz(painter, "#6b4520", grosor=max(1.0, size / 14.0))
    painter.setBrush(QColor("#8a5a2b"))
    painter.drawRoundedRect(QRectF(0.20 * s, 0.28 * s, 0.60 * s, 0.60 * s), 0.12 * s, 0.12 * s)
    _relleno(painter, "#a9702f")
    painter.drawRoundedRect(QRectF(0.24 * s, 0.34 * s, 0.52 * s, 0.26 * s), 0.08 * s, 0.08 * s)

    _relleno(painter, "#e0c060")
    painter.drawRect(QRectF(0.44 * s, 0.54 * s, 0.12 * s, 0.10 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=64)
def punto_estado(color: str, size: int = 12) -> QPixmap:
    """Circulo de color que resume el estado (verde encendido, gris parado).

    Va al lado del texto de estado de la consola: se ve de un vistazo sin
    tener que leer la frase entera.
    """
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    _relleno(painter, color)
    painter.drawEllipse(QRectF(0.08 * s, 0.08 * s, 0.84 * s, 0.84 * s))
    painter.end()
    return pixmap


def icono_plataforma(*, size: int = SIZE) -> QIcon:
    """Icono de la ventana/acciones: el bloque de Java."""
    return QIcon(bloque_java(size))


class PlatformBadge(QWidget):
    """Insignia que dice si el servidor es de Java, de Bedrock o de los dos.

    Siempre se ve el bloque de cesped (Java). Si el servidor tambien acepta
    jugadores de movil o consola, aparece al lado el bloque de piedra (Bedrock).
    Con ``with_text=False`` se queda solo en iconos (util en la barra lateral,
    donde hay poco ancho).
    """

    def __init__(
        self,
        size: int = SIZE,
        *,
        with_text: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PlatformBadge")
        self._size = size
        self._with_text = with_text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.java_icon = QLabel()
        self.java_icon.setPixmap(bloque_java(size))
        self.java_icon.setFixedSize(size, size)
        self.java_icon.setToolTip("Minecraft Java: PC, Mac y Linux.")
        layout.addWidget(self.java_icon)
        self.java_text = QLabel("Java")
        self.java_text.setObjectName("PlatformText")
        layout.addWidget(self.java_text)

        self.bedrock_icon = QLabel()
        self.bedrock_icon.setPixmap(bloque_bedrock(size))
        self.bedrock_icon.setFixedSize(size, size)
        self.bedrock_icon.setToolTip(
            "Minecraft Bedrock: movil, tablet y consola (entran con Geyser)."
        )
        layout.addWidget(self.bedrock_icon)
        self.bedrock_text = QLabel("Bedrock")
        self.bedrock_text.setObjectName("PlatformText")
        layout.addWidget(self.bedrock_text)

        self.java_text.setVisible(with_text)
        self.bedrock_text.setVisible(with_text)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_spec(None)

    def set_spec(self, spec) -> None:
        """Actualiza la insignia con la definicion del servidor (o ``None``)."""
        bedrock = bool(spec is not None and getattr(spec, "bedrock_enabled", False))
        self.bedrock_icon.setVisible(bedrock)
        self.bedrock_text.setVisible(bedrock and self._with_text)
        if spec is None:
            self.setToolTip("")
            self.setVisible(False)
            return
        self.setVisible(True)
        if bedrock:
            self.setToolTip(
                "Servidor de Java y Bedrock: entran tanto PC como movil, tablet y consola."
            )
        else:
            self.setToolTip("Servidor de Java: entran PC, Mac y Linux.")


@lru_cache(maxsize=32)
def icono_corona(size: int = SIZE) -> QPixmap:
    """Corona dorada: jugador con permisos de administrador."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grosor = max(1.0, size / 15.0)

    corona = QPolygonF(
        [
            QPointF(0.12 * s, 0.30 * s),
            QPointF(0.32 * s, 0.48 * s),
            QPointF(0.50 * s, 0.20 * s),
            QPointF(0.68 * s, 0.48 * s),
            QPointF(0.88 * s, 0.30 * s),
            QPointF(0.80 * s, 0.76 * s),
            QPointF(0.20 * s, 0.76 * s),
        ]
    )
    _pincel(painter, "#f2c14e", grosor=grosor)
    painter.setBrush(QColor("#f2c14e"))
    painter.drawPolygon(corona)
    _lapiz(painter, "#8a5c0d", grosor=grosor)
    painter.drawPolygon(corona)

    _relleno(painter, "#fff2b0")
    painter.drawEllipse(QRectF(0.44 * s, 0.34 * s, 0.12 * s, 0.12 * s))
    _relleno(painter, "#d94b4b")
    painter.drawEllipse(QRectF(0.22 * s, 0.40 * s, 0.08 * s, 0.08 * s))
    painter.drawEllipse(QRectF(0.70 * s, 0.40 * s, 0.08 * s, 0.08 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_pase(size: int = SIZE) -> QPixmap:
    """Pase verde con un visto: invitacion para entrar al servidor."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grosor = max(1.0, size / 16.0)

    _lapiz(painter, "#1f6b3a", grosor=grosor)
    painter.setBrush(QColor("#4fbf62"))
    painter.drawRoundedRect(QRectF(0.10 * s, 0.24 * s, 0.80 * s, 0.52 * s), 0.10 * s, 0.10 * s)

    _relleno(painter, "#2e8b45")
    painter.drawRect(QRectF(0.30 * s, 0.24 * s, 0.06 * s, 0.52 * s))

    _lapiz(painter, "#ffffff", grosor=max(1.3, size / 8.5))
    painter.drawLine(QPointF(0.44 * s, 0.51 * s), QPointF(0.53 * s, 0.61 * s))
    painter.drawLine(QPointF(0.53 * s, 0.61 * s), QPointF(0.72 * s, 0.40 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_candado(size: int = SIZE) -> QPixmap:
    """Candado: un jugador al que se le ha bloqueado la entrada."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grosor = max(1.3, size / 11.0)

    _lapiz(painter, "#7d2a24", grosor=grosor)
    painter.drawArc(QRectF(0.30 * s, 0.12 * s, 0.40 * s, 0.42 * s), 0, 180 * 16)
    painter.drawLine(QPointF(0.30 * s, 0.32 * s), QPointF(0.30 * s, 0.44 * s))
    painter.drawLine(QPointF(0.70 * s, 0.32 * s), QPointF(0.70 * s, 0.44 * s))

    _lapiz(painter, "#7d2a24", grosor=grosor)
    painter.setBrush(QColor("#d95a4e"))
    painter.drawRoundedRect(QRectF(0.18 * s, 0.42 * s, 0.64 * s, 0.46 * s), 0.08 * s, 0.08 * s)

    _relleno(painter, "#78211c")
    painter.drawEllipse(QRectF(0.45 * s, 0.56 * s, 0.10 * s, 0.10 * s))
    painter.drawRect(QRectF(0.475 * s, 0.64 * s, 0.05 * s, 0.10 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_salida(size: int = SIZE) -> QPixmap:
    """Puerta con una flecha: sacar a un jugador del juego ahora mismo."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grosor = max(1.0, size / 13.0)

    _lapiz(painter, "#7a4a1e", grosor=grosor)
    painter.setBrush(QColor("#b97a3e"))
    painter.drawRoundedRect(QRectF(0.12 * s, 0.10 * s, 0.38 * s, 0.80 * s), 0.04 * s, 0.04 * s)
    _relleno(painter, "#f2c14e")
    painter.drawEllipse(QRectF(0.38 * s, 0.48 * s, 0.07 * s, 0.07 * s))

    _lapiz(painter, "#1f6f3a", grosor=max(1.4, size / 7.5))
    painter.drawLine(QPointF(0.55 * s, 0.50 * s), QPointF(0.88 * s, 0.50 * s))
    painter.drawLine(QPointF(0.88 * s, 0.50 * s), QPointF(0.76 * s, 0.36 * s))
    painter.drawLine(QPointF(0.88 * s, 0.50 * s), QPointF(0.76 * s, 0.64 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_lista(size: int = SIZE) -> QPixmap:
    """Portapapeles con nombres: administrar invitados y bloqueados."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grosor = max(1.0, size / 16.0)

    _lapiz(painter, "#5b3a16", grosor=grosor)
    painter.setBrush(QColor("#e8c98a"))
    painter.drawRoundedRect(QRectF(0.17 * s, 0.14 * s, 0.66 * s, 0.76 * s), 0.08 * s, 0.08 * s)
    _relleno(painter, "#8a5a2b")
    painter.drawRoundedRect(QRectF(0.34 * s, 0.08 * s, 0.32 * s, 0.16 * s), 0.05 * s, 0.05 * s)

    _lapiz(painter, "#7a5527", grosor=max(1.0, size / 14.0))
    for y in (0.40, 0.54, 0.68):
        painter.drawLine(QPointF(0.30 * s, y * s), QPointF(0.68 * s, y * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_si(size: int = SIZE) -> QPixmap:
    """Circulo verde con un visto: una casilla afirmativa de la tabla."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    _relleno(painter, "#2e9b4f")
    painter.drawEllipse(QRectF(0.08 * s, 0.08 * s, 0.84 * s, 0.84 * s))
    _lapiz(painter, "#ffffff", grosor=max(1.2, size / 8.0))
    painter.drawLine(QPointF(0.28 * s, 0.52 * s), QPointF(0.44 * s, 0.68 * s))
    painter.drawLine(QPointF(0.44 * s, 0.68 * s), QPointF(0.72 * s, 0.34 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_no(size: int = SIZE) -> QPixmap:
    """Circulo gris con un guion: una casilla negativa de la tabla."""
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    _relleno(painter, "#7d848c")
    painter.drawEllipse(QRectF(0.08 * s, 0.08 * s, 0.84 * s, 0.84 * s))
    _lapiz(painter, "#ffffff", grosor=max(1.3, size / 7.5))
    painter.drawLine(QPointF(0.30 * s, 0.50 * s), QPointF(0.70 * s, 0.50 * s))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_conectar(size: int = 48) -> QPixmap:
    """Dos bloques juntos (Java y Bedrock): entrar desde cualquier plataforma.

    La cabecera de «Unirse» usa este dibujo en vez de un icono generico del
    escritorio: se reconoce al instante que en esa pestana se conectan tanto
    jugadores de PC como de movil o consola.
    """
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    lado = max(1, int(round(size * 0.68)))
    painter.drawPixmap(0, 0, bloque_java(lado))
    painter.drawPixmap(size - lado, size - lado, bloque_bedrock(lado))
    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_copiar(size: int = SIZE) -> QPixmap:
    """Dos hojas superpuestas: copiar una direccion al portapapeles.

    La hoja de delante es clara y la de atras verde para que el simbolo se vea
    tanto en un boton verde como en un fondo claro u oscuro.
    """
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grosor = max(1.0, size / 15.0)

    # Hoja de atras.
    _lapiz(painter, "#245c2e", grosor=grosor)
    painter.setBrush(QColor("#7fc98a"))
    painter.drawRoundedRect(QRectF(0.30 * s, 0.08 * s, 0.56 * s, 0.66 * s), 0.05 * s, 0.05 * s)

    # Hoja de delante.
    _lapiz(painter, "#263238", grosor=grosor)
    painter.setBrush(QColor("#f7faf5"))
    painter.drawRoundedRect(QRectF(0.14 * s, 0.24 * s, 0.56 * s, 0.68 * s), 0.05 * s, 0.05 * s)

    _lapiz(painter, "#5f6f60", grosor=max(1.0, size / 18.0))
    for y in (0.43, 0.56, 0.69):
        painter.drawLine(QPointF(0.28 * s, y * s), QPointF(0.56 * s, y * s))
    painter.end()
    return pixmap


def icono_de_pixmap(pixmap: QPixmap) -> QIcon:
    """Envuelve un dibujo en un ``QIcon`` (con el tamano que ya tiene)."""
    return QIcon(pixmap)


__all__ = [
    "SIZE",
    "PlatformBadge",
    "bloque_bedrock",
    "bloque_java",
    "icono_candado",
    "icono_conectar",
    "icono_consola",
    "icono_copiar",
    "icono_corona",
    "icono_cuadro",
    "icono_de_pixmap",
    "icono_escudo",
    "icono_jugador",
    "icono_lista",
    "icono_mochila",
    "icono_mod",
    "icono_mundo",
    "icono_no",
    "icono_pack",
    "icono_pase",
    "icono_plataforma",
    "icono_plugin",
    "icono_salida",
    "icono_si",
    "marcar_desactivado",
    "pixmap_de_bytes",
    "punto_estado",
]


# ================================================================ objetos ====
#: Colores (claro, oscuro) de los materiales que aparecen en los nombres.
_MATERIALES: tuple[tuple[tuple[str, ...], tuple[str, str]], ...] = (
    (("netherite",), ("#6a5a66", "#3b3238")),
    (("diamond",), ("#5fe0da", "#2a9d99")),
    (("emerald",), ("#4fd07a", "#1f7a43")),
    (("golden", "gold"), ("#f5ce5d", "#b8860b")),
    (("iron",), ("#dfe4e8", "#8d949b")),
    (("copper",), ("#d98a55", "#8a4a26")),
    (("chainmail",), ("#b3bac2", "#6f7780")),
    (("leather",), ("#b06a38", "#6b3a1c")),
    (("stone", "cobblestone", "andesite", "diorite", "granite", "deepslate", "tuff"), ("#a8adb2", "#666b70")),
    (("wooden", "oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "bamboo", "crimson", "warped", "wood"), ("#bd8a52", "#744a22")),
)

#: Bloques que se pintan como un cubo (aunque el nombre no acabe en _block).
_BLOQUES = frozenset(
    {
        "dirt",
        "grass_block",
        "stone",
        "cobblestone",
        "sand",
        "gravel",
        "clay",
        "obsidian",
        "netherrack",
        "end_stone",
        "deepslate",
        "tuff",
        "basalt",
        "glass",
        "bricks",
        "snow_block",
        "mossy_cobblestone",
        "soul_sand",
        "soul_soil",
        "mycelium",
        "podzol",
        "farmland",
        "sponge",
        "crying_obsidian",
        "magma_block",
        "glowstone",
    }
)

#: Colores propios de algunos bloques muy reconocibles.
_COLORES_BLOQUE: dict[str, tuple[str, str, str]] = {
    "grass_block": ("#6cbb3c", "#8a5a2b", "#2f5c19"),
    "dirt": ("#8a5a2b", "#744a22", "#4a2f14"),
    "stone": ("#9aa0a6", "#7c8288", "#575c61"),
    "cobblestone": ("#a8adb2", "#86868c", "#5b5f63"),
    "sand": ("#e8d9a0", "#cdbb7a", "#a89a5e"),
    "gravel": ("#9a9490", "#7d7874", "#565250"),
    "oak_planks": ("#c99b62", "#a87b45", "#7a5527"),
    "obsidian": ("#3b2a52", "#2a1d3c", "#170f22"),
    "netherrack": ("#8a3b3b", "#6d2b2b", "#4a1b1b"),
    "glass": ("#cfe9ee", "#a8d4dc", "#7fb3bd"),
    "bricks": ("#b05a4a", "#96483b", "#6d3027"),
    "snow_block": ("#f4f8fa", "#dbe6ec", "#b6c6cf"),
}

#: Alimentos que se dibujan con forma de comida.
_COMIDAS = frozenset(
    {
        "apple",
        "golden_apple",
        "enchanted_golden_apple",
        "bread",
        "carrot",
        "potato",
        "baked_potato",
        "beetroot",
        "cookie",
        "cake",
        "melon_slice",
        "sweet_berries",
        "glow_berries",
        "beef",
        "cooked_beef",
        "porkchop",
        "cooked_porkchop",
        "chicken",
        "cooked_chicken",
        "mutton",
        "cooked_mutton",
        "cod",
        "cooked_cod",
        "salmon",
        "cooked_salmon",
        "tropical_fish",
        "rabbit",
        "cooked_rabbit",
        "pumpkin_pie",
        "mushroom_stew",
        "beetroot_soup",
        "rabbit_stew",
    }
)


#: Colores propios de objetos que no se deducen del nombre del material.
_COLORES_ESPECIALES: dict[str, tuple[str, str]] = {
    "coal": ("#4a4a4a", "#1f1f1f"),
    "charcoal": ("#4a4a4a", "#1f1f1f"),
    "redstone": ("#ef4b3a", "#8a1f14"),
    "lapis_lazuli": ("#3a63d0", "#1e3a8a"),
    "amethyst_shard": ("#b07ae0", "#6a3f96"),
    "quartz": ("#f1ece2", "#c9c1b2"),
    "flint": ("#4b4b4b", "#262626"),
    "echo_shard": ("#2fa7a0", "#155e5a"),
    "prismarine_shard": ("#63c9b8", "#2f7f73"),
    "gunpowder": ("#8b8b8b", "#4a4a4a"),
}


def _material(nombre: str) -> tuple[str, str]:
    for clave, colores in _COLORES_ESPECIALES.items():
        if clave in nombre:
            return colores
    for claves, colores in _MATERIALES:
        if any(clave in nombre for clave in claves):
            return colores
    return "#b9c0c7", "#6f7780"


def _forma_cubo(painter: QPainter, s: float, nombre: str, claro: str, oscuro: str) -> None:
    """Cubo en perspectiva con la cara de arriba mas clara."""
    superior, izquierda, borde = _COLORES_BLOQUE.get(
        nombre, (claro, oscuro, "#3a3a3a")
    )
    c = s * 0.08
    m = s * 0.5
    a = s * 0.16
    # Cara superior.
    _relleno(painter, superior)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(c, s * 0.32),
                QPointF(m, a),
                QPointF(s - c, s * 0.32),
                QPointF(m, s * 0.48),
            ]
        )
    )
    # Cara izquierda y derecha.
    _relleno(painter, izquierda)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(c, s * 0.32),
                QPointF(m, s * 0.48),
                QPointF(m, s - a),
                QPointF(c, s * 0.58),
            ]
        )
    )
    _relleno(painter, borde)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(s - c, s * 0.32),
                QPointF(m, s * 0.48),
                QPointF(m, s - a),
                QPointF(s - c, s * 0.58),
            ]
        )
    )


def _forma_espada(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _lapiz(painter, "#5d3a17", grosor=max(1.2, s / 12.0))
    painter.drawLine(QPointF(0.22 * s, 0.78 * s), QPointF(0.40 * s, 0.60 * s))
    _relleno(painter, "#e8c15a")
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.28 * s, 0.56 * s),
                QPointF(0.44 * s, 0.72 * s),
                QPointF(0.52 * s, 0.64 * s),
                QPointF(0.36 * s, 0.48 * s),
            ]
        )
    )
    _pincel(painter, claro, grosor=max(1.0, s / 18.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.38 * s, 0.58 * s),
                QPointF(0.82 * s, 0.14 * s),
                QPointF(0.88 * s, 0.20 * s),
                QPointF(0.44 * s, 0.64 * s),
            ]
        )
    )
    _lapiz(painter, oscuro, grosor=max(0.8, s / 22.0))
    painter.drawLine(QPointF(0.44 * s, 0.56 * s), QPointF(0.86 * s, 0.16 * s))


def _forma_pico(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _lapiz(painter, "#7a4f26", grosor=max(1.6, s / 7.0))
    painter.drawLine(QPointF(0.30 * s, 0.84 * s), QPointF(0.66 * s, 0.40 * s))
    _lapiz(painter, claro, grosor=max(1.4, s / 8.0))
    painter.drawArc(QRectF(0.36 * s, 0.14 * s, 0.56 * s, 0.42 * s), 150 * 16, 150 * 16)
    _lapiz(painter, oscuro, grosor=max(0.8, s / 20.0))
    painter.drawArc(QRectF(0.36 * s, 0.14 * s, 0.56 * s, 0.42 * s), 150 * 16, 150 * 16)


def _forma_hacha(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _lapiz(painter, "#7a4f26", grosor=max(1.6, s / 7.0))
    painter.drawLine(QPointF(0.30 * s, 0.86 * s), QPointF(0.62 * s, 0.40 * s))
    _pincel(painter, claro, grosor=max(1.0, s / 18.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.52 * s, 0.36 * s),
                QPointF(0.78 * s, 0.16 * s),
                QPointF(0.90 * s, 0.34 * s),
                QPointF(0.64 * s, 0.52 * s),
            ]
        )
    )
    _lapiz(painter, oscuro, grosor=max(0.8, s / 22.0))
    painter.drawLine(QPointF(0.56 * s, 0.42 * s), QPointF(0.82 * s, 0.24 * s))


def _forma_pala(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _lapiz(painter, "#7a4f26", grosor=max(1.6, s / 7.0))
    painter.drawLine(QPointF(0.28 * s, 0.86 * s), QPointF(0.62 * s, 0.40 * s))
    _pincel(painter, claro, grosor=max(1.0, s / 18.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.54 * s, 0.34 * s),
                QPointF(0.78 * s, 0.12 * s),
                QPointF(0.92 * s, 0.28 * s),
                QPointF(0.68 * s, 0.50 * s),
            ]
        )
    )
    _lapiz(painter, oscuro, grosor=max(0.8, s / 22.0))
    painter.drawLine(QPointF(0.58 * s, 0.40 * s), QPointF(0.82 * s, 0.20 * s))


def _forma_azada(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _lapiz(painter, "#7a4f26", grosor=max(1.6, s / 7.0))
    painter.drawLine(QPointF(0.28 * s, 0.86 * s), QPointF(0.62 * s, 0.40 * s))
    _lapiz(painter, claro, grosor=max(1.6, s / 7.0))
    painter.drawLine(QPointF(0.58 * s, 0.36 * s), QPointF(0.86 * s, 0.24 * s))
    painter.drawLine(QPointF(0.86 * s, 0.24 * s), QPointF(0.88 * s, 0.44 * s))


def _forma_armadura(painter: QPainter, s: float, nombre: str, claro: str, oscuro: str) -> None:
    _relleno(painter, claro)
    if nombre.endswith("helmet"):
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.20 * s, 0.46 * s),
                    QPointF(0.28 * s, 0.22 * s),
                    QPointF(0.72 * s, 0.22 * s),
                    QPointF(0.80 * s, 0.46 * s),
                    QPointF(0.80 * s, 0.72 * s),
                    QPointF(0.62 * s, 0.72 * s),
                    QPointF(0.62 * s, 0.52 * s),
                    QPointF(0.38 * s, 0.52 * s),
                    QPointF(0.38 * s, 0.72 * s),
                    QPointF(0.20 * s, 0.72 * s),
                ]
            )
        )
    elif nombre.endswith("chestplate"):
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.34 * s, 0.20 * s),
                    QPointF(0.66 * s, 0.20 * s),
                    QPointF(0.84 * s, 0.32 * s),
                    QPointF(0.78 * s, 0.52 * s),
                    QPointF(0.70 * s, 0.46 * s),
                    QPointF(0.70 * s, 0.82 * s),
                    QPointF(0.30 * s, 0.82 * s),
                    QPointF(0.30 * s, 0.46 * s),
                    QPointF(0.22 * s, 0.52 * s),
                    QPointF(0.16 * s, 0.32 * s),
                ]
            )
        )
    elif nombre.endswith("leggings"):
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.28 * s, 0.18 * s),
                    QPointF(0.72 * s, 0.18 * s),
                    QPointF(0.70 * s, 0.82 * s),
                    QPointF(0.54 * s, 0.82 * s),
                    QPointF(0.50 * s, 0.48 * s),
                    QPointF(0.46 * s, 0.82 * s),
                    QPointF(0.30 * s, 0.82 * s),
                ]
            )
        )
    else:  # botas
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.26 * s, 0.30 * s),
                    QPointF(0.44 * s, 0.30 * s),
                    QPointF(0.44 * s, 0.64 * s),
                    QPointF(0.66 * s, 0.64 * s),
                    QPointF(0.70 * s, 0.80 * s),
                    QPointF(0.26 * s, 0.80 * s),
                ]
            )
        )
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.56 * s, 0.30 * s),
                    QPointF(0.74 * s, 0.30 * s),
                    QPointF(0.74 * s, 0.60 * s),
                    QPointF(0.56 * s, 0.60 * s),
                ]
            )
        )
    _lapiz(painter, oscuro, grosor=max(0.8, s / 20.0))
    painter.drawLine(QPointF(0.30 * s, 0.52 * s), QPointF(0.70 * s, 0.52 * s))


def _forma_comida(painter: QPainter, s: float, nombre: str, claro: str, oscuro: str) -> None:
    if nombre in {"bread", "cookie", "cake", "pumpkin_pie"}:
        _pincel(painter, "#c78b3e", grosor=max(1.0, s / 18.0))
        painter.drawRoundedRect(QRectF(0.16 * s, 0.34 * s, 0.68 * s, 0.36 * s), s * 0.16, s * 0.16)
        _lapiz(painter, "#8a5a2b", grosor=max(0.8, s / 22.0))
        painter.drawLine(QPointF(0.32 * s, 0.44 * s), QPointF(0.68 * s, 0.44 * s))
        return
    if nombre.endswith(("beef", "porkchop", "mutton", "chicken", "rabbit", "cod", "salmon")):
        _pincel(painter, claro if claro != "#b9c0c7" else "#d98a8a", grosor=max(1.0, s / 18.0))
        painter.drawEllipse(QRectF(0.18 * s, 0.30 * s, 0.64 * s, 0.44 * s))
        _relleno(painter, "#efe6d2")
        painter.drawEllipse(QRectF(0.22 * s, 0.52 * s, 0.20 * s, 0.16 * s))
        return
    # Manzana o fruta redonda.
    _pincel(painter, claro if nombre != "apple" else "#d94b3b", grosor=max(1.0, s / 18.0))
    painter.drawEllipse(QRectF(0.20 * s, 0.28 * s, 0.60 * s, 0.58 * s))
    _lapiz(painter, "#6b4520", grosor=max(1.0, s / 16.0))
    painter.drawLine(QPointF(0.50 * s, 0.30 * s), QPointF(0.54 * s, 0.14 * s))
    _relleno(painter, "#5aa64a")
    painter.drawEllipse(QRectF(0.54 * s, 0.12 * s, 0.20 * s, 0.12 * s))


def _forma_lingote(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    """Lingote en perspectiva: cara de arriba clara y dos caras laterales."""
    _pincel(painter, claro, grosor=max(0.8, s / 24.0))
    # Cara superior.
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.24 * s, 0.46 * s),
                QPointF(0.34 * s, 0.34 * s),
                QPointF(0.86 * s, 0.34 * s),
                QPointF(0.76 * s, 0.46 * s),
            ]
        )
    )
    # Cara frontal.
    _relleno(painter, oscuro)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.24 * s, 0.46 * s),
                QPointF(0.76 * s, 0.46 * s),
                QPointF(0.76 * s, 0.68 * s),
                QPointF(0.24 * s, 0.68 * s),
            ]
        )
    )
    # Lateral derecho, mas oscuro.
    _relleno(painter, oscuro)
    painter.setOpacity(0.7)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.76 * s, 0.46 * s),
                QPointF(0.86 * s, 0.34 * s),
                QPointF(0.86 * s, 0.56 * s),
                QPointF(0.76 * s, 0.68 * s),
            ]
        )
    )
    painter.setOpacity(1.0)
    _lapiz(painter, "#ffffff", grosor=max(0.7, s / 28.0))
    painter.setOpacity(0.35)
    painter.drawLine(QPointF(0.30 * s, 0.50 * s), QPointF(0.70 * s, 0.50 * s))
    painter.setOpacity(1.0)


def _forma_gema(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _pincel(painter, claro, grosor=max(0.9, s / 20.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.50 * s, 0.16 * s),
                QPointF(0.82 * s, 0.42 * s),
                QPointF(0.68 * s, 0.84 * s),
                QPointF(0.32 * s, 0.84 * s),
                QPointF(0.18 * s, 0.42 * s),
            ]
        )
    )
    _lapiz(painter, oscuro, grosor=max(0.8, s / 24.0))
    painter.drawLine(QPointF(0.50 * s, 0.16 * s), QPointF(0.50 * s, 0.84 * s))
    painter.drawLine(QPointF(0.18 * s, 0.42 * s), QPointF(0.82 * s, 0.42 * s))
    _relleno(painter, "#ffffff")
    painter.setOpacity(0.55)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.50 * s, 0.20 * s),
                QPointF(0.62 * s, 0.44 * s),
                QPointF(0.50 * s, 0.44 * s),
            ]
        )
    )
    painter.setOpacity(1.0)


def _forma_pocion(painter: QPainter, s: float, claro: str) -> None:
    _lapiz(painter, "#cfd8dd", grosor=max(1.0, s / 14.0))
    painter.drawLine(QPointF(0.42 * s, 0.18 * s), QPointF(0.42 * s, 0.36 * s))
    painter.drawLine(QPointF(0.58 * s, 0.18 * s), QPointF(0.58 * s, 0.36 * s))
    painter.drawEllipse(QRectF(0.24 * s, 0.34 * s, 0.52 * s, 0.50 * s))
    _relleno(painter, claro)
    painter.drawEllipse(QRectF(0.30 * s, 0.46 * s, 0.40 * s, 0.34 * s))
    _relleno(painter, "#8a5a2b")
    painter.drawRect(QRectF(0.40 * s, 0.12 * s, 0.20 * s, 0.08 * s))


def _forma_antorcha(painter: QPainter, s: float) -> None:
    _lapiz(painter, "#7a4f26", grosor=max(1.8, s / 6.0))
    painter.drawLine(QPointF(0.50 * s, 0.82 * s), QPointF(0.50 * s, 0.38 * s))
    _relleno(painter, "#f3a72f")
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.50 * s, 0.10 * s),
                QPointF(0.64 * s, 0.34 * s),
                QPointF(0.50 * s, 0.44 * s),
                QPointF(0.36 * s, 0.34 * s),
            ]
        )
    )
    _relleno(painter, "#ffe28a")
    painter.drawEllipse(QRectF(0.45 * s, 0.26 * s, 0.10 * s, 0.14 * s))


def _forma_arco(painter: QPainter, s: float) -> None:
    _lapiz(painter, "#8a5a2b", grosor=max(1.4, s / 9.0))
    painter.drawArc(QRectF(0.18 * s, 0.10 * s, 0.62 * s, 0.80 * s), 290 * 16, 220 * 16)
    _lapiz(painter, "#e8e8e8", grosor=max(0.7, s / 26.0))
    painter.drawLine(QPointF(0.62 * s, 0.12 * s), QPointF(0.62 * s, 0.88 * s))


def _forma_vara(painter: QPainter, s: float) -> None:
    _lapiz(painter, "#8a5a2b", grosor=max(1.6, s / 7.0))
    painter.drawLine(QPointF(0.24 * s, 0.82 * s), QPointF(0.76 * s, 0.22 * s))


def _forma_papel(painter: QPainter, s: float) -> None:
    _pincel(painter, "#f4f1e8", grosor=max(0.9, s / 22.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.28 * s, 0.14 * s),
                QPointF(0.64 * s, 0.14 * s),
                QPointF(0.76 * s, 0.28 * s),
                QPointF(0.76 * s, 0.86 * s),
                QPointF(0.28 * s, 0.86 * s),
            ]
        )
    )
    _relleno(painter, "#cfc7b4")
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.64 * s, 0.14 * s),
                QPointF(0.76 * s, 0.28 * s),
                QPointF(0.64 * s, 0.28 * s),
            ]
        )
    )
    _lapiz(painter, "#a89e88", grosor=max(0.7, s / 26.0))
    for y in (0.46, 0.58, 0.70):
        painter.drawLine(QPointF(0.36 * s, y * s), QPointF(0.68 * s, y * s))


def _forma_hilo(painter: QPainter, s: float) -> None:
    _lapiz(painter, "#ececec", grosor=max(1.1, s / 12.0))
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(0.20 * s, 0.28 * s),
                QPointF(0.38 * s, 0.46 * s),
                QPointF(0.24 * s, 0.62 * s),
                QPointF(0.46 * s, 0.82 * s),
                QPointF(0.74 * s, 0.60 * s),
            ]
        )
    )


def _forma_pluma(painter: QPainter, s: float) -> None:
    _pincel(painter, "#f2f2f2", grosor=max(0.9, s / 22.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.68 * s, 0.12 * s),
                QPointF(0.82 * s, 0.28 * s),
                QPointF(0.50 * s, 0.70 * s),
                QPointF(0.32 * s, 0.84 * s),
                QPointF(0.36 * s, 0.60 * s),
            ]
        )
    )
    _lapiz(painter, "#a8a8a8", grosor=max(0.8, s / 24.0))
    painter.drawLine(QPointF(0.70 * s, 0.18 * s), QPointF(0.36 * s, 0.84 * s))


def _forma_cubo_de_agua(painter: QPainter, s: float, claro: str) -> None:
    _pincel(painter, claro, grosor=max(0.9, s / 22.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.26 * s, 0.36 * s),
                QPointF(0.74 * s, 0.36 * s),
                QPointF(0.68 * s, 0.82 * s),
                QPointF(0.32 * s, 0.82 * s),
            ]
        )
    )
    _lapiz(painter, "#5a6268", grosor=max(1.0, s / 18.0))
    painter.drawArc(QRectF(0.22 * s, 0.16 * s, 0.56 * s, 0.40 * s), 0, 180 * 16)
    _lapiz(painter, "#f4f4f4", grosor=max(0.7, s / 28.0))
    painter.drawLine(QPointF(0.34 * s, 0.48 * s), QPointF(0.66 * s, 0.48 * s))


def _forma_escudo(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _pincel(painter, oscuro, grosor=max(1.0, s / 18.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.50 * s, 0.12 * s),
                QPointF(0.84 * s, 0.24 * s),
                QPointF(0.80 * s, 0.58 * s),
                QPointF(0.50 * s, 0.88 * s),
                QPointF(0.20 * s, 0.58 * s),
                QPointF(0.16 * s, 0.24 * s),
            ]
        )
    )
    _pincel(painter, claro, grosor=max(0.8, s / 26.0))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(0.50 * s, 0.20 * s),
                QPointF(0.76 * s, 0.30 * s),
                QPointF(0.72 * s, 0.54 * s),
                QPointF(0.50 * s, 0.78 * s),
                QPointF(0.28 * s, 0.54 * s),
                QPointF(0.24 * s, 0.30 * s),
            ]
        )
    )
    _lapiz(painter, "#e3c15a", grosor=max(0.8, s / 24.0))
    painter.drawLine(QPointF(0.50 * s, 0.24 * s), QPointF(0.50 * s, 0.74 * s))


def _forma_libro(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _pincel(painter, claro, grosor=max(0.9, s / 22.0))
    painter.drawRoundedRect(QRectF(0.18 * s, 0.18 * s, 0.64 * s, 0.66 * s), s * 0.06, s * 0.06)
    _relleno(painter, "#f4f1e8")
    painter.drawRect(QRectF(0.30 * s, 0.24 * s, 0.44 * s, 0.54 * s))
    _lapiz(painter, oscuro, grosor=max(1.0, s / 18.0))
    painter.drawLine(QPointF(0.28 * s, 0.18 * s), QPointF(0.28 * s, 0.84 * s))
    for y in (0.38, 0.48, 0.58):
        painter.drawLine(QPointF(0.38 * s, y * s), QPointF(0.66 * s, y * s))


def _forma_bola(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _pincel(painter, claro, grosor=max(0.9, s / 22.0))
    painter.drawEllipse(QRectF(0.18 * s, 0.18 * s, 0.64 * s, 0.64 * s))
    _relleno(painter, "#ffffff")
    painter.setOpacity(0.5)
    painter.drawEllipse(QRectF(0.28 * s, 0.26 * s, 0.18 * s, 0.14 * s))
    painter.setOpacity(1.0)
    _lapiz(painter, oscuro, grosor=max(0.8, s / 24.0))
    painter.drawArc(QRectF(0.18 * s, 0.18 * s, 0.64 * s, 0.64 * s), 200 * 16, 120 * 16)


def _forma_saco(painter: QPainter, s: float, claro: str, oscuro: str) -> None:
    _pincel(painter, claro, grosor=max(1.0, s / 18.0))
    painter.drawRoundedRect(QRectF(0.22 * s, 0.34 * s, 0.56 * s, 0.48 * s), s * 0.12, s * 0.12)
    _lapiz(painter, oscuro, grosor=max(1.0, s / 16.0))
    painter.drawLine(QPointF(0.32 * s, 0.34 * s), QPointF(0.50 * s, 0.20 * s))
    painter.drawLine(QPointF(0.68 * s, 0.34 * s), QPointF(0.50 * s, 0.20 * s))


@lru_cache(maxsize=512)
def item_icon(item_id: str, size: int = SIZE) -> QPixmap:
    """Icono dibujado de un objeto, por categoria y material.

    Es el respaldo sin conexion de las texturas de verdad: se reconoce un pico,
    una espada, una manzana o un bloque, con el color del material (diamante,
    hierro, oro...). Se dibuja aqui mismo, sin descargar nada.
    """
    nombre = str(item_id or "").split(":")[-1].strip().lower()
    pixmap = _lienzo(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    claro, oscuro = _material(nombre)

    if nombre in _BLOQUES or nombre.endswith(("_planks", "_log", "_wood", "_ore", "_block")):
        _forma_cubo(painter, s, nombre, claro, oscuro)
    elif nombre.endswith("sword"):
        _forma_espada(painter, s, claro, oscuro)
    elif nombre.endswith("pickaxe"):
        _forma_pico(painter, s, claro, oscuro)
    elif nombre.endswith("axe"):
        _forma_hacha(painter, s, claro, oscuro)
    elif nombre.endswith("shovel"):
        _forma_pala(painter, s, claro, oscuro)
    elif nombre.endswith("hoe"):
        _forma_azada(painter, s, claro, oscuro)
    elif nombre.endswith(("helmet", "chestplate", "leggings", "boots")):
        _forma_armadura(painter, s, nombre, claro, oscuro)
    elif nombre in _COMIDAS or nombre.endswith(("_stew", "_soup", "_slice", "berries", "_pie")):
        _forma_comida(painter, s, nombre, claro, oscuro)
    elif nombre.endswith("ingot") or nombre.endswith("nugget"):
        _forma_lingote(painter, s, claro, oscuro)
    elif nombre in {
        "diamond",
        "emerald",
        "lapis_lazuli",
        "amethyst_shard",
        "quartz",
        "coal",
        "charcoal",
        "redstone",
        "gunpowder",
        "flint",
        "echo_shard",
        "prismarine_shard",
    }:
        _forma_gema(painter, s, claro, oscuro)
    elif nombre.endswith(("potion", "bottle")):
        _forma_pocion(painter, s, claro if nombre != "potion" else "#c05ad9")
    elif nombre in {"paper", "map", "filled_map", "name_tag"}:
        _forma_papel(painter, s)
    elif nombre in {"string", "lead"}:
        _forma_hilo(painter, s)
    elif nombre in {"feather", "phantom_membrane"}:
        _forma_pluma(painter, s)
    elif nombre.endswith("bucket"):
        _forma_cubo_de_agua(painter, s, claro if nombre != "bucket" else "#c9ced3")
    elif nombre == "shield":
        _forma_escudo(painter, s, claro, oscuro)
    elif nombre in {"book", "writable_book", "written_book", "enchanted_book", "knowledge_book"}:
        _forma_libro(painter, s, claro if nombre != "book" else "#a05a2c", oscuro)
    elif nombre in {"ender_pearl", "snowball", "egg", "slime_ball", "fire_charge", "magma_cream"}:
        _forma_bola(painter, s, claro, oscuro)
    elif nombre in {"torch", "soul_torch", "redstone_torch"}:
        _forma_antorcha(painter, s)
    elif nombre in {"bow", "crossbow"}:
        _forma_arco(painter, s)
    elif nombre in {"arrow", "spectral_arrow", "stick", "blaze_rod", "breeze_rod"}:
        _forma_vara(painter, s)
    else:
        _forma_saco(painter, s, claro, oscuro)
    painter.end()
    return pixmap


@lru_cache(maxsize=256)
def texture_pixmap(datos: bytes, size: int = SIZE) -> QPixmap:
    """Convierte los bytes de una textura en un pixmap nitido (sin suavizar).

    Las texturas del juego son pixel art: escalarlas con suavizado las vuelve
    borrosas, asi que se usa el vecino mas cercano.
    """
    if not datos:
        return QPixmap()
    imagen = QPixmap()
    if not imagen.loadFromData(datos):
        return QPixmap()
    return imagen.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
