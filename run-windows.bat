@echo off
setlocal DisableDelayedExpansion
title Operator Complex - setup and launch
set "OPERATOR_LAUNCHER=%~f0"
set "OPERATOR_ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -Command "$s=[IO.File]::ReadAllText($env:OPERATOR_LAUNCHER); $p=$s -split '(?m)^# OPERATOR_POWERSHELL\r?$',2; if($p.Count -ne 2){Write-Host 'Launcher is damaged'; exit 1}; & ([scriptblock]::Create($p[1]))"
set "OPERATOR_EXIT=%ERRORLEVEL%"
if "%OPERATOR_EXIT%"=="0" exit /b 0
echo.
echo Setup or launch failed. See the error above and setup-windows.log in the project folder.
pause
exit /b %OPERATOR_EXIT%
# OPERATOR_POWERSHELL
# Setup and launch only. Place this file next to main.py and requirements.txt.
# Requires Windows 10/11, 64-bit. No application sources are embedded.
# Python installer and SHA256:
# https://www.python.org/downloads/release/python-31316/
# Installer options: https://docs.python.org/3.13/using/windows.html
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = [IO.Path]::GetFullPath($env:OPERATOR_ROOT)
$log = Join-Path $root 'setup-windows.log'
$transcriptStarted = $false
$launcherExit = 1

function Test-ProjectFolder([string] $Directory) {
    foreach ($file in @('main.py', 'requirements.txt', 'operator_stub\__main__.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Directory $file) -PathType Leaf)) { return $false }
    }
    return $true
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

function Find-ProjectPython {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    if ($env:OPERATOR_PYTHON) {
        $override = Get-Command $env:OPERATOR_PYTHON -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($override) { $candidates.Add($override.Source) }
        else { $candidates.Add($env:OPERATOR_PYTHON) }
    }
    $candidates.Add((Join-Path $root '.runtime\python-3.13.16\python.exe'))
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
        if ($working) { return $working }
    }
    return $null
}

function Install-ProjectPython {
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -eq 'ARM64') {
        $installerName = 'python-3.13.16-arm64.exe'
        $expectedHash = '696e2226062c6ec3622c13f143d28336a856968518e49cb4f4c62513215a4f5d'
    } elseif ($architecture -eq 'AMD64') {
        $installerName = 'python-3.13.16-amd64.exe'
        $expectedHash = 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b'
    } else {
        throw 'This project needs 64-bit Windows 10 or 11.'
    }
    $runtime = Join-Path $root '.runtime\python-3.13.16'
    $downloads = Join-Path $root '.runtime\downloads'
    [void] (New-Item -ItemType Directory -Path $downloads -Force)
    $installer = Join-Path $downloads $installerName
    $url = 'https://www.python.org/ftp/python/3.13.16/' + $installerName
    Write-Host '[2/3] Downloading Python 3.13.16 from python.org (about 30 MB)...'
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
    $installerLog = Join-Path $root 'python-install.log'
    $installArguments = @(
        '/quiet', '/norestart', 'InstallAllUsers=0',
        ('TargetDir="{0}"' -f $runtime),
        'Include_pip=1', 'Include_launcher=0', 'InstallLauncherAllUsers=0',
        'PrependPath=0', 'AppendPath=0', 'AssociateFiles=0', 'Shortcuts=0',
        'Include_test=0', 'Include_doc=0', 'Include_tcltk=0', 'Include_dev=0',
        'Include_debug=0', 'Include_symbols=0', 'Include_freethreaded=0',
        '/log', ('"{0}"' -f $installerLog)
    )
    $installation = Start-Process -FilePath $installer -ArgumentList $installArguments -PassThru -Wait
    if ($installation.ExitCode -notin @(0, 3010)) {
        throw "Python installer returned $($installation.ExitCode). See python-install.log."
    }
    $python = Find-ProjectPython
    if (-not $python) {
        if ($installation.ExitCode -eq 3010) {
            throw 'Python installation requires a Windows restart. Restart and run this file again.'
        }
        throw 'Python was installed but could not start. See python-install.log.'
    }
    return $python
}

try {
    Set-Location -LiteralPath $root
    Start-Transcript -LiteralPath $log -Force | Out-Null
    $transcriptStarted = $true
    Write-Host 'Operator Complex - automatic setup and launch'
    Write-Host "Project: $root"
    if (-not (Test-ProjectFolder $root)) {
        throw 'Put run-windows.bat in the existing project folder, next to main.py and requirements.txt.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'This project needs 64-bit Windows 10 or 11.'
    }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONNOUSERSITE = '1'
    # Only this launch process is affected; ignore another Python environment.
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
    Write-Host '[1/3] Checking Python and the project environment...'
    $venv = Join-Path $root '.venv'
    $python = Test-ProjectPython (Join-Path $venv 'Scripts\python.exe')
    if ((Test-Path -LiteralPath $venv) -and (-not $python)) {
        $backup = '.venv-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
        Rename-Item -LiteralPath $venv -NewName $backup
        Write-Host "Old environment was preserved as $backup. A new one will be created."
    }
    if (-not $python) { $python = Find-ProjectPython }
    if (-not $python) { $python = Install-ProjectPython }
    else { Write-Host '[2/3] A compatible Python is already available.' }
    Write-Host "Python: $python"
    Write-Host '[3/3] Preparing the local environment and dependencies...'
    if (-not (Test-Path -LiteralPath $venv)) {
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project .venv. See the error above.' }
    }
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    Write-Host 'Installing dependencies from requirements.txt...'
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install requirements.txt. Check the Internet connection and the error above.' }
    Write-Host 'Starting main.py. Keep this window open while the app is running.'
    & $venvPython (Join-Path $root 'main.py')
    $launcherExit = $LASTEXITCODE
    if ($launcherExit -ne 0) {
        Write-Host "Application/setup returned code $launcherExit. Details are above and in setup-windows.log."
    }
} catch {
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    if ($transcriptStarted) { Write-Host "Log: $log" }
    else { Write-Host 'Setup stopped before the log could be created.' }
    $launcherExit = 1
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
exit $launcherExit
