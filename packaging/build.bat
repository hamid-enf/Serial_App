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
REM
REM  Set SERIAL_CONSOLE_ROOT to override the detected repository root.
REM
REM  Note: this script deliberately does NOT use delayed expansion, so
REM  that it survives repository paths containing an exclamation mark.
REM  Variables assigned inside a block are therefore never read inside
REM  the same block; labels are used instead.
REM ===================================================================
setlocal

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

REM Resolve "<script dir>\.." to a canonical absolute path. Fall back to
REM the current directory, and then to an explicit override, so that an
REM odd invocation cannot silently point the build at the wrong folder.
set "ROOT="
for %%I in ("%SCRIPT_DIR%..") do set "ROOT=%%~fI"
if defined SERIAL_CONSOLE_ROOT for %%I in ("%SERIAL_CONSOLE_ROOT%") do set "ROOT=%%~fI"

call :is_repo "%ROOT%"
if not errorlevel 1 goto root_ok
set "ROOT=%CD%"
call :is_repo "%ROOT%"
if not errorlevel 1 goto root_ok
goto bad_root

:root_ok
pushd "%ROOT%" || exit /b 1
set "BUILD_VENV=%ROOT%\.build-venv"
set "REQ_DEV=%ROOT%\requirements-dev.txt"
set "REQ=%ROOT%\requirements.txt"
set "DIST=%SCRIPT_DIR%dist"
set "WORK=%SCRIPT_DIR%build"

echo.
echo === [1/5] Locating Python ===========================================
echo Project root: %ROOT%
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
    goto fail
)
echo Found: "%PY_EXE%" %PY_ARGS%
"%PY_EXE%" %PY_ARGS% --version

echo.
echo === [2/5] Preparing build environment ===============================
if "%USE_ACTIVE_VENV%"=="1" goto use_active
if "%CLEAN%"=="1" if exist "%BUILD_VENV%" rmdir /s /q "%BUILD_VENV%"
if exist "%BUILD_VENV%\Scripts\python.exe" goto venv_ready
echo Creating "%BUILD_VENV%" ...
"%PY_EXE%" %PY_ARGS% -m venv "%BUILD_VENV%"
if errorlevel 1 (
    echo ERROR: could not create the build virtual environment at
    echo        "%BUILD_VENV%".
    echo        Check that the drive has free space and is writable.
    goto fail
)
:venv_ready
set "VPY=%BUILD_VENV%\Scripts\python.exe"
goto have_vpy

:use_active
if not defined VIRTUAL_ENV (
    echo ERROR: /usevenv was passed but no virtual environment is active.
    goto fail
)
set "VPY=%VIRTUAL_ENV%\Scripts\python.exe"
echo Building inside the active environment: %VIRTUAL_ENV%

:have_vpy
if not exist "%VPY%" (
    echo ERROR: python.exe not found at "%VPY%".
    goto fail
)

set "REQ_USED=%REQ_DEV%"
if not exist "%REQ_DEV%" goto no_req_dev
echo Installing dependencies from "%REQ_DEV%" ^(a few minutes the first time^) ...
"%VPY%" -m pip install --upgrade pip --quiet
"%VPY%" -m pip install -r "%REQ_DEV%" --quiet
if errorlevel 1 goto pip_failed
goto deps_ok

:no_req_dev
echo WARNING: "%REQ_DEV%" is missing from this working copy.
echo          Installing the build dependencies explicitly instead.
echo          ^(Run "git pull" to restore the file.^)
set "REQ_USED=explicit package list"
"%VPY%" -m pip install --upgrade pip --quiet
if not exist "%REQ%" goto no_req_at_all
"%VPY%" -m pip install -r "%REQ%" --quiet
if errorlevel 1 goto pip_failed
"%VPY%" -m pip install "pytest>=8.0" "pyinstaller>=6.6" --quiet
if errorlevel 1 goto pip_failed
goto deps_ok

:no_req_at_all
"%VPY%" -m pip install "PySide6-Essentials>=6.6,<7" "pyserial>=3.5,<4" "pytest>=8.0" "pyinstaller>=6.6" --quiet
if errorlevel 1 goto pip_failed

:deps_ok

