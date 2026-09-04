"""Translation of low-level exceptions into messages a human can act on.

Rule of the codebase: a raw exception string is *never* shown in the UI.  It
goes to the log file; the user gets a sentence that says what happened and what
to do next.
"""

from __future__ import annotations

import errno
from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class UserError:
    """A presentable error.

    Attributes:
        message: One sentence describing what went wrong, in plain language.
        hint: Optional follow-up telling the user what to try.
        detail: The technical text (exception repr) for the log / details pane.
        severity: Controls the icon and whether a modal dialog is used.
    """

    message: str
    hint: str = ""
    detail: str = ""
    severity: Severity = Severity.ERROR

    def full_text(self) -> str:
        return f"{self.message} {self.hint}".strip()


def _is_permission_problem(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in ("access is denied", "permission denied", "errno 13", "errno 16")
    )


def _is_missing_port(exc: BaseException) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "could not open port",
            "no such file or directory",
            "the system cannot find the file",
            "filenotfounderror",
        )
    )


def map_open_error(exc: BaseException, port: str) -> UserError:
    """Explain why a port could not be opened."""
    detail = f"{type(exc).__name__}: {exc}"
    port_label = port or "the selected port"

    if isinstance(exc, ValueError):
        return UserError(
            message=f"The serial settings for {port_label} are not valid.",
            hint="Check the baud rate, data bits, parity and stop bit combination.",
            detail=detail,
        )
    if _is_permission_problem(exc):
        return UserError(
            message=f"Unable to open {port_label}. The port may be in use by another application.",
            hint="Close any other terminal, IDE serial monitor or flashing tool and try again.",
            detail=detail,
        )
    if _is_missing_port(exc):
        return UserError(
            message=f"{port_label} is not available.",
            hint="Reconnect the USB-serial adapter, then press Refresh Ports (Ctrl+R).",
            detail=detail,
        )
    return UserError(
        message=f"Unable to open {port_label}.",
        hint="Verify the device is connected and the settings are supported by the driver.",
        detail=detail,
    )


def map_read_error(exc: BaseException, port: str) -> UserError:
    """Explain a failure while reading, usually a surprise disconnect."""
    detail = f"{type(exc).__name__}: {exc}"
    port_label = port or "the serial port"
    if _looks_like_disconnect(exc):
        return UserError(
            message=f"{port_label} was disconnected.",
            hint="Reconnect the device and press Connect to resume.",
            detail=detail,
            severity=Severity.WARNING,
        )
    return UserError(
        message=f"Reading from {port_label} failed.",
        hint="The connection has been closed. Reconnect to continue.",
        detail=detail,
    )


def map_write_error(exc: BaseException, port: str) -> UserError:
    """Explain a failure while writing."""
    detail = f"{type(exc).__name__}: {exc}"
    port_label = port or "the serial port"
    if isinstance(exc, TimeoutError) or "timeout" in str(exc).lower():
        return UserError(
            message=f"Sending to {port_label} timed out.",
            hint=(
                "The device is not accepting data. If hardware flow control is enabled, "
                "check that CTS is asserted."
            ),
            detail=detail,
            severity=Severity.WARNING,
        )
    if _looks_like_disconnect(exc):
        return UserError(
            message=f"{port_label} was disconnected while sending.",
            hint="Reconnect the device and try again.",
            detail=detail,
            severity=Severity.WARNING,
        )
    return UserError(
        message=f"Sending to {port_label} failed.",
        hint="The connection has been closed. Reconnect to continue.",
        detail=detail,
    )


def _looks_like_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, OSError) and exc.errno in {
        errno.ENODEV,
        errno.ENXIO,
        errno.EIO,
        errno.EBADF,
        errno.ENOENT,
        errno.EPIPE,
    }:
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "device disconnected",
            "device reports readiness",
            "attempted to use a port that is not open",
            "handle is invalid",
            "i/o error",
            "input/output error",
            "device not configured",
            "clearcommerror",
            "readfile failed",
            "writefile failed",
        )
    )


def map_config_error(exc: BaseException, path: str) -> UserError:
    """Explain a configuration load/save failure."""
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, PermissionError):
        return UserError(
            message="Settings could not be saved because the file is not writable.",
            hint=f"Check the permissions on {path}.",
            detail=detail,
        )
    return UserError(
        message="Settings could not be saved.",
        hint="Your changes are still active for this session.",
        detail=detail,
    )
