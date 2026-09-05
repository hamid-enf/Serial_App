"""Command button management (CRUD, reordering, reset) for a single profile.

The store is a thin, fully testable façade over ``Profile.buttons``.  It owns
all invariants — unique ids, valid indices, never leaving the list in a
half-updated state — so the UI layer only has to render.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from ..models.command import CommandButton
from ..models.errors import ValidationError
from ..models.profile import Profile

MAX_BUTTONS = 1000
"""Upper bound so a corrupt file cannot try to build a million widgets."""


class CommandStore:
    """Mutating operations on the command buttons of one profile."""

    def __init__(self, profile: Profile) -> None:
        self._profile = profile

    # ------------------------------------------------------------------
    @property
    def profile(self) -> Profile:
        return self._profile

    def set_profile(self, profile: Profile) -> None:
        self._profile = profile

    @property
    def buttons(self) -> list[CommandButton]:
        return self._profile.buttons

    def __len__(self) -> int:
        return len(self._profile.buttons)

    def __iter__(self):
        return iter(self._profile.buttons)

    def get(self, button_id: str) -> CommandButton:
        button = self._profile.find(button_id)
        if button is None:
            raise ValidationError("That command button no longer exists.")
        return button

    def index_of(self, button_id: str) -> int:
        return self._profile.index_of(button_id)

    # ------------------------------------------------------------------
    # Create / update / delete
    # ------------------------------------------------------------------
    def add(self, button: CommandButton | None = None, index: int | None = None) -> CommandButton:
        """Insert a button (defaults to a blank one appended at the end)."""
        if len(self._profile.buttons) >= MAX_BUTTONS:
            raise ValidationError(
                f"A profile can hold at most {MAX_BUTTONS} command buttons."
            )
        new_button = button or CommandButton(name=self._next_default_name())
        new_button.validate()
        if index is None or index >= len(self._profile.buttons):
            self._profile.buttons.append(new_button)
        else:
            self._profile.buttons.insert(max(0, index), new_button)
        return new_button

    def add_many(self, count: int) -> list[CommandButton]:
        """Append ``count`` blank buttons; used by "add row" style actions."""
        created: list[CommandButton] = []
        for _ in range(max(0, count)):
            created.append(self.add())
        return created

    def update(self, button_id: str, updated: CommandButton) -> CommandButton:
        """Replace the button in place, keeping its position and identity."""
        updated.validate()
        index = self.index_of(button_id)
        updated.id = button_id
        self._profile.buttons[index] = updated
        return updated

    def remove(self, button_id: str) -> CommandButton:
        index = self.index_of(button_id)
        return self._profile.buttons.pop(index)

    def duplicate(self, button_id: str) -> CommandButton:
        """Copy a button and insert the copy directly after the original."""
        index = self.index_of(button_id)
        clone = self._profile.buttons[index].duplicate()
        self._profile.buttons.insert(index + 1, clone)
        return clone

    def reset(self, button_id: str) -> CommandButton:
        """Clear a button back to a blank slot without changing its position."""
        index = self.index_of(button_id)
        blank = CommandButton(name=f"Command {index + 1}")
        blank.id = button_id
        self._profile.buttons[index] = blank
        return blank

    def rename(self, button_id: str, name: str) -> CommandButton:
        button = self.get(button_id)
        previous = button.name
        button.name = name.strip()
        try:
            button.validate()
        except ValidationError:
            button.name = previous
            raise
        return button

    def set_enabled(self, button_id: str, enabled: bool) -> CommandButton:
        button = self.get(button_id)
        button.enabled = bool(enabled)
        return button

    # ------------------------------------------------------------------
    # Ordering
    # ------------------------------------------------------------------
    def move(self, button_id: str, new_index: int) -> int:
        """Move a button to ``new_index`` (clamped) and return the final index."""
        current = self.index_of(button_id)
        button = self._profile.buttons.pop(current)
        target = max(0, min(new_index, len(self._profile.buttons)))
        self._profile.buttons.insert(target, button)
        return target

    def move_by(self, button_id: str, delta: int) -> int:
        return self.move(button_id, self.index_of(button_id) + delta)

    def reorder(self, ordered_ids: Sequence[str]) -> None:
        """Apply a full ordering; ids not listed keep their relative order."""
        by_id = {b.id: b for b in self._profile.buttons}
        if len(set(ordered_ids)) != len(ordered_ids):
            raise ValidationError("Duplicate command button in the new ordering.")
        result: list[CommandButton] = []
        for button_id in ordered_ids:
            button = by_id.pop(button_id, None)
            if button is not None:
                result.append(button)
        result.extend(b for b in self._profile.buttons if b.id in by_id)
        self._profile.buttons[:] = result

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------
    def ensure_count(self, count: int) -> None:
        """Grow or shrink to exactly ``count`` buttons (shrink drops the tail)."""
        count = max(0, min(MAX_BUTTONS, int(count)))
        while len(self._profile.buttons) < count:
            self.add()
        if len(self._profile.buttons) > count:
            del self._profile.buttons[count:]

    def clear_all(self) -> None:
        self._profile.buttons.clear()

    def replace_all(self, buttons: Iterable[CommandButton]) -> None:
        new_list = list(buttons)
        for button in new_list:
            button.validate()
        self._profile.buttons[:] = new_list

    def find_where(self, predicate: Callable[[CommandButton], bool]) -> list[CommandButton]:
        return [b for b in self._profile.buttons if predicate(b)]

    def active_auto_send(self) -> list[CommandButton]:
        return [b for b in self._profile.buttons if b.enabled and b.auto_send.enabled]

    # ------------------------------------------------------------------
    def _next_default_name(self) -> str:
        existing = {b.name for b in self._profile.buttons}
        index = len(self._profile.buttons) + 1
        while f"Command {index}" in existing:
            index += 1
        return f"Command {index}"
