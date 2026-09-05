<#
.SYNOPSIS
    Build Serial Command Console into a Windows executable.

.DESCRIPTION
    Creates an isolated virtual environment, installs the pinned
    dependencies, runs the test suite and freezes the app with PyInstaller.
    Artefacts are written to packaging\dist.

.PARAMETER SkipTests
    Do not run pytest before freezing.

.PARAMETER Installer
    Also compile the Inno Setup installer (requires Inno Setup 6).

.PARAMETER Clean
    Delete the build virtual environment first.

.PARAMETER UseVenv
    Build inside the currently activated virtual environment instead of
    creating packaging's own .build-venv.

.EXAMPLE
    .\packaging\build.ps1
.EXAMPLE
    .\packaging\build.ps1 -Installer
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Installer,
    [switch]$Clean,
    [switch]$UseVenv
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Resolve the repository root, and prove it. An odd invocation must not
# silently point the build at the wrong folder: fall back to the current
# directory, then to an explicit SERIAL_CONSOLE_ROOT override.
function Test-RepoRoot([string]$Path) {
    if (-not $Path) { return $false }
    return (Test-Path (Join-Path $Path 'pyproject.toml')) -and
           (Test-Path (Join-Path $Path 'serial_console\__init__.py'))
}

$Root = $null
foreach ($candidate in @($env:SERIAL_CONSOLE_ROOT, (Split-Path -Parent $ScriptDir), (Get-Location).Path)) {
    if (Test-RepoRoot $candidate) { $Root = (Resolve-Path $candidate).Path; break }
}
if (-not $Root) {
    throw (@'
Could not locate the repository.

  Script directory  : {0}
  Current directory : {1}

  Neither contains pyproject.toml and serial_console\, so this is not a
  Serial_App working copy - or the copy is incomplete.

  Fixes:
    * cd into the repository, then run:  .\packaging\build.ps1
    * or point the script at it:
        $env:SERIAL_CONSOLE_ROOT = 'D:\Serial_App'; .\packaging\build.ps1
    * if files really are missing, restore them with:  git pull
'@ -f $ScriptDir, (Get-Location).Path)
}

$BuildVenv = Join-Path $Root '.build-venv'
$DistDir   = Join-Path $ScriptDir 'dist'
$WorkDir   = Join-Path $ScriptDir 'build'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "=== $Text " -ForegroundColor Cyan -NoNewline
    Write-Host ('=' * [Math]::Max(0, 66 - $Text.Length)) -ForegroundColor Cyan
}

