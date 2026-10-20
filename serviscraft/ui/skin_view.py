"""La skin de un jugador: su cara y su cuerpo, sacados del PNG de 64x64.

Minecraft guarda la skin como una imagen de 64x64 con las seis caras de cada
parte del cuerpo colocadas en posiciones fijas. Aqui se recortan las caras
frontales y se componen en un muneco pequeno, sin suavizado (pixel art), igual
que se ve en el juego.

Si no hay skin (servidor sin conexion, jugador sin cuenta...) se dibuja un
jugador generico para que la ventana no quede vacia.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from .mc_icons import icono_jugador

#: Posiciones (x, y, ancho, alto) de las caras frontales en la skin moderna.
_CABEZA = (8, 8, 8, 8)
_CABEZA_SOMBRERO = (40, 8, 8, 8)
_CUERPO = (20, 20, 8, 12)
_CUERPO_CHAQUETA = (20, 36, 8, 12)
_BRAZO_DERECHO = (44, 20, 4, 12)
_BRAZO_DERECHO_MANGA = (44, 36, 4, 12)
_BRAZO_IZQUIERDO = (36, 20, 4, 12)
_BRAZO_IZQUIERDO_MANGA = (36, 36, 4, 12)
_PIERNA_DERECHA = (4, 20, 4, 12)
_PIERNA_DERECHA_PANTALON = (4, 36, 4, 12)
_PIERNA_IZQUIERDA = (20, 52, 4, 12)
_PIERNA_IZQUIERDA_PANTALON = (4, 52, 4, 12)


def _imagen(datos: bytes) -> QImage | None:
    if not datos:
        return None
    imagen = QImage()
    if not imagen.loadFromData(datos):
        return None
    if imagen.isNull() or imagen.width() < 64 or imagen.height() < 32:
        return None
    return imagen.convertToFormat(QImage.Format.Format_ARGB32)


def has_skin(datos: bytes) -> bool:
    return _imagen(datos) is not None


def _recorte(imagen: QImage, rect: tuple[int, int, int, int]) -> QImage:
    x, y, ancho, alto = rect
    return imagen.copy(QRect(x, y, ancho, alto))


def _pegar(
    lienzo: QImage,
    parte: QImage,
    x: int,
    y: int,
    *,
    voltear: bool = False,
) -> None:
    """Pega una parte (4x12, 8x8...) en el lienzo de 16x32 unidades."""
    if parte.isNull():
        return
    if voltear:
        parte = parte.mirrored(True, False)
    painter = QPainter(lienzo)
    painter.drawImage(QRect(x, y, parte.width(), parte.height()), parte)
    painter.end()


def _capa(imagen: QImage, base: tuple, extra: tuple) -> QImage:
    """Parte base con su capa de ropa/sombrero encima (si existe)."""
    resultado = _recorte(imagen, base).copy()
    if imagen.width() >= extra[0] + extra[2] and imagen.height() >= extra[1] + extra[3]:
        capa = _recorte(imagen, extra)
        painter = QPainter(resultado)
        painter.drawImage(0, 0, capa)
        painter.end()
    return resultado


def _generica() -> QImage:
    """Jugador generico (piel, camiseta azul y pantalon) para cuando no hay skin."""
    lienzo = QImage(16, 32, QImage.Format.Format_ARGB32)
    lienzo.fill(Qt.GlobalColor.transparent)
    painter = QPainter(lienzo)
    piel = QColor("#c98f66")
    pelo = QColor("#5a3a22")
    camiseta = QColor("#2f9fd0")
    pantalon = QColor("#3b4a8a")
    zapatos = QColor("#4a4a4a")
    # Cabeza (con pelo arriba y ojos).
    painter.fillRect(QRect(4, 0, 8, 8), piel)
    painter.fillRect(QRect(4, 0, 8, 2), pelo)
    painter.fillRect(QRect(4, 0, 1, 3), pelo)
    painter.fillRect(QRect(11, 0, 1, 3), pelo)
    painter.fillRect(QRect(5, 3, 2, 1), QColor("#3b2a1a"))
    painter.fillRect(QRect(9, 3, 2, 1), QColor("#3b2a1a"))
    # Cuerpo y brazos.
    painter.fillRect(QRect(4, 8, 8, 12), camiseta)
    painter.fillRect(QRect(0, 8, 4, 12), piel)
    painter.fillRect(QRect(12, 8, 4, 12), piel)
    # Piernas.
    painter.fillRect(QRect(4, 20, 4, 10), pantalon)
    painter.fillRect(QRect(8, 20, 4, 10), pantalon)
    painter.fillRect(QRect(4, 29, 4, 3), zapatos)
    painter.fillRect(QRect(8, 29, 4, 3), zapatos)
    painter.end()
    return lienzo


def _componer(datos: bytes) -> QImage:
    imagen = _imagen(datos)
    if imagen is None:
        return _generica()

    lienzo = QImage(16, 32, QImage.Format.Format_ARGB32)
    lienzo.fill(Qt.GlobalColor.transparent)

    _pegar(lienzo, _capa(imagen, _CABEZA, _CABEZA_SOMBRERO), 4, 0)
    _pegar(lienzo, _capa(imagen, _CUERPO, _CUERPO_CHAQUETA), 4, 8)
    if imagen.width() >= 64 and imagen.height() >= 64:
        _pegar(lienzo, _capa(imagen, _BRAZO_DERECHO, _BRAZO_DERECHO_MANGA), 0, 8)
        _pegar(lienzo, _capa(imagen, _BRAZO_IZQUIERDO, _BRAZO_IZQUIERDO_MANGA), 12, 8)
        _pegar(lienzo, _capa(imagen, _PIERNA_DERECHA, _PIERNA_DERECHA_PANTALON), 4, 20)
        _pegar(lienzo, _capa(imagen, _PIERNA_IZQUIERDA, _PIERNA_IZQUIERDA_PANTALON), 8, 20)
    else:
        # Formato antiguo (64x32): los dos brazos y las dos piernas comparten
        # textura; el lado izquierdo se refleja.
        _pegar(lienzo, _recorte(imagen, _BRAZO_DERECHO), 0, 8)
        _pegar(lienzo, _recorte(imagen, _BRAZO_DERECHO), 12, 8, voltear=True)
        _pegar(lienzo, _recorte(imagen, _PIERNA_DERECHA), 4, 20)
        _pegar(lienzo, _recorte(imagen, _PIERNA_DERECHA), 8, 20, voltear=True)
    return lienzo


def _escalar(imagen: QImage, ancho: int, alto: int) -> QPixmap:
    return QPixmap.fromImage(
        imagen.scaled(
            ancho,
            alto,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
    )


@lru_cache(maxsize=64)
def head_pixmap(datos: bytes, size: int = 32) -> QPixmap:
    """Cara del jugador (con el sombrero o el pelo que tenga la skin)."""
    imagen = _imagen(datos)
    if imagen is None:
        return icono_jugador(size)
    cabeza = lienzo = QImage(8, 8, QImage.Format.Format_ARGB32)
    cabeza.fill(Qt.GlobalColor.transparent)
    _pegar(cabeza, _capa(imagen, _CABEZA, _CABEZA_SOMBRERO), 0, 0)
    return _escalar(lienzo, size, size)


@lru_cache(maxsize=64)
def body_pixmap(datos: bytes, height: int = 96) -> QPixmap:
    """Muneco con la skin puesta (16x32 unidades, escalado a ``height``)."""
    alto = max(16, int(height))
    ancho = max(8, alto // 2)
    return _escalar(_componer(datos), ancho, alto)


def head_from_skin(datos: bytes, size: int = 40) -> QPixmap:
    """Igual que :func:`head_pixmap`, con el nombre que usa la ventana."""
    return head_pixmap(datos, size)


__all__ = ["body_pixmap", "has_skin", "head_from_skin", "head_pixmap"]
