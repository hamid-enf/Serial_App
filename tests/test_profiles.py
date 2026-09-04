"""Profile lifecycle and import/export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from serial_console.core.profiles import ProfileManager
from serial_console.models.command import CommandButton
from serial_console.models.errors import ValidationError
from serial_console.models.profile import Profile
from serial_console.models.settings import AppConfig


@pytest.fixture()
def manager(config: AppConfig) -> ProfileManager:
    return ProfileManager(config)


class TestLifecycle:
    def test_manager_guarantees_at_least_one_profile(self) -> None:
        empty = AppConfig(profiles=[], active_profile_id="")
        manager = ProfileManager(empty)
        assert len(manager) == 1
        assert manager.active() is manager.profiles[0]

    def test_create(self, manager: ProfileManager) -> None:
        profile = manager.create("ESP32", button_count=8)
        assert profile.name == "ESP32"
        assert len(profile.buttons) == 8
        assert profile in manager.profiles

    def test_create_rejects_duplicate_names_case_insensitively(
        self, manager: ProfileManager
    ) -> None:
        manager.create("STM32")
        with pytest.raises(ValidationError, match="already exists"):
            manager.create("stm32")

    def test_create_rejects_blank_names(self, manager: ProfileManager) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            manager.create("   ")

    def test_rename(self, manager: ProfileManager) -> None:
        target = manager.profiles[0]
        manager.rename(target.id, "Renamed")
        assert manager.get(target.id).name == "Renamed"

    def test_rename_to_its_own_name_is_allowed(self, manager: ProfileManager) -> None:
        target = manager.profiles[0]
        manager.rename(target.id, target.name)
        assert manager.get(target.id).name == target.name

    def test_duplicate_is_a_deep_copy(self, manager: ProfileManager) -> None:
        source = manager.profiles[0]
        clone = manager.duplicate(source.id)
        assert clone.id != source.id
        assert len(clone.buttons) == len(source.buttons)
        assert clone.buttons[0].id != source.buttons[0].id
        clone.buttons[0].command = "CHANGED"
        assert source.buttons[0].command != "CHANGED"

    def test_duplicate_is_inserted_after_the_source(self, manager: ProfileManager) -> None:
        source = manager.profiles[0]
        clone = manager.duplicate(source.id)
        assert manager.profiles[manager.index_of(source.id) + 1] is clone

    def test_delete(self, manager: ProfileManager) -> None:
        extra = manager.create("Temporary")
        manager.delete(extra.id)
        assert extra.id not in [p.id for p in manager.profiles]

    def test_the_last_profile_cannot_be_deleted(self, manager: ProfileManager) -> None:
        while len(manager) > 1:
            manager.delete(manager.profiles[-1].id)
        with pytest.raises(ValidationError, match="At least one profile"):
            manager.delete(manager.profiles[0].id)

    def test_deleting_the_active_profile_reassigns_active(
        self, manager: ProfileManager
    ) -> None:
        extra = manager.create("Second")
        manager.set_active(extra.id)
        manager.delete(extra.id)
        assert manager.config.active_profile_id != extra.id
        assert manager.active() in manager.profiles

    def test_active_heals_a_dangling_pointer(self, manager: ProfileManager) -> None:
        manager.config.active_profile_id = "ghost"
        assert manager.active() is manager.profiles[0]


class TestImportExport:
    def test_export_then_import_round_trip(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        source = manager.profiles[0]
        target = tmp_path / "profile.json"
        manager.export_to_file(source.id, target)

        imported = manager.import_from_file(target)
        assert imported.id != source.id  # re-keyed so importing twice is safe
        assert [b.command for b in imported.buttons] == [b.command for b in source.buttons]

    def test_import_twice_yields_unique_names(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        target = tmp_path / "profile.json"
        manager.export_to_file(manager.profiles[0].id, target)
        first = manager.import_from_file(target)
        second = manager.import_from_file(target)
        assert first.name != second.name

    def test_exported_document_is_self_describing(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        target = tmp_path / "profile.json"
        manager.export_to_file(manager.profiles[0].id, target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["kind"] == "serial-command-console.profile"
        assert data["version"] >= 1

    def test_import_accepts_a_bare_profile_object(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        target = tmp_path / "bare.json"
        target.write_text(json.dumps(Profile.create_default("Bare", 3).to_dict()))
        imported = manager.import_from_file(target)
        assert len(imported.buttons) == 3

    def test_import_rejects_invalid_json_with_a_readable_message(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        target = tmp_path / "broken.json"
        target.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError, match="not valid JSON"):
            manager.import_from_file(target)

    def test_import_rejects_a_foreign_document(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        target = tmp_path / "other.json"
        target.write_text(json.dumps({"kind": "something-else", "profile": {}}))
        with pytest.raises(ValidationError):
            manager.import_from_file(target)

    def test_import_reports_a_missing_file_clearly(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        with pytest.raises(ValidationError, match="could not be read"):
            manager.import_from_file(tmp_path / "nope.json")

    def test_import_does_not_corrupt_the_existing_list_on_failure(
        self, manager: ProfileManager, tmp_path: Path
    ) -> None:
        before = list(manager.profiles)
        target = tmp_path / "broken.json"
        target.write_text("[]", encoding="utf-8")
        with pytest.raises(ValidationError):
            manager.import_from_file(target)
        assert manager.profiles == before


class TestProfileModel:
    def test_create_default_has_the_requested_button_count(self) -> None:
        assert len(Profile.create_default("X", 20).buttons) == 20

    def test_starter_profile_has_examples_and_twenty_buttons(self) -> None:
        profile = Profile.create_starter()
        assert len(profile.buttons) == 20
        assert any(b.command == "AT+STATUS" for b in profile.buttons)

    def test_from_dict_skips_a_single_broken_button(self) -> None:
        profile = Profile.from_dict(
            {"name": "P", "buttons": [{"name": "ok", "command": "A"}, "not-an-object"]}
        )
        assert len(profile.buttons) == 1

    def test_index_of_unknown_button_raises(self) -> None:
        with pytest.raises(ValidationError):
            Profile(name="P", buttons=[CommandButton()]).index_of("ghost")
