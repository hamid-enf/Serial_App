# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Serial Command Console.

Build from the repository root (or from packaging/ — the spec resolves paths
either way):

    pyinstaller packaging/serial_console.spec --noconfirm

Produces two artefacts:

  * ``dist/SerialCommandConsole.exe``        one-file portable build
  * ``dist/SerialCommandConsole/``           one-folder build (faster startup)

Set ``SERIAL_CONSOLE_ONEFILE=0`` in the environment to build only the folder
variant, or ``=1`` (default) for both.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# ---------------------------------------------------------------- paths
try:
    SPEC_DIR = Path(SPECPATH)  # noqa: F821 - injected by PyInstaller
except NameError:  # pragma: no cover - direct execution fallback
    SPEC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SPEC_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ONEFILE = os.environ.get("SERIAL_CONSOLE_ONEFILE", "1") != "0"
APP_NAME = "SerialCommandConsole"
ICON = PROJECT_ROOT / "resources" / "icons" / "app.ico"
VERSION_FILE = SPEC_DIR / "version_info.txt"

# ------------------------------------------------------------- payload
# Ship the QSS themes and PNG icons; the app resolves them through
# ``serial_console.config.paths.resource_dir()``, which understands _MEIPASS.
datas = [
    (str(PROJECT_ROOT / "resources" / "themes"), "resources/themes"),
    (str(PROJECT_ROOT / "resources" / "icons"), "resources/icons"),
]

hiddenimports = [
    # pyserial picks its backend at import time via a string, so the Windows
    # implementation is invisible to static analysis.
    "serial.serialwin32",
    "serial.serialposix",
    "serial.serialutil",
    "serial.tools.list_ports",
    "serial.tools.list_ports_windows",
    "serial.tools.list_ports_posix",
]
hiddenimports += collect_submodules("serial_console")

# Qt modules the app never touches. Excluding them keeps the one-file build
# around 45 MB instead of 120 MB+ and shortens the unpack time on launch.
excludes = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtSvgWidgets",
    "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    # Scientific stack occasionally dragged in by site-packages.
    "matplotlib", "numpy", "scipy", "pandas", "PIL", "tkinter",
    "test", "unittest", "pydoc_data",
]

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

common = dict(
    name=APP_NAME,
    bootloader_ignore_signals=False,
    debug=False,
    strip=False,
    upx=False,  # UPX regularly trips antivirus heuristics; not worth the MBs.
    console=False,  # GUI app: no console window.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)

# ------------------------------------------------- one-folder (default)
exe_folder = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    **common,
)
coll = COLLECT(
    exe_folder,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

# ------------------------------------------------------------ one-file
if ONEFILE:
    exe_onefile = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        runtime_tmpdir=None,
        **{**common, "name": f"{APP_NAME}-portable"},
    )
