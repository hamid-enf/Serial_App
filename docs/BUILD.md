# Building the Windows executable

Everything needed to turn this source tree into a shippable `.exe`, in four
different ways, plus what to do when each of them goes wrong.

**Cheat sheet** — on a Windows machine with Python installed:

```bat
git clone https://github.com/hamid-enf/Serial_App.git
cd Serial_App
git checkout arena/01a06db5-serial-app
packaging\build.bat /installer
```

Twelve minutes later (three, on the second run) you have all three artefacts in
`packaging\dist\` and `packaging\installer_output\`.

---

## Contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Route A — `build.bat` (recommended)](#route-a--buildbat-recommended)
- [Route B — `build.ps1` (PowerShell)](#route-b--buildps1-powershell)
- [Route C — PyInstaller by hand](#route-c--pyinstaller-by-hand)
- [Route D — GitHub Actions (no Windows PC needed)](#route-d--github-actions-no-windows-pc-needed)
- [Verifying the build](#verifying-the-build)
- [Which file do I give people?](#which-file-do-i-give-people)
- [Troubleshooting](#troubleshooting)
- [Changing the version, name or icon](#changing-the-version-name-or-icon)
- [What the build actually does](#what-the-build-actually-does)

---

## What you get

| Artefact | Path | Size | Use it when |
| --- | --- | --- | --- |
| **Portable single file** | `packaging\dist\SerialCommandConsole-portable.exe` | ~45 MB | You want one file to copy to a USB stick or send to a colleague. Starts ~1–3 s slower because it unpacks itself to a temp folder on every launch. |
| **Folder build** | `packaging\dist\SerialCommandConsole\SerialCommandConsole.exe` | ~110 MB (folder) | Fastest startup. This is what the installer ships. Do not send just the `.exe` — it needs the whole folder. |
| **Installer** | `packaging\installer_output\SerialCommandConsole-1.0.0-setup.exe` | ~45 MB | Proper install: Start-menu entry, optional desktop icon, uninstaller. Needs Inno Setup 6 at build time. |

All three come from the same PyInstaller spec, so they behave identically.

---

## Before you start

| Requirement | Notes |
| --- | --- |
| **Windows** | PyInstaller **cannot cross-compile**. A Windows `.exe` must be built on Windows (or by [Route D](#route-d--github-actions-no-windows-pc-needed), which rents one from GitHub). A VM or Windows Sandbox is fine. |
| **Python 3.10 – 3.13**, 64-bit | From [python.org](https://www.python.org/downloads/windows/). Tick **“Add python.exe to PATH”** in the installer. Avoid the Microsoft Store build if you can — it sandboxes paths in ways that confuse virtual environments. |
| **~3 GB free disk** | The build virtual environment, PyInstaller's work directory and the outputs. |
| **Internet access** | First run only, to download PySide6 (~90 MB) and PyInstaller. |
| **Inno Setup 6** *(optional)* | Only for the installer: <https://jrsoftware.org/isdl.php>. Install with defaults; the script finds it automatically. |
| **Git** *(optional)* | Or download the ZIP from GitHub and extract it. |

Nothing else. You do **not** need Visual Studio, a compiler, or admin rights.

---

## Route A — `build.bat` (recommended)

```bat
cd path\to\Serial_App
packaging\build.bat
```

That is the whole thing. It is safe to re-run and never touches your system
Python: it creates its own `.build-venv` in the repository.

### Options

| Flag | Effect |
| --- | --- |
| *(none)* | Create/reuse `.build-venv`, install dependencies, run the 411 tests, freeze, self-test the result |
| `/installer` | Also compile the Inno Setup installer |
| `/skiptests` | Skip `pytest` — saves ~25 s, and the only way to build while a test is failing |
| `/usevenv` | Build inside the virtual environment you already activated, instead of `.build-venv` |
| `/clean` | Delete `.build-venv` first. Use after upgrading Python or when dependencies look broken |
| `/?` | Print the usage summary |

Flags combine: `packaging\build.bat /clean /installer`.

### What you should see

```
=== [1/5] Locating Python ===========================================
Project root: C:\src\Serial_App
Found: "python"
Python 3.12.4

