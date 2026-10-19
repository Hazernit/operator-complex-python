"""Project inspection and launch planning; no downloads or global installations."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import venv
from unittest.mock import patch

from scripts import project_launcher as launcher


class ProjectLauncherTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="project launcher ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def write(self, filename, text=""):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def config(self, value):
        self.write("project-launcher.json", json.dumps(value))

    def inspect(self):
        return launcher.inspect_project(self.root)

    def test_plain_main_needs_no_manifest(self):
        self.write("main.py", "raise AssertionError('inspection must never execute this')")
        plan = self.inspect()
        self.assertEqual(plan.selected_entry.target, "main.py")
        self.assertFalse(plan.install_project)
        self.assertEqual(launcher.install_commands(plan, "python"), [])

    def test_missing_project_is_actionable(self):
        with self.assertRaisesRegex(launcher.LauncherError, "No supported Python project"):
            self.inspect()

    def test_requirements_and_package_metadata_are_both_installed(self):
        self.write("requirements.txt", "example-dependency>=1")
        self.write("pyproject.toml", '[project]\nname="example"\nversion="1.0"\nrequires-python=">=3.11,<3.14"\n[project.scripts]\nexample="example:main"\n')
        plan = self.inspect()
        self.assertEqual(plan.requires_python, ">=3.11,<3.14")
        self.assertEqual(launcher.install_commands(plan, "my python"), [
            ["my python", "-m", "pip", "install", "-r", str(self.root / "requirements.txt")],
            ["my python", "-m", "pip", "install", "."],
        ])
        self.assertEqual(plan.selected_entry.type, "console")

    def test_tool_only_pyproject_does_not_trigger_pip_install_dot(self):
        self.write("main.py")
        self.write("pyproject.toml", '[tool.ruff]\nline-length=100\n')
        plan = self.inspect()
        self.assertFalse(plan.install_project)
        self.assertTrue(any("tool configuration only" in item for item in plan.warnings))

    def test_setup_py_is_never_executed_during_inspection(self):
        setup = self.write("setup.py", "raise RuntimeError('do not execute during inspection')")
        self.write("app.py")
        self.assertTrue(self.inspect().install_project)
        self.assertIn("do not execute", setup.read_text(encoding="utf-8"))

    def test_setup_cfg_metadata_and_python_requires(self):
        self.write("pyproject.toml", '[build-system]\nrequires=["setuptools"]\nbuild-backend="setuptools.build_meta"\n')
        self.write("setup.cfg", "[metadata]\nname=example\n[options]\npython_requires=>=3.12\n")
        self.write("main.py")
        plan = self.inspect()
        self.assertTrue(plan.install_project)
        self.assertEqual(plan.requires_python, ">=3.12")

    def test_setup_cfg_alone_explains_missing_build_manifest(self):
        self.write("setup.cfg", "[metadata]\nname=example\n")
        self.write("main.py")
        with self.assertRaisesRegex(launcher.LauncherError, "setup.cfg alone is not pip-installable"):
            self.inspect()

    def test_setup_cfg_console_entry_is_detected(self):
        self.write("setup.py", "# Package setup is deliberately not executed in this test.")
        self.write("setup.cfg", "[metadata]\nname=example\n[options.entry_points]\nconsole_scripts=\n    robot-ui = robot_ui.cli:main\n")
        plan = self.inspect()
        self.assertEqual(plan.selected_entry.type, "console")
        self.assertEqual(plan.selected_entry.target, "robot-ui")

    def test_pyproject_gui_entry_selects_gui_metadata_group(self):
        self.write("pyproject.toml", '[project]\nname="example"\n[project.gui-scripts]\nrobot-ui="robot_ui:main"\n')
        plan = self.inspect()
        entry = plan.selected_entry
        self.assertEqual(entry.type, "gui")
        command = launcher.launch_command(plan, entry, "python", ["--test"])
        self.assertEqual(command[-3:], ["gui_scripts", "robot-ui", "--test"])

    def test_setup_cfg_gui_entry_is_detected(self):
        self.write("setup.py")
        self.write("setup.cfg", "[metadata]\nname=example\n[options.entry_points]\ngui_scripts=\n    robot-ui = robot_ui:main\n")
        self.assertEqual(self.inspect().selected_entry.type, "gui")

    def test_explicit_gui_entry_configuration(self):
        self.config({"entry": {"type": "gui", "target": "robot-ui"}})
        self.assertEqual(self.inspect().selected_entry.type, "gui")

    def test_missing_env_warning_does_not_read_example_values(self):
        self.write("main.py")
        self.write(".env.example", "SECRET=must-not-appear-in-plan\n")
        plan = self.inspect()
        self.assertTrue(any(".env is missing" in item for item in plan.warnings))
        self.assertNotIn("must-not-appear", json.dumps(plan.to_dict()))
        self.write(".env", "SECRET=also-must-not-appear")
        self.assertFalse(any(".env is missing" in item for item in self.inspect().warnings))

    def test_src_package_with_main_is_detected_and_importable(self):
        self.write("src/robot_ui/__main__.py")
        self.write("pyproject.toml", '[project]\nname="robot-ui"\nversion="1.0"\n')
        plan = self.inspect()
        self.assertEqual(plan.selected_entry.type, "module")
        self.assertEqual(plan.selected_entry.target, "robot_ui")
        self.assertEqual(plan.selected_entry.source_dir, str(self.root / "src"))
        self.assertTrue(plan.install_project)

    def test_src_package_without_metadata_still_runs_with_source_path(self):
        self.write("src/robot_ui/__main__.py")
        plan = self.inspect()
        self.assertFalse(plan.install_project)
        with patch.object(launcher.sys, "prefix", "prepared-venv"), \
             patch.object(launcher.subprocess, "call", return_value=4) as call, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.run_project(plan), 4)
        command = call.call_args.args[0]
        self.assertEqual(command, [launcher.sys.executable, "-m", "robot_ui"])
        self.assertTrue(call.call_args.kwargs["env"]["PYTHONPATH"].startswith(str(self.root / "src")))

    def test_multiple_console_entries_do_not_silently_choose_one(self):
        self.write("pyproject.toml", '[project]\nname="example"\n[project.scripts]\na="example:a"\nb="example:b"\n')
        plan = self.inspect()
        self.assertIsNone(plan.selected_entry)
        with self.assertRaisesRegex(launcher.LauncherError, "Multiple entry points"):
            launcher.choose_entry(plan, interactive=False)
        self.assertEqual(launcher.choose_entry(plan, "console:b").target, "b")
        with redirect_stdout(io.StringIO()):
            selected = launcher.choose_entry(plan, interactive=True, input_fn=lambda _: "2")
        self.assertEqual(selected.target, "b")

    def test_invalid_menu_input_retries_then_cancels(self):
        self.write("main.py")
        self.write("app.py")
        answers = iter(["0", "abc", "q"])
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(launcher.LauncherError, "cancelled"):
                launcher.choose_entry(self.inspect(), interactive=True, input_fn=lambda _: next(answers))

    def test_configured_entry_overrides_ambiguity_and_keeps_arguments_literal(self):
        self.write("main.py")
        self.write("app.py")
        strange = "$(touch never); & echo 'literal'"
        self.config({"entry": {"type": "script", "target": "app.py", "args": ["--config", strange]}})
        plan = self.inspect()
        self.assertEqual(len(plan.entries), 1)
        self.assertEqual(launcher.launch_command(plan, plan.selected_entry, "python exe", ["--tail"]), [
            "python exe", str(self.root / "app.py"), "--config", strange, "--tail",
        ])

    def test_streamlit_requires_explicit_config_and_is_not_guessed_from_imports(self):
        self.write("app.py", "import streamlit\n")
        self.assertEqual(self.inspect().selected_entry.type, "script")
        self.config({"entry": {"type": "module", "target": "streamlit", "args": ["run", "app.py"]}})
        plan = self.inspect()
        self.assertEqual(launcher.launch_command(plan, plan.selected_entry, "python", []), [
            "python", "-m", "streamlit", "run", "app.py",
        ])

    def test_django_manage_py_starts_local_default_runserver(self):
        self.write("manage.py")
        entry = self.inspect().selected_entry
        self.assertEqual(entry.target, "manage.py")
        self.assertEqual(entry.args, ("runserver",))

    def test_custom_requirements_and_opt_out(self):
        custom = self.write("deps/windows.txt", "example")
        self.write("main.py")
        self.config({"requirements": "deps/windows.txt"})
        self.assertEqual(self.inspect().requirements, custom)
        self.config({"requirements": None})
        self.assertIsNone(self.inspect().requirements)

    def test_paths_outside_root_and_absolute_windows_paths_are_rejected(self):
        self.write("main.py")
        for target in ("../outside.py", "C:\\outside.py", "/outside.py"):
            with self.subTest(target=target):
                self.config({"entry": {"type": "script", "target": target}})
                with self.assertRaises(launcher.LauncherError):
                    self.inspect()

    def test_existing_project_files_are_not_modified(self):
        self.write("main.py", "print('keep me')\n")
        self.write("requirements.txt", "# preserve comments\n")
        self.write(".venv/preserve.txt", "existing user environment")
        snapshot = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.inspect()
        self.assertEqual(snapshot, {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_invalid_metadata_stops_without_installing(self):
        self.write("pyproject.toml", "[project")
        with self.assertRaisesRegex(launcher.LauncherError, "Invalid pyproject.toml"):
            self.inspect()

    def test_python_constraints_intersect_config_file_and_project(self):
        self.write("main.py")
        self.write("pyproject.toml", '[project]\nname="example"\nrequires-python=">=3.12.3,<3.13"\n')
        self.write(".python-version", "3.12\n")
        self.config({"python": "3.12"})
        plan = self.inspect()
        self.assertEqual(plan.python_version, "3.12")
        self.assertTrue(launcher.check_python(plan, "3.12.4")["compatible"])
        self.assertFalse(launcher.check_python(plan, "3.12.2")["compatible"])
        self.assertFalse(launcher.check_python(plan, "3.13.1")["compatible"])

    def test_python_version_patch_is_exact_and_conflicting_constraints_are_preserved(self):
        self.write("main.py")
        self.write(".python-version", "3.12.4\n")
        plan = self.inspect()
        self.assertTrue(launcher.check_python(plan, "3.12.4")["compatible"])
        self.assertFalse(launcher.check_python(plan, "3.12.5")["compatible"])
        self.config({"python": "3.13"})
        plan = self.inspect()
        self.assertEqual(plan.requested_python, "3.13")
        self.assertFalse(launcher.check_python(plan, "3.13.1")["compatible"])
        self.assertFalse(launcher.check_python(plan, "3.12.4")["compatible"])

    def test_unsupported_python_version_and_invalid_specifier_are_actionable(self):
        self.write("main.py")
        self.write(".python-version", "system\n")
        with self.assertRaisesRegex(launcher.LauncherError, "Unsupported .python-version"):
            launcher.check_python(self.inspect(), "3.12.4")
        self.write(".python-version", "3.12\n")
        self.write("pyproject.toml", '[project]\nname="example"\nrequires-python="definitely not a specifier"\n')
        with self.assertRaisesRegex(launcher.LauncherError, "Invalid requires-python"):
            launcher.check_python(self.inspect(), "3.12.4")

    def test_plan_json_is_machine_readable(self):
        self.write("main.py")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(launcher.main(["--plan-json", str(self.root)]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["root"], str(self.root))
        self.assertEqual(data["selected_entry"]["target"], "main.py")

    def test_check_python_json_returns_false_without_process_failure(self):
        self.write("main.py")
        self.config({"python": "3.12"})
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(launcher.main(["--check-python", str(self.root), "--version", "3.13.1"]), 0)
        self.assertFalse(json.loads(output.getvalue())["compatible"])

    def test_real_venv_without_pip_checks_spec_from_ensurepip_wheel(self):
        self.write("main.py")
        self.write("pyproject.toml", '[project]\nname="example"\nrequires-python=">=3.11"\n')
        environment = self.root / ".without-pip"
        venv.EnvBuilder(with_pip=False).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        probe = subprocess.run(
            [str(python), "-c", "import importlib.util; assert importlib.util.find_spec('pip') is None; assert importlib.util.find_spec('packaging') is None"],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(probe.returncode, 0)
        version = ".".join(map(str, launcher.sys.version_info[:3]))
        result = subprocess.run(
            [str(python), str(Path(launcher.__file__).resolve()), "--check-python", str(self.root), "--version", version],
            check=True, capture_output=True, text=True,
        )
        self.assertTrue(json.loads(result.stdout)["compatible"])
        # Merely checking compatibility must not install pip into that venv.
        subprocess.run(
            [str(python), "-c", "import importlib.util; assert importlib.util.find_spec('pip') is None"],
            check=True, capture_output=True, text=True,
        )

    def test_run_does_not_install_into_global_python(self):
        self.write("main.py")
        with patch.object(launcher.sys, "prefix", launcher.sys.base_prefix), \
             patch.object(launcher.subprocess, "run") as install:
            with self.assertRaisesRegex(launcher.LauncherError, "Global package installation is disabled"):
                launcher.run_project(self.inspect())
        install.assert_not_called()

    def test_ambiguous_project_does_not_install_before_entry_selected(self):
        self.write("main.py")
        self.write("app.py")
        self.write("requirements.txt")
        with patch.object(launcher.sys, "prefix", "prepared-venv"), \
             patch.object(launcher.sys.stdin, "isatty", return_value=False), \
             patch.object(launcher.subprocess, "run") as install:
            with self.assertRaisesRegex(launcher.LauncherError, "Multiple entry points"):
                launcher.run_project(self.inspect())
        install.assert_not_called()

    def test_failed_install_prevents_launch(self):
        self.write("main.py")
        self.write("requirements.txt")
        with patch.object(launcher.sys, "prefix", "prepared-venv"), \
             patch.object(launcher.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "pip")), \
             patch.object(launcher.subprocess, "call") as launch, \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(launcher.main(["--run", str(self.root)]), 1)
        launch.assert_not_called()

    def test_setup_only_installs_without_entry_or_launch(self):
        self.write("requirements.txt")
        with patch.object(launcher.sys, "prefix", "prepared-venv"), \
             patch.object(launcher.subprocess, "run") as install, \
             patch.object(launcher.subprocess, "call") as launch, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.run_project(self.inspect(), setup_only=True), 0)
        install.assert_called_once()
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
