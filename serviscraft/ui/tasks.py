"""Ejecucion de tareas en segundo plano para no bloquear la interfaz.

Todas las llamadas a Podman, las descargas y las copias de seguridad se hacen
fuera del hilo de la interfaz mediante ``QThreadPool``.
"""

from __future__ import annotations

import traceback
import weakref
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ..core.errors import ServiscraftError
from ..core.logging_setup import get_logger

logger = get_logger("ui.tasks")


class TaskContext:
    """Permite a la tarea informar del progreso y saber si se ha cancelado."""

    def __init__(self) -> None:
        self._cancelled = False
        self._progress: Callable[[str], None] | None = None
        self._progress_value: Callable[[int, int], None] | None = None

    def bind(self, callback: Callable[[str], None]) -> None:
        self._progress = callback

    def bind_value(self, callback: Callable[[int, int], None]) -> None:
        self._progress_value = callback

    def progress(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)

    def progress_step(self, done: int, total: int, message: str = "") -> None:
        """Informa de progreso medible (por ejemplo, bytes copiados de una copia)."""
        if message:
            self.progress(message)
        if self._progress_value is not None:
            self._progress_value(int(done), int(total))

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


def anunciar(senal, *args: Any) -> bool:
    """Emite una senal sin reventar si su objeto ya no existe.

    Al cerrar la ventana (o la aplicacion) puede quedar una tarea terminando.
    Si el objeto de senales se ha destruido, ``emit`` lanzaria ``RuntimeError``
    en el hilo de la tarea, que PySide imprime como error grave. El aviso ya no
    le importa a nadie: se descarta y se anota en el registro.
    """
    try:
        senal.emit(*args)
    except RuntimeError:  # pragma: no cover - solo al cerrar con tareas a medias
        logger.debug("Se descarta un aviso de una tarea: su ventana ya no existe.")
        return False
    return True


class TaskSignals(QObject):
    """Senales de una tarea (los ``QRunnable`` no pueden emitir por si mismos)."""

    progress = Signal(str)
    progress_value = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str, str)


