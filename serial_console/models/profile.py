"""Profiles: a named set of command buttons plus its own send history."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .command import CommandButton
from .errors import ValidationError

MAX_PROFILE_NAME_LENGTH = 64
DEFAULT_BUTTON_COUNT = 20


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass(slots=True)
class Profile:
    """A device-specific working set.

    A profile owns its command buttons and its send history so that switching
    from, say, ``ESP32`` to ``Motor Controller`` swaps the whole context at
    once instead of mixing unrelated commands together.
    """

    name: str = "Default"
    description: str = ""
    buttons: list[CommandButton] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    id: str = field(default_factory=_new_id)

    # ------------------------------------------------------------------
    def validate(self) -> None:
        if not self.name.strip():
            raise ValidationError("Profile name cannot be empty.")
        if len(self.name) > MAX_PROFILE_NAME_LENGTH:
            raise ValidationError(
                f"Profile name is too long (maximum {MAX_PROFILE_NAME_LENGTH} characters)."
            )
        for button in self.buttons:
            button.validate()

    def duplicate(self, new_name: str | None = None) -> Profile:
        """Deep copy the profile, including buttons, under a fresh identity."""
        clone = Profile(
            id=_new_id(),
            name=(new_name or f"{self.name} copy")[:MAX_PROFILE_NAME_LENGTH],
            description=self.description,
            buttons=[b.duplicate(name_suffix="") for b in self.buttons],
            history=list(self.history),
        )
        return clone

    def find(self, button_id: str) -> CommandButton | None:
        for button in self.buttons:
            if button.id == button_id:
                return button
        return None

    def index_of(self, button_id: str) -> int:
        for index, button in enumerate(self.buttons):
            if button.id == button_id:
                return index
        raise ValidationError("That command button no longer exists.")

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "buttons": [b.to_dict() for b in self.buttons],
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Profile:
        if not isinstance(data, Mapping):
            raise ValidationError("Profile entry is not an object.")
        raw_buttons: Sequence[Any] = data.get("buttons") or []
        buttons: list[CommandButton] = []
        if isinstance(raw_buttons, Sequence) and not isinstance(raw_buttons, (str, bytes)):
            for entry in raw_buttons:
                try:
                    buttons.append(CommandButton.from_dict(entry))
                except ValidationError:
                    # Skip an individual broken button rather than losing the
                    # whole profile.
                    continue
        raw_history = data.get("history") or []
        history = [str(item) for item in raw_history if isinstance(item, (str, int, float))]
        name = str(data.get("name") or "Profile").strip() or "Profile"
        return cls(
            id=str(data.get("id") or "") or _new_id(),
            name=name[:MAX_PROFILE_NAME_LENGTH],
            description=str(data.get("description") or ""),
            buttons=buttons,
            history=history,
        )

    # ------------------------------------------------------------------
    @classmethod
    def create_default(
        cls, name: str = "Default", button_count: int = DEFAULT_BUTTON_COUNT
    ) -> Profile:
        """Create a profile pre-populated with blank, ready to edit buttons."""
        buttons = [
            CommandButton(name=f"Command {index + 1}", command="")
            for index in range(max(0, button_count))
        ]
        return cls(name=name, buttons=buttons)

    @classmethod
    def create_starter(cls) -> Profile:
        """The profile a first-time user sees: a few worked examples."""
        examples: Iterable[tuple[str, str]] = (
            ("Status", "AT+STATUS"),
            ("Read Sensor", "AT+READ_SENSOR"),
            ("Read Temp", "AT+TEMP?"),
            ("Version", "AT+GMR"),
            ("Motor ON", "MOTOR ON"),
            ("Motor OFF", "MOTOR OFF"),
            ("LED ON", "LED ON"),
            ("LED OFF", "LED OFF"),
            ("Reset", "AT+RST"),
            ("Ping", "AT"),
        )
        buttons = [CommandButton(name=name, command=command) for name, command in examples]
        buttons.extend(
            CommandButton(name=f"Command {index}", command="")
            for index in range(len(buttons) + 1, DEFAULT_BUTTON_COUNT + 1)
        )
        return cls(name="Default", description="Example AT-style commands", buttons=buttons)
