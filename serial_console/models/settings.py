"""Application settings models and the root :class:`AppConfig` document."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .enums import (
    DataBits,
    DisplayMode,
    FlowControl,
    LineEnding,
    Parity,
    StopBits,
    Theme,
    enum_value,
)
from .errors import ValidationError
from .profile import Profile

#: Bumped whenever the on-disk layout changes in a non-additive way.
SCHEMA_VERSION = 1

MIN_BAUD = 50
MAX_BAUD = 20_000_000
MIN_BUFFER_BYTES = 64 * 1024
MAX_BUFFER_BYTES = 512 * 1024 * 1024
MIN_HISTORY = 0
MAX_HISTORY = 10_000


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


@dataclass(slots=True)
class SerialSettings:
    """Everything needed to open a port."""

    port: str = ""
    baud_rate: int = 115200
    data_bits: DataBits = DataBits.EIGHT
    parity: Parity = Parity.NONE
    stop_bits: StopBits = StopBits.ONE
    flow_control: FlowControl = FlowControl.NONE
    read_timeout_s: float = 0.05
    write_timeout_s: float = 2.0
    dtr: bool = True
    rts: bool = True

    def validate(self) -> None:
        if not self.port.strip():
            raise ValidationError("Select a COM port before connecting.")
        if not MIN_BAUD <= self.baud_rate <= MAX_BAUD:
            raise ValidationError(
                f"Baud rate must be between {MIN_BAUD} and {MAX_BAUD}."
            )
        if self.data_bits is DataBits.FIVE and self.stop_bits is StopBits.TWO:
            raise ValidationError("5 data bits cannot be combined with 2 stop bits.")
        if self.data_bits is not DataBits.FIVE and self.stop_bits is StopBits.ONE_POINT_FIVE:
            raise ValidationError("1.5 stop bits is only valid with 5 data bits.")

    def describe(self) -> str:
        """Short human readable summary, e.g. ``COM5 @ 115200 8N1``."""
        parity_char = str(enum_value(self.parity))[0].upper()
        stop = str(enum_value(self.stop_bits)).rstrip("0").rstrip(".") or "1"
        return (
            f"{self.port or '-'} @ {self.baud_rate} "
            f"{enum_value(self.data_bits)}{parity_char}{stop}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "baud_rate": self.baud_rate,
            "data_bits": enum_value(self.data_bits),
            "parity": enum_value(self.parity),
            "stop_bits": enum_value(self.stop_bits),
            "flow_control": enum_value(self.flow_control),
            "read_timeout_s": self.read_timeout_s,
            "write_timeout_s": self.write_timeout_s,
            "dtr": self.dtr,
            "rts": self.rts,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> SerialSettings:
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            port=str(data.get("port") or ""),
            baud_rate=_clamp(_as_int(data.get("baud_rate"), 115200), MIN_BAUD, MAX_BAUD),
            data_bits=DataBits.coerce(data.get("data_bits"), DataBits.EIGHT),
            parity=Parity.coerce(data.get("parity"), Parity.NONE),
            stop_bits=StopBits.coerce(data.get("stop_bits"), StopBits.ONE),
            flow_control=FlowControl.coerce(data.get("flow_control"), FlowControl.NONE),
            read_timeout_s=float(data.get("read_timeout_s") or 0.05),
            write_timeout_s=float(data.get("write_timeout_s") or 2.0),
            dtr=_as_bool(data.get("dtr"), True),
            rts=_as_bool(data.get("rts"), True),
        )


@dataclass(slots=True)
class TerminalSettings:
    """Presentation and memory policy for the receive pane."""

    show_timestamp: bool = True
    auto_scroll: bool = True
    max_buffer_bytes: int = 5 * 1024 * 1024
    display_mode: DisplayMode = DisplayMode.ASCII
    line_ending: LineEnding = LineEnding.LF
    echo_tx: bool = True
    hex_bytes_per_line: int = 16
    encoding: str = "utf-8"

    def validate(self) -> None:
        if not MIN_BUFFER_BYTES <= self.max_buffer_bytes <= MAX_BUFFER_BYTES:
            raise ValidationError("Terminal buffer size is outside the supported range.")
        if not 1 <= self.hex_bytes_per_line <= 64:
            raise ValidationError("Hex bytes per line must be between 1 and 64.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "show_timestamp": self.show_timestamp,
            "auto_scroll": self.auto_scroll,
            "max_buffer_bytes": self.max_buffer_bytes,
            "display_mode": enum_value(self.display_mode),
            "line_ending": enum_value(self.line_ending),
            "echo_tx": self.echo_tx,
            "hex_bytes_per_line": self.hex_bytes_per_line,
            "encoding": self.encoding,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> TerminalSettings:
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            show_timestamp=_as_bool(data.get("show_timestamp"), True),
            auto_scroll=_as_bool(data.get("auto_scroll"), True),
            max_buffer_bytes=_clamp(
                _as_int(data.get("max_buffer_bytes"), 5 * 1024 * 1024),
                MIN_BUFFER_BYTES,
                MAX_BUFFER_BYTES,
            ),
            display_mode=DisplayMode.coerce(data.get("display_mode"), DisplayMode.ASCII),
            line_ending=LineEnding.coerce(data.get("line_ending"), LineEnding.LF),
            echo_tx=_as_bool(data.get("echo_tx"), True),
            hex_bytes_per_line=_clamp(_as_int(data.get("hex_bytes_per_line"), 16), 1, 64),
            encoding=str(data.get("encoding") or "utf-8"),
        )


@dataclass(slots=True)
class AppearanceSettings:
    theme: Theme = Theme.DARK
    font_family: str = ""
    """Empty means "pick the best available monospace font at runtime"."""
    font_size: int = 10
    line_spacing: int = 118
    """Terminal line height as a percentage of the font's natural height.

    Dense log output is markedly easier to scan with a little air between the
    lines, and Persian or Arabic text — whose ascenders and descenders reach
    further than Latin — needs it to avoid clipping."""
    command_button_columns: int = 2
    window_geometry: str = ""
    window_state: str = ""

    def validate(self) -> None:
        if not 6 <= self.font_size <= 32:
            raise ValidationError("Font size must be between 6 and 32.")
        if not 100 <= self.line_spacing <= 200:
            raise ValidationError("Line spacing must be between 100 % and 200 %.")
        if not 1 <= self.command_button_columns <= 8:
            raise ValidationError("Command button columns must be between 1 and 8.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": enum_value(self.theme),
            "font_family": self.font_family,
            "font_size": self.font_size,
            "line_spacing": self.line_spacing,
            "command_button_columns": self.command_button_columns,
            "window_geometry": self.window_geometry,
            "window_state": self.window_state,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> AppearanceSettings:
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            theme=Theme.coerce(data.get("theme"), Theme.DARK),
            font_family=str(data.get("font_family") or ""),
            font_size=_clamp(_as_int(data.get("font_size"), 10), 6, 32),
            line_spacing=_clamp(_as_int(data.get("line_spacing"), 118), 100, 200),
            command_button_columns=_clamp(
                _as_int(data.get("command_button_columns"), 2), 1, 8
            ),
            window_geometry=str(data.get("window_geometry") or ""),
            window_state=str(data.get("window_state") or ""),
        )


@dataclass(slots=True)
class CommandSettings:
    history_limit: int = 200
    confirm_delete: bool = True
    flash_on_send: bool = True

    def validate(self) -> None:
        if not MIN_HISTORY <= self.history_limit <= MAX_HISTORY:
            raise ValidationError(
                f"History size must be between {MIN_HISTORY} and {MAX_HISTORY}."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "history_limit": self.history_limit,
            "confirm_delete": self.confirm_delete,
            "flash_on_send": self.flash_on_send,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> CommandSettings:
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            history_limit=_clamp(_as_int(data.get("history_limit"), 200), MIN_HISTORY, MAX_HISTORY),
            confirm_delete=_as_bool(data.get("confirm_delete"), True),
            flash_on_send=_as_bool(data.get("flash_on_send"), True),
        )


@dataclass(slots=True)
class AppConfig:
    """Root configuration document persisted as a single JSON file."""

    schema_version: int = SCHEMA_VERSION
    serial: SerialSettings = field(default_factory=SerialSettings)
    terminal: TerminalSettings = field(default_factory=TerminalSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    commands: CommandSettings = field(default_factory=CommandSettings)
    profiles: list[Profile] = field(default_factory=list)
    active_profile_id: str = ""

    # ------------------------------------------------------------------
    def validate(self) -> None:
        self.terminal.validate()
        self.appearance.validate()
        self.commands.validate()
        for profile in self.profiles:
            profile.validate()

    def active_profile(self) -> Profile:
        """Return the active profile, healing a dangling reference."""
        if not self.profiles:
            self.profiles.append(Profile.create_starter())
        for profile in self.profiles:
            if profile.id == self.active_profile_id:
                return profile
        self.active_profile_id = self.profiles[0].id
        return self.profiles[0]

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "serial": self.serial.to_dict(),
            "terminal": self.terminal.to_dict(),
            "appearance": self.appearance.to_dict(),
            "commands": self.commands.to_dict(),
            "active_profile_id": self.active_profile_id,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AppConfig:
        if not isinstance(data, Mapping):
            raise ValidationError("Configuration root is not an object.")
        raw_profiles = data.get("profiles") or []
        profiles: list[Profile] = []
        if isinstance(raw_profiles, list):
            for entry in raw_profiles:
                try:
                    profiles.append(Profile.from_dict(entry))
                except ValidationError:
                    continue
        if not profiles:
            profiles = [Profile.create_starter()]
        config = cls(
            schema_version=_as_int(data.get("schema_version"), SCHEMA_VERSION),
            serial=SerialSettings.from_dict(data.get("serial")),
            terminal=TerminalSettings.from_dict(data.get("terminal")),
            appearance=AppearanceSettings.from_dict(data.get("appearance")),
            commands=CommandSettings.from_dict(data.get("commands")),
            profiles=profiles,
            active_profile_id=str(data.get("active_profile_id") or ""),
        )
        config.active_profile()  # heal dangling active-profile pointer
        return config

    @classmethod
    def create_default(cls) -> AppConfig:
        profile = Profile.create_starter()
        return cls(profiles=[profile], active_profile_id=profile.id)
