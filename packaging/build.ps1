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

.EXAMPLE
    .\packaging\build.ps1
.EXAMPLE
    .\packaging\build.ps1 -Installer
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Installer,
    [switch]$Clean
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
    $python = $null
    foreach ($candidate in @('py', 'python')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            $argsList = if ($candidate -eq 'py') { @('-3') } else { @() }
            $version = & $cmd.Source @argsList -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
            if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]'3.10') {
                $python = @($cmd.Source) + $argsList
                break
            }
        }
    }
    if (-not $python) {
        throw 'Python 3.10 or newer was not found on PATH. Install it from https://www.python.org/downloads/windows/'
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
        & $venvPython -m pytest tests -q
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed - build aborted.' }
    }

    Write-Step '[4/5] Freezing with PyInstaller'
    foreach ($dir in @($DistDir, $WorkDir)) {
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    }
    & $venvPython -m PyInstaller (Join-Path $ScriptDir 'serial_console.spec') `
        --noconfirm --distpath $DistDir --workpath $WorkDir
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

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
