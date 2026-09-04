@echo off
REM ===================================================================
REM  Serial Command Console - Windows build script
REM
REM  Usage (from anywhere):   packaging\build.bat
REM
REM  Creates a throwaway virtual environment, installs the pinned
REM  dependencies, runs the test suite and freezes the application with
REM  PyInstaller. Output lands in packaging\dist\.
REM
REM  Options:
REM    packaging\build.bat /skiptests    do not run pytest
REM    packaging\build.bat /installer    also build the Inno Setup installer
REM ===================================================================
setlocal EnableDelayedExpansion

set "SKIP_TESTS=0"
set "BUILD_INSTALLER=0"
:parse
if "%~1"=="" goto parsed
if /I "%~1"=="/skiptests"  set "SKIP_TESTS=1"
if /I "%~1"=="/installer"  set "BUILD_INSTALLER=1"
shift
goto parse
:parsed

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
pushd "%ROOT%" || exit /b 1
set "BUILD_VENV=%ROOT%\.build-venv"

echo.
echo === [1/5] Locating Python ===========================================
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>&1 || (
        echo ERROR: Python 3.10+ was not found on PATH.
        echo        Install it from https://www.python.org/downloads/windows/
        popd & exit /b 1
    )
    set "PY=python"
)
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" || (
    echo ERROR: Python 3.10 or newer is required.
    popd & exit /b 1
)
%PY% --version

echo.
echo === [2/5] Preparing build environment ===============================
if not exist "%BUILD_VENV%" (
    %PY% -m venv "%BUILD_VENV%" || (popd & exit /b 1)
)
set "VPY=%BUILD_VENV%\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet || (popd & exit /b 1)
"%VPY%" -m pip install -r requirements-dev.txt --quiet || (popd & exit /b 1)

echo.
echo === [3/5] Running tests =============================================
if "%SKIP_TESTS%"=="1" (
    echo Skipped ^(/skiptests^).
) else (
    "%VPY%" -m pytest tests -q || (
        echo ERROR: tests failed - build aborted.
        popd & exit /b 1
    )
)

echo.
echo === [4/5] Freezing with PyInstaller =================================
if exist "%SCRIPT_DIR%dist"  rmdir /s /q "%SCRIPT_DIR%dist"
if exist "%SCRIPT_DIR%build" rmdir /s /q "%SCRIPT_DIR%build"
"%VPY%" -m PyInstaller "%SCRIPT_DIR%serial_console.spec" ^
    --noconfirm ^
    --distpath "%SCRIPT_DIR%dist" ^
    --workpath "%SCRIPT_DIR%build" || (
    echo ERROR: PyInstaller failed.
    popd & exit /b 1
)

echo.
echo === [5/5] Installer =================================================
if "%BUILD_INSTALLER%"=="1" (
    set "ISCC="
    for %%P in (
        "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
        "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    ) do if exist %%P set "ISCC=%%~P"
    if not defined ISCC (
        where iscc >nul 2>&1 && set "ISCC=iscc"
    )
    if not defined ISCC (
        echo WARNING: Inno Setup 6 not found - skipping the installer.
        echo          Get it from https://jrsoftware.org/isdl.php
    ) else (
        "!ISCC!" "%SCRIPT_DIR%installer.iss" || (popd & exit /b 1)
    )
) else (
    echo Skipped ^(pass /installer to build it^).
)

echo.
echo =====================================================================
echo  Build complete.
echo    Portable single file : packaging\dist\SerialCommandConsole-portable.exe
echo    Folder build         : packaging\dist\SerialCommandConsole\SerialCommandConsole.exe
if "%BUILD_INSTALLER%"=="1" echo    Installer            : packaging\installer_output\
echo =====================================================================
popd
endlocal
exit /b 0
