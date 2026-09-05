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
$Root      = Split-Path -Parent $ScriptDir
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
    if (-not (Test-Path $BuildVenv)) {
        & $python[0] @($python[1..($python.Count - 1)]) -m venv $BuildVenv
    }
    $venvPython = Join-Path $BuildVenv 'Scripts\python.exe'
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r (Join-Path $Root 'requirements-dev.txt') --quiet

    Write-Step '[3/5] Running tests'
    if ($SkipTests) {
        Write-Host 'Skipped (-SkipTests).' -ForegroundColor Yellow
    }
    else {
        $env:QT_QPA_PLATFORM = 'offscreen'
        & $venvPython -m pytest tests -q
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