=== [2/5] Preparing build environment ===============================
Creating "C:\...\Serial_App\.build-venv" ...
Installing dependencies (this can take a few minutes the first time) ...

=== [3/5] Running tests =============================================
411 passed in 24.02s

=== [4/5] Freezing with PyInstaller =================================
...
Verifying the frozen application ...
SELFTEST OK: ENF Serial Command Console 1.0.0

=== [5/5] Installer =================================================
Successful compile (3.21 sec). Resulting Setup program filename is:
C:\...\packaging\installer_output\SerialCommandConsole-1.0.0-setup.exe

=====================================================================
 Build complete.
   Portable single file : packaging\dist\SerialCommandConsole-portable.exe
   Folder build         : packaging\dist\SerialCommandConsole\SerialCommandConsole.exe
   Installer            : packaging\installer_output\
=====================================================================
```

**Every stage stops the build on failure** and prints why, so a green
“Build complete” means the tests passed *and* the frozen application started.

Timing: 8–15 minutes the first time (downloading PySide6 dominates), 2–4
minutes afterwards.

---

## Route B — `build.ps1` (PowerShell)

Identical behaviour, PowerShell-native flags and coloured output:

```powershell
cd path\to\Serial_App
.\packaging\build.ps1                       # tests + freeze
.\packaging\build.ps1 -Installer            # + Inno Setup
.\packaging\build.ps1 -SkipTests -Clean     # rebuild from scratch, no tests
.\packaging\build.ps1 -UseVenv              # use the activated venv
```

If PowerShell refuses to run it:

```
.\packaging\build.ps1 : File ... cannot be loaded because running scripts is disabled on this system.
```

then either allow local scripts for your account (persistent, safe):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

or bypass the policy for this one command:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build.ps1 -Installer
```

---

## Route C — PyInstaller by hand

Use this when a script misbehaves, when you want to see each step, or when you
are integrating the build into something else.

```bat
:: 1. a clean environment
python -m venv .venv
.venv\Scripts\activate

:: 2. dependencies (PySide6-Essentials, pyserial, pytest, pyinstaller, ruff, mypy)
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

:: 3. prove the source is healthy before freezing it
set QT_QPA_PLATFORM=offscreen
pytest tests -q
set QT_QPA_PLATFORM=

:: 4. freeze
pyinstaller packaging\serial_console.spec --noconfirm ^
    --distpath packaging\dist --workpath packaging\build

:: 5. prove the frozen build is healthy too
packaging\dist\SerialCommandConsole\SerialCommandConsole.exe --selftest

:: 6. optional installer
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Useful switches for the spec:

```bat
:: build only the folder version (skips the slow one-file pass)
set SERIAL_CONSOLE_ONEFILE=0
pyinstaller packaging\serial_console.spec --noconfirm

:: see what PyInstaller is actually collecting
pyinstaller packaging\serial_console.spec --noconfirm --log-level DEBUG
```

---

## Route D — GitHub Actions (no Windows PC needed)

The project is developed on Linux, so this is the *supported* path to an
executable: a real `windows-latest` runner does the freeze for you.

**Step 1 — turn the workflows on.** They ship in `packaging/ci/` rather than
`.github/workflows/`, because GitHub refuses workflow files pushed by an
automation account without the `workflows` permission. From a normal clone:

```bash
mkdir -p .github/workflows
git mv packaging/ci/build-windows.yml packaging/ci/tests.yml .github/workflows/
git commit -m "Enable CI workflows"
git push
```

**Step 2 — run it.** The build triggers on every push, or on demand:
**Actions → Build Windows executable → Run workflow**.

**Step 3 — download.** Open the finished run and take the artefacts from the
bottom of the page:

- `SerialCommandConsole-portable-exe`
- `SerialCommandConsole-windows-folder` (zip of the folder build)
- `SerialCommandConsole-installer`

**Step 4 — publish a release.** Tag it, and the same three files are attached
to a GitHub release automatically:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow runs the full test suite and executes the frozen binary with
`--selftest` before uploading anything, so a missing hidden import fails the
build instead of reaching a user.

---

## Verifying the build

```bat
:: 1. wires up the whole application headlessly and exits 0 — catches missing
::    data files and hidden imports (the build scripts do this for you)
packaging\dist\SerialCommandConsole-portable.exe --selftest

