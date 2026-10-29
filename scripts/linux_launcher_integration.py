"""Exercise a clean Linux source launch and offline reuse from an unrelated cwd.

CI checks out the project into a path containing spaces. This script deliberately
uses the real bootstrap, real pip/venv, and real PySide6 UI; no stubs or skips.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> str:
    command = ["sh", str(ROOT / "run-linux.sh"), *arguments]
    result = subprocess.run(
        command, cwd=cwd, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
    )
    print(result.stdout, flush=True)
    if result.returncode:
        raise RuntimeError(f"Linux launcher returned {result.returncode}: {command!r}")
    return result.stdout


def main() -> int:
    if sys.platform != "linux":
        raise RuntimeError("This integration check must run on Linux")
    environment_path = ROOT / ".venv"
    if environment_path.exists():
        raise RuntimeError("Fresh-environment check requires a checkout without .venv")
    environment = dict(os.environ, OPERATOR_PYTHON=sys.executable)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM", "VIRTUAL_ENV"):
        environment.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="operator unrelated cwd ") as directory:
        cwd = Path(directory)
        run(["--setup-only"], cwd, environment)
        executable = environment_path / "bin" / "python"
        configuration = environment_path / "pyvenv.cfg"
        if not executable.is_file() or not configuration.is_file():
            raise AssertionError("bootstrap did not create the project-local .venv")
        before = (configuration.read_bytes(), configuration.stat().st_mtime_ns,
                  executable.stat().st_ino, executable.stat().st_mtime_ns)
        marker = environment_path / "launcher-ci-reuse-marker.txt"
        marker.write_text("preserve existing environment", encoding="utf-8")
        # A warm source launch must succeed even with package indexes disabled.
        offline = dict(environment, PIP_NO_INDEX="1")
        run(["--setup-only"], cwd, offline)
        smoke_output = run(["--smoke-test"], cwd, offline)
        if "UI smoke test passed:" not in smoke_output:
            raise AssertionError("The real application GUI smoke did not report success")
        after = (configuration.read_bytes(), configuration.stat().st_mtime_ns,
                 executable.stat().st_ino, executable.stat().st_mtime_ns)
        if before != after or marker.read_text(encoding="utf-8") != "preserve existing environment":
            raise AssertionError("A warm launch recreated or modified the virtual environment")
        if (cwd / ".venv").exists():
            raise AssertionError("The launcher created .venv in the caller's directory")
        marker.unlink()
    print("Linux integration passed: fresh setup, offline .venv reuse, unrelated cwd, real headless UI.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
