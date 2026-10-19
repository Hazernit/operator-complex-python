@echo off
setlocal DisableDelayedExpansion
title Python project launcher
set "PYPROJECT_LAUNCHER_FILE=%~f0"
set "PYPROJECT_LAUNCHER_ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -Command "$s=[IO.File]::ReadAllText($env:PYPROJECT_LAUNCHER_FILE); $p=$s -split '(?m)^# PYPROJECT_POWERSHELL\r?$',2; if($p.Count -ne 2){Write-Host 'Launcher is damaged'; exit 1}; $q=$p[1] -split '(?m)^# PYPROJECT_PYTHON\r?$',2; if($q.Count -ne 2){Write-Host 'Launcher is incomplete'; exit 1}; & ([scriptblock]::Create($q[0]))"
set "PYPROJECT_EXIT=%ERRORLEVEL%"
if "%PYPROJECT_EXIT%"=="0" exit /b 0
echo.
echo See the error above and python-project-launcher.log in the project folder.
pause
exit /b %PYPROJECT_EXIT%
# PYPROJECT_POWERSHELL
# Universal Windows bootstrap. The bundled Python helper inspects the project.
# Python installer and SHA256:
# https://www.python.org/downloads/release/python-31316/
# https://www.python.org/downloads/release/python-3148/
# Installer options: https://docs.python.org/3.13/using/windows.html
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = [IO.Path]::GetFullPath($env:PYPROJECT_LAUNCHER_ROOT)
$log = Join-Path $root 'python-project-launcher.log'
$transcriptStarted = $false
$launcherExit = 1
$helper = $null
$releaseHashes = @{
    '3.13.16' = @{
        'AMD64' = 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b'
        'ARM64' = '696e2226062c6ec3622c13f143d28336a856968518e49cb4f4c62513215a4f5d'
    }
    '3.14.8' = @{
        'AMD64' = '759be887b96e736a3ca886daf8d575f18fcae1a09efab6902f42d59e8999f8ef'
        'ARM64' = '53ba74b5b4370eb823fe0005eedeab907479f7339cecb11efea0e75ab5f10cfc'
    }
}

function Get-PythonVersion([string] $Python) {
    $version = & $Python -I -c "import sys; print('.'.join(map(str,sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the Python version.' }
    return ([string] $version).Trim()
}

function Invoke-ProjectMetadata([string] $Python, [string[]] $Arguments) {
    $output = @(& $Python $helper @Arguments)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the project. See the message above.' }
    return (($output -join "`n") | ConvertFrom-Json)
}

function Test-ProjectCompatibility([string] $Python, [string] $Version) {
    $result = Invoke-ProjectMetadata $Python @('--check-python', $root, '--version', $Version)
    return [bool] $result.compatible
}

function Test-ProjectPython([string] $Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $null }
    if ($Candidate -match '\\Microsoft\\WindowsApps\\') { return $null }
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $null }
    $process = $null
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = [IO.Path]::GetFullPath($Candidate)
        $info.Arguments = '-I -c "import sys,struct,sysconfig,venv,ensurepip; sys.exit(0 if (3,11)<=sys.version_info[:2]<(3,15) and struct.calcsize(''P'')==8 and not sysconfig.get_config_var(''Py_GIL_DISABLED'') else 1)"'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        [void] $process.Start()
        if (-not $process.WaitForExit(15000)) {
            $process.Kill()
            return $null
        }
        if ($process.ExitCode -eq 0) { return $info.FileName }
    } catch {
        # A missing DLL or an obsolete Python is not a usable candidate.
    } finally {
        if ($null -ne $process) { $process.Dispose() }
    }
    return $null
}