:: 2. version and branding
packaging\dist\SerialCommandConsole-portable.exe --version

:: 3. the real thing, with a fake port so no hardware is required
packaging\dist\SerialCommandConsole-portable.exe --demo

:: 4. if something misbehaves, get the log on the console
packaging\dist\SerialCommandConsole-portable.exe --verbose
```

Right-click the `.exe` → **Properties → Details** should show
`ENF Serial Command Console`, version `1.0.0` and the ENF company name — that
metadata comes from `packaging/version_info.txt`.

---

## Which file do I give people?

| Situation | Send them |
| --- | --- |
| A colleague who just wants to try it | `SerialCommandConsole-portable.exe` — one file, no install, no admin rights |
| A lab PC, or anything permanent | The installer: Start-menu entry, uninstaller, no temp-folder unpacking |
| A machine where nothing may be installed | The folder build, zipped — extract and run |
| A USB stick that should carry its settings with it | Portable exe **plus an empty `portable.txt` next to it**. The app then stores its config in `data\` beside the exe instead of `%APPDATA%` |

**About the SmartScreen warning.** The executable is unsigned, so Windows shows
*“Windows protected your PC”* the first time. Click **More info → Run anyway**.
The only real fix is an OV/EV code-signing certificate (~€200/year); until then,
warn the people you send it to, or point them at the GitHub release page so they
can see where the file came from.

---

## Troubleshooting

### Quick index

| Symptom | Jump to |
| --- | --- |
| `No Python 3.10 or newer could be found` | [1](#1-no-python-310-or-newer-could-be-found) |
| `No suitable Python runtime found` (from `py`) | [2](#2-no-suitable-python-runtime-found) |
| `Could not open requirements file: requirements-dev.txt` | [3](#3-could-not-open-requirements-file) |
| `pip install` fails / times out / SSL error | [4](#4-dependency-installation-fails) |
| `Could not find a version that satisfies PySide6-Essentials` | [5](#5-no-pyside6-wheel-for-your-python) |
| `ERROR: tests failed - build aborted` | [6](#6-tests-fail) |
| PyInstaller finishes but the exe does nothing | [7](#7-the-exe-starts-and-immediately-exits) |
| `Failed to execute script 'main'` / `ModuleNotFoundError` | [8](#8-modulenotfounderror-in-the-frozen-build) |
| `could not find or load the Qt platform plugin "windows"` | [9](#9-qt-platform-plugin-windows-not-found) |
| Antivirus deletes the exe | [10](#10-antivirus-quarantines-the-executable) |
| `WARNING: Inno Setup 6 not found` | [11](#11-inno-setup-not-found) |
| `Access is denied` / `PermissionError` during the build | [12](#12-access-is-denied-while-building) |
| Path too long, or the repo lives in OneDrive | [13](#13-long-paths-onedrive-and-non-ascii-folders) |
| The portable exe takes seconds to start | [14](#14-the-portable-exe-is-slow-to-start) |
| Build succeeded yesterday, fails today | [15](#15-a-stale-build-venv) |
| The icon is wrong or missing | [16](#16-the-icon-does-not-appear) |
| It works here but not on another PC | [17](#17-works-on-the-build-machine-only) |

---

### 1. `No Python 3.10 or newer could be found`

The script tried the active virtual environment, `python`, `python3`, `py -3`
and the default install locations, and none of them answered.

```bat
python --version
```

- **“not recognized as an internal or external command”** → Python is not on
  `PATH`. Reinstall from [python.org](https://www.python.org/downloads/windows/)
  with **“Add python.exe to PATH”** ticked, then open a **new** terminal (an
  existing one keeps the old `PATH`).
- **It opens the Microsoft Store** → Windows' app-execution alias is
  intercepting. **Settings → Apps → Advanced app settings → App execution
  aliases** → turn off both `python.exe` and `python3.exe` entries.
- **It prints 3.9 or older** → install a newer Python; the project needs 3.10+.
- **You already have a working venv** → activate it and use
  `packaging\build.bat /usevenv`.

### 2. `No suitable Python runtime found`

The `py` launcher exists but has no runtime registered — typical after an
uninstall, or with a Store install. Harmless: the scripts try `py` **last**
precisely because of this. If you hit it running a command by hand, use
`python` instead of `py`, or reinstall Python and let it register itself.

### 3. `Could not open requirements file`

```
ERROR: Could not open requirements file: [Errno 2] No such file or directory: 'requirements-dev.txt'
ERROR: dependency installation failed. Check your internet connection.
```

The file is in the repository, so this is almost never a download problem —
the build is looking in the wrong folder, or the working copy is incomplete.
(Older build scripts printed the misleading "check your internet connection"
line for this failure, and could mis-detect the project folder. `git pull`
first — the current ones print the folder they picked and refuse to run if it
is wrong.)

**Check what the script thinks the project is.** Current versions print it:

```
=== [1/5] Locating the project ======================================
Project root: D:\Serial_App
```

If that says anything else — `D:\`, `D:\..`, your home folder — the root was
misdetected. Confirm the file really is there and point the script at it:

```bat
cd /d D:\Serial_App
dir requirements-dev.txt

