"""Ventana del inventario de un jugador, con la forma de la mochila de Minecraft.

Se abre desde la pestana **Jugadores**. Ensenar los objetos en la misma
disposicion que los ve el jugador (tres filas de inventario, la armadura, la mano
secundaria y la barra rapida abajo) hace que se entienda de un vistazo, sin
explicar nada: es la pantalla que ya conoce cualquiera que haya jugado.

Los objetos se pintan con su textura. La primera vez se descargan (una sola vez,
unos pocos KB) y se guardan en la cache; mientras llegan, o si no hay conexion,
se dibuja un icono propio con la forma y el color del material. A la derecha se
ve la **skin** del jugador, sacada de su cara y su cuerpo.

Los datos vienen del servidor (``data get entity``); aqui solo se pintan. Si el
inventario no cupo en una sola respuesta, se avisa en vez de mentir.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.inventory import ItemStack, PlayerInventory, slot_label
from ..core.textures import cached_item_texture, cached_skin, fetch_item_texture, fetch_skin
from .common import Chip, ElidedLabel, FlowRow, HelpButton, WrappingLabel, escape_text
from .mc_icons import icono_jugador, icono_mochila, item_icon, texture_pixmap
from .skin_view import body_pixmap, head_pixmap
from .tasks import TaskRunner

#: Tamano de cada hueco, en pixeles. Con nueve columnas la mochila se ve igual
#: que en el juego y el nombre del objeto cabe en dos lineas.
SLOT_WIDTH = 64
SLOT_HEIGHT = 60
#: Lado del icono dentro del hueco.
ICON_SIZE = 26
#: Alto del muneco con la skin.
SKIN_HEIGHT = 104

#: Explicacion del boton «?» de la ventana.
_AYUDA = (
    "Aqui se ve lo que lleva encima un jugador <b>en este momento</b>."
    "<br><br>· Las <b>tres filas de arriba</b> son su inventario."
    "<br>· La fila de la <b>armadura</b>: casco, peto, pantalones y botas; a la "
    "derecha, lo que lleva en la mano secundaria."
    "<br>· La <b>barra rapida</b> de abajo son los nueve objetos que elige con "
    "las teclas 1-9."
    "<br><br>Cada objeto lleva su <b>textura</b>. La primera vez se descargan de "
    "un espejo publico y se guardan en el equipo (son muy ligeras); sin conexion "
    "se dibuja un icono del mismo color y forma."
    "<br><br>A la derecha se ve la <b>skin</b> del jugador con la ropa que lleva "
    "puesta. Si el servidor no tiene skins (sin conexion o sin cuenta), se muestra "
    "un jugador generico."
    "<br><br>Los numeros amarillos dicen cuantos objetos hay en ese hueco. Para "
    "ver mas detalles de uno, deja el raton encima."
    "<br><br>Serviscraft pregunta estos datos al servidor por su consola: no "
    "modifica el inventario ni el mundo."
)


class _SlotBox(QFrame):
    """Un hueco de la mochila: textura, nombre del objeto y cuantos hay."""

    def __init__(self, item: ItemStack | None, *, hueco: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InventorySlot")
        self.setFixedSize(SLOT_WIDTH, SLOT_HEIGHT)
        self.item = item
        self._textura_manual = False

        layout = QGridLayout(self)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(0)

        self.icon = QLabel()
        self.icon.setObjectName("SlotIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon, 0, 0)

        if item is None:
            self.icon.clear()
            self.setToolTip(f"{hueco}: vacio")
            layout.setRowStretch(0, 1)
            return

        detalle = [item.name, hueco]
        if item.count > 1:
            detalle.append(f"{item.count} objetos")
        self.setToolTip(
            "<br>".join(escape_text(parte) for parte in (*detalle, item.item_id))
        )

        if item.count > 1:
            cantidad = QLabel(f"x{item.count}")
            cantidad.setObjectName("SlotCount")
            cantidad.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(cantidad, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.icon.setPixmap(item_icon(item.item_id, ICON_SIZE))

        nombre = WrappingLabel(item.name)
        nombre.setObjectName("SlotName")
        nombre.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(nombre, 1, 0)
        layout.setRowStretch(0, 1)

    def set_texture(self, datos: bytes) -> None:
        """Pone la textura de verdad (cuando termina la descarga)."""
        if self.item is None or self._textura_manual:
            return
        pixmap = texture_pixmap(datos, ICON_SIZE)
        if pixmap.isNull():
            return
        self._textura_manual = True
        self.icon.setPixmap(pixmap)


class InventoryDialog(QDialog):
    """Mochila, armadura y estado de un jugador conectado."""

    def __init__(
        self,
        inventory: PlayerInventory,
        *,
        on_refresh: Callable[[], None] | None = None,
        runner: TaskRunner | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Inventario de {inventory.player}")
        self.setModal(False)
        self.setMinimumSize(480, 420)
        self.resize(720, 620)

        self._on_refresh = on_refresh
        self.runner = runner
        self._inventory = inventory
        self._boxes: list[_SlotBox] = []
        self._texturas: dict[str, bytes] = {}
        self._skin_bytes: bytes = b""
        self._descargando = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        # ------------------------------------------------------------- cabecera
        head = QHBoxLayout()
        head.setSpacing(10)
        self.portrait = QLabel()
        self.portrait.setPixmap(icono_jugador(36))
        self.portrait.setToolTip("Cara del jugador")
        head.addWidget(self.portrait)
        self.title = ElidedLabel("")
        self.title.setObjectName("HelpTitle")
        head.addWidget(self.title, 1)
        head.addWidget(HelpButton("Inventario del jugador", _AYUDA, self))
        layout.addLayout(head)

        self.chips = FlowRow(spacing=8)
        self.chip_health = Chip("", tone="bad")
        self.chip_food = Chip("", tone="warn")
        self.chip_level = Chip("", tone="info")
        self.chip_items = Chip("", pixmap=icono_mochila(14))
        for chip in (self.chip_health, self.chip_food, self.chip_level, self.chip_items):
            self.chips.add(chip)
        layout.addWidget(self.chips)

        # --------------------------------------------------------------- huecos
        # La rejilla no se estira: los huecos tienen el tamano del juego. Si la
        # ventana es mas ancha, sobra espacio a la derecha; si es mas estrecha,
        # la zona se desplaza (nunca se encogen los huecos).
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        self.grid_host.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum
        )

        # La skin, pegada a la derecha de la mochila.
        self.skin_panel = QWidget()
        skin_panel = QVBoxLayout(self.skin_panel)
        skin_panel.setContentsMargins(0, 0, 0, 0)
        skin_panel.setSpacing(4)
        self.skin_label = QLabel()
        self.skin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.skin_label.setFixedWidth(56)
        self.skin_label.setPixmap(body_pixmap(b"", SKIN_HEIGHT))
        skin_panel.addWidget(self.skin_label)
        self.skin_caption = ElidedLabel("Skin")
        self.skin_caption.setObjectName("SlotTitle")
        self.skin_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.skin_caption.setFixedWidth(56)
        self.skin_caption.setToolTip("Skin del jugador")
        skin_panel.addWidget(self.skin_caption)
        skin_panel.addStretch(1)
        self.skin_panel.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum
        )

        self.contenido = QWidget()
        contenido_layout = QHBoxLayout(self.contenido)
        contenido_layout.setContentsMargins(0, 0, 0, 0)
        contenido_layout.setSpacing(10)
        contenido_layout.addWidget(self.grid_host)
        contenido_layout.addWidget(self.skin_panel)
        contenido_layout.addStretch(1)
        self.contenido.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum
        )

        self.scroll = QScrollArea()
        self.scroll.setObjectName("InventoryGrid")
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.contenido)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(10)
        cuerpo.addWidget(self.scroll, 1)
        layout.addLayout(cuerpo, 1)

        self.note = WrappingLabel("")
        self.note.setObjectName("Hint")
        layout.addWidget(self.note)

        buttons = QDialogButtonBox()
        if on_refresh is not None:
            actualizar = buttons.addButton("Actualizar", QDialogButtonBox.ButtonRole.ActionRole)
            actualizar.setToolTip("Volver a preguntar al servidor que lleva ahora mismo")
            actualizar.clicked.connect(self._refresh)
        cerrar = buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.RejectRole)
        cerrar.setDefault(True)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.set_inventory(inventory)

    # ================================================================= API
    def _refresh(self) -> None:
        if self._on_refresh is not None:
            self._on_refresh()

    def set_inventory(self, inventory: PlayerInventory) -> None:
        """Repinta la ventana con datos nuevos (sin cerrarla)."""
        self._inventory = inventory
        self.title.setText(f"Inventario de «{inventory.player}»")
        self.chip_health.set_text(self._vida(inventory))
        self.chip_health.set_tone("ok" if (inventory.health or 0) > 6 else "bad")
        self.chip_food.set_text(f"Comida: {int(inventory.food)}" if inventory.food is not None else "Comida: ?")
        self.chip_level.set_text(f"Nivel {int(inventory.level)}" if inventory.level is not None else "Nivel ?")
        self.chip_items.set_text(
            f"{inventory.total_items} objetos en {inventory.stacks} huecos"
        )
        self.note.setText(inventory.note)
        self.note.setVisible(bool(inventory.note))
        self._rellenar(inventory)
        self._actualizar_skin()
        self._pedir_texturas(inventory)

    @staticmethod
    def _vida(inventory: PlayerInventory) -> str:
        if inventory.health is None:
            return "Vida: ?"
        return f"Vida: {int(round(inventory.health))} de 20"

    def _rellenar(self, inventory: PlayerInventory) -> None:
        while self.grid.count():
            elemento = self.grid.takeAt(0)
            widget = elemento.widget() if elemento is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._boxes = []

        # Tres filas de inventario (huecos 9 a 35), como en el juego.
        for fila in range(3):
            for columna in range(9):
                hueco = 9 + fila * 9 + columna
                self._poner(self.grid, fila, columna, inventory, hueco)

        # Armadura y mano secundaria, con su titulo.
        titulo = QLabel("Armadura y mano secundaria")
        titulo.setObjectName("SlotTitle")
        self.grid.addWidget(titulo, 3, 0, 1, 9)

        for columna, hueco in enumerate((103, 102, 101, 100)):
            self._poner(self.grid, 4, columna, inventory, hueco)
        self._poner(self.grid, 4, 8, inventory, -106)

        # La barra rapida, abajo (las teclas 1-9).
        titulo_rapida = QLabel("Barra rapida (teclas 1-9)")
        titulo_rapida.setObjectName("SlotTitle")
        self.grid.addWidget(titulo_rapida, 5, 0, 1, 9)
        for columna in range(9):
            self._poner(self.grid, 6, columna, inventory, columna)

        self.grid_host.adjustSize()

    def _poner(
        self, grid: QGridLayout, fila: int, columna: int, inventory: PlayerInventory, hueco: int
    ) -> None:
        item = inventory.at(hueco)
        etiqueta = item.slot_label if item is not None else _hueco_de(hueco)
        caja = _SlotBox(item, hueco=etiqueta)
        if item is not None:
            guardada = cached_item_texture(item.item_id)
            if guardada is not None:
                caja.set_texture(guardada)
        self._boxes.append(caja)
        grid.addWidget(caja, fila, columna)

    # ================================================================ skin
    def _actualizar_skin(self) -> None:
        player = self._inventory.player
        datos = self._skin_bytes or cached_skin(player)
        if datos:
            self._skin_bytes = datos
            self.portrait.setPixmap(head_pixmap(datos, 36))
            self.skin_label.setPixmap(body_pixmap(datos, SKIN_HEIGHT))
            self.skin_caption.setText(f"Skin de {player}")
            self.skin_caption.setToolTip(f"Skin de {player} (descargada de mc-heads.net)")
        else:
            self.portrait.setPixmap(icono_jugador(36))
            self.skin_label.setPixmap(body_pixmap(b"", SKIN_HEIGHT))
            self.skin_caption.setText("Sin skin")
            self.skin_caption.setToolTip(
                "No se pudo descargar la skin: se muestra un jugador generico."
            )

    # ========================================================== descargas
    def _pedir_texturas(self, inventory: PlayerInventory) -> None:
        """Descarga (en segundo plano) las texturas que falten y la skin."""
        if self._descargando:
            return
        ids = {item.item_id for item in inventory.items}
        faltan = [item_id for item_id in ids if not self._texturas.get(item_id) and not cached_item_texture(item_id)]
        falta_skin = not self._skin_bytes and not cached_skin(inventory.player)
        if not faltan and not falta_skin:
            return
        if self.runner is None:
            return
        self._descargando = True
        player = inventory.player

        def work(*, context):
            texturas: dict[str, bytes] = {}
            for item_id in faltan:
                if context.cancelled:
                    break
                datos = fetch_item_texture(item_id)
                if datos is not None:
                    texturas[item_id] = datos
            skin = b""
            if falta_skin and not context.cancelled:
                skin = fetch_skin(player) or b""
            return texturas, skin

        def done(result) -> None:
            self._descargando = False
            texturas, skin = result
            if texturas:
                self._texturas.update(texturas)
                for caja in self._boxes:
                    if caja.item is not None and caja.item.item_id in texturas:
                        caja.set_texture(texturas[caja.item.item_id])
            if skin:
                self._skin_bytes = skin
                # El jugador puede haber cambiado si el dialogo se reutiliza.
                if self._inventory.player == player:
                    self._actualizar_skin()

        def failed(message: str, details: str) -> None:
            # Sin conexion no se avisa: los iconos dibujados ya se ven bien.
            self._descargando = False

        self.runner.submit(
            "Descargando texturas del inventario",
            work,
            on_finished=done,
            on_failed=failed,
            track_busy=False,
        )


def _hueco_de(hueco: int) -> str:
    """Nombre del hueco de un objeto vacio (para el tooltip)."""
    return slot_label(hueco)


__all__ = ["InventoryDialog"]
