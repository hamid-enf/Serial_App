"""Shared pytest fixtures."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from serial_console.config.store import ConfigStore
from serial_console.models.command import CommandButton
from serial_console.models.profile import Profile
from serial_console.models.settings import AppConfig, SerialSettings


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the app at a throwaway data directory for every test."""
    home = tmp_path / "appdata"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SERIAL_CONSOLE_HOME", str(home))
    return home


@pytest.fixture()
def serial_settings() -> SerialSettings:
    return SerialSettings(port="COM_TEST", baud_rate=115200)


@pytest.fixture()
def profile() -> Profile:
    return Profile(
        name="Test",
        buttons=[
            CommandButton(name="Status", command="AT+STATUS"),
            CommandButton(name="Temp", command="AT+TEMP?"),
            CommandButton(name="Blank", command=""),
        ],
    )


@pytest.fixture()
def config(profile: Profile) -> AppConfig:
    cfg = AppConfig(profiles=[profile], active_profile_id=profile.id)
    return cfg


# ----------------------------------------------------------------------
# Qt fixtures. Importing PySide6 lazily keeps the non-GUI suite runnable on a
# machine where Qt's shared libraries are missing.
# ----------------------------------------------------------------------
@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session — Qt allows no more."""
    pytest.importorskip("PySide6", reason="PySide6 is required for the GUI tests")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, tmp_path: Path):
    """A fully wired MainWindow backed by a loopback port and a temp config."""
    from serial_console.transport.loopback import LoopbackTransport
    from serial_console.ui.main_window import MainWindow

    store = ConfigStore(tmp_path / "config.json")
    win = MainWindow(AppConfig.create_default(), store, transport=LoopbackTransport(echo=True))
    win.resize(1200, 800)
    yield win
    win.service.shutdown()
    win.deleteLater()
    _process_events()


def _process_events() -> None:
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.processEvents()


def spin(milliseconds: int = 120) -> None:
    """Run the Qt event loop for a while so timers can fire."""
    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + milliseconds / 1000.0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()


def spin_until(predicate, timeout_ms: int = 3000) -> bool:
    """Pump the event loop until ``predicate()`` is true or the timeout expires."""
    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    QCoreApplication.processEvents()
    return predicate()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gui: tests that need a QApplication")
    # Qt must never try to reach a real display in CI.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