set SERIAL_CONSOLE_ROOT=D:\Serial_App
packaging\build.bat /installer
```

PowerShell: `$env:SERIAL_CONSOLE_ROOT = 'D:\Serial_App'`.

**If `dir` says the file is not found**, the checkout is incomplete — a partial
ZIP download, or a clone made before the file existed:

```bat
git pull
git status
```

**Then delete any virtual environment created in the wrong place**, because the
next run will happily reuse it:

```bat
rmdir /s /q D:\.build-venv
```

**Install by hand as a last resort** — the build only needs five packages:

```bat
.build-venv\Scripts\python -m pip install PySide6-Essentials pyserial pytest pyinstaller
packaging\build.bat /installer
```

Current scripts also fall back automatically: if `requirements-dev.txt` is
missing they install `requirements.txt` plus `pytest` and `pyinstaller`, and
they refuse to run at all unless the folder they picked contains
`pyproject.toml` and `serial_console\`.

### 4. Dependency installation fails

```
ERROR: installing the build dependencies failed (...).
       Re-running without --quiet so the real error is visible:
```

The script re-runs the install verbosely so you can read the actual failure.
To reproduce it yourself:

```bat
.build-venv\Scripts\python -m pip install -r requirements-dev.txt
```

- **Timeout / connection reset** → a proxy or a filtered network. Set
  `HTTPS_PROXY` / `HTTP_PROXY`, or use a mirror:
  `pip install -r requirements-dev.txt -i https://pypi.org/simple`
- **`SSLError` / `CERTIFICATE_VERIFY_FAILED`** → corporate TLS interception.
  Point pip at your company's root certificate:
  `pip config set global.cert C:\path\to\corp-root.pem`
- **Disk full** → PySide6 needs ~400 MB unpacked.

### 5. No PySide6 wheel for your Python

```
ERROR: Could not find a version that satisfies the requirement PySide6-Essentials
```

Qt wheels lag new Python releases by a few months, and there are no wheels for
32-bit Windows or Windows-on-ARM. Check what you are running:

```bat
python -c "import sys, platform; print(sys.version, platform.machine())"
```

Install Python **3.12** (the version CI uses) alongside whatever you have and
build with `/clean`, or on ARM run the x64 build under emulation.

### 6. Tests fail

The build aborts on purpose: freezing a broken source tree only moves the
problem into an `.exe`. See the failure first:

```bat
set QT_QPA_PLATFORM=offscreen
.build-venv\Scripts\python -m pytest tests -q
```

If the failures are unrelated to what you are doing and you need a binary now:

```bat
packaging\build.bat /skiptests
```

…but treat that as a temporary measure, and please open an issue with the
output — the suite is green on Linux and Windows in CI.

### 7. The exe starts and immediately exits

The application is built with `console=False`, so a crash before the window
appears leaves no trace. Get the story out of it:

```bat
packaging\dist\SerialCommandConsole-portable.exe --selftest
packaging\dist\SerialCommandConsole-portable.exe --verbose
```

Run those **from `cmd`, not by double-clicking**, so the exit code and any
message are visible. The log file is at
`%APPDATA%\SerialCommandConsole\logs\serial_console.log`.

Nine times out of ten it is a missing hidden import — see the next entry.

### 8. `ModuleNotFoundError` in the frozen build

Something imported at runtime that PyInstaller could not see statically. Add it
to `hiddenimports` in `packaging/serial_console.spec`:

```python
hiddenimports = [
    "serial.serialwin32",
    ...
    "your.missing.module",
]
```

The spec already lists every pyserial backend and collects all of
`serial_console`. If it is a *data* file rather than a module, add it to
`datas` in the same file and read it through
`serial_console.config.paths.resource_dir()`, which understands PyInstaller's
`_MEIPASS`.

### 9. Qt platform plugin "windows" not found

```
This application failed to start because no Qt platform plugin could be initialized.
```

- **Only in a hand-rolled PyInstaller command** → use the provided spec; it
  collects the Qt plugins.
- **`QT_QPA_PLATFORM` is set to `offscreen` in your environment** → the test
  step exports it. Open a new terminal, or `set QT_QPA_PLATFORM=`.
- **On the target machine only** → install the
  [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).
  Qt needs it; Windows 10/11 usually has it already, fresh installs sometimes
  do not.

### 10. Antivirus quarantines the executable

PyInstaller output is a self-extracting binary, which heuristic scanners
dislike. The spec already sets `upx=False` because UPX compression makes this
dramatically worse.