Push-Location $Root
try {
    Write-Step '[1/5] Locating Python'
    Write-Host ("Project root: {0}" -f $Root)
    # The py launcher is tried last: it is frequently installed without any
    # registered runtime (Microsoft Store installs, leftovers from an
    # uninstall) and then fails with "No suitable Python runtime found" even
    # though python.exe works perfectly well.
    $candidates = @()
    if ($env:VIRTUAL_ENV) {
        $candidates += , @((Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'), @())
    }
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += , @($cmd.Source, @()) }
    }
    $pyCmd = Get-Command 'py' -ErrorAction SilentlyContinue
    if ($pyCmd) { $candidates += , @($pyCmd.Source, @('-3')) }
    foreach ($ver in @('313', '312', '311', '310')) {
        foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", $env:ProgramFiles)) {
            if ($base) { $candidates += , @((Join-Path $base "Python$ver\python.exe"), @()) }
        }
    }

    $python = $null
    $version = $null
    foreach ($candidate in $candidates) {
        $exe, $extra = $candidate
        if (-not (Test-Path $exe -ErrorAction SilentlyContinue) -and
            -not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $reported = & $exe @extra -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
        if ($LASTEXITCODE -eq 0 -and $reported -and [version]$reported -ge [version]'3.10') {
            $python = @($exe) + $extra
            $version = $reported
            break
        }
    }
    if (-not $python) {
        throw @'
No Python 3.10 or newer could be found.

  Tried: the active virtual environment, python, python3, py -3 and the
         default install locations.

  Fixes:
    * Install Python from https://www.python.org/downloads/windows/ and tick
      "Add python.exe to PATH" during setup.
    * Inside an activated venv, run: .\packaging\build.ps1 -UseVenv
'@
    }
    Write-Host ("Using {0} (Python {1})" -f $python[0], $version)

    Write-Step '[2/5] Preparing build environment'
    if ($Clean -and (Test-Path $BuildVenv)) {
        Remove-Item -Recurse -Force $BuildVenv
    }
    if (-not $UseVenv -and -not (Test-Path $BuildVenv)) {
        & $python[0] @($python[1..($python.Count - 1)]) -m venv $BuildVenv
    }
    $venvPython = Join-Path $BuildVenv 'Scripts\python.exe'
    if ($UseVenv) {
        if (-not $env:VIRTUAL_ENV) { throw '-UseVenv was passed but no virtual environment is active.' }
        $venvPython = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
        Write-Host ("Building inside the active environment: {0}" -f $env:VIRTUAL_ENV)
    }
    if (-not (Test-Path $venvPython)) { throw "python.exe not found at $venvPython" }

    & $venvPython -m pip install --upgrade pip --quiet

    # Absolute paths: never rely on the current directory for these.
    $reqDev = Join-Path $Root 'requirements-dev.txt'
    $req    = Join-Path $Root 'requirements.txt'
    if (Test-Path $reqDev) {
        Write-Host ("Installing dependencies from {0} ..." -f $reqDev)
        & $venvPython -m pip install -r $reqDev --quiet
    }
    elseif (Test-Path $req) {
        Write-Warning "$reqDev is missing from this working copy - installing the build tools explicitly. Run 'git pull' to restore it."
        & $venvPython -m pip install -r $req --quiet
        if ($LASTEXITCODE -eq 0) { & $venvPython -m pip install 'pytest>=8.0' 'pyinstaller>=6.6' --quiet }
    }
    else {
        Write-Warning 'No requirements files found - installing the known dependency set.'
        & $venvPython -m pip install 'PySide6-Essentials>=6.6,<7' 'pyserial>=3.5,<4' 'pytest>=8.0' 'pyinstaller>=6.6' --quiet
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Warning 'Dependency installation failed. Re-running without --quiet so the real error is visible:'
        if (Test-Path $reqDev) { & $venvPython -m pip install -r $reqDev }
        elseif (Test-Path $req) { & $venvPython -m pip install -r $req }
        throw @'
Installing the build dependencies failed.

  Common causes:
    * No internet access, or a proxy:  $env:HTTPS_PROXY = 'http://host:port'
    * Corporate TLS interception:      pip config set global.cert C:\path\root.pem
    * No PySide6 wheel for this Python (needs 3.10-3.13, 64-bit x86)
    * Not enough disk space (PySide6 unpacks to ~400 MB)

  docs\BUILD.md has the full list.
'@
    }

    Write-Step '[3/5] Running tests'
    if ($SkipTests) {
        Write-Host 'Skipped (-SkipTests).' -ForegroundColor Yellow
    }
    else {
        $env:QT_QPA_PLATFORM = 'offscreen'
        & $venvPython -m pytest (Join-Path $Root 'tests') -q
        $testExit = $LASTEXITCODE
        Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        if ($testExit -ne 0) { throw 'Tests failed - build aborted. Re-run with -SkipTests to build anyway.' }
    }

    Write-Step '[4/5] Freezing with PyInstaller'
    foreach ($dir in @($DistDir, $WorkDir)) {
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    }
    & $venvPython -m PyInstaller (Join-Path $ScriptDir 'serial_console.spec') `
        --noconfirm --distpath $DistDir --workpath $WorkDir
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    Write-Host 'Verifying the frozen application ...'
    & (Join-Path $DistDir 'SerialCommandConsole\SerialCommandConsole.exe') --selftest
    if ($LASTEXITCODE -ne 0) { throw 'The frozen application failed its self-test.' }

    Write-Step '[5/5] Installer'
    if ($Installer) {
        $iscc = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $iscc) {
            $iscc = (Get-Command iscc -ErrorAction SilentlyContinue)?.Source
        }
        if (-not $iscc) {
            Write-Warning 'Inno Setup 6 not found - skipping. Get it from https://jrsoftware.org/isdl.php'
        }
        else {
            & $iscc (Join-Path $ScriptDir 'installer.iss')
            if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }
        }
    }
    else {
        Write-Host 'Skipped (pass -Installer to build it).' -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host 'Build complete.' -ForegroundColor Green
    Get-ChildItem -Path $DistDir -Filter '*.exe' -Recurse |
        ForEach-Object {
            '  {0,-46} {1,8:N1} MB' -f $_.FullName.Substring($Root.Length + 1), ($_.Length / 1MB)
        }
    if ($Installer) {
        Write-Host ('  Installer: ' + (Join-Path $ScriptDir 'installer_output'))
    }
}
finally {
    Pop-Location
}
