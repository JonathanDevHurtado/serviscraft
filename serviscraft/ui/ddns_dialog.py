"""Ventana para elegir el nombre con el que se entra al servidor.

En vez de dar a los amigos una IP (``83.54.12.7:25565``), se les da un nombre
(``reinotrebol.duckdns.org:25565``): es mas facil de recordar, se puede escribir
sin errores y no revela donde vives. El nombre lo resuelve internet y DuckDNS se
encarga de mantenerlo apuntando a la IP que tengas en cada momento.

La ventana explica con el boton «?» lo que hay que hacer (crear la cuenta, pegar
el token, guardar) y avisa de lo unico que un nombre **no** puede hacer: abrir el
puerto del router. Las comprobaciones de DNS y las llamadas a DuckDNS se hacen en
segundo plano: la ventana nunca se queda congelada mientras espera a internet.
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..core import ddns, netinfo
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from .common import (
    Chip,
    FlowRow,
    SectionCard,
    WrappingLabel,
    hint_label,
    make_button,
)
from .dialogs import confirm, show_error
from .mc_icons import icono_mundo, icono_si
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

#: Ancho minimo comodo para el formulario; por debajo, los botones se envuelven.
_ANCHO_MINIMO = 560
#: Ancho con el que se abre: las tres acciones principales caben en una fila.
_ANCHO_INICIAL = 720


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
        #: Hay una operacion de guardado en curso: se bloquea el cierre para no
        #: perder el resultado (la pestana se refresca al cerrar la ventana).
        self._busy = False
        #: Numero de la comprobacion de DNS en curso. Al cambiar el nombre se
        #: incrementa para descartar resultados viejos que lleguen tarde.
        self._check_seq = 0
        self._cargando = False

        self.setWindowTitle(f"Nombre para entrar · {spec.name}")
        self.setModal(False)
        self.setMinimumWidth(_ANCHO_MINIMO)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.intro = hint_label(
            "Dale un nombre propio a tu servidor para que tus amigos no tengan que "
            "escribir tu IP. Se escribe igual que una direccion de Minecraft."
        )
        layout.addWidget(self.intro)

        layout.addWidget(self._build_form())
        layout.addWidget(self._build_status())
        layout.addWidget(self._build_actions())

        self._cargar()
        self._ajustar_tamano()

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
        self.subdomain_input.setClearButtonEnabled(True)
        self.subdomain_input.setToolTip(
            "Solo letras, numeros y guiones. Es la parte que hay delante de .duckdns.org"
        )
        self.subdomain_input.textChanged.connect(self._on_changed)
        fila.addWidget(self.subdomain_input, 1)
        sufijo = QLabel(f".{ddns.DUCKDNS_DOMAIN}")
        sufijo.setObjectName("Hint")
        fila.addWidget(sufijo)
        cuerpo.addLayout(fila)

        self.name_error = hint_label("")
        self.name_error.setObjectName("FieldError")
        self.name_error.setVisible(False)
        cuerpo.addWidget(self.name_error)

        # La direccion resultante se muestra en un campo de solo lectura: se
        # puede seleccionar y copiar, y nunca se recorta en vertical como una
        # etiqueta con relleno.
        self.preview = QLineEdit()
        self.preview.setObjectName("DdnsPreview")
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Escribe un nombre para ver la direccion")
        self.preview.setToolTip("Esta es la direccion que se escribe en Minecraft")
        cuerpo.addWidget(self.preview)

        token_fila = QHBoxLayout()
        token_fila.setSpacing(6)
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText("Token de DuckDNS (se guarda en tu equipo)")
        self.token_input.setToolTip(
            "La clave larga que te da www.duckdns.org. Se guarda con los datos "
            "privados del servidor y no se envia a ningun sitio salvo a DuckDNS."
        )
        self.token_input.textChanged.connect(self._on_changed)
        token_fila.addWidget(self.token_input, 1)
        self.ver_token = make_button("Ver", tooltip="Mostrar u ocultar el token")
        self.ver_token.setCheckable(True)
        self.ver_token.setObjectName("TokenToggle")
        self.ver_token.toggled.connect(self._ver_token)
        token_fila.addWidget(self.ver_token)
        cuerpo.addLayout(token_fila)

        self.token_error = hint_label("")
        self.token_error.setObjectName("FieldError")
        self.token_error.setVisible(False)
        cuerpo.addWidget(self.token_error)

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
        card = SectionCard("Estado", pixmap=icono_si(18))
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

    def _build_actions(self) -> QWidget:
        """Acciones principales y pie, cada grupo en su propia fila.

        Los botones van en un ``FlowRow``: con sitio quedan en una linea y, en
        una ventana estrecha, pasan a la siguiente en vez de recortarse.
        """
        contenedor = QWidget()
        caja = QVBoxLayout(contenedor)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(8)

        self.actions = FlowRow(spacing=8)
        self.save_button = make_button(
            "Guardar y actualizar",
            icon_names=("document-save",),
            accent=True,
            tooltip="Guarda el nombre y avisa a DuckDNS de tu IP publica",
        )
        self.save_button.clicked.connect(lambda: self._guardar())
        self.actions.add(self.save_button)

        self.update_button = make_button(
            "Actualizar direccion",
            icon_names=("view-refresh",),
            tooltip="Vuelve a avisar a DuckDNS de tu IP publica",
        )
        self.update_button.clicked.connect(lambda: self._actualizar_direccion())
        self.actions.add(self.update_button)

        self.check_button = make_button(
            "Comprobar",
            icon_names=("dialog-ok-apply",),
            tooltip="Averigua a que direccion apunta el nombre ahora mismo",
        )
        self.check_button.clicked.connect(lambda: self._comprobar())
        self.actions.add(self.check_button)
        caja.addWidget(self.actions)

        pie = QHBoxLayout()
        pie.setSpacing(8)
        self.clear_button = make_button(
            "Quitar nombre",
            icon_names=("edit-delete",),
            danger=True,
            tooltip="Vuelve a entrar con la IP publica y el puerto",
        )
        self.clear_button.clicked.connect(lambda: self._quitar())
        pie.addWidget(self.clear_button)
        pie.addStretch(1)
        self.close_button = make_button("Cerrar", icon_names=("window-close",))
        self.close_button.clicked.connect(self.close)
        pie.addWidget(self.close_button)
        caja.addLayout(pie)
        return contenedor

    # =================================================================== datos
    def _cargar(self, *, comprobar: bool = True) -> None:
        """Rellena el formulario con lo guardado, sin tocar la red."""
        self._cargando = True
        bloqueos = [
            QSignalBlocker(widget)
            for widget in (
                self.subdomain_input,
                self.token_input,
                self.auto_check,
                self.ver_token,
            )
        ]
        try:
            self.subdomain_input.setText(self.spec.ddns_subdomain)
            self.token_input.setText(self.spec.ddns_token)
            self.auto_check.setChecked(bool(self.spec.ddns_auto))
            self.ver_token.setChecked(False)
            self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.ver_token.setText("Ver")
        finally:
            del bloqueos
            self._cargando = False
        self._on_changed()
        if comprobar and self.spec.ddns_configured:
            self._comprobar(silencioso=True)
        elif not self.spec.ddns_configured:
            self._pintar_status(None)

    def _texto_nombre(self) -> str:
        return self.subdomain_input.text().strip()

    def _direccion(self) -> str:
        """Direccion completa que se escribira en Minecraft (vacia si no vale)."""
        try:
            return f"{ddns.hostname(self._texto_nombre())}:{self.spec.port}"
        except ServiscraftError:
            return ""

    def _nombre_valido(self) -> str:
        """Nombre normalizado o cadena vacia si lo escrito no vale."""
        try:
            return ddns.validate_subdomain(self._texto_nombre())
        except ServiscraftError:
            return ""

    def _token_valido(self) -> str:
        try:
            return ddns.validate_token(self.token_input.text())
        except ServiscraftError:
            return ""

    def _hay_cambios(self) -> bool:
        """True si el formulario difiere de lo que hay guardado."""
        nombre = self._nombre_valido() or self._texto_nombre().lower()
        return (
            nombre != self.spec.ddns_subdomain
            or self._token_valido() != self.spec.ddns_token
            or self.auto_check.isChecked() != bool(self.spec.ddns_auto)
        )

    def _on_changed(self, *_args: object) -> None:
        if self._cargando:
            return

        nombre = self._texto_nombre()
        nombre_valido = self._nombre_valido()
        error_nombre = ""
        if nombre and not nombre_valido:
            try:
                ddns.validate_subdomain(nombre)
            except ServiscraftError as exc:
                error_nombre = str(exc)
        self.name_error.setText(error_nombre)
        self.name_error.setVisible(bool(error_nombre))

        direccion = f"{nombre_valido}.{ddns.DUCKDNS_DOMAIN}:{self.spec.port}" if nombre_valido else ""
        self.preview.setText(direccion)
        self.preview.setCursorPosition(0)
        self.preview.setToolTip(
            f"Se escribira en Minecraft: {direccion}"
            if direccion
            else "Escribe un nombre valido para ver la direccion"
        )

        token = self.token_input.text().strip()
        error_token = ""
        if token and not self._token_valido():
            try:
                ddns.validate_token(token)
            except ServiscraftError as exc:
                error_token = str(exc)
        elif not token and (nombre_valido or self.auto_check.isChecked()):
            error_token = (
                "Falta el token de DuckDNS: sin el no se puede actualizar la direccion."
            )
        if self.auto_check.isChecked() and not token:
            error_token = "Para mantener al dia hace falta el token de DuckDNS."
        self.token_error.setText(error_token)
        self.token_error.setVisible(bool(error_token))

        # Al cambiar el nombre, cualquier comprobacion en curso queda obsoleta.
        self._check_seq += 1

        formulario_ok = bool(nombre_valido) and bool(self._token_valido()) and not error_token
        self.save_button.setEnabled(formulario_ok and not self._busy)
        self.update_button.setEnabled(
            self.spec.ddns_configured
            and not self._hay_cambios()
            and not self._busy
            and not error_token
        )
        self.update_button.setToolTip(
            "Guarda primero los cambios y despues podras actualizar la direccion"
            if self.spec.ddns_configured and self._hay_cambios()
            else "Vuelve a avisar a DuckDNS de tu IP publica"
        )
        self.check_button.setEnabled(bool(nombre_valido) and not self._busy)
        self.clear_button.setEnabled(self.spec.ddns_configured and not self._busy)

    # ================================================================== estado
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

    def _pintar_guardado(self, *, actualizado: bool) -> None:
        if actualizado:
            self.state_chip.set_text("Guardado")
            self.state_chip.set_tone("ok")
            self.state_chip.setToolTip("DuckDNS ha recibido la nueva direccion")
            self.status_note.setText(
                "DuckDNS ha recibido la nueva direccion. Puede tardar unos minutos en "
                "verse desde internet; pulsa «Comprobar» para consultarlo ahora."
            )
        else:
            self.state_chip.set_text("Guardado sin actualizar")
            self.state_chip.set_tone("warn")
            self.state_chip.setToolTip("El nombre se guardo, pero no se aviso a DuckDNS")
            self.status_note.setText(
                "El nombre se guardo, pero no se pudo avisar a DuckDNS. Revisa la "
                "conexion y pulsa «Actualizar direccion»."
            )

    def _ver_token(self, visible: bool) -> None:
        self.token_input.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.ver_token.setText("Ocultar" if visible else "Ver")

    # ================================================================= acciones
    def _guardar(self) -> None:
        """Guarda el nombre y, si hay token, avisa a DuckDNS de la IP actual."""
        self._ejecutar_guardado(descripcion="Guardando el nombre del servidor")

    def _actualizar_direccion(self) -> None:
        """Reenvia a DuckDNS la IP actual sin cambiar el nombre guardado."""
        self._ejecutar_guardado(descripcion="Actualizando la direccion")

    def _ejecutar_guardado(self, *, descripcion: str) -> None:
        if self._busy or not self._formulario_listo():
            return
        nombre = self._nombre_valido()
        token = self._token_valido()
        auto = self.auto_check.isChecked()
        self._set_busy(True)
        self.state_chip.set_text("Guardando...")
        self.state_chip.set_tone("warn")
        self.status_note.setText("Guardando el nombre y avisando a DuckDNS. Un momento...")

        def work(*, context) -> tuple[ServerSpec, str]:
            context.progress("Guardando el nombre del servidor...")
            spec = self.manager.configure_ddns(
                self.spec.id, subdomain=nombre, token=token, auto=auto
            )
            aviso = ""
            if token:
                context.progress("Avisando a DuckDNS de tu IP publica...")
                try:
                    # Sin IP explicita, DuckDNS usa la direccion de salida de la
                    # peticion: si el operador la ha cambiado, se corrige sola.
                    self.manager.ddns_update(spec.id, public_ip="")
                except ServiscraftError as exc:
                    aviso = str(exc)
            return spec, aviso

        def done(resultado: tuple[ServerSpec, str]) -> None:
            spec, aviso = resultado
            self.spec = spec
            self._set_busy(False)
            self._cargar(comprobar=False)
            self._pintar_guardado(actualizado=not aviso)
            logger.info("Nombre personalizado guardado para %s", spec.id)
            if aviso:
                show_error(
                    self,
                    "El nombre se guardo, pero DuckDNS no respondio",
                    aviso,
                )

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            self._on_changed()
            self.state_chip.set_text("Error al guardar")
            self.state_chip.set_tone("bad")
            self.state_chip.setToolTip(message)
            self.status_note.setText(message)
            show_error(self, "No se pudo guardar el nombre", message, details)

        self.runner.submit(
            descripcion,
            work,
            on_finished=done,
            on_failed=failed,
        )

    def _formulario_listo(self) -> bool:
        """Comprueba el formulario y lleva el foco al primer problema."""
        self._on_changed()
        if not self.save_button.isEnabled():
            if self.name_error.isVisible():
                self.subdomain_input.setFocus()
            elif self.token_error.isVisible():
                self.token_input.setFocus()
            return False
        return True

    def _comprobar(self, *, silencioso: bool = False) -> None:
        if self._busy:
            return
        nombre = self._nombre_valido()
        if not nombre:
            return
        self._check_seq += 1
        secuencia = self._check_seq
        self.check_button.setEnabled(False)
        self.state_chip.set_text("Comprobando...")
        self.state_chip.set_tone("warn")
        self.status_note.setText("Consultando en internet a que direccion apunta el nombre...")

        def work(*, context) -> tuple[ddns.DdnsStatus, str]:
            context.progress("Comprobando a donde apunta el nombre...")
            ip = self._ip_publica or netinfo.public_ip()
            return ddns.check(nombre, public_ip=ip, puerto=self.spec.port), ip

        def done(resultado: tuple[ddns.DdnsStatus, str]) -> None:
            if secuencia != self._check_seq or self._busy:
                return
            status, ip = resultado
            self._ip_publica = ip
            self._pintar_status(status)
            self._on_changed()

        def failed(message: str, details: str) -> None:
            if secuencia != self._check_seq or self._busy:
                return
            self.state_chip.set_text("Sin comprobar")
            self.state_chip.set_tone("warn")
            self.state_chip.setToolTip(message)
            self.status_note.setText(message)
            self._on_changed()
            if not silencioso:
                show_error(self, "No se pudo comprobar el nombre", message, details)

        self.runner.submit(
            "Comprobando el nombre",
            work,
            on_finished=done,
            on_failed=failed,
            track_busy=False,
        )

    def _quitar(self) -> None:
        if self._busy:
            return
        if not confirm(
            self,
            "Quitar el nombre personalizado",
            "Se dejara de usar el nombre y se volvera a entrar con la IP publica y el "
            "puerto.\n\nEl servidor, el mundo y los mods no se tocan.",
            confirm_label="Quitar nombre",
            destructive=True,
        ):
            return

        self._set_busy(True)
        self.state_chip.set_text("Quitando...")
        self.state_chip.set_tone("warn")
        self.status_note.setText("Quitando el nombre personalizado...")

        def work(*, context) -> ServerSpec:
            context.progress("Quitando el nombre...")
            return self.manager.configure_ddns(self.spec.id, subdomain="")

        def done(spec: ServerSpec) -> None:
            self.spec = spec
            self._set_busy(False)
            self._cargar(comprobar=False)
            self._pintar_status(None)

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            self._on_changed()
            self.state_chip.set_text("Error al quitar")
            self.state_chip.set_tone("bad")
            self.state_chip.setToolTip(message)
            self.status_note.setText(message)
            show_error(self, "No se pudo quitar el nombre", message, details)

        self.runner.submit("Quitando el nombre", work, on_finished=done, on_failed=failed)

    # ================================================================ ventana
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.subdomain_input,
            self.token_input,
            self.auto_check,
            self.ver_token,
            self.close_button,
        ):
            widget.setEnabled(not busy)
        self._on_changed()

    def _ajustar_tamano(self) -> None:
        """Abre con sitio suficiente sin pasarse del borde de la pantalla.

        ``QDialog`` limita el tamano automatico a dos tercios de la pantalla; en
        un monitor pequeno eso dejaba los botones fuera de la ventana. Aqui se
        elige un tamano que quepa y, si hace falta, los botones se envuelven.
        """
        pantalla = self.screen() or QApplication.primaryScreen()
        disponible = pantalla.availableGeometry() if pantalla is not None else None
        sugerido = self.sizeHint()
        ancho = max(_ANCHO_INICIAL, sugerido.width())
        alto = sugerido.height()
        if disponible is not None:
            ancho = min(ancho, max(_ANCHO_MINIMO, int(disponible.width() * 0.92)))
            alto = min(alto, max(380, int(disponible.height() * 0.92)))
        self.resize(ancho, alto)

    def reject(self) -> None:  # noqa: N802 - API de Qt
        if self._busy:
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if self._busy:
            event.ignore()
            self.status_note.setText(
                "Espera a que termine la operacion antes de cerrar la ventana."
            )
            return
        super().closeEvent(event)


__all__ = ["DdnsDialog"]
