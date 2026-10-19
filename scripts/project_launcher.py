"""Inspect and start a local Python project without guessing dependencies from imports.

The Windows launcher embeds this stdlib-only helper and runs it with Python 3.11+.
Inspection reads metadata; package installation and project code run only in --run.
"""

from __future__ import annotations

import argparse
import configparser
from dataclasses import asdict, dataclass
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import Callable


class LauncherError(RuntimeError):
    """An actionable project or launcher configuration error."""


@dataclass(frozen=True)
class Entry:
    type: str
    target: str
    label: str
    args: tuple[str, ...] = ()
    source_dir: str | None = None


@dataclass(frozen=True)
class ProjectPlan:
    root: Path
    requirements: Path | None
    install_project: bool
    requires_python: str | None
    requested_python: str | None
    configured_python: str | None
    python_version: str | None
    entries: tuple[Entry, ...]
    selected_entry: Entry | None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        result = asdict(self)
        result["root"] = str(self.root)
        result["requirements"] = str(self.requirements) if self.requirements else None
        return result


_MODULE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$", re.ASCII)
_CONSOLE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_EXCLUDED_DIRECTORIES = {"tests", "test", "build", "dist", "node_modules", "__pycache__"}


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise LauncherError(f"Cannot read {path.name}: {error}") from error