echo.
echo === [3/5] Running tests =============================================
if "%SKIP_TESTS%"=="1" goto tests_done
if not exist "%ROOT%\tests" (
    echo WARNING: no tests directory at "%ROOT%\tests" - skipping.
    goto tests_done
)
set "QT_QPA_PLATFORM=offscreen"
"%VPY%" -m pytest "%ROOT%\tests" -q
if errorlevel 1 (
    echo.
    echo ERROR: tests failed - build aborted.
    echo        Re-run with /skiptests to build anyway.
    goto fail
)
set "QT_QPA_PLATFORM="
:tests_done

echo.
echo === [4/5] Freezing with PyInstaller =================================
if not exist "%SCRIPT_DIR%serial_console.spec" (
    echo ERROR: "%SCRIPT_DIR%serial_console.spec" is missing.
    echo        This working copy is incomplete - run "git pull".
    goto fail
)
if exist "%DIST%" rmdir /s /q "%DIST%"
if exist "%WORK%" rmdir /s /q "%WORK%"
"%VPY%" -m PyInstaller "%SCRIPT_DIR%serial_console.spec" ^
    --noconfirm ^
    --distpath "%DIST%" ^
    --workpath "%WORK%"
if errorlevel 1 (
    echo ERROR: PyInstaller failed. The traceback above has the details;
    echo        docs\BUILD.md explains the common causes.
    goto fail
)

echo Verifying the frozen application ...
"%DIST%\SerialCommandConsole\SerialCommandConsole.exe" --selftest
if errorlevel 1 (
    echo ERROR: the frozen application failed its self-test.
    echo        See docs\BUILD.md, "ModuleNotFoundError in the frozen build".
    goto fail
)

echo.
echo === [5/5] Installer =================================================
if "%BUILD_INSTALLER%"=="1" goto do_installer
echo Skipped ^(pass /installer to build it^).
goto installer_done
:do_installer
set "ISCC="
set "PF86=%ProgramFiles(x86)%"
if not exist "%PF86%" set "PF86=%ProgramFiles%"
if exist "%PF86%\Inno Setup 6\ISCC.exe"          set "ISCC=%PF86%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    where iscc >nul 2>&1 && set "ISCC=iscc"
)
if not defined ISCC (
    echo WARNING: Inno Setup 6 not found - skipping the installer.
    echo          Get it from https://jrsoftware.org/isdl.php
    goto installer_done
)
"%ISCC%" "%SCRIPT_DIR%installer.iss"
if errorlevel 1 goto fail
:installer_done

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
:pip_failed
echo.
echo ERROR: installing the build dependencies failed ^(%REQ_USED%^).
echo        Re-running without --quiet so the real error is visible:
echo.
if exist "%REQ_DEV%" "%VPY%" -m pip install -r "%REQ_DEV%"
if not exist "%REQ_DEV%" if exist "%REQ%" "%VPY%" -m pip install -r "%REQ%"
echo.
echo   Common causes:
echo     * No internet access, or a proxy:  set HTTPS_PROXY=http://host:port
echo     * Corporate TLS interception:      pip config set global.cert C:\path\root.pem
echo     * No PySide6 wheel for this Python ^(needs 3.10-3.13, 64-bit x86^)
echo     * Not enough disk space ^(PySide6 unpacks to ~400 MB^)
echo   See docs\BUILD.md for the full list.
goto fail

REM ------------------------------------------------------------------
:bad_root
echo ERROR: could not locate the repository.
echo.
echo   Script directory  : %SCRIPT_DIR%
echo   Derived root      : %ROOT%
echo   Current directory : %CD%
echo.
echo   Neither of those contains pyproject.toml and serial_console\,
echo   so this is not a Serial_App working copy - or the copy is
echo   incomplete.
echo.
echo   Fixes:
echo     * cd into the repository and run:  packaging\build.bat
echo     * or point the script at it:
echo         set SERIAL_CONSOLE_ROOT=D:\Serial_App
echo         packaging\build.bat
echo     * if files really are missing, restore them with:  git pull
exit /b 1

:fail
popd
endlocal
exit /b 1

REM ------------------------------------------------------------------
REM :is_repo <directory>   exit code 0 when it looks like this project
REM ------------------------------------------------------------------
:is_repo
if "%~1"=="" exit /b 1
if not exist "%~1\pyproject.toml" exit /b 1
if not exist "%~1\serial_console\__init__.py" exit /b 1
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
echo   /clean       delete .build-venv and start from scratch
echo.
echo Set SERIAL_CONSOLE_ROOT to override the detected repository root.
exit /b 0
