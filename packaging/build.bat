@echo off
REM ===================================================================
REM  ENF Serial Command Console - Windows build script
REM
REM  Usage (from anywhere):   packaging\build.bat
REM
REM  Creates a throwaway virtual environment, installs the pinned
REM  dependencies, runs the test suite and freezes the application with
REM  PyInstaller. Output lands in packaging\dist\.
REM
REM  Options:
REM    /skiptests   do not run pytest before freezing
REM    /installer   also compile the Inno Setup installer
REM    /usevenv     build inside the currently activated virtual
REM                 environment instead of creating .build-venv
REM    /clean       delete .build-venv first
REM ===================================================================
setlocal EnableDelayedExpansion

set "SKIP_TESTS=0"
set "BUILD_INSTALLER=0"
set "USE_ACTIVE_VENV=0"
set "CLEAN=0"
:parse
if "%~1"=="" goto parsed
if /I "%~1"=="/skiptests"  set "SKIP_TESTS=1"
if /I "%~1"=="/installer"  set "BUILD_INSTALLER=1"
if /I "%~1"=="/usevenv"    set "USE_ACTIVE_VENV=1"
if /I "%~1"=="/clean"      set "CLEAN=1"
if /I "%~1"=="/?"          goto usage
if /I "%~1"=="--help"      goto usage
shift
goto parse
:parsed

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
pushd "%ROOT%" || exit /b 1
set "BUILD_VENV=%ROOT%\.build-venv"

echo.
echo === [1/5] Locating Python ===========================================
REM Try every plausible interpreter and keep the first one that actually
REM runs and reports 3.10+. The py launcher is tried LAST on purpose: it is
REM often present without any registered runtime (Microsoft Store installs,
REM or a launcher left behind by an uninstall), in which case it fails with
REM "No suitable Python runtime found" even though python.exe works fine.
set "PY_EXE="
set "PY_ARGS="

if defined VIRTUAL_ENV call :try_python "%VIRTUAL_ENV%\Scripts\python.exe" ""
call :try_python "python" ""
call :try_python "python3" ""
call :try_python "py" "-3"
call :try_python "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" ""
call :try_python "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ""
call :try_python "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" ""
call :try_python "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" ""
call :try_python "%ProgramFiles%\Python313\python.exe" ""
call :try_python "%ProgramFiles%\Python312\python.exe" ""
call :try_python "%ProgramFiles%\Python311\python.exe" ""
call :try_python "%ProgramFiles%\Python310\python.exe" ""

if not defined PY_EXE (
    echo ERROR: No Python 3.10 or newer could be found.
    echo.
    echo   Tried: the active virtual environment, python, python3, py -3,
    echo          and the default install locations.
    echo.
    echo   Fixes:
    echo     * Install Python from https://www.python.org/downloads/windows/
    echo       and tick "Add python.exe to PATH" during setup.
    echo     * If you already have Python, activate it or add it to PATH,
    echo       then run this script again.
    echo     * Inside an activated venv, run: packaging\build.bat /usevenv
    popd
    exit /b 1
)
echo Found: "%PY_EXE%" %PY_ARGS%
"%PY_EXE%" %PY_ARGS% --version

echo.
echo === [2/5] Preparing build environment ===============================
if "%USE_ACTIVE_VENV%"=="1" (
    if not defined VIRTUAL_ENV (
        echo ERROR: /usevenv was passed but no virtual environment is active.
        popd
        exit /b 1
    )
    set "VPY=%VIRTUAL_ENV%\Scripts\python.exe"
    echo Building inside the active environment: %VIRTUAL_ENV%
) else (
    if "%CLEAN%"=="1" if exist "%BUILD_VENV%" rmdir /s /q "%BUILD_VENV%"
    if not exist "%BUILD_VENV%" (
        echo Creating "%BUILD_VENV%" ...
        "%PY_EXE%" %PY_ARGS% -m venv "%BUILD_VENV%" || (
            echo ERROR: could not create the build virtual environment.
            popd
            exit /b 1
        )
    )
    set "VPY=%BUILD_VENV%\Scripts\python.exe"
)

if not exist "!VPY!" (
    echo ERROR: python.exe not found at "!VPY!".
    popd
    exit /b 1
)
echo Installing dependencies ^(this can take a few minutes the first time^) ...
"!VPY!" -m pip install --upgrade pip --quiet || (popd & exit /b 1)
"!VPY!" -m pip install -r requirements-dev.txt --quiet || (
    echo ERROR: dependency installation failed. Check your internet connection.
    popd
    exit /b 1
)

echo.
echo === [3/5] Running tests =============================================
if "%SKIP_TESTS%"=="1" (
    echo Skipped ^(/skiptests^).
) else (
    set "QT_QPA_PLATFORM=offscreen"
    "!VPY!" -m pytest tests -q || (
        echo.
        echo ERROR: tests failed - build aborted.
        echo        Re-run with /skiptests to build anyway.
        popd
        exit /b 1
    )
    set "QT_QPA_PLATFORM="
)

echo.
echo === [4/5] Freezing with PyInstaller =================================
if exist "%SCRIPT_DIR%dist"  rmdir /s /q "%SCRIPT_DIR%dist"
if exist "%SCRIPT_DIR%build" rmdir /s /q "%SCRIPT_DIR%build"
"!VPY!" -m PyInstaller "%SCRIPT_DIR%serial_console.spec" ^
    --noconfirm ^
    --distpath "%SCRIPT_DIR%dist" ^
    --workpath "%SCRIPT_DIR%build" || (
    echo ERROR: PyInstaller failed.
    popd
    exit /b 1
)

echo Verifying the frozen application ...
"%SCRIPT_DIR%dist\SerialCommandConsole\SerialCommandConsole.exe" --selftest || (
    echo ERROR: the frozen application failed its self-test.
    popd
    exit /b 1
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

REM ------------------------------------------------------------------
REM :try_python <executable> <extra args>
REM Sets PY_EXE/PY_ARGS when the candidate exists and is 3.10 or newer.
REM ------------------------------------------------------------------
:try_python
if defined PY_EXE goto :eof
if "%~1"=="" goto :eof
"%~1" %~2 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
set "PY_EXE=%~1"
set "PY_ARGS=%~2"
goto :eof

:usage
echo Usage: packaging\build.bat [/skiptests] [/installer] [/usevenv] [/clean]
echo.
echo   /skiptests   do not run pytest before freezing
echo   /installer   also compile the Inno Setup installer
echo   /usevenv     build inside the currently activated virtual environment
echo   /clean       delete .build-venv first
exit /b 0
