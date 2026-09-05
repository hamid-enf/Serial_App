"""Plain data models shared by every layer of the application."""

from __future__ import annotations

from .command import AutoSendSpec, CommandButton
from .enums import (
    BUFFER_PRESETS,
    COMMON_BAUD_RATES,
    DataBits,
    Direction,
    DisplayMode,
    FlowControl,
    LineEnding,
    Parity,
    StopBits,
    Theme,
)
from .errors import ConfigError, SerialConsoleError, ValidationError
from .profile import Profile
from .settings import (
    SCHEMA_VERSION,
    AppConfig,
    AppearanceSettings,
    CommandSettings,
    SerialSettings,
    TerminalSettings,
)

__all__ = [
    "BUFFER_PRESETS",
    "COMMON_BAUD_RATES",
    "SCHEMA_VERSION",
    "AppConfig",
    "AppearanceSettings",
    "AutoSendSpec",
    "CommandButton",
    "CommandSettings",
    "ConfigError",
    "DataBits",
    "Direction",
    "DisplayMode",
    "FlowControl",
    "LineEnding",
    "Parity",
    "Profile",
    "SerialConsoleError",
    "SerialSettings",
    "StopBits",
    "TerminalSettings",
    "Theme",
    "ValidationError",
]
