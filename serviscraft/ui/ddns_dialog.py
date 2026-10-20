"""Ventana para elegir el nombre con el que se entra al servidor.

En vez de dar a los amigos una IP (``83.54.12.7:25565``), se les da un nombre
(``reinotrebol.duckdns.org:25565``): es mas facil de recordar, se puede escribir
sin errores y no revela donde vives. El nombre lo resuelve internet y DuckDNS se
encarga de mantenerlo apuntando a la IP que tengas en cada momento.

La ventana explica en tres pasos lo que hay que hacer (crear la cuenta, pegar el
token, guardar) con el boton «?», y avisa de lo unico que un nombre **no** puede
hacer: abrir el puerto del router.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import ddns
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from .common import (
    Chip,
    SectionCard,
    WrappingLabel,
    hint_label,
    icon_pixmap,
    make_button,
)
from .dialogs import confirm, show_error
from .mc_icons import icono_mundo
from .tasks import TaskRunner

logger = get_logger("ui.ddns")

#: Explicacion completa del boton «?» (texto sin acentos, como el resto de la UI).
_AYUDA = (
    "<b>Para que sirve</b><br>Es el nombre con el que tus amigos entran al "
    "servidor en vez de tu IP: mas facil de recordar, igual en cada partida y sin "
    "ensenar donde vives.<br><br>"
    "<b>Como se consigue (5 minutos, gratis)</b><br>"
    "1. Entra en <b>www.duckdns.org</b> y accede con tu cuenta de Google o "
    "GitHub.<br>"
    "2. En «add domain» escribe el nombre que quieras (por ejemplo "
    "<i>reinotrebol</i>) y pulsa «add domain».<br>"
    "3. La pagina te muestra tu <b>token</b> (una clave larga). Copialo y pegalo "
    "aqui.<br>"
    "4. Elige el mismo nombre aqui y pulsa «Guardar y actualizar».<br><br>"
    "<b>Muy importante</b><br>El nombre solo traduce tu direccion: <b>no abre el "
    "puerto</b>. Para que entren desde otra ciudad, el router tiene que reenviar "
    "el puerto del juego a este equipo (pestana «Unirse», recuadro 3).<br><br>"
    "<b>Consejo</b><br>Marca «Mantener al dia»: cada vez que inicies el servidor, "
    "Serviscraft comprueba si tu IP ha cambiado y avisa a DuckDNS por ti, asi el "
    "nombre nunca deja de funcionar."
)


class DdnsDialog(QDialog):
    """Configura el nombre personalizado (DuckDNS) de un servidor."""

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        spec: ServerSpec,
        *,
        public_ip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self.spec = spec
        self._ip_publica = public_ip
        self._status: ddns.DdnsStatus | None = None

        self.setWindowTitle(f"Nombre para entrar · {spec.name}")
        self.setMinimumWidth(520)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.intro = hint_label(
            "Dale un nombre propio a tu servidor para que tus amigos no tengan que "
            "escribir tu IP."
        )
        layout.addWidget(self.intro)

        layout.addWidget(self._build_form())
        layout.addWidget(self._build_status())

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.save_button = make_button(
            "Guardar y actualizar",
            icon_names=("document-save",),
            accent=True,
            tooltip="Guarda el nombre y avisa a DuckDNS de tu IP publica",
        )
        self.save_button.clicked.connect(self._guardar)
        self.buttons.addWidget(self.save_button)

        self.update_button = make_button(
            "Actualizar direccion",
            icon_names=("view-refresh",),
            tooltip="Vuelve a avisar a DuckDNS de tu IP publica",
        )
        self.update_button.clicked.connect(lambda: self._actualizar(el_nombre=False))
        self.buttons.addWidget(self.update_button)

        self.check_button = make_button(
            "Comprobar",
            icon_names=("dialog-ok-apply",),
            tooltip="Averigua a que direccion apunta el nombre ahora mismo",
        )
        self.check_button.clicked.connect(self._comprobar)
        self.buttons.addWidget(self.check_button)

        self.clear_button = make_button(
            "Quitar nombre",
            icon_names=("edit-delete",),
            danger=True,
            tooltip="Vuelve a entrar con la IP publica y el puerto",
        )
        self.clear_button.clicked.connect(self._quitar)
        self.buttons.addWidget(self.clear_button)
        self.buttons.addStretch(1)

        self.close_button = make_button("Cerrar", icon_names=("window-close",))
        self.close_button.clicked.connect(self.close)
        self.buttons.addWidget(self.close_button)
        layout.addLayout(self.buttons)

        self._cargar()

    # ============================================================== construccion
    def _build_form(self) -> SectionCard:
        card = SectionCard(
            "Tu nombre",
            pixmap=icono_mundo(18),
            help_title="Como consigo un nombre propio",
            help_text=_AYUDA,
        )
        cuerpo = card.body()

        fila = QHBoxLayout()
        fila.setSpacing(6)
        self.subdomain_input = QLineEdit()
        self.subdomain_input.setPlaceholderText("reinotrebol")
        self.subdomain_input.setToolTip(
            "Solo letras, numeros y guiones. Es la parte que hay delante de .duckdns.org"
        )
        self.subdomain_input.textChanged.connect(self._on_changed)
        fila.addWidget(self.subdomain_input, 1)
        sufijo = QLabel(f".{ddns.DUCKDNS_DOMAIN}")
        sufijo.setObjectName("Hint")
        fila.addWidget(sufijo)
        cuerpo.addLayout(fila)

        self.preview = WrappingLabel("")
        self.preview.setObjectName("AddressText")
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cuerpo.addWidget(self.preview)

        token_fila = QHBoxLayout()
        token_fila.setSpacing(6)
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText("token de DuckDNS (se guarda en tu equipo)")
        self.token_input.setToolTip(
            "La clave larga que te da www.duckdns.org. Se guarda con los datos "
            "privados del servidor y no se envia a ningun sitio salvo a DuckDNS."
        )
        self.token_input.textChanged.connect(self._on_changed)
        token_fila.addWidget(self.token_input, 1)
        self.ver_token = QPushButton("Ver")
        self.ver_token.setCheckable(True)
        self.ver_token.setToolTip("Mostrar u ocultar el token")
        self.ver_token.toggled.connect(self._ver_token)
        token_fila.addWidget(self.ver_token)
        cuerpo.addLayout(token_fila)

        self.auto_check = QCheckBox("Mantener al dia (actualizar la IP al iniciar el servidor)")
        self.auto_check.setToolTip(
            "Cada vez que inicies el servidor se comprueba si tu IP publica ha cambiado "
            "y se avisa a DuckDNS. Sin esto, si el operador te cambia la IP, el nombre "
            "deja de funcionar hasta que pulses «Actualizar direccion»."
        )
        self.auto_check.toggled.connect(self._on_changed)
        cuerpo.addWidget(self.auto_check)

        cuerpo.addWidget(
            hint_label(
                "El token es la llave de tu nombre: no lo compartas. Serviscraft lo guarda "
                "solo en este equipo (fichero privado del servidor) y nunca lo escribe en el "
                "registro."
            )
        )
        return card

    def _build_status(self) -> SectionCard:
        card = SectionCard("Estado", pixmap=icono_mundo(18))
        cuerpo = card.body()
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.state_chip = Chip("Sin configurar", tone="warn")
        fila.addWidget(self.state_chip)
        fila.addStretch(1)
        cuerpo.addLayout(fila)
        self.status_note = WrappingLabel("")
        self.status_note.setObjectName("Hint")
        cuerpo.addWidget(self.status_note)
        return card

    # =================================================================== datos
    def _cargar(self) -> None:
        self.subdomain_input.setText(self.spec.ddns_subdomain)
        self.token_input.setText(self.spec.ddns_token)
        self.auto_check.setChecked(bool(self.spec.ddns_auto))
        self.update_button.setEnabled(self.spec.ddns_configured)
        self.clear_button.setEnabled(self.spec.ddns_configured)
        self._on_changed()
        self._pintar_status(
            ddns.check(
                self.spec.ddns_subdomain,
                public_ip=self._ip_publica,
                puerto=self.spec.port,
            )
            if self.spec.ddns_configured
            else None
        )

    def _texto_nombre(self) -> str:
        return self.subdomain_input.text().strip()

    def _direccion(self) -> str:
        """Direccion completa que se escribira en Minecraft (cadena vacia si no vale)."""
        try:
            return f"{ddns.hostname(self._texto_nombre())}:{self.spec.port}"
        except ServiscraftError:
            return ""

    def _on_changed(self, *_args: object) -> None:
        nombre = self._texto_nombre()
        direccion = self._direccion()
        self.preview.setText(direccion or "Escribe un nombre arriba para ver la direccion.")
        self.save_button.setEnabled(bool(nombre) and bool(self.token_input.text().strip()))
        self.update_button.setEnabled(bool(self.spec.ddns_configured))

    def _pintar_status(self, status: ddns.DdnsStatus | None) -> None:
        self._status = status
        if status is None:
            self.state_chip.set_text("Sin configurar")
            self.state_chip.set_tone("warn")
            self.status_note.setText(
                "Todavia no hay nombre: tus amigos entran con tu IP publica y el puerto."
            )
            return
        tonos = {
            "ok": "ok",
            "otra-ip": "warn",
            "sin-ip": "warn",
            "sin-resolver": "bad",
            "sin-configurar": "warn",
        }
        etiquetas = {
            "ok": "Funcionando",
            "otra-ip": "Apunta a otra IP",
            "sin-ip": "Sin comprobar",
            "sin-resolver": "No responde",
            "sin-configurar": "Sin configurar",
        }
        self.state_chip.set_text(etiquetas.get(status.state, status.state))
        self.state_chip.set_tone(tonos.get(status.state, "warn"))
        self.state_chip.setToolTip(status.detail)
        self.status_note.setText(status.detail)

    def _ver_token(self, visible: bool) -> None:
        self.token_input.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.ver_token.setText("Ocultar" if visible else "Ver")

    # ================================================================= acciones
    def _guardar(self) -> None:
        """Guarda el nombre y, si hay token, avisa a DuckDNS de la IP actual."""
        self._actualizar(el_nombre=True)

    def _actualizar(self, *, el_nombre: bool) -> None:
        nombre = self._texto_nombre()
        token = self.token_input.text().strip()
        auto = self.auto_check.isChecked()

        def work(*, context) -> ServerSpec:
            context.progress("Guardando el nombre del servidor...")
            spec = self.manager.configure_ddns(
                self.spec.id, subdomain=nombre, token=token, auto=auto
            )
            if token:
                context.progress("Avisando a DuckDNS de tu IP publica...")
                self.manager.ddns_update(spec.id, public_ip="")
            return spec

        def done(spec: ServerSpec) -> None:
            self.spec = spec
            self._cargar()
            logger.info("Nombre personalizado guardado para %s", spec.id)

        def failed(message: str, details: str) -> None:
            show_error(self, "No se pudo guardar el nombre", message, details)

        self.runner.submit(
            "Guardando el nombre del servidor" if el_nombre else "Actualizando la direccion",
            work,
            on_finished=done,
            on_failed=failed,
        )

    def _comprobar(self) -> None:
        self.check_button.setEnabled(False)
        self.state_chip.set_text("Comprobando...")
        self.state_chip.set_tone("warn")
        nombre = self._texto_nombre()

        def work(*, context) -> tuple[ddns.DdnsStatus, str]:
            context.progress("Comprobando a donde apunta el nombre...")
            from ..core import netinfo

            ip = self._ip_publica or netinfo.public_ip()
            return ddns.check(nombre, public_ip=ip, puerto=self.spec.port), ip

        def done(resultado: tuple[ddns.DdnsStatus, str]) -> None:
            self.check_button.setEnabled(True)
            status, ip = resultado
            self._ip_publica = ip
            self._pintar_status(status)

        def failed(message: str, details: str) -> None:
            self.check_button.setEnabled(True)
            show_error(self, "No se pudo comprobar el nombre", message, details)

        self.runner.submit("Comprobando el nombre", work, on_finished=done, on_failed=failed)

    def _quitar(self) -> None:
        if not confirm(
            self,
            "Quitar el nombre personalizado",
            "Se dejara de usar el nombre y se volvera a entrar con la IP publica y el "
            "puerto.\n\nEl servidor, el mundo y los mods no se tocan.",
            confirm_label="Quitar nombre",
            destructive=True,
        ):
            return

        def work(*, context) -> ServerSpec:
            context.progress("Quitando el nombre...")
            return self.manager.configure_ddns(self.spec.id, subdomain="")

        def done(spec: ServerSpec) -> None:
            self.spec = spec
            self._cargar()

        def failed(message: str, details: str) -> None:
            show_error(self, "No se pudo quitar el nombre", message, details)

        self.runner.submit("Quitando el nombre", work, on_finished=done, on_failed=failed)


__all__ = ["DdnsDialog"]
