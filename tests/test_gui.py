"""Pruebas de la interfaz grafica (sin pantalla real).

Se usa la plataforma ``offscreen`` de Qt: las pruebas construyen la ventana
completa, recorren sus pestanas y comprueban que todo se monta sin errores.
No lanzan ningun contenedor.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox  # noqa: E402

from serviscraft.core import paths  # noqa: E402
from serviscraft.core.appconfig import AppConfig  # noqa: E402
from serviscraft.core.manager import ServerManager, jvm_overhead_mb  # noqa: E402
from serviscraft.core.models import ServerState, ServerType, ServerView  # noqa: E402
from serviscraft.core.store import ServerStore  # noqa: E402
from serviscraft.ui import theme  # noqa: E402
from serviscraft.ui.common import ElidedLabel, StatusBadge, polish_table_header  # noqa: E402
from serviscraft.ui.main_window import MainWindow  # noqa: E402

from .conftest import make_spec  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)
    return app


@pytest.fixture(autouse=True)
def sin_dialogos_modales(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Sustituye los cuadros de dialogo modales por dobles que no bloquean.

    ``show_error``/``show_info``/``confirm``/``ask_text`` abren un bucle de
    eventos propio con ``exec()``: en una prueba sin usuario delante eso deja el
    proceso colgado para siempre. Se sustituyen en cada modulo que los importa
    (incluidos los que lo hacen dentro de una funcion, que se resuelven contra
    ``serviscraft.ui.dialogs``) y se registran las llamadas para poder
    comprobarlas despues.
    """
    from serviscraft import app as app_module
    from serviscraft.ui import (
        backups_panel,
        catalog_dialog,
        console_panel,
        create_dialog,
        details_panel,
        dialogs,
        ddns_dialog,
        files_panel,
        import_dialog,
        main_window,
        players_manager_dialog,
        players_panel,
        properties_panel,
        settings_dialog,
    )

    registro: dict[str, list] = {
        "errores": [],
        "avisos": [],
        "confirmaciones": [],
        "textos": [],
    }

    def falso_show_error(parent, title, message, details="") -> None:
        registro["errores"].append((title, message, details))

    def falso_show_info(parent, title, message) -> None:
        registro["avisos"].append((title, message))

    def falso_confirm(parent, title, text, **_kwargs) -> bool:
        registro["confirmaciones"].append((title, text))
        return True

    def falso_ask_text(parent, title, label, **_kwargs) -> None:
        registro["textos"].append((title, label))
        return None

    sustitutos = {
        "show_error": falso_show_error,
        "show_info": falso_show_info,
        "confirm": falso_confirm,
        "ask_text": falso_ask_text,
    }
    for modulo in (
        dialogs,
        app_module,
        backups_panel,
        catalog_dialog,
        console_panel,
        create_dialog,
        details_panel,
        files_panel,
        import_dialog,
        main_window,
        players_manager_dialog,
        players_panel,
        properties_panel,
        settings_dialog,
    ):
        for nombre, funcion in sustitutos.items():
            if hasattr(modulo, nombre):
                monkeypatch.setattr(modulo, nombre, funcion)

    # Aviso de servidores huerfanos y cierre con servidores activos: tambien
    # construyen un ``QMessageBox`` con ``exec()`` a mano.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    return registro


@pytest.fixture
def window(qapp: QApplication, store: ServerStore, config: AppConfig) -> MainWindow:
    manager = ServerManager(store=store, config=config)
    ventana = MainWindow(manager, config)
    yield ventana
    # Cierre determinista: sin temporizadores vivos ni servidores "en ejecucion"
    # (que dejarian la ventana abierta tras el aviso de cierre).
    ventana.stats_timer.stop()
    ventana.backup_timer.stop()
    ventana.views.clear()
    ventana.console.shutdown()
    ventana.runner.cancel_all()
    ventana.runner.wait_for_done(4000)
    ventana.close()
    qapp.processEvents()


def _indice_pestana(window: MainWindow, titulo: str) -> int:
    """Indice de una pestana por su titulo (los indices cambian al anadir pestanas)."""
    for indice in range(window.tabs.count()):
        if window.tabs.tabText(indice) == titulo:
            return indice
    raise AssertionError(f"no existe la pestana «{titulo}»")


def _esperar(window: MainWindow, qapp: QApplication, condicion, intentos: int = 200) -> None:
    """Espera a que se cumpla una condicion atendiendo los eventos de Qt.

    Las tareas de fondo avisan por senales, asi que hay que dejar que el bucle
    de eventos las entregue: ``wait_for_done`` por si solo no basta.
    """
    for _ in range(intentos):
        qapp.processEvents()
        if condicion():
            return
        window.runner.wait_for_done(50)
    qapp.processEvents()
    assert condicion(), "no se cumplio la condicion a tiempo"


class TestTema:
    def test_la_hoja_de_estilos_se_construye(self, qapp: QApplication) -> None:
        css = theme.build_stylesheet(qapp.palette())
        assert "QPushButton" in css
        assert "#ConsoleOutput" in css
        assert len(css) > 2000

    def test_el_tema_es_legible_en_claro_y_en_oscuro(self, qapp: QApplication) -> None:
        from PySide6.QtGui import QColor, QPalette

        for claro in (True, False):
            paleta = QPalette()
            paleta.setColor(QPalette.ColorRole.Window, QColor("#ffffff" if claro else "#1b1e20"))
            paleta.setColor(QPalette.ColorRole.Base, QColor("#ffffff" if claro else "#14161a"))
            paleta.setColor(QPalette.ColorRole.WindowText, QColor("#000000" if claro else "#ffffff"))
            css = theme.build_stylesheet(paleta)
            assert "#ConsoleOutput" in css