class Task(QRunnable):
    """Envuelve una funcion para ejecutarla en un hilo del pool."""

    def __init__(self, description: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.description = description
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.context = TaskContext()
        # El ``Task`` y sus senales son de Python: los libera ``_complete`` cuando
        # ya no se va a usar la tarea. Con ``autoDelete`` el grupo de hilos
        # borraba el objeto por su cuenta y una tarea que terminaba al cerrar la
        # ventana se encontraba sus senales muertas.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:  # pragma: no cover - requiere bucle de eventos
        try:
            result = self.fn(*self.args, context=self.context, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - se informa a la interfaz
            message, details = describe_error(exc)
            logger.error("Tarea '%s' fallida: %s", self.description, message)
            logger.debug("Detalle:\n%s", details)
            anunciar(self.signals.failed, message, details)
        else:
            anunciar(self.signals.finished, result)

    def cancel(self) -> None:
        self.context.cancel()


def describe_error(exc: BaseException) -> tuple[str, str]:
    """Convierte una excepcion en (mensaje para el usuario, detalle tecnico)."""
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if isinstance(exc, ServiscraftError):
        return str(exc) or exc.__class__.__name__, details
    if isinstance(exc, PermissionError):
        return (
            "Permiso denegado. Comprueba que Podman funciona en modo rootless "
            "y que tus ficheros te pertenecen.",
            details,
        )
    if isinstance(exc, FileNotFoundError):
        return f"No se encontro un fichero necesario: {exc.filename or exc}", details
    return f"{exc.__class__.__name__}: {exc}", details


class TaskRunner(QObject):
    """Cola de tareas con seguimiento del numero de trabajos activos."""

    busy_changed = Signal(bool)
    task_started = Signal(str)
    #: Solo para las tareas que marcan la aplicacion como ocupada (las
    #: operaciones que el usuario ha pedido): los refrescos de fondo no deben
    #: dejar la barra de operacion encendida.
    tracked_started = Signal(str)
    task_progress = Signal(str)
    task_finished = Signal(str)

    def __init__(self, parent: QObject | None = None, *, max_threads: int = 8) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)
        self._active: list[Task] = []
        self._count = 0
        # Solo las tareas "seguidas" (``track_busy=True``) marcan la aplicacion
        # como ocupada. Las tareas informativas en segundo plano (estadisticas,
        # refrescos, uso de disco) no deben desactivar los botones.
        self._tracked = 0

    # ------------------------------------------------------------------ estado
    @property
    def busy(self) -> bool:
        return self._tracked > 0

    # -------------------------------------------------------------- ejecucion
    def submit(
        self,
        description: str,
        fn: Callable[..., Any],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        on_finished: Callable[[Any], None] | None = None,
        on_failed: Callable[[str, str], None] | None = None,
        on_progress: Callable[[str], None] | None = None,
        on_progress_value: Callable[[int, int], None] | None = None,
        track_busy: bool = True,
    ) -> Task:
        """Lanza ``fn`` en segundo plano y conecta las senales indicadas."""
        task = Task(description, fn, *args, **(kwargs or {}))
        task.tracked = track_busy
        task.context.bind(lambda message: anunciar(task.signals.progress, message))
        task.context.bind_value(
            lambda done, total: anunciar(task.signals.progress_value, done, total)
        )

        if on_progress is not None:
            task.signals.progress.connect(on_progress)
        if on_progress_value is not None:
            task.signals.progress_value.connect(on_progress_value)
        if on_finished is not None:
            task.signals.finished.connect(on_finished)
        if on_failed is not None:
            task.signals.failed.connect(on_failed)

        task.signals.progress.connect(self.task_progress)
        # Referencia debil: si la conexion guardara la tarea, tarea y senales se
        # referenciarian entre si a traves de la lambda y ninguna se liberaria.
        tarea_ref = weakref.ref(task)
        task.signals.finished.connect(
            lambda _r, ref=tarea_ref, d=description: self._complete(ref(), d)
        )
        task.signals.failed.connect(
            lambda _m, _d, ref=tarea_ref, d=description: self._complete(ref(), d, failed=True)
        )

        self._active.append(task)
        self._count += 1
        if track_busy:
            self._tracked += 1
            anunciar(self.busy_changed, True)
            anunciar(self.tracked_started, description)
        anunciar(self.task_started, description)
        logger.debug("Tarea lanzada: %s", description)
        self._pool.start(task)
        return task

    def _complete(self, task: Task | None, description: str, *, failed: bool = False) -> None:
        if task is None:  # la tarea ya se libero: no hay nada que anotar
            return
        if task in self._active:
            self._active.remove(task)
        self._count = max(0, self._count - 1)
        anunciar(self.task_finished, description)
        if getattr(task, "tracked", True):
            self._tracked = max(0, self._tracked - 1)
            if self._tracked == 0:
                anunciar(self.busy_changed, False)
        logger.debug("Tarea finalizada (%s): %s", "con error" if failed else "correcta", description)

    def cancel_all(self) -> None:
        for task in list(self._active):
            task.cancel()

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Cancela lo que quede y espera a que las tareas terminen.

        Se llama al cerrar: asi ninguna tarea sigue viva cuando desaparece la
        ventana (y con ella este objeto y su grupo de hilos).
        """
        self.cancel_all()
        terminado = self._pool.waitForDone(timeout_ms)
        if not terminado:
            logger.warning("Quedan %d tarea(s) en marcha al cerrar", self._count)
        return terminado

    @property
    def pending(self) -> int:
        """Tareas lanzadas que todavia no han avisado de que terminaron."""
        return self._count

    def wait_for_done(self, timeout_ms: int = 5000) -> bool:
        """Espera a que terminen las tareas (usado al cerrar la aplicacion)."""
        return self._pool.waitForDone(timeout_ms)
