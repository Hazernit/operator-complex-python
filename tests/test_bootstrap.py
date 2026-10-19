"""Startup checks without installing packages, using the network, or opening Qt."""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import bootstrap


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="operator startup ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        root_patch = patch.object(bootstrap, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.executable = self.root / ".venv" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )

    def existing_environment(self):
        environment = self.root / ".venv"
        environment.mkdir()
        marker = environment / "keep-user-files.txt"
        marker.write_text("existing environment", encoding="utf-8")
        return marker

    def test_invalid_explicit_python_does_not_silently_fall_back(self):
        with patch.dict(os.environ, {"OPERATOR_PYTHON": "/missing/python3.12"}), \
             patch.object(bootstrap.shutil, "which", return_value=None) as which, \
             patch.object(bootstrap, "supported_python", return_value=False) as supported:
            with self.assertRaisesRegex(RuntimeError, "OPERATOR_PYTHON.*3.11"):
                bootstrap.find_python()
        which.assert_called_once_with("/missing/python3.12")
        supported.assert_called_once_with("/missing/python3.12")

    def test_ready_environment_does_not_create_or_install_anything(self):
        marker = self.existing_environment()
        with patch.object(bootstrap, "supported_python", return_value=True), \
             patch.object(bootstrap, "dependencies_ready", return_value=True), \
             patch.object(bootstrap, "find_python") as find, \
             patch.object(bootstrap.subprocess, "run") as run:
            self.assertEqual(bootstrap.prepare_environment(), self.executable)
        find.assert_not_called()
        run.assert_not_called()
        self.assertEqual(marker.read_text(encoding="utf-8"), "existing environment")

    def test_incompatible_environment_reports_recovery_and_preserves_files(self):
        marker = self.existing_environment()
        with patch.object(bootstrap, "supported_python", return_value=False), \
             patch.object(bootstrap, "dependencies_ready") as ready, \
             patch.object(bootstrap, "find_python") as find, \
             patch.object(bootstrap.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, r"\.venv-old"):
                bootstrap.prepare_environment()
        ready.assert_not_called()
        find.assert_not_called()
        run.assert_not_called()
        self.assertEqual(marker.read_text(encoding="utf-8"), "existing environment")

    def test_failed_install_returns_failure_and_does_not_launch_application(self):
        marker = self.existing_environment()
        error_output = io.StringIO()
        with patch.object(bootstrap, "supported_python", return_value=True), \
             patch.object(bootstrap, "dependencies_ready", return_value=False), \
             patch.object(bootstrap.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "pip")) as run, \
             patch.object(bootstrap.subprocess, "call") as launch, \
             redirect_stdout(io.StringIO()), redirect_stderr(error_output):
            self.assertEqual(bootstrap.main(["--smoke-test"]), 1)
        run.assert_called_once_with(
            [str(self.executable), "-m", "pip", "install", "-r", str(self.root / "requirements.txt")],
            check=True, cwd=self.root,
        )
        launch.assert_not_called()
        self.assertIn("Проверьте подключение к интернету", error_output.getvalue())
        self.assertTrue(marker.is_file())

    def test_arguments_are_forwarded_as_a_list_without_shell_interpretation(self):
        arguments = ["--config", "папка с пробелами/$(touch unexpected).json", "--smoke-test"]
        original = list(arguments)
        with patch.object(bootstrap, "prepare_environment", return_value=self.executable), \
             patch.object(bootstrap.subprocess, "call", return_value=7) as launch:
            self.assertEqual(bootstrap.main(arguments), 7)
        launch.assert_called_once_with(
            [str(self.executable), str(self.root / "main.py"), *original], cwd=self.root,
        )
        self.assertEqual(arguments, original)

    def test_fresh_environment_is_created_locally_with_selected_python(self):
        selected = "/some Python installation/python3.12"
        with patch.object(bootstrap, "find_python", return_value=selected), \
             patch.object(bootstrap, "dependencies_ready", return_value=True), \
             patch.object(bootstrap.subprocess, "run") as run, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.prepare_environment(), self.executable)
        run.assert_called_once_with(
            [selected, "-m", "venv", str(self.root / ".venv")], check=True, cwd=self.root,
        )

    def test_setup_only_does_not_launch_the_application(self):
        with patch.object(bootstrap, "prepare_environment", return_value=self.executable), \
             patch.object(bootstrap.subprocess, "call") as launch, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["--setup-only"]), 0)
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