class TestComponentes:
    def test_el_numero_y_la_palabra_concuerdan(self, qapp: QApplication) -> None:
        """Los mensajes dicen «1 servidor» y «3 servidores», no «1 servidor(es)»."""
        from serviscraft.ui.common import plural

        assert plural(1, "servidor", "servidores") == "1 servidor"
        assert plural(3, "servidor", "servidores") == "3 servidores"
        assert plural(0, "copia", "copias") == "0 copias"

    def test_la_caja_de_numeros_reemplaza_el_valor_al_escribir(self, qapp: QApplication) -> None:
        """Escribir encima no debe mezclarse con el numero anterior (2048+8192)."""
        from PySide6.QtCore import QPoint, QPointF, Qt as QtCore
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtTest import QTest

        from serviscraft.ui.common import NumberBox

        caja = NumberBox()
        caja.setRange(1024, 65535)
        caja.setValue(2048)
        caja.show()
        qapp.processEvents()

        QTest.mouseClick(caja, QtCore.MouseButton.LeftButton)
        QTest.keyClicks(caja, "8192")
        assert caja.lineEdit().text() == "8192"
        QTest.keyClick(caja, QtCore.Key.Key_Return)
        assert caja.value() == 8192

        # La rueda del raton no cambia el valor por accidente.
        evento = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, 120),
            QtCore.MouseButton.NoButton,
            QtCore.KeyboardModifier.NoModifier,
            QtCore.ScrollPhase.NoScrollPhase,
            False,
        )
        qapp.sendEvent(caja, evento)
        assert caja.value() == 8192
        caja.close()

    def test_el_deslizador_se_pega_al_paso(self, qapp: QApplication) -> None:
        from serviscraft.ui.common import NumberSlider

        deslizador = NumberSlider(minimum=512, maximum=8192, step=512, value=2048)
        assert deslizador.value() == 2048

        deslizador.slider.setValue(2500)
        assert deslizador.value() == 2048

        deslizador.box.setValue(4096)
        assert deslizador.slider.value() == 4096
        assert deslizador.value() == 4096

    def test_la_version_no_se_escribe_a_mano(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        """El desplegable de version solo admite las versiones de la lista."""
        from serviscraft.core.manager import ServerManager
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = CreateServerDialog(ServerManager(store=store, config=config), TaskRunner(), config)
        try:
            assert not dialogo.version_combo.isEditable()
            assert dialogo.version_combo.count() > 1
            assert dialogo.version_combo.currentText() == "latest"
        finally:
            dialogo.close()

    def test_insignia_de_estado(self, qapp: QApplication) -> None:
        insignia = StatusBadge()
        for estado in ServerState:
            insignia.set_state(estado)
            assert insignia.text() == estado.label

    def test_cabeceras_de_tabla(self, qapp: QApplication) -> None:
        from PySide6.QtWidgets import QTableWidget

        tabla = QTableWidget(0, 2)
        tabla.setHorizontalHeaderLabels(["Nombre", "Tamano"])
        polish_table_header(tabla)
        assert tabla.horizontalHeaderItem(0).text() == "Nombre"


class TestVentanaPrincipal:
    def test_se_construye(self, window: MainWindow) -> None:
        assert window.windowTitle().startswith("Serviscraft")
        assert window.tabs.count() == 10
        assert [window.tabs.tabText(i) for i in range(10)] == [
            "Consola",
            "Unirse",
            "Mods",
            "Plugins",
            "Propiedades",
            "Archivos",
            "Jugadores",
            "Copias",
            "Registros",
            "Detalles",
        ]

    def test_muestra_el_estado_vacio(self, window: MainWindow) -> None:
        assert window.stack.currentIndex() == 0
        window._on_views_ready([])
        assert window.current_id is None
        assert not window.action_start.isEnabled()

    def test_la_pestana_plugins_solo_aparece_en_servidores_paper(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        paper = make_spec(id="servidor-paper01", type=ServerType.PAPER)
        store.prepare_dirs(paper.id)
        store.save(paper)
        window._on_views_ready([ServerView(spec=paper, state=ServerState.CREATED)])
        qapp.processEvents()
        indice = _indice_pestana(window, "Plugins")
        assert window.tabs.isTabVisible(indice)
        assert window.plugins.catalog.spec is paper

        vanilla = make_spec(id="servidor-vainilla", type=ServerType.VANILLA)
        store.prepare_dirs(vanilla.id)
        store.save(vanilla)
        window._on_views_ready([ServerView(spec=vanilla, state=ServerState.CREATED)])
        qapp.processEvents()
        assert not window.tabs.isTabVisible(indice)
        assert window.plugins.catalog.spec is None

    def test_con_servidores_detectados(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        vista = ServerView(spec=spec, state=ServerState.CREATED)

        window._on_views_ready([vista])
        qapp.processEvents()
        assert window.current_id == spec.id
        assert window.stack.currentIndex() == 1
        assert window.header_title.text() == spec.name
        # Con el servidor detenido no se puede detener ni reiniciar.
        assert not window.action_stop.isEnabled()
        assert not window.action_restart.isEnabled()
        assert window.action_delete.isEnabled()

    def test_recorre_todas_las_pestanas(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        for indice in range(window.tabs.count()):
            window.tabs.setCurrentIndex(indice)
            qapp.processEvents()
            assert window.tabs.currentIndex() == indice
        window.tabs.setCurrentIndex(0)

    def test_la_consola_solo_sigue_si_es_visible(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Propiedades"))  # la consola no debe seguir
        qapp.processEvents()
        assert window.console._process is None

    def test_barra_de_estado_del_motor(self, window: MainWindow) -> None:
        window._on_engine_ready(("5.8.9", True))
        assert "5.8.9" in window.status_engine.text()
        assert "rootless" in window.status_engine.text()

    def test_motor_no_disponible(self, window: MainWindow, sin_dialogos_modales: dict) -> None:
        window._on_engine_failed("no encontrado", "detalle")
        assert "no disponible" in window.status_engine.text()
        assert not window.action_start.isEnabled()
        assert any("no encontrado" in mensaje for _t, mensaje, _d in sin_dialogos_modales["errores"])

    def test_estadisticas_en_la_cabecera(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        from serviscraft.core.models import ServerStats

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        window._on_stats_ready(
            ServerStats(cpu_percent=25.0, memory_bytes=512 * 1024**2, memory_limit_bytes=1024**3, pids=42, available=True)
        )
        assert window.cpu_bar.bar.value() == 25
        assert "512" in window.ram_bar.value_label.text()
        assert "42" in window.metrics_extra.text()

    def test_la_cpu_nunca_ensena_mas_del_100_por_ciento(
        self, window: MainWindow, store: ServerStore
    ) -> None:
        """Aunque llegue una cifra por nucleo (200 %), la barra no miente."""
        from serviscraft.core.models import ServerStats

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        window._on_stats_ready(
            ServerStats(
                cpu_percent=200.0,
                cpu_cores=8,
                memory_bytes=256 * 1024**2,
                memory_limit_bytes=1024**3,
                pids=10,
                available=True,
            )
        )
        assert window.cpu_bar.bar.value() == 100
        assert window.cpu_bar.value_label.text() == "100 %"
        assert "256.0 MiB / 2.0 GiB" in window.ram_bar.value_label.text()
        assert "12 %" in window.ram_bar.bar.toolTip()

    def test_las_barras_parecen_de_experiencia(
        self, window: MainWindow
    ) -> None:
        from serviscraft.ui.common import MinecraftBar

        assert isinstance(window.cpu_bar.bar, MinecraftBar)
        assert isinstance(window.ram_bar.bar, MinecraftBar)
        assert window.cpu_bar.bar.height() >= 14
        # Se pintan sin errores (fondo oscuro, relleno verde y marcas).
        assert not window.cpu_bar.bar.grab().isNull()

    def test_estadisticas_no_disponibles(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        from serviscraft.core.models import ServerStats

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        window._on_stats_ready(ServerStats(available=False))
        assert window.cpu_bar.bar.value() == 0

    def test_error_de_operacion_no_rompe_la_ventana(
        self, window: MainWindow, sin_dialogos_modales: dict
    ) -> None:
        window._on_operation_failed("fallo de prueba", "detalle tecnico")
        assert not window.operation.isVisible()
        assert any("fallo de prueba" in mensaje for _t, mensaje, _d in sin_dialogos_modales["errores"])


class TestPaneles:
    def test_la_tarjeta_lateral_no_se_sale_de_la_barra(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el nombre largo ensanchaba la tarjeta y la cortaba la barra."""
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        lista = window.sidebar.list
        tarjeta = window.sidebar._cards[spec.id]
        assert not lista.horizontalScrollBar().isVisible(), (
            "la tarjeta lateral ensancha la lista y saca una barra horizontal"
        )
        assert tarjeta.width() <= lista.viewport().width()
        assert tarjeta.badge.width() >= tarjeta.badge.sizeHint().width() - 2, (
            f"la insignia de estado se recorta: {tarjeta.badge.width()} px"
        )

    def test_la_busqueda_encuentra_por_el_nombre_completo(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """El recorte del titulo no debe romper la busqueda de la barra lateral."""
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        window.sidebar.search.setText("supervivencia")
        for _ in range(6):
            qapp.processEvents()
        item = window.sidebar._items[spec.id]
        assert not item.isHidden(), "no se encuentra el servidor por su nombre completo"

    def test_la_barra_de_la_consola_no_recorta_la_etiqueta(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el resumen de la consola se recortaba a media palabra."""
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        etiqueta = window.console.status_label
        assert isinstance(etiqueta, ElidedLabel)
        assert etiqueta.full_text().startswith("Consola de «Servidor supervivencia extremo»")
        assert etiqueta.text().endswith("…")  # recortada, no cortada a media palabra
        assert window.console.autoscroll.width() >= window.console.autoscroll.sizeHint().width() - 2

    def test_ninguna_etiqueta_normal_se_recorta(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Barrido: toda QLabel visible cabe en su hueco o es una ElidedLabel."""
        from PySide6.QtWidgets import QLabel

        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()

        recortadas = []
        for indice in range(window.tabs.count()):
            window.tabs.setCurrentIndex(indice)
            for _ in range(6):
                qapp.processEvents()
            for etiqueta in window.findChildren(QLabel):
                if not etiqueta.isVisible() or not etiqueta.text().strip():
                    continue
                if etiqueta.wordWrap() or isinstance(etiqueta, ElidedLabel):
                    continue
                if etiqueta.width() < etiqueta.sizeHint().width() - 2:
                    recortadas.append(
                        f"[{window.tabs.tabText(indice)}] "
                        f"{etiqueta.objectName() or 'QLabel'}: {etiqueta.width()} px "
                        f"para un texto de {etiqueta.sizeHint().width()} px"
                    )
        assert not recortadas, "etiquetas recortadas:\n" + "\n".join(recortadas)

    def test_la_cabecera_no_recorta_los_botones(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: con un nombre largo la cabecera empujaba y recortaba los botones.

        La etiqueta del resumen del servidor exigia el ancho completo de su texto
        como ancho minimo, de modo que en el tamano minimo de ventana los botones
        de accion quedaban mas estrechos que su propio texto.
        """
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        for boton in (
            window.start_button,
            window.stop_button,
            window.restart_button,
            window.settings_button,
            window.delete_button,
        ):
            assert boton.width() >= boton.sizeHint().width() - 2, (
                f"el boton «{boton.text()}» se recorta: {boton.width()} px "
                f"para un texto de {boton.sizeHint().width()} px"
            )

    def test_el_titulo_largo_se_recorta_con_puntos_suspensivos(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        nombre = "Servidor supervivencia extremo"
        spec = make_spec(name=nombre)
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        etiqueta = window.header_title
        # Con la ventana al minimo los botones de la cabecera bajan a su propia
        # linea, de modo que el nombre cabe entero: eso es lo deseable. Para
        # comprobar el recorte se limita el ancho de la etiqueta, que es lo que
        # ocurre cuando el nombre es muy largo o la ventana aun mas estrecha.
        etiqueta.setFixedWidth(120)
        for _ in range(6):
            qapp.processEvents()
        assert etiqueta.full_text() == nombre
        assert etiqueta.toolTip() == nombre
        assert etiqueta.text().endswith("…"), (
            f"titulo='{etiqueta.text()}' ancho={etiqueta.width()} "
            f"min={window.minimumSize().width()} ventana={window.width()} pila={window.stack.width()}"
        )
        assert len(etiqueta.text()) < len(nombre)

    def test_el_titulo_se_despliega_entero_cuando_hay_sitio(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el recorte se quedaba «pegado» y ya no crecia al ensanchar."""
        nombre = "Servidor supervivencia extremo"
        spec = make_spec(name=nombre)
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(6):
            qapp.processEvents()
        window.resize(1600, 900)
        for _ in range(10):
            qapp.processEvents()
        assert window.header_title.text() == nombre

    def test_las_etiquetas_recortadas_usan_el_ancho_disponible(
        self, qapp: QApplication
    ) -> None:
        from serviscraft.ui.common import ElidedLabel

        etiqueta = ElidedLabel("resumen muy largo del servidor con puerto y contenedor")
        etiqueta.show()
        for ancho, recortada in ((120, True), (4000, False)):
            etiqueta.resize(ancho, 24)
            for _ in range(4):
                qapp.processEvents()
            assert etiqueta.minimumSizeHint().width() == 0
            if recortada:
                assert etiqueta.text().endswith("…")
                assert len(etiqueta.text()) < len(etiqueta.full_text())
            else:
                assert etiqueta.text() == etiqueta.full_text()
        etiqueta.hide()
        etiqueta.deleteLater()

    def test_detalles_no_solapa_las_etiquetas(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Las etiquetas con ajuste de linea deben tener la altura que necesitan.

        El estilo Breeze usa ``ExpandingFieldsGrow``, que no estira los QLabel; si
        el formulario no lo evita, el texto se dibuja encima de la fila siguiente.
        """
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Detalles"))
        for _ in range(5):
            qapp.processEvents()
        for clave, etiqueta in window.details._labels.items():
            ancho = etiqueta.width()
            assert etiqueta.height() >= min(etiqueta.heightForWidth(ancho), 200), (
                f"la etiqueta '{clave}' es mas baja que el texto que contiene"
            )

    def test_la_copia_tiene_el_boton_compacto(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el boton de eliminar copia ocupaba todo el ancho del panel."""
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Copias"))
        for _ in range(5):
            qapp.processEvents()
        boton = window.backups.delete_button
        assert boton.width() < window.backups.width() / 2

    def test_el_panel_de_ficheros_no_ofrece_mods_a_vanilla(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        from serviscraft.ui.files_panel import MODE_MODS, MODE_PLUGINS

        spec = make_spec(type="VANILLA")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        modos = [window.files.mode_combo.itemData(i) for i in range(window.files.mode_combo.count())]
        assert MODE_MODS not in modos
        assert MODE_PLUGINS not in modos

    def test_paper_ofrece_pluguins(self, window: MainWindow, store: ServerStore, qapp: QApplication) -> None:
        from serviscraft.ui.files_panel import MODE_PLUGINS

        spec = make_spec(type="PAPER")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        modos = [window.files.mode_combo.itemData(i) for i in range(window.files.mode_combo.count())]
        assert MODE_PLUGINS in modos

    def test_el_panel_muestra_el_catalogo_solo_con_pluguins_o_mods(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        paper = make_spec(type="PAPER", id="catalogo-paper")
        store.prepare_dirs(paper.id)
        store.save(paper)
        window._on_views_ready([ServerView(spec=paper, state=ServerState.CREATED)])
        assert window.files.mode == "plugins"
        assert window.files.catalog_button.isVisibleTo(window.files)

        vanilla = make_spec(type="VANILLA", id="catalogo-vanilla")
        store.prepare_dirs(vanilla.id)
        store.save(vanilla)
        window._on_views_ready([ServerView(spec=vanilla, state=ServerState.CREATED)])
        assert window.files.mode == "ficheros"
        assert not window.files.catalog_button.isVisibleTo(window.files)


class TestDialogosDelFlujoPrincipal:
    """El flujo que estaba roto en la 0.1.0: crear, ajustar y cambiar version."""

    def test_el_dialogo_de_crear_servidor_se_construye_y_valida(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        manager = ServerManager(store=store, config=config)
        dialogo = CreateServerDialog(manager, TaskRunner(), config)
        try:
            assert dialogo.server_type is ServerType.PAPER
            dialogo.name.setText("Nuevo servidor")
            dialogo.port.setValue(manager.next_free_port(25900))
            valores = dialogo.values()
            assert valores["name"] == "Nuevo servidor"
            assert valores["type"] is ServerType.PAPER
            assert valores["version"]
            assert 1024 <= valores["port"] <= 65535
        finally:
            dialogo.close()

    def test_el_asistente_prepara_el_contenido_segun_el_tipo(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = CreateServerDialog(
            ServerManager(store=store, config=config), TaskRunner(), config
        )
        try:
            # Paper es el valor inicial: el boton habla de plugins.
            assert dialogo.server_type is ServerType.PAPER
            assert dialogo.content_button.isEnabled()
            assert "plugins" in dialogo.content_button.text()

            indice = dialogo.type_combo.findData(ServerType.FABRIC.value)
            dialogo.type_combo.setCurrentIndex(indice)
            assert "mods" in dialogo.content_button.text()
            assert dialogo.content_button.isEnabled()

            indice = dialogo.type_combo.findData(ServerType.VANILLA.value)
            dialogo.type_combo.setCurrentIndex(indice)
            assert not dialogo.content_button.isEnabled()
            assert "Vanilla" in dialogo.content_hint.text()
        finally:
            dialogo.close()

    def test_el_contenido_elegido_se_quita_si_cambia_el_tipo(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.modrinth import ContentSelection, Project, Release
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = CreateServerDialog(
            ServerManager(store=store, config=config), TaskRunner(), config
        )
        try:
            dialogo.version_combo.setCurrentText("1.21.4")
            proyecto = Project(
                "p1",
                "essentialsx",
                "EssentialsX",
                "Comandos",
                10,
                project_type="plugin",
            )
            release = Release(
                "p1",
                "EssentialsX 1.0",
                "1.0",
                ("1.21.4",),
                ("paper",),
                "https://cdn.modrinth.com/essentialsx.jar",
                "essentialsx.jar",
            )
            dialogo._content = [ContentSelection(proyecto, release)]
            dialogo._refresh_content()
            assert len(dialogo.selected_content()) == 1
            assert dialogo.content_list.count() == 1

            indice = dialogo.type_combo.findData(ServerType.FABRIC.value)
            dialogo.type_combo.setCurrentIndex(indice)
            assert dialogo.selected_content() == []
            assert dialogo.content_list.count() == 0
            assert "Se quitaron 1" in dialogo.content_status.text()
        finally:
            dialogo.close()

    def test_el_selector_guarda_una_version_por_proyecto(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.modrinth import ContentSelection, Project, Release
        from serviscraft.ui.content_picker import ContentPickerDialog
        from serviscraft.ui.tasks import TaskRunner

        proyecto = Project(
            "p1", "essentialsx", "EssentialsX", "Comandos", 10, project_type="plugin"
        )
        primera = Release(
            "p1",
            "EssentialsX 1.0",
            "1.0",
            ("1.21.4",),
            ("paper",),
            "https://cdn.modrinth.com/1.jar",
            "essentialsx-1.jar",
        )
        segunda = Release(
            "p1",
            "EssentialsX 2.0",
            "2.0",
            ("1.21.4",),
            ("paper",),
            "https://cdn.modrinth.com/2.jar",
            "essentialsx-2.jar",
        )
        picker = ContentPickerDialog(
            TaskRunner(),
            mode="plugins",
            server_type=ServerType.PAPER,
            version="1.21.4",
            loaders=("paper",),
        )
        try:
            # El catalogo crece al enseñar las versiones: la pagina desplazable
            # evita que Qt lo comprima y que las tablas se solapen.
            from PySide6.QtWidgets import QScrollArea

            assert isinstance(picker.catalog_page, QScrollArea)
            assert picker.catalog_page.widget() is picker.catalog
            assert picker.catalog_page.minimumHeight() >= 300

            picker._add(ContentSelection(proyecto, primera))
            picker._add(ContentSelection(proyecto, segunda))
            assert len(picker.values()) == 1
            assert picker.values()[0].release.version_number == "2.0"
            assert picker.selected_list.count() == 1
            assert picker.accept_button.isEnabled()

            picker.selected_list.setCurrentRow(0)
            picker._remove()
            assert picker.values() == []
            assert not picker.accept_button.isEnabled()

            picker.reject()
            assert picker.catalog._closed is True
        finally:
            picker.close()

    def test_elegir_la_version_sugiere_el_java_correcto(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = CreateServerDialog(ServerManager(store=store, config=config), TaskRunner(), config)
        try:
            dialogo.version_combo.setCurrentText("1.16.5")
            assert dialogo.java_combo.currentText() == "java8"
            dialogo.version_combo.setCurrentText("1.20.4")
            assert dialogo.java_combo.currentText() == "java17"
            dialogo.version_combo.setCurrentText("1.21.4")
            assert dialogo.java_combo.currentText() == "java21"
        finally:
            dialogo.close()

    def test_el_dialogo_de_ajustes_cambia_version_y_java(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.settings_dialog import ServerSettingsDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="PAPER", version="1.21.4", java_tag="java21")
        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)
        dialogo = ServerSettingsDialog(manager, spec, runner=TaskRunner())
        try:
            dialogo.version_combo.setCurrentText("1.20.1")
            assert dialogo.java_combo.currentText() == "java17"
            dialogo._on_accept()
            valores = dialogo.values()
            assert valores["version"] == "1.20.1"
            assert valores["java_tag"] == "java17"
        finally:
            dialogo.close()

    def test_el_catalogo_activa_instalar_al_seleccionar(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.modrinth import Project
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="PAPER")
        dialogo = CatalogDialog(ServerManager(store=store, config=config), TaskRunner(), spec, "plugins")
        try:
            assert not dialogo.install_button.isEnabled()
            dialogo._fill(
                [
                    Project("p1", "essentialsx", "EssentialsX", "Comandos", 1234567, project_type="plugin"),
                    Project("p2", "luckperms", "LuckPerms", "Permisos", 900000, project_type="plugin"),
                ]
            )
            assert dialogo.table.rowCount() == 2
            assert dialogo.table.item(0, 3).text() == "1.234.567"
            assert dialogo.table.item(0, 1).text() == "sin datos"
            dialogo.table.selectRow(0)
            assert dialogo.install_button.isEnabled()
        finally:
            dialogo.close()

    def test_abrir_la_carpeta_del_servidor(
        self,
        window: MainWindow,
        store: ServerStore,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from serviscraft.ui import main_window as main_window_module

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        abiertas: list[str] = []

        class FalsoDesktop:
            @staticmethod
            def openUrl(url) -> bool:
                abiertas.append(url.toLocalFile())
                return True

        monkeypatch.setattr(main_window_module, "QDesktopServices", FalsoDesktop)
        assert window.action_open_folder.isEnabled()
        window.open_server_folder("data")
        assert abiertas == [str(store.data_dir(spec.id))]


class TestConsolaDelPanel:
    def test_colores_por_tipo_de_linea(self) -> None:
        from serviscraft.ui.console_panel import ConsolePanel

        assert ConsolePanel._color_for("[12:00:00 ERROR] fallo") == "#ff6b6b"
        assert ConsolePanel._color_for("[12:00:00 WARN] cuidado") == "#ffcc66"
        assert ConsolePanel._color_for("[12:00:00] Done (3.5s)! For help, type hi") == "#7fd6a2"
        assert ConsolePanel._color_for("[Serviscraft] respuesta") == "#8ab4f8"
        assert ConsolePanel._color_for("> list") == "#7fd6a2"

    def test_comandos_frecuentes(self) -> None:
        from serviscraft.ui.console_panel import QUICK_COMMANDS

        comandos = {c for c, _ in QUICK_COMMANDS}
        assert {"list", "save-all", "stop"} <= comandos

    def test_la_cabecera_tiene_icono_y_leyenda_de_colores(
        self, window: MainWindow
    ) -> None:
        """Personalidad: se ve de que va la consola sin leer un manual."""
        assert window.console.card.title_label.text() == "Consola del servidor"
        leyenda = window.console.legend.text()
        for palabra in ("listo", "aviso", "error", "chat", "normal"):
            assert palabra in leyenda
        # Los cuadraditos van en HTML: si se pinta como texto plano se ve el
        # codigo fuente en vez de la leyenda.
        assert window.console.legend.textFormat() == Qt.TextFormat.RichText
        assert not window.console.state_dot.pixmap().isNull()

    def test_el_punto_de_estado_cambia_de_color(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        qapp.processEvents()
        encendido = window.console.state_dot.pixmap().toImage()
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        parado = window.console.state_dot.pixmap().toImage()
        assert encendido != parado

    def test_el_filtro_de_problemas_esconde_lo_normal(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        consola = window.console
        consola._lines.clear()
        consola.output.clear()
        consola._append("[12:00:00] [Server thread/INFO]: Done (3.5s)! For help, type help")
        consola._append("[12:00:01] [Server thread/WARN]: Can't keep up!")
        consola._append("[12:00:02] [Server thread/ERROR]: fallo gordo")
        consola._append("> list")

        consola.only_problems.setChecked(True)
        texto = consola.output.toPlainText()
        assert "fallo gordo" in texto
        assert "Can't keep up!" in texto
        assert "> list" in texto
        assert "Done (3.5s)" not in texto
        assert "ocultas" in consola.status_label.full_text()

        consola.only_problems.setChecked(False)
        assert "Done (3.5s)" in consola.output.toPlainText()

    def test_limpiar_vacia_la_pantalla_y_el_filtro_cuenta_bien(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        consola = window.console
        consola._append("[INFO]: normal")
        consola._append("[ERROR]: problema")
        assert "problema" in consola.output.toPlainText()

        # Los botones de la consola: limpiar no toca al servidor, solo la pantalla.
        limpiar = next(
            b for b in consola.console_actions.widgets() if getattr(b, "text", lambda: "")() == "Limpiar"
        )
        limpiar.click()
        qapp.processEvents()
        assert consola.output.toPlainText().strip() == ""
        assert consola._lines == []

    def test_el_filtro_de_texto_cuenta_solo_lo_que_se_ve(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        consola = window.console
        consola._lines.clear()
        consola.output.clear()
        consola._hidden = 0
        consola._visible = 0
        consola._append("[12:00:00] [Server thread/INFO]: Ana joined the game")
        consola._append("[12:00:01] [Server thread/INFO]: Luis joined the game")
        consola._append("[12:00:02] [Server thread/ERROR]: fallo de conexion")

        consola.filter_input.setText("ana")
        consola._on_filter_changed()
        texto = consola.output.toPlainText()
        assert "Ana joined" in texto
        assert "Luis joined" not in texto
        assert "fallo de conexion" not in texto
        assert consola.line_count.text() == "1 de 3 lineas"
        assert "filtro «ana» (1 de 3)" in consola.status_label.full_text()

        consola.filter_input.clear()
        consola._on_filter_changed()
        assert consola.line_count.text() == "3 lineas"

    def test_al_recortar_lineas_los_contadores_siguen_cuadrando(
        self,
        window: MainWindow,
        store: ServerStore,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Al llegar al limite se van las mas viejas, no la cuenta."""
        from serviscraft.ui import console_panel

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        consola = window.console
        monkeypatch.setattr(console_panel, "MAX_LINES", 3)
        consola.output.setMaximumBlockCount(3)
        consola._clear()

        for indice in range(5):
            consola._append(f"[INFO]: linea {indice}")

        assert len(consola._lines) == 3
        assert consola._visible == 3
        assert consola._hidden == 0
        assert consola.line_count.text() == "3 lineas"
        assert "linea 4" in consola.output.toPlainText()
        assert "linea 0" not in consola.output.toPlainText()

        # Lo mismo con lineas ocultas por el filtro.
        consola.only_problems.setChecked(True)
        consola._clear()
        for indice in range(5):
            consola._append(f"[INFO]: normal {indice}")

        assert len(consola._lines) == 3
        assert consola._visible == 0
        assert consola._hidden == 3
        assert consola.line_count.text() == "0 de 3 lineas"

        # Si se recorta una linea visible mientras otras estan ocultas, el
        # texto tambien debe desaparecer del terminal (no solo del contador).
        consola.only_problems.setChecked(False)
        consola._clear()
        consola._append("[ERROR]: vieja")
        consola.filter_input.setText("ERROR")
        consola._on_filter_changed()
        consola._filter_timer.stop()
        for indice in range(3):
            consola._append(f"[INFO]: normal {indice}")

        assert "vieja" not in consola.output.toPlainText()
        assert consola._visible == 0
        assert consola._hidden == 3

        consola._append("[ERROR]: nueva")
        assert consola.output.toPlainText() == "[ERROR]: nueva"
        assert consola._visible == 1

    def test_la_insignia_de_estado_sigue_al_servidor(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        qapp.processEvents()
        consola = window.console
        assert consola.state_badge.text() == "EN VIVO"

        consola.follow_button.setChecked(False)
        assert consola.state_badge.text() == "EN PAUSA"
        assert "en pausa" in consola.status_label.full_text().lower()

        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        assert consola.state_badge.text() == "DETENIDO"

    def test_copiar_todo_deja_la_consola_en_la_memoria(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        from PySide6.QtWidgets import QApplication

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        consola = window.console
        consola._lines.clear()
        consola.output.clear()
        consola._append("[12:00:00] [Server thread/INFO]: hola")

        copiar = next(
            b
            for b in consola.console_actions.widgets()
            if getattr(b, "text", lambda: "")() == "Copiar todo"
        )
        copiar.click()
        qapp.processEvents()
        assert "hola" in QApplication.clipboard().text()
        assert "copiada" in consola.status_label.full_text().lower()

    def test_la_consola_no_esta_activa_sin_servidor(self, window: MainWindow) -> None:
        assert not window.console.input.isEnabled()
        assert not window.console.send_button.isEnabled()
        assert "Sin servidor" in window.console.status_label.text()


class TestJugadores:
    def test_muestra_la_lista_blanca_con_el_servidor_detenido(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        import json

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}, {"uuid": "2", "name": "luis"}]),
            encoding="utf-8",
        )
        (store.data_dir(spec.id) / "ops.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        (store.data_dir(spec.id) / "banned-players.json").write_text(
            json.dumps([{"uuid": "3", "name": "Troll"}]), encoding="utf-8"
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Jugadores"))
        for _ in range(6):
            qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        tabla = window.players.table
        assert tabla.rowCount() == 3
        nombres = {tabla.item(fila, 0).text() for fila in range(tabla.rowCount())}
        assert nombres == {"Ana", "luis", "Troll"}
        # Ana esta en la lista blanca y es operadora; luis solo en la lista blanca.
        assert tabla.item(0, 2).text() == "Si"
        # El bloqueado se ve aunque el servidor este detenido (lo lee del fichero).
        bloqueados = {
            tabla.item(fila, 0).text()
            for fila in range(tabla.rowCount())
            if tabla.item(fila, 4).text() == "Si"
        }
        assert bloqueados == {"Troll"}
        assert "bloqueado" in window.players.status.text().lower()
        assert "detenido" in window.players.status.text().lower()
        # Con el servidor detenido se pueden preparar las listas (se escriben
        # en disco); expulsar y ver el inventario si necesitan el servidor vivo.
        assert window.players._action_buttons["gestion"].isEnabled()
        assert window.players._action_buttons["op"].isEnabled()
        assert window.players._action_buttons["whitelist_add"].isEnabled()
        assert not window.players._action_buttons["kick"].isEnabled()
        assert not window.players._action_buttons["inventario"].isEnabled()

    def test_con_el_servidor_en_marcha_se_pueden_aplicar_acciones(
        self, window: MainWindow, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        # Se simula el estado en marcha y la consola del servidor.
        monkeypatch.setattr(
            window.manager, "players_snapshot", lambda server_id: __import__(
                "serviscraft.core.players", fromlist=["PlayersSnapshot"]
            ).PlayersSnapshot(online=("Ana",), max_players=20, running=True)
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        enviadas: list[tuple] = []
        monkeypatch.setattr(
            window.manager,
            "run_player_action",
            lambda server_id, action, player=None: enviadas.append((action, player)) or "ok",
        )

        window.players.player_input.setText("Ana")
        window.players._action_buttons["op"].click()
        window.runner.wait_for_done(5000)

        assert enviadas == [("op", "Ana")]

    def test_un_nombre_invalido_avisa_sin_enviar_nada(
        self, window: MainWindow, store: ServerStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        enviadas: list[tuple] = []
        monkeypatch.setattr(
            window.manager,
            "run_player_action",
            lambda server_id, action, player=None: enviadas.append((action, player)) or "ok",
        )
        avisos: list[tuple] = []
        monkeypatch.setattr(
            "serviscraft.ui.players_panel.show_error",
            lambda *args, **kwargs: avisos.append((args, kwargs)),
        )

        window.players.player_input.setText("Ana; stop")
        window.players._action_buttons["op"].click()
        window.runner.wait_for_done(2000)

        assert enviadas == []
        assert avisos, "se esperaba un aviso de nombre no valido"


    def test_al_cambiar_de_servidor_se_olvida_el_jugador_anterior(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        import json

        primero = make_spec()
        segundo = make_spec(id="servidor-test02", name="Otro servidor", port=25566, rcon_port=25576)
        for spec in (primero, segundo):
            store.prepare_dirs(spec.id)
            store.save(spec)
        (store.data_dir(primero.id) / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )

        window._on_views_ready(
            [
                ServerView(spec=primero, state=ServerState.CREATED),
                ServerView(spec=segundo, state=ServerState.CREATED),
            ]
        )
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()
        assert window.players.table.rowCount() == 1

        # Se selecciona un jugador del primer servidor y despues se cambia de servidor.
        window.players.table.selectRow(0)
        qapp.processEvents()
        assert window.players.player_input.text() == "Ana"

        window.select_server(segundo.id)
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        assert window.players.player_input.text() == ""
        assert window.players.table.rowCount() == 0

    def test_las_fichas_resumen_lo_que_hay(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        import json

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}, {"uuid": "2", "name": "luis"}]),
            encoding="utf-8",
        )
        (store.data_dir(spec.id) / "ops.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        (store.data_dir(spec.id) / "banned-players.json").write_text(
            json.dumps([{"uuid": "3", "name": "Troll"}]), encoding="utf-8"
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Jugadores"))
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        textos = [chip.text() for chip in window.players.chips.widgets()]
        assert textos[0] == "Conectados: 0"
        assert textos[1].startswith("Lista blanca: 2")
        assert textos[2] == "Operadores: 1"
        assert textos[3] == "Bloqueados: 1"
        # Hay bloqueados, asi que la ficha se ve.
        assert not window.players.chip_banned.isHidden()

    def test_la_ficha_de_bloqueados_se_esconde_si_no_hay_ninguno(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        import json

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        assert window.players.chip_banned.text() == "Bloqueados: 0"
        assert window.players.chip_banned.isHidden()

    def test_los_jugadores_de_bedrock_se_reconocen_por_el_punto(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Floodgate antepone un punto: la ficha lo explica y lo cuenta."""
        import json

        spec = make_spec(type=ServerType.PAPER, bedrock=True)
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "whitelist.json").write_text(
            json.dumps(
                [
                    {"uuid": "1", "name": "Ana"},
                    {"uuid": "2", "name": ".Steve"},
                ]
            ),
            encoding="utf-8",
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        tabla = window.players.table
        nombres = {tabla.item(fila, 0).text() for fila in range(tabla.rowCount())}
        assert nombres == {"Ana", ".Steve"}
        fila_steve = next(
            fila for fila in range(tabla.rowCount()) if tabla.item(fila, 0).text() == ".Steve"
        )
        assert "Bedrock" in tabla.item(fila_steve, 0).toolTip()
        assert not window.players.chip_bedrock.isHidden()
        assert window.players.chip_bedrock.text() == "Bedrock: 1"

        tabla.selectRow(fila_steve)
        qapp.processEvents()
        assert not window.players.bedrock_chip.isHidden()
        assert "Bedrock" in window.players.actions_note.text()
        # El nombre que se envia al servidor conserva el punto.
        assert window.players._target_name() == ".Steve"
        assert window.players.player_input.maxLength() == 33

    def test_cada_fila_lleva_la_cara_del_jugador(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        import json

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        tabla = window.players.table
        assert tabla.rowCount() == 1
        assert not tabla.item(0, 0).icon().isNull()

    def test_las_cabezas_usan_la_skin_real_del_jugador(
        self,
        window: MainWindow,
        store: ServerStore,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Los conectados y los desconectados comparten el mismo camino de skin."""
        import json

        from PySide6.QtCore import QBuffer
        from PySide6.QtGui import QColor, QImage

        from serviscraft.ui import players_panel

        imagen = QImage(64, 64, QImage.Format.Format_ARGB32)
        imagen.fill(QColor("#28c878"))
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        assert imagen.save(buffer, "PNG")
        skin = bytes(buffer.data())
        buffer.close()
        monkeypatch.setattr(players_panel, "cached_skin", lambda _name: skin)

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}, {"uuid": "2", "name": "luis"}]),
            encoding="utf-8",
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        tabla = window.players.table
        assert tabla.rowCount() == 2
        for fila in range(tabla.rowCount()):
            cara = tabla.item(fila, 0).icon().pixmap(28, 28)
            color = cara.toImage().pixelColor(cara.width() // 2, cara.height() // 2)
            assert color.green() > color.red()
            assert color.green() > color.blue()

    def test_sin_jugadores_aparece_la_cabeza_con_signo_de_duda(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        assert window.players.table.rowCount() == 0
        assert not window.players.players_empty.isHidden()
        assert "todavia no hay jugadores" in window.players.players_empty.title.text().lower()

        # La ranura de la ficha tambien deja de estar vacia: muestra una cabeza
        # gris con el signo de duda, no la cara de un jugador inventado.
        pixmap = window.players.selection_slot._pixmap
        assert not pixmap.isNull()
        centro = pixmap.toImage().pixelColor(pixmap.width() // 2, pixmap.height() // 2)
        assert centro.red() > 220 and centro.green() > 220 and centro.blue() > 180

    def test_las_acciones_tienen_estilos_distintos_y_espaciado(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        from serviscraft.core.players import PLAYER_ACTIONS
        from serviscraft.ui import theme

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()

        props = {
            boton.property("playerAction")
            for boton in window.players.actions_row.widgets()
        }
        assert {action.key for action in PLAYER_ACTIONS} <= props
        assert "inventario" in props
        assert window.players.actions_row.flow.spacing() >= 10

        css = theme.build_stylesheet(qapp.palette())
        for key in ("op", "whitelist_add", "kick", "ban", "pardon", "inventario"):
            assert f'playerAction="{key}"' in css
        assert 'panelRole="stone"' in css

    def test_los_botones_de_jugador_tienen_nombres_cortos(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Los botones se leen enteros y explican lo que hacen al pasar el raton."""
        from serviscraft.core.players import PLAYER_ACTIONS

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()

        for action in PLAYER_ACTIONS:
            assert len(action.label) <= 18, action.label
        for boton in window.players.actions_row.widgets():
            assert boton.toolTip(), boton.text()
        assert window.players.inventory_button.text() == "Ver inventario"

    def test_un_solo_boton_gestiona_lista_blanca_bloqueados_y_operadores(
        self,
        window: MainWindow,
        store: ServerStore,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """La ventana de gestion reune las tres listas y funciona sin servidor."""
        import json

        from serviscraft.ui.players_manager_dialog import PlayersManagerDialog

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        data = store.data_dir(spec.id)
        (data / "whitelist.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        (data / "ops.json").write_text(
            json.dumps([{"uuid": "1", "name": "Ana"}]), encoding="utf-8"
        )
        (data / "banned-players.json").write_text(
            json.dumps([{"uuid": "3", "name": "Troll"}]), encoding="utf-8"
        )
        monkeypatch.setattr(
            window.manager.client, "container_state", lambda name: ServerState.EXITED
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Jugadores"))
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        window.players.manage_button.click()
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        dialogo = window.players._gestion
        assert isinstance(dialogo, PlayersManagerDialog)
        assert dialogo.isVisible()
        # Las tres listas se leen del disco aunque el servidor este apagado.
        assert [dialogo._lists["whitelist"].item(i).text() for i in range(dialogo._lists["whitelist"].count())] == ["Ana"]
        assert [dialogo._lists["ops"].item(i).text() for i in range(dialogo._lists["ops"].count())] == ["Ana"]
        assert [dialogo._lists["banned"].item(i).text() for i in range(dialogo._lists["banned"].count())] == ["Troll"]
        assert "detenido" in dialogo.resumen.text().lower()

        # Se anade un invitado sin tener el servidor encendido.
        dialogo._inputs["whitelist"].setText("Luis")
        dialogo._add_buttons["whitelist"].click()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        datos = json.loads((data / "whitelist.json").read_text(encoding="utf-8"))
        assert {entrada["name"] for entrada in datos} == {"Ana", "Luis"}
        assert dialogo._inputs["whitelist"].text() == ""

        # Y se perdona a un bloqueado.
        dialogo._lists["banned"].setCurrentRow(0)
        dialogo._remove_buttons["banned"].click()
        window.runner.wait_for_done(5000)
        qapp.processEvents()
        assert json.loads((data / "banned-players.json").read_text(encoding="utf-8")) == []

        dialogo.close()
        qapp.processEvents()
        assert window.players._gestion is not None  # la referencia se limpia al cambiar de servidor

    def test_la_lista_blanca_se_activa_y_desactiva(
        self,
        window: MainWindow,
        store: ServerStore,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        data = store.data_dir(spec.id)
        (data / "server.properties").write_text("white-list=false\n", encoding="utf-8")
        monkeypatch.setattr(
            window.manager.client, "container_state", lambda name: ServerState.EXITED
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        qapp.processEvents()
        window.players.manage_button.click()
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        dialogo = window.players._gestion
        assert not dialogo.whitelist_check.isChecked()
        dialogo.whitelist_check.setChecked(True)
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        propiedades = (data / "server.properties").read_text(encoding="utf-8")
        assert "white-list=true" in propiedades
        assert dialogo.whitelist_check.isChecked()
        dialogo.close()


class TestImportarInterfaz:
    """La ventana de importacion reconoce el servidor y rellena los datos."""

    def _origen(self, tmp_path: Path) -> Path:
        raiz = tmp_path / "servidor-exportado"
        (raiz / "world").mkdir(parents=True)
        (raiz / "plugins").mkdir(parents=True)
        (raiz / "world" / "level.dat").write_bytes(b"nivel")
        (raiz / "plugins" / "EssentialsX.jar").write_bytes(b"jar")
        (raiz / "server.properties").write_text(
            "motd=Mi mundo\nlevel-name=world\nserver-port=25565\n", encoding="utf-8"
        )
        (raiz / "version_history.json").write_text(
            '{"currentVersion": "git-Paper-196 (MC: 1.20.4)"}', encoding="utf-8"
        )
        return raiz

    def test_ensena_lo_que_ha_reconocido(
        self, qapp: QApplication, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from serviscraft.core.import_server import inspect_source
        from serviscraft.ui.import_dialog import ImportServerDialog

        info = inspect_source(self._origen(tmp_path))
        dialogo = ImportServerDialog(window.manager, window.runner, window.config, parent=window)
        dialogo._on_inspected(info)
        qapp.processEvents()

        assert dialogo.name.text() == info.name
        assert dialogo.version_combo.currentText() == "1.20.4"
        assert dialogo.port.value() == 25565
        assert not dialogo.detect_card.isHidden()
        assert "Paper" in dialogo.detect_label.text()
        assert "Plugins: 1" in dialogo.detect_label.text()
        assert dialogo.import_button.isEnabled()
        assert "1.20.4" in dialogo.summary.text()

    def test_sin_origen_no_deja_importar(
        self, qapp: QApplication, window: MainWindow
    ) -> None:
        from serviscraft.ui.import_dialog import ImportServerDialog

        dialogo = ImportServerDialog(window.manager, window.runner, window.config, parent=window)
        assert not dialogo.import_button.isEnabled()
        assert dialogo._info is None


class TestInventario:
    """Ventana de la mochila de un jugador (se abre desde «Jugadores»)."""

    def _inventario(self):
        from serviscraft.core.inventory import ItemStack, PlayerInventory

        return PlayerInventory(
            player="Ana",
            items=(
                ItemStack(0, "minecraft:diamond_sword", 1),
                ItemStack(1, "minecraft:torch", 64),
                ItemStack(9, "minecraft:oak_planks", 32),
                ItemStack(103, "minecraft:diamond_helmet", 1),
                ItemStack(-106, "minecraft:shield", 1),
            ),
            health=17.0,
            food=18,
            level=32,
        )

    def test_ensena_la_mochila_con_la_forma_del_juego(
        self, qapp: QApplication, window: MainWindow
    ) -> None:
        from serviscraft.ui.inventory_dialog import InventoryDialog

        dialogo = InventoryDialog(self._inventario(), parent=window)
        dialogo.show()
        for _ in range(6):
            qapp.processEvents()

        assert "Ana" in dialogo.title.text()
        assert [chip.text() for chip in dialogo.chips.widgets()] == [
            "Vida: 17 de 20",
            "Comida: 18",
            "Nivel 32",
            "99 objetos en 5 huecos",
        ]
        # Los nueve huecos de la barra rapida y los 27 del inventario, mas la
        # armadura y la mano secundaria: aunque el objeto no este, el hueco se ve.
        assert dialogo.grid.count() >= 27 + 9 + 6
        dialogo.close()

    def test_el_boton_actualizar_vuelve_a_preguntar_al_servidor(
        self, qapp: QApplication, window: MainWindow
    ) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        from serviscraft.ui.inventory_dialog import InventoryDialog

        llamadas: list[int] = []
        dialogo = InventoryDialog(
            self._inventario(), on_refresh=lambda: llamadas.append(1), parent=window
        )
        dialogo.show()
        qapp.processEvents()
        caja = dialogo.findChild(QDialogButtonBox)
        assert caja is not None
        actualizar = next(b for b in caja.buttons() if b.text() == "Actualizar")
        actualizar.click()
        qapp.processEvents()
        assert llamadas == [1]
        dialogo.close()

    def test_el_boton_ver_inventario_abre_la_mochila(
        self,
        qapp: QApplication,
        window: MainWindow,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        pedidos: list[tuple[str, str]] = []
        inventario = self._inventario()
        monkeypatch.setattr(
            window.manager,
            "player_inventory",
            lambda server_id, player: pedidos.append((server_id, player)) or inventario,
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        window.players.player_input.setText("Ana")

        window.players.inventory_button.click()
        window.runner.wait_for_done(5000)
        for _ in range(6):
            qapp.processEvents()

        assert pedidos == [(spec.id, "Ana")]
        dialogo = window.players._inventario
        assert dialogo is not None
        assert dialogo.isVisible()
        assert "Ana" in dialogo.title.text()
        dialogo.close()
        window.runner.wait_for_done(3000)

    def test_sin_el_servidor_en_marcha_no_se_pregunta_nada(
        self,
        qapp: QApplication,
        window: MainWindow,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
        sin_dialogos_modales: dict[str, list],
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        pedidos: list[tuple[str, str]] = []
        monkeypatch.setattr(
            window.manager,
            "player_inventory",
            lambda server_id, player: pedidos.append((server_id, player)) or None,
        )
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.players.player_input.setText("Ana")

        window.players.inventory_button.click()
        qapp.processEvents()

        assert pedidos == []
        assert window.players._inventario is None
        assert any("inventario" in str(aviso).lower() for aviso in sin_dialogos_modales["errores"])

    def test_sin_nombre_de_jugador_se_avisa(
        self,
        qapp: QApplication,
        window: MainWindow,
        store: ServerStore,
        sin_dialogos_modales: dict[str, list],
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        window.players.player_input.clear()

        window.players.inventory_button.click()
        qapp.processEvents()

        assert window.players._inventario is None
        assert sin_dialogos_modales["errores"]

    def test_al_cambiar_de_servidor_se_cierra_la_mochila(
        self,
        qapp: QApplication,
        window: MainWindow,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        primero = make_spec()
        segundo = make_spec(id="servidor-test02", name="Otro servidor", port=25566, rcon_port=25576)
        for spec in (primero, segundo):
            store.prepare_dirs(spec.id)
            store.save(spec)
        inventario = self._inventario()
        monkeypatch.setattr(window.manager, "player_inventory", lambda server_id, player: inventario)

        window._on_views_ready(
            [
                ServerView(spec=primero, state=ServerState.RUNNING),
                ServerView(spec=segundo, state=ServerState.RUNNING),
            ]
        )
        window.players.player_input.setText("Ana")
        window.players.inventory_button.click()
        window.runner.wait_for_done(5000)
        qapp.processEvents()
        assert window.players._inventario is not None

        window.select_server(segundo.id)
        qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        assert window.players._inventario is None


class TestCopiasEnLaInterfaz:
    def test_la_pestana_de_copias_muestra_donde_estan(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        from serviscraft.ui.backups_panel import ETIQUETAS_ORIGEN

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Copias"))
        qapp.processEvents()

        esperado = str(store.backups_dir(spec.id))
        assert window.backups.location.text() == esperado
        assert esperado in window.backups.location.toolTip()
        assert ETIQUETAS_ORIGEN["al-detener"] == "al detener"

        window.backups._copy_path()
        assert QApplication.clipboard().text() == esperado

    def test_una_copia_automatica_se_ve_como_tal(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "world").mkdir()
        (store.data_dir(spec.id) / "world" / "level.dat").write_bytes(b"mundo")
        window.manager.backups.create_backup(spec.id, label="al-detener", origin="al-detener")

        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Copias"))
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        assert window.backups.table.rowCount() == 1
        assert window.backups.table.item(0, 3).text() == "al detener"

    def test_abrir_la_carpeta_de_copias(
        self,
        window: MainWindow,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from serviscraft.ui import backups_panel as backups_module

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        abiertas: list[str] = []

        class FalsoDesktop:
            @staticmethod
            def openUrl(url) -> bool:
                abiertas.append(url.toLocalFile())
                return True

        monkeypatch.setattr(backups_module, "QDesktopServices", FalsoDesktop)
        window.backups._open_folder()

        assert abiertas == [str(store.backups_dir(spec.id))]


class TestDetalles:
    def test_muestra_los_datos_del_servidor(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec(memory_mb=2048, port=25700, rcon_port=26700)
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()
        etiquetas = window.details._labels
        assert etiquetas["name"].text() == spec.name
        assert etiquetas["port"].text() == "25700"
        assert str(spec.memory_mb) not in etiquetas["memory_limit"].text().split(" ")[0]
        assert "asignados" in etiquetas["memory_limit"].text()
        assert str(store.data_dir(spec.id)) == etiquetas["data_path"].text()

    def test_el_limite_incluye_la_sobrecarga_del_jvm(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        from serviscraft.core.models import format_bytes

        spec = make_spec(type="FORGE", memory_mb=4096)
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        esperado = format_bytes((4096 + jvm_overhead_mb(ServerType.FORGE)) * 1024 * 1024)
        assert esperado in window.details._labels["memory_limit"].text()

    def test_el_resumen_y_las_seis_tarjetas_cuentan_el_servidor(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Las tarjetas nuevas y los chips muestran los mismos datos que la ficha."""
        spec = make_spec(
            name="Reino Trebol",
            type=ServerType.FABRIC,
            version="1.21.4",
            memory_mb=4096,
            port=25700,
        )
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        qapp.processEvents()

        detalles = window.details
        titulos = [tarjeta.title_label.full_text() for tarjeta in detalles._cards]
        assert titulos == [
            "Tu servidor",
            "Como se ve en Minecraft",
            "Recursos y puertos",
            "Fechas y rutas",
            "Notas",
            "Mantenimiento",
        ]
        assert all(tarjeta.isVisibleTo(detalles) for tarjeta in detalles._cards)
        assert detalles.summary_row.isVisibleTo(detalles)
        assert detalles.empty.isHidden()

        assert detalles.chip_state.text() == "Estado: En marcha"
        assert detalles.chip_type.text() == "Tipo: Fabric"
        assert detalles.chip_version.text() == "Minecraft: 1.21.4"
        assert detalles.chip_memory.text() == "Memoria: 4G"
        assert detalles.chip_port.text() == "Puerto: 25700"

        # Sin servidor se apartan las tarjetas y queda el aviso centrado.
        detalles.set_server(None, ServerState.MISSING)
        assert not detalles.summary_row.isVisibleTo(detalles)
        assert not any(tarjeta.isVisibleTo(detalles) for tarjeta in detalles._cards)
        assert detalles.empty.isVisibleTo(detalles)
        assert detalles.chip_state.text() == "Estado: Sin servidor"

    def test_las_rutas_se_copian_con_un_clic(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """El icono de la ranura copia la ruta sin tener que seleccionarla."""
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()

        campo = window.details._labels["data_path"]
        assert isinstance(campo, QLineEdit)
        assert campo.actions(), "la ruta debe tener el boton de copiar"
        campo.actions()[0].trigger()
        assert QApplication.clipboard().text() == str(store.data_dir(spec.id))

    def test_los_titulos_de_las_tarjetas_caben_a_480_px(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: «Como se ve en Minecraft» se recortaba en ventana estrecha."""
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()
        window.resize(480, 640)
        for indice in range(window.tabs.count()):
            if window.tabs.tabText(indice) == "Detalles":
                window.tabs.setCurrentIndex(indice)
                break
        for _ in range(12):
            qapp.processEvents()

        recortados = [
            etiqueta.full_text()
            for tarjeta in window.details._cards
            for etiqueta in (tarjeta.title_label,)
            if etiqueta.text() != etiqueta.full_text()
        ]
        assert not recortados, "titulos recortados a 480 px: " + ", ".join(recortados)


class TestAdaptabilidad:
    """Adaptacion al ancho de la ventana (mosaico automatico tipo Polonium).

    Un gestor de ventanas con mosaico da a la ventana el ancho que quiere
    (1/2, 1/3 o 1/4 de la pantalla) sin respetar su tamano minimo. Estas
    pruebas comprueban que, pase lo que pase, no hay textos a medias.
    """

    #: Anchos que puede imponer el mosaico (1/4, 1/3, 1/2 y pantalla completa).
    ANCHOS = (480, 560, 700, 900, 1280)

    def test_las_barras_envuelven_en_varias_filas(self, qapp: QApplication) -> None:
        """Con sitio, una sola fila; sin sitio, varias, pero nada recortado."""
        from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

        from serviscraft.ui.common import FlowRow

        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        fila = FlowRow()
        botones = [
            fila.add(QPushButton(texto))
            for texto in ("Iniciar", "Detener", "Reiniciar", "Ajustes", "Eliminar")
        ]
        layout.addWidget(fila)
        # Como en los paneles reales: el contenido de debajo ocupa el alto que sobra.
        layout.addStretch(1)
        contenedor.show()

        medido: dict[int, tuple[int, int]] = {}
        for ancho in (900, 300, 220):
            contenedor.resize(ancho, 320)
            for _ in range(8):
                qapp.processEvents()
            assert all(
                boton.width() >= boton.sizeHint().width() - 2 for boton in botones
            ), f"boton recortado a {ancho} px"
            medido[ancho] = (len({boton.y() for boton in botones}), fila.height())

        assert medido[900][0] == 1, "con sitio deberia quedar en una sola fila"
        assert medido[300][0] > 1, "sin sitio deberia envolver en varias filas"
        assert medido[220][1] > medido[900][1], "la fila deberia crecer de alto al envolver"

    def test_las_barras_se_adaptan_a_ventanas_estrechas(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """A cualquier ancho y en cualquier pestana, nada queda recortado."""
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()

        recortes: list[str] = []
        for ancho in self.ANCHOS:
            window.resize(ancho, 640)
            for _ in range(10):
                qapp.processEvents()
            assert window.width() == ancho, f"la ventana no acepta {ancho} px de ancho"
            for indice in range(window.tabs.count()):
                window.tabs.setCurrentIndex(indice)
                for _ in range(6):
                    qapp.processEvents()
                controles = [
                    *window.findChildren(QPushButton),
                    *window.findChildren(QCheckBox),
                ]
                controles += [
                    etiqueta
                    for etiqueta in window.findChildren(QLabel)
                    if etiqueta.text().strip()
                    and not etiqueta.wordWrap()
                    and not isinstance(etiqueta, ElidedLabel)
                ]
                for control in controles:
                    if not control.isVisible():
                        continue
                    texto = control.text() if hasattr(control, "text") else ""
                    # Se recorta cuando es mas estrecho que su texto...
                    if control.width() < control.sizeHint().width() - 2:
                        recortes.append(
                            f"[{ancho} px · {window.tabs.tabText(indice)}] «{texto}»: "
                            f"{control.width()} px para {control.sizeHint().width()} px"
                        )
                        continue
                    # ...o cuando se sale por la derecha de la ventana.
                    esquina = control.mapTo(window, QPoint(0, 0))
                    if esquina.x() + control.width() > window.width() + 2:
                        recortes.append(
                            f"[{ancho} px · {window.tabs.tabText(indice)}] «{texto}» se sale "
                            f"de la ventana: llega a {esquina.x() + control.width()} px"
                        )
        assert not recortes, "controles recortados:\n" + "\n".join(recortes)

    def test_el_texto_ajustado_cabe_en_su_altura(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el texto ajustado se recortaba por arriba en ventana estrecha.

        Qt reserva a una etiqueta con ``setWordWrap(True)`` el alto de **una**
        linea (el de su ``sizeHint``, calculado con el ancho larguisimo del
        texto). Si la ventana es mas estrecha, el texto necesita mas lineas y se
        dibujaba centrado: se veia cortado por arriba y se solapaba con lo de
        abajo. Ahora cada etiqueta reserva el alto que pide su ancho real.
        """
        from PySide6.QtCore import QRect, Qt
        from PySide6.QtWidgets import QLabel

        from serviscraft.ui.common import parece_texto_con_formato

        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.select_server(spec.id)
        window.show()

        cortes: list[str] = []
        for ancho in self.ANCHOS:
            window.resize(ancho, 640)
            for _ in range(10):
                qapp.processEvents()
            for indice in range(window.tabs.count()):
                window.tabs.setCurrentIndex(indice)
                for _ in range(8):
                    qapp.processEvents()
                for etiqueta in window.findChildren(QLabel):
                    if not etiqueta.isVisible() or not etiqueta.text().strip():
                        continue
                    if not etiqueta.wordWrap() or isinstance(etiqueta, ElidedLabel):
                        continue
                    if parece_texto_con_formato(etiqueta.text()):
                        continue
                    # Alto que de verdad necesita el texto con la fuente que se
                    # pinta y el ancho que tiene la etiqueta.
                    necesario = etiqueta.fontMetrics().boundingRect(
                        QRect(0, 0, etiqueta.width(), 10000),
                        Qt.TextFlag.TextWordWrap,
                        etiqueta.text(),
                    ).height()
                    if necesario > etiqueta.height() + 1:
                        cortes.append(
                            f"[{ancho} px · {window.tabs.tabText(indice)}] "
                            f"{etiqueta.objectName() or 'QLabel'}: {etiqueta.height()} px de alto "
                            f"para un texto que necesita {necesario} px "
                            f"(«{etiqueta.text()[:40]}…»)"
                        )
        assert not cortes, "etiquetas ajustadas cortadas:\n" + "\n".join(cortes)

    def test_la_barra_lateral_se_oculta_sola_y_vuelve(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """En ventana estrecha la lista se aparta; al ensanchar, vuelve sola."""
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()

        window.resize(1280, 800)
        for _ in range(8):
            qapp.processEvents()
        assert window.sidebar.isVisible()

        window.resize(520, 640)
        for _ in range(8):
            qapp.processEvents()
        assert not window.sidebar.isVisible(), "la barra lateral no se aparta"
        assert not window.sidebar_button.isChecked()
        assert window.stack.width() > window.width() - 60, (
            "al ocultarse la lista el contenido deberia quedarse con el ancho"
        )

        window.resize(1280, 800)
        for _ in range(8):
            qapp.processEvents()
        assert window.sidebar.isVisible(), "la barra lateral no vuelve al ensanchar"
        assert window.sidebar_button.isChecked()

    def test_el_usuario_manda_sobre_la_barra_lateral(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Si la cierra el usuario, la adaptacion automatica no la reabre."""
        window.show()
        window.resize(1280, 800)
        for _ in range(8):
            qapp.processEvents()

        window.sidebar_button.setChecked(False)
        for _ in range(4):
            qapp.processEvents()
        assert not window.sidebar.isVisible()

        window.resize(520, 640)
        for _ in range(6):
            qapp.processEvents()
        window.resize(1280, 800)
        for _ in range(8):
            qapp.processEvents()
        assert not window.sidebar.isVisible(), "no se respeta la eleccion del usuario"

        window.action_sidebar.trigger()
        for _ in range(6):
            qapp.processEvents()
        assert window.sidebar.isVisible(), "el menu Ver debe poder recuperar la lista"
        assert window.sidebar_button.isChecked()

    def test_la_etiqueta_de_estado_nunca_se_queda_sin_sitio(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el grupo de botones de la consola se comia el ancho de la etiqueta.

        Al medir se vio que la etiqueta de estado llegaba a quedarse con 0 px (y a
        mostrarse vacia) porque ``QHBoxLayout`` reparte el ancho que falta quitando
        primero el de la etiqueta. Ahora tiene su propia linea.
        """
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()

        fallos: list[str] = []
        for ancho in self.ANCHOS:
            window.resize(ancho, 640)
            for _ in range(10):
                qapp.processEvents()
            etiqueta = window.console.status_label
            if etiqueta.width() < 60:
                fallos.append(f"{ancho} px: la etiqueta solo tiene {etiqueta.width()} px")
            if not etiqueta.text().strip():
                fallos.append(f"{ancho} px: la etiqueta se queda vacia")
            elif not etiqueta.text().endswith("…") and etiqueta.text() != etiqueta.full_text():
                fallos.append(f"{ancho} px: texto a medias sin puntos suspensivos: {etiqueta.text()!r}")
        assert not fallos, "\n".join(fallos)

    def test_ninguna_etiqueta_queda_con_un_solo_caracter(self, qapp: QApplication) -> None:
        """Con muy poco sitio es mejor no mostrar nada que un resto («C»)."""
        etiqueta = ElidedLabel("Consola de «Servidor supervivencia extremo» — en directo")
        etiqueta.show()
        for ancho in (1, 3, 5, 7, 9, 12, 16, 24):
            etiqueta.resize(ancho, 24)
            for _ in range(4):
                qapp.processEvents()
            texto = etiqueta.text()
            if texto in ("", etiqueta.full_text()):
                continue
            assert texto.endswith("…"), f"recorte sin puntos suspensivos: {texto!r}"
            assert len(texto.replace("…", "").strip()) >= 2, (
                f"resto degenerado {texto!r} con {ancho} px de ancho"
            )

    def test_las_pestanas_altas_se_desplazan_sin_comprimir_los_paneles(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: en una ventana baja los botones se dibujaban encima del texto.

        La pestana de Mods es la mas larga. Sin un area de desplazamiento, el
        panel se comprimia por debajo de su minimo y las barras que envuelven se
        salian de su sitio. Ahora el panel conserva su alto minimo y, si no cabe,
        aparece una barra vertical; cuando hay sitio, se estira y no hay barra.
        """
        from PySide6.QtWidgets import QScrollArea

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()
        indice = _indice_pestana(window, "Mods")
        window.tabs.setCurrentIndex(indice)
        pagina = window.tabs.widget(indice)

        assert isinstance(pagina, QScrollArea)
        assert window._panel_de(pagina) is window.mods

        window.resize(480, 420)
        for _ in range(15):
            qapp.processEvents()
        assert window.mods.height() >= window.mods.minimumSizeHint().height()
        assert pagina.verticalScrollBar().maximum() > 0, "deberia poder desplazarse"

        window.resize(1180, 820)
        for _ in range(15):
            qapp.processEvents()
        assert pagina.verticalScrollBar().maximum() == 0, (
            "con sitio de sobra no deberia hacer falta desplazarse"
        )


class TestTareas:
    def test_tarea_correcta(self, qapp: QApplication) -> None:
        from serviscraft.ui.tasks import TaskRunner

        resultados = []
        runner = TaskRunner()
        runner.submit("prueba", lambda *, context: 21 * 2, on_finished=resultados.append)
        runner.wait_for_done(5000)
        qapp.processEvents()
        assert resultados == [42]
        assert not runner.busy

    def test_tarea_con_error(self, qapp: QApplication) -> None:
        from serviscraft.ui.tasks import TaskRunner

        fallos = []

        def explota(*, context):
            raise ValueError("algo fue mal")

        runner = TaskRunner()
        runner.submit("prueba", explota, on_failed=lambda m, d: fallos.append(m))
        runner.wait_for_done(5000)
        qapp.processEvents()
        assert fallos and "algo fue mal" in fallos[0]

    def test_descripcion_de_errores(self) -> None:
        from serviscraft.core.errors import ValidationError
        from serviscraft.ui.tasks import describe_error

        mensaje, detalle = describe_error(ValidationError("port", "El puerto no vale."))
        assert mensaje == "El puerto no vale."
        assert "ValidationError" in detalle

        mensaje, _ = describe_error(PermissionError("nope"))
        assert "Permiso denegado" in mensaje


class TestEstadoVacio:
    """Sin servidores seleccionados no debe quedar ningun boton suelto.

    Se usa ``isHidden`` (no ``isVisible``): la pagina de contenido esta oculta y
    lo que interesa saber es si cada widget estaria a la vista.
    """

    def test_los_paneles_muestran_solo_el_aviso(
        self, window: MainWindow, qapp: QApplication
    ) -> None:
        window.show()
        window._on_views_ready([])
        qapp.processEvents()

        assert not window.backups.empty.isHidden()
        for widget in (
            window.backups.table,
            window.backups.backups_actions,
            window.backups.keep_actions,
            window.backups.location_row,
            window.backups.warning,
        ):
            assert widget.isHidden(), widget

        assert not window.players.empty.isHidden()
        for widget in (
            window.players.table,
            window.players.player_input,
            window.players.actions_row,
            window.players.status,
        ):
            assert widget.isHidden(), widget
        window.close()

    def test_al_eliminar_el_ultimo_servidor_se_vacian_los_paneles(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        qapp.processEvents()
        # Con servidor: los paneles muestran su contenido.
        assert window.players.table.isHidden() is False
        assert window.players.empty.isHidden() is True
        assert window.backups.location.text() == str(store.backups_dir(spec.id))

        # Se elimina el ultimo servidor.
        window._on_views_ready([])
        qapp.processEvents()
        assert window.players.table.isHidden() is True
        assert not window.players.empty.isHidden()
        assert window.backups.location.text() == ""
        assert window.views == {}
        window.close()


def test_el_icono_se_puede_cargar(qapp: QApplication) -> None:
    from PySide6.QtGui import QIcon, QPixmap

    icono = QIcon(str(paths.bundled_resource("icons", "serviscraft.svg")))
    assert not icono.isNull()
    pixeles = icono.pixmap(64, 64)
    assert not pixeles.isNull() and pixeles.width() == 64
    assert isinstance(pixeles, QPixmap)


class TestModpacksEnLaCreacion:
    """El modpack se traduce a los ajustes que entiende la imagen."""

    @staticmethod
    def _plan():
        from serviscraft.core.modrinth import ModpackPlan

        return ModpackPlan(
            slug="cobblemon-fabric",
            project_id="cobblemon",
            version_id="Oa9ZDzZq",
            version_number="1.6.0",
            loader="fabric",
            minecraft_version="1.21.1",
            title="Cobblemon",
        )

    def test_elegir_un_modpack_fija_tipo_version_y_variables(
        self,
        qapp: QApplication,
        store: ServerStore,
        config: AppConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from PySide6.QtWidgets import QDialog

        from serviscraft.ui import modpack_dialog as modpack_module
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        plan = self._plan()
        monkeypatch.setattr(modpack_module.ModpackDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        monkeypatch.setattr(modpack_module.ModpackDialog, "values", lambda self: plan)

        manager = ServerManager(store=store, config=config)
        dialogo = CreateServerDialog(manager, TaskRunner(), config)
        try:
            dialogo.name.setText("Con modpack")
            dialogo.port.setValue(manager.next_free_port(25900))
            dialogo.modpack_check.setChecked(True)
            dialogo._choose_modpack()

            assert dialogo.server_type is ServerType.MODRINTH
            assert dialogo.version_combo.currentText() == "1.21.1"
            # La version la fija el pack: no se edita a mano.
            assert not dialogo.version_combo.isEnabled()
            # El tipo de servidor tambien lo fija el pack.
            assert not dialogo.type_combo.isEnabled()

            valores = dialogo.values()
            assert valores["type"] is ServerType.MODRINTH
            assert valores["version"] == "1.21.1"
            assert valores["extra_env"] == {
                "MODRINTH_MODPACK": "cobblemon-fabric",
                "MODRINTH_VERSION": "Oa9ZDzZq",
                "MODRINTH_LOADER": "fabric",
            }
        finally:
            dialogo.close()

    def test_sin_elegir_modpack_avisa_en_lugar_de_crear_algo_raro(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.errors import ValidationError
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = CreateServerDialog(ServerManager(store=store, config=config), TaskRunner(), config)
        try:
            dialogo.name.setText("Sin modpack")
            dialogo.modpack_check.setChecked(True)
            with pytest.raises(ValidationError):
                dialogo.values()
        finally:
            dialogo.close()

    def test_desmarcar_el_modpack_vuelve_a_paper(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.create_dialog import CreateServerDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = CreateServerDialog(ServerManager(store=store, config=config), TaskRunner(), config)
        try:
            dialogo.modpack_check.setChecked(True)
            dialogo.modpack_check.setChecked(False)
            assert dialogo.server_type is ServerType.PAPER
            assert dialogo.version_combo.isEnabled()
            assert dialogo.type_combo.isEnabled()
        finally:
            dialogo.close()

    def test_el_selector_de_modpacks_deja_elegir_version(
        self, qapp: QApplication
    ) -> None:
        from serviscraft.core.modrinth import Project, Release
        from serviscraft.ui.modpack_dialog import ModpackDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = ModpackDialog(TaskRunner())
        try:
            dialogo._fill(
                [Project("cobblemon", "cobblemon-fabric", "Cobblemon", "Pokemon", 5000, project_type="modpack")]
            )
            dialogo.table.selectRow(0)
            assert dialogo.table.rowCount() == 1

            dialogo._project = Project(
                "cobblemon", "cobblemon-fabric", "Cobblemon", "Pokemon", 5000, project_type="modpack"
            )
            dialogo._fill_versions(
                [
                    Release(
                        project_id="cobblemon",
                        name="Con NeoForge",
                        version_number="1.7.0",
                        game_versions=("1.21.4",),
                        loaders=("neoforge",),
                        download_url="u",
                        filename="a.mrpack",
                    ),
                    Release(
                        project_id="cobblemon",
                        name="Con Fabric",
                        version_number="1.6.0",
                        game_versions=("1.21.1",),
                        loaders=("fabric",),
                        download_url="u",
                        filename="b.mrpack",
                        version_id="Oa9ZDzZq",
                    ),
                ]
            )

            # Se preselecciona la primera version instalable (Fabric).
            assert "fabric" in dialogo.version_combo.currentText()
            assert dialogo.accept_button.isEnabled()
            plan = dialogo.values()
            assert plan is not None and plan.minecraft_version == "1.21.1"

            # Y una version que requiere NeoForge no se puede usar.
            dialogo.version_combo.setCurrentIndex(0)
            assert not dialogo.accept_button.isEnabled()
            assert dialogo.values() is None
        finally:
            dialogo.close()

    def test_los_filtros_del_selector_de_modpacks_reducen_la_lista(
        self, qapp: QApplication
    ) -> None:
        from serviscraft.core.modrinth import Project
        from serviscraft.ui.modpack_dialog import ModpackDialog
        from serviscraft.ui.tasks import TaskRunner

        def pack(pid: str, loaders: tuple[str, ...], lado: str) -> Project:
            return Project(
                pid,
                pid,
                pid.title(),
                "Descripcion",
                1000,
                project_type="modpack",
                loaders=loaders,
                server_side=lado,
                updated="2025-03-04T10:00:00Z",
            )

        dialogo = ModpackDialog(TaskRunner())
        try:
            dialogo._fill(
                [
                    pack("fabric", ("fabric",), "required"),
                    pack("neoforge", ("neoforge",), "unsupported"),
                    pack("sindatos", (), "required"),
                ]
            )
            # Por defecto se ocultan los packs que solo publican NeoForge.
            assert dialogo.table.rowCount() == 2
            assert dialogo.table.item(0, 4).text() == "04/03/2025"

            dialogo.only_installable.setChecked(False)
            assert dialogo.table.rowCount() == 3

            # Filtro de cargador: solo los de Fabric.
            dialogo.loader_combo.setCurrentIndex(1)
            assert dialogo.table.rowCount() == 1
            assert dialogo.table.item(0, 0).text() == "Fabric"

            # Y el filtro por lado deja solo los de cliente.
            dialogo.loader_combo.setCurrentIndex(0)
            dialogo.side_combo.setCurrentIndex(2)
            assert dialogo.table.rowCount() == 1
            assert dialogo.table.item(0, 0).text() == "Neoforge"

            dialogo.side_combo.setCurrentIndex(0)
            assert dialogo.table.rowCount() == 3
        finally:
            dialogo.close()

    def test_un_filtro_sin_resultados_lo_explica(self, qapp: QApplication) -> None:
        from serviscraft.core.modrinth import Project
        from serviscraft.ui.modpack_dialog import ModpackDialog
        from serviscraft.ui.tasks import TaskRunner

        dialogo = ModpackDialog(TaskRunner())
        try:
            dialogo._fill(
                [
                    Project(
                        "p",
                        "p",
                        "Pack",
                        "",
                        1,
                        project_type="modpack",
                        loaders=("fabric",),
                        server_side="required",
                    )
                ]
            )
            dialogo.side_combo.setCurrentIndex(2)  # Solo cliente
            assert dialogo.table.rowCount() == 0
            assert "Ninguno de los 1 modpacks" in dialogo.status.text()
            assert dialogo.values() is None
        finally:
            dialogo.close()

    def test_el_catalogo_oculta_por_defecto_lo_que_no_sirve_en_servidor(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.modrinth import Project
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="FABRIC")
        dialogo = CatalogDialog(ServerManager(store=store, config=config), TaskRunner(), spec, "mods")
        try:
            dialogo._fill(
                [
                    Project(
                        "cliente",
                        "cliente",
                        "Solo cliente",
                        "",
                        10,
                        project_type="mod",
                        server_side="unsupported",
                    ),
                    Project(
                        "servidor",
                        "servidor",
                        "Sirve",
                        "",
                        20,
                        project_type="mod",
                        server_side="required",
                    ),
                ]
            )
            assert dialogo.table.rowCount() == 1
            assert dialogo.table.item(0, 0).text() == "Sirve"

            dialogo.side_combo.setCurrentIndex(1)  # Cliente o servidor
            assert dialogo.table.rowCount() == 2

            dialogo.side_combo.setCurrentIndex(2)  # Solo cliente
            assert dialogo.table.rowCount() == 1
            assert dialogo.table.item(0, 0).text() == "Solo cliente"
        finally:
            dialogo.close()


class TestCatalogoDeModrinth:
    def test_la_busqueda_usa_el_orden_y_los_filtros_del_servidor(
        self,
        qapp: QApplication,
        store: ServerStore,
        config: AppConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from serviscraft.core import modrinth
        from serviscraft.core.modrinth import Project
        from serviscraft.ui import catalog_dialog
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="FABRIC", version="1.21.4")
        visto: dict[str, object] = {}

        def falso_search(query: str, **kwargs):
            visto["query"] = query
            visto.update(kwargs)
            return [
                Project(
                    "p1",
                    "sodium",
                    "Sodium",
                    "Motor de renderizado",
                    100,
                    project_type="mod",
                    server_side="required",
                )
            ]

        monkeypatch.setattr(modrinth, "search_projects", falso_search)
        monkeypatch.setattr(catalog_dialog.iconos_remotos, "prefetch", lambda _urls: None)

        dialogo = CatalogDialog(ServerManager(store=store, config=config), TaskRunner(), spec, "mods")
        try:
            dialogo.search_input.setText("sodium")
            dialogo._search_timer.stop()
            dialogo.sort_combo.setCurrentIndex(3)  # Actualizados
            dialogo.search()
            _esperar(dialogo, qapp, lambda: dialogo._has_searched)

            assert visto["query"] == "sodium"
            assert visto["index"] == "updated"
            assert visto["project_type"] == "mod"
            assert visto["game_version"] == "1.21.4"
            assert visto["loaders"] == dialogo.loaders
            assert dialogo.table.rowCount() == 1
            assert dialogo.table.item(0, 0).text() == "Sodium"
        finally:
            dialogo.close()

    def test_el_catalogo_ensena_todas_las_versiones_y_marca_las_compatibles(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.modrinth import Project, Release
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="PAPER", version="1.21.4")
        proyecto = Project(
            "p1", "essentialsx", "EssentialsX", "Comandos", 10, project_type="plugin"
        )
        incompatible = Release(
            "p1",
            "EssentialsX viejo",
            "0.9",
            ("1.20.1",),
            ("paper",),
            "https://cdn.modrinth.com/0.9.jar",
            "essentialsx-0.9.jar",
            version_type="release",
            published="2024-01-02T10:00:00Z",
        )
        compatible = Release(
            "p1",
            "EssentialsX nuevo",
            "2.0",
            ("1.21.4",),
            ("paper",),
            "https://cdn.modrinth.com/2.0.jar",
            "essentialsx-2.0.jar",
            version_type="beta",
            published="2025-03-04T10:00:00Z",
        )
        dialogo = CatalogDialog(
            ServerManager(store=store, config=config), TaskRunner(), spec, "plugins"
        )
        try:
            dialogo._fill([proyecto])
            dialogo.table.selectRow(0)
            dialogo._fill_versions([incompatible, compatible])

            assert dialogo.versions_table.rowCount() == 2
            assert "2 versiones publicadas" in dialogo.versions_title.text()
            assert "1 compatible" in dialogo.versions_title.text()
            assert "essentialsx-0.9.jar" in dialogo.versions_table.item(0, 0).toolTip()
            # La primera version compatible se elige sola.
            assert dialogo.versions_table.currentRow() == 1
            assert dialogo.install_button.isEnabled()

            dialogo.versions_table.selectRow(0)
            assert not dialogo.install_button.isEnabled()
            assert "no es compatible" in dialogo.status.text()
        finally:
            dialogo.close()

    def test_el_modo_seleccion_no_descarga_y_emite_lo_elegido(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.modrinth import ContentSelection, Project, Release
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        proyecto = Project(
            "p1", "essentialsx", "EssentialsX", "Comandos", 10, project_type="plugin"
        )
        release = Release(
            "p1",
            "EssentialsX 2.0",
            "2.0",
            ("1.21.4",),
            ("paper",),
            "https://cdn.modrinth.com/2.0.jar",
            "essentialsx-2.0.jar",
        )
        dialogo = CatalogDialog(
            None,
            TaskRunner(),
            None,
            "plugins",
            selection=True,
            server_type=ServerType.PAPER,
            version="1.21.4",
            loaders=("paper",),
        )
        capturado: list[ContentSelection] = []
        dialogo.content_selected.connect(capturado.append)
        try:
            dialogo._fill([proyecto])
            dialogo.table.selectRow(0)
            dialogo._fill_versions([release])
            dialogo._install_selected()

            assert len(capturado) == 1
            assert capturado[0].project.slug == "essentialsx"
            assert capturado[0].release.filename == "essentialsx-2.0.jar"
            assert dialogo.installed == []
            assert "Anadido" in dialogo.status.text()
        finally:
            dialogo.close()

    def test_cargar_mas_pide_la_siguiente_tanda_con_offset(
        self,
        qapp: QApplication,
        store: ServerStore,
        config: AppConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from serviscraft.core import modrinth
        from serviscraft.core.modrinth import Project
        from serviscraft.ui import catalog_dialog
        from serviscraft.ui.catalog_dialog import CatalogDialog, SEARCH_LIMIT
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="FABRIC", version="1.21.4")
        vistos: list[int] = []

        def falso_search(_query: str, **kwargs):
            vistos.append(kwargs.get("offset", 0))
            return [
                Project(
                    "p2",
                    "lithium",
                    "Lithium",
                    "Optimizacion",
                    10,
                    project_type="mod",
                    server_side="required",
                )
            ]

        monkeypatch.setattr(modrinth, "search_projects", falso_search)
        monkeypatch.setattr(catalog_dialog.iconos_remotos, "prefetch", lambda _urls: None)

        dialogo = CatalogDialog(
            ServerManager(store=store, config=config), TaskRunner(), spec, "mods"
        )
        try:
            dialogo._projects = [
                Project(
                    "p1",
                    "sodium",
                    "Sodium",
                    "Motor",
                    20,
                    project_type="mod",
                    server_side="required",
                )
            ]
            dialogo._offset = SEARCH_LIMIT
            dialogo._has_more = True
            dialogo._load_more()
            _esperar(dialogo, qapp, lambda: len(dialogo._projects) == 2)

            assert vistos == [SEARCH_LIMIT]
            assert [p.id for p in dialogo._projects] == ["p1", "p2"]
            assert dialogo._offset == SEARCH_LIMIT + 1
            assert not dialogo._has_more
        finally:
            dialogo.close()

    def test_escribir_mientras_busca_relanza_la_consulta_al_terminar(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="FABRIC")
        dialogo = CatalogDialog(ServerManager(store=store, config=config), TaskRunner(), spec, "mods")
        try:
            llamadas: list[str] = []
            dialogo.search = lambda: llamadas.append("buscar")  # type: ignore[method-assign]
            dialogo._busy = True
            dialogo._on_search_text_changed("sodium")
            assert dialogo._pending_search

            dialogo._busy = False
            dialogo._search_again_if_pending()
            _esperar(dialogo, qapp, lambda: bool(llamadas))
            assert llamadas == ["buscar"]
        finally:
            dialogo.close()

    def test_instalar_no_pierde_la_busqueda_escrita_mientras_tanto(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        """Al acabar una instalacion se lanza la busqueda que quedo pendiente."""
        from types import SimpleNamespace

        from serviscraft.core.modrinth import Project
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type="FABRIC")
        dialogo = CatalogDialog(
            ServerManager(store=store, config=config), TaskRunner(), spec, "mods"
        )
        try:
            proyecto = Project(
                "p1",
                "sodium",
                "Sodium",
                "Motor de renderizado",
                100,
                project_type="mod",
                server_side="required",
            )
            dialogo._fill([proyecto])
            dialogo.table.selectRow(0)

            capturado: dict[str, object] = {}

            def falso_submit(_desc, _work, **kwargs):
                capturado.update(kwargs)
                return object()

            dialogo.runner.submit = falso_submit  # type: ignore[method-assign]
            dialogo._install_selected()
            assert dialogo._busy

            # El usuario escribe mientras la instalacion esta en marcha.
            dialogo._on_search_text_changed("otra cosa")
            assert dialogo._pending_search

            llamadas: list[str] = []
            dialogo._search_again_if_pending = lambda: llamadas.append("buscar")
            finished = capturado["on_finished"]
            assert callable(finished)
            finished((SimpleNamespace(version_number="1.0", dependencies=()), "sodium.jar"))

            assert llamadas == ["buscar"]
            assert dialogo.installed == ["sodium.jar"]
            assert not dialogo._busy
        finally:
            dialogo.close()


class TestPreferenciasDeCopias:
    def test_guardar_las_opciones_de_copias(
        self, qapp: QApplication, config: AppConfig
    ) -> None:
        from serviscraft.ui.settings_dialog import PreferencesDialog

        config.backup_on_stop = True
        config.scheduled_backup_minutes = 0
        config.automatic_backup_keep = 8
        dialogo = PreferencesDialog(config)
        try:
            assert dialogo.stop_backup.isChecked()
            assert dialogo.scheduled_backup.value() == 0
            assert dialogo.automatic_keep.value() == 8

            dialogo.stop_backup.setChecked(False)
            dialogo.scheduled_backup.setValue(120)
            dialogo.automatic_keep.setValue(3)
            dialog_value = dialogo.scheduled_backup.value()
            assert dialog_value == 120

            from PySide6.QtWidgets import QDialog

            # Sin tocar nada mas, se guarda al pulsar Guardar.
            dialogo._on_accept()
            assert dialogo.result() == QDialog.DialogCode.Accepted
        finally:
            dialogo.close()

        guardado = AppConfig.load()
        assert guardado.backup_on_stop is False
        assert guardado.scheduled_backup_minutes == 120
        assert guardado.automatic_backup_keep == 3

    def test_el_temporizador_de_copias_sigue_a_las_preferencias(
        self, window: MainWindow
    ) -> None:
        window.config.scheduled_backup_minutes = 45
        window._configurar_copia_programada()
        assert window.backup_timer.isActive()
        assert window.backup_timer.interval() == 45 * 60_000

        window.config.scheduled_backup_minutes = 0
        window._configurar_copia_programada()
        assert not window.backup_timer.isActive()

    def test_la_copia_programada_copia_los_servidores_en_marcha(
        self,
        window: MainWindow,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
        qapp: QApplication,
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "world").mkdir()
        (store.data_dir(spec.id) / "world" / "level.dat").write_bytes(b"mundo")
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        # El gestor vuelve a preguntar a Podman quien esta en marcha.
        monkeypatch.setattr(
            window.manager.client,
            "managed_containers",
            lambda: [{"Names": [spec.container_name], "State": "running"}],
        )

        window._on_scheduled_backup()
        # Se espera al aviso final (no solo a que exista el fichero): el
        # mensaje de estado se escribe cuando la tarea de fondo termina.
        _esperar(window, qapp, lambda: "Copia programada" in window.status_message.text())

        copias = window.manager.backups.list_backups(spec.id)
        assert [info.origin for info in copias] == ["programada"]
        assert "Copia programada" in window.status_message.text()

    def test_sin_servidores_en_marcha_la_copia_programada_no_hace_nada(
        self, window: MainWindow, store: ServerStore
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])

        window._on_scheduled_backup()

        assert window.manager.backups.list_backups(spec.id) == []
        assert window.status_message.text() != "Copia programada"

    def test_copiar_todos_los_servidores_a_mano(
        self,
        window: MainWindow,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
        qapp: QApplication,
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        (store.data_dir(spec.id) / "world").mkdir()
        (store.data_dir(spec.id) / "world" / "level.dat").write_bytes(b"mundo")
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        monkeypatch.setattr("serviscraft.ui.main_window.confirm", lambda *a, **k: True)
        informados: list[tuple] = []
        monkeypatch.setattr(
            "serviscraft.ui.main_window.show_info", lambda *a, **k: informados.append((a, k))
        )

        window.backup_all_servers()
        _esperar(window, qapp, lambda: bool(informados))

        copias = window.manager.backups.list_backups(spec.id)
        assert [info.origin for info in copias] == ["manual"]
        assert "Copias creadas" in informados[0][0][1]


class TestCierreConServidores:
    def test_al_salir_detiene_los_servidores_y_actualiza_el_estado(
        self,
        window: MainWindow,
        store: ServerStore,
        monkeypatch: pytest.MonkeyPatch,
        qapp: QApplication,
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.RUNNING)])
        detenidos: list[str] = []
        monkeypatch.setattr(
            window.manager, "stop_server", lambda server_id, **k: detenidos.append(server_id)
        )

        window._stop_and_exit([spec])
        assert window._saliendo_tras_detener is True

        _esperar(window, qapp, lambda: not window._saliendo_tras_detener)

        assert detenidos == [spec.id]
        assert window.views[spec.id].state is ServerState.EXITED

    def test_la_barra_de_operacion_no_se_queda_encendida_tras_un_refresco(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Los refrescos de fondo no son «operaciones»: no deben dejar la barra."""
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window.show()
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Detalles"))
        for _ in range(10):
            qapp.processEvents()
        window.runner.wait_for_done(5000)
        qapp.processEvents()

        assert not window.operation.isVisible()


class TestPestanaDeMods:
    """La pestana «Mods»: listar, activar sin borrar y detectar lo que falta."""

    def _panel(self, store: ServerStore, config: AppConfig, spec):
        from serviscraft.ui.mods_panel import ModsPanel
        from serviscraft.ui.tasks import TaskRunner

        panel = ModsPanel(ServerManager(store=store, config=config), TaskRunner())
        panel.set_server(spec, running=False)
        return panel

    def test_lista_activa_y_desactiva_sin_borrar(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        spec = make_spec(type=ServerType.FABRIC)
        store.prepare_dirs(spec.id)
        store.save(spec)
        carpeta = store.data_dir(spec.id) / "mods"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "create.jar").write_bytes(b"PK\x03\x04")
        (carpeta / "sodium.jar.desactivado").write_bytes(b"PK\x03\x04")

        panel = self._panel(store, config, spec)
        try:
            assert panel.table.rowCount() == 2
            assert panel.table.item(0, 1).text() == "activo"
            assert panel.table.item(1, 1).text() == "desactivado"
            # En un servidor sin modpack, todo lo que hay lo puso el usuario.
            assert panel.table.item(0, 2).text() == "personalizado"
            # Regresion: decia «1 desactivados».
            assert "1 activo, 1 desactivado (" in panel.status.text()

            panel.table.selectRow(0)
            panel._toggle_selected()

            assert (carpeta / "create.jar.desactivado").is_file()
            assert not (carpeta / "create.jar").exists()
            assert panel.table.item(0, 1).text() == "desactivado"

            panel.table.selectRow(1)
            panel._toggle_selected()
            assert (carpeta / "sodium.jar").is_file()
        finally:
            panel.close()

    def test_los_mods_del_modpack_se_marcan_y_avisan_al_borrar(
        self, qapp: QApplication, store: ServerStore, config: AppConfig, monkeypatch
    ) -> None:
        from serviscraft.ui import mods_panel as modulo

        spec = make_spec(type=ServerType.MODRINTH, extra_env={"MODRINTH_MODPACK": "cobblemon"})
        store.prepare_dirs(spec.id)
        store.save(spec)
        carpeta = store.data_dir(spec.id) / "mods"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "del-pack.jar").write_bytes(b"PK\x03\x04")
        (carpeta / "mio.jar").write_bytes(b"PK\x03\x04")

        panel = self._panel(store, config, spec)
        try:
            assert panel.table.item(0, 1).text() == "activo"
            origenes = {panel.table.item(fila, 0).text(): panel.table.item(fila, 2).text()
                        for fila in range(panel.table.rowCount())}
            assert origenes == {"del-pack.jar": "del modpack", "mio.jar": "del modpack"}

            # Un fichero anadido por la interfaz si queda marcado como propio.
            (carpeta / "mio.jar").unlink()
            panel._inventory.mark_custom("mio.jar")
            (carpeta / "mio.jar").write_bytes(b"PK\x03\x04")
            panel.refresh()
            origenes = {panel.table.item(fila, 0).text(): panel.table.item(fila, 2).text()
                        for fila in range(panel.table.rowCount())}
            assert origenes["mio.jar"] == "personalizado"
            assert origenes["del-pack.jar"] == "del modpack"

            avisos: list[str] = []

            def falso_confirm(parent, titulo, texto, **kwargs):
                avisos.append(texto)
                return True

            monkeypatch.setattr(modulo, "confirm", falso_confirm)
            for fila in range(panel.table.rowCount()):
                if panel.table.item(fila, 0).text() == "del-pack.jar":
                    panel.table.selectRow(fila)
            panel._delete_selected()

            assert any("volvera a instalarlo" in texto for texto in avisos)
            assert not (carpeta / "del-pack.jar").exists()
        finally:
            panel.close()

    def test_detecta_los_mods_que_faltan_y_marca_los_que_ya_estan(
        self, qapp: QApplication, store: ServerStore, config: AppConfig, monkeypatch
    ) -> None:
        spec = make_spec(type=ServerType.MODRINTH, extra_env={"MODRINTH_MODPACK": "cobblemon"})
        store.prepare_dirs(spec.id)
        store.save(spec)
        carpeta = store.data_dir(spec.id) / "mods"
        carpeta.mkdir(parents=True, exist_ok=True)
        # Este ya esta dentro: debe salir en verde.
        (carpeta / "fabric-api-0.100.1.jar").write_bytes(b"PK\x03\x04")
        registros = store.data_dir(spec.id) / "logs"
        registros.mkdir(parents=True, exist_ok=True)
        (registros / "latest.log").write_text(
            "[12:00:00] [main/ERROR]: Missing or unsupported mandatory dependencies:\n"
            "\tMod ID: 'fabric-api', Requested by: 'cobblemon', Actual version: '[MISSING]'\n"
            "[12:00:01] [main/ERROR]: Failed to download https://modrinth.com/mod/create\n"
        )

        manager = ServerManager(store=store, config=config)
        # El contenedor no existe: se lee solo el registro del disco.
        monkeypatch.setattr(manager, "recent_logs", lambda *a, **k: "")
        from serviscraft.ui.mods_panel import ModsPanel
        from serviscraft.ui.tasks import TaskRunner

        panel = ModsPanel(manager, TaskRunner())
        try:
            panel.set_server(spec, running=False)
            panel.analyze_logs()
            _esperar(panel, qapp, lambda: panel.missing_table.rowCount() == 2)

            estados = {
                panel.missing_table.item(fila, 0).text(): panel.missing_table.item(fila, 1).text()
                for fila in range(panel.missing_table.rowCount())
            }
            assert estados == {"fabric-api": "ya esta en el servidor", "create": "falta"}
            enlaces = {
                panel.missing_table.item(fila, 0).text(): panel.missing_table.item(fila, 2).text()
                for fila in range(panel.missing_table.rowCount())
            }
            assert enlaces["create"] == "https://modrinth.com/mod/create"
            assert enlaces["fabric-api"].startswith("https://modrinth.com/mods?q=")
        finally:
            panel.close()

    def test_copiar_el_jar_descargado_lo_deja_en_el_servidor(
        self, qapp: QApplication, store: ServerStore, config: AppConfig, tmp_path: Path
    ) -> None:
        from serviscraft.core.missing_mods import MissingMod

        spec = make_spec(type=ServerType.FABRIC)
        store.prepare_dirs(spec.id)
        store.save(spec)
        descargado = tmp_path / "create-1.20.1.jar"
        descargado.write_bytes(b"PK\x03\x04contenido")

        panel = self._panel(store, config, spec)
        panel._files_dialog = lambda *a, **k: (str(descargado), "")
        try:
            panel._missing = [MissingMod(name="create", url="https://modrinth.com/mod/create")]
            panel._update_missing_rows()
            panel.missing_table.selectRow(0)
            panel._copy_missing_file()

            copiado = store.data_dir(spec.id) / "mods" / "create-1.20.1.jar"
            assert copiado.is_file()
            assert copiado.read_bytes() == b"PK\x03\x04contenido"
            # Y la fila pasa a verde: ya esta dentro del servidor.
            assert panel.missing_table.item(0, 1).text() == "ya esta en el servidor"
        finally:
            panel.close()

    def test_el_resumen_cuenta_activos_desactivados_y_tamano(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core.models import format_bytes

        spec = make_spec(type=ServerType.FABRIC)
        store.prepare_dirs(spec.id)
        store.save(spec)
        carpeta = store.data_dir(spec.id) / "mods"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "create.jar").write_bytes(b"x" * 100)
        (carpeta / "sodium.jar.desactivado").write_bytes(b"x" * 50)

        panel = self._panel(store, config, spec)
        try:
            assert panel.chip_folder.text() == "Carpeta: mods"
            assert panel.chip_files.text() == "Ficheros: 2"
            assert panel.chip_active.text() == "Activos: 1"
            assert panel.chip_disabled.text() == "Desactivados: 1"
            assert panel.chip_size.text() == f"Ocupan: {format_bytes(150)}"
            # El origen y el tamano siguen en el tooltip aunque la columna se
            # aparte en ventanas estrechas.
            tooltip = panel.table.item(0, 0).toolTip()
            assert "Origen: personalizado" in tooltip
            assert f"Tamano: {format_bytes(100)}" in tooltip

            panel.set_server(None, running=False)
            assert panel.empty.isVisibleTo(panel)
            assert not panel.summary_row.isVisibleTo(panel)
            assert not panel.card_installed.isVisibleTo(panel)
            assert not panel.card_missing.isVisibleTo(panel)
            assert panel.chip_files.text() == "Ficheros: ?"
            assert panel.hero.title.full_text() == "Mods y complementos"
        finally:
            panel.close()

    def test_las_columnas_secundarias_se_apartan_en_ventanas_estrechas(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        spec = make_spec(type=ServerType.FABRIC)
        store.prepare_dirs(spec.id)
        store.save(spec)
        carpeta = store.data_dir(spec.id) / "mods"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "fabric-api-0.100.4+1.21.4.jar").write_bytes(b"PK\x03\x04")

        panel = self._panel(store, config, spec)
        panel.show()
        try:
            panel.resize(480, 700)
            for _ in range(8):
                qapp.processEvents()
            assert panel.width() == 480
            assert panel.table.isColumnHidden(2), "«Origen» debe apartarse a 480 px"
            assert panel.table.isColumnHidden(3), "«Tamano» debe apartarse a 480 px"
            assert panel.missing_table.isColumnHidden(2), "el enlace debe apartarse a 480 px"
            # El nombre del fichero se queda con el sitio que dejan libre.
            assert panel.table.columnWidth(0) > 200

            panel.resize(900, 700)
            for _ in range(8):
                qapp.processEvents()
            assert not panel.table.isColumnHidden(2)
            assert not panel.table.isColumnHidden(3)
            assert not panel.missing_table.isColumnHidden(2)
        finally:
            panel.close()

    def test_sin_ficheros_se_ve_un_aviso_en_vez_de_una_tabla_vacia(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        spec = make_spec(type=ServerType.FABRIC)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            assert not panel.table.isVisibleTo(panel)
            assert panel.installed_empty.isVisibleTo(panel)
            assert "Todavia no hay mods" in panel.installed_empty.title.text()
            # El aviso es una seccion propia: la pista de doble clic y la
            # leyenda no se apilan encima, y una linea los separa de los botones.
            assert not panel.installed_hint.isVisibleTo(panel)
            assert not panel.legend.isVisibleTo(panel)
            assert not panel.status.isVisibleTo(panel)
            assert panel.installed_separator.isVisibleTo(panel)
            # La tabla de pendientes tampoco aparece hasta que se analiza.
            assert not panel.missing_table.isVisibleTo(panel)
            assert panel.missing_empty.isVisibleTo(panel)
            assert "Sin mods pendientes" in panel.missing_empty.title.text()
            assert not panel.missing_hint.isVisibleTo(panel)
            assert panel.missing_separator.isVisibleTo(panel)
        finally:
            panel.close()

    def test_se_pueden_soltar_varios_ficheros_a_la_vez(
        self, qapp: QApplication, store: ServerStore, config: AppConfig, tmp_path: Path
    ) -> None:
        spec = make_spec(type=ServerType.FABRIC)
        store.prepare_dirs(spec.id)
        store.save(spec)
        primero = tmp_path / "create.jar"
        segundo = tmp_path / "jei.jar"
        primero.write_bytes(b"PK\x03\x04create")
        segundo.write_bytes(b"PK\x03\x04jei")

        panel = self._panel(store, config, spec)
        try:
            panel._add_dropped([str(primero), str(segundo)])
            carpeta = store.data_dir(spec.id) / "mods"
            assert (carpeta / "create.jar").is_file()
            assert (carpeta / "jei.jar").is_file()
            assert panel.table.rowCount() == 2
            assert panel.drop_zone.isVisibleTo(panel)
            assert panel.installed_hint.isVisibleTo(panel)
            assert not panel.installed_separator.isVisibleTo(panel)
        finally:
            panel.close()

    def test_un_servidor_de_pluguins_cambia_los_nombres(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        spec = make_spec(type=ServerType.PAPER)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            assert panel.chip_folder.text() == "Carpeta: plugins"
            assert panel.hero.title.full_text() == "Pluguins de «Servidor test»"
            assert panel.card_installed.title_label.full_text() == "Pluguins instalados"
            assert panel.card_missing.title_label.full_text() == "Pluguins que faltan"
        finally:
            panel.close()


class TestPestanaDeRegistros:
    """La pestana «Registros»: leer, filtrar y seguir un registro."""

    def test_muestra_el_ultimo_registro_y_filtra(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.logs_panel import LogsPanel
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        carpeta = store.data_dir(spec.id) / "logs"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "latest.log").write_text(
            "[12:00:00] [Server thread/INFO]: Done (3.2s)!\n"
            "[12:00:05] [Server thread/ERROR]: algo ha fallado\n"
        )

        panel = LogsPanel(ServerManager(store=store, config=config), TaskRunner())
        try:
            panel.set_server(spec, running=False)
            assert panel.source_combo.count() == 1
            assert "Done (3.2s)" in panel.view.toPlainText()

            panel.filter_input.setText("error")
            texto = panel.view.toPlainText()
            assert "algo ha fallado" in texto
            assert "Done (3.2s)" not in texto.split("\n")[0]

            panel.filter_input.clear()
            assert "Done (3.2s)" in panel.view.toPlainText()
        finally:
            panel.close()

    def test_sin_registros_lo_explica(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.logs_panel import LogsPanel
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = LogsPanel(ServerManager(store=store, config=config), TaskRunner())
        try:
            panel.set_server(spec, running=False)
            assert "Todavia no hay registros" in panel.status.text()
        finally:
            panel.close()

    def test_el_boton_de_mods_faltantes_avisa_a_la_ventana(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Registros"))
        for _ in range(6):
            qapp.processEvents()

        window.logs.missing_button.click()
        qapp.processEvents()

        assert window._panel_de(window.tabs.currentWidget()) is window.mods


class TestPestanaUnirse:
    """La pestana «Unirse»: direccion y modo de cuentas (premium o sin licencia)."""

    def _panel(self, store, config, spec):
        from serviscraft.ui.join_panel import JoinPanel
        from serviscraft.ui.tasks import TaskRunner

        panel = JoinPanel(ServerManager(store=store, config=config), TaskRunner())
        panel.set_server(spec, running=False)
        return panel

    def test_muestra_las_direcciones(self, qapp, store, config) -> None:
        spec = make_spec(lan=True)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            assert panel.local_address.text() == f"localhost:{spec.port}"
            assert panel.lan_address.text().endswith(f":{spec.port}")
            assert spec.container_name in panel.container_label.text()
        finally:
            panel.close()

    def test_sin_red_local_no_se_ofrece_la_direccion_de_la_red(self, qapp, store, config) -> None:
        spec = make_spec(lan=False)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            assert "solo este equipo" in panel.lan_address.text()
            assert not panel.copy_lan_button.isEnabled()
            assert "solo acepta conexiones de este mismo equipo" in panel.scope_note.text()
        finally:
            panel.close()

    def test_bedrock_automatico_muestra_la_direccion_y_los_pasos(
        self, qapp, store, config
    ) -> None:
        spec = make_spec(type=ServerType.PAPER, lan=False, bedrock=True)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            assert panel.bedrock_address.text() == f"localhost:{spec.bedrock_port}"
            assert panel.copy_bedrock_button.isEnabled()
            assert panel.bedrock_check.isChecked()
            assert "descargan solos" in panel.bedrock_note.text()
            assert "Solo se puede si usas el plugin" not in panel.bedrock_note.text()
        finally:
            panel.close()

    def test_paper_sin_bedrock_ensenia_la_direccion_si_se_instala_el_plugin(
        self, qapp: QApplication, store, config
    ) -> None:
        """Con Geyser puesto a mano no se puede detectar: se muestra igual."""
        spec = make_spec(type=ServerType.PAPER, lan=False)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            assert not panel.bedrock_check.isChecked()
            assert panel.bedrock_check.isEnabled()
            assert panel.bedrock_address.text() == f"localhost:{spec.bedrock_port}"
            assert panel.copy_bedrock_button.isEnabled()
            nota = panel.bedrock_note.text()
            assert "Solo se puede si usas el plugin" in nota
            assert "Plugins" in nota
            assert "puerto UDP" in nota

            panel.copy_bedrock_button.click()
            qapp.processEvents()
            assert QApplication.clipboard().text() == panel.bedrock_address.full_text()
        finally:
            panel.close()

    def test_un_servidor_sin_plugins_no_ofrece_bedrock(self, qapp, store, config) -> None:
        spec = make_spec(type=ServerType.VANILLA, lan=False)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            assert not panel.bedrock_check.isEnabled()
            assert panel.bedrock_address.text() == "No disponible"
            assert not panel.copy_bedrock_button.isEnabled()
            assert "Paper" in panel.bedrock_note.text()
        finally:
            panel.close()

    def test_los_botones_copian_la_direccion_que_se_ve(
        self, qapp: QApplication, store, config
    ) -> None:
        """El boton copia el valor cargado, no el texto vacio de la construccion."""
        spec = make_spec(lan=True)
        store.prepare_dirs(spec.id)
        store.save(spec)

        panel = self._panel(store, config, spec)
        try:
            panel.copy_local_button.click()
            qapp.processEvents()
            assert QApplication.clipboard().text() == f"localhost:{spec.port}"

            panel.copy_lan_button.click()
            qapp.processEvents()
            assert QApplication.clipboard().text() == panel.lan_address.full_text()
            assert panel.lan_address.full_text().endswith(f":{spec.port}")
        finally:
            panel.close()

    def test_el_ayudante_de_copia_no_llama_a_programas_externos_offscreen(
        self, qapp: QApplication, monkeypatch
    ) -> None:
        """En las pruebas solo se toca el portapapeles de Qt, nunca el real."""
        from serviscraft.ui import common

        llamadas: list[tuple] = []
        monkeypatch.setattr(common.subprocess, "run", lambda *args, **kwargs: llamadas.append(args))
        try:
            assert common.copiar_al_portapapeles("serviscraft-copia-123")
            assert QApplication.clipboard().text() == "serviscraft-copia-123"
            assert not llamadas
            assert not common.copiar_al_portapapeles("")
        finally:
            QApplication.clipboard().clear()

    def test_si_el_portapapeles_falla_avisa_y_muestra_la_direccion(
        self, qapp: QApplication, store, config, monkeypatch
    ) -> None:
        """Un fallo de copia no se queda en silencio: se puede copiar a mano."""
        from serviscraft.ui import join_panel as modulo

        spec = make_spec(lan=True)
        store.prepare_dirs(spec.id)
        store.save(spec)
        panel = self._panel(store, config, spec)
        errores: list[tuple[str, str]] = []
        monkeypatch.setattr(modulo, "copiar_al_portapapeles", lambda texto: False)
        monkeypatch.setattr(
            modulo,
            "show_error",
            lambda parent, titulo, mensaje, details="": errores.append((titulo, mensaje)),
        )
        try:
            panel.copy_lan_button.click()
            qapp.processEvents()
            assert errores, "no se aviso del fallo"
            assert panel.lan_address.full_text() in errores[0][1]
            assert "Ctrl+C" in errores[0][1]
        finally:
            panel.close()

    def test_quitar_el_modo_premium_avisa_y_guarda_al_reiniciar(
        self, qapp, store, config, monkeypatch
    ) -> None:
        from serviscraft.ui import join_panel as modulo

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)

        panel = self._panel(store, config, spec)
        preguntas: list[str] = []

        def falso_confirm(parent, titulo, texto, **kwargs):
            preguntas.append(texto)
            return True

        monkeypatch.setattr(modulo, "confirm", falso_confirm)
        try:
            # Por defecto se exige cuenta premium.
            assert panel.premium.isChecked()

            panel.premium.setChecked(False)
            assert panel.warning.isVisible() or "Aviso de seguridad" in panel.warning.text()
            # Hay cambios sin guardar: el boton esta activo.
            assert panel.apply_button.isEnabled()

            panel._save()
            _esperar(panel, qapp, lambda: not panel.apply_button.isEnabled())

            assert preguntas and "sin licencia" in preguntas[0]
            assert manager.properties(spec.id).get_bool("online-mode", True) is False
        finally:
            panel.close()

    def test_volver_a_premium_no_pide_confirmacion(self, qapp, store, config, monkeypatch) -> None:
        from serviscraft.ui import join_panel as modulo

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)
        props = manager.properties(spec.id)
        props.set("online-mode", "false")
        manager.save_properties(spec.id, props)

        panel = self._panel(store, config, spec)
        pedidas: list[str] = []
        monkeypatch.setattr(
            modulo, "confirm", lambda parent, titulo, texto, **k: pedidas.append(titulo) or True
        )
        try:
            assert not panel.premium.isChecked()
            panel.premium.setChecked(True)
            panel._save()
            _esperar(panel, qapp, lambda: manager.properties(spec.id).get_bool("online-mode", False))
            assert manager.properties(spec.id).get_bool("online-mode", False) is True
            assert pedidas == []
        finally:
            panel.close()


class TestPropiedades:
    """La pestana «Propiedades»: tarjetas, mandos grandes y textos sencillos."""

    def _filas(self, panel) -> dict[str, int]:
        filas: dict[str, int] = {}
        for fila in range(panel.table.rowCount()):
            item = panel.table.item(fila, 0)
            if item is not None:
                filas[item.text()] = fila
        return filas

    def _preparar(self, store, config, spec, valores: dict[str, str] | None = None):
        from serviscraft.ui.properties_panel import PropertiesPanel
        from serviscraft.ui.tasks import TaskRunner

        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)
        props = manager.properties(spec.id)
        for clave, valor in (valores or {}).items():
            props.set(clave, valor)
        manager.save_properties(spec.id, props)

        panel = PropertiesPanel(manager, TaskRunner())
        panel.set_server(spec)
        return panel, manager

    def test_las_tarjetas_y_los_resumenes_se_entienden(
        self, qapp: QApplication, store, config
    ) -> None:
        from serviscraft.ui.properties_panel import _PropertyCard

        spec = make_spec()
        panel, _manager = self._preparar(
            store,
            config,
            spec,
            {
                "motd": "Bienvenidos al Reino",
                "max-players": "8",
                "difficulty": "normal",
                "gamemode": "creative",
                "level-name": "mundo-reino",
            },
        )
        try:
            assert panel.title.text() == f"Propiedades de «{spec.name}»"
            titulos = {tarjeta.title_label.text() for tarjeta in panel.findChildren(_PropertyCard)}
            assert {
                "Tu servidor",
                "Como se juega",
                "Quien puede entrar",
                "El mundo",
            } <= titulos
            assert panel.summary_world.text() == "Mundo: mundo-reino"
            assert panel.summary_mode.text() == "Modo: Creativo"
            assert panel.summary_difficulty.text() == "Dificultad: Normal"
            assert panel.summary_players.text() == "Maximo: 8"
            assert panel.dirty_chip.text() == "Todo guardado"
            assert panel.restart_chip.text() == "Minecraft lo aplica al reiniciar"
            assert "reinicia" in panel.restart_chip.toolTip().lower()
        finally:
            panel.close()

    def test_los_desplegables_guardan_el_valor_real_de_minecraft(
        self, qapp: QApplication, store, config
    ) -> None:
        spec = make_spec()
        panel, manager = self._preparar(
            store,
            config,
            spec,
            {
                "difficulty": "normal",
                "gamemode": "creative",
                "pvp": "false",
                "max-players": "8",
            },
        )
        try:
            combo = panel._widgets["difficulty"][1]
            assert combo.currentText() == "Normal"
            assert combo.currentData() == "normal"

            combo.setCurrentIndex(combo.findData("hard"))
            qapp.processEvents()
            assert combo.currentText() == "Dificil"
            assert panel.dirty_chip.text() == "Cambios sin guardar"
            assert panel._table_values(exclude_managed=True)["difficulty"] == "hard"

            panel.save_button.click()
            qapp.processEvents()
            assert manager.properties(spec.id).get("difficulty") == "hard"
            assert manager.properties(spec.id).get("gamemode") == "creative"
            assert manager.properties(spec.id).get_bool("pvp", True) is False
            assert manager.properties(spec.id).get_int("max-players") == 8
            assert panel.dirty_chip.text() == "Todo guardado"
        finally:
            panel.close()

    def test_los_interruptores_actualizan_la_tabla_y_se_guardan(
        self, qapp: QApplication, store, config
    ) -> None:
        spec = make_spec()
        panel, manager = self._preparar(store, config, spec, {"pvp": "false"})
        try:
            interruptor = panel._widgets["pvp"][1]
            assert interruptor.objectName() == "PropertySwitch"
            assert interruptor.accessibleName() == "Peleas entre amigos"
            assert interruptor.sizeHint().width() >= 134

            panel.show()
            panel.resize(700, 700)
            for _ in range(10):
                qapp.processEvents()
            assert interruptor.width() >= 134, "el interruptor no debe comprimirse"

            interruptor.setChecked(True)
            qapp.processEvents()
            filas = self._filas(panel)
            assert panel.table.item(filas["pvp"], 1).text() == "true"
            assert panel.dirty_chip.text() == "Cambios sin guardar"

            panel.save_button.click()
            qapp.processEvents()
            assert manager.properties(spec.id).get_bool("pvp", False) is True
        finally:
            panel.close()

    def test_el_buscador_filtra_por_nombre_y_por_valor(
        self, qapp: QApplication, store, config
    ) -> None:
        spec = make_spec()
        panel, _manager = self._preparar(
            store,
            config,
            spec,
            {
                "motd": "Bienvenidos al Reino",
                "level-name": "mundo-reino",
                "pvp": "true",
                "difficulty": "normal",
            },
        )
        try:
            filas = self._filas(panel)
            panel.search.setText("pvp")
            qapp.processEvents()
            assert not panel.table.isRowHidden(filas["pvp"])
            assert panel.table.isRowHidden(filas["motd"])

            panel.search.setText("reino")
            qapp.processEvents()
            assert not panel.table.isRowHidden(filas["motd"])
            assert panel.table.isRowHidden(filas["difficulty"])

            panel.search.clear()
            qapp.processEvents()
            assert all(
                not panel.table.isRowHidden(fila) for fila in range(panel.table.rowCount())
            )
        finally:
            panel.close()

    def test_las_propiedades_gestionadas_estan_protegidas(
        self, qapp: QApplication, store, config, sin_dialogos_modales
    ) -> None:
        spec = make_spec()
        panel, _manager = self._preparar(store, config, spec)
        try:
            filas = self._filas(panel)
            fila = filas["server-port"]
            valor = panel.table.item(fila, 1)
            assert not (valor.flags() & Qt.ItemFlag.ItemIsEditable)
            assert panel.table.item(fila, 2).text() == "Protegida"
            assert not panel.table.item(fila, 2).icon().isNull()

            panel.table.setCurrentCell(fila, 1)
            antes = panel.table.rowCount()
            panel._remove_selected()
            qapp.processEvents()
            assert panel.table.rowCount() == antes
            assert any("protegida" in titulo.lower() for titulo, _m, _d in sin_dialogos_modales["errores"])
        finally:
            panel.close()

    def test_en_ventana_estrecha_los_campos_bajan_de_fila_sin_recortarse(
        self, qapp: QApplication, store, config
    ) -> None:
        from PySide6.QtCore import QPoint

        spec = make_spec()
        panel, _manager = self._preparar(store, config, spec)
        try:
            panel.show()
            panel.resize(480, 760)
            for _ in range(15):
                qapp.processEvents()

            viewport = panel.basic_scroll.viewport()
            assert panel.basic_scroll.horizontalScrollBar().maximum() == 0
            assert panel.basic_content.width() <= viewport.width() + 2

            for clave in ("motd", "max-players", "difficulty", "gamemode", "pvp", "enable-status"):
                _tipo, control = panel._widgets[clave]
                esquina = control.mapTo(viewport, QPoint(0, 0))
                assert esquina.x() + control.width() <= viewport.width() + 2, (
                    f"«{clave}» se sale de la ventana a 480 px: "
                    f"{esquina.x() + control.width()} px"
                )
                assert control.width() >= control.minimumSizeHint().width(), (
                    f"«{clave}» se comprime por debajo de su tamano minimo"
                )
        finally:
            panel.close()


class TestIconosDePlataforma:
    """Bloques de Minecraft: dicen si el servidor es de Java, de Bedrock o de los dos."""

    def test_los_iconos_se_dibujan(self, qapp) -> None:
        from serviscraft.ui import mc_icons

        for tam in (12, 16, 24, 40):
            for pixmap in (
                mc_icons.bloque_java(tam),
                mc_icons.bloque_bedrock(tam),
                mc_icons.icono_mod(tam),
                mc_icons.icono_plugin(tam),
                mc_icons.icono_pack(tam),
                mc_icons.icono_copiar(tam),
                mc_icons.icono_conectar(tam),
            ):
                assert not pixmap.isNull()
                assert pixmap.width() == tam and pixmap.height() == tam
        apagado = mc_icons.marcar_desactivado(mc_icons.bloque_java(16))
        assert not apagado.isNull()

    def test_bytes_invalidos_no_dan_icono(self, qapp) -> None:
        from serviscraft.ui.mc_icons import pixmap_de_bytes

        assert pixmap_de_bytes(b"no soy una imagen", 16).isNull()
        assert pixmap_de_bytes(b"", 16).isNull()

    def test_la_insignia_enseña_solo_los_bloques_que_corresponden(self, qapp) -> None:
        from serviscraft.ui.mc_icons import PlatformBadge

        java = make_spec(type=ServerType.PAPER)
        con_bedrock = make_spec(id="servidor-test02", type=ServerType.PAPER, bedrock=True)

        insignia = PlatformBadge()
        insignia.set_spec(java)
        # ``isHidden`` dice si el widget se oculto a proposito, aunque la ventana
        # de la prueba no este visible.
        assert not insignia.java_icon.isHidden()
        assert insignia.bedrock_icon.isHidden()

        insignia.set_spec(con_bedrock)
        assert not insignia.bedrock_icon.isHidden()
        assert not insignia.bedrock_text.isHidden()
        assert "Bedrock" in insignia.toolTip()

    def test_un_servidor_sin_bedrock_no_lo_anuncia(self, qapp, store, config) -> None:
        spec = make_spec(type=ServerType.PAPER)
        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)
        assert spec.platform_label == "Java"
        assert manager.store.load(spec.id).platform_label == "Java"

    def test_la_tarjeta_lateral_la_cabecera_y_los_detalles_lo_ensenan(
        self, qapp, window, store
    ) -> None:
        java = make_spec(id="servidor-java", type=ServerType.PAPER, name="Solo Java")
        bedrock = make_spec(
            id="servidor-bedrock", type=ServerType.PAPER, name="Con Bedrock", bedrock=True
        )
        for spec in (java, bedrock):
            store.prepare_dirs(spec.id)
            store.save(spec)
        window._on_views_ready(
            [
                ServerView(spec=java, state=ServerState.CREATED),
                ServerView(spec=bedrock, state=ServerState.EXITED),
            ]
        )

        tarjeta_java = window.sidebar._cards[java.id]
        tarjeta_bedrock = window.sidebar._cards[bedrock.id]
        assert tarjeta_java.platform.bedrock_icon.isHidden()
        assert not tarjeta_bedrock.platform.bedrock_icon.isHidden()

        window.select_server(bedrock.id)
        assert not window.header_platform.bedrock_icon.isHidden()
        assert window.header_platform.java_text.isHidden()  # en la cabecera solo van los bloques

        window.select_server(java.id)
        assert window.header_platform.bedrock_icon.isHidden()
        assert window.details.platform.bedrock_icon.isHidden()
        # Paper sin Bedrock automatico: no se afirma que solo entren jugadores
        # de Java, porque puede tener Geyser instalado a mano.
        details_java = window.details._labels["bedrock"].text()
        assert "solo se puede si usas el plugin" in details_java
        assert "solo entran jugadores de Java" not in details_java

        window.select_server(bedrock.id)
        assert not window.details.platform.bedrock_icon.isHidden()
        assert "UDP" in window.details._labels["bedrock"].text()


class TestIconosDeContenido:
    """Los mods y pluguins llevan su icono en la lista, como en Prism Launcher."""

    def _panel(self, qapp, store, config, spec):
        from serviscraft.ui.mods_panel import ModsPanel
        from serviscraft.ui.tasks import TaskRunner

        store.prepare_dirs(spec.id)
        store.save(spec)
        panel = ModsPanel(ServerManager(store=store, config=config), TaskRunner())
        panel.set_server(spec, running=False)
        return panel

    def test_cada_fila_lleva_su_icono(self, qapp, store, config) -> None:
        spec = make_spec(type=ServerType.PAPER, bedrock=True)
        panel = self._panel(qapp, store, config, spec)
        try:
            carpeta = store.data_dir(spec.id) / "plugins"
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "EssentialsX.jar").write_bytes(b"jar")
            (carpeta / "otro.jar.desactivado").write_bytes(b"jar")
            panel.refresh()

            assert panel.table.rowCount() == 2
            for fila in range(panel.table.rowCount()):
                assert not panel.table.item(fila, 0).icon().isNull()
            # El desactivado se ve distinto (apagado con una raya roja).
            activo = panel.table.item(0, 0).icon().pixmap(16).toImage()
            apagado = panel.table.item(1, 0).icon().pixmap(16).toImage()
            assert activo != apagado
        finally:
            panel.close()

    def test_el_proyecto_recordado_aporta_su_icono(self, qapp, store, config) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter, QPixmap

        from serviscraft.core import icons as iconos_remotos

        spec = make_spec(type=ServerType.PAPER)
        panel = self._panel(qapp, store, config, spec)
        try:
            carpeta = store.data_dir(spec.id) / "plugins"
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "Mapa.jar").write_bytes(b"jar")

            # Como si el icono se hubiera descargado al instalarlo del catalogo.
            url = "https://example.invalid/mapa.png"
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            pintor = QPainter(pixmap)
            pintor.setBrush(QColor("#cc2222"))
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.drawEllipse(1, 1, 30, 30)
            pintor.end()
            ruta = iconos_remotos.cached_path(url)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(ruta))
            panel.manager.mods_inventory(spec.id).remember_project(
                "Mapa.jar", slug="mapa", title="Mapa", icon=url
            )

            panel.refresh()
            assert panel.table.item(0, 0).text() == "Mapa.jar"
            imagen = panel.table.item(0, 0).icon().pixmap(16).toImage()
            assert imagen.pixelColor(8, 8).red() > 120
            assert "Mapa" in panel.table.item(0, 0).toolTip()
        finally:
            panel.close()

    def test_el_catalogo_ensena_el_icono_del_proyecto(self, qapp, store, config) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter, QPixmap

        from serviscraft.core import icons as iconos_remotos
        from serviscraft.core.modrinth import Project
        from serviscraft.ui.catalog_dialog import CatalogDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(type=ServerType.PAPER)
        store.prepare_dirs(spec.id)
        store.save(spec)
        dialog = CatalogDialog(
            ServerManager(store=store, config=config), TaskRunner(), spec, "plugins"
        )
        try:
            url = "https://example.invalid/plugin.png"
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            pintor = QPainter(pixmap)
            pintor.setBrush(QColor("#2277cc"))
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.drawEllipse(1, 1, 30, 30)
            pintor.end()
            ruta = iconos_remotos.cached_path(url)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(ruta))

            con_icono = Project(
                id="abc",
                slug="prueba",
                title="Con icono",
                description="Un proyecto",
                downloads=10,
                icon_url=url,
            )
            sin_icono = Project(
                id="def",
                slug="otro",
                title="Sin icono",
                description="Otro proyecto",
                downloads=5,
            )
            dialog._fill([con_icono, sin_icono])

            assert not dialog.table.item(0, 0).icon().isNull()
            imagen = dialog.table.item(0, 0).icon().pixmap(16).toImage()
            assert imagen.pixelColor(8, 8).blue() > 120
            # Sin icono conocido queda el simbolo del tipo de contenido.
            assert not dialog.table.item(1, 0).icon().isNull()
        finally:
            dialog.close()


class TestAspectoDelServidor:
    """Imagen y descripcion con las que se ve el servidor antes de entrar."""

    def _esperar_tarea(self, qapp: QApplication, condicion, intentos: int = 500) -> None:
        # ``processEvents`` solo no basta en un equipo lento: el hilo de la
        # tarea necesita tiempo real para arrancar. Con 500 x 10 ms damos hasta
        # cinco segundos, sin frenar las pruebas cuando termina antes.
        for _ in range(intentos):
            qapp.processEvents()
            if condicion():
                return
            time.sleep(0.01)
        qapp.processEvents()
        assert condicion(), "la tarea de fondo no termino a tiempo"

    def _icono(self) -> bytes:
        from serviscraft.ui.appearance_dialog import png_de_pixmap, presets_iconos

        return png_de_pixmap(presets_iconos()["java"])

    def test_el_dialogo_ensena_lo_que_ya_tiene_el_servidor(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.appearance_dialog import AppearanceDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)
        manager.save_motd(spec.id, "&aBienvenido")
        manager.save_icon(spec.id, self._icono())

        dialogo = AppearanceDialog(manager, TaskRunner(), spec, running=False)
        try:
            assert dialogo.motd_edit.toPlainText() == "§aBienvenido"
            assert dialogo.preview._motd == "§aBienvenido"
            assert not dialogo.icon_preview.pixmap().isNull()
            # Nada cambiado: guardar no tiene sentido todavia.
            assert not dialogo.save_button.isEnabled()
            assert len(dialogo.color_buttons) == 16
            assert len(dialogo.format_buttons) == 6
        finally:
            dialogo.close()

    def test_la_descripcion_demasiado_larga_no_se_puede_guardar(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.core import appearance
        from serviscraft.ui.appearance_dialog import AppearanceDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        dialogo = AppearanceDialog(ServerManager(store=store, config=config), TaskRunner(), spec)
        try:
            dialogo.motd_edit.setPlainText("x" * (appearance.MAX_LINE_LENGTH + 5))
            assert not dialogo.save_button.isEnabled()
            assert f"{appearance.MAX_LINE_LENGTH + 5}/" in dialogo.counter.text()
            assert "maximo" in dialogo.counter.text()
        finally:
            dialogo.close()

    def test_solo_caben_dos_lineas(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.appearance_dialog import AppearanceDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        dialogo = AppearanceDialog(ServerManager(store=store, config=config), TaskRunner(), spec)
        try:
            dialogo.motd_edit.setPlainText("Una\nDos\nTres")
            assert dialogo.motd_edit.toPlainText() == "Una\nDos"
            assert dialogo.save_button.isEnabled()
        finally:
            dialogo.close()

    def test_los_colores_se_insertan_donde_esta_el_cursor(
        self, qapp: QApplication, store: ServerStore, config: AppConfig
    ) -> None:
        from serviscraft.ui.appearance_dialog import AppearanceDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        dialogo = AppearanceDialog(ServerManager(store=store, config=config), TaskRunner(), spec)
        try:
            dialogo.motd_edit.setPlainText("Hola")
            cursor = dialogo.motd_edit.textCursor()
            cursor.setPosition(2)
            dialogo.motd_edit.setTextCursor(cursor)
            dialogo._insertar_codigo("a")
            assert dialogo.motd_edit.toPlainText() == "Ho§ala"
            # Y la vista previa pinta el texto limpio con su color.
            assert dialogo.preview._motd == "Ho§ala"
        finally:
            dialogo.close()

    def test_guardar_escribe_la_imagen_y_la_descripcion(
        self,
        qapp: QApplication,
        store: ServerStore,
        config: AppConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from serviscraft.ui import appearance_dialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        manager = ServerManager(store=store, config=config)
        monkeypatch.setattr(appearance_dialog, "show_info", lambda *a, **k: None)
        monkeypatch.setattr(appearance_dialog, "show_error", lambda *a, **k: None)

        # La referencia al lanzador de tareas se conserva: si se recoge antes de
        # que termine el hilo, Qt se cae al cerrar la ventana.
        runner = TaskRunner()
        dialogo = appearance_dialog.AppearanceDialog(
            manager, runner, spec, running=False
        )
        try:
            dialogo.motd_edit.setPlainText("&bNuevo aspecto")
            dialogo._usar_preset("java")
            assert dialogo.save_button.isEnabled()
            guardado: list[bool] = []
            dialogo.saved.connect(lambda: guardado.append(True))
            dialogo._guardar()
            # La senal se emite cuando la tarea de fondo ha terminado del todo.
            self._esperar_tarea(qapp, lambda: guardado == [True])
            assert manager.motd(spec.id) == "§bNuevo aspecto"
            assert manager.server_icon(spec.id) == self._icono()
            # Al guardar ya no hay cambios pendientes.
            assert not dialogo.save_button.isEnabled()
        finally:
            runner.wait_for_done(3000)
            dialogo.close()

    def test_el_panel_de_detalles_muestra_la_entrada_de_la_lista(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window.manager.save_motd(spec.id, "&aBienvenido\n&eDiversion")
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.tabs.setCurrentIndex(_indice_pestana(window, "Detalles"))
        _esperar(window, qapp, lambda: window.details.mc_preview._motd == "§aBienvenido\n§eDiversion")
        assert window.details.mc_preview._name == spec.name
        assert "asi lo ven" in window.details.appearance_note.text().lower()

        # Se suelta el manejador de la ventana (abre un dialogo modal) para
        # comprobar solo que el boton pide el editor del servidor correcto.
        window.details.appearance_requested.disconnect()
        pedidos: list[str] = []
        window.details.appearance_requested.connect(pedidos.append)
        window.details.appearance_button.click()
        assert pedidos == [spec.id]

    def test_el_icono_se_ve_en_la_lista_y_en_la_cabecera(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window.resize(1180, 820)
        window._on_views_ready(
            [ServerView(spec=spec, state=ServerState.RUNNING, icon=self._icono())]
        )
        for _ in range(10):
            qapp.processEvents()
        assert not window.header_icon.pixmap().isNull()
        tarjeta = window.sidebar._cards[spec.id]
        # ``isHidden`` y no ``isVisible``: la tarjeta puede estar en una ventana
        # que la prueba no llega a mostrar.
        assert not tarjeta.icon.isHidden()
        assert not tarjeta.icon.pixmap().isNull()

    def test_sin_icono_la_cabecera_muestra_el_marco_generico(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        spec = make_spec()
        store.prepare_dirs(spec.id)
        store.save(spec)
        window.resize(1180, 820)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        for _ in range(10):
            qapp.processEvents()
        assert not window.header_icon.pixmap().isNull()


class TestDialogoNombre:
    """El dialogo de DuckDNS: cabe, valida y consulta sin congelar la ventana."""

    def _dialogo(
        self,
        qapp: QApplication,
        store: ServerStore,
        config: AppConfig,
        *,
        public_ip: str = "",
        **overrides,
    ):
        from serviscraft.ui.ddns_dialog import DdnsDialog
        from serviscraft.ui.tasks import TaskRunner

        spec = make_spec(**overrides)
        store.prepare_dirs(spec.id)
        store.save(spec)
        runner = TaskRunner()
        dialogo = DdnsDialog(
            ServerManager(store=store, config=config),
            runner,
            spec,
            public_ip=public_ip,
        )
        return dialogo, runner, spec

    @staticmethod
    def _cerrar(dialogo, runner, qapp: QApplication) -> None:
        dialogo.close()
        runner.wait_for_done(4000)
        qapp.processEvents()

    @staticmethod
    def _comprobar_encaje(dialogo, qapp: QApplication) -> None:
        from PySide6.QtWidgets import QPushButton

        for _ in range(10):
            qapp.processEvents()
        assert dialogo.width() >= 560
        for boton in dialogo.findChildren(QPushButton):
            if not boton.isVisible():
                continue
            esquina = boton.mapTo(dialogo, boton.rect().bottomRight())
            assert esquina.x() <= dialogo.width(), f"«{boton.text()}» se sale por la derecha"
            assert esquina.y() <= dialogo.height(), f"«{boton.text()}» se sale por abajo"

    def test_los_botones_y_la_direccion_caben_en_la_ventana(
        self, qapp: QApplication, store, config
    ) -> None:
        dialogo, runner, _spec = self._dialogo(qapp, store, config)
        try:
            dialogo.show()
            self._comprobar_encaje(dialogo, qapp)
            # La vista previa tiene alto de sobra: antes se pintaba a 18 px y el
            # texto aparecia cortado por la mitad.
            assert dialogo.preview.height() >= dialogo.preview.fontMetrics().height() + 10

            # En el ancho minimo los botones se envuelven, pero siguen enteros.
            dialogo.resize(560, dialogo.minimumSizeHint().height())
            self._comprobar_encaje(dialogo, qapp)
        finally:
            self._cerrar(dialogo, runner, qapp)

    def test_el_formulario_avisa_de_un_nombre_o_token_invalidos(
        self, qapp: QApplication, store, config
    ) -> None:
        dialogo, runner, spec = self._dialogo(qapp, store, config)
        try:
            dialogo.show()
            qapp.processEvents()

            dialogo.subdomain_input.setText("Reino Trebol")
            qapp.processEvents()
            assert dialogo.name_error.isVisible()
            assert "letras" in dialogo.name_error.text()
            assert not dialogo.save_button.isEnabled()
            assert dialogo.preview.text() == ""

            dialogo.subdomain_input.setText("ReinoTrebol")
            dialogo.token_input.setText("1234")
            qapp.processEvents()
            assert dialogo.token_error.isVisible()
            assert not dialogo.save_button.isEnabled()

            dialogo.token_input.setText("12345678-abcd-1234-abcd-123456789012")
            qapp.processEvents()
            assert not dialogo.name_error.isVisible()
            assert not dialogo.token_error.isVisible()
            assert dialogo.save_button.isEnabled()
            assert dialogo.preview.text() == f"reinotrebol.duckdns.org:{spec.port}"
        finally:
            self._cerrar(dialogo, runner, qapp)

    def test_guardar_aplica_el_nombre_y_avisa_a_duckdns(
        self, qapp: QApplication, store, config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from serviscraft.core import ddns

        monkeypatch.setattr(ddns, "update", lambda *a, **k: "OK")
        monkeypatch.setattr(ddns, "resolve", lambda *a, **k: {"83.54.12.7"})
        dialogo, runner, spec = self._dialogo(
            qapp, store, config, public_ip="83.54.12.7"
        )
        try:
            dialogo.show()
            dialogo.subdomain_input.setText("reinotrebol")
            dialogo.token_input.setText("12345678-abcd-1234-abcd-123456789012")
            qapp.processEvents()
            dialogo.save_button.click()
            for _ in range(200):
                qapp.processEvents()
                if dialogo.state_chip.text() == "Guardado":
                    break
                runner.wait_for_done(20)
            assert dialogo.state_chip.text() == "Guardado"
            guardado = store.load(spec.id)
            assert guardado.ddns_subdomain == "reinotrebol"
            assert guardado.ddns_configured
        finally:
            self._cerrar(dialogo, runner, qapp)

    def test_la_comprobacion_de_dns_no_bloquea_la_ventana(
        self, qapp: QApplication, store, config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from serviscraft.core.ddns import DdnsStatus
        from serviscraft.ui import ddns_dialog as modulo

        empezo = threading.Event()
        liberar = threading.Event()

        def check_lento(subdominio, *, public_ip="", puerto=None):
            empezo.set()
            liberar.wait(4)
            return DdnsStatus(
                subdomain=subdominio,
                hostname=f"{subdominio}.duckdns.org",
                state="ok",
                detail="Listo: el nombre apunta a este equipo.",
                public_ip=public_ip,
            )

        monkeypatch.setattr(modulo.ddns, "check", check_lento)
        dialogo, runner, _spec = self._dialogo(
            qapp,
            store,
            config,
            public_ip="83.54.12.7",
            ddns_subdomain="reinotrebol",
            ddns_token="token-de-prueba",
        )
        try:
            # La consulta corre en segundo plano: el constructor ya devolvio y la
            # ventana se puede mostrar mientras el DNS sigue esperando.
            assert empezo.wait(2), "la comprobacion no llego a empezar"
            dialogo.show()
            assert dialogo.state_chip.text() == "Comprobando..."

            liberar.set()
            for _ in range(200):
                qapp.processEvents()
                if dialogo.state_chip.text() == "Funcionando":
                    break
                runner.wait_for_done(20)
            assert dialogo.state_chip.text() == "Funcionando"
        finally:
            liberar.set()
            self._cerrar(dialogo, runner, qapp)
