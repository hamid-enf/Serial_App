"""Command button CRUD, ordering and validation."""

from __future__ import annotations

import pytest

from serial_console.core.commands import MAX_BUTTONS, CommandStore
from serial_console.models.command import (
    MIN_AUTO_SEND_INTERVAL_MS,
    AutoSendSpec,
    CommandButton,
)
from serial_console.models.enums import LineEnding
from serial_console.models.errors import ValidationError
from serial_console.models.profile import Profile


@pytest.fixture()
def store(profile: Profile) -> CommandStore:
    return CommandStore(profile)


class TestCrud:
    def test_add_appends_a_blank_button(self, store: CommandStore) -> None:
        before = len(store)
        button = store.add()
        assert len(store) == before + 1
        assert store.buttons[-1] is button
        assert button.is_blank()

    def test_add_at_index(self, store: CommandStore) -> None:
        button = store.add(CommandButton(name="First", command="X"), index=0)
        assert store.buttons[0] is button

    def test_add_generates_non_colliding_default_names(self, store: CommandStore) -> None:
        names = {store.add().name for _ in range(5)}
        assert len(names) == 5

    def test_update_keeps_identity_and_position(self, store: CommandStore) -> None:
        target = store.buttons[1]
        replacement = CommandButton(name="Renamed", command="NEW")
        store.update(target.id, replacement)
        assert store.buttons[1].id == target.id
        assert store.buttons[1].name == "Renamed"
        assert store.buttons[1].command == "NEW"

    def test_update_rejects_invalid_data(self, store: CommandStore) -> None:
        target = store.buttons[0]
        with pytest.raises(ValidationError):
            store.update(target.id, CommandButton(name="   ", command="X"))
        assert store.buttons[0].name == "Status"

    def test_remove(self, store: CommandStore) -> None:
        target = store.buttons[0]
        removed = store.remove(target.id)
        assert removed.id == target.id
        assert target.id not in [b.id for b in store.buttons]

    def test_remove_unknown_id_raises_a_clear_error(self, store: CommandStore) -> None:
        with pytest.raises(ValidationError, match="no longer exists"):
            store.remove("does-not-exist")

    def test_duplicate_inserts_after_the_original_with_a_new_id(
        self, store: CommandStore
    ) -> None:
        original = store.buttons[0]
        clone = store.duplicate(original.id)
        assert store.buttons[1] is clone
        assert clone.id != original.id
        assert clone.command == original.command
        assert clone.name == "Status copy"

    def test_duplicate_deep_copies_auto_send(self, store: CommandStore) -> None:
        original = store.buttons[0]
        original.auto_send = AutoSendSpec(enabled=True, interval_ms=250)
        clone = store.duplicate(original.id)
        clone.auto_send.interval_ms = 999
        assert original.auto_send.interval_ms == 250

    def test_reset_clears_content_but_keeps_slot_and_id(self, store: CommandStore) -> None:
        target = store.buttons[0]
        blank = store.reset(target.id)
        assert blank.id == target.id
        assert store.buttons[0].id == target.id
        assert blank.is_blank()
        assert blank.name == "Command 1"

    def test_rename_rolls_back_on_invalid_name(self, store: CommandStore) -> None:
        target = store.buttons[0]
        with pytest.raises(ValidationError):
            store.rename(target.id, "")
        assert store.buttons[0].name == "Status"

    def test_set_enabled(self, store: CommandStore) -> None:
        target = store.buttons[0]
        store.set_enabled(target.id, False)
        assert store.buttons[0].enabled is False


