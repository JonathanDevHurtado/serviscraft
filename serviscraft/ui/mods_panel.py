"""Pestana de mods: lo que hay instalado y lo que falta por conseguir.

Muestra la carpeta de mods (o pluguins) del servidor, permite activar y
desactivar sin borrar nada, eliminar, y anadir contenido desde el catalogo de
Modrinth, desde un fichero ``.jar`` del equipo o desde una URL.

Ademas analiza el registro del servidor para detectar los mods que el modpack no
pudo descargar: de cada uno ofrece el enlace a Modrinth, avisa en verde cuando el
fichero ya esta dentro del servidor y permite copiar el ``.jar`` descargado para
poder borrar la descarga original.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import logs, mods
from ..core import icons as iconos_remotos
from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.missing_mods import MissingMod, parse_missing_mods
from ..core.models import ServerSpec, format_bytes
from .catalog_dialog import CatalogDialog
from .common import FlowRow, WrappingLabel, hint_label, make_button, plural, polish_table_header
from .dialogs import ask_text, confirm, show_error, show_info
from .mc_icons import (
    SIZE as ICON_SIZE,
    icono_mod,
    icono_plugin,
    marcar_desactivado,
    pixmap_de_bytes,
)
from .tasks import TaskRunner

logger = get_logger("ui.mods")

#: Color del texto de los mods que ya estan dentro del servidor.
_VERDE = QColor("#3fa34d")


class ModsPanel(QWidget):
    """Mods instalados y mods que faltan del servidor seleccionado."""

    #: Aviso para que la ventana refresque lo que dependa de los ficheros.
    changed = Signal()

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        parent: QWidget | None = None,
        *,
        files_provider=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self._spec: ServerSpec | None = None
        self._running = False
        self._inventory: mods.ModsInventory | None = None
        self._missing: list[MissingMod] = []
        #: Permite a las pruebas inyectar un selector de ficheros.
        self._files_dialog = files_provider or QFileDialog.getOpenFileName

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.actions_row = FlowRow(spacing=8)
        self.refresh_button = make_button(
            "Refrescar",
            icon_names=("view-refresh",),
            tooltip="Volver a leer la carpeta de mods del servidor",
        )
        self.refresh_button.clicked.connect(self.refresh)
        self.actions_row.add(self.refresh_button)

        self.catalog_button = make_button(
            "Catalogo...",
            icon_names=("system-search", "download"),
            accent=True,
            tooltip="Buscar contenido en Modrinth e instalarlo con un clic",
        )
        self.catalog_button.clicked.connect(self._open_catalog)
        self.actions_row.add(self.catalog_button)

        self.local_button = make_button(
            "Desde archivo...",
            icon_names=("document-open",),
            tooltip="Copiar un .jar, .zip o .mrpack que ya tengas en el equipo",
        )
        self.local_button.clicked.connect(self._add_local)
        self.actions_row.add(self.local_button)

        self.url_button = make_button(
            "Desde enlace...",
            icon_names=("insert-link",),
            tooltip="Descargar el archivo desde una direccion http o https",
        )
        self.url_button.clicked.connect(self._add_url)
        self.actions_row.add(self.url_button)

        self.toggle_button = make_button(
            "Activar",
            icon_names=("object-select",),
            tooltip="Activar o desactivar sin borrar el fichero",
        )
        self.toggle_button.clicked.connect(self._toggle_selected)
        self.actions_row.add(self.toggle_button)

        self.delete_button = make_button(
            "Eliminar",
            icon_names=("edit-delete", "user-trash"),
            danger=True,
            tooltip="Borrar el fichero del disco (no se puede deshacer)",
        )
        self.delete_button.clicked.connect(self._delete_selected)
        self.actions_row.add(self.delete_button)
        layout.addWidget(self.actions_row)

        # Leyenda con los iconos de verdad: la lista se entiende de un vistazo.
        self.legend = FlowRow(spacing=14)
        layout.addWidget(self.legend)

        self.status = hint_label("")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Fichero", "Estado", "Origen", "Tamano"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        # Cada fila lleva el icono del proyecto (o el del tipo de contenido), asi
        # que las filas son un poco mas altas que el texto.
        self.table.verticalHeader().setDefaultSectionSize(ICON_SIZE + 8)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(lambda _index: self._toggle_selected())
        polish_table_header(self.table)
        self.table.setMinimumHeight(160)
        layout.addWidget(self.table, 1)

        # ------------------------------------------------------- mods que faltan
        self.missing_title = QLabel("Mods que faltan")
        self.missing_title.setObjectName("SectionTitle")
        layout.addWidget(self.missing_title)

        self.missing_hint = hint_label(
            "Analiza el registro del servidor para ver que mods no pudo descargar el "
            "modpack. De cada uno se muestra su enlace de Modrinth y se avisa en verde "
            "cuando el fichero ya esta dentro del servidor."
        )
        layout.addWidget(self.missing_hint)

        self.missing_actions = FlowRow(spacing=8)
        self.analyze_button = make_button(
            "Buscar los que faltan",
            icon_names=("system-search",),
            tooltip="Lee el registro del servidor y busca los mods que el modpack no pudo descargar",
        )
        self.analyze_button.clicked.connect(self.analyze_logs)
        self.missing_actions.add(self.analyze_button)

        self.open_link_button = make_button(
            "Ver en Modrinth",
            icon_names=("internet-web-browser",),
            tooltip="Abrir en el navegador la pagina del mod que falta",
        )
        self.open_link_button.clicked.connect(self._open_missing_link)
        self.missing_actions.add(self.open_link_button)

        self.copy_button = make_button(
            "Copiar aqui...",
            icon_names=("document-save",),
            accent=True,
            tooltip="Copiar el .jar descargado dentro del servidor (y poder borrar la descarga)",
        )
        self.copy_button.clicked.connect(self._copy_missing_file)
        self.missing_actions.add(self.copy_button)
        layout.addWidget(self.missing_actions)

        self.missing_table = QTableWidget(0, 3)
        self.missing_table.setHorizontalHeaderLabels(["Mod", "Estado", "Enlace"])
        self.missing_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.missing_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.missing_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.missing_table.verticalHeader().setVisible(False)
        self.missing_table.setAlternatingRowColors(True)
        self.missing_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.missing_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.missing_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.missing_table.setMaximumHeight(150)
        self.missing_table.setMinimumHeight(80)
        self.missing_table.itemSelectionChanged.connect(self._update_missing_actions)
        self.missing_table.doubleClicked.connect(lambda _index: self._open_missing_link())
        polish_table_header(self.missing_table)
        layout.addWidget(self.missing_table, 1)

        self.empty = WrappingLabel("Selecciona un servidor para ver sus mods.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.set_server(None, running=False)

    def _leyenda(self, icono: QPixmap, texto: str) -> QWidget:
        """Icono + palabra: explica la lista de un vistazo (tambien para niños)."""
        caja = QWidget()
        fila = QHBoxLayout(caja)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(6)
        imagen = QLabel()
        imagen.setPixmap(icono)
        fila.addWidget(imagen)
        letra = QLabel(texto)
        letra.setObjectName("Hint")
        fila.addWidget(letra)
        return caja

    def _rellenar_leyenda(self, es_pluguins: bool) -> None:
        """Explica solo los iconos que puede tener este servidor."""
        self.legend.clear()
        if es_pluguins:
            self.legend.add(self._leyenda(icono_plugin(), "pluguin"))
        else:
            self.legend.add(self._leyenda(icono_mod(), "mod"))
        self.legend.add(self._leyenda(marcar_desactivado(icono_mod()), "desactivado (no se borra)"))

    # ================================================================= API
    def set_server(self, spec: ServerSpec | None, *, running: bool = False) -> None:
        cambio = spec is None or self._spec is None or self._spec.id != spec.id
        cambio_estado = cambio or self._running != running
        if cambio:
            self.table.setRowCount(0)
            self.missing_table.setRowCount(0)
            self._missing = []
            self.status.clear()
        self._spec = spec
        self._running = running
        if spec is None:
            self._inventory = None
        else:
            self._inventory = mods.ModsInventory(
                self.manager.store,
                spec.id,
                folder=mods.folder_for(spec),
                modpack=bool(spec.modpack) or spec.type.value == "MODRINTH",
            )
        has_server = spec is not None
        if has_server:
            self._rellenar_leyenda(mods.folder_for(spec) == "plugins")
        for widget in (
            self.actions_row,
            self.legend,
            self.status,
            self.table,
            self.missing_title,
            self.missing_hint,
            self.missing_actions,
            self.missing_table,
        ):
            widget.setVisible(has_server)
        self.empty.setVisible(not has_server)
        if has_server and cambio_estado:
            self.refresh()

    def refresh(self) -> None:
        """Vuelve a leer la carpeta de mods del servidor."""
        if self._inventory is None or self._spec is None:
            return
        inventario = self._inventory
        try:
            entradas = inventario.list_mods()
        except ServiscraftError as exc:  # pragma: no cover - carpeta ilegible
            show_error(self, "No se pudieron leer los mods", str(exc))
            return
        self.table.setRowCount(0)
        es_pluguins = mods.folder_for(self._spec) == "plugins"
        for entrada in entradas:
            row = self.table.rowCount()
            self.table.insertRow(row)
            nombre = QTableWidgetItem(self._icono_entrada(entrada, es_pluguins), entrada.filename)
            nombre.setData(Qt.ItemDataRole.UserRole, entrada.filename)
            detalle = entrada.title or entrada.base_name
            nombre.setToolTip(
                f"{entrada.filename}\n{detalle}\n"
                f"{'Activo' if entrada.enabled else 'Desactivado (el fichero sigue en el disco)'}"
            )
            if not entrada.enabled:
                nombre.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 0, nombre)
            self.table.setItem(row, 1, QTableWidgetItem("activo" if entrada.enabled else "desactivado"))
            self.table.setItem(row, 2, QTableWidgetItem(entrada.origin_label))
            tamano = QTableWidgetItem(entrada.size_label)
            tamano.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, tamano)
        self._update_status(entradas)
        self._update_actions()
        self._update_missing_rows()

    def _icono_entrada(self, entrada, es_pluguins: bool) -> QIcon:
        """Icono del fichero: el del proyecto si se conoce, si no el del tipo.

        Es lo mismo que hace Prism Launcher: cada mod o pluguin se ve con su
        icono en la lista, y los que no se han instalado desde el catalogo llevan
        el simbolo generico (pieza de puzle para mods, enchufe para pluguins).
        """
        generico = icono_plugin() if es_pluguins else icono_mod()
        icono = generico
        if entrada.icon_url:
            datos = iconos_remotos.cached_bytes(entrada.icon_url)
            if datos:
                real = pixmap_de_bytes(datos, ICON_SIZE)
                if not real.isNull():
                    icono = real
        if not entrada.enabled:
            icono = marcar_desactivado(icono)
        return QIcon(icono)

    def _update_status(self, entradas) -> None:
        if self._spec is None:
            return
        carpeta = mods.folder_for(self._spec)
        activos = sum(1 for entrada in entradas if entrada.enabled)
        desactivados = len(entradas) - activos
        total = sum(entrada.size_bytes for entrada in entradas)
        partes = [
            f"{plural(len(entradas), 'fichero', 'ficheros')} en «{carpeta}»: "
            f"{plural(activos, 'activo', 'activos')}, "
            f"{plural(desactivados, 'desactivado', 'desactivados')} "
            f"({format_bytes(total)})."
        ]
        if not entradas:
            partes.append(
                "La carpeta esta vacia. Pulsa «Catalogo...» para instalar contenido de Modrinth."
            )
        if self._running:
            partes.append(
                "El servidor esta en marcha: detenlo para que los cambios surtan efecto."
            )
        self.status.setText(" ".join(partes))

    # =============================================================== acciones
    def _selected_filename(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole) or item.text()

    def _update_actions(self) -> None:
        hay_seleccion = self._selected_filename() is not None
        permitido = hay_seleccion and not self._running
        self.toggle_button.setEnabled(permitido)
        self.delete_button.setEnabled(permitido)
        self.catalog_button.setEnabled(not self._running)
        self.local_button.setEnabled(not self._running)
        self.url_button.setEnabled(not self._running)
        self.refresh_button.setEnabled(True)
        # El boton dice lo que va a hacer con el fichero elegido: mas claro que
        # un «Activar o desactivar» que obliga a pensar.
        if not hay_seleccion:
            self.toggle_button.setText("Activar/Desactivar")
        else:
            self.toggle_button.setText("Desactivar" if self._selected_enabled() else "Activar")
        self.toggle_button.setToolTip(
            "Deten el servidor para cambiar los mods."
            if self._running
            else "Activar o desactivar sin borrar el fichero"
        )

    def _selected_enabled(self) -> bool:
        """Esta activo el fichero elegido? (para que el boton diga que hara)."""
        fila = self.table.currentRow()
        if fila < 0:
            return True
        estado = self.table.item(fila, 1)
        return estado is None or estado.text().strip().lower() == "activo"

    def _open_catalog(self) -> None:
        if self._spec is None:
            return
        mode = mods.folder_for(self._spec)
        dialog = CatalogDialog(self.manager, self.runner, self._spec, mode, self)
        dialog.exec()
        if dialog.installed:
            show_info(
                self,
                "Contenido instalado",
                "Se ha instalado:\n\n"
                + "\n".join(f"  • {nombre}" for nombre in dialog.installed)
                + "\n\nReinicia el servidor para aplicarlo.",
            )
        self.refresh()
        self.changed.emit()

    def _add_local(self) -> None:
        if self._inventory is None:
            return
        ruta, _filtro = self._files_dialog(
            self,
            "Elige el mod o pluguin que quieres copiar",
            "",
            "Contenido de Minecraft (*.jar *.zip *.mrpack);;Todos los ficheros (*)",
        )
        if not ruta:
            return
        try:
            destino = self._inventory.add_file(Path(ruta))
        except ServiscraftError as exc:
            show_error(self, "No se pudo anadir el fichero", str(exc))
            return
        logger.info("Mod local anadido: %s", destino)
        self.refresh()
        self.changed.emit()

    def _add_url(self) -> None:
        if self._inventory is None:
            return
        url = ask_text(
            self,
            "Anadir un mod desde una URL",
            "Direccion http o https del fichero .jar:\n\n"
            "Se descarga directamente a la carpeta del servidor y se comprueba que "
            "sea un JAR o ZIP valido.",
            placeholder="https://ejemplo.com/mi-mod.jar",
        )
        if not url:
            return
        inventario = self._inventory
        spec = self._spec
        assert spec is not None

        def work(*, context) -> str:
            context.progress("Descargando el mod...")
            destino = inventario.add_url(
                url,
                files=self.manager.files(spec.id),
                on_progress=lambda hecho, total: context.progress_step(hecho, total),
                should_cancel=lambda: context.cancelled,
            )
            return destino.name

        def done(nombre: str) -> None:
            self.status.setText(f"Anadido «{nombre}». Reinicia el servidor para aplicarlo.")
            self.refresh()
            self.changed.emit()

        def failed(message: str, details: str) -> None:
            show_error(self, "No se pudo descargar el mod", message, details)

        self.runner.submit("Descargando mod", work, on_finished=done, on_failed=failed)

    def _toggle_selected(self) -> None:
        nombre = self._selected_filename()
        if nombre is None or self._inventory is None or self._running:
            return
        try:
            entradas = {entrada.filename: entrada for entrada in self._inventory.list_mods()}
            entrada = entradas.get(nombre)
            if entrada is None:
                return
            self._inventory.set_enabled(nombre, not entrada.enabled)
        except ServiscraftError as exc:
            show_error(self, "No se pudo cambiar el mod", str(exc))
            return
        self.refresh()
        self.changed.emit()

    def _delete_selected(self) -> None:
        nombre = self._selected_filename()
        if nombre is None or self._inventory is None or self._running:
            return
        entradas = {entrada.filename: entrada for entrada in self._inventory.list_mods()}
        entrada = entradas.get(nombre)
        aviso = ""
        if entrada is not None and not entrada.custom and self._inventory.modpack:
            aviso = (
                "\n\nOjo: este fichero vino con el modpack. Si lo eliminas, el modpack "
                "volvera a instalarlo en el siguiente arranque."
            )
        if not confirm(
            self,
            "Eliminar el mod",
            f"¿Eliminar «{nombre}» de la carpeta del servidor?{aviso}\n\n"
            "Si solo quieres dejarlo inactivo, usa «Activar o desactivar» (no borra nada).",
            confirm_label="Eliminar",
            destructive=True,
        ):
            return
        try:
            self._inventory.delete(nombre)
        except ServiscraftError as exc:
            show_error(self, "No se pudo eliminar el mod", str(exc))
            return
        self.refresh()
        self.changed.emit()

    # ==================================================== mods que faltan
    def analyze_logs(self) -> None:
        """Lee el registro del servidor y busca mods que no se pudieron descargar."""
        if self._spec is None or self.manager is None:
            return
        spec = self._spec
        self.status.setText("Analizando el registro del servidor...")

        def work(*, context) -> str:
            context.progress("Leyendo el registro del servidor...")
            partes: list[str] = []
            try:
                partes.append(self.manager.recent_logs(spec.id, tail=4000))
            except ServiscraftError as exc:
                logger.debug("Sin registro del contenedor: %s", exc)
            try:
                partes.append(logs.latest_log(self.manager.files(spec.id)))
            except ServiscraftError as exc:  # pragma: no cover - defensivo
                logger.debug("Sin latest.log: %s", exc)
            return "\n".join(parte for parte in partes if parte)

        def done(texto: str) -> None:
            self._missing = parse_missing_mods(texto)
            self._update_missing_rows()
            if self._missing:
                faltan = sum(1 for mod in self._missing if not self._esta_instalado(mod))
                self.status.setText(
                    f"El registro menciona {plural(len(self._missing), 'mod', 'mods')}: "
                    f"{faltan} por conseguir. Abre el enlace, descarga el fichero y usa "
                    "«Copiar el .jar aqui»."
                )
            else:
                self.status.setText(
                    "El registro no menciona mods que falten. Si el servidor no arranca, "
                    "revisa el registro completo en la pestana «Registros»."
                )

        def failed(message: str, details: str) -> None:
            self.status.setText(f"No se pudo analizar el registro: {message}")

        self.runner.submit(
            "Analizando el registro",
            work,
            on_finished=done,
            on_failed=failed,
            track_busy=False,
        )

    def _esta_instalado(self, mod: MissingMod) -> bool:
        if self._inventory is None:
            return False
        return mods.find_installed(mod.name, self._inventory.installed_names()) is not None

    def _update_missing_rows(self) -> None:
        self.missing_table.setRowCount(0)
        for mod in self._missing:
            row = self.missing_table.rowCount()
            self.missing_table.insertRow(row)
            instalado = self._esta_instalado(mod)
            nombre = QTableWidgetItem(mod.name)
            nombre.setData(Qt.ItemDataRole.UserRole, mod)
            nombre.setToolTip(mod.detail or mod.name)
            if instalado:
                nombre.setForeground(_VERDE)
            self.missing_table.setItem(row, 0, nombre)

            estado = QTableWidgetItem("ya esta en el servidor" if instalado else "falta")
            if instalado:
                estado.setForeground(_VERDE)
            self.missing_table.setItem(row, 1, estado)

            enlace = QTableWidgetItem(mod.link)
            enlace.setToolTip(f"Abrir en el navegador:\n{mod.link}")
            self.missing_table.setItem(row, 2, enlace)
        self._update_missing_actions()

    def _selected_missing(self) -> MissingMod | None:
        row = self.missing_table.currentRow()
        if row < 0:
            return None
        item = self.missing_table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, MissingMod) else None

    def _update_missing_actions(self) -> None:
        permitido = self._selected_missing() is not None
        self.open_link_button.setEnabled(permitido)
        self.copy_button.setEnabled(permitido and not self._running)
        self.copy_button.setToolTip(
            "Deten el servidor para copiar ficheros." if self._running else "Copia el .jar descargado"
        )

    def _open_missing_link(self) -> None:
        mod = self._selected_missing()
        if mod is None:
            return
        QDesktopServices.openUrl(QUrl(mod.link))

    def _copy_missing_file(self) -> None:
        """Copia dentro del servidor un .jar descargado a mano."""
        mod = self._selected_missing()
        if mod is None or self._inventory is None or self._running:
            return
        ruta, _filtro = self._files_dialog(
            self,
            f"Elige el fichero de «{mod.name}» que has descargado",
            "",
            "Mods (*.jar *.zip);;Todos los ficheros (*)",
        )
        if not ruta:
            return
        try:
            destino = self._inventory.add_file(Path(ruta))
        except ServiscraftError as exc:
            show_error(self, "No se pudo copiar el fichero", str(exc))
            return
        logger.info("Mod %s copiado al servidor desde %s", destino.name, ruta)
        self.refresh()
        self.changed.emit()
        show_info(
            self,
            "Mod copiado al servidor",
            f"«{destino.name}» ya esta en la carpeta «{self._inventory.folder}» del servidor.\n\n"
            "Ya puedes borrar el fichero que habias descargado. Reinicia el servidor "
            "para que lo cargue.",
        )
