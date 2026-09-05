"""Framework-independent application core."""

from __future__ import annotations

from .codec import build_payload, format_hex, format_hex_dump, parse_hex
from .commands import CommandStore
from .errors import Severity, UserError
from .history import CommandHistory
from .profiles import ProfileManager
from .rx_aggregator import RxAggregator, RxBatch
from .serial_worker import SerialWorker, WorkerEvent, WorkerEventType
from .stats import SessionStats, format_bytes
from .terminal_buffer import (
    TerminalBuffer,
    TerminalChunk,
    TerminalRenderer,
    render_chunk,
)

__all__ = [
    "CommandHistory",
    "CommandStore",
    "ProfileManager",
    "RxAggregator",
    "RxBatch",
    "SerialWorker",
    "SessionStats",
    "Severity",
    "TerminalBuffer",
    "TerminalChunk",
    "TerminalRenderer",
    "UserError",
    "WorkerEvent",
    "WorkerEventType",
    "build_payload",
    "format_bytes",
    "format_hex",
    "format_hex_dump",
    "parse_hex",
    "render_chunk",
]
