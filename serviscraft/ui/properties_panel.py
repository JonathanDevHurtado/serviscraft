"""Editor de ``server.properties``.

La pestana se organiza como un pequeno taller de Minecraft: cuatro tarjetas
(tu servidor, como se juega, quien entra y el mundo), cada ajuste explicado con
palabras sencillas y mandos grandes. Las propiedades que gestiona la
aplicacion (puerto, RCON, IP) siguen bloqueadas para no romper el contenedor.

Los nombres tecnicos del fichero no desaparecen: cada campo los lleva en su
tooltip y la pestana «Todas las propiedades» sigue mostrando el fichero entero.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from ..core.properties import KNOWN_PROPERTIES, ServerProperties
from .common import (
    Chip,
    ElidedLabel,
    FlowRow,
    HelpButton,
    NumberBox,
    SectionCard,
    WrappingLabel,
    hint_label,
    make_button,
    polish_table_header,
)
from .dialogs import ask_text, confirm, show_error, show_info
from .mc_icons import (
    icono_ajustes,
    icono_candado,
    icono_cuadro,
    icono_escudo,
    icono_jugador,
    icono_lista,
    icono_mundo,
    icono_no,
    icono_si,
    item_icon,
)
from .tasks import TaskRunner

logger = get_logger("ui.properties")

#: Propiedades que se muestran en la pestana «Ajustes faciles», en este orden.
BASIC_KEYS: tuple[str, ...] = (
    "motd",
    "max-players",
    "difficulty",
    "gamemode",
    "pvp",
    "hardcore",
    "online-mode",
    "white-list",
    "enforce-whitelist",
    "level-name",
    "level-seed",
    "view-distance",
    "simulation-distance",
    "spawn-protection",
    "allow-flight",
    "enable-command-block",
    "allow-nether",
    "spawn-monsters",
    "spawn-animals",
    "spawn-npcs",
    "generate-structures",
    "enable-status",
    "force-gamemode",
    "player-idle-timeout",
    "op-permission-level",
    "function-permission-level",
)

#: Grupos de la pestana «Ajustes faciles».
BASIC_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Identidad del servidor", ("motd", "max-players", "difficulty", "gamemode", "enable-status")),
    ("Jugabilidad", ("pvp", "hardcore", "allow-flight", "enable-command-block", "force-gamemode", "player-idle-timeout")),
    ("Acceso", ("online-mode", "white-list", "enforce-whitelist", "op-permission-level", "function-permission-level")),
    (
        "Mundo",
        (
            "level-name",
            "level-seed",
            "view-distance",
            "simulation-distance",
            "spawn-protection",
            "allow-nether",
            "spawn-monsters",
            "spawn-animals",
            "spawn-npcs",
            "generate-structures",
        ),
    ),
)

#: Explicacion general del boton «?» de la cabecera.
_AYUDA_GENERAL = (
    "<b>Que hay en esta pestana</b><br>"
    "Las reglas de tu servidor, explicadas con palabras sencillas. Empieza por "
    "«Ajustes faciles»: las cuatro tarjetas reunen lo que mas se cambia.<br><br>"
    "<b>Como se guarda</b><br>"
    "Al pulsar «Guardar cambios» se escribe el fichero <i>server.properties</i> "
    "del servidor. Minecraft lo lee al arrancar, asi que reinicia el servidor "
    "para que los cambios se noten.<br><br>"
    "<b>Si algo no aparece</b><br>"
    "«Todas las propiedades» muestra el fichero completo y «Editor de texto» "
    "permite escribirlo a mano. Las claves del puerto, RCON y la IP las controla "
    "Serviscraft: aparecen bloqueadas para no romper la conexion.<br><br>"
    "<b>Consejo</b><br>"
    "Pasa el raton por encima de cualquier ajuste: el nombre tecnico y una "
    "explicacion mas larga aparecen en el aviso."
)

_AYUDA_IDENTIDAD = (
    "<b>Tu servidor</b><br>"
    "Aqui eliges como se llama, cuantos amigos caben y como empiezan a jugar. "
    "El mensaje de bienvenida es lo que aparece debajo del nombre en la lista de "
    "Minecraft.<br><br>"
    "Si no sabes que dificultad elegir, empieza por <b>Normal</b>. Para jugar con "
    "ninos pequeños, <b>Pacifico</b> evita los monstruos."
)

_AYUDA_JUEGO = (
    "<b>Como se juega</b><br>"
    "Estas son las reglas de la partida: si se pueden pelear, volar o usar "
    "bloques de comandos.<br><br>"
    "El <b>modo hardcore</b> es para valientes: si alguien muere, no puede volver "
    "a ese mundo. La <b>expulsion por inactividad</b> saca a quien lleva mucho "
    "tiempo quieto; 0 significa que nunca se expulsa a nadie."
)

_AYUDA_ACCESO = (
    "<b>Quien puede entrar</b><br>"
    "«Solo cuentas originales» comprueba que la cuenta de Minecraft sea de "
    "verdad. Es lo recomendable si el servidor esta abierto a internet.<br><br>"
    "La <b>lista blanca</b> solo deja entrar a los amigos que invites desde la "
    "pestana «Jugadores». Si activas «expulsar a los no invitados», quien no "
    "este en la lista sale del servidor.<br><br>"
    "Los niveles de operador y de funciones son para usuarios avanzados: 1 da "
    "permisos basicos y 4 da todos los comandos."
)

_AYUDA_MUNDO = (
    "<b>El mundo</b><br>"
    "Elige que mundo se abre y como se genera. La semilla es el codigo que crea "
    "el paisaje: si la dejas vacia, se elige una al azar.<br><br>"
    "Las distancias de vision y simulacion controlan cuanto mundo ve cada "
    "jugador y hasta donde pasan las cosas. Si el equipo va lento, bajalas un "
    "poco.<br><br>"
    "La proteccion del inicio impide romper bloques alrededor del punto de "
    "aparicion. El Nether, los monstruos, los animales y las estructuras se "
    "pueden activar o desactivar por separado."
)

#: Nombre visible, pista y color de cada tarjeta.
_GROUP_STYLE: dict[str, tuple[str, str, str, Callable[[], QPixmap], str]] = {
    "Identidad del servidor": (
        "green",
        "Tu servidor",
        "El nombre, el mensaje y como se ve en la lista.",
        lambda: icono_cuadro(20),
        _AYUDA_IDENTIDAD,
    ),
    "Jugabilidad": (
        "gold",
        "Como se juega",
        "Las reglas de la partida: peleas, vuelo y comandos.",
        lambda: item_icon("diamond_sword", 20),
        _AYUDA_JUEGO,
    ),
    "Acceso": (
        "blue",
        "Quien puede entrar",
        "Cuentas originales, lista blanca y permisos.",
        lambda: icono_escudo(20),
        _AYUDA_ACCESO,
    ),
    "Mundo": (
        "brown",
        "El mundo",
        "Como se genera y que aparece en el.",
        lambda: item_icon("grass_block", 20),
        _AYUDA_MUNDO,
    ),
}

#: Textos sencillos de cada ajuste. Si falta uno, se usa la descripcion tecnica.
_FIELD_TEXT: dict[str, tuple[str, str]] = {
    "motd": (
        "Mensaje de bienvenida",
        "Lo que tus amigos leen debajo del nombre del servidor en la lista de Minecraft.",
    ),
    "max-players": (
        "Cuantos pueden jugar a la vez",
        "El numero maximo de amigos dentro del servidor al mismo tiempo.",
    ),
    "difficulty": (
        "Dificultad",
        "Pacifico no tiene monstruos. Facil y Normal tienen peligro. Dificil hace mucho dano.",
    ),
    "gamemode": (
        "Como empiezan a jugar",
        "Supervivencia: recogen materiales. Creativo: vuelan y tienen todo. Aventura: siguen un mapa. Espectador: solo miran.",
    ),
    "pvp": (
        "Peleas entre amigos",
        "Si esta activado, los jugadores pueden hacerse dano entre ellos.",
    ),
    "hardcore": (
        "Modo hardcore",
        "Muy dificil: si un jugador muere, no puede volver a ese mundo.",
    ),
    "online-mode": (
        "Solo cuentas originales",
        "Comprueba que cada jugador tiene una cuenta de Minecraft de verdad. Si lo desactivas, pueden entrar cuentas sin licencia.",
    ),
    "white-list": (
        "Solo amigos invitados",
        "Solo pueden entrar los jugadores que esten en la lista blanca de la pestana Jugadores.",
    ),
    "enforce-whitelist": (
        "Expulsar a los no invitados",
        "Si alguien no esta en la lista blanca, se le saca del servidor.",
    ),
    "level-name": (
        "Mundo que se abre",
        "La carpeta del mundo que carga el servidor. Puedes elegir uno de tus mundos o escribir otro nombre.",
    ),
    "level-seed": (
        "Semilla del mundo",
        "El codigo con el que se genera el mundo. Dejala vacia para una semilla al azar.",
    ),
    "view-distance": (
        "Distancia de vision",
        "Cuanto mundo ve cada jugador. Mas distancia se ve mejor, pero gasta mas recursos.",
    ),
    "simulation-distance": (
        "Distancia de simulacion",
        "Hasta donde se mueven los animales, crecen las plantas y pasan las cosas.",
    ),
    "spawn-protection": (
        "Zona protegida del inicio",
        "Radio alrededor del punto de inicio donde nadie puede romper ni poner bloques. 0 quita la proteccion.",
    ),
    "allow-flight": (
        "Dejar volar",
        "Permite volar sin que el servidor expulse al jugador. Normalmente solo hace falta con mods.",
    ),
    "enable-command-block": (
        "Bloques de comandos",
        "Activa los bloques que ejecutan ordenes. Es util para minijuegos y mapas.",
    ),
    "allow-nether": (
        "Permitir el Nether",
        "Deja que los jugadores entren al Nether por el portal.",
    ),
    "spawn-monsters": (
        "Aparecen monstruos",
        "Genera zombis, esqueletos y otros monstruos por el mundo.",
    ),
    "spawn-animals": (
        "Aparecen animales",
        "Genera vacas, cerdos, ovejas y otros animales.",
    ),
    "spawn-npcs": (
        "Aparecen aldeanos",
        "Genera aldeanos y sus aldeas.",
    ),
    "generate-structures": (
        "Generar estructuras",
        "Crea aldeas, templos, fortalezas y otras construcciones al generar el mundo.",
    ),
    "enable-status": (
        "Aparecer en la lista",
        "Muestra el servidor en la lista de Minecraft para que tus amigos lo encuentren.",
    ),
    "force-gamemode": (
        "Mantener el modo de juego",
        "Vuelve a poner el modo elegido cada vez que alguien entra.",
    ),
    "player-idle-timeout": (
        "Expulsar si no se mueven",
        "Minutos que puede estar alguien quieto antes de salir. 0 significa nunca.",
    ),
    "op-permission-level": (
        "Poder de los operadores",
        "Del 1 al 4. 4 es el maximo: pueden usar todos los comandos.",
    ),
    "function-permission-level": (
        "Poder de las funciones",
        "Del 1 al 4. Controla que comandos pueden usar las funciones del mundo.",
    ),
}

#: Nombres faciles de las opciones que Minecraft guarda en ingles.
_ENUM_LABELS: dict[str, dict[str, str]] = {
    "difficulty": {
        "peaceful": "Pacifico",
        "easy": "Facil",
        "normal": "Normal",
        "hard": "Dificil",
    },
    "gamemode": {
        "survival": "Supervivencia",
        "creative": "Creativo",
        "adventure": "Aventura",
        "spectator": "Espectador",
    },
}

#: Limites y unidad visible de los numeros mas habituales.
_INT_CONFIG: dict[str, tuple[int, int, str]] = {
    "max-players": (1, 1000, " jugadores"),
    "view-distance": (2, 32, " chunks"),
    "simulation-distance": (2, 32, " chunks"),
    "spawn-protection": (0, 1000, " bloques"),
    "player-idle-timeout": (0, 1440, " min"),
    "op-permission-level": (1, 4, ""),
    "function-permission-level": (1, 4, ""),
}

#: Colores de las tarjetas. El borde y la franja lateral usan este tono.
_ACCENTS = {
    "green": "#3FA34D",
    "gold": "#C79A3A",
    "blue": "#3C8FBF",
    "brown": "#A8703F",
}


def _shorten(text: str, limit: int = 26) -> str:
    """Recorta un texto largo para que un chip no ensanche la ventana."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class _PropertiesHero(QFrame):
    """Cabecera verde con textura de bloques, dibujada sin imagenes externas."""

    _LADO_TEXTURA = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PropertiesHero")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(86)

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        marco = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        camino = QPainterPath()
        camino.addRoundedRect(marco, 3.0, 3.0)

        degradado = QLinearGradient(marco.topLeft(), marco.bottomRight())
        degradado.setColorAt(0.0, QColor("#3FA34D"))
        degradado.setColorAt(1.0, QColor("#2E7D3A"))
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

        # Franja de cesped en el borde inferior: el detalle que lo hace parecer
        # un bloque de Minecraft y no una simple cabecera plana.
        alto = 6
        suelo = int(marco.bottom()) - alto
        painter.fillRect(
            int(marco.left()), suelo, int(marco.width()) + 1, alto, QColor("#8a5a2b")
        )
        for x in range(int(marco.left()), int(marco.right()) + 1, 12):
            painter.fillRect(x, suelo, min(12, int(marco.right()) - x + 1), 2, QColor("#6cbb3c"))
        painter.restore()

        painter.setPen(QPen(QColor("#1b4d24"), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(camino)
        painter.end()


class _TexturedPage(QWidget):
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


class _FieldLabel(QWidget):
    """Nombre facill del ajuste y una pista corta debajo."""

    def __init__(self, title: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(1)

        self.name = WrappingLabel(title)
        self.name.setObjectName("PropertyName")
        self.name.setMinimumWidth(280)
        self.name.setMaximumWidth(420)
        caja.addWidget(self.name)

        self.hint = WrappingLabel(hint)
        self.hint.setObjectName("PropertyHint")
        self.hint.setMinimumWidth(280)
        self.hint.setMaximumWidth(420)
        self.hint.setVisible(bool(hint))
        caja.addWidget(self.hint)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)


class _PropertySwitch(QCheckBox):
    """Interruptor grande de dos estados, con aspecto de boton de Minecraft.

    Sigue siendo un ``QCheckBox``: conserva ``isChecked``, ``setChecked``, el
    teclado y la accesibilidad, pero se pinta como un boton con relieve para que
    se vea de un vistazo si una opcion esta activada.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PropertySwitch")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # El texto «Desactivado» necesita este ancho: si el formulario lo
        # comprime, se recorta la palabra y el boton deja de entenderse.
        self.setFixedWidth(134)
        self.setMinimumHeight(30)
        self.toggled.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        return QSize(134, 30)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        return self.sizeHint()

    def enterEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().leaveEvent(event)
        self.update()

    def focusInEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().focusOutEvent(event)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().mousePressEvent(event)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().mouseReleaseEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect().adjusted(0, 0, -1, -1)
        activo = self.isChecked()
        habilitado = self.isEnabled()

        if not habilitado:
            base = QColor("#70757a")
        elif activo:
            base = QColor("#3FA34D")
        else:
            base = QColor("#8b9095")
        if self.isDown():
            base = base.darker(118)
        elif self.underMouse():
            base = base.lighter(108)

        claro = base.lighter(135)
        oscuro = base.darker(145)
        painter.fillRect(rect, base)
        painter.fillRect(rect.left() + 1, rect.top() + 1, rect.width() - 2, 2, claro)
        painter.fillRect(rect.left() + 1, rect.top() + 1, 2, rect.height() - 2, claro)
        painter.fillRect(rect.left() + 1, rect.bottom() - 2, rect.width() - 2, 2, oscuro)
        painter.fillRect(rect.right() - 2, rect.top() + 1, 2, rect.height() - 2, oscuro)

        borde = QColor("#245c2c" if activo else "#4f555b")
        painter.setPen(QPen(borde, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(1, 1, -1, -1))

        fuente = self.font()
        fuente.setBold(True)
        painter.setFont(fuente)
        painter.setPen(QColor("#ffffff" if habilitado else "#d7dbde"))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter,
            "Activado" if activo else "Desactivado",
        )

        if self.hasFocus():
            painter.setPen(QPen(QColor("#f2c14e"), 1.0, Qt.PenStyle.DashLine))
            painter.drawRect(rect.adjusted(4, 4, -4, -4))
        painter.end()


class _PropertyCard(SectionCard):
    """Tarjeta de propiedades con borde de color y textura de piedra."""

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
        self.setObjectName("PropertyCard")
        self.setProperty("accent", accent)
        self._accent = QColor(_ACCENTS.get(accent, _ACCENTS["green"]))
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


class PropertiesPanel(QWidget):
    """Formulario y editor de texto para la configuracion del servidor."""

    saved = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PropertiesPanel")
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._widgets: dict[str, tuple[str, QWidget]] = {}
        self._snapshot: dict[str, str] = {}
        self._baseline_values: dict[str, str] = {}
        self._raw_loaded: str = ""
        self._loading = True
        self._table_dirty = False
        self._text_dirty = False
        self._props: ServerProperties = ServerProperties(path=Path("server.properties"))
        #: Formularios de las tarjetas; se apilan en ventanas estrechas.
        self._basic_forms: list[QFormLayout] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.hero = self._build_hero()
        layout.addWidget(self.hero)

        # Resumen de un vistazo: los datos que mas preguntan los jugadores.
        self.summary_row = FlowRow(spacing=8)
        self.summary_world = Chip("Mundo: ?", pixmap=icono_mundo(14))
        self.summary_mode = Chip("Modo: ?", pixmap=item_icon("diamond_sword", 14))
        self.summary_difficulty = Chip("Dificultad: ?", pixmap=item_icon("apple", 14))
        self.summary_players = Chip("Maximo: ?", pixmap=icono_jugador(14))
        for chip in (
            self.summary_world,
            self.summary_players,
            self.summary_mode,
            self.summary_difficulty,
        ):
            self.summary_row.add(chip)
        layout.addWidget(self.summary_row)

        self.status_row = FlowRow(spacing=8)
        self.dirty_chip = Chip(
            "Todo guardado",
            tone="ok",
            pixmap=icono_si(14),
            tooltip="No hay cambios pendientes en el formulario",
        )
        self.restart_chip = Chip(
            "Minecraft lo aplica al reiniciar",
            tone="info",
            tooltip="Guarda los cambios y reinicia el servidor para que Minecraft los lea",
        )
        self.status_row.add(self.dirty_chip)
        self.status_row.add(self.restart_chip)
        layout.addWidget(self.status_row)

        acciones = QHBoxLayout()
        acciones.setContentsMargins(0, 0, 0, 0)
        acciones.addStretch(1)
        self.properties_actions = FlowRow()
        self.reload_button = make_button(
            "Recargar",
            icon_names=("view-refresh",),
            tooltip="Vuelve a leer el fichero y descarta los cambios sin guardar",
        )
        self.reload_button.clicked.connect(self._reload)
        self.properties_actions.add(self.reload_button)

        self.save_button = make_button(
            "Guardar cambios",
            icon_names=("document-save",),
            accent=True,
            tooltip="Escribe los ajustes en server.properties",
        )
        self.save_button.clicked.connect(self._save)
        self.properties_actions.add(self.save_button)
        acciones.addWidget(self.properties_actions)
        layout.addLayout(acciones)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("PropertiesTabs")
        self.tabs.setUsesScrollButtons(True)
        self.tabs.addTab(self._build_basic_tab(), "Ajustes faciles")
        self.tabs.addTab(self._build_advanced_tab(), "Todas las propiedades")
        self.tabs.addTab(self._build_text_tab(), "Editor de texto")
        self.tabs.setTabToolTip(0, "Los ajustes mas habituales, explicados paso a paso")
        self.tabs.setTabToolTip(1, "Todas las claves del fichero server.properties")
        self.tabs.setTabToolTip(2, "Escribe el fichero a mano, si sabes lo que haces")
        # Cada pestana ya tiene su propia area desplazable. Dejar que Qt use el
        # alto minimo de la tabla obligaba a una segunda barra en la ventana.
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.tabs, 1)

        self.empty = QLabel("Selecciona un servidor para editar sus propiedades.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None)

    # ================================================================ cabecera
    def _build_hero(self) -> _PropertiesHero:
        hero = _PropertiesHero()
        fila = QHBoxLayout(hero)
        fila.setContentsMargins(16, 12, 14, 14)
        fila.setSpacing(12)

        icono = QLabel()
        icono.setObjectName("PropertiesHeroIcon")
        icono.setPixmap(icono_ajustes(48))
        icono.setFixedSize(50, 50)
        fila.addWidget(icono)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.title = ElidedLabel("Propiedades del servidor")
        self.title.setObjectName("PropertiesHeroTitle")
        # Algunos estilos nativos (Breeze) ignoran el color de la hoja de
        # estilos en etiquetas dentro de un QFrame; se fija tambien aqui.
        self.title.setStyleSheet("color: #ffffff;")
        textos.addWidget(self.title)

        self.hero_subtitle = WrappingLabel(
            "Cambia como se juega y quien puede entrar, sin complicaciones."
        )
        self.hero_subtitle.setObjectName("PropertiesHeroSubtitle")
        self.hero_subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.88);")
        textos.addWidget(self.hero_subtitle)
        fila.addLayout(textos, 1)

        self.hero_help = HelpButton(
            "Propiedades: como cambiar las reglas del servidor",
            _AYUDA_GENERAL,
            hero,
        )
        self.hero_help.setObjectName("PropertiesHeroHelp")
        fila.addWidget(self.hero_help, 0, Qt.AlignmentFlag.AlignTop)
        return hero

    # ================================================================ construccion
    def _build_basic_tab(self) -> QWidget:
        self.basic_scroll = QScrollArea()
        self.basic_scroll.setObjectName("PropertiesScroll")
        self.basic_scroll.setWidgetResizable(True)
        self.basic_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.basic_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.basic_scroll.viewport().setAutoFillBackground(False)

        pagina = _TexturedPage()
        pagina.setObjectName("PropertiesBasicPage")
        outer = QVBoxLayout(pagina)
        outer.setContentsMargins(4, 8, 10, 12)
        outer.setSpacing(12)

        contenido = QWidget()
        contenido.setObjectName("PropertiesBasicContent")
        contenido.setMaximumWidth(1040)
        contenido.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        columna = QVBoxLayout(contenido)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(12)
        self.basic_content = contenido

        for group_title, keys in BASIC_GROUPS:
            accent, title, hint, icono, ayuda = _GROUP_STYLE[group_title]
            tarjeta = _PropertyCard(
                title,
                pixmap=icono(),
                help_title=title,
                help_text=ayuda,
                accent=accent,
            )
            tarjeta.body().setSpacing(10)
            tarjeta.body().addWidget(hint_label(hint))

            form = QFormLayout()
            form.setContentsMargins(0, 2, 0, 0)
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(13)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            # En una ventana estrecha el campo pasa debajo del nombre en vez de
            # comprimir las dos columnas hasta recortar el texto.
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            self._basic_forms.append(form)

            for key in keys:
                meta = KNOWN_PROPERTIES.get(key)
                if meta is None:
                    continue
                texto, pista = _FIELD_TEXT.get(
                    key, (meta.label, meta.description or meta.label)
                )
                kind = "enum" if key == "level-name" else meta.kind
                widget = self._build_field(key, kind, meta.choices)
                tooltip = f"{key}\n{meta.description or meta.label}"
                widget.setToolTip(tooltip)
                if meta.managed:
                    widget.setEnabled(False)
                else:
                    self._connect_field(key, kind, widget)
                self._widgets[key] = (kind, widget)

                etiqueta = _FieldLabel(texto, pista)
                etiqueta.setToolTip(tooltip)
                form.addRow(etiqueta, widget)

            tarjeta.body().addLayout(form)
            columna.addWidget(tarjeta)

        columna.addWidget(
            hint_label(
                "Estas son las opciones mas habituales. Para el resto, usa "
                "«Todas las propiedades» o el «Editor de texto»."
            )
        )
        # Con stretch alto el contenido se queda casi todo el ancho; los dos
        # pequenos margenes elasticos solo reparten el sobrante cuando la
        # ventana supera el ancho comodo de la tarjeta.
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(0)
        fila.addStretch(1)
        fila.addWidget(contenido, 100)
        fila.addStretch(1)
        outer.addLayout(fila)
        outer.addStretch(1)
        self.basic_scroll.setWidget(pagina)
        return self.basic_scroll

    def _build_advanced_tab(self) -> QWidget:
        pagina = _TexturedPage()
        outer = QVBoxLayout(pagina)
        outer.setContentsMargins(4, 8, 10, 12)
        outer.setSpacing(8)

        tarjeta = _PropertyCard(
            "Todas las propiedades",
            pixmap=icono_lista(20),
            help_title="Todas las propiedades del fichero",
            help_text=(
                "<b>El fichero completo</b><br>"
                "Aqui aparece cada clave de <i>server.properties</i>. Puedes "
                "editar el valor haciendo doble clic y anadir claves nuevas con "
                "«Anadir propiedad».<br><br>"
                "Las filas con candado las gestiona Serviscraft (puerto, RCON e "
                "IP): se muestran para que las veas, pero no se pueden cambiar "
                "desde aqui."
            ),
            accent="blue",
        )
        cuerpo = tarjeta.body()
        cuerpo.setSpacing(8)
        cuerpo.addWidget(
            hint_label(
                "Todas las claves del fichero. Busca una o filtra por su nombre; "
                "las propiedades con candado las controla Serviscraft."
            )
        )

        self.search = QLineEdit()
        self.search.setObjectName("PropertiesSearch")
        self.search.setPlaceholderText("Buscar una propiedad (por ejemplo: pvp)")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(QIcon(icono_lista(14)), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter_table)
        cuerpo.addWidget(self.search)

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("PropertiesTable")
        self.table.setHorizontalHeaderLabels(["Propiedad", "Valor", "Serviscraft"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._on_table_changed)
        polish_table_header(self.table)
        cuerpo.addWidget(self.table, 1)

        botones = FlowRow(spacing=8)
        add_button = make_button("Anadir propiedad", icon_names=("list-add",))
        add_button.clicked.connect(self._add_row)
        botones.add(add_button)
        remove_button = make_button("Quitar seleccionada", icon_names=("list-remove",))
        remove_button.clicked.connect(self._remove_selected)
        botones.add(remove_button)
        cuerpo.addWidget(botones)

        outer.addWidget(tarjeta, 1)
        return pagina

    def _build_text_tab(self) -> QWidget:
        pagina = _TexturedPage()
        outer = QVBoxLayout(pagina)
        outer.setContentsMargins(4, 8, 10, 12)
        outer.setSpacing(8)

        tarjeta = _PropertyCard(
            "Editor de texto",
            pixmap=item_icon("book", 20),
            help_title="Editor directo de server.properties",
            help_text=(
                "<b>Para usuarios avanzados</b><br>"
                "Aqui se escribe el fichero tal cual. Cada linea es una clave y "
                "su valor, por ejemplo <i>pvp=true</i>. Los comentarios que "
                "empiezan por # se conservan.<br><br>"
                "Si escribes una clave que gestiona Serviscraft (puerto, RCON o "
                "IP), se corrige automaticamente al guardar."
            ),
            accent="brown",
        )
        cuerpo = tarjeta.body()
        cuerpo.setSpacing(8)
        cuerpo.addWidget(
            hint_label(
                "Editor directo del fichero. Si escribes una clave que gestiona "
                "Serviscraft, se corrige al guardar."
            )
        )
        self.text_editor = QPlainTextEdit()
        self.text_editor.setObjectName("PropertiesTextEditor")
        self.text_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_editor.textChanged.connect(self._on_text_changed)
        cuerpo.addWidget(self.text_editor, 1)
        outer.addWidget(tarjeta, 1)
        return pagina

    def _build_field(self, key: str, kind: str, choices: tuple[str, ...]) -> QWidget:
        if kind == "bool":
            boton = _PropertySwitch()
            boton.setAccessibleName(_FIELD_TEXT.get(key, (key, ""))[0])
            return boton
        if kind == "int":
            spin = NumberBox()
            minimo, maximo, sufijo = _INT_CONFIG.get(key, (-1, 100_000_000, ""))
            spin.setRange(minimo, maximo)
            if sufijo:
                spin.setSuffix(sufijo)
            if key == "player-idle-timeout":
                spin.setSpecialValueText("Nunca")
            spin.setMinimumWidth(170)
            spin.setMaximumWidth(620)
            return spin
        if kind == "enum":
            combo = QComboBox()
            if key == "level-name":
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            etiquetas = _ENUM_LABELS.get(key, {})
            for valor in choices:
                combo.addItem(etiquetas.get(valor, valor), valor)
            combo.setMinimumWidth(190)
            combo.setMaximumWidth(620)
            return combo

        edit = QLineEdit()
        edit.setClearButtonEnabled(key in {"motd", "level-seed", "level-name"})
        if key == "motd":
            edit.setPlaceholderText("Bienvenidos al servidor")
        elif key == "level-seed":
            edit.setPlaceholderText("Dejala vacia para una semilla al azar")
        edit.setMinimumWidth(190)
        edit.setMaximumWidth(620)
        return edit

    # ================================================================= API
    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        """Alto minimo util: la cabecera, los avisos y una zona de pestanas.

        El area desplazable de la ventana pregunta este alto para decidir si
        hace falta barra. Sin un minimo propio, Qt usaba el alto de la tabla y
        aparecian dos barras verticales (la de la ventana y la del panel).
        """
        hint = super().minimumSizeHint()
        return QSize(hint.width(), max(hint.height(), 430))

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self._adaptar_formularios()

    def _adaptar_formularios(self) -> None:
        """Apila nombre y campo cuando la pestana es demasiado estrecha.

        Con poco ancho, mezclar filas en dos columnas y filas apiladas deja un
        formulario dificil de seguir. Por debajo del umbral se ponen todas las
        filas iguales: el nombre arriba y el mando debajo, a todo el ancho.
        """
        politica = (
            QFormLayout.RowWrapPolicy.WrapAllRows
            if self.width() < 620
            else QFormLayout.RowWrapPolicy.WrapLongRows
        )
        for form in getattr(self, "_basic_forms", ()):
            if form.rowWrapPolicy() != politica:
                form.setRowWrapPolicy(politica)

    def set_server(self, spec: ServerSpec | None) -> None:
        # Solo se relee el fichero al cambiar de servidor: si se hiciera en cada
        # refresco periodico se perderian los cambios que el usuario este
        # escribiendo en el formulario.
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        self._spec = spec
        has_server = spec is not None
        self.tabs.setVisible(has_server)
        self.empty.setVisible(not has_server)
        self.save_button.setEnabled(has_server)
        self.reload_button.setEnabled(has_server)
        self.summary_row.setVisible(has_server)
        self.status_row.setVisible(has_server)
        self.properties_actions.setVisible(has_server)
        if has_server:
            self.title.setText(f"Propiedades de «{spec.name}»")
            self.hero_subtitle.setText(
                "Cambia como se juega y quien puede entrar, sin complicaciones."
            )
            if cambio:
                self.load(spec)
        else:
            self.title.setText("Propiedades del servidor")
            self.hero_subtitle.setText(
                "Selecciona un servidor a la izquierda para cambiar sus reglas."
            )

    def load(self, spec: ServerSpec | None) -> None:
        """Lee el fichero del disco y rellena el formulario."""
        if spec is None:
            return
        try:
            props = self.manager.properties(spec.id)
        except ServiscraftError as exc:
            show_error(self, "No se pudo leer la configuracion", str(exc))
            return
        self._props = props
        self._snapshot = props.as_dict()
        self._raw_loaded = props.to_text()
        self._loading = True
        self._table_dirty = False
        self._text_dirty = False
        self._fill_table(props)
        self._fill_basic(props)
        self.text_editor.setPlainText(self._raw_loaded)
        # La linea base se toma de lo que muestran los controles (con los
        # valores por defecto ya aplicados): asi un fichero recien creado no
        # aparece como «cambios sin guardar» nada mas abrirlo.
        self._baseline_values = self.current_values()
        self._loading = False
        self._update_summary()
        self._refresh_status()
        self.raw_editor_shown()

    def raw_editor_shown(self) -> None:
        """Hook para quien quiera saber que se recargo el texto."""

    def current_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, (kind, widget) in self._widgets.items():
            if kind == "bool":
                values[key] = "true" if widget.isChecked() else "false"  # type: ignore[attr-defined]
            elif kind == "int":
                values[key] = str(widget.value())  # type: ignore[attr-defined]
            elif kind == "enum":
                values[key] = self._combo_value(key, widget)  # type: ignore[arg-type]
            else:
                values[key] = widget.text()  # type: ignore[attr-defined]
        return values

    @staticmethod
    def _combo_value(key: str, widget: QComboBox) -> str:
        """Valor real de un desplegable, aunque la etiqueta sea en espanol."""
        if key == "level-name":
            return widget.currentText().strip()
        data = widget.currentData()
        return str(data) if data is not None else widget.currentText()

    # ================================================================= relleno
    def _connect_field(self, key: str, kind: str, widget: QWidget) -> None:
        """Escritura directa: el formulario y la tabla comparten un unico modelo."""
        if kind == "bool":
            widget.toggled.connect(lambda _checked, k=key: self._sync_field(k))  # type: ignore[attr-defined]
        elif kind == "int":
            widget.valueChanged.connect(lambda _value, k=key: self._sync_field(k))  # type: ignore[attr-defined]
        elif kind == "enum":
            widget.currentTextChanged.connect(lambda _text, k=key: self._sync_field(k))  # type: ignore[attr-defined]
        else:
            widget.textChanged.connect(lambda _text, k=key: self._sync_field(k))  # type: ignore[attr-defined]

    def _field_value(self, key: str) -> str:
        kind, widget = self._widgets[key]
        if kind == "bool":
            return "true" if widget.isChecked() else "false"  # type: ignore[attr-defined]
        if kind == "int":
            return str(widget.value())  # type: ignore[attr-defined]
        if kind == "enum":
            return self._combo_value(key, widget)  # type: ignore[arg-type]
        return widget.text()  # type: ignore[attr-defined]

    def _sync_field(self, key: str) -> None:
        if key not in self._widgets or self._loading:
            return
        self._set_table_value(key, self._field_value(key))
        self._update_summary()
        self._refresh_status()

    def _set_table_value(self, key: str, value: str) -> None:
        bloqueo = QSignalBlocker(self.table)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None and item.text() == key:
                    value_item = self.table.item(row, 1)
                    if value_item is not None and value_item.text() != value:
                        value_item.setText(value)
                    return
            self._append_row(key, value)
        finally:
            del bloqueo

    def _fill_basic(self, props: ServerProperties) -> None:
        worlds = self._available_worlds()
        for key, (kind, widget) in self._widgets.items():
            meta = KNOWN_PROPERTIES.get(key)
            default = meta.default if meta else ""
            raw = props.get(key, default)
            if kind == "bool":
                widget.setChecked(str(raw).strip().lower() in {"true", "1", "yes", "on"})  # type: ignore[attr-defined]
            elif kind == "int":
                try:
                    widget.setValue(int(str(raw).strip()))  # type: ignore[attr-defined]
                except ValueError:
                    widget.setValue(int(default or 0))  # type: ignore[attr-defined]
            elif kind == "enum":
                if key == "level-name" and worlds:
                    widget.blockSignals(True)  # type: ignore[attr-defined]
                    widget.clear()  # type: ignore[attr-defined]
                    for mundo in worlds:
                        widget.addItem(mundo, mundo)  # type: ignore[attr-defined]
                    widget.blockSignals(False)  # type: ignore[attr-defined]
                    if raw not in worlds:
                        widget.addItem(str(raw), str(raw))  # type: ignore[attr-defined]
                index = widget.findData(str(raw))  # type: ignore[attr-defined]
                if index < 0:
                    index = widget.findText(str(raw))  # type: ignore[attr-defined]
                if index >= 0:
                    widget.setCurrentIndex(index)  # type: ignore[attr-defined]
                elif widget.isEditable():  # type: ignore[attr-defined]
                    widget.setEditText(str(raw))  # type: ignore[attr-defined]
            else:
                widget.setText(str(raw))  # type: ignore[attr-defined]
                # Al escribir el texto, el cursor queda al final y el campo
                # aparece desplazado (se veia «venidos al Reino»). Se deja al
                # principio para que se lea el valor completo desde el inicio.
                widget.setCursorPosition(0)  # type: ignore[attr-defined]

    def _available_worlds(self) -> list[str]:
        if self._spec is None:
            return []
        try:
            worlds = [w.name for w in self.manager.files(self._spec.id).list_worlds()]
        except ServiscraftError:
            return []
        active = self._spec and self._props.get("level-name", "world")
        if active and active not in worlds:
            worlds.insert(0, active)
        return worlds

    def _fill_table(self, props: ServerProperties) -> None:
        values = props.as_dict()
        self.table.setRowCount(0)
        for key, value in values.items():
            self._append_row(key, value)

    def _append_row(self, key: str = "", value: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(key))
        self.table.setItem(row, 1, QTableWidgetItem(value))
        flag = QTableWidgetItem("")
        flag.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 2, flag)
        self._set_row_managed(
            row,
            bool(KNOWN_PROPERTIES.get(key) and KNOWN_PROPERTIES[key].managed),
        )

    def _set_row_managed(self, row: int, managed: bool) -> None:
        key_item = self.table.item(row, 0)
        value_item = self.table.item(row, 1)
        if value_item is None:
            return
        if managed:
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if key_item is not None:
                key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            flag = QTableWidgetItem(QIcon(icono_candado(14)), "Protegida")
            flag.setToolTip("Esta propiedad la gestiona Serviscraft")
            value_item.setForeground(
                self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            )
            value_item.setToolTip("Lo gestiona Serviscraft; no se puede cambiar desde aqui")
        else:
            value_item.setFlags(value_item.flags() | Qt.ItemFlag.ItemIsEditable)
            if key_item is not None:
                key_item.setFlags(key_item.flags() | Qt.ItemFlag.ItemIsEditable)
            flag = QTableWidgetItem("")
            value_item.setToolTip("")
        flag.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 2, flag)

    # ================================================================= filtros
    def _filter_table(self, text: str) -> None:
        aguja = text.strip().lower()
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            contenido = " ".join(
                item.text() for item in (key_item, value_item) if item is not None
            ).lower()
            self.table.setRowHidden(row, bool(aguja) and aguja not in contenido)

    def _on_table_changed(self, _item: QTableWidgetItem) -> None:
        if self._loading:
            return
        self._table_dirty = True
        self._refresh_status()

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        self._text_dirty = True
        self._refresh_status()

    # ================================================================= resumen
    def _update_summary(self) -> None:
        if not self._widgets:
            return
        mundo = self._field_value("level-name") or "world"
        modo = self._display_text("gamemode")
        dificultad = self._display_text("difficulty")
        try:
            jugadores = self._field_value("max-players")
        except KeyError:
            jugadores = "?"

        self.summary_world.set_text(f"Mundo: {_shorten(mundo)}")
        self.summary_world.setToolTip(f"Mundo que se abre: {mundo}")
        self.summary_mode.set_text(f"Modo: {_shorten(modo)}")
        self.summary_mode.setToolTip(f"Modo de juego inicial: {modo}")
        self.summary_difficulty.set_text(f"Dificultad: {_shorten(dificultad)}")
        self.summary_difficulty.setToolTip(f"Dificultad del mundo: {dificultad}")
        self.summary_players.set_text(f"Maximo: {jugadores}")
        self.summary_players.setToolTip(f"Jugadores maximos a la vez: {jugadores}")

    def _display_text(self, key: str) -> str:
        entry = self._widgets.get(key)
        if entry is None:
            return "?"
        kind, widget = entry
        if kind == "enum":
            return widget.currentText()  # type: ignore[attr-defined]
        if kind == "bool":
            return "Activado" if widget.isChecked() else "Desactivado"  # type: ignore[attr-defined]
        if kind == "int":
            return str(widget.value())  # type: ignore[attr-defined]
        return widget.text()  # type: ignore[attr-defined]

    def _refresh_status(self) -> None:
        if self._spec is None:
            return
        dirty = self.is_dirty()
        if dirty:
            self.dirty_chip.set_text("Cambios sin guardar")
            self.dirty_chip.set_tone("warn")
            self.dirty_chip.set_pixmap(icono_no(14))
            self.dirty_chip.setToolTip(
                "Todavia no se han escrito los cambios en server.properties"
            )
        else:
            self.dirty_chip.set_text("Todo guardado")
            self.dirty_chip.set_tone("ok")
            self.dirty_chip.set_pixmap(icono_si(14))
            self.dirty_chip.setToolTip("No hay cambios pendientes")

    # ================================================================= acciones
    def _reload(self) -> None:
        if self._spec is None:
            return
        if self.is_dirty() and not confirm(
            self,
            "Descartar los cambios",
            "Se volvera a leer el fichero y se perderan los cambios que no hayas "
            "guardado.\n\nEl servidor, el mundo y los mods no se tocan.",
            confirm_label="Descartar",
            destructive=True,
        ):
            return
        self.load(self._spec)

    def _add_row(self) -> None:
        key = ask_text(self, "Nueva propiedad", "Nombre de la propiedad:", placeholder="por ejemplo: allow-flight")
        if not key:
            return
        key = key.strip()
        if not key:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == key:
                self.table.setCurrentCell(row, 1)
                return
        self._append_row(key, "")
        self.table.setCurrentCell(self.table.rowCount() - 1, 1)

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        key = item.text() if item else ""
        if KNOWN_PROPERTIES.get(key) and KNOWN_PROPERTIES[key].managed:
            show_error(self, "Propiedad protegida", "Esta propiedad la gestiona Serviscraft y no se puede quitar.")
            return
        self.table.removeRow(row)
        self._table_dirty = True
        self._refresh_status()

    # ================================================================= guardar
    def _save(self) -> None:
        if self._spec is None:
            return
        if self._text_dirty and self.tabs.currentIndex() != 2:
            if not confirm(
                self,
                "Cambios en el editor de texto",
                "El editor de texto tiene cambios sin guardar. Si guardas desde "
                "otra pestana, se perderan.\n\n¿Guardar de todas formas?",
                confirm_label="Guardar",
                destructive=True,
            ):
                return
        spec = self._spec
        props = self._current_properties()
        try:
            self.manager.save_properties(spec.id, props)
        except ServiscraftError as exc:
            show_error(self, "No se pudieron guardar las propiedades", str(exc))
            return
        logger.info("Propiedades de %s guardadas desde la interfaz", spec.id)
        self.load(spec)
        self.saved.emit()
        show_info(
            self,
            "Propiedades guardadas",
            "Los cambios se han guardado.\n\n"
            "Reinicia el servidor para que Minecraft los aplique.",
        )

    def _current_properties(self) -> ServerProperties:
        """Construye las propiedades a partir de la vista activa."""
        if self.tabs.currentIndex() == 2:
            # Editor de texto: se usa tal cual lo ha escrito el usuario.
            return ServerProperties.from_text(self._props.path, self.text_editor.toPlainText())

        props = ServerProperties(path=self._props.path, entries=[])
        # Conservamos los comentarios del fichero original para no perderlos.
        for entry in self._props.entries:
            if entry.kind == "comment":
                props.entries.append(entry)
        for key, value in self._table_values(exclude_managed=False).items():
            props.set(key, value)
        return props

    def _table_values(self, *, exclude_managed: bool) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if key_item is None or value_item is None:
                continue
            key = key_item.text().strip()
            if not key:
                continue
            meta = KNOWN_PROPERTIES.get(key)
            if exclude_managed and meta and meta.managed:
                continue
            values[key] = value_item.text()
        return values

    # ================================================================== avisos
    def is_dirty(self) -> bool:
        if self._spec is None:
            return False
        if self.current_values() != self._baseline_values:
            return True
        return self._table_dirty or self._text_dirty

    def confirm_discard(self) -> bool:
        if not self.is_dirty():
            return True
        return confirm(
            self,
            "Cambios sin guardar",
            "Hay cambios sin guardar en las propiedades. ¿Descartarlos?",
            confirm_label="Descartar",
            destructive=True,
        )
