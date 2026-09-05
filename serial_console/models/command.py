"""The :class:`CommandButton` model and its auto-repeat specification."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .enums import LineEnding, enum_value
from .errors import ValidationError

#: Guard rail for auto repeat.  Anything faster floods both the UART and the
#: GUI event loop without being useful.
MIN_AUTO_SEND_INTERVAL_MS = 20
MAX_AUTO_SEND_INTERVAL_MS = 24 * 60 * 60 * 1000

MAX_NAME_LENGTH = 64
MAX_COMMAND_LENGTH = 4096
MAX_DESCRIPTION_LENGTH = 512


def _new_id() -> str:
    return uuid.uuid4().hex


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


@dataclass(slots=True)
class AutoSendSpec:
    """Auto-repeat configuration for a single command button."""

    enabled: bool = False
    interval_ms: int = 1000

    def validate(self) -> None:
        if self.interval_ms < MIN_AUTO_SEND_INTERVAL_MS:
            raise ValidationError(
                f"Auto-send interval must be at least {MIN_AUTO_SEND_INTERVAL_MS} ms."
            )
        if self.interval_ms > MAX_AUTO_SEND_INTERVAL_MS:
            raise ValidationError("Auto-send interval must be 24 hours or less.")

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "interval_ms": self.interval_ms}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> AutoSendSpec:
        if not isinstance(data, Mapping):
            return cls()
        spec = cls(
            enabled=_as_bool(data.get("enabled"), False),
            interval_ms=_as_int(data.get("interval_ms"), 1000),
        )
        # Repair rather than reject: a hand-edited file should not stop the app.
        spec.interval_ms = max(
            MIN_AUTO_SEND_INTERVAL_MS, min(MAX_AUTO_SEND_INTERVAL_MS, spec.interval_ms)
        )
        return spec


@dataclass(slots=True)
class CommandButton:
    """A single user-defined command button.

    Ordering is *positional*: the index inside :attr:`Profile.buttons` is the
    single source of truth for layout order.  Storing an explicit ``position``
    field as well would create two representations of the same fact that can
    drift apart after a drag-and-drop reorder.
    """

    name: str = "Command"
    command: str = ""
    line_ending: LineEnding | None = None
    """Per-button override; ``None`` means "use the global line ending"."""
    hex_mode: bool = False
    """When true, :attr:`command` is parsed as hex bytes instead of text."""
    enabled: bool = True
    description: str = ""
    color: str | None = None
    auto_send: AutoSendSpec = field(default_factory=AutoSendSpec)
    id: str = field(default_factory=_new_id)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Raise :class:`ValidationError` if the button is not usable."""
        name = self.name.strip()
        if not name:
            raise ValidationError("Button name cannot be empty.")
        if len(name) > MAX_NAME_LENGTH:
            raise ValidationError(
                f"Button name is too long (maximum {MAX_NAME_LENGTH} characters)."
            )
        if len(self.command) > MAX_COMMAND_LENGTH:
            raise ValidationError(
                f"Command is too long (maximum {MAX_COMMAND_LENGTH} characters)."
            )
        if len(self.description) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(
                f"Description is too long (maximum {MAX_DESCRIPTION_LENGTH} characters)."
            )
        if self.hex_mode:
            # Imported lazily to keep the model layer import-light.
            from ..core.codec import parse_hex

            parse_hex(self.command)  # raises ValidationError with a clear message
        self.auto_send.validate()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def resolved_line_ending(self, fallback: LineEnding) -> LineEnding:
        """Return the effective line ending for this button."""
        return self.line_ending if self.line_ending is not None else fallback

    def duplicate(self, name_suffix: str = " copy") -> CommandButton:
        """Return a deep copy with a fresh identity."""
        return replace(
            self,
            id=_new_id(),
            name=f"{self.name}{name_suffix}"[:MAX_NAME_LENGTH],
            auto_send=AutoSendSpec(
                enabled=self.auto_send.enabled, interval_ms=self.auto_send.interval_ms
            ),
        )

    def is_blank(self) -> bool:
        """True when the button carries no command payload."""
        return not self.command.strip()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "line_ending": None if self.line_ending is None else enum_value(self.line_ending),
            "hex_mode": self.hex_mode,
            "enabled": self.enabled,
            "description": self.description,
            "color": self.color,
            "auto_send": self.auto_send.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CommandButton:
        """Build a button from untrusted JSON data, repairing bad fields."""
        if not isinstance(data, Mapping):
            raise ValidationError("Command button entry is not an object.")
        raw_ending = data.get("line_ending")
        line_ending: LineEnding | None
        if raw_ending in (None, "", "inherit", "default"):
            line_ending = None
        else:
            line_ending = LineEnding.coerce(raw_ending, LineEnding.NONE)
        name = _as_str(data.get("name"), "Command").strip() or "Command"
        return cls(
            id=_as_str(data.get("id")) or _new_id(),
            name=name[:MAX_NAME_LENGTH],
            command=_as_str(data.get("command"))[:MAX_COMMAND_LENGTH],
            line_ending=line_ending,
            hex_mode=_as_bool(data.get("hex_mode"), False),
            enabled=_as_bool(data.get("enabled"), True),
            description=_as_str(data.get("description"))[:MAX_DESCRIPTION_LENGTH],
            color=data.get("color") if isinstance(data.get("color"), str) else None,
            auto_send=AutoSendSpec.from_dict(data.get("auto_send")),
        )
