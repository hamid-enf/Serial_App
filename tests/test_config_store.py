"""Configuration persistence: atomicity, backups and corruption recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from serial_console.config.migrations import migrate
from serial_console.config.store import ConfigStore
from serial_console.models.enums import DataBits, LineEnding, Parity, Theme
from serial_console.models.errors import ConfigError
from serial_console.models.settings import SCHEMA_VERSION, AppConfig


@pytest.fixture()
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


class TestRoundTrip:
    def test_save_then_load_preserves_everything(self, store_path: Path) -> None:
        store = ConfigStore(store_path)
        config = AppConfig.create_default()
        config.serial.port = "COM7"
        config.serial.baud_rate = 921600
        config.serial.parity = Parity.EVEN
        config.serial.data_bits = DataBits.SEVEN
        config.terminal.line_ending = LineEnding.CRLF
        config.terminal.max_buffer_bytes = 10 * 1024 * 1024
        config.appearance.theme = Theme.LIGHT
        config.commands.history_limit = 42
        config.active_profile().buttons[0].name = "My Button"
        store.save(config)

        restored = ConfigStore(store_path).load().config
        assert restored.serial.port == "COM7"
        assert restored.serial.baud_rate == 921600
        assert restored.serial.parity is Parity.EVEN
        assert restored.serial.data_bits is DataBits.SEVEN
        assert restored.terminal.line_ending is LineEnding.CRLF
        assert restored.terminal.max_buffer_bytes == 10 * 1024 * 1024
        assert restored.appearance.theme is Theme.LIGHT
        assert restored.commands.history_limit == 42
        assert restored.active_profile().buttons[0].name == "My Button"

    def test_missing_file_yields_defaults_without_error(self, store_path: Path) -> None:
        result = ConfigStore(store_path).load()
        assert result.recovered is False
        assert result.config.profiles

    def test_written_json_is_human_readable(self, store_path: Path) -> None:
        ConfigStore(store_path).save(AppConfig.create_default())
        text = store_path.read_text(encoding="utf-8")
        assert "\n  " in text  # indented
        json.loads(text)

    def test_schema_version_is_recorded(self, store_path: Path) -> None:
        ConfigStore(store_path).save(AppConfig.create_default())
        data = json.loads(store_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION


class TestAtomicityAndBackup:
    def test_no_temporary_files_are_left_behind(self, store_path: Path) -> None:
        store = ConfigStore(store_path)
        store.save(AppConfig.create_default())
        leftovers = [p.name for p in store_path.parent.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_second_save_creates_a_backup(self, store_path: Path) -> None:
        store = ConfigStore(store_path)
        config = AppConfig.create_default()
        store.save(config)
        config.serial.port = "COM9"
        store.save(config)
        assert store.backup_path.exists()

    def test_identical_payload_is_not_rewritten(self, store_path: Path) -> None:
        store = ConfigStore(store_path)
        config = AppConfig.create_default()
        store.save(config)
        first_mtime = store_path.stat().st_mtime_ns
        store.save(config)
        assert store_path.stat().st_mtime_ns == first_mtime

    def test_force_rewrites_even_when_unchanged(self, store_path: Path) -> None:
        store = ConfigStore(store_path)
        config = AppConfig.create_default()
        store.save(config)
        store.save(config, force=True)
        assert store_path.exists()

    def test_dirty_flag_drives_save_if_dirty(self, store_path: Path) -> None:
        store = ConfigStore(store_path)
        config = AppConfig.create_default()
        assert store.save_if_dirty(config) is None
        store.mark_dirty()
        assert store.save_if_dirty(config) == store_path
        assert store.is_dirty is False

    @pytest.mark.skipif(os.name == "nt", reason="chmod is not enforced the same way on Windows")
    def test_unwritable_target_raises_config_error_not_oserror(self, tmp_path: Path) -> None:
        directory = tmp_path / "locked"
        directory.mkdir()
        target = directory / "config.json"
        directory.chmod(0o500)
        try:
            with pytest.raises(ConfigError):
                ConfigStore(target).save(AppConfig.create_default())
        finally:
            directory.chmod(0o700)


class TestCorruptionRecovery:
    def test_truncated_json_falls_back_to_the_backup(self, store_path: Path) -> None:
        store = ConfigStore(store_path)
        config = AppConfig.create_default()
        config.serial.port = "COM_GOOD"
        store.save(config)
        config.serial.port = "COM_NEWER"
        store.save(config)  # refreshes the .bak with COM_GOOD

        store_path.write_text('{"schema_version": 1, "serial": {', encoding="utf-8")

        result = ConfigStore(store_path).load()
        assert result.recovered is True
        assert "backup" in result.message
        assert result.config.serial.port == "COM_GOOD"

    def test_corrupt_file_without_backup_falls_back_to_defaults(
        self, store_path: Path
    ) -> None:
        store_path.write_text("this is not json at all", encoding="utf-8")
        result = ConfigStore(store_path).load()
        assert result.recovered is True
        assert result.config.profiles  # app still starts
        assert result.quarantine_path is not None
        assert result.quarantine_path.exists()

    def test_the_damaged_file_is_quarantined_not_deleted(self, store_path: Path) -> None:
        store_path.write_text("{oops", encoding="utf-8")
        result = ConfigStore(store_path).load()
        assert result.quarantine_path is not None
        assert result.quarantine_path.read_text(encoding="utf-8") == "{oops"

    def test_quarantine_copies_are_pruned(self, store_path: Path) -> None:
        for _ in range(9):
            store_path.write_text("{oops", encoding="utf-8")
            ConfigStore(store_path).load()
        copies = list(store_path.parent.glob("config.corrupt-*.json"))
        assert len(copies) <= 6

    def test_json_array_root_is_treated_as_corrupt(self, store_path: Path) -> None:
        store_path.write_text("[1, 2, 3]", encoding="utf-8")
        result = ConfigStore(store_path).load()
        assert result.recovered is True
        assert result.config.profiles

    def test_partially_broken_document_still_loads(self, store_path: Path) -> None:
        store_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "serial": {"baud_rate": "not-a-number", "parity": "nonsense"},
                    "terminal": {"max_buffer_bytes": -12},
                    "profiles": "not-a-list",
                }
            ),
            encoding="utf-8",
        )
        result = ConfigStore(store_path).load()
        config = result.config
        assert config.serial.baud_rate == 115200  # repaired
        assert config.serial.parity.value == "none"
        assert config.terminal.max_buffer_bytes >= 64 * 1024
        assert config.profiles  # a starter profile was substituted

    def test_empty_file_is_handled(self, store_path: Path) -> None:
        store_path.write_text("", encoding="utf-8")
        assert ConfigStore(store_path).load().config.profiles


class TestMigrations:
    def test_unversioned_flat_layout_is_migrated(self) -> None:
        legacy = {
            "buttons": [{"name": "Old", "command": "AT"}],
            "history": ["AT"],
        }
        migrated = migrate(dict(legacy))
        assert migrated["schema_version"] == SCHEMA_VERSION
        assert migrated["profiles"][0]["buttons"][0]["name"] == "Old"

    def test_legacy_document_loads_end_to_end(self, store_path: Path) -> None:
        store_path.write_text(
            json.dumps({"buttons": [{"name": "Legacy", "command": "AT+X"}]}),
            encoding="utf-8",
        )
        config = ConfigStore(store_path).load().config
        assert config.active_profile().buttons[0].name == "Legacy"

    def test_newer_schema_is_loaded_best_effort(self, store_path: Path) -> None:
        store_path.write_text(
            json.dumps({"schema_version": 999, "profiles": [], "unknown_key": 1}),
            encoding="utf-8",
        )
        result = ConfigStore(store_path).load()
        assert result.config.profiles  # did not crash, substituted a starter

    def test_current_version_is_untouched(self) -> None:
        data = {"schema_version": SCHEMA_VERSION, "profiles": []}
        assert migrate(dict(data))["schema_version"] == SCHEMA_VERSION
