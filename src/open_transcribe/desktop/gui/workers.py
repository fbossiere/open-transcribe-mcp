"""Running blocking work off the user interface thread.

Network calls, keyring operations, filesystem writes, subprocesses, and client registration all
run here. The window stays responsive, progress is named, and Cancel is answered rather than
promised: a task that has already caused a side effect reports that instead of pretending not to.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


@dataclass(frozen=True, slots=True)
class TaskFailure:
    """A failure reduced to something showable: a message and a recovery action."""

    message: str
    recovery: str | None = None
    code: str | None = None


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(object)


class Task[T](QRunnable):
    """One unit of blocking work. Its result reaches the window through a queued signal."""

    def __init__(self, work: Callable[[], T]) -> None:
        super().__init__()
        self._work = work
        self.signals = _Signals()
        self._cancelled = False

    def cancel(self) -> None:
        """Ask for a bounded stop. Work already sent to a provider is not recalled by this."""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @Slot()
    def run(self) -> None:
        try:
            result = self._work()
        except Exception as exc:
            self.signals.failed.emit(describe(exc))
            return
        if self._cancelled:
            return
        self.signals.finished.emit(result)


def describe(exc: BaseException) -> TaskFailure:
    """Normalize any failure into user-facing text, never a traceback or a provider's own words."""
    from open_transcribe.desktop.errors import DesktopError
    from open_transcribe.domain.errors import OpenTranscribeError

    if isinstance(exc, DesktopError):
        return TaskFailure(exc.message, exc.recovery, exc.code.value)
    if isinstance(exc, OpenTranscribeError):
        return TaskFailure(exc.response.message, None, exc.response.code.value)
    return TaskFailure("Something went wrong.", None, "INTERNAL_ERROR")


def run_async(
    work: Callable[[], Any],
    on_success: Callable[[Any], None],
    on_failure: Callable[[TaskFailure], None],
) -> Task[Any]:
    task: Task[Any] = Task(work)
    task.signals.finished.connect(on_success)
    task.signals.failed.connect(on_failure)
    QThreadPool.globalInstance().start(task)
    return task
