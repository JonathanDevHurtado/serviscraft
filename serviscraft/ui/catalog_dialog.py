"""Catalogo de pluguins y mods de Modrinth para instalarlos desde la interfaz.

La busqueda ya filtra en Modrinth por la version de Minecraft y por los
cargadores que admite el servidor, y muestra de cada proyecto el cargador, las
versiones de Minecraft, las descargas y la ultima actualizacion. El filtro de
lado (cliente o servidor) se aplica aqui mismo, sin volver a consultar la red.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
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

from ..core import icons as iconos_remotos
from ..core import modrinth
from ..core.logging_setup import get_logger
from ..core.manager import ServerManager
from ..core.models import ServerSpec
from ..core.modrinth import Project
from .common import escape_text, hint_label, make_button, polish_table_header
from .dialogs import show_error, show_info
from .mc_icons import SIZE as ICON_SIZE, icono_mod, icono_plugin, pixmap_de_bytes
from .tasks import TaskRunner

logger = get_logger("ui.catalog")

#: Filtros por lado del juego.
FILTROS_LADO: tuple[tuple[str, str | None], ...] = (
    ("Sirve en servidor", "servidor"),
    ("Cliente o servidor", None),
    ("Solo cliente", "cliente"),
)


class CatalogDialog(QDialog):
    """Busca contenido en Modrinth y lo instala en ``plugins`` o ``mods``."""

    def __init__(
        self,
        manager: ServerManager,
        runner: TaskRunner,
        spec: ServerSpec,
        mode: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = runner
        self.spec = spec
        self.mode = mode
        self.installed: list[str] = []
        self._projects: list[Project] = []
        self._busy = False
        # Cargadores que entiende este servidor: se filtran en Modrinth para no
        # ofrecer contenido que luego no se puede instalar.
        self.loaders = modrinth.loaders_for_spec(spec)

        kind = "pluguins" if mode == "plugins" else "mods"
        self.setWindowTitle(f"Instalar {kind} en «{spec.name}»")
        self.setMinimumSize(560, 480)
        self.resize(900, 580)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        hint = f"Contenido para {spec.type.label} {spec.version}. Fuente: Modrinth."
        if self.loaders:
            hint += f" Cargadores: {', '.join(self.loaders)}."
        hint += (
            f" Al instalar se descarga el fichero mas reciente compatible y se guarda en "
            f"la carpeta «{mode}» del servidor."
        )
        layout.addWidget(hint_label(hint))

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por nombre, por ejemplo EssentialsX")
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
        filters_row.addWidget(QLabel("Lado"))
        self.side_combo = QComboBox()
        for etiqueta, valor in FILTROS_LADO:
            self.side_combo.addItem(etiqueta, valor)
        self.side_combo.setToolTip(
            "Modrinth marca algunos proyectos como «solo cliente»: no sirven en un "
            "servidor. Aqui puedes ocultarlos (por defecto) o verlos."
        )
        self.side_combo.currentIndexChanged.connect(self._aplicar_filtros)
        filters_row.addWidget(self.side_combo, 1)
        layout.addLayout(filters_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Proyecto", "Cargador", "Minecraft", "Descargas", "Actualizado", "Descripcion"]
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
        self.table.doubleClicked.connect(self._install_selected)
        polish_table_header(self.table)
        layout.addWidget(self.table, 1)

        self.details = hint_label("Elige un proyecto de la lista para ver mas datos.")
        self.details.setMinimumHeight(34)
        layout.addWidget(self.details)

        self.status = QLabel("Escribe un nombre y pulsa «Buscar».")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.install_button = buttons.addButton("Instalar seleccionado", QDialogButtonBox.ButtonRole.AcceptRole)
        self.install_button.setProperty("accent", "true")
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self._install_selected)
        buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search_input.setFocus()

    # ================================================================ busqueda
    def search(self) -> None:
        if self._busy:
            return
        project_type = modrinth.project_type_for(self.spec)
        if project_type is None:
            self.status.setText("Este tipo de servidor no admite pluguins ni mods.")
            return
        query = self.search_input.text().strip()
        self._set_busy(True, "Buscando en Modrinth...")

        def work(*, context):
            context.progress("Consultando Modrinth...")
            proyectos = modrinth.search_projects(
                query,
                project_type=project_type,
                game_version=self.spec.version,
                loaders=self.loaders,
                only_server_side=False,
                limit=40,
            )
            # Los iconos se descargan aqui (en el hilo de trabajo) y quedan en la
            # cache: la tabla los pinta al instante y sin volver a la red.
            if proyectos:
                context.progress("Descargando los iconos de los proyectos...")
                iconos_remotos.prefetch(proyecto.icon_url for proyecto in proyectos)
            return proyectos

        def done(projects: list[Project]) -> None:
            self._set_busy(False)
            self._fill(projects)
            if projects:
                label = "resultados" if len(projects) != 1 else "resultado"
                self.status.setText(f"{len(projects)} {label}. Selecciona uno para instalarlo.")
                if self.table.rowCount():
                    self.table.selectRow(0)
            else:
                self.status.setText(
                    f"No se encontro contenido compatible con {self.spec.type.label} "
                    f"{self.spec.version}. Prueba con otro nombre o revisa la version del servidor."
                )

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            self.status.setText(f"No se pudo buscar: {message}")
            show_error(self, "No se pudo consultar Modrinth", message, details)

        self.runner.submit("Buscando pluguins y mods", work, on_finished=done, on_failed=failed)

    def _pasa_filtros(self, project: Project) -> bool:
        lado = self.side_combo.currentData()
        if lado == "servidor" and not project.works_on_server:
            return False
        if lado == "cliente" and project.works_on_server:
            return False
        return True

    def _fill(self, projects: list[Project]) -> None:
        self._projects = list(projects)
        self._aplicar_filtros()

    def _aplicar_filtros(self) -> None:
        """Repinta la tabla con el filtro de lado sin perder la seleccion."""
        seleccionado = self._selected_project()
        visibles = 0
        restaurada = False
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
            self.status.setText(f"Mostrando {visibles} de {total} resultados (filtros activos).")
        if seleccionado is not None and not restaurada:
            self._limpiar_seleccion()
        self._update_install_button()

    def _icono_proyecto(self, project: Project) -> QIcon:
        """Icono del proyecto (el de Modrinth) o el generico de su tipo."""
        if project.icon_url:
            datos = iconos_remotos.cached_bytes(project.icon_url)
            if datos:
                real = pixmap_de_bytes(datos, ICON_SIZE + 2)
                if not real.isNull():
                    return QIcon(real)
        return QIcon(icono_plugin() if self.mode == "plugins" else icono_mod())

    def _add_row(self, project: Project) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        title = QTableWidgetItem(self._icono_proyecto(project), project.title)
        title.setData(Qt.ItemDataRole.UserRole, project)
        descripcion = project.description or "Sin descripcion."
        # Los datos vienen de la API de Modrinth: se escapan antes de usarlos en
        # una ayuda emergente (Qt las interpreta como HTML si "parecen" HTML).
        title.setToolTip(
            "<br>".join(
                escape_text(parte)
                for parte in (project.title, descripcion, "", project.page_url)
            )
        )
        if not project.works_on_server:
            title.setForeground(Qt.GlobalColor.gray)
            title.setToolTip(f"{title.toolTip()}\n\nSolo cliente: no sirve en un servidor.")
        self.table.setItem(row, 0, title)

        cargador = QTableWidgetItem(project.loader_label)
        cargador.setToolTip(
            "Cargadores que anuncia el proyecto. El servidor usa "
            + (", ".join(self.loaders) if self.loaders else "los de su tipo")
            + "."
        )
        self.table.setItem(row, 1, cargador)

        minecraft = QTableWidgetItem(project.minecraft_label)
        minecraft.setToolTip("Versiones de Minecraft que anuncia el proyecto.")
        self.table.setItem(row, 2, minecraft)

        downloads = QTableWidgetItem(f"{project.downloads:,}".replace(",", "."))
        downloads.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        downloads.setToolTip(f"{project.downloads} descargas")
        self.table.setItem(row, 3, downloads)

        actualizado = QTableWidgetItem(project.updated_label)
        actualizado.setToolTip(f"Ultima publicacion: {project.updated or 'sin datos'}")
        self.table.setItem(row, 4, actualizado)

        descripcion_celda = QTableWidgetItem(descripcion)
        descripcion_celda.setToolTip(escape_text(descripcion))
        self.table.setItem(row, 5, descripcion_celda)

    def _limpiar_seleccion(self) -> None:
        self.table.clearSelection()
        self.details.setText("Elige un proyecto de la lista para ver mas datos.")
        self.open_button.setEnabled(False)
        self.install_button.setEnabled(False)

    def _open_page(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        QDesktopServices.openUrl(QUrl(project.page_url))

    def _on_project_selected(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        self.open_button.setEnabled(True)
        partes = [f"Cargador: {project.loader_label}", f"Lado: {project.side_label}"]
        if project.follows:
            partes.append(f"Seguimientos: {project.follows:,}".replace(",", "."))
        texto = "  ·  ".join(partes)
        if project.description:
            texto += f"\n{project.description}"
        self.details.setText(texto)
        self._update_install_button()

    # ================================================================ instalacion
    def _selected_project(self) -> Project | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, Project) else None

    def _update_install_button(self) -> None:
        self.install_button.setEnabled(not self._busy and self._selected_project() is not None)

    def _install_selected(self) -> None:
        if self._busy:
            return
        project = self._selected_project()
        if project is None:
            self.status.setText("Selecciona antes un proyecto de la lista.")
            return
        destination = self.mode
        spec = self.spec
        loaders = self.loaders
        self._set_busy(True, f"Buscando una version compatible de «{project.title}»...")

        def work(*, context):
            releases = modrinth.fetch_releases(
                project.id,
                game_version=spec.version,
                loaders=loaders,
            )
            release = modrinth.choose_release(releases)
            if release is None:
                raise modrinth.ModrinthError(
                    f"No hay una version de «{project.title}» compatible con "
                    f"{spec.type.label} {spec.version}."
                )
            context.progress(f"Descargando {release.filename}...")
            path = modrinth.download_release(
                manager.files(spec.id),
                release,
                destination,
                on_progress=lambda done, total: context.progress_step(done, total),
                should_cancel=lambda: context.cancelled,
            )
            # Se guarda de que proyecto salio: asi la lista de mods puede enseñar
            # su icono despues, sin volver a consultar Modrinth.
            if project.icon_url:
                context.progress("Guardando el icono del proyecto...")
                iconos_remotos.prefetch([project.icon_url])
            try:
                manager.mods_inventory(spec.id).remember_project(
                    path.name,
                    slug=project.slug,
                    title=project.title,
                    icon=project.icon_url,
                )
            except Exception as exc:  # noqa: BLE001 - anotar el icono no es critico
                logger.warning("No se pudo anotar el proyecto de %s: %s", path.name, exc)
            return release, path.name

        def done(result) -> None:
            release, filename = result
            self._set_busy(False)
            self.installed.append(filename)
            self.status.setText(f"Instalado «{filename}» ({project.title} {release.version_number}).")
            note = ""
            if release.dependencies:
                note = (
                    "\n\nEste proyecto indica dependencias obligatorias. Si el servidor no "
                    "arranca, instala tambien los proyectos que aparecen en su pagina de Modrinth."
                )
            show_info(
                self,
                "Contenido instalado",
                f"Se ha instalado «{project.title}» {release.version_number}:\n\n"
                f"{filename}\n\nReinicia el servidor para aplicarlo.{note}",
            )

        def failed(message: str, details: str) -> None:
            self._set_busy(False)
            self.status.setText(f"No se pudo instalar: {message}")
            show_error(self, "No se pudo instalar el contenido", message, details)

        self.runner.submit(f"Instalando {project.title}", work, on_finished=done, on_failed=failed)

    # ================================================================ utilidades
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.search_button.setEnabled(not busy)
        self.search_input.setEnabled(not busy)
        self.table.setEnabled(not busy)
        if message:
            self.status.setText(message)
        self._update_install_button()
