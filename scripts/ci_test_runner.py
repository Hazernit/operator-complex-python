"""Run the complete test suite and fail CI on silent Qt test skips.

The previous workflow reported success despite 76 GUI tests being skipped after
an ImportError. This runner makes Qt import errors visible and skips fatal.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test*.py", help="unittest discovery filename pattern")
    parser.add_argument("--repeat", type=positive_integer, default=1, help="number of suite repetitions")
    args = parser.parse_args(argv)

    if not check_qt_available():
        return 2

    totals = dict(discovered=0, passed=0, skipped=0, failures=0, errors=0)
    started = time.monotonic()
    exit_code = 0
    for repetition in range(1, args.repeat + 1):
        print(f"CI repetition {repetition}/{args.repeat}: pattern={args.pattern}", flush=True)
        repetition_started = time.monotonic()
        # unittest consumes suites as they run. Discover fresh test instances
        # each time, retaining the Qt application to exercise task cleanup too.
        suite = unittest.defaultTestLoader.discover("tests", pattern=args.pattern)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        counts = dict(
            discovered=result.testsRun,
            passed=result.testsRun - len(result.skipped) - len(result.failures) - len(result.errors),
            skipped=len(result.skipped),
            failures=len(result.failures),
            errors=len(result.errors),
        )
        for key, count in counts.items():
            totals[key] += count
        print(
            f"CI repetition {repetition}/{args.repeat} result: "
            + " ".join(f"{key}={count}" for key, count in counts.items())
            + f" elapsed={time.monotonic() - repetition_started:.3f}s",
            flush=True,
        )
        if not result.testsRun:
            print("ERROR: test discovery found zero tests", file=sys.stderr)
            exit_code = 1
        if result.skipped:
            print("ERROR: unexpected unittest skips are not allowed in CI:", file=sys.stderr)
            for case, reason in result.skipped:
                print(f"  - {case.id()}: {reason}", file=sys.stderr)
            exit_code = 1
        if not result.wasSuccessful():
            exit_code = 1
        if exit_code:
            break

    print(
        "CI result: " + " ".join(f"{key}={count}" for key, count in totals.items())
        + f" repetitions={repetition}/{args.repeat} elapsed={time.monotonic() - started:.3f}s",
        flush=True,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
