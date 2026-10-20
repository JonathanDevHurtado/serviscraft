"""Pruebas de las tareas en segundo plano.

Aquí se comprueba el ciclo de vida de ``TaskRunner`` sin Podman: que las
señales lleguen, que un fallo se informe con detalle y, sobre todo, que al
cerrar no queden tareas avisando a objetos ya destruidos (eso imprimía
``RuntimeError: Signal source has been deleted`` en las pruebas).
"""

from __future__ import annotations

import time

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

from serviscraft.ui.tasks import Task, TaskRunner, TaskSignals, anunciar


def _atender(qapp: QApplication, condicion, intentos: int = 300) -> bool:
    """Deja que el bucle de eventos entregue las señales de las tareas."""
    for _ in range(intentos):
        qapp.processEvents()
        if condicion():
            return True
        time.sleep(0.005)
    qapp.processEvents()
    return bool(condicion())


def test_el_progreso_y_el_final_llegan_a_la_interfaz(qapp: QApplication) -> None:
    runner = TaskRunner()
    mensajes: list[str] = []
    resultados: list[object] = []
    pasos: list[tuple[int, int]] = []

    def trabajo(*, context):
        context.progress("a medias")
        context.progress_step(5, 10)
        return "hecho"

    runner.submit(
        "prueba",
        trabajo,
        on_progress=mensajes.append,
        on_progress_value=lambda hecho, total: pasos.append((hecho, total)),
        on_finished=resultados.append,
    )

    assert _atender(qapp, lambda: bool(resultados))
    assert mensajes == ["a medias"]
    assert pasos == [(5, 10)]
    assert resultados == ["hecho"]
    assert runner.pending == 0


def test_un_fallo_se_informa_con_mensaje_y_detalle(qapp: QApplication) -> None:
    runner = TaskRunner()
    fallos: list[tuple[str, str]] = []

    def revienta(*, context):
        raise ValueError("algo salio mal")

    runner.submit("falla", revienta, on_failed=lambda m, d: fallos.append((m, d)), track_busy=False)

    assert _atender(qapp, lambda: bool(fallos))
    mensaje, detalle = fallos[0]
    assert "algo salio mal" in mensaje
    assert "ValueError" in detalle
    assert runner.pending == 0


def test_anunciar_descarta_el_aviso_si_la_ventana_ya_no_existe() -> None:
    """Emitir sobre un objeto destruido no debe lanzar una excepción."""
    senales = TaskSignals()
    recibido: list[str] = []
    senales.progress.connect(recibido.append)
    senal = senales.progress

    assert anunciar(senal, "hola") is True
    assert recibido == ["hola"]

    # Como si la ventana se hubiera cerrado con la tarea en marcha.
    shiboken6.delete(senales)
    assert anunciar(senal, "tarde") is False


def test_apagar_el_runner_espera_a_las_tareas(qapp: QApplication) -> None:
    runner = TaskRunner()
    pasos: list[str] = []

    def lenta(*, context):
        pasos.append("empieza")
        return "ok"

    runner.submit(
        "lenta",
        lenta,
        on_finished=lambda _r: pasos.append("avisada"),
        track_busy=False,
    )

    assert runner.shutdown(5000) is True
    # La tarea terminó de verdad antes de apagar (no se abandonó a medias).
    assert pasos[0] == "empieza"
    assert _atender(qapp, lambda: not runner.pending)
    assert runner.pending == 0


def test_shutdown_no_deja_tareas_colgadas_ni_marca_ocupado(qapp: QApplication) -> None:
    runner = TaskRunner()
    for _ in range(4):
        runner.submit("refresco", lambda *, context: None, track_busy=False)

    assert runner.shutdown(5000) is True
    assert _atender(qapp, lambda: not runner.pending)
    assert runner.pending == 0
    assert runner.busy is False


def test_submit_devuelve_la_tarea_y_admite_argumentos(qapp: QApplication) -> None:
    runner = TaskRunner()
    resultados: list[object] = []
    tarea = runner.submit(
        "suma",
        lambda a, b=0, *, context: a + b,
        args=(2,),
        kwargs={"b": 40},
        on_finished=resultados.append,
        track_busy=False,
    )

    assert isinstance(tarea, Task)
    # ``args`` y ``kwargs`` se combinan como en cualquier llamada normal.
    assert _atender(qapp, lambda: bool(resultados))
    assert resultados == [42]


def test_una_sola_tarea_fallida_no_deja_la_aplicacion_ocupada(qapp: QApplication) -> None:
    runner = TaskRunner()
    terminadas: list[str] = []
    runner.task_finished.connect(terminadas.append)

    runner.submit("falla", lambda *, context: (_ for _ in ()).throw(RuntimeError("x")))
    assert runner.busy is True

    assert _atender(qapp, lambda: bool(terminadas))
    assert runner.busy is False
    assert terminadas == ["falla"]


@pytest.mark.parametrize("track_busy", [True, False])
def test_el_seguimiento_de_ocupado_respeta_track_busy(
    qapp: QApplication, track_busy: bool
) -> None:
    runner = TaskRunner()
    terminadas: list[str] = []
    runner.task_finished.connect(terminadas.append)

    runner.submit("x", lambda *, context: None, track_busy=track_busy)
    if track_busy:
        assert runner.busy is True
    assert _atender(qapp, lambda: bool(terminadas))
    assert runner.busy is False