- Add `packaging\dist` to your scanner's exclusions while building.
- Upload the result to [VirusTotal](https://www.virustotal.com/) — one or two
  no-name engines flagging it is the normal false-positive pattern.
- The permanent fix is code signing.
- Prefer the **installer** for distribution: signed or not, it is a far more
  familiar shape to both users and scanners than a bare 45 MB exe.

### 11. Inno Setup not found

```
WARNING: Inno Setup 6 not found - skipping the installer.
```

Install it from <https://jrsoftware.org/isdl.php>. The script looks in
`%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe`, `%ProgramFiles%\Inno Setup 6\ISCC.exe`
and on `PATH`. For a non-standard location, call it directly:

```bat
"D:\Tools\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Note the installer packages the **folder build**, so `packaging\dist\SerialCommandConsole\`
must exist first — always freeze before compiling the installer.

### 12. `Access is denied` while building

- **The app is still running** — close every instance, including one started by
  a previous `--selftest`.
- **The exe is open in Explorer's preview pane** or being scanned. Close the
  window, wait a few seconds, retry.
- **`.build-venv` is locked** by an activated shell. Deactivate it, or use
  `/usevenv` to build inside it deliberately.

### 13. Long paths, OneDrive and non-ASCII folders

PyInstaller writes deeply nested temporary paths and can hit the 260-character
limit. Symptoms are odd `FileNotFoundError`s for files that clearly exist.

- Build from a short path: `C:\src\Serial_App`, not
  `C:\Users\…\OneDrive\مستندات\Projects\…`.
- Avoid OneDrive-synced folders entirely — the sync client locks files mid-build.
- Or enable long paths once, as administrator:
  ```powershell
  New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
    -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
  ```

### 14. The portable exe is slow to start

Expected: a one-file build unpacks ~110 MB into `%TEMP%` on every launch, which
costs 1–3 seconds (more with an aggressive antivirus). It is the price of a
single file.

Use the **folder build** or the **installer** when startup time matters — they
start in well under a second.

### 15. A stale `.build-venv`

The build worked yesterday and fails today with weird import or version errors,
typically after upgrading Python or switching branches:

```bat
packaging\build.bat /clean
```

That deletes `.build-venv` and rebuilds it from `requirements-dev.txt`.

### 16. The icon does not appear

- Windows caches icons aggressively. Rename the exe, or clear the cache:
  `ie4uinit.exe -show`.
- Confirm `resources\icons\app.ico` exists — the spec only sets an icon when it
  does, and silently builds without one otherwise. Regenerate it with
  `python scripts\make_icon.py`.
- A multi-resolution `.ico` (16/32/48/256 px) is required for a clean look in
  every Explorer view; `make_icon.py` produces exactly that.

### 17. Works on the build machine only

- Missing **VC++ 2015-2022 Redistributable (x64)** on the target — see [9](#9-qt-platform-plugin-windows-not-found).
- You copied `SerialCommandConsole.exe` out of the **folder** build without the
  rest of the folder. Send the portable exe or the whole folder.
- The target is 32-bit Windows or ARM; these builds are x64.
- The user has no write access to `%APPDATA%` — drop a `portable.txt` beside
  the exe so it stores its configuration in `data\` instead.

---

## Changing the version, name or icon

Bumping the version touches four files — keep them in step:

| File | What to change |
| --- | --- |
| `pyproject.toml` | `version = "1.0.0"` |
| `serial_console/__init__.py` | `__version__` |
| `packaging/version_info.txt` | `filevers`, `prodvers`, `FileVersion`, `ProductVersion` (Windows file properties) |
| `packaging/installer.iss` | `#define AppVersion` (drives the installer's filename and Add/Remove entry) |

`tests/test_branding.py` checks that these agree, so a mismatch fails the test
suite before it can ship.

Other knobs:

- **Application name** — `APP_NAME` in the spec and `#define AppName` in
  `installer.iss`. **Do not change `APP_SLUG`** in `serial_console/__init__.py`:
  it is the config folder name, and existing installations would lose their
  settings. A test enforces this.
- **Icon** — replace `resources/icons/app.ico` (or regenerate:
  `python scripts\make_icon.py`).
- **Ship extra files** — add them to `datas` in the spec and read them via
  `serial_console.config.paths.resource_dir()`.
- **Smaller build** — the spec already excludes the Qt modules the app never
  touches (~45 MB instead of 120 MB+). If you add a feature that needs one of
  them, remove it from `excludes`.

---

## What the build actually does

So that nothing here is a black box:

1. **Locates an interpreter** — the active venv, then `python`, `python3`,
   `py -3`, then the standard install directories. `py` is last on purpose
   (see [2](#2-no-suitable-python-runtime-found)).
2. **Creates `.build-venv`** in the repository root and installs
   `requirements-dev.txt` into it. Your system Python is never modified.
3. **Runs the test suite** with `QT_QPA_PLATFORM=offscreen`, so Qt needs no
   display. A failure aborts the build.
4. **Runs PyInstaller** against `packaging/serial_console.spec`, which:
   - bundles `resources/themes` and `resources/icons` as data,
   - force-includes the pyserial backends and every `serial_console` submodule
     (`hiddenimports`),
   - excludes ~35 unused Qt modules and the scientific stack,
   - disables UPX (antivirus false positives),
   - stamps the Windows version resource and the icon,
   - emits **both** the folder build (`COLLECT`) and the one-file build.
5. **Self-tests the frozen application** (`--selftest` constructs the whole app
   headlessly and exits 0), so packaging mistakes fail here rather than on a
   user's desk.
6. **Optionally compiles the installer** with Inno Setup, packaging the folder
   build plus `README.md` and `LICENSE`, creating Start-menu and optional
   desktop shortcuts, and registering a proper uninstaller.

The CI workflow (`packaging/ci/build-windows.yml`) performs exactly these steps
on `windows-latest`, which is why a local build and a CI build produce the same
artefacts.
