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