function Find-ProjectPythons {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    if ($env:PROJECT_PYTHON) {
        $override = Get-Command $env:PROJECT_PYTHON -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($override) { $candidates.Add($override.Source) }
        else { $candidates.Add($env:PROJECT_PYTHON) }
    }
    $candidates.Add((Join-Path $root '.venv\Scripts\python.exe'))
    $candidates.Add((Join-Path $root '.runtime\python-3.13.16\python.exe'))
    $candidates.Add((Join-Path $root '.runtime\python-3.14.8\python.exe'))
    $branches = @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore'
    )
    foreach ($branch in $branches) {
        foreach ($version in @(Get-ChildItem -LiteralPath $branch -ErrorAction SilentlyContinue)) {
            $key = Get-Item -LiteralPath ($version.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
            if ($null -ne $key) {
                $executable = $key.GetValue('ExecutablePath')
                $directory = $key.GetValue('')
                if ($executable) { $candidates.Add([string] $executable) }
                if ($directory) { $candidates.Add((Join-Path $directory 'python.exe')) }
            }
        }
    }
    foreach ($version in @('313', '312', '311', '314')) {
        if ($env:LOCALAPPDATA) {
            $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe"))
        }
    }
    foreach ($name in @('python.exe', 'python3.exe', 'python3.13.exe', 'python3.12.exe', 'python3.11.exe', 'python3.14.exe')) {
        foreach ($command in @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)) {
            $candidates.Add($command.Source)
        }
    }
    # Both the legacy Python launcher and the install manager support -0p.
    $py = Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($py) {
        $listing = $null
        try {
            $info = New-Object System.Diagnostics.ProcessStartInfo
            $info.FileName = $py.Source
            $info.Arguments = '-0p'
            $info.UseShellExecute = $false
            $info.CreateNoWindow = $true
            $info.RedirectStandardOutput = $true
            $info.RedirectStandardError = $true
            $listing = New-Object System.Diagnostics.Process
            $listing.StartInfo = $info
            [void] $listing.Start()
            if ($listing.WaitForExit(10000)) {
                foreach ($line in ($listing.StandardOutput.ReadToEnd() -split '\r?\n')) {
                    if ($line -match '([A-Za-z]:\\.+?\.exe)\s*$') {
                        $candidates.Add($Matches[1])
                    }
                }
            } else { $listing.Kill() }
        } catch {
            # Missing or unusable launcher: try the actual interpreter paths.
        } finally {
            if ($null -ne $listing) { $listing.Dispose() }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        $working = Test-ProjectPython $candidate
        if ($working) { $working }
    }
}

function Install-ProjectPython([string] $Version) {
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -eq 'ARM64') {
        $installerName = 'python-' + $Version + '-arm64.exe'
        $expectedHash = $releaseHashes[$Version]['ARM64']
    } elseif ($architecture -eq 'AMD64') {
        $installerName = 'python-' + $Version + '-amd64.exe'
        $expectedHash = $releaseHashes[$Version]['AMD64']
    } else {
        throw 'This project needs 64-bit Windows 10 or 11.'
    }
    $runtime = Join-Path $root ('.runtime\python-' + $Version)
    $downloads = Join-Path $root '.runtime\downloads'
    [void] (New-Item -ItemType Directory -Path $downloads -Force)
    $installer = Join-Path $downloads $installerName
    $url = 'https://www.python.org/ftp/python/' + $Version + '/' + $installerName
    Write-Host ('Downloading Python ' + $Version + ' from python.org...')
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $cached = (Test-Path -LiteralPath $installer -PathType Leaf) -and ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -eq $expectedHash)
    if (-not $cached) {
        $partial = $installer + '.part'
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $partial -TimeoutSec 300
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $expectedHash) {
            Remove-Item -LiteralPath $partial -Force
            throw 'Python download failed its SHA256 check. Please run this file again.'
        }
        Move-Item -LiteralPath $partial -Destination $installer -Force
    }
    Write-Host 'Installing Python for this user. Please wait...'
    $installerLog = Join-Path $root 'python-project-install.log'
    $installArguments = @(
        '/quiet', '/norestart', 'InstallAllUsers=0',
        ('TargetDir="{0}"' -f $runtime),
        'Include_pip=1', 'Include_launcher=0', 'InstallLauncherAllUsers=0',
        'PrependPath=0', 'AppendPath=0', 'AssociateFiles=0', 'Shortcuts=0',
        'Include_test=0', 'Include_doc=0', 'Include_tcltk=1', 'Include_dev=1',
        'Include_debug=0', 'Include_symbols=0', 'Include_freethreaded=0',
        '/log', ('"{0}"' -f $installerLog)
    )
    $installation = Start-Process -FilePath $installer -ArgumentList $installArguments -PassThru -Wait
    if ($installation.ExitCode -notin @(0, 3010)) {
        throw "Python installer returned $($installation.ExitCode). See python-project-install.log."
    }
    $python = Test-ProjectPython (Join-Path $runtime 'python.exe')
    if (-not $python) {
        $branch = ($Version.Split('.')[0..1] -join '.') + '.'
        $python = @(Find-ProjectPythons) | Where-Object { (Get-PythonVersion $_).StartsWith($branch) } | Select-Object -First 1
    }
    if (-not $python) {
        if ($installation.ExitCode -eq 3010) {
            throw 'Python installation requires a Windows restart. Restart and run this file again.'
        }
        throw 'Python was installed but could not start. See python-project-install.log.'
    }
    return $python
}

