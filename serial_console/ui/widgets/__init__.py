"""Composite widgets used by the main window."""

from __future__ import annotations

from .command_button import COMMAND_MIME, CommandButtonWidget
from .command_panel import CommandPanel
from .connection_bar import ConnectionBar
from .send_panel import CommandInput, SendPanel
from .status_bar import StatusBar
from .terminal_view import TerminalView

__all__ = [
    "COMMAND_MIME",
    "CommandButtonWidget",
    "CommandInput",
    "CommandPanel",
    "ConnectionBar",
    "SendPanel",
    "StatusBar",
    "TerminalView",
]
