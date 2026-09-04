"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gui: tests that need a QApplication")
    # Qt must never try to reach a real display in CI.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
