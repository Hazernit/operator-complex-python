"""Prepare validated recording players in Qt's thread pool, without UI changes.

``loader.start(path, platform_id)`` returns a request ID immediately. Results are
delivered to the loader's owning thread through ``success`` / ``failure``. The
caller decides whether a result still belongs to the selected platform and may
discard an older request; loading itself never changes an active player, map,
simulation, or command state.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot

from .playback import RecordingPlayer
from .sensor_data import load_recording


class _LoadSignals(QObject):
    success = Signal(int, str, object)
    failure = Signal(int, str, str)
    finished = Signal(int)


class _RecordingLoadTask(QRunnable):
    def __init__(self, request_id: int, platform_id: str, path: Path):
        super().__init__()
        self.request_id = request_id
        self.platform_id = platform_id
        self.path = path
        # No QObject parent: closing a window must not destroy these signals
        # while the runnable is still parsing. Both the runnable and the loader
        # retain them until completion; no QWidget is accessed in run().
        self.signals = _LoadSignals()

    @Slot()
    def run(self):
        try:
            player = RecordingPlayer(load_recording(self.path))
        except Exception as error:
            self.signals.failure.emit(
                self.request_id, self.platform_id, str(error) or type(error).__name__,
            )
        else:
            self.signals.success.emit(self.request_id, self.platform_id, player)
        finally:
            self.signals.finished.emit(self.request_id)


class RecordingLoader(QObject):
    """Asynchronous read-only preparation of recording players.

    Create and call this object on the GUI thread. All public result signals
    are emitted on that same thread, even though file parsing and player bounds
    calculation run in the pool. Multiple requests are independent and may
    finish in a different order. Request IDs increase for this loader instance.

    An optional ``pool`` supports isolated tests or application-specific limits;
    otherwise Qt's shared global pool is used. No blocking wait runs here.
    """

    success = Signal(int, str, object)
    failure = Signal(int, str, str)

    def __init__(self, parent=None, *, pool: QThreadPool | None = None):
        super().__init__(parent)
        self._pool = pool if pool is not None else QThreadPool.globalInstance()
        self._next_request_id = 0
        self._jobs: dict[int, _RecordingLoadTask] = {}

    @property
    def is_loading(self) -> bool:
        return bool(self._jobs)

    @property
    def pending_request_ids(self) -> tuple[int, ...]:
        return tuple(self._jobs)

    def start(self, path: str | Path, platform_id: str) -> int:
        self._next_request_id += 1
        request_id = self._next_request_id
        task = _RecordingLoadTask(request_id, str(platform_id), Path(path))
        task.signals.success.connect(self._success, Qt.ConnectionType.QueuedConnection)
        task.signals.failure.connect(self._failure, Qt.ConnectionType.QueuedConnection)
        task.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        # QThreadPool auto-deletes the runnable's C++ object. Keeping its Python
        # wrapper here also keeps the separate signals object alive until the
        # queued finished callback has been processed on the owning thread.
        self._jobs[request_id] = task
        self._pool.start(task)
        return request_id

    @Slot(int, str, object)
    def _success(self, request_id, platform_id, player):
        self.success.emit(request_id, platform_id, player)

    @Slot(int, str, str)
    def _failure(self, request_id, platform_id, message):
        self.failure.emit(request_id, platform_id, message)

    @Slot(int)
    def _finished(self, request_id):
        task = self._jobs.pop(request_id, None)
        if task is not None:
            task.signals.deleteLater()
