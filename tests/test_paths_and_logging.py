"""Data locations and the logging subsystem.

Both are boring until they misbehave on someone else's machine: a read-only
install directory, a USB-stick copy, a frozen build. These tests pin down the
behaviour on every platform branch without needing that platform.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from serial_console import APP_SLUG
from serial_console.config import paths
from serial_console.core import logging_setup


@pytest.fixture()
def no_home_override(monkeypatch: pytest.MonkeyPatch):
    """Undo the autouse SERIAL_CONSOLE_HOME so platform branches are reachable."""
    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)


# ----------------------------------------------------------------------
class TestAppDataDir:
    def test_environment_override_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "custom"))
        assert paths.app_data_dir() == tmp_path / "custom"

    def test_override_expands_a_user_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(paths.ENV_HOME, "~/serial-data")
        assert paths.app_data_dir() == Path.home() / "serial-data"

    def test_windows_uses_appdata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        assert paths.app_data_dir() == tmp_path / "Roaming" / APP_SLUG

    def test_windows_falls_back_to_localappdata_then_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
        assert paths.app_data_dir() == tmp_path / "Local" / APP_SLUG

        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert paths.app_data_dir() == Path.home() / "AppData" / "Roaming" / APP_SLUG

    def test_macos_uses_application_support(
        self, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        expected = Path.home() / "Library" / "Application Support" / APP_SLUG
        assert paths.app_data_dir() == expected

    def test_linux_honours_xdg_config_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        assert paths.app_data_dir() == tmp_path / "xdg" / APP_SLUG

        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert paths.app_data_dir() == Path.home() / ".config" / APP_SLUG


class TestPortableMode:
    def test_marker_next_to_a_frozen_exe_redirects_to_a_data_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        exe = tmp_path / "SerialCommandConsole.exe"
        exe.write_bytes(b"MZ")
        (tmp_path / paths.PORTABLE_MARKER).write_text("portable", encoding="utf-8")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))

        assert paths.app_data_dir() == tmp_path / "data"

    def test_marker_is_ignored_when_running_from_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        # Otherwise a developer's checkout would silently switch storage.
        (tmp_path / paths.PORTABLE_MARKER).write_text("", encoding="utf-8")
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
        monkeypatch.setattr(sys, "platform", "linux")
        assert paths.app_data_dir() != tmp_path / "data"

    def test_no_marker_means_the_normal_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        assert paths.app_data_dir() == tmp_path / "Roaming" / APP_SLUG

    def test_an_unreadable_marker_does_not_crash_startup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_home_override
    ) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            Path, "exists", lambda self: (_ for _ in ()).throw(OSError("I/O error"))
        )
        assert paths.app_data_dir() == Path.home() / ".config" / APP_SLUG


class TestDerivedPaths:
    def test_everything_hangs_off_the_data_dir(self, isolated_home: Path) -> None:
        assert paths.config_file() == isolated_home / "config.json"
        assert paths.log_dir() == isolated_home / "logs"
        assert paths.profiles_dir() == isolated_home / "profiles"

    def test_ensure_dirs_creates_the_tree_and_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "fresh"))
        root = paths.ensure_dirs()
        paths.ensure_dirs()
        assert root.is_dir()
        assert paths.log_dir().is_dir()
        assert paths.profiles_dir().is_dir()

    def test_resource_dir_points_into_the_repository_when_running_from_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        resources = paths.resource_dir()
        assert (resources / "themes" / "dark.qss").is_file()

    def test_resource_dir_follows_meipass_in_a_frozen_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert paths.resource_dir() == tmp_path / "resources"


# ----------------------------------------------------------------------
@pytest.fixture()
def restore_logging():
    """Logging is process-global; put it back the way we found it."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_memory = logging_setup._memory_handler
    saved_file = logging_setup._log_file
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)
    logging_setup._memory_handler = saved_memory
    logging_setup._log_file = saved_file


@pytest.mark.usefixtures("restore_logging")
class TestSetupLogging:
    def test_creates_the_directory_and_the_file(self, tmp_path: Path) -> None:
        log_file = logging_setup.setup_logging(tmp_path / "logs")
        logging.getLogger("serial_console.test").info("hello file")
        assert log_file.exists()
        assert "hello file" in log_file.read_text(encoding="utf-8")
        assert logging_setup.log_file_path() == log_file

    def test_records_reach_the_in_memory_ring_for_the_log_viewer(
        self, tmp_path: Path
    ) -> None:
        logging_setup.setup_logging(tmp_path / "logs")
        logging.getLogger("serial_console.test").warning("ring buffer entry")
        handler = logging_setup.memory_handler()
        assert handler is not None
        assert any("ring buffer entry" in line for line in handler.lines())

    def test_level_filters_debug_unless_verbose(self, tmp_path: Path) -> None:
        logging_setup.setup_logging(tmp_path / "logs", level=logging.INFO)
        logging.getLogger("serial_console.test").debug("chatter")
        handler = logging_setup.memory_handler()
        assert handler is not None
        assert not any("chatter" in line for line in handler.lines())

        logging_setup.setup_logging(tmp_path / "logs2", level=logging.DEBUG)
        logging.getLogger("serial_console.test").debug("chatter")
        handler = logging_setup.memory_handler()
        assert handler is not None
        assert any("chatter" in line for line in handler.lines())

    def test_console_handler_is_opt_in(self, tmp_path: Path) -> None:
        logging_setup.setup_logging(tmp_path / "a")
        assert not any(
            type(h) is logging.StreamHandler for h in logging.getLogger().handlers
        )
        logging_setup.setup_logging(tmp_path / "b", console=True)
        assert any(
            type(h) is logging.StreamHandler for h in logging.getLogger().handlers
        )

    def test_reconfiguring_does_not_stack_handlers(self, tmp_path: Path) -> None:
        logging_setup.setup_logging(tmp_path / "logs")
        first = len(logging.getLogger().handlers)
        logging_setup.setup_logging(tmp_path / "logs")
        assert len(logging.getLogger().handlers) == first

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permissions")
    def test_an_unwritable_directory_still_yields_a_working_logger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A read-only install location must never stop the app from starting.
        target = tmp_path / "logs"
        target.mkdir()

        def refuse(*args: object, **kwargs: object):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(logging.handlers, "RotatingFileHandler", refuse)
        logging_setup.setup_logging(target)
        logging.getLogger("serial_console.test").info("still alive")
        handler = logging_setup.memory_handler()
        assert handler is not None
        assert any("still alive" in line for line in handler.lines())


class TestMemoryLogHandler:
    def test_oldest_records_are_discarded_at_capacity(self) -> None:
        handler = logging_setup.MemoryLogHandler(capacity=3)
        handler.setFormatter(logging.Formatter("%(message)s"))
        for index in range(5):
            handler.emit(
                logging.LogRecord("t", logging.INFO, __file__, 1, str(index), None, None)
            )
        assert list(handler.lines()) == ["2", "3", "4"]

    def test_clear(self) -> None:
        handler = logging_setup.MemoryLogHandler(capacity=3)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "x", None, None))
        handler.clear()
        assert list(handler.lines()) == []

    def test_a_bad_format_string_never_raises_into_the_caller(self) -> None:
        handler = logging_setup.MemoryLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(
            logging.LogRecord("t", logging.INFO, __file__, 1, "%d", ("nope",), None)
        )  # logging must swallow its own errors

    def test_get_logger_namespaces_under_the_package(self) -> None:
        assert logging_setup.get_logger("serial_console.x").name == "serial_console.x"