try {
    Set-Location -LiteralPath $root
    Start-Transcript -LiteralPath $log -Force | Out-Null
    $transcriptStarted = $true
    Write-Host 'Python project launcher'
    Write-Host "Project folder: $root"
    if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows 10 or 11 is required.' }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding

    $content = [IO.File]::ReadAllText($env:PYPROJECT_LAUNCHER_FILE)
    $parts = $content -split '(?m)^# PYPROJECT_PYTHON\r?$', 2
    if ($parts.Count -ne 2) { throw 'The launcher file is incomplete.' }
    $helper = Join-Path ([IO.Path]::GetTempPath()) ('python-project-launcher-' + [guid]::NewGuid().ToString('N') + '.py')
    [IO.File]::WriteAllText($helper, $parts[1], (New-Object System.Text.UTF8Encoding($false)))

    Write-Host '[1/4] Finding Python for project inspection...'
    $available = @(Find-ProjectPythons)
    if ($available.Count -eq 0) {
        Write-Host 'Python 3.11-3.14 was not found. Preparing Python 3.13 for inspection.'
        $available = @((Install-ProjectPython '3.13.16'))
    }
    $inspector = $available[0]
    $plan = Invoke-ProjectMetadata $inspector @('--plan-json', $root)
    Write-Host '[2/4] Checking the Python version required by this project...'
    if ($plan.requires_python) { Write-Host "requires-python: $($plan.requires_python)" }
    if ($plan.python_version) { Write-Host ".python-version: $($plan.python_version)" }
    if ($plan.configured_python) { Write-Host "Configured Python: $($plan.configured_python)" }
    if ($plan.requirements) { Write-Host "Requirements: $($plan.requirements)" }
    Write-Host "Install project package: $($plan.install_project)"
    $python = $null
    foreach ($candidate in $available) {
        if (Test-ProjectCompatibility $inspector (Get-PythonVersion $candidate)) {
            $python = $candidate
            break
        }
    }
    if (-not $python) {
        foreach ($version in @('3.13.16', '3.14.8')) {
            if (Test-ProjectCompatibility $inspector $version) {
                $python = Install-ProjectPython $version
                if (-not (Test-ProjectCompatibility $inspector (Get-PythonVersion $python))) {
                    throw 'The installed Python does not satisfy the project requirements.'
                }
                break
            }
        }
    }
    if (-not $python) {
        throw 'No compatible Python was found. Install the Python version specified above and run this file again. Automatic downloads cover Python 3.13/3.14; installed 3.11/3.12 can also be used.'
    }
    Write-Host "Selected Python: $python"

    Write-Host '[3/4] Preparing the project .venv...'
    $venv = Join-Path $root '.venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    $existing = Test-ProjectPython $venvPython
    $reuse = $false
    if ($existing) { $reuse = Test-ProjectCompatibility $inspector (Get-PythonVersion $existing) }
    if ((Test-Path -LiteralPath $venv) -and (-not $reuse)) {
        $backup = '.venv-backup-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        Rename-Item -LiteralPath $venv -NewName $backup
        Write-Host "Previous environment was preserved as $backup"
    }
    if (-not $reuse) {
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. See the error above.' }
    }
    Write-Host 'Checking pip in the project environment...'
    & $venvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare pip in .venv. See the error above.' }
    Write-Host '[4/4] Selecting the entry point, installing dependencies and launching...'
    Write-Host 'If there are several entry points, enter the required menu number.'
    & $venvPython $helper --run $root
    $launcherExit = $LASTEXITCODE
    if ($launcherExit -ne 0) { Write-Host "Project launch finished with code $launcherExit." }
} catch {
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    $launcherExit = 1
} finally {
    if ($helper) { Remove-Item -LiteralPath $helper -Force -ErrorAction SilentlyContinue }
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
exit $launcherExit
# PYPROJECT_PYTHON
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
