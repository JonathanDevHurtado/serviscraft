"""Selector de modpacks de Modrinth para crear un servidor nuevo.

La imagen ``itzg/minecraft-server`` instala el modpack completo (mods y su
cargador) cuando se le dan las variables ``TYPE=MODRINTH`` +
``MODRINTH_MODPACK`` (+ ``MODRINTH_VERSION`` y ``MODRINTH_LOADER``). Este cuadro
solo elige el pack y la version; la instalacion la hace la imagen al iniciar el
servidor por primera vez.

La busqueda muestra de cada pack el cargador, las versiones de Minecraft, las
descargas y la ultima actualizacion, y se puede filtrar por cargador y por lado
(cliente o servidor) sin volver a buscar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import modrinth
from ..core.logging_setup import get_logger
from ..core.modrinth import ModpackPlan, Project, Release
from .common import hint_label, make_button, polish_table_header
from .dialogs import show_error
from .mc_icons import SIZE as ICON_SIZE, icono_pack, pixmap_de_bytes
from .tasks import TaskRunner

logger = get_logger("ui.modpack")

#: Filtros de cargador que ofrece la ventana (``None`` es «todos»).
FILTROS_CARGADOR: tuple[tuple[str, str | None], ...] = (
    ("Todos los cargadores", None),
    ("Fabric", "fabric"),
    ("Forge", "forge"),
    ("Quilt", "quilt"),
    ("NeoForge", "neoforge"),
)

#: Filtros por lado del juego.
FILTROS_LADO: tuple[tuple[str, str | None], ...] = (
    ("Cliente o servidor", None),
    ("Sirve en servidor", "servidor"),
    ("Solo cliente", "cliente"),
)


class ModpackDialog(QDialog):
    """Busca modpacks en Modrinth y devuelve la eleccion del usuario."""

    def __init__(self, runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._project: Project | None = None
        self._projects: list[Project] = []
        self._releases: list[Release] = []
        self._buscado = False
        self.plan: ModpackPlan | None = None
        self._busy = False

        self.setWindowTitle("Elegir un modpack de Modrinth")
        self.setMinimumSize(600, 480)
        self.resize(940, 640)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(
            hint_label(
                "Un modpack trae los mods, sus configuraciones y el cargador que necesita. "
                "La primera vez que inicies el servidor, la imagen descargara todo el pack "
                "(puede tardar varios minutos y ocupar bastante espacio)."
            )
        )

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por nombre, por ejemplo Cobblemon")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self.search)
        search_row.addWidget(self.search_input, 1)
        self.search_button = make_button("Buscar", icon_names=("system-search",), accent=True)
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.search_button)
        self.open_button = make_button("Ver en Modrinth", icon_names=("internet-web-browser",))
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_page)
        search_row.addWidget(self.open_button)
        layout.addLayout(search_row)

        filters_row = QHBoxLayout()
        filters_row.setSpacing(8)
        filters_row.addWidget(QLabel("Cargador"))
        self.loader_combo = QComboBox()
        for etiqueta, valor in FILTROS_CARGADOR:
            self.loader_combo.addItem(etiqueta, valor)
        self.loader_combo.setToolTip(
            "Fabric, Forge y Quilt se pueden instalar. NeoForge todavia no: "
            "se muestra para que sepas que existe."
        )
        self.loader_combo.currentIndexChanged.connect(self._on_loader_filter_changed)
        filters_row.addWidget(self.loader_combo, 1)

        filters_row.addWidget(QLabel("Lado"))
        self.side_combo = QComboBox()
        for etiqueta, valor in FILTROS_LADO:
            self.side_combo.addItem(etiqueta, valor)
        self.side_combo.currentIndexChanged.connect(self._aplicar_filtros)
        filters_row.addWidget(self.side_combo, 1)

        self.only_installable = QCheckBox("Solo instalables")
        self.only_installable.setChecked(True)
        self.only_installable.setToolTip(
            "Oculta los modpacks que solo publican versiones para cargadores que "
            "Serviscraft no prepara (por ejemplo, NeoForge)."
        )
        self.only_installable.toggled.connect(self._aplicar_filtros)
        filters_row.addWidget(self.only_installable)
        layout.addLayout(filters_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Modpack", "Cargador", "Minecraft", "Descargas", "Actualizado", "Descripcion"]
        )
        cabecera = self.table.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        cabecera.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ICON_SIZE + 8)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_project_selected)
        self.table.doubleClicked.connect(self._open_page)
        polish_table_header(self.table)
        layout.addWidget(self.table, 1)

        self.details = hint_label("Elige un modpack de la lista para ver mas datos.")
        self.details.setMinimumHeight(34)
        layout.addWidget(self.details)

        version_row = QHBoxLayout()
        version_row.setSpacing(8)
        version_row.addWidget(QLabel("Version"))
        self.version_combo = QComboBox()
        self.version_combo.setEnabled(False)
        self.version_combo.setToolTip(
            "Solo se pueden elegir versiones ya publicadas. Las que piden un "
            "cargador no soportado aparecen marcadas como no compatibles."
        )
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)
        version_row.addWidget(self.version_combo, 1)
        layout.addLayout(version_row)

        self.status = QLabel("Escribe un nombre y pulsa «Buscar».")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.accept_button = buttons.addButton("Usar este modpack", QDialogButtonBox.ButtonRole.AcceptRole)
        self.accept_button.setProperty("accent", "true")
        self.accept_button.setEnabled(False)
        self.accept_button.clicked.connect(self.accept)
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search_input.setFocus()

    # ================================================================ busqueda
    def _loader_filter(self) -> str | None:
        return self.loader_combo.currentData()

    def search(self) -> None:
        if self._busy:
            return
        query = self.search_input.text().strip()
        cargador = self._loader_filter()
        loaders = (cargador,) if cargador else ()
        self._set_busy(True, "Buscando modpacks en Modrinth...")

        def work(*, context):
            context.progress("Consultando Modrinth...")
            proyectos = modrinth.search_modpacks(query, loaders=loaders)
            if proyectos:
                context.progress("Descargando los iconos de los modpacks...")
                iconos_remotos.prefetch(proyecto.icon_url for proyecto in proyectos)
            return proyectos

        def done(projects: list[Project]) -> None:
            self._set_busy(False)
            self._buscado = True
            self._fill(projects)
            if projects:
                self.status.setText(
                    f"{len(projects)} modpacks encontrados. Elige uno para ver sus versiones."
                )
                self.table.selectRow(0)
            else:
                sufijo = " con ese cargador" if cargador else ""
                self.status.setText(f"No se encontro ningun modpack con ese nombre{sufijo}.")

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            self.status.setText(f"No se pudo buscar: {message}")
            show_error(self, "No se pudo consultar Modrinth", message, details)

        self.runner.submit("Buscando modpacks", work, on_finished=done, on_failed=failed)

    def _on_loader_filter_changed(self) -> None:
        """El cargador se filtra tambien en Modrinth, asi que hay que rebuscar."""
        if self._buscado:
            self.search()
        else:
            self._aplicar_filtros()

    def _pasa_filtros(self, project: Project) -> bool:
        cargador = self._loader_filter()
        if cargador and cargador not in project.loaders:
            return False
        lado = self.side_combo.currentData()
        if lado == "servidor" and not project.works_on_server:
            return False
        if lado == "cliente" and project.works_on_server:
            return False
        if self.only_installable.isChecked() and project.loaders:
            instalable = any(loader in modrinth.MODPACK_LOADERS for loader in project.loaders)
            if not instalable:
                return False
        return True

    def _fill(self, projects: list[Project]) -> None:
        self._projects = list(projects)
        self._aplicar_filtros()

    def _aplicar_filtros(self) -> None:
        """Vuelve a pintar la tabla aplicando los filtros, sin perder la seleccion."""
        seleccionado = self._project
        visibles = 0
        restaurada = False
        # Sin senales: repintar no debe lanzar otra consulta de versiones.
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            for project in self._projects:
                if not self._pasa_filtros(project):
                    continue
                self._add_row(project)
                if seleccionado is not None and project == seleccionado:
                    self.table.selectRow(visibles)
                    restaurada = True
                visibles += 1
        finally:
            self.table.blockSignals(False)
        total = len(self._projects)
        if total and visibles < total:
            if visibles:
                self.status.setText(f"Mostrando {visibles} de {total} modpacks (filtros activos).")
            else:
                self.status.setText(
                    f"Ninguno de los {total} modpacks pasa los filtros. Prueba a "
                    "quitar el filtro de cargador o de lado."
                )
        if seleccionado is not None and not restaurada:
            self._limpiar_seleccion()

    def _icono_proyecto(self, project: Project) -> QIcon:
        """Icono del modpack (el de Modrinth) o la caja generica."""
        if project.icon_url:
            datos = iconos_remotos.cached_bytes(project.icon_url)
            if datos:
                real = pixmap_de_bytes(datos, ICON_SIZE + 2)
                if not real.isNull():
                    return QIcon(real)
        return QIcon(icono_pack())

    def _add_row(self, project: Project) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        title = QTableWidgetItem(self._icono_proyecto(project), project.title)
        title.setData(Qt.ItemDataRole.UserRole, project)
        descripcion = project.description or "Sin descripcion."
        tooltip = f"{project.title}\n{descripcion}\n\n{project.page_url}"
        title.setToolTip(tooltip)

        instalable = not project.loaders or any(
            loader in modrinth.MODPACK_LOADERS for loader in project.loaders
        )
        if not instalable:
            title.setForeground(Qt.GlobalColor.gray)
        self.table.setItem(row, 0, title)

        cargador = QTableWidgetItem(project.loader_label)
        cargador.setToolTip(
            "Cargadores del pack. Serviscraft puede instalar Fabric, Forge y Quilt."
        )
        if not instalable:
            cargador.setToolTip(
                f"{project.loader_label}: Serviscraft no puede instalar este pack "
                "(solo prepara Fabric, Forge y Quilt)."
            )
        self.table.setItem(row, 1, cargador)

        minecraft = QTableWidgetItem(project.minecraft_label)
        minecraft.setToolTip("Versiones de Minecraft que anuncia el pack.")
        self.table.setItem(row, 2, minecraft)

        downloads = QTableWidgetItem(f"{project.downloads:,}".replace(",", "."))
        downloads.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        downloads.setToolTip(f"{project.downloads} descargas")
        self.table.setItem(row, 3, downloads)

        actualizado = QTableWidgetItem(project.updated_label)
        actualizado.setToolTip(f"Ultima publicacion: {project.updated or 'sin datos'}")
        self.table.setItem(row, 4, actualizado)

        descripcion_celda = QTableWidgetItem(descripcion)
        descripcion_celda.setToolTip(descripcion)
        self.table.setItem(row, 5, descripcion_celda)

    def _limpiar_seleccion(self) -> None:
        self.table.clearSelection()
        self._project = None
        self.plan = None
        self.details.setText("Elige un modpack de la lista para ver mas datos.")
        self.open_button.setEnabled(False)
        self.accept_button.setEnabled(False)
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.setEnabled(False)
        self.version_combo.blockSignals(False)

    def _open_page(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        QDesktopServices.openUrl(QUrl(project.page_url))

    # =============================================================== versiones
    def _selected_project(self) -> Project | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, Project) else None

    def _detalles(self, project: Project) -> str:
        partes = [f"Cargador: {project.loader_label}"]
        partes.append(f"Minecraft: {project.minecraft_label}")
        partes.append(f"Lado: {project.side_label}")
        if project.follows:
            partes.append(f"Seguimientos: {project.follows:,}".replace(",", "."))
        texto = "  ·  ".join(partes)
        if project.description:
            texto += f"\n{project.description}"
        return texto

    def _on_project_selected(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        self.open_button.setEnabled(True)
        self._project = project
        self.details.setText(self._detalles(project))
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.setEnabled(False)
        self.version_combo.blockSignals(False)
        self.accept_button.setEnabled(False)
        self._set_busy(True, f"Consultando las versiones de «{project.title}»...")

        def work(*, context):
            context.progress("Consultando las versiones del modpack...")
            return modrinth.fetch_releases(project.id)

        def done(releases: list[Release]) -> None:
            self._set_busy(False)
            # La seleccion pudo cambiar mientras se descargaban las versiones.
            if self._project is not project:
                return
            self._releases = releases
            self._fill_versions(releases)

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            self.status.setText(f"No se pudieron consultar las versiones: {message}")

        self.runner.submit("Consultando versiones del modpack", work, on_finished=done, on_failed=failed)

    def _fill_versions(self, releases: list[Release]) -> None:
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for release in releases:
            plan = modrinth.plan_modpack(self._project, release) if self._project else None
            label = f"{release.version_number}"
            if plan is not None and plan.installable:
                label += f" · {plan.loader} · Minecraft {plan.minecraft_version}"
                if release.version_type and release.version_type != "release":
                    label += f" ({release.version_type})"
            else:
                loaders = ", ".join(release.loaders) or "sin cargador"
                label += f" · no compatible ({loaders})"
            self.version_combo.addItem(label, release)
        self.version_combo.blockSignals(False)
        if not releases:
            self.version_combo.setEnabled(False)
            self.status.setText("Este modpack no publica ninguna version.")
            return
        self.version_combo.setEnabled(True)
        preferred = modrinth.choose_modpack_version(releases)
        if preferred is not None:
            index = self.version_combo.findData(preferred)
            if index >= 0:
                self.version_combo.setCurrentIndex(index)
        self._on_version_changed()

    def _selected_release(self) -> Release | None:
        data = self.version_combo.currentData()
        return data if isinstance(data, Release) else None

    def _on_version_changed(self) -> None:
        release = self._selected_release()
        project = self._project
        if release is None or project is None:
            self.plan = None
            self.accept_button.setEnabled(False)
            return
        plan = modrinth.plan_modpack(project, release)
        self.plan = plan if plan is not None and plan.installable else None
        if self.plan is None:
            loaders = ", ".join(release.loaders) or "desconocido"
            self.status.setText(
                "Esta version usa un cargador que Serviscraft todavia no prepara "
                f"({loaders}). Elige una version de Fabric, Forge o Quilt."
            )
            self.accept_button.setEnabled(False)
            return
        estables = sum(
            1 for item in self._releases if (item.version_type or "release") == "release"
        )
        self.status.setText(
            f"«{project.title}» {release.version_number}: Minecraft {plan.minecraft_version} "
            f"con {plan.loader}. {len(self._releases)} versiones publicadas ({estables} estables). "
            "Al crear el servidor se guardaran estas variables y la imagen instalara el pack "
            "en el primer arranque."
        )
        self.accept_button.setEnabled(True)

    # ================================================================ utilidad
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.search_button.setEnabled(not busy)
        if message:
            self.status.setText(message)

    def values(self) -> ModpackPlan | None:
        """Modpack elegido (ya validado) o ``None`` si no hay ninguno."""
        return self.plan
