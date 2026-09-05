"""Where the application keeps its files.

Honours ``SERIAL_CONSOLE_HOME`` (useful for a truly portable USB-stick install
and for tests) before falling back to the per-user location for the platform.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import APP_SLUG

ENV_HOME = "SERIAL_CONSOLE_HOME"
PORTABLE_MARKER = "portable.txt"


def _portable_root() -> Path | None:
    """Return the executable directory when a portable marker sits next to it.

    Dropping an empty ``portable.txt`` beside ``SerialCommandConsole.exe`` makes
    the app keep its settings in that folder, so the whole tool can live on a
    USB stick and leave no trace on the host machine.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    marker = exe_dir / PORTABLE_MARKER
    try:
        if marker.exists():
            return exe_dir / "data"
    except OSError:
        return None
    return None


def app_data_dir() -> Path:
    """Root directory for configuration and logs."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()

    portable = _portable_root()
    if portable is not None:
        return portable

    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / APP_SLUG
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_SLUG
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / APP_SLUG


def config_file() -> Path:
    return app_data_dir() / "config.json"


def log_dir() -> Path:
    return app_data_dir() / "logs"


def profiles_dir() -> Path:
    """Default folder offered by the profile import/export dialogs."""
    return app_data_dir() / "profiles"


def ensure_dirs() -> Path:
    """Create the data directories, returning the root."""
    root = app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
    profiles_dir().mkdir(parents=True, exist_ok=True)
    return root


def resource_dir() -> Path:
    """Locate bundled resources both in source runs and inside PyInstaller."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "resources"
    return Path(__file__).resolve().parent.parent.parent / "resources"
