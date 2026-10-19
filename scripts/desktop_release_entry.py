"""Entry point shared by packaged technical and new-interface betas.

This module is build tooling, not part of the existing source archive. The
frozen program uses local demo data and must never control physical robots.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


def resources_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def verify_bundle() -> None:
    from operator_stub.sensor_data import load_recording

    root = resources_root()
    config = root / "config" / "demo_platforms.json"
    with config.open(encoding="utf-8") as stream:
        platforms = json.load(stream).get("platforms")
    if not platforms:
        raise ValueError(f"Missing demo platforms: {config}")
    for name in ("lidar-room.txt", "sonar-route.txt", "mixed-route.txt"):
        path = root / "examples" / name
        recording = load_recording(path)
        if not recording.frames:
            raise ValueError(f"Empty or missing demonstration recording: {path}")
    print("Bundled examples and demo config verified.", flush=True)


def log_directory() -> Path:
    track = os.environ.get("OPERATOR_EDITION", "OperatorComplex")
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / track / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / track
    return Path.home() / ".local" / "state" / track


def main() -> int:
    directory = log_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stream = (directory / "application.log").open("a", encoding="utf-8", buffering=1)
    except OSError:
        directory = Path(tempfile.mkdtemp(prefix="OperatorComplex-logs-"))
        stream = (directory / "application.log").open("a", encoding="utf-8", buffering=1)

    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    try:
        args = sys.argv[1:]
        if "--verify-bundle" in args:
            verify_bundle()
            return 0
        if "--smoke-test" in args:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            verify_bundle()
        from operator_stub.__main__ import main as run_operator

        return int(run_operator())
    except BaseException:
        details = traceback.format_exc()
        stream.write(details)
        if sys.stderr is not stream:
            sys.stderr.write(details)
        return 1
    finally:
        stream.flush()
        stream.close()


if __name__ == "__main__":
    raise SystemExit(main())