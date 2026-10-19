"""Bounded Qt event-loop waits for tests with Python background workers."""

from PySide6.QtCore import QEventLoop, QTimer, Qt


def wait_until(predicate, timeout=10):
    """Dispatch GUI events and release the GIL until predicate or timeout.

    PySide6 6.12's QTest.qWait holds the GIL while sleeping in C++. Short qWait
    calls can starve a Python QRunnable on Linux. exec() runs the same kind
    of native event loop as the application, allowing workers to make progress.
    """
    if predicate():
        return True

    loop = QEventLoop()
    error = None

    def check():
        nonlocal error
        try:
            ready = predicate()
        except BaseException as caught:
            # PySide prints and swallows exceptions escaping a Qt callback.
            # Transfer them back to unittest's Python call stack instead.
            error = caught
            loop.quit()
        else:
            if ready:
                loop.quit()

    poll = QTimer()
    poll.setInterval(1)
    poll.timeout.connect(check)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.setTimerType(Qt.TimerType.PreciseTimer)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(round(timeout * 1000))
    try:
        loop.exec()
    finally:
        poll.stop()
        deadline.stop()
    if error is not None:
        raise error
    return predicate()
