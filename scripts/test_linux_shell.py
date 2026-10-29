"""POSIX-shell contract tests, run explicitly by Linux launcher CI.

Kept outside cross-platform unittest discovery because Windows has no POSIX shell.
No Qt installation, internet access, or environment creation is used here.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class LinuxShellTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="operator shell tests ")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.project = self.base / "source project with spaces"
        self.project.mkdir()
        shutil.copyfile(ROOT / "run-linux.sh", self.project / "run-linux.sh")
        (self.project / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/linux_launcher.py", self.project / "scripts/linux_launcher.py")
        shutil.copyfile(ROOT / "bootstrap.py", self.project / "bootstrap.py")
        self.cwd = self.base / "unrelated caller directory"
        self.cwd.mkdir()
        self.bin = self.base / "commands"
        self.bin.mkdir()
        # Only platform/path utilities are exposed; no Python can leak in from PATH.
        for name in ("dirname", "uname", "readlink"):
            executable = shutil.which(name)
            if executable:
                (self.bin / name).symlink_to(executable)
        self.record = self.base / "arguments.txt"
        self.environment = dict(os.environ, PATH=str(self.bin), OPERATOR_SHELL_RECORD=str(self.record))
        self.environment.pop("OPERATOR_PYTHON", None)
        self.shell = shutil.which("sh")
        if not self.shell:
            raise RuntimeError("These tests require the POSIX sh used by the Linux launcher")

    def fake_python(self, name="python3") -> Path:
        interpreter = self.bin / name
        interpreter.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$OPERATOR_SHELL_RECORD"\nexit 23\n',
            encoding="utf-8",
        )
        interpreter.chmod(0o755)
        return interpreter

    def launch(self, arguments=()):
        return subprocess.run(
            [self.shell, str(self.project / "run-linux.sh"), *arguments],
            cwd=self.cwd, env=self.environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )

    def test_missing_python_is_actionable(self):
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python", result.stdout + result.stderr)
        self.assertIn("3.11", result.stdout + result.stderr)
        self.assertFalse((self.project / ".venv").exists())

    def test_arbitrary_cwd_spaces_arguments_and_exit_status(self):
        self.fake_python()
        arguments = ["--config", "a b/$(touch must-not-exist).json", "--smoke-test"]
        result = self.launch(arguments)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        recorded = self.record.read_text(encoding="utf-8").splitlines()
        self.assertEqual(recorded[0], str(self.project))
        self.assertEqual(Path(recorded[1]).resolve(), self.project / "scripts/linux_launcher.py")
        self.assertEqual(recorded[2:], arguments)
        self.assertFalse((self.project / "must-not-exist").exists())
        self.assertFalse((self.cwd / ".venv").exists())

    def test_explicit_interpreter_path_with_spaces_is_preserved(self):
        interpreter = self.fake_python("Python installation with spaces")
        self.environment["OPERATOR_PYTHON"] = str(interpreter)
        result = self.launch(["--setup-only"])
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(self.record.read_text(encoding="utf-8").splitlines()[-1], "--setup-only")

    def test_missing_explicit_python_does_not_fall_back(self):
        self.fake_python()
        self.environment["OPERATOR_PYTHON"] = str(self.bin / "missing-python")
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OPERATOR_PYTHON", result.stdout + result.stderr)
        self.assertFalse(self.record.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
