"""User-facing error mapping: no raw exceptions, always actionable."""

from __future__ import annotations

import errno

import pytest
import serial

from serial_console.core.errors import (
    Severity,
    UserError,
    map_config_error,
    map_open_error,
    map_read_error,
    map_write_error,
)


def _all_messages(error: UserError) -> str:
    return f"{error.message} {error.hint}"


class TestOpenErrors:
    def test_port_in_use(self) -> None:
        exc = serial.SerialException(
            "could not open port 'COM5': PermissionError(13, 'Access is denied.', None, 5)"
        )
        error = map_open_error(exc, "COM5")
        assert error.message == (
            "Unable to open COM5. The port may be in use by another application."
        )
        assert "Close any other terminal" in error.hint

    def test_permission_error_subclass(self) -> None:
        error = map_open_error(PermissionError(13, "Permission denied"), "/dev/ttyUSB0")
        assert "in use by another application" in error.message

    def test_missing_port(self) -> None:
        error = map_open_error(FileNotFoundError("no such device"), "COM9")
        assert error.message == "COM9 is not available."
        assert "Ctrl+R" in error.hint

    def test_invalid_settings(self) -> None:
        error = map_open_error(ValueError("invalid baudrate"), "COM3")
        assert "not valid" in error.message
        assert "baud rate" in error.hint

    def test_unknown_failure_still_produces_a_sentence(self) -> None:
        error = map_open_error(RuntimeError("¯\\_(ツ)_/¯"), "COM1")
        assert error.message.startswith("Unable to open COM1")
        assert error.hint

    def test_technical_detail_is_kept_separately(self) -> None:
        error = map_open_error(serial.SerialException("boom"), "COM1")
        assert "SerialException" in error.detail
        assert "SerialException" not in error.message

    def test_blank_port_name_is_handled(self) -> None:
        error = map_open_error(OSError("x"), "")
        assert "the selected port" in error.message

    @pytest.mark.parametrize(
        "exc",
        [
            serial.SerialException("could not open port"),
            PermissionError("Access is denied"),
            FileNotFoundError("missing"),
            ValueError("bad"),
            OSError(errno.EBUSY, "busy"),
            RuntimeError("unexpected"),
        ],
    )
    def test_never_returns_an_empty_message(self, exc: BaseException) -> None:
        error = map_open_error(exc, "COM1")
        assert error.message.strip()
        assert error.message.endswith(".")


class TestReadWriteErrors:
    def test_unplugged_device_while_reading(self) -> None:
        exc = serial.SerialException(
            "device reports readiness to read but returned no data (device disconnected?)"
        )
        error = map_read_error(exc, "COM5")
        assert error.message == "COM5 was disconnected."
        assert error.severity is Severity.WARNING

    def test_io_error_is_treated_as_a_disconnect(self) -> None:
        error = map_read_error(OSError(errno.EIO, "Input/output error"), "COM5")
        assert "disconnected" in error.message

    def test_generic_read_failure(self) -> None:
        error = map_read_error(RuntimeError("strange"), "COM5")
        assert error.message == "Reading from COM5 failed."
        assert error.severity is Severity.ERROR

    def test_write_timeout_mentions_flow_control(self) -> None:
        error = map_write_error(serial.SerialTimeoutException("Write timeout"), "COM5")
        assert "timed out" in error.message
        assert "CTS" in error.hint

    def test_write_after_disconnect(self) -> None:
        error = map_write_error(OSError(errno.ENODEV, "No such device"), "COM5")
        assert "disconnected while sending" in error.message

    def test_generic_write_failure(self) -> None:
        error = map_write_error(RuntimeError("nope"), "COM5")
        assert error.message == "Sending to COM5 failed."


class TestConfigErrors:
    def test_read_only_file(self) -> None:
        error = map_config_error(PermissionError("denied"), "/tmp/config.json")
        assert "not writable" in error.message
        assert "/tmp/config.json" in error.hint

    def test_generic_failure_reassures_the_user(self) -> None:
        error = map_config_error(OSError("disk full"), "/tmp/config.json")
        assert "still active for this session" in error.hint


class TestUserError:
    def test_full_text_joins_message_and_hint(self) -> None:
        error = UserError(message="A.", hint="B.")
        assert error.full_text() == "A. B."

    def test_full_text_without_hint(self) -> None:
        assert UserError(message="A.").full_text() == "A."

    def test_default_severity_is_error(self) -> None:
        assert UserError(message="x").severity is Severity.ERROR