class TestOrdering:
    def test_move_to_index(self, store: CommandStore) -> None:
        last = store.buttons[-1]
        store.move(last.id, 0)
        assert store.buttons[0].id == last.id

    def test_move_clamps_out_of_range_targets(self, store: CommandStore) -> None:
        first = store.buttons[0]
        assert store.move(first.id, 999) == len(store) - 1
        assert store.move(first.id, -5) == 0

    def test_move_by_delta(self, store: CommandStore) -> None:
        target = store.buttons[0]
        assert store.move_by(target.id, 1) == 1
        assert store.move_by(target.id, -1) == 0

    def test_reorder_applies_a_full_ordering(self, store: CommandStore) -> None:
        ids = [b.id for b in store.buttons]
        store.reorder(list(reversed(ids)))
        assert [b.id for b in store.buttons] == list(reversed(ids))

    def test_reorder_keeps_unlisted_buttons(self, store: CommandStore) -> None:
        ids = [b.id for b in store.buttons]
        store.reorder([ids[2]])
        assert [b.id for b in store.buttons] == [ids[2], ids[0], ids[1]]

    def test_reorder_rejects_duplicates(self, store: CommandStore) -> None:
        target = store.buttons[0].id
        with pytest.raises(ValidationError):
            store.reorder([target, target])


class TestBulk:
    def test_ensure_count_grows_and_shrinks(self, store: CommandStore) -> None:
        store.ensure_count(20)
        assert len(store) == 20
        store.ensure_count(5)
        assert len(store) == 5

    def test_button_count_is_not_limited_to_twenty(self, store: CommandStore) -> None:
        store.ensure_count(120)
        assert len(store) == 120

    def test_hard_cap_is_enforced(self, store: CommandStore) -> None:
        store.ensure_count(MAX_BUTTONS)
        with pytest.raises(ValidationError, match="at most"):
            store.add()

    def test_active_auto_send_filters_disabled_buttons(self, store: CommandStore) -> None:
        store.buttons[0].auto_send = AutoSendSpec(enabled=True, interval_ms=500)
        store.buttons[1].auto_send = AutoSendSpec(enabled=True, interval_ms=500)
        store.buttons[1].enabled = False
        assert [b.id for b in store.active_auto_send()] == [store.buttons[0].id]


class TestValidation:
    def test_empty_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            CommandButton(name="  ", command="X").validate()

    def test_overlong_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="too long"):
            CommandButton(name="x" * 200, command="X").validate()

    def test_hex_payload_is_validated(self) -> None:
        with pytest.raises(ValidationError):
            CommandButton(name="Bad", command="ZZ", hex_mode=True).validate()

    def test_auto_send_interval_floor(self) -> None:
        button = CommandButton(name="Fast", command="X")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=1)
        with pytest.raises(ValidationError, match="at least"):
            button.validate()

    def test_resolved_line_ending_falls_back_to_global(self) -> None:
        button = CommandButton(name="A", command="X")
        assert button.resolved_line_ending(LineEnding.CRLF) is LineEnding.CRLF
        button.line_ending = LineEnding.CR
        assert button.resolved_line_ending(LineEnding.CRLF) is LineEnding.CR


class TestSerialisation:
    def test_round_trip(self) -> None:
        original = CommandButton(
            name="Read Temp",
            command="AT+TEMP?",
            line_ending=LineEnding.CRLF,
            hex_mode=False,
            enabled=False,
            description="note",
        )
        original.auto_send = AutoSendSpec(enabled=True, interval_ms=1500)
        restored = CommandButton.from_dict(original.to_dict())
        assert restored.to_dict() == original.to_dict()

    def test_from_dict_repairs_missing_fields(self) -> None:
        button = CommandButton.from_dict({})
        assert button.name == "Command"
        assert button.enabled is True
        assert button.id

    def test_from_dict_clamps_a_hostile_interval(self) -> None:
        button = CommandButton.from_dict(
            {"name": "x", "auto_send": {"enabled": True, "interval_ms": -5}}
        )
        assert button.auto_send.interval_ms == MIN_AUTO_SEND_INTERVAL_MS

    def test_from_dict_accepts_inherit_sentinel(self) -> None:
        assert CommandButton.from_dict({"line_ending": None}).line_ending is None
        assert CommandButton.from_dict({"line_ending": "inherit"}).line_ending is None
