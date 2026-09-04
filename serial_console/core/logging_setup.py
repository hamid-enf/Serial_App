"""Application logging.

Logs go to a rotating file next to the configuration, and to an in-memory ring
that the built-in Log Viewer renders.  Nothing is printed to the terminal pane:
diagnostics must never pollute the serial output the user is reading.
"""

from __future__ import annotations

import logging
import logging.handlers
from collections import deque
from collections.abc import Iterable
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_MEMORY_CAPACITY = 2000


class MemoryLogHandler(logging.Handler):
    """Keeps the most recent records so the UI can display them on demand."""

    def __init__(self, capacity: int = _MEMORY_CAPACITY) -> None:
        super().__init__()
        self._records: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._records.append(self.format(record))
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)

    def lines(self) -> Iterable[str]:
        return tuple(self._records)

    def clear(self) -> None:
        self._records.clear()


_memory_handler: MemoryLogHandler | None = None
_log_file: Path | None = None


def setup_logging(log_dir: Path, *, level: int = logging.INFO, console: bool = False) -> Path:
    """Configure root logging and return the active log file path."""
    global _memory_handler, _log_file

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "serial-console.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
    except OSError:
        # A read-only install directory must not prevent the app from starting.
        logging.getLogger(__name__).warning("File logging unavailable at %s", log_file)

    _memory_handler = MemoryLogHandler()
    _memory_handler.setFormatter(formatter)
    _memory_handler.setLevel(level)
    root.addHandler(_memory_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.setLevel(level)
        root.addHandler(stream)

    _log_file = log_file
    return log_file


def memory_handler() -> MemoryLogHandler | None:
    """Return the in-memory handler backing the Log Viewer."""
    return _memory_handler


def log_file_path() -> Path | None:
    return _log_file


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
