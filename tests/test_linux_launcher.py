"""Linux preflight contracts, deterministic on every CI operating system."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import linux_launcher


class DisplaySelectionTests(unittest.TestCase):
    def setUp(self):
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_headless_smoke_selects_offscreen(self):
        environment = {}
        linux_launcher.configure_display(["--smoke-test"], environment)
        self.assertEqual(environment.get("QT_QPA_PLATFORM"), "offscreen")

    def test_screenshot_uses_existing_headless_application_mode(self):
        environment = {}
        linux_launcher.configure_display(["--screenshot", "window.png"], environment)
        self.assertEqual(environment.get("QT_QPA_PLATFORM"), "offscreen")

    def test_explicit_qt_platform_is_preserved_in_smoke(self):
        for platform in ("xcb", "wayland", "offscreen", "minimal", "wayland;xcb"):
            with self.subTest(platform=platform):
                environment = {"QT_QPA_PLATFORM": platform}
                linux_launcher.configure_display(["--smoke-test"], environment)
                self.assertEqual(environment["QT_QPA_PLATFORM"], platform)

    def test_x11_session_remains_available_to_qt(self):
        environment = {"DISPLAY": ":45"}
        linux_launcher.configure_display([], environment)
        self.assertEqual(environment["DISPLAY"], ":45")
        self.assertEqual(environment.get("QT_QPA_PLATFORM"), "xcb")

    def test_wayland_session_remains_available_to_qt(self):
        environment = {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/1000"}
        linux_launcher.configure_display([], environment)
        self.assertEqual(environment["WAYLAND_DISPLAY"], "wayland-0")
        self.assertEqual(environment.get("QT_QPA_PLATFORM"), "wayland")

    def test_mixed_session_prefers_wayland_without_overriding_explicit_choice(self):
        environment = {"DISPLAY": ":45", "WAYLAND_DISPLAY": "wayland-0"}
        linux_launcher.configure_display([], environment)
        self.assertEqual(environment["QT_QPA_PLATFORM"], "wayland")
        environment["QT_QPA_PLATFORM"] = "xcb"
        linux_launcher.configure_display([], environment)
        self.assertEqual(environment["QT_QPA_PLATFORM"], "xcb")

    def test_screenshot_equals_form_selects_offscreen(self):
        environment = {}
        linux_launcher.configure_display(["--screenshot=window with spaces.png"], environment)
        self.assertEqual(environment.get("QT_QPA_PLATFORM"), "offscreen")

    def test_help_requires_no_display_or_qt_probe(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(linux_launcher.bootstrap, "find_python", return_value="python3.12"), \
             patch.object(linux_launcher.bootstrap, "main", return_value=0) as bootstrap_main, \
             patch.object(linux_launcher, "check_native_imports"), \
             patch.object(linux_launcher, "check_qt") as check:
            self.assertEqual(linux_launcher.main(["--help"]), 0)
        check.assert_not_called()
        self.assertEqual(bootstrap_main.call_args.args[0], ["--help"])

    def test_gui_without_display_reports_headless_smoke_instructions(self):
        with self.assertRaisesRegex(RuntimeError, "(?i)(headless|диспле|графическ)") as error:
            linux_launcher.configure_display([], {})
        self.assertIn("--smoke-test", str(error.exception))
        self.assertIn("offscreen", str(error.exception))

    def test_setup_only_needs_no_display(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(linux_launcher.bootstrap, "find_python", return_value="python3.12"), \
             patch.object(linux_launcher.bootstrap, "main", return_value=0) as bootstrap_main, \
             patch.object(linux_launcher, "check_native_imports"):
            self.assertEqual(linux_launcher.main(["--setup-only"]), 0)
        bootstrap_main.assert_called_once_with(["--setup-only"], before_launch=None)


class LinuxPreflightTests(unittest.TestCase):
    def setUp(self):
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.directory = tempfile.TemporaryDirectory(prefix="operator preflight tests ")
        self.addCleanup(self.directory.cleanup)
        root_patch = patch.object(linux_launcher, "ROOT", Path(self.directory.name))
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def test_main_delegates_setup_and_arguments_to_shared_bootstrap(self):
        arguments = ["--config", "path with spaces/$(touch unexpected).json", "--smoke-test"]
        original = list(arguments)
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(linux_launcher.bootstrap, "find_python", return_value="python3.12"), \
             patch.object(linux_launcher.bootstrap, "main", return_value=19) as bootstrap_main:
            self.assertEqual(linux_launcher.main(arguments), 19)
        bootstrap_main.assert_called_once_with(original, before_launch=linux_launcher.check_qt)
        self.assertEqual(arguments, original)

    def test_unsupported_explicit_python_failure_does_not_reach_bootstrap(self):
        error_output = io.StringIO()
        with patch.object(linux_launcher.bootstrap, "find_python", side_effect=RuntimeError("OPERATOR_PYTHON requires Python 3.11+")), \
             patch.object(linux_launcher.bootstrap, "main") as bootstrap_main, \
             redirect_stderr(error_output):
            self.assertEqual(linux_launcher.main(["--smoke-test"]), 1)
        bootstrap_main.assert_not_called()
        self.assertIn("3.11", error_output.getvalue())

    def test_old_entry_interpreter_reexecutes_bootstrap_selected_python(self):
        arguments = ["--smoke-test"]
        with patch.object(linux_launcher.bootstrap, "find_python", return_value="/Python 3.12/bin/python"), \
             patch.object(linux_launcher.sys, "version_info", (3, 10)), \
             patch.object(linux_launcher.os, "execv", side_effect=OSError("stop test before reexec")) as reexec, \
             redirect_stderr(io.StringIO()):
            self.assertEqual(linux_launcher.main(arguments), 1)
        reexec.assert_called_once_with(
            "/Python 3.12/bin/python",
            ["/Python 3.12/bin/python", str(Path(linux_launcher.__file__).resolve()), *arguments],
        )

    def test_native_import_error_is_reported_before_pip_or_application_start(self):
        with patch.object(linux_launcher.bootstrap, "find_python", return_value="python3.12"), \
             patch.object(linux_launcher, "check_native_imports", side_effect=RuntimeError("libEGL.so.1 missing")), \
             patch.object(linux_launcher.bootstrap, "main") as bootstrap_main, \
             redirect_stderr(io.StringIO()):
            self.assertEqual(linux_launcher.main(["--smoke-test"]), 1)
        bootstrap_main.assert_not_called()

    def test_fresh_install_native_failure_gets_final_system_library_diagnostic(self):
        error_output = io.StringIO()
        with patch.object(linux_launcher.bootstrap, "find_python", return_value="python3.12"), \
             patch.object(linux_launcher, "check_native_imports", side_effect=[None, RuntimeError("libEGL.so.1 missing")]) as native, \
             patch.object(linux_launcher.bootstrap, "main", return_value=1) as bootstrap_main, \
             redirect_stderr(error_output):
            self.assertEqual(linux_launcher.main(["--smoke-test"]), 1)
        self.assertEqual(native.call_count, 2)
        bootstrap_main.assert_called_once()
        self.assertIn("libEGL.so.1", error_output.getvalue())

    def test_installed_pyside_blocked_by_native_library_has_actionable_error(self):
        executable = Path(self.directory.name) / "python"
        executable.touch()
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="ImportError: libEGL.so.1: cannot open shared object file")
        with patch.object(linux_launcher.subprocess, "run", return_value=result), \
             patch.object(linux_launcher, "missing_qt_libraries", return_value=["libEGL.so.1"]):
            with self.assertRaisesRegex(RuntimeError, "libEGL.so.1") as error:
                linux_launcher.check_native_imports(executable)
        self.assertIn("libegl1", str(error.exception))

    def test_missing_pyside_is_left_to_bootstrap_dependency_installation(self):
        executable = Path(self.directory.name) / "python"
        executable.touch()
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="ModuleNotFoundError: No module named 'PySide6'")
        with patch.object(linux_launcher.subprocess, "run", return_value=result), \
             patch.object(linux_launcher, "missing_qt_libraries") as libraries:
            linux_launcher.check_native_imports(executable)
        libraries.assert_not_called()

    def test_qt_abort_reports_actual_native_library_and_original_diagnostic(self):
        executable = Path("/source with spaces/.venv/bin/python")
        result = subprocess.CompletedProcess([], -6, stdout="", stderr="Could not load the Qt platform plugin xcb")
        with patch.object(linux_launcher.subprocess, "run", return_value=result) as run, \
             patch.object(linux_launcher, "missing_qt_libraries", return_value=["libEGL.so.1", "libxcb-cursor.so.0"]):
            with self.assertRaisesRegex(RuntimeError, "libEGL.so.1") as error:
                linux_launcher.check_qt(executable)
        message = str(error.exception)
        self.assertIn("libxcb-cursor0", message)
        self.assertIn("libegl1", message)
        self.assertIn("Could not load the Qt platform plugin xcb", message)
        self.assertEqual(run.call_args.args[0][0], str(executable))
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_qt_timeout_is_bounded_and_actionable(self):
        with patch.object(linux_launcher.subprocess, "run", side_effect=subprocess.TimeoutExpired("Qt", 30)):
            with self.assertRaisesRegex(RuntimeError, "30.*DISPLAY"):
                linux_launcher.check_qt("python")

    def test_display_connection_failure_preserves_qt_output_without_guessed_packages(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="could not connect to display :99")
        with patch.object(linux_launcher.subprocess, "run", return_value=result), \
             patch.object(linux_launcher, "missing_qt_libraries", return_value=[]):
            with self.assertRaises(RuntimeError) as error:
                linux_launcher.check_qt("python")
        self.assertIn("could not connect to display :99", str(error.exception))
        self.assertNotIn("libxcb-cursor0", str(error.exception))

    def test_healthy_qt_is_checked_in_child_process(self):
        result = subprocess.CompletedProcess([], 0, stdout="Qt platform: offscreen\n", stderr="")
        with patch.object(linux_launcher.subprocess, "run", return_value=result), \
             patch.object(linux_launcher, "missing_qt_libraries") as missing:
            linux_launcher.check_qt("python")
        missing.assert_not_called()

    def test_missing_ldd_does_not_hide_original_qt_error(self):
        with patch.object(linux_launcher.shutil, "which", return_value=None), \
             patch.object(linux_launcher.subprocess, "run") as run:
            self.assertEqual(linux_launcher.missing_qt_libraries("python"), [])
        run.assert_not_called()

    def test_current_wayland_plugin_filename_is_included_in_native_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix="operator Wayland wheel ") as directory:
            plugin = Path(directory) / "Qt/plugins/platforms/libqwayland.so"
            plugin.parent.mkdir(parents=True)
            plugin.touch()
            results = [
                subprocess.CompletedProcess([], 0, stdout=json.dumps([directory])),
                subprocess.CompletedProcess([], 0, stdout=" libxkbcommon.so.0 => not found\n"),
            ]
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "wayland"}, clear=True), \
                 patch.object(linux_launcher.shutil, "which", return_value="/usr/bin/ldd"), \
                 patch.object(linux_launcher.subprocess, "run", side_effect=results) as run:
                self.assertEqual(linux_launcher.missing_qt_libraries("python"), ["libxkbcommon.so.0"])
            self.assertEqual(run.call_args.args[0], ["ldd", str(plugin)])

    def test_ldd_diagnostics_scan_only_installed_core_and_selected_plugins(self):
        with tempfile.TemporaryDirectory(prefix="operator Qt wheel ") as directory:
            pyside = Path(directory)
            core = pyside / "Qt/lib/libQt6Gui.so.6"
            plugin = pyside / "Qt/plugins/platforms/libqxcb.so"
            core.parent.mkdir(parents=True)
            plugin.parent.mkdir(parents=True)
            core.touch()
            plugin.touch()
            (plugin.parent / "libqwayland-generic.so").touch()
            results = [
                subprocess.CompletedProcess([], 0, stdout=json.dumps([directory])),
                subprocess.CompletedProcess([], 0, stdout=" libEGL.so.1 => not found\n"),
                subprocess.CompletedProcess([], 0, stdout=" libxcb-cursor.so.0 => not found\n libEGL.so.1 => not found\n"),
            ]
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "xcb"}, clear=True), \
                 patch.object(linux_launcher.shutil, "which", return_value="/usr/bin/ldd"), \
                 patch.object(linux_launcher.subprocess, "run", side_effect=results) as run:
                self.assertEqual(linux_launcher.missing_qt_libraries("python"), ["libEGL.so.1", "libxcb-cursor.so.0"])
            self.assertEqual([call.args[0] for call in run.call_args_list[1:]], [["ldd", str(core)], ["ldd", str(plugin)]])


if __name__ == "__main__":
    unittest.main()
