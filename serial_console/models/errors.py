"""Errors raised by the model / core layers."""

from __future__ import annotations


class SerialConsoleError(Exception):
    """Base class for all application specific errors."""


class ValidationError(SerialConsoleError):
    """Raised when user supplied data fails validation.

    The message is written to be shown directly to the user, so it must never
    contain a raw traceback or library jargon.
    """


class ConfigError(SerialConsoleError):
    """Raised when the configuration file cannot be read or written."""
