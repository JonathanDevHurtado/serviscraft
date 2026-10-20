"""Ventana para cambiar la imagen y la descripcion del servidor.

Son las dos cosas que se ven en la lista de servidores de Minecraft **antes de
entrar**: el icono de 64x64 y las dos lineas de descripcion (el ``motd``), que
admiten colores. Con esto cada servidor se distingue de los demas de un vistazo,
tanto en Minecraft como en la lista de la propia aplicacion.

La ventana ensena una **vista previa** de la entrada tal y como la pinta el
juego, una paleta con los 16 colores de Minecraft (y negrita, cursiva,
subrayado...), un contador de caracteres y un aviso claro de lo unico que hay
que tener en cuenta: Minecraft lee estas dos cosas al arrancar, asi que el
cambio se aplica al reiniciar el servidor.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import appearance
from ..core.errors import ServiscraftError, ValidationError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from .common import (
    FlowRow,
    HelpButton,
    SectionCard,
    WrappingLabel,
    hint_label,
    make_button,
)
from .dialogs import confirm, show_error, show_info
from .mc_icons import (
    bloque_bedrock,
    bloque_java,
    icono_cuadro,
    icono_escudo,
    icono_jugador,
    icono_mod,
    icono_mundo,
    icono_pack,
    icono_plugin,
)
from .server_preview import McListEntry
from .tasks import TaskRunner

logger = get_logger("ui.aspecto")

#: Tamano con el que se ensena el icono dentro de la ventana (el doble, para
#: que se vea el detalle del dibujo sin perder la nitidez de los pixeles).
ICON_PREVIEW = appearance.ICON_SIZE * 2

#: Explicacion completa del boton «?» (texto sin acentos, como el resto de la UI).
_AYUDA = (
    "<b>Que se puede cambiar aqui</b><br>"
    "· <b>La imagen</b>: el cuadro de 64x64 que aparece a la izquierda de tu "
    "servidor en la lista de Minecraft.<br>"
    "· <b>La descripcion</b>: las dos lineas de texto que salen debajo del "
    "nombre, con los colores que elijas.<br><br>"
    "<b>Como se usan los colores</b><br>"
    "Pulsa un color y se escribe delante del texto; todo lo que venga despues "
    "sale de ese color, hasta que pongas otro (o «Normal»).<br>"
    "Si seleccionas un trozo de texto y pulsas un color, solo se colorea ese "
    "trozo.<br><br>"
    "<b>Limites (los pone Minecraft)</b><br>"
    "· Dos lineas como maximo.<br>"
    f"· {appearance.MAX_LINE_LENGTH} caracteres utiles por linea (los codigos "
    "de color no cuentan).<br>"
    "Lo que se pasa de ahi no se ve: el juego lo corta.<br><br>"
    "<b>Muy importante</b><br>"
    "Minecraft lee la imagen y la descripcion <b>al arrancar</b>, asi que el "
    "cambio se ve al reiniciar el servidor. Si el servidor esta en marcha y se "
    "detiene despues, puede volver a escribir su fichero de propiedades: lo mas "
    "seguro es guardar esto con el servidor detenido.<br><br>"
    "<b>Consejo</b><br>Prueba a mirar tu servidor desde «Multijugador → Anadir "
    "servidor» para verlo tal y como lo veran tus amigos."
)

#: Presets de icono dibujados por la aplicacion (sin descargar nada).
_PRESETS: tuple[tuple[str, str], ...] = (
    ("Cesped (Java)", "java"),
    ("Piedra (Bedrock)", "bedrock"),
    ("Modpack", "pack"),
    ("Mod", "mod"),
    ("Pluguin", "plugin"),
    ("Mundo", "mundo"),
    ("Jugador", "jugador"),
    ("Escudo", "escudo"),
)


class MotdEdit(QPlainTextEdit):
    """Editor de la descripcion: dos lineas, como en la lista del juego."""

    def keyPressEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.document().blockCount() >= appearance.MAX_LINES:
                # Enter en la segunda linea: no hay sitio para una tercera.
                return
        super().keyPressEvent(event)


def png_de_imagen(imagen: QImage) -> bytes:
    """Convierte una imagen de Qt en los bytes de un PNG."""
    datos = QByteArray()
    buffer = QBuffer(datos)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    imagen.save(buffer, "PNG")
    buffer.close()
    return bytes(datos)


def png_de_pixmap(pixmap: QPixmap) -> bytes:
    """Convierte un dibujo de la aplicacion en los bytes de un PNG."""
    return png_de_imagen(pixmap.toImage())


def ajustar_a_icono(imagen: QImage) -> bytes:
    """Deja cualquier imagen en un PNG de 64x64 centrado y con transparencia.

    Un icono que ya mide 64x64 se respeta tal cual (el pixel art se estropea al
    suavizarlo); cualquier otra imagen se encaja sin deformarla.
    """
    if imagen.isNull():
        raise ValidationError("icono", "No se pudo leer la imagen elegida.")
    if imagen.width() == appearance.ICON_SIZE and imagen.height() == appearance.ICON_SIZE:
        return png_de_imagen(imagen.convertToFormat(QImage.Format.Format_ARGB32))
    lienzo = QImage(
        appearance.ICON_SIZE, appearance.ICON_SIZE, QImage.Format.Format_ARGB32
    )
    lienzo.fill(Qt.GlobalColor.transparent)
    escalada = imagen.scaled(
        appearance.ICON_SIZE,
        appearance.ICON_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pintor = QPainter(lienzo)
    pintor.drawImage(
        (appearance.ICON_SIZE - escalada.width()) // 2,
        (appearance.ICON_SIZE - escalada.height()) // 2,
        escalada,
    )
    pintor.end()
    return png_de_imagen(lienzo)


@lru_cache(maxsize=1)
def presets_iconos() -> dict[str, QPixmap]:
    """Iconos de Minecraft ya dibujados a 64x64, para elegir sin buscar nada."""
    return {
        "java": bloque_java(appearance.ICON_SIZE),
        "bedrock": bloque_bedrock(appearance.ICON_SIZE),
        "pack": icono_pack(appearance.ICON_SIZE),
        "mod": icono_mod(appearance.ICON_SIZE),
        "plugin": icono_plugin(appearance.ICON_SIZE),
        "mundo": icono_mundo(appearance.ICON_SIZE),
        "jugador": icono_jugador(appearance.ICON_SIZE),
        "escudo": icono_escudo(appearance.ICON_SIZE),
    }


class AppearanceDialog(QDialog):
    """Cambia el icono y la descripcion con los que se ve el servidor."""

    #: Se ha guardado algo: la ventana principal debe refrescar la lista.
    saved = Signal()

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        spec: ServerSpec,
        *,
        running: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self.spec = spec
        self._running = running
        #: Icono actual y cambio pendiente (``None`` = no se ha tocado).
        self._icono = b""
        self._icono_pendiente: bytes | None = None

        self.setWindowTitle(f"Aspecto del servidor · {spec.name}")
        # La ventana se puede encoger y desplazar: en una pantalla pequena (o con
        # la ventana en un mosaico) el contenido no cabe y hay que poder llegar
        # a todo sin que se recorte nada.
        self.setMinimumSize(480, 420)
        self.resize(600, 720)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        contenido = QWidget()
        cuerpo = QVBoxLayout(contenido)
        # Margen a la derecha para que el texto no se pegue a la barra de
        # desplazamiento cuando la ventana es pequena.
        cuerpo.setContentsMargins(0, 0, 8, 0)
        cuerpo.setSpacing(10)

        self.intro = hint_label(
            "Asi se vera tu servidor en la lista de Minecraft: la imagen y las dos "
            "lineas de descripcion son lo que distingue unos servidores de otros."
        )
        cuerpo.addWidget(self.intro)
        cuerpo.addWidget(self._build_icon_card())
        cuerpo.addWidget(self._build_description_card())
        cuerpo.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(contenido)
        layout.addWidget(self.scroll, 1)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.save_button = make_button(
            "Guardar",
            icon_names=("document-save",),
            accent=True,
            tooltip="Guardar la imagen y la descripcion en el servidor",
        )
        self.save_button.clicked.connect(self._guardar)
        self.buttons.addWidget(self.save_button)

        self.close_button = make_button("Cerrar", icon_names=("window-close",))
        self.close_button.clicked.connect(self.close)
        self.buttons.addWidget(self.close_button)
        self.buttons.addStretch(1)
        self.help_button = HelpButton("La imagen y la descripcion del servidor", _AYUDA)
        self.buttons.addWidget(self.help_button)
        layout.addLayout(self.buttons)

        self._cargar()

    # ============================================================== construccion
    def _build_icon_card(self) -> SectionCard:
        card = SectionCard(
            "Imagen del servidor",
            pixmap=icono_cuadro(18),
            help_title="La imagen de la lista de servidores",
            help_text=(
                "Es el cuadro que aparece a la izquierda de tu servidor en la lista "
                "de Minecraft, de 64x64 pixeles.<br><br>Puedes elegir cualquier "
                "imagen de tu equipo: Serviscraft la encaja sola en el tamano que "
                "pide el juego (lo cuadra y, si no es cuadrada, la centra).<br><br>"
                "Si no quieres buscar nada, usa uno de los bloques de Minecraft de "
                "abajo: se generan en tu equipo, sin descargar nada."
            ),
        )
        cuerpo = card.body()

        fila = QHBoxLayout()
        fila.setSpacing(12)

        self.icon_preview = QLabel()
        self.icon_preview.setObjectName("IconPreview")
        self.icon_preview.setFixedSize(ICON_PREVIEW, ICON_PREVIEW)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fila.addWidget(self.icon_preview, 0, Qt.AlignmentFlag.AlignTop)

        columna = QVBoxLayout()
        columna.setSpacing(6)
        self.choose_button = make_button(
            "Elegir una imagen...",
            icon_names=("image-x-generic", "document-open"),
            tooltip="Usa una imagen de tu equipo (se recorta a 64x64)",
        )
        self.choose_button.clicked.connect(self._elegir_imagen)
        columna.addWidget(self.choose_button)

        self.clear_button = make_button(
            "Quitar imagen",
            icon_names=("edit-delete", "edit-clear"),
            tooltip="Volver a la imagen generica del juego",
        )
        self.clear_button.clicked.connect(self._quitar_imagen)
        columna.addWidget(self.clear_button)

        self.icon_note = WrappingLabel("")
        self.icon_note.setObjectName("Hint")
        columna.addWidget(self.icon_note)
        columna.addStretch(1)
        fila.addLayout(columna, 1)
        cuerpo.addLayout(fila)

        cuerpo.addWidget(hint_label("O usa uno de estos bloques, ya preparados:"))
        presets = FlowRow(spacing=6)
        self.preset_buttons: list[QToolButton] = []
        for etiqueta, clave in _PRESETS:
            boton = QToolButton()
            boton.setObjectName("IconPreset")
            boton.setToolTip(f"Usar {etiqueta.lower()} como imagen del servidor")
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setIconSize(QSize(32, 32))
            boton.setIcon(QIcon(presets_iconos()[clave]))
            boton.clicked.connect(lambda _checked=False, c=clave: self._usar_preset(c))
            presets.add(boton)
            self.preset_buttons.append(boton)
        cuerpo.addWidget(presets)
        return card

    def _build_description_card(self) -> SectionCard:
        card = SectionCard(
            "Descripcion de la lista",
            pixmap=icono_cuadro(18),
            help_title="La descripcion con colores",
            help_text=_AYUDA,
        )
        cuerpo = card.body()

        self.preview = McListEntry(scale=2)
        cuerpo.addWidget(self.preview)

        self.motd_edit = MotdEdit()
        self.motd_edit.setObjectName("MotdEdit")
        self.motd_edit.setPlaceholderText(
            "Primera linea\nSegunda linea (opcional)"
        )
        # ``ensurePolished`` aplica ya la hoja de estilos: si se mide antes, la
        # fuente es la de por defecto y el alto se queda corto (una linea y media).
        self.motd_edit.ensurePolished()
        alto_linea = self.motd_edit.fontMetrics().height()
        self.motd_edit.setFixedHeight(2 * alto_linea + 22)
        self.motd_edit.textChanged.connect(self._on_motd_changed)
        cuerpo.addWidget(self.motd_edit)

        self.counter = QLabel("")
        self.counter.setObjectName("Hint")
        self.counter.setWordWrap(True)
        cuerpo.addWidget(self.counter)

        colores = FlowRow(spacing=3)
        etiqueta_color = QLabel("Color:")
        etiqueta_color.setObjectName("Hint")
        colores.add(etiqueta_color)
        self.color_buttons: dict[str, QToolButton] = {}
        for code, (nombre, hexa) in appearance.COLORS.items():
            boton = QToolButton()
            boton.setObjectName("ColorSwatch")
            boton.setToolTip(f"{nombre} (se escribe el codigo en el texto)")
            boton.setFixedSize(20, 20)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(
                f"background-color: {hexa}; border: 1px solid #101014; border-radius: 3px;"
            )
            boton.clicked.connect(lambda _checked=False, c=code: self._insertar_codigo(c))
            colores.add(boton)
            self.color_buttons[code] = boton
        cuerpo.addWidget(colores)

        estilos = FlowRow(spacing=3)
        etiqueta_estilo = QLabel("Estilo:")
        etiqueta_estilo.setObjectName("Hint")
        estilos.add(etiqueta_estilo)
        self.format_buttons: dict[str, QToolButton] = {}
        for code, nombre in appearance.FORMATS.items():
            boton = QToolButton()
            boton.setObjectName("FormatButton")
            boton.setText({"l": "N", "o": "C", "n": "S", "m": "T", "k": "?", "r": "Normal"}[code])
            boton.setToolTip(f"{nombre} (atajo del codigo de Minecraft)")
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.clicked.connect(lambda _checked=False, c=code: self._insertar_codigo(c))
            estilos.add(boton)
            self.format_buttons[code] = boton
        cuerpo.addWidget(estilos)

        cuerpo.addWidget(
            hint_label(
                "Los colores se escriben en el texto con el codigo de Minecraft: lo que "
                "venga despues de un color sale de ese color. El nombre de arriba lo elige "
                "cada jugador en su Minecraft; la imagen y la descripcion las ve todo el "
                "mundo igual."
            )
        )
        return card

    # =================================================================== datos
    def _cargar(self) -> None:
        self._icono = self.manager.server_icon(self.spec.id)
        self._icono_pendiente = None
        try:
            self._texto_original = appearance.validate_text(self.manager.motd(self.spec.id))
        except ServiscraftError:  # pragma: no cover - fichero de propiedades raro
            self._texto_original = ""
        self.motd_edit.blockSignals(True)
        self.motd_edit.setPlainText(self._texto_original)
        self.motd_edit.blockSignals(False)
        self._pintar_icono()
        self._on_motd_changed()

    def _pintar_icono(self) -> None:
        datos = self._icono if self._icono_pendiente is None else self._icono_pendiente
        pixmap = pixmap_icono(datos)
        if pixmap.isNull():
            self.icon_preview.setText("Sin imagen\n(imagen del juego)")
            self.icon_preview.setPixmap(QPixmap())
            self.clear_button.setEnabled(False)
        else:
            self.icon_preview.setText("")
            self.icon_preview.setPixmap(pixmap)
            self.clear_button.setEnabled(True)
        self.icon_note.setText(
            "La imagen actual es la generica del juego."
            if not datos
            else "Esta imagen se guardara en la carpeta del servidor como server-icon.png."
        )
        self.preview.set_icon(pixmap_icono(datos))
        self._actualizar_boton_guardar()

    def _on_motd_changed(self, *_args: object) -> None:
        texto = self.motd_edit.toPlainText()
        lineas = texto.split("\n")
        if len(lineas) > appearance.MAX_LINES:
            # Solo se puede pegar de mas: se recortan las lineas sobrantes.
            recortado = "\n".join(lineas[: appearance.MAX_LINES])
            self.motd_edit.blockSignals(True)
            self.motd_edit.setPlainText(recortado)
            self.motd_edit.blockSignals(False)
            texto = recortado
        self._actualizar_contador(texto)
        self.preview.set_data(self.spec.name, texto)
        self._actualizar_boton_guardar()

    def _actualizar_contador(self, texto: str) -> None:
        partes: list[str] = []
        for numero, linea in enumerate(appearance.useful_lines(texto), start=1):
            utiles = len(appearance.strip_codes(linea))
            partes.append(f"Linea {numero}: {utiles}/{appearance.MAX_LINE_LENGTH}")
        valido, motivo = self._comprobar_texto(texto)
        self.counter.setText(" · ".join(partes) + (f" — {motivo}" if motivo else ""))
        self.counter.setStyleSheet("" if valido else "color: #e05252;")

    def _comprobar_texto(self, texto: str) -> tuple[bool, str]:
        try:
            appearance.validate_text(texto)
            return True, ""
        except ValidationError as exc:
            return False, exc.message

    def _actualizar_boton_guardar(self) -> None:
        valido, _motivo = self._comprobar_texto(self.motd_edit.toPlainText())
        cambio = self._icono_pendiente is not None or self._texto_actual() != self._texto_original
        self.save_button.setEnabled(valido and cambio)

    def _texto_actual(self) -> str:
        try:
            return appearance.validate_text(self.motd_edit.toPlainText())
        except ValidationError:
            return self.motd_edit.toPlainText()

    # ================================================================= acciones
    def _insertar_codigo(self, code: str) -> None:
        """Escribe el codigo de color (o de estilo) en el texto."""
        cursor = self.motd_edit.textCursor()
        marca = f"{appearance.SECTION}{code}"
        if cursor.hasSelection():
            elegido = cursor.selectedText().replace("\u2029", "\n")
            cursor.insertText(f"{marca}{elegido}{appearance.SECTION}r")
        else:
            cursor.insertText(marca)
        self.motd_edit.setTextCursor(cursor)
        self.motd_edit.setFocus()

    def _elegir_imagen(self) -> None:
        ruta, _filtro = QFileDialog.getOpenFileName(
            self,
            "Elegir la imagen del servidor",
            "",
            "Imagenes (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tga);;Todos los ficheros (*)",
        )
        if not ruta:
            return
        imagen = QImage(ruta)
        if imagen.isNull():
            show_error(
                self,
                "No se pudo leer la imagen",
                "El fichero elegido no es una imagen que se pueda usar.",
                ruta,
            )
            return
        try:
            self._icono_pendiente = ajustar_a_icono(imagen)
        except ValidationError as exc:
            show_error(self, "Imagen no valida", exc.message)
            return
        logger.info("Imagen elegida para el servidor %s: %s", self.spec.id, ruta)
        self._pintar_icono()

    def _usar_preset(self, clave: str) -> None:
        pixmap = presets_iconos().get(clave)
        if pixmap is None or pixmap.isNull():  # pragma: no cover - no deberia pasar
            return
        self._icono_pendiente = png_de_pixmap(pixmap)
        self._pintar_icono()

    def _quitar_imagen(self) -> None:
        self._icono_pendiente = b""
        self._pintar_icono()

    def _guardar(self) -> None:
        texto = self.motd_edit.toPlainText()
        try:
            valor = appearance.validate_text(texto)
        except ValidationError as exc:
            show_error(self, "La descripcion no vale", exc.message)
            return

        icono = self._icono_pendiente
        if icono is not None and len(icono) > 0:
            try:
                appearance.validate_icon(icono)
            except ValidationError as exc:
                show_error(self, "La imagen no vale", exc.message)
                return

        if self._running and not confirm(
            self,
            "El servidor esta en marcha",
            "Minecraft lee la imagen y la descripcion al arrancar, y ademas vuelve a "
            "escribir su fichero de propiedades al detenerse: si el servidor esta en "
            "marcha, el cambio puede no verse o deshacerse al pararlo.\n\n"
            "Lo mas seguro es detener el servidor, guardar y volver a iniciarlo.\n\n"
            "¿Guardar de todas formas?",
            confirm_label="Guardar igualmente",
        ):
            return

        spec_id = self.spec.id

        def work(*, context):
            context.progress("Guardando el aspecto del servidor...")
            if icono is not None:
                if icono:
                    self.manager.save_icon(spec_id, icono)
                else:
                    self.manager.clear_icon(spec_id)
            return self.manager.save_motd(spec_id, valor)

        def done(_valor: str) -> None:
            self._icono = self.manager.server_icon(spec_id)
            self._icono_pendiente = None
            self._texto_original = valor
            self._pintar_icono()
            self._actualizar_boton_guardar()
            self.saved.emit()
            aviso = (
                "\n\nEl servidor esta en marcha: reinicialo para que se vea el cambio."
                if self._running
                else ""
            )
            show_info(
                self,
                "Aspecto guardado",
                "La lista de servidores ya ensena tu imagen y tu descripcion."
                + aviso
                + "\n\nPuedes verlo desde «Multijugador → Anadir servidor» en Minecraft.",
            )

        def failed(message: str, details: str) -> None:
            show_error(self, "No se pudo guardar el aspecto", message, details)

        self.runner.submit("Guardando el aspecto", work, on_finished=done, on_failed=failed)


def pixmap_icono(datos: bytes) -> QPixmap:
    """Icono listo para la ventana (nunca escalado con suavizado: pixel art)."""
    if not datos:
        return QPixmap()
    pixmap = QPixmap()
    if not pixmap.loadFromData(datos):
        return QPixmap()
    return pixmap.scaled(
        ICON_PREVIEW,
        ICON_PREVIEW,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


__all__ = ["AppearanceDialog", "MotdEdit", "ajustar_a_icono", "png_de_imagen", "png_de_pixmap"]
