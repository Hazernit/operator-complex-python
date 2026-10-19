"""Combine the generic Windows bootstrap and Python inspector into one BAT."""

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent.parent
WRAPPER = r'''@echo off
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
'''


def build():
    powershell = (ROOT / 'scripts/windows_project_launcher.ps1').read_text(encoding='utf-8')
    python = (ROOT / 'scripts/project_launcher.py').read_text(encoding='utf-8')
    for marker in ('# PYPROJECT_POWERSHELL', '# PYPROJECT_PYTHON'):
        assert marker not in powershell.splitlines() and marker not in python.splitlines()
    source = WRAPPER + powershell.rstrip() + '\n# PYPROJECT_PYTHON\n' + python
    target = ROOT / 'run-python-project.bat'
    target.write_bytes(source.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
    output = ROOT / 'output/run-python-project.bat'
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, output)
    print(f'{output}: {output.stat().st_size:,} bytes (launcher logic only)')


if __name__ == '__main__':
    build()
