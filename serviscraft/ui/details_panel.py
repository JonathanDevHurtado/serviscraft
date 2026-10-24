"""Panel de detalles del servidor con acciones de mantenimiento.

La pestana se lee como una ficha de Minecraft: una cabecera de bloque, un
resumen de un vistazo y varias tarjetas de piedra (identidad, aspecto, recursos,
fechas, notas y mantenimiento). Cada tarjeta explica para que sirve con un
boton «?» y deja los datos tecnicos en segundo plano.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core import appearance
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager, jvm_overhead_mb
from ..core.models import ServerSpec, ServerState, format_bytes
from .common import (
    STATE_COLORS,
    Chip,
    FlowRow,
    StatusBadge,
    WrappingLabel,
    hint_label,
    make_button,
)
from .dialogs import confirm, show_error, show_info
from .mc_icons import (
    PlatformBadge,
    bloque_bedrock,
    icono_ajustes,
    icono_conectar,
    icono_consola,
    icono_copiar,
    icono_cuadro,
    icono_lista,
    icono_mochila,
    icono_mundo,
    icono_pack,
    item_icon,
    punto_estado,
)
from .mc_widgets import AccentCard, CenteredEmpty, IconSlot, MinecraftHero, TexturedPage
from .server_preview import McListEntry, icon_pixmap
from .tasks import TaskRunner

logger = get_logger("ui.details")

#: Ayuda general de la pestana.
_AYUDA_GENERAL = (
    "<b>Que hay en esta pestana</b><br>"
    "La ficha completa del servidor, ordenada en tarjetas: quien es, como se ve "
    "en la lista de Minecraft, los recursos que tiene, donde estan sus ficheros "
    "y las acciones de mantenimiento.<br><br>"
    "<b>Que puedes tocar</b><br>"
    "Los datos se leen del servidor y no se cambian aqui: usa «Editar ajustes» "
    "para el nombre, la memoria o los puertos, y «Cambiar aspecto» para el icono "
    "y el mensaje de la lista.<br><br>"
    "<b>Consejo</b><br>"
    "Pasa el raton por encima de cualquier dato: el aviso muestra el valor "
    "completo cuando es demasiado largo para la tarjeta."
)

_AYUDA_IDENTIDAD = (
    "<b>Tu servidor</b><br>"
    "El nombre, el identificador interno, el tipo de motor y la version de "
    "Minecraft. Tambien la imagen del contenedor y la version de Java que usa.<br><br>"
    "El identificador no se puede cambiar: es el nombre de su carpeta y de su "
    "contenedor. El estado y la plataforma se actualizan solos."
)

_AYUDA_ASPECTO = (
    "<b>Como se ve antes de entrar</b><br>"
    "Esta es la misma entrada que pinta Minecraft en la lista de servidores: "
    "el icono a la izquierda y el mensaje con colores debajo del nombre.<br><br>"
    "Minecraft lee el icono y el mensaje al arrancar. Si los cambias, reinicia "
    "el servidor para que tus amigos vean el aspecto nuevo."
)

_AYUDA_RECURSOS = (
    "<b>Memoria y puertos</b><br>"
    "La memoria del servidor es el limite de Java (``-Xmx``). El contenedor "
    "reserva ademas un poco mas para la propia maquina virtual: por eso el "
    "«Limite» es mayor que la memoria del juego.<br><br>"
    "El puerto es por donde entran los jugadores de Java. La consola local "
    "(RCON) solo se publica en este equipo y esta protegida con contrasena. "
    "Bedrock usa un puerto UDP aparte para movil, tablet y consola.<br><br>"
    "El boton «Copiar direccion» copia la direccion que ven tus amigos."
)

_AYUDA_FECHAS = (
    "<b>Fechas y carpetas</b><br>"
    "Cuando se creo el servidor, cuando arranco por ultima vez y donde estan sus "
    "ficheros. Las rutas se pueden seleccionar y copiar con el icono de la "
    "derecha de cada una.<br><br>"
    "La carpeta de datos guarda el mundo, los mods y la configuracion. La de "
    "copias guarda las copias de seguridad que hagas desde la pestana «Copias»."
)

_AYUDA_NOTAS = (
    "<b>Tus recordatorios</b><br>"
    "Un espacio privado para apuntar la version, los mods pendientes o cualquier "
    "cosa que quieras recordar. Las notas se guardan en la ficha del servidor y "
    "no se envian a nadie.<br><br>"
    "Pulsa «Guardar notas» para conservarlas."
)

_AYUDA_MANTENIMIENTO = (
    "<b>Acciones de mantenimiento</b><br>"
    "«Editar ajustes» cambia el nombre, la memoria, los puertos o el acceso desde "
    "la red. «Recrear contenedor» aplica la configuracion actual sin tocar el "
    "mundo, los mods ni las copias.<br><br>"
    "Los botones de carpeta abren el explorador de archivos. «Ver registro» abre "
    "el registro de Serviscraft.<br><br>"
    "<b>Importante</b><br>"
    "Serviscraft nunca ejecuta Podman con sudo ni abre puertos en el cortafuegos. "
    "Si expones el servidor en la red, revisa tu cortafuegos por tu cuenta."
)


class _FieldLabel(QWidget):
    """Nombre del dato con su objeto en una ranura pequena."""

    def __init__(
        self,
        text: str,
        pixmap: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(7)
        self.slot = IconSlot(pixmap, size=24, icon_size=16, parent=self)
        fila.addWidget(self.slot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel(text)
        self.label.setObjectName("DetailKey")
        fila.addWidget(self.label, 1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)


class _ValueSlot(QFrame):
    """Ranura donde vive el valor: fondo hundido y borde de piedra.

    Mantiene el alto de las etiquetas con ajuste de linea, igual que hacia el
    formulario anterior, para que el texto largo no se solape con la fila de
    abajo en una ventana estrecha.
    """

    _MARGENES = 18

    def __init__(self, child: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DetailSlot")
        self.child = child
        caja = QVBoxLayout(self)
        caja.setContentsMargins(8, 3, 8, 3)
        caja.setSpacing(0)
        caja.addWidget(child)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - API de Qt
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - API de Qt
        contenido = max(0, width - self._MARGENES)
        if self.child.hasHeightForWidth():
            alto = self.child.heightForWidth(contenido)
        else:
            alto = self.child.sizeHint().height()
        return max(26, alto + 8)

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        necesario = self.heightForWidth(self.width())
        if self.minimumHeight() != necesario:
            self.setMinimumHeight(necesario)


def _badge_row(widget: QWidget) -> QWidget:
    """Insignia pequena alineada a la izquierda, sin ranura de valor."""
    caja = QWidget()
    fila = QHBoxLayout(caja)
    fila.setContentsMargins(0, 0, 0, 0)
    fila.addWidget(widget)
    fila.addStretch(1)
    return caja


def _make_form(parent: QWidget | None = None) -> QFormLayout:
    """Crea un formulario cuyas etiquetas de valor se estiran y ajustan bien.

    Importante: el estilo Breeze usa ``ExpandingFieldsGrow``, que **no** estira los
    ``QLabel`` (su politica es ``Preferred``). Con ese ajuste, una etiqueta con
    ``setWordWrap(True)`` conserva la altura de una sola linea y su texto se
    superpone a la fila siguiente. ``AllNonFixedFieldsGrow`` la estira al ancho de
    la columna, de modo que Qt calcula la altura real del texto ajustado.
    """
    form = QFormLayout(parent)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(7)
    # En una ventana estrecha el valor pasa debajo del nombre en vez de comprimir
    # las dos columnas hasta recortar el texto.
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    return form


class DetailsPanel(TexturedPage):
    """Ficha tecnica del servidor y operaciones de mantenimiento."""

    settings_requested = Signal(str)
    appearance_requested = Signal(str)
    state_changed = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DetailsPanel")
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._state = ServerState.MISSING
        self._labels: dict[str, QLabel | QLineEdit] = {}
        #: Formularios de las tarjetas; se apilan en ventanas estrechas.
        self._forms: list[QFormLayout] = []
        self._cards: list[AccentCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ------------------------------------------------------------ cabecera
        self.hero = MinecraftHero(
            "Detalles del servidor",
            "Todo lo que hay dentro, explicado sin tecnicismos.",
            pixmap=item_icon("book", 44),
            accent="green",
            help_title="Detalles: la ficha completa del servidor",
            help_text=_AYUDA_GENERAL,
        )
        layout.addWidget(self.hero)

        # -------------------------------------------------------------- resumen
        self.summary_row = FlowRow(spacing=8)
        self.chip_state = Chip("Estado: ?", pixmap=punto_estado(STATE_COLORS[ServerState.MISSING], 14))
        self.chip_type = Chip("Tipo: ?", pixmap=icono_ajustes(14))
        self.chip_version = Chip("Minecraft: ?", pixmap=item_icon("grass_block", 14))
        self.chip_memory = Chip("Memoria: ?", pixmap=item_icon("iron_ingot", 14))
        self.chip_port = Chip("Puerto: ?", pixmap=icono_conectar(14))
        for chip in (
            self.chip_state,
            self.chip_type,
            self.chip_version,
            self.chip_memory,
            self.chip_port,
        ):
            self.summary_row.add(chip)
        layout.addWidget(self.summary_row)

        # ------------------------------------------------------------ identidad
        identity = self._nueva_tarjeta(
            "Tu servidor",
            "Los datos con los que se creo y como lo reconoce Minecraft.",
            icono=item_icon("grass_block", 20),
            accent="green",
            ayuda_titulo="Tu servidor: identidad y version",
            ayuda=_AYUDA_IDENTIDAD,
        )
        identity_form = _make_form()
        self._forms.append(identity_form)
        for key, label, icon in (
            ("name", "Nombre", item_icon("name_tag", 16)),
            ("id", "Identificador", item_icon("paper", 16)),
            ("type", "Tipo", item_icon("iron_pickaxe", 16)),
            ("version", "Minecraft", item_icon("grass_block", 16)),
            ("image", "Imagen", icono_cuadro(16)),
            ("java", "Java", item_icon("potion", 16)),
        ):
            self._add_row(identity_form, key, label, icon=icon)
        self.badge = StatusBadge()
        identity_form.addRow(
            _FieldLabel("Estado", item_icon("torch", 16)),
            _badge_row(self.badge),
        )
        # Insignia con los bloques: cesped (Java) y piedra (Bedrock).
        self.platform = PlatformBadge(14)
        identity_form.addRow(
            _FieldLabel("Plataforma", icono_mundo(16)),
            _badge_row(self.platform),
        )
        identity.body().addLayout(identity_form)
        layout.addWidget(identity)

        # -------------------------------------------------------------- aspecto
        aspect = self._nueva_tarjeta(
            "Como se ve en Minecraft",
            "La misma entrada que ven tus amigos antes de entrar.",
            icono=icono_lista(20),
            accent="gold",
            ayuda_titulo="Aspecto en la lista de servidores",
            ayuda=_AYUDA_ASPECTO,
        )
        # La misma entrada que pinta el juego, para verla antes de entrar.
        self.mc_preview = McListEntry(scale=1)
        aspect.body().addWidget(self.mc_preview)
        aspect_row = FlowRow(spacing=8)
        self.appearance_button = make_button(
            "Cambiar aspecto...",
            icon_names=("preferences-desktop-theme", "image-x-generic"),
            tooltip="Elegir el icono y el mensaje con colores que se ven en la lista de Minecraft",
        )
        self.appearance_button.clicked.connect(
            lambda: self._spec and self.appearance_requested.emit(self._spec.id)
        )
        aspect_row.add(self.appearance_button)
        aspect.body().addWidget(aspect_row)
        self.appearance_note = hint_label("")
        aspect.body().addWidget(self.appearance_note)
        layout.addWidget(aspect)

        # ------------------------------------------------------------- recursos
        resources = self._nueva_tarjeta(
            "Recursos y puertos",
            "La memoria y las puertas por las que entra la gente.",
            icono=icono_ajustes(20),
            accent="blue",
            ayuda_titulo="Recursos, puertos y direccion",
            ayuda=_AYUDA_RECURSOS,
        )
        resources_form = _make_form()
        self._forms.append(resources_form)
        for key, label, icon in (
            ("memory", "Memoria (heap)", item_icon("iron_ingot", 16)),
            ("memory_limit", "Limite", icono_pack(16)),
            ("port", "Puerto", icono_conectar(16)),
            ("rcon", "Consola (local)", icono_consola(16)),
            ("bedrock", "Bedrock", bloque_bedrock(16)),
            ("address", "Direccion", icono_conectar(16)),
            ("disk", "En disco", icono_mochila(16)),
        ):
            self._add_row(resources_form, key, label, icon=icon)
        resources.body().addLayout(resources_form)

        copy_button = make_button("Copiar direccion", icon_names=("edit-copy",))
        copy_button.clicked.connect(self._copy_address)
        resources.body().addWidget(copy_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(resources)

        # --------------------------------------------------------------- fechas
        times = self._nueva_tarjeta(
            "Fechas y rutas",
            "Cuando empezo todo y donde estan sus ficheros.",
            icono=item_icon("map", 20),
            accent="brown",
            ayuda_titulo="Fechas, contenedor y carpetas",
            ayuda=_AYUDA_FECHAS,
        )
        times_form = _make_form()
        self._forms.append(times_form)
        for key, label, icon, selectable in (
            ("created", "Creado", item_icon("book", 16), False),
            ("started", "Arranque", item_icon("torch", 16), False),
            ("container", "Contenedor", icono_pack(16), False),
            ("data_path", "Datos", icono_mochila(16), True),
            ("backups_path", "Copias", icono_copiar(16), True),
        ):
            self._add_row(times_form, key, label, icon=icon, selectable=selectable)
        times.body().addLayout(times_form)
        layout.addWidget(times)

        # ---------------------------------------------------------------- notas
        notes_box = self._nueva_tarjeta(
            "Notas",
            "Recordatorios que solo ves tu.",
            icono=item_icon("book", 20),
            accent="gold",
            ayuda_titulo="Notas privadas del servidor",
            ayuda=_AYUDA_NOTAS,
        )
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Recordatorios sobre este servidor (versiones, mods pendientes...)")
        self.notes.setFixedHeight(90)
        notes_box.body().addWidget(self.notes)
        notes_row = FlowRow(spacing=8)
        save_notes = make_button("Guardar notas", icon_names=("document-save",), accent=True)
        save_notes.clicked.connect(self._save_notes)
        notes_row.add(save_notes)
        notes_box.body().addWidget(notes_row)
        layout.addWidget(notes_box)

        # ------------------------------------------------------------ acciones
        actions = self._nueva_tarjeta(
            "Mantenimiento",
            "Arreglar, abrir o revisar el servidor sin miedo.",
            icono=icono_consola(20),
            accent="green",
            ayuda_titulo="Mantenimiento del servidor",
            ayuda=_AYUDA_MANTENIMIENTO,
        )
        # Dos filas que se envuelven al estrecharse la ventana.
        self.maintenance_row1 = FlowRow(spacing=8)
        edit_button = make_button(
            "Editar ajustes...",
            icon_names=("document-edit", "configure"),
            accent=True,
            tooltip="Cambiar nombre, memoria, puerto o acceso desde la red",
        )
        edit_button.clicked.connect(lambda: self._spec and self.settings_requested.emit(self._spec.id))
        self.maintenance_row1.add(edit_button)

        recreate_button = make_button(
            "Recrear contenedor",
            icon_names=("view-refresh", "system-reboot"),
            tooltip="Vuelve a crear el contenedor con la configuracion actual",
        )
        recreate_button.clicked.connect(self._recreate)
        self.maintenance_row1.add(recreate_button)
        actions.body().addWidget(self.maintenance_row1)

        self.maintenance_row2 = FlowRow(spacing=8)
        data_button = make_button("Abrir carpeta de datos", icon_names=("folder-open",))
        data_button.clicked.connect(lambda: self._open_path("data"))
        self.maintenance_row2.add(data_button)
        backups_button = make_button("Abrir carpeta de copias", icon_names=("folder-", "archive-insert-directory"))
        backups_button.clicked.connect(lambda: self._open_path("backups"))
        self.maintenance_row2.add(backups_button)
        log_button = make_button(
            "Ver registro",
            icon_names=("text-x-generic",),
            tooltip="Abrir el registro de Serviscraft",
        )
        log_button.clicked.connect(self._open_log)
        self.maintenance_row2.add(log_button)
        actions.body().addWidget(self.maintenance_row2)

        actions.body().addWidget(
            hint_label(
                "Serviscraft nunca ejecuta Podman con sudo y no abre puertos en el cortafuegos. "
                "Si expones el servidor en la red, revisa tu cortafuegos por tu cuenta."
            )
        )
        layout.addWidget(actions)

        self.empty = CenteredEmpty(
            "Elige un servidor",
            "Selecciona uno en la lista de la izquierda para ver su ficha completa: "
            "identidad, aspecto, recursos, rutas y mantenimiento.",
            pixmap=icono_pack(64),
        )
        layout.addWidget(self.empty, 1)

        self.set_server(None, ServerState.MISSING)

    # ================================================================ ayudas
    def _nueva_tarjeta(
        self,
        titulo: str,
        pista: str,
        *,
        icono: QPixmap,
        accent: str,
        ayuda_titulo: str,
        ayuda: str,
    ) -> AccentCard:
        tarjeta = AccentCard(
            titulo,
            pixmap=icono,
            help_title=ayuda_titulo,
            help_text=ayuda,
            accent=accent,
        )
        tarjeta.body().setSpacing(10)
        tarjeta.body().addWidget(hint_label(pista))
        self._cards.append(tarjeta)
        return tarjeta

    @staticmethod
    def _copiar_texto(texto: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(texto)

    def _add_row(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        *,
        icon: QPixmap | None = None,
        selectable: bool = False,
    ) -> None:
        if selectable:
            # Una ruta larga en una QLabel obliga a ensanchar toda la ficha: la
            # etiqueta no puede partir el texto y su ancho minimo es el de la
            # ruta entera. Un campo de solo lectura se desplaza, se puede
            # seleccionar y no impone ese ancho.
            campo = QLineEdit()
            campo.setObjectName("DetailsPath")
            campo.setReadOnly(True)
            campo.setFrame(False)
            copiar = campo.addAction(
                QIcon(icono_copiar(14)), QLineEdit.ActionPosition.TrailingPosition
            )
            copiar.setToolTip("Copiar esta ruta al portapapeles")
            copiar.triggered.connect(
                lambda _checked=False, c=campo: self._copiar_texto(c.text())
            )

            def _sincronizar(texto: str) -> None:
                campo.setCursorPosition(0)
                campo.setToolTip(
                    f"{texto}\n\nPulsa el icono de la derecha para copiar la ruta."
                    if texto and texto != "—"
                    else ""
                )

            campo.textChanged.connect(_sincronizar)
            value: QLabel | QLineEdit = campo
        else:
            # WrappingLabel reserva el alto real del texto ajustado; una QLabel
            # normal se queda con la altura de una linea y lo recorta por abajo.
            value = WrappingLabel("—")
            value.setObjectName("DetailValue")
        form.addRow(_FieldLabel(label, icon), _ValueSlot(value))
        self._labels[key] = value

    def _mostrar_contenido(self, visible: bool) -> None:
        self.summary_row.setVisible(visible)
        for tarjeta in self._cards:
            tarjeta.setVisible(visible)

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, state: ServerState) -> None:
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._state != state
        self._spec = spec
        self._state = state
        if spec is None:
            for label in self._labels.values():
                label.setText("—")
                label.setToolTip("")
            self.badge.set_state(ServerState.MISSING)
            self.platform.set_spec(None)
            self.notes.setPlainText("")
            self.notes.setEnabled(False)
            self.mc_preview.set_data("", "", icon_pixmap(b"", 32))
            self.appearance_note.setText("")
            self._mostrar_contenido(False)
            self.empty.setVisible(True)
            self.hero.set_title("Detalles del servidor")
            self.hero.set_subtitle("Selecciona un servidor a la izquierda para ver su ficha.")
            self._actualizar_resumen(None, ServerState.MISSING)
            return

        self.empty.setVisible(False)
        self._mostrar_contenido(True)
        self.notes.setEnabled(True)
        self.badge.set_state(state)
        self.platform.set_spec(spec)
        self.hero.set_title(f"Detalles de «{spec.name}»")
        self.hero.set_subtitle(
            "La ficha completa del servidor: identidad, aspecto, recursos y mantenimiento."
        )
        self._labels["name"].setText(spec.name)
        self._labels["id"].setText(spec.id)
        self._labels["type"].setText(spec.type.label)
        self._labels["type"].setToolTip(
            f"{spec.type.label}: {spec.type.description}\n\n"
            "El tipo se elige al crear el servidor y no se cambia desde esta ficha."
        )
        self._labels["version"].setText(spec.version)
        self._labels["image"].setText(spec.image_ref)
        self._labels["image"].setToolTip(
            f"Imagen del contenedor: {spec.image_ref}\nLa usa Podman para arrancar el servidor."
        )
        self._labels["java"].setText(spec.java_tag)
        self._labels["java"].setToolTip(f"Version de Java dentro del contenedor: {spec.java_tag}")
        self._labels["memory"].setText(f"{spec.memory_label} (JVM -Xmx)")
        self._labels["memory"].setToolTip(
            f"{spec.memory_label} para el juego: es el limite -Xmx que recibe Java."
        )
        self._labels["memory_limit"].setText(
            f"{format_bytes((spec.memory_mb + jvm_overhead_mb(spec.type)) * 1024 * 1024)} asignados al contenedor"
        )
        self._labels["memory_limit"].setToolTip(
            "La memoria del juego mas un margen para la maquina virtual de Java."
        )
        self._labels["port"].setText(str(spec.port))
        self._labels["port"].setToolTip(
            f"Puerto de Java: {spec.port}. Es el numero que se escribe despues de la direccion."
        )
        self._labels["rcon"].setText(
            f"{spec.rcon_port} — publicado solo en 127.0.0.1, protegido con contrasena"
        )
        if spec.bedrock_enabled:
            bedrock_text = (
                f"activados — movil, tablet y consola entran por el puerto UDP "
                f"{spec.bedrock_port}"
            )
        elif spec.type.supports_plugins:
            bedrock_text = (
                "no configurado — si instalas Geyser y Floodgate a mano (pestana "
                "Plugins), solo se puede si usas el plugin y el puerto UDP esta abierto"
            )
        else:
            bedrock_text = (
                f"no — {spec.type.label} no admite Geyser; solo entran jugadores de Java"
            )
        self._labels["bedrock"].setText(bedrock_text)
        if spec.lan:
            address = f"{self.manager.host_lan_ip()}:{spec.port}"
            self._labels["address"].setText(f"{address} (red local) — tambien localhost:{spec.port}")
        else:
            self._labels["address"].setText(f"localhost:{spec.port} (solo este equipo)")
        self._labels["address"].setToolTip(
            "Direccion para entrar desde este equipo o desde la red local."
        )
        self._labels["created"].setText(_format_date(spec.created_at))
        self._labels["started"].setText(_format_date(spec.last_started_at) if spec.last_started_at else "nunca")
        self._labels["container"].setText(spec.container_name)
        self._labels["data_path"].setText(str(self.manager.store.data_dir(spec.id)))
        self._labels["backups_path"].setText(str(self.manager.store.backups_dir(spec.id)))
        if self.notes.toPlainText() != spec.notes:
            self.notes.setPlainText(spec.notes)
        self._actualizar_resumen(spec, state)
        if cambio_estado:
            self.refresh_disk_usage()
            self.refresh_appearance()

    def set_state(self, state: ServerState) -> None:
        self._state = state
        self.badge.set_state(state)
        self._actualizar_resumen(self._spec, state)

    def _actualizar_resumen(self, spec: ServerSpec | None, state: ServerState) -> None:
        """Rellena los chips de un vistazo (o los deja en «?»)."""
        tonos = {
            ServerState.RUNNING: "ok",
            ServerState.CREATED: "info",
            ServerState.PAUSED: "warn",
            ServerState.EXITED: "bad",
        }
        estado = state.label if spec is not None else "Sin servidor"
        self.chip_state.set_text(f"Estado: {estado}")
        self.chip_state.set_tone(tonos.get(state, ""))
        self.chip_state.set_pixmap(punto_estado(STATE_COLORS.get(state, "#9ca3af"), 14))
        if spec is None:
            self.chip_type.set_text("Tipo: ?")
            self.chip_version.set_text("Minecraft: ?")
            self.chip_memory.set_text("Memoria: ?")
            self.chip_port.set_text("Puerto: ?")
            return
        self.chip_type.set_text(f"Tipo: {_shorten(spec.type.label, 20)}")
        self.chip_type.setToolTip(f"Tipo de servidor: {spec.type.label}")
        self.chip_version.set_text(f"Minecraft: {_shorten(spec.version, 14)}")
        self.chip_version.setToolTip(f"Version de Minecraft: {spec.version}")
        self.chip_memory.set_text(f"Memoria: {_shorten(spec.memory_label, 14)}")
        self.chip_memory.setToolTip(
            f"Memoria del juego: {spec.memory_label}. El contenedor reserva ademas la sobrecarga de la JVM."
        )
        self.chip_port.set_text(f"Puerto: {spec.port}")
        self.chip_port.setToolTip(f"Puerto de Java: {spec.port}")

    def refresh_appearance(self) -> None:
        """Lee el icono y la descripcion con los que se ve el servidor."""
        if self._spec is None:
            return
        spec = self._spec
        self.mc_preview.set_data(
            spec.name, "", icon_pixmap(self.manager.server_icon(spec.id), 32)
        )

        def work(*, context):
            return self.manager.motd(spec.id)

        def done(motd: str) -> None:
            if self._spec is None or self._spec.id != spec.id:
                return
            self.mc_preview.set_data(spec.name, motd)
            if appearance.strip_codes(motd).strip():
                self.appearance_note.setText(
                    "Asi lo ven tus amigos antes de entrar. Minecraft lee la imagen y la "
                    "descripcion al arrancar: el cambio se aplica al reiniciar el servidor."
                )
            else:
                self.appearance_note.setText(
                    "Todavia no tiene descripcion propia. Ponle una (con colores) para "
                    "distinguirlo de otros servidores en la lista."
                )

        self.runner.submit(
            "Leyendo el aspecto del servidor",
            work,
            on_finished=done,
            on_failed=lambda _m, _d: None,
            track_busy=False,
        )

    def refresh_disk_usage(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        server_id = spec.id

        def work(*, context):
            return self.manager.total_disk_usage(server_id)

        def done(size: int) -> None:
            # La consulta puede terminar despues de cambiar de servidor: el
            # tamano del anterior no debe aparecer en la ficha del nuevo.
            if self._spec is not None and self._spec.id == server_id:
                self._labels["disk"].setText(format_bytes(size))

        def failed(_message: str, _details: str) -> None:
            if self._spec is not None and self._spec.id == server_id:
                self._labels["disk"].setText("no disponible")

        self.runner.submit(
            "Calculando el uso de disco",
            work,
            on_finished=done,
            on_failed=failed,
            track_busy=False,
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        politica = (
            QFormLayout.RowWrapPolicy.WrapAllRows
            if self.width() < 620
            else QFormLayout.RowWrapPolicy.WrapLongRows
        )
        for form in self._forms:
            if form.rowWrapPolicy() != politica:
                form.setRowWrapPolicy(politica)

    # ============================================================== acciones
    def _copy_address(self) -> None:
        from PySide6.QtWidgets import QApplication

        if self._spec is None:
            return
        address = f"localhost:{self._spec.port}"
        if self._spec.lan:
            address = f"{self.manager.host_lan_ip()}:{self._spec.port}"
        QApplication.clipboard().setText(address)
        show_info(self, "Direccion copiada", f"Se ha copiado al portapapeles:\n\n{address}")

    def _open_path(self, kind: str) -> None:
        if self._spec is None:
            return
        if kind == "data":
            path = self.manager.store.data_dir(self._spec.id)
        else:
            path = self.manager.store.backups_dir(self._spec.id)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_log(self) -> None:
        from ..core import paths

        log = paths.log_file()
        if not log.is_file():
            show_info(self, "Registro vacio", "Todavia no hay registro de la aplicacion.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log)))

    def _save_notes(self) -> None:
        if self._spec is None:
            return
        spec = self.manager.get(self._spec.id)
        spec.notes = self.notes.toPlainText()
        try:
            self.manager.store.save(spec)
        except ServiscraftError as exc:
            show_error(self, "No se pudieron guardar las notas", str(exc))
            return
        self._spec = spec
        show_info(self, "Notas guardadas", "Las notas del servidor se han guardado.")

    def _recreate(self) -> None:
        if self._spec is None:
            return
        if self._state.is_running:
            show_error(self, "Servidor en ejecucion", "Deten el servidor antes de recrear el contenedor.")
            return
        if not confirm(
            self,
            "Recrear contenedor",
            "Se volvera a crear el contenedor del servidor con la configuracion actual.\n\n"
            "Los mundos, pluguins y mods no se tocan.",
            confirm_label="Recrear",
        ):
            return
        spec = self._spec
        self.state_changed.emit()

        def work(*, context) -> str:
            context.progress("Recreando el contenedor...")
            self.manager.recreate_container(spec.id, on_progress=context.progress)
            return spec.id

        self.runner.submit(
            "Recreando contenedor",
            work,
            on_finished=lambda _r: show_info(self, "Contenedor recreado", "El contenedor se ha recreado correctamente."),
            on_failed=lambda message, details: show_error(self, "No se pudo recrear", message, details),
        )


def _shorten(text: str, limit: int = 24) -> str:
    """Recorta un texto largo para que un chip no ensanche la ventana."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_date(value: str | None) -> str:
    if not value:
        return "—"
    text = str(value).replace("T", " ")
    return text[:19]
