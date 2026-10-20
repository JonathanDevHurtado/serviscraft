"""Pestana «Unirse»: como entran los jugadores, paso a paso.

Cuatro secciones, en el orden en que se necesitan:

1. **Java** (PC, Mac, Linux): la direccion exacta que hay que escribir en
   Minecraft, con boton para copiarla y los pasos numerados.
2. **Bedrock** (movil, tablet, consola): se activa con Geyser y Floodgate, que
   descarga la propia imagen, y se publica el puerto UDP correspondiente.
3. **Amigos de fuera de casa**: la IP publica, el puerto que hay que abrir en el
   router y las alternativas si el operador no deja.
4. **Cuentas**: si se exigen cuentas premium (``online-mode``) o se acepta
   cualquier cliente, con confirmacion y aviso de seguridad.

Cada seccion lleva un boton «?» que explica para que sirve y que hay que hacer:
asi la pestana se entiende sin leer parrafos y sin adivinar. Serviscraft **no**
toca el cortafuegos ni el router: solo lo explica y comprueba lo que puede.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import netinfo
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from .common import (
    Chip,
    ElidedLabel,
    FlowRow,
    HelpButton,
    SectionCard,
    WrappingLabel,
    hint_label,
    make_button,
)
from .dialogs import confirm, show_error
from .ddns_dialog import DdnsDialog
from .mc_icons import PlatformBadge, bloque_bedrock, bloque_java, icono_escudo, icono_mundo
from .tasks import TaskRunner

logger = get_logger("ui.join")

#: Aviso que se muestra cuando el servidor acepta cuentas sin licencia.
_AVISO_SIN_PREMIUM = (
    "Aviso de seguridad: con la verificacion de cuentas desactivada, cualquiera "
    "puede entrar usando el nombre de otro jugador (y hacerse pasar por un "
    "operador). Usalo solo en un servidor privado, en tu red de confianza y sin "
    "operadores entre desconocidos."
)

#: Explicaciones del boton «?» de cada seccion (texto sin acentos, como el resto
#: de la interfaz; acepta formato sencillo de Qt).
_AYUDA_JAVA = (
    "Minecraft <b>Java</b> es el del ordenador (Windows, Mac y Linux)."
    "<br><br><b>La direccion</b> es como el numero de casa del servidor: lo que "
    "tus amigos escriben para llegar a el.<br>"
    "· <b>Direccion del servidor</b>: funciona para los que estan en tu misma "
    "casa o tu misma red (el cole, la oficina).<br>"
    "· <b>En este mismo equipo</b> (localhost): solo vale en tu ordenador, para "
    "probar.<br><br><b>El puerto</b> es la puerta concreta dentro de esa casa. "
    "Java usa el 25565; si el tuyo es otro, se escribe igual: "
    "direccion:puerto.<br><br><b>Que hay que hacer:</b> copia la direccion con el "
    "boton y pegala en Minecraft, en Multijugador → Anadir servidor."
)

_AYUDA_BEDROCK = (
    "Minecraft <b>Bedrock</b> es el de movil (Android y iPhone), tablet, consola "
    "y la tienda de Microsoft. Habla un idioma distinto al de Java, asi que para "
    "que entren hace falta un traductor: los pluguins <b>Geyser</b> y "
    "<b>Floodgate</b> (Serviscraft los descarga solo, no hay que buscar nada)."
    "<br><br>Al marcar la casilla se abre tambien el <b>puerto UDP</b> (19132) "
    "ademas del de Java. El mundo es el mismo para todos: los de movil y los de "
    "PC se ven entre ellos.<br><br>Solo funciona en servidores de tipo Paper, que "
    "es el unico que admite pluguins."
)

_AYUDA_INTERNET = (
    "Tus amigos de otra ciudad no llegan a tu ordenador directamente: tu router "
    "solo deja entrar a quien llama a una puerta abierta."
    "<br><br>1. Tu router tiene una <b>IP publica</b>: la direccion de tu casa en "
    "internet.<br>2. En el router hay que <b>reenviar</b> el puerto del juego a "
    "este equipo (se llama «Port forwarding»).<br>3. Tus amigos escriben "
    "<b>IP publica:puerto</b>.<br><br>Serviscraft no toca el router ni el "
    "cortafuegos: solo te dice que hay que abrir y averigua tu IP. Si tu operador "
    "no deja abrir puertos, la alternativa es una red privada (Tailscale, "
    "ZeroTier) o un tunel como playit.gg."
)

_AYUDA_NOMBRE = (
    "En vez de dar a tus amigos una direccion con numeros (tu IP), les das un "
    "<b>nombre</b>: <i>reinotrebol.duckdns.org:25565</i>."
    "<br><br><b>Por que es mejor</b><br>"
    "· Se recuerda y se escribe sin errores.<br>"
    "· No revela donde vives ni cual es tu IP.<br>"
    "· Sigue valiendo aunque tu operador te cambie la IP (si activas «mantener al "
    "dia»).<br><br><b>Como se consigue</b><br>Crea el nombre gratis en "
    "<b>www.duckdns.org</b> (con tu cuenta de Google o GitHub), copia el token que "
    "te da y pulsa «Poner un nombre». Serviscraft guarda el token en tu equipo y "
    "avisa a DuckDNS de tu IP por ti.<br><br><b>Ojo</b><br>El nombre traduce tu "
    "direccion, pero <b>no abre el puerto</b>: el router tiene que reenviar el "
    "puerto del juego igualmente. Y para entrar sin escribir el puerto haria falta "
    "un dominio propio con un registro SRV (DuckDNS no lo permite)."
)

_AYUDA_CUENTAS = (
    "<b>Con cuentas premium</b> (lo recomendado): la consola de Mojang comprueba "
    "que cada jugador tiene el juego comprado. Nadie puede hacerse pasar por "
    "otro.<br><br><b>Sin licencia</b> (<i>online-mode=false</i>): entra "
    "cualquiera, tambien quien no ha comprado el juego, y alguien podria usar el "
    "nombre de un operador para hacer trastadas. Solo para servidores privados y "
    "de gente de confianza.<br><br>El cambio se guarda en el fichero de "
    "propiedades del servidor y se aplica al reiniciarlo."
)


class JoinPanel(QWidget):
    """Como se conectan los jugadores y que cuentas se aceptan."""

    #: La definicion del servidor ha cambiado (Bedrock): hay que refrescar la ventana.
    changed = Signal()

    def __init__(self, manager: ServerManager, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._running = False
        self._cargando = False
        self._ip_publica = ""
        self._ddns_dialog: DdnsDialog | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.intro = hint_label("")
        layout.addWidget(self.intro)

        # Resumen de un vistazo: estado del servidor y plataformas que admite.
        self.status_row = FlowRow(spacing=8)
        self.state_chip = Chip("", tone="warn")
        self.status_row.add(self.state_chip)
        self.platform_badge = PlatformBadge()
        self.status_row.add(self.platform_badge)
        layout.addWidget(self.status_row)

        layout.addWidget(self._build_java_box())
        layout.addWidget(self._build_bedrock_box())
        layout.addWidget(self._build_outside_box())
        layout.addWidget(self._build_accounts_box())
        layout.addStretch(1)

        self.empty = WrappingLabel("Selecciona un servidor para ver como se conectan los jugadores.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None, running=False)

    # ============================================================== construccion
    def _fila(self, *widgets: QWidget) -> FlowRow:
        """Fila que se envuelve sola: nada se recorta en ventanas estrechas."""
        fila = FlowRow(spacing=8)
        for widget in widgets:
            fila.add(widget)
        return fila

    def _valor(self, texto: str = "") -> ElidedLabel:
        """Etiqueta de un dato (direccion) que se puede seleccionar con el raton."""
        etiqueta = ElidedLabel(texto)
        etiqueta.setObjectName("AddressText")
        etiqueta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return etiqueta

    def _paso(self, numero: int, texto: str) -> QWidget:
        """Un paso numerado: el circulo con el numero y el texto al lado."""
        fila = QWidget()
        disposicion = QHBoxLayout(fila)
        disposicion.setContentsMargins(0, 0, 0, 0)
        disposicion.setSpacing(8)
        marca = QLabel(str(numero))
        marca.setObjectName("StepNumber")
        marca.setAlignment(Qt.AlignmentFlag.AlignCenter)
        marca.setFixedSize(20, 20)
        disposicion.addWidget(marca, 0, Qt.AlignmentFlag.AlignTop)
        disposicion.addWidget(WrappingLabel(texto), 1)
        return fila

    def _pasos(self, pasos: list[str]) -> QWidget:
        caja = QWidget()
        disposicion = QVBoxLayout(caja)
        disposicion.setContentsMargins(0, 0, 0, 0)
        disposicion.setSpacing(4)
        for numero, texto in enumerate(pasos, start=1):
            disposicion.addWidget(self._paso(numero, texto))
        return caja

    def _copiar(self, texto: str) -> QPushButton:
        boton = make_button("Copiar", icon_names=("edit-copy",), tooltip="Copiar al portapapeles")
        boton.clicked.connect(lambda: self._copy(texto, boton))
        return boton

    def _build_java_box(self) -> SectionCard:
        box = self.address_box = SectionCard(
            "1. Entrar desde un PC (Java)",
            pixmap=bloque_java(18),
            help_title="Minecraft Java: como se entra",
            help_text=_AYUDA_JAVA,
        )
        layout = box.body()

        self.steps = self._pasos(
            [
                "Abre Minecraft y entra en «Multijugador».",
                "Pulsa «Anadir servidor».",
                "Escribe la direccion de aqui abajo (el boton la copia).",
                "Ponle el nombre que quieras y pulsa «Hecho». Ya puedes entrar.",
            ]
        )
        layout.addWidget(self.steps)

        # Direccion principal: es la que se copia y se pega en Minecraft.
        self.lan_address = self._valor()
        self.copy_lan_button = self._copiar(self.lan_address.text())
        layout.addWidget(
            self._fila(QLabel("Direccion del servidor"), self.lan_address, self.copy_lan_button)
        )

        self.local_address = self._valor()
        self.copy_local_button = self._copiar(self.local_address.text())
        layout.addWidget(
            self._fila(QLabel("En este mismo equipo"), self.local_address, self.copy_local_button)
        )

        self.container_label = ElidedLabel("")
        self.container_label.setObjectName("Hint")
        layout.addWidget(self._fila(QLabel("Contenedor"), self.container_label))

        self.scope_note = hint_label("")
        layout.addWidget(self.scope_note)
        return box

    def _build_outside_box(self) -> SectionCard:
        box = self.outside_box = SectionCard(
            "3. Amigos de otras ciudades (internet)",
            pixmap=icono_mundo(18),
            help_title="Jugar con gente de fuera de casa",
            help_text=_AYUDA_INTERNET,
        )
        layout = box.body()

        # Nombre personalizado: la forma recomendada de entrar desde fuera.
        self.ddns_address = self._valor("Sin nombre: se entra con tu IP publica")
        self.copy_ddns_button = self._copiar(self.ddns_address.text())
        self.copy_ddns_button.setEnabled(False)
        self.ddns_button = make_button(
            "Poner un nombre",
            icon_names=("insert-link", "edit-rename"),
            tooltip="Un nombre propio (reinotrebol.duckdns.org) en vez de tu IP publica",
        )
        self.ddns_button.clicked.connect(self._abrir_ddns)
        layout.addWidget(
            self._fila(
                QLabel("Nombre para entrar"),
                self.ddns_address,
                self.copy_ddns_button,
                self.ddns_button,
                HelpButton("El nombre para entrar", _AYUDA_NOMBRE),
            )
        )
        self.ddns_chip = Chip("", tone="warn")
        self.ddns_chip.setVisible(False)
        layout.addWidget(self.ddns_chip)
        self.ddns_note = hint_label("")
        layout.addWidget(self.ddns_note)

        self.public_address = self._valor("Pulsa «Consultar mi IP publica»")
        self.public_button = make_button(
            "Consultar mi IP publica",
            icon_names=("network-wired", "network-workgroup"),
            tooltip="Pregunta a un servicio de internet cual es tu IP de salida",
        )
        self.public_button.clicked.connect(self._consultar_ip_publica)
        self.copy_public_button = self._copiar(self.public_address.text())
        self.copy_public_button.setEnabled(False)
        layout.addWidget(
            self._fila(
                QLabel("Tu IP publica"),
                self.public_address,
                self.public_button,
                self.copy_public_button,
            )
        )

        self.outside_steps = self._pasos(
            [
                "Busca «Port forwarding» (reenvio de puertos) en tu router.",
                "Reenvia el puerto del juego a este equipo.",
                "Tus amigos escriben la direccion de arriba: ip:puerto.",
            ]
        )
        layout.addWidget(self.outside_steps)

        self.outside_note = hint_label("")
        layout.addWidget(self.outside_note)

        self.router_note = hint_label("")
        layout.addWidget(self.router_note)
        return box

    def _build_bedrock_box(self) -> SectionCard:
        box = self.bedrock_box = SectionCard(
            "2. Jugadores de movil, tablet y consola (Bedrock)",
            pixmap=bloque_bedrock(18),
            help_title="Minecraft Bedrock: como se entra",
            help_text=_AYUDA_BEDROCK,
        )
        layout = box.body()

        self.bedrock_check = QCheckBox("Permitir jugadores de Bedrock (Geyser)")
        self.bedrock_check.setToolTip(
            "Instala los pluguins Geyser y Floodgate, y publica el puerto UDP de Bedrock."
        )
        self.bedrock_check.toggled.connect(self._on_bedrock_toggled)
        layout.addWidget(self.bedrock_check)

        self.bedrock_address = self._valor()
        self.copy_bedrock_button = self._copiar(self.bedrock_address.text())
        layout.addWidget(
            self._fila(QLabel("Direccion Bedrock"), self.bedrock_address, self.copy_bedrock_button)
        )

        self.bedrock_note = hint_label("")
        layout.addWidget(self.bedrock_note)
        return box

    def _build_accounts_box(self) -> SectionCard:
        accounts = self.accounts_box = SectionCard(
            "4. Cuentas y seguridad",
            pixmap=icono_escudo(18),
            help_title="Cuentas premium y sin licencia",
            help_text=_AYUDA_CUENTAS,
        )
        accounts_layout = accounts.body()
        self.premium = QCheckBox("Exigir cuentas premium (online-mode)")
        self.premium.setToolTip(
            "Activado: solo entran cuentas compradas y verificadas con Mojang.\n"
            "Desactivado: tambien entran clientes sin licencia."
        )
        self.premium.toggled.connect(self._on_premium_toggled)
        accounts_layout.addWidget(self.premium)

        self.premium_note = hint_label("")
        accounts_layout.addWidget(self.premium_note)

        self.warning_chip = Chip("Sin verificacion de cuentas", tone="bad", pixmap=icono_escudo(14))
        self.warning_chip.setVisible(False)
        accounts_layout.addWidget(self.warning_chip)
        self.warning = hint_label("")
        accounts_layout.addWidget(self.warning)

        self.apply_row = FlowRow(spacing=8)
        self.apply_button = make_button(
            "Guardar el modo de cuentas",
            icon_names=("document-save",),
            accent=True,
            tooltip="Guardar en el fichero de propiedades del servidor",
        )
        self.apply_button.setObjectName("ApplyAccounts")
        self.apply_button.clicked.connect(self._save)
        self.apply_row.add(self.apply_button)
        self.reload_button = make_button("Descartar cambios", icon_names=("edit-undo",))
        self.reload_button.clicked.connect(self._cargar_cuentas)
        self.apply_row.add(self.reload_button)
        accounts_layout.addWidget(self.apply_row)

        accounts_layout.addWidget(
            hint_label(
                "El cambio se guarda en el fichero de propiedades del servidor y se aplica "
                "al reiniciarlo. Las cuentas de Bedrock que entren con Geyser no necesitan "
                "tener el juego en Java."
            )
        )
        return accounts

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._running != running
        self._spec = spec
        self._running = running
        has_server = spec is not None
        for widget in (
            self.intro,
            self.status_row,
            self.address_box,
            self.outside_box,
            self.bedrock_box,
            self.accounts_box,
        ):
            widget.setVisible(has_server)
        # Los avisos que se ocultan por su cuenta (nombre sin configurar, aviso de
        # cuentas) se apagan uno a uno: un hijo de un recuadro oculto no cuenta
        # como oculto para las comprobaciones de la interfaz.
        for widget in (self.ddns_chip,):
            if not has_server:
                widget.setVisible(False)
        self.empty.setVisible(not has_server)
        if has_server and cambio_estado:
            self._cargar()
        elif not has_server:
            self._ocultar_aviso()

    def set_running(self, running: bool) -> None:
        self.set_server(self._spec, running=running)

    # ============================================================== direccion
    def _cargar(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        host = self.manager.host_lan_ip()
        if spec.lan:
            self.lan_address.setText(spec.connection_address(host))
            self.copy_lan_button.setEnabled(True)
        else:
            self.lan_address.setText("Desactivada (solo este equipo)")
            self.copy_lan_button.setEnabled(False)
        self.local_address.setText(f"localhost:{spec.port}")
        red = "tambien desde la red local" if spec.lan else "solo desde este equipo"
        self.container_label.setText(f"{spec.container_name} · {spec.type.label} {spec.version}")
        self.intro.setText(
            f"Asi se conectan los jugadores a «{spec.name}» ({red}). La direccion se copia "
            "con el boton y se pega en Minecraft."
        )
        self._cargar_estado()
        self.scope_note.setText(
            "La direccion de red local funciona para los equipos de tu casa o tu oficina."
            if spec.lan
            else "Este servidor solo acepta conexiones de este mismo equipo. Se puede "
            "cambiar en «Ajustes del servidor» marcando la red local."
        )
        self._cargar_internet()
        self._cargar_ddns()
        self._cargar_bedrock()
        self._cargar_cuentas()

    def _cargar_estado(self) -> None:
        """Ficha de estado: dice de un vistazo si ya pueden entrar o no."""
        if self._running:
            self.state_chip.set_text("En marcha: ya pueden entrar")
            self.state_chip.set_tone("ok")
            self.state_chip.setToolTip("El servidor esta encendido; los jugadores pueden conectarse.")
        else:
            self.state_chip.set_text("Detenido: inicialo para jugar")
            self.state_chip.set_tone("warn")
            self.state_chip.setToolTip(
                "El servidor esta apagado. Inicialo con el boton «Iniciar» de la cabecera."
            )
        self.platform_badge.set_spec(self._spec)

    def _cargar_internet(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        if self._ip_publica:
            self.public_address.setText(f"{self._ip_publica}:{spec.port}")
            self.copy_public_button.setEnabled(True)
        else:
            self.public_address.setText("Pulsa «Consultar mi IP publica»")
            self.copy_public_button.setEnabled(False)
        puertos_bedrock = f" y el {spec.bedrock_port} UDP" if spec.bedrock_enabled else ""
        self.outside_note.setText(
            "Para que entren desde otras ciudades o paises hay que abrir el puerto en el "
            f"router de casa: busca «Port forwarding» en su configuracion y reenvia el "
            f"puerto {spec.port}{puertos_bedrock} a este equipo. Despues se conectan con "
            f"«tu IP publica:{spec.port}»."
        )
        self.router_note.setText(
            "Serviscraft no toca el cortafuegos ni el router: solo te dice que hay que "
            "abrir. Si tu operador no deja abrir puertos, la alternativa es una red "
            "privada (Tailscale, ZeroTier) o un tunel como playit.gg: los amigos instalan "
            "el programa, se unen a tu red y entran con la direccion que te indique."
        )

    # ============================================== nombre personalizado (DuckDNS)
    def _cargar_ddns(self) -> None:
        """Muestra el nombre configurado y comprueba (sin salir a internet) que resuelve."""
        if self._spec is None:
            return
        spec = self._spec
        if not spec.ddns_configured:
            self.ddns_address.setText("Sin nombre: se entra con tu IP publica")
            self.copy_ddns_button.setEnabled(False)
            self.ddns_button.setText("Poner un nombre")
            self.ddns_chip.setVisible(False)
            self.ddns_note.setText(
                "Ponle un nombre (por ejemplo reinotrebol.duckdns.org) y tus amigos no "
                "tendran que escribir tu IP ni apuntarla en un papel."
            )
            return

        self.ddns_address.setText(spec.public_address())
        self.copy_ddns_button.setEnabled(True)
        self.ddns_button.setText("Cambiar nombre")
        self.ddns_chip.set_text("Comprobando el nombre...")
        self.ddns_chip.set_tone("warn")
        self.ddns_chip.setVisible(True)
        self.ddns_note.setText(
            "Este nombre apunta a tu IP publica. La comprobacion de abajo no sale a "
            "internet: solo pregunta al sistema de nombres si responde."
        )
        self._comprobar_ddns(spec)

    def _comprobar_ddns(self, spec: ServerSpec) -> None:
        """Comprueba en segundo plano a que direccion apunta el nombre."""
        publica = self._ip_publica

        def work(*, context):
            from ..core import ddns

            context.progress("Comprobando el nombre del servidor...")
            return ddns.check(spec.ddns_subdomain, public_ip=publica, puerto=spec.port)

        def done(status) -> None:
            if self._spec is None or self._spec.id != spec.id:
                return
            tonos = {
                "ok": "ok",
                "otra-ip": "warn",
                "sin-ip": "warn",
                "sin-resolver": "bad",
                "sin-configurar": "warn",
            }
            etiquetas = {
                "ok": "Nombre funcionando",
                "otra-ip": "Apunta a otra IP",
                "sin-ip": "Nombre configurado",
                "sin-resolver": "El nombre no responde",
                "sin-configurar": "Sin configurar",
            }
            self.ddns_chip.set_text(etiquetas.get(status.state, status.state))
            self.ddns_chip.set_tone(tonos.get(status.state, "warn"))
            self.ddns_chip.setToolTip(status.detail)
            self.ddns_note.setText(self._nota_ddns(spec, status))

        self.runner.submit(
            "Comprobando el nombre del servidor",
            work,
            on_finished=done,
            on_failed=lambda *_: None,
            track_busy=False,
        )

    def _nota_ddns(self, spec: ServerSpec, status) -> str:
        """Explica el estado del nombre y lo que falta para que funcione."""
        partes: list[str] = []
        if status.detail:
            partes.append(status.detail)
        if not spec.lan:
            partes.append(
                "Ademas, este servidor solo acepta conexiones de este equipo: activa la "
                "red local en «Ajustes del servidor» para que el nombre sirva de algo."
            )
        elif status.state in {"ok", "sin-ip"}:
            partes.append(
                f"Recuerda que el router tiene que reenviar el puerto {spec.port} a este "
                "equipo: el nombre no abre la puerta."
            )
        return " ".join(partes)

    def _abrir_ddns(self) -> None:
        if self._spec is None:
            return
        if self._ddns_dialog is not None and self._ddns_dialog.isVisible():
            self._ddns_dialog.raise_()
            self._ddns_dialog.activateWindow()
            return
        dialogo = DdnsDialog(
            self.manager,
            self.runner,
            self._spec,
            public_ip=self._ip_publica,
            parent=self.window(),
        )
        dialogo.finished.connect(self._ddns_cerrado)
        self._ddns_dialog = dialogo
        dialogo.show()

    def _ddns_cerrado(self, *_args: object) -> None:
        """Al cerrar la ventana se refresca la pestana con lo que se haya guardado."""
        dialogo = self._ddns_dialog
        self._ddns_dialog = None
        if dialogo is not None:
            self._spec = dialogo.spec
        self.changed.emit()
        self._cargar_internet()
        self._cargar_ddns()

    def _cargar_bedrock(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        disponible, motivo = self.manager.bedrock_available(spec)
        self._cargando = True
        self.bedrock_check.setChecked(spec.bedrock_enabled)
        self._cargando = False
        # Mientras el servidor esta en marcha no se puede cambiar (habria que
        # recrear el contenedor): se explica en la nota.
        self.bedrock_check.setEnabled(disponible and not self._running)
        if not disponible:
            self.bedrock_address.setText("No disponible")
            self.copy_bedrock_button.setEnabled(False)
            self.bedrock_note.setText(motivo)
            return
        host = self.manager.host_lan_ip()
        if spec.bedrock_enabled:
            self.bedrock_address.setText(f"{host}:{spec.bedrock_port}")
            self.copy_bedrock_button.setEnabled(True)
            aviso = (
                " Geyser y Floodgate se descargan solos al iniciar el servidor. Si el "
                "servidor esta en marcha, hay que reiniciarlo para que entren."
                if self._running
                else " Geyser y Floodgate se descargan solos al iniciar el servidor."
            )
            self.bedrock_note.setText(
                "En Minecraft Bedrock: «Jugar» → «Servidores» → «Anadir servidor», "
                f"direccion {host} y puerto {spec.bedrock_port}." + aviso
            )
        else:
            self.bedrock_address.setText("Desactivado")
            self.copy_bedrock_button.setEnabled(False)
            self.bedrock_note.setText(
                "Los jugadores de movil, tablet y consola hablan otro idioma que Java: "
                "para que entren hay que instalar los pluguins Geyser y Floodgate "
                "(lo hace Serviscraft automaticamente al marcar la casilla)."
            )

    def _cargar_cuentas(self) -> None:
        if self._spec is None:
            return
        try:
            props = self.manager.properties(self._spec.id)
            premium = props.get_bool("online-mode", True)
        except ServiscraftError as exc:
            self.premium_note.setText(f"No se pudo leer el fichero de propiedades: {exc}")
            premium = True
        self._cargando = True
        self.premium.setChecked(premium)
        self._cargando = False
        self._actualizar_notas(premium)
        self.apply_button.setEnabled(False)

    def _actualizar_notas(self, premium: bool) -> None:
        if premium:
            self.premium_note.setText(
                "Modo premium: la consola de Mojang comprueba que la cuenta existe. "
                "Es lo recomendado y lo que evita suplantaciones."
            )
            self._ocultar_aviso()
            return
        self.premium_note.setText(
            "Modo sin licencia: se acepta cualquier cliente, tambien los que no han "
            "comprado el juego."
        )
        self.warning_chip.set_text("Sin verificacion de cuentas")
        self.warning_chip.setVisible(True)
        self.warning.setText(_AVISO_SIN_PREMIUM)
        self.warning.setVisible(True)

    def _ocultar_aviso(self) -> None:
        self.warning_chip.setVisible(False)
        self.warning.clear()
        self.warning.setVisible(False)

    def _on_premium_toggled(self, _valor: bool) -> None:
        if self._cargando:
            return
        self._actualizar_notas(self.premium.isChecked())
        self.apply_button.setEnabled(True)

    def _copy(self, texto: str, boton: QPushButton | None = None) -> None:
        """Copia al portapapeles y confirma en el propio boton que se copio."""
        if not texto or texto.startswith(("Pulsa «", "Desactivad", "Consultando", "No disponible")):
            return
        QApplication.clipboard().setText(texto)
        self._confirmar_copiado(boton)

    def _confirmar_copiado(self, boton: QPushButton | None) -> None:
        if boton is None or not boton.isEnabled():
            return
        anterior = boton.text()
        boton.setText("Copiado")
        boton.setEnabled(False)
        QTimer.singleShot(1400, partial(self._restaurar_boton, boton, anterior))

    @staticmethod
    def _restaurar_boton(boton: QPushButton, anterior: str) -> None:
        try:
            boton.setText(anterior)
            boton.setEnabled(True)
        except RuntimeError:  # pragma: no cover - el boton ya no existe
            pass

    # ============================================================= IP publica
    def _consultar_ip_publica(self) -> None:
        self.public_button.setEnabled(False)
        self.public_address.setText("Consultando...")

        def work(*, context) -> str:
            context.progress("Consultando la IP publica...")
            return netinfo.public_ip()

        def done(direccion: str) -> None:
            self.public_button.setEnabled(True)
            if not direccion:
                self.public_address.setText("No se pudo averiguar (¿hay conexion?)")
                return
            self._ip_publica = direccion
            self._cargar_internet()
            # Con la IP en la mano ya se puede decir si el nombre apunta aqui.
            self._cargar_ddns()

        def failed(message: str, _details: str) -> None:
            self.public_button.setEnabled(True)
            self.public_address.setText("No se pudo averiguar")
            logger.warning("No se pudo consultar la IP publica: %s", message)

        self.runner.submit("Consultando la IP publica", work, on_finished=done, on_failed=failed)

    # ============================================================== Bedrock
    def _on_bedrock_toggled(self, activo: bool) -> None:
        if self._cargando or self._spec is None:
            return
        spec = self._spec
        disponible, motivo = self.manager.bedrock_available(spec)
        if activo and not disponible:
            show_error(self, "Bedrock no esta disponible", motivo)
            self._cargando = True
            self.bedrock_check.setChecked(False)
            self._cargando = False
            return
        if activo:
            puerto = spec.bedrock_port
            if not confirm(
                self,
                "Activar jugadores de Bedrock",
                "Se instalan los pluguins Geyser y Floodgate en el servidor y se abre "
                f"el puerto UDP {puerto} para movil, tablet y consola.\n\n"
                "El mundo y los mods no se tocan. El servidor esta detenido, asi que se "
                "aplicara la proxima vez que lo inicies.",
                confirm_label="Activar Bedrock",
            ):
                self._cargando = True
                self.bedrock_check.setChecked(False)
                self._cargando = False
                return

        def work(*, context) -> ServerSpec:
            context.progress(
                "Activando Bedrock (Geyser + Floodgate)..." if activo else "Desactivando Bedrock..."
            )
            return self.manager.set_bedrock(spec.id, enabled=activo)

        def done(_spec: ServerSpec) -> None:
            self.changed.emit()
            self._cargar()
            self.bedrock_note.setText(
                self.bedrock_note.text() + " Listo: inicia el servidor para que se descarguen."
            )

        def failed(message: str, details: str) -> None:
            self._cargando = True
            self.bedrock_check.setChecked(not activo)
            self._cargando = False
            show_error(self, "No se pudo cambiar el modo Bedrock", message, details)

        self.runner.submit("Cambiando el modo Bedrock", work, on_finished=done, on_failed=failed)

    def apply_bedrock_config(self) -> None:
        """Ajusta Geyser para Floodgate al arrancar (si ya genero su config)."""
        if self._spec is None or not self._spec.bedrock_enabled:
            return
        spec = self._spec
        if not self._running:
            return

        def work(*, context) -> bool:
            return self.manager.apply_bedrock_config(spec.id)

        def done(cambiado: bool) -> None:
            if cambiado:
                self.bedrock_note.setText(
                    "Geyser ya esta configurado para Floodgate. Reinicia el servidor "
                    "para que los jugadores de Bedrock entren sin cuenta de Java."
                )

        self.runner.submit(
            "Ajustando Geyser", work, on_finished=done, on_failed=lambda *_: None,
            track_busy=False,
        )

    # ================================================================ guardar
    def _save(self) -> None:
        if self._spec is None:
            return
        spec = self._spec
        premium = self.premium.isChecked()
        if not premium and not confirm(
            self,
            "Desactivar la verificacion de cuentas",
            "Vas a permitir que entren jugadores sin licencia.\n\n"
            + _AVISO_SIN_PREMIUM
            + "\n\n¿Seguro que quieres hacerlo?",
            confirm_label="Permitir sin licencia",
            destructive=True,
        ):
            return
        aviso_reinicio = (
            "\n\nEl servidor esta en marcha: reinicialo para que el cambio surta efecto."
            if self._running
            else ""
        )

        def work(*, context) -> bool:
            context.progress("Guardando el modo de cuentas...")
            props = self.manager.properties(spec.id)
            props.set("online-mode", "true" if premium else "false")
            self.manager.save_properties(spec.id, props)
            return premium

        def done(valor: bool) -> None:
            self.apply_button.setEnabled(False)
            logger.info(
                "online-mode de %s cambiado a %s", spec.id, "true" if valor else "false"
            )
            self._cargar_cuentas()

        def failed(message: str, details: str) -> None:
            show_error(self, "No se pudo guardar el cambio", message, details)

        self.runner.submit("Guardando el modo de cuentas", work, on_finished=done, on_failed=failed)
        self.scope_note.setText(
            "Guardando el modo de cuentas en el fichero de propiedades..."
            + aviso_reinicio
        )

    # ================================================================ utilidad
    def _direcciones(self) -> tuple[str, str]:
        """Direcciones que se muestran (para las pruebas y el portapapeles)."""
        return self.lan_address.text(), self.local_address.text()


__all__ = ["JoinPanel"]
