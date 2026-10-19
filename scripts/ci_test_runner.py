"""Run the complete test suite and fail CI on silent Qt test skips.

The previous workflow reported success despite 76 GUI tests being skipped after
an ImportError. This runner makes Qt import errors visible and skips fatal.
"""

from __future__ import annotations

import sys
import traceback
import unittest


def check_qt_available() -> bool:
    try:
        import PySide6
        from PySide6.QtCore import QCoreApplication  # noqa: F401
        from PySide6.QtGui import QPainter  # noqa: F401
        from PySide6.QtTest import QTest  # noqa: F401
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from operator_stub.ui import OperatorWindow  # noqa: F401
    except Exception:
        print("ERROR: PySide6 GUI prerequisites are not importable; GUI tests would be skipped.", file=sys.stderr)
        traceback.print_exc()
        return False

    print(f"Qt import preflight passed: PySide6 {PySide6.__version__}", flush=True)
    return True


def main() -> int:
    if not check_qt_available():
        return 2

    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.testsRun - len(result.skipped) - len(result.failures) - len(result.errors)
    print(
        f"CI result: discovered={result.testsRun} passed={passed} "
        f"skipped={len(result.skipped)} failures={len(result.failures)} errors={len(result.errors)}",
        flush=True,
    )
    if not result.testsRun:
        print("ERROR: test discovery found zero tests", file=sys.stderr)
        return 1
    if result.skipped:
        print("ERROR: unexpected unittest skips are not allowed in CI:", file=sys.stderr)
        for case, reason in result.skipped:
            print(f"  - {case.id()}: {reason}", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())