def _local_file(root: Path, value: str, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise LauncherError(f"{field} must be a nonempty relative file path.")
    # Windows paths must also be rejected when inspection runs on another OS.
    if Path(value).is_absolute() or re.match(r"^[A-Za-z]:", value) or value.startswith(("\\", "/")):
        raise LauncherError(f"{field} must be relative to the project folder.")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise LauncherError(f"{field} points outside the project folder.")
    if not path.is_file():
        raise LauncherError(f"{field} file does not exist: {value}")
    return path


def _configuration(root: Path) -> dict:
    path = root / "project-launcher.json"
    if not path.is_file():
        return {}
    try:
        result = json.loads(_text(path))
    except json.JSONDecodeError as error:
        raise LauncherError(f"Invalid project-launcher.json: {error}") from error
    if not isinstance(result, dict):
        raise LauncherError("project-launcher.json must contain a JSON object.")
    unknown = set(result) - {"python", "entry", "requirements", "install_project"}
    if unknown:
        raise LauncherError(f"Unknown project-launcher.json fields: {', '.join(sorted(unknown))}")
    if "python" in result and (
        not isinstance(result["python"], str)
        or not re.fullmatch(r"3\.\d+(?:\.\d+)?", result["python"])
    ):
        raise LauncherError("project-launcher.json python must be a version such as '3.12'.")
    if "install_project" in result and not isinstance(result["install_project"], bool):
        raise LauncherError("project-launcher.json install_project must be true or false.")
    return result


def _module_source(root: Path, target: str) -> str | None:
    relative = Path(*target.split("."))
    if (root / relative).exists() or (root / relative.with_suffix(".py")).is_file():
        return None
    if (root / "src" / relative).exists() or (root / "src" / relative.with_suffix(".py")).is_file():
        return str(root / "src")
    return None


def _configured_entry(root: Path, configuration: dict) -> Entry | None:
    if "entry" not in configuration:
        return None
    entry = configuration["entry"]
    if not isinstance(entry, dict) or set(entry) - {"type", "target", "args"}:
        raise LauncherError("entry must contain type, target, and optionally args.")
    kind, target = entry.get("type"), entry.get("target")
    if kind not in {"script", "module", "console", "gui"} or not isinstance(target, str):
        raise LauncherError("entry needs type script/module/console/gui and a string target.")
    arguments = entry.get("args", [])
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        raise LauncherError("entry.args must be a JSON array of strings.")
    source_dir = None
    if kind == "script":
        script = _local_file(root, target, "entry.target")
        if script.suffix.lower() != ".py":
            raise LauncherError("A script entry must be a .py file.")
        target = script.relative_to(root).as_posix()
    elif kind == "module":
        if not _MODULE.fullmatch(target):
            raise LauncherError("A module entry must be a dotted Python module name.")
        source_dir = _module_source(root, target)
    elif not _CONSOLE.fullmatch(target):
        raise LauncherError("A console/gui entry must be an installed entry point name.")
    return Entry(kind, target, f"Configured {kind}: {target}", tuple(arguments), source_dir)


def inspect_project(directory: str | Path) -> ProjectPlan:
    """Read supported metadata only. Never import the project or execute setup.py."""
    root = Path(directory).resolve()
    if not root.is_dir():
        raise LauncherError(f"Project folder does not exist: {root}")
    configuration = _configuration(root)
    pyproject_path = root / "pyproject.toml"
    pyproject = {}
    if pyproject_path.is_file():
        try:
            pyproject = tomllib.loads(_text(pyproject_path))
        except tomllib.TOMLDecodeError as error:
            raise LauncherError(f"Invalid pyproject.toml: {error}") from error
    project = pyproject.get("project", {})
    if not isinstance(project, dict):
        raise LauncherError("pyproject.toml [project] must be a table.")
    requires_python = project.get("requires-python")
    if requires_python is not None and not isinstance(requires_python, str):
        raise LauncherError("pyproject.toml requires-python must be a string.")

    setup_cfg = configparser.ConfigParser(interpolation=None)
    setup_cfg_path = root / "setup.cfg"
    if setup_cfg_path.is_file():
        try:
            setup_cfg.read_string(_text(setup_cfg_path))
        except configparser.Error as error:
            raise LauncherError(f"Invalid setup.cfg: {error}") from error
    if requires_python is None:
        requires_python = setup_cfg.get("options", "python_requires", fallback=None)
    package_metadata = bool(
        project.get("name")
        or pyproject.get("build-system")
        or (root / "setup.py").is_file()
        or setup_cfg.get("metadata", "name", fallback="").strip()
    )
    install_project = configuration.get("install_project", package_metadata)
    if install_project and not package_metadata:
        raise LauncherError("install_project=true requires package metadata in pyproject.toml, setup.py, or setup.cfg.")
    if install_project and not pyproject_path.is_file() and not (root / "setup.py").is_file():
        raise LauncherError("setup.cfg alone is not pip-installable. Add the project's pyproject.toml/setup.py, or set install_project=false for a plain script.")

    requirements = root / "requirements.txt" if (root / "requirements.txt").is_file() else None
    if "requirements" in configuration:
        requirements = None if configuration["requirements"] is None else _local_file(
            root, configuration["requirements"], "requirements"
        )
    configured_python = configuration.get("python")
    python_version = None
    version_path = root / ".python-version"
    if version_path.is_file():
        versions = [line.split("#", 1)[0].strip() for line in _text(version_path).splitlines()]
        versions = [line for line in versions if line]
        if len(versions) > 1:
            raise LauncherError("Multiple versions in .python-version; set one python version in project-launcher.json.")
        python_version = versions[0] if versions else None
    requested_python = configured_python or python_version

    entries: list[Entry] = []
    for filename in ("main.py", "app.py", "run.py", "__main__.py"):
        if (root / filename).is_file():
            entries.append(Entry("script", filename, f"Python script: {filename}"))
    if (root / "manage.py").is_file():
        entries.append(Entry("script", "manage.py", "Django: manage.py runserver (127.0.0.1)", ("runserver",)))
    for table, group, kind in (("scripts", "console_scripts", "console"), ("gui-scripts", "gui_scripts", "gui")):
        scripts = project.get(table, {})
        if not isinstance(scripts, dict):
            raise LauncherError(f"pyproject.toml [project.{table}] must be a table.")
        scripts = dict(scripts)
        cfg_scripts = setup_cfg.get("options.entry_points", group, fallback="")
        for line in cfg_scripts.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            name, separator, target = line.partition("=")
            if not separator or not target.strip():
                raise LauncherError(f"Invalid setup.cfg {group} entry: {line}")
            scripts.setdefault(name.strip(), target.strip())
        for name in sorted(scripts):
            if not _CONSOLE.fullmatch(name) or not isinstance(scripts[name], str):
                raise LauncherError(f"Invalid [project.{table}] entry: {name}")
            if install_project:
                label = "Installed GUI command" if kind == "gui" else "Installed command"
                entries.append(Entry(kind, name, f"{label}: {name}"))
    for source in (root, root / "src"):
        if not source.is_dir():
            continue
        for child in sorted(source.iterdir()):
            if (
                child.is_dir() and not child.name.startswith(".")
                and child.name not in _EXCLUDED_DIRECTORIES
                and _MODULE.fullmatch(child.name) and (child / "__main__.py").is_file()
            ):
                entries.append(Entry("module", child.name, f"Python module: {child.name}", (), str(source) if source != root else None))
    override = _configured_entry(root, configuration)
    if override:
        entries = [override]
    # Keep root and src modules distinct when both exist; that is genuinely ambiguous.
    entries = list(dict.fromkeys(entries))
    if not entries and requirements is None and not package_metadata:
        raise LauncherError("No supported Python project found. Expected main.py/app.py/run.py, a runnable package, requirements.txt, or package metadata.")
    warnings = []
    if not entries:
        warnings.append("No entry point detected; add entry to project-launcher.json.")
    if pyproject_path.is_file() and not package_metadata:
        warnings.append("pyproject.toml contains tool configuration only; pip install . will not run.")
    if (root / ".env.example").is_file() and not (root / ".env").exists():
        warnings.append(".env.example exists but .env is missing; the application may require configuration values.")
    return ProjectPlan(
        root, requirements, install_project, requires_python, requested_python, configured_python, python_version,
        tuple(entries), entries[0] if len(entries) == 1 else None, tuple(warnings),
    )


def _specifier_types():
    try:
        from packaging.specifiers import SpecifierSet, InvalidSpecifier
        return SpecifierSet, InvalidSpecifier
    except ImportError:
        try:
            from pip._vendor.packaging.specifiers import SpecifierSet, InvalidSpecifier
            return SpecifierSet, InvalidSpecifier
        except ImportError:
            pass
    # A standard Python installation includes pip's wheel with ensurepip, even
    # when a venv was created using --without-pip. Read it directly; no package
    # installation, network access, or global interpreter changes are needed.
    try:
        import ensurepip
        bundled = Path(ensurepip.__file__).parent / "_bundled"
        wheels = sorted(bundled.glob("pip-*.whl"))
    except (ImportError, TypeError, OSError):
        wheels = []
    for wheel in wheels:
        # Import the standalone vendored packaging package from the wheel. This
        # also works when an existing pip installation has stripped its vendor.
        vendor_path = str(wheel) + "/pip/_vendor"
        sys.path.insert(0, vendor_path)
        importlib.invalidate_caches()
        try:
            from packaging.specifiers import SpecifierSet, InvalidSpecifier
            return SpecifierSet, InvalidSpecifier
        except ImportError:
            continue
        finally:
            sys.path.remove(vendor_path)
    raise LauncherError("Cannot check requires-python: packaging and the ensurepip bundled wheel are unavailable; install packaging into the launcher environment.")


def check_python(plan: ProjectPlan, version: str) -> dict:
    """Check the intersection of metadata constraints without importing project code."""
    if not re.fullmatch(r"3\.\d+(?:\.\d+)?", version):
        raise LauncherError("--version must be a Python version such as 3.13.2.")
    numbers = tuple(int(part) for part in version.split("."))
    if numbers < (3, 11):
        return {"compatible": False, "reason": "This launcher supports Python 3.11 or newer."}
    for origin, requested in (("project-launcher.json python", plan.configured_python), (".python-version", plan.python_version)):
        if not requested:
            continue
        if not re.fullmatch(r"3\.\d+(?:\.\d+)?", requested):
            raise LauncherError(f"Unsupported {origin} value {requested!r}; use a version such as 3.12 or 3.12.3.")
        prefix = tuple(int(part) for part in requested.split("."))
        if numbers[:len(prefix)] != prefix:
            return {"compatible": False, "reason": f"Python {version} does not match {origin}={requested}."}
    if plan.requires_python:
        SpecifierSet, InvalidSpecifier = _specifier_types()
        try:
            specifier = SpecifierSet(plan.requires_python)
        except InvalidSpecifier as error:
            raise LauncherError(f"Invalid requires-python: {plan.requires_python}") from error
        if not specifier.contains(version, prereleases=False):
            return {"compatible": False, "reason": f"Python {version} does not satisfy requires-python={plan.requires_python}."}
    return {"compatible": True, "reason": f"Python {version} satisfies the declared project constraints."}


def choose_entry(
    plan: ProjectPlan,
    selection: str | None = None,
    *,
    input_fn: Callable[[str], str] | None = None,
    interactive: bool | None = None,
) -> Entry:
    if not plan.entries:
        raise LauncherError("No entry point detected. Set entry in project-launcher.json, for example {\"entry\":{\"type\":\"script\",\"target\":\"start.py\"}}.")
    if selection is not None:
        if selection.isdecimal() and 1 <= int(selection) <= len(plan.entries):
            return plan.entries[int(selection) - 1]
        matches = [entry for entry in plan.entries if selection in {entry.target, f"{entry.type}:{entry.target}"}]
        if len(matches) == 1:
            return matches[0]
        raise LauncherError(f"Entry selection is missing or ambiguous: {selection}")
    if plan.selected_entry:
        return plan.selected_entry
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        names = ", ".join(f"{entry.type}:{entry.target}" for entry in plan.entries)
        raise LauncherError(f"Multiple entry points: {names}. Use --entry or project-launcher.json.")
    print("Choose the project entry point:", flush=True)
    for index, entry in enumerate(plan.entries, 1):
        print(f"  {index}. {entry.label}", flush=True)
    read = input if input_fn is None else input_fn
    for _ in range(3):
        try:
            answer = read("Number (or q to cancel): ").strip()
        except EOFError as error:
            raise LauncherError("Entry selection cancelled.") from error
        if answer.lower() in {"q", "quit", "exit"}:
            raise LauncherError("Entry selection cancelled.")
        if answer.isdecimal() and 1 <= int(answer) <= len(plan.entries):
            return plan.entries[int(answer) - 1]
        print("Enter a number from the list.", flush=True)
    raise LauncherError("No valid entry point selected.")


def install_commands(plan: ProjectPlan, executable: str) -> list[list[str]]:
    commands = []
    if plan.requirements:
        commands.append([executable, "-m", "pip", "install", "-r", str(plan.requirements)])
    if plan.install_project:
        commands.append([executable, "-m", "pip", "install", "."])
    return commands


_CONSOLE_RUNNER = (
    "import sys; from importlib.metadata import entry_points; "
    "group=sys.argv.pop(1); name=sys.argv.pop(1); matches=list(entry_points(group=group,name=name)); "
    "assert len(matches)==1, 'Console entry point missing or ambiguous: '+name; "
    "sys.argv[0]=name; sys.exit(matches[0].load()())"
)


def launch_command(plan: ProjectPlan, entry: Entry, executable: str, arguments: list[str]) -> list[str]:
    if entry.type == "script":
        command = [executable, str(plan.root / entry.target)]
    elif entry.type == "module":
        command = [executable, "-m", entry.target]
    elif entry.type in {"console", "gui"}:
        group = "gui_scripts" if entry.type == "gui" else "console_scripts"
        command = [executable, "-c", _CONSOLE_RUNNER, group, entry.target]
    else:
        raise LauncherError(f"Unsupported entry type: {entry.type}")
    return [*command, *entry.args, *arguments]


def run_project(plan: ProjectPlan, *, selection: str | None = None, arguments: list[str] | None = None, setup_only: bool = False) -> int:
    if sys.prefix == sys.base_prefix:
        raise LauncherError("--run must use the prepared .venv Python. Global package installation is disabled.")
    compatibility = check_python(plan, ".".join(str(value) for value in sys.version_info[:3]))
    if not compatibility["compatible"]:
        raise LauncherError(compatibility["reason"])
    # Resolve ambiguity before installing any dependencies.
    entry = None if setup_only else choose_entry(plan, selection)
    for warning in plan.warnings:
        print(f"Note: {warning}", flush=True)
    for command in install_commands(plan, sys.executable):
        print(f"Installing {'requirements' if '-r' in command else 'project package'}...", flush=True)
        subprocess.run(command, cwd=plan.root, check=True)
    if setup_only:
        print("Project environment is ready.", flush=True)
        return 0
    environment = os.environ.copy()
    if entry.source_dir:
        environment["PYTHONPATH"] = entry.source_dir + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    print(f"Starting {entry.label}...", flush=True)
    return subprocess.call(launch_command(plan, entry, sys.executable, arguments or []), cwd=plan.root, env=environment)


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    arguments = []
    if "--" in values:
        boundary = values.index("--")
        values, arguments = values[:boundary], values[boundary + 1:]
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-json", metavar="ROOT")
    mode.add_argument("--run", metavar="ROOT")
    mode.add_argument("--check-python", metavar="ROOT")
    parser.add_argument("--version", help="Python version to check against project metadata")
    parser.add_argument("--entry", help="One-based menu number, target, or type:target")
    parser.add_argument("--setup-only", action="store_true")
    options = parser.parse_args(values)
    try:
        plan = inspect_project(options.plan_json or options.run or options.check_python)
        if options.plan_json:
            print(json.dumps(plan.to_dict(), ensure_ascii=True))
            return 0
        if options.check_python:
            if not options.version:
                raise LauncherError("--check-python requires --version.")
            print(json.dumps(check_python(plan, options.version), ensure_ascii=True))
            return 0
        return run_project(plan, selection=options.entry, arguments=arguments, setup_only=options.setup_only)
    except (LauncherError, OSError, subprocess.CalledProcessError) as error:
        print(f"Project launcher error: {error}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
