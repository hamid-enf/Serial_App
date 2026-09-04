"""In-process virtual serial ports used by the test suite and Demo Mode.

:class:`LoopbackTransport` echoes whatever is written back to the reader, which
makes it possible to exercise the whole RX/TX path — including the aggregator,
the terminal buffer and the UI — with no hardware attached.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from ..models.settings import SerialSettings


class TransportClosedError(OSError):
    """Raised when I/O is attempted on a closed virtual port."""


class LoopbackTransport:
    """A virtual port whose RX stream is fed programmatically.

    Args:
        echo: When true, every written byte is queued back for reading.
        responder: Optional callable mapping written bytes to a reply.
        fail_on_open: Exception raised by :meth:`open`, for error-path tests.
    """

    def __init__(
        self,
        *,
        echo: bool = True,
        responder: Callable[[bytes], bytes] | None = None,
        fail_on_open: BaseException | None = None,
        fail_on_write: BaseException | None = None,
        fail_on_read: BaseException | None = None,
    ) -> None:
        self._open = False
        self._echo = echo
        self._responder = responder
        self._fail_on_open = fail_on_open
        self._fail_on_write = fail_on_write
        self._fail_on_read = fail_on_read
        self._rx: deque[int] = deque()
        self._tx_log = bytearray()
        self._lock = threading.RLock()
        self._data_available = threading.Event()
        self._label = "LOOPBACK"
        self._read_timeout = 0.05

    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def written(self) -> bytes:
        """Everything that has been transmitted since construction."""
        with self._lock:
            return bytes(self._tx_log)

    def describe(self) -> str:
        return self._label

    # ------------------------------------------------------------------
    def open(self, settings: SerialSettings) -> None:
        if self._fail_on_open is not None:
            raise self._fail_on_open
        settings.validate()
        self._read_timeout = max(0.001, float(settings.read_timeout_s))
        self._label = settings.describe()
        self._open = True

    def close(self) -> None:
        self._open = False
        self._data_available.set()

    # ------------------------------------------------------------------
    def feed(self, data: bytes) -> None:
        """Inject bytes as if the device had sent them."""
        if not data:
            return
        with self._lock:
            self._rx.extend(data)
        self._data_available.set()

    def read(self, max_bytes: int) -> bytes:
        if self._fail_on_read is not None:
            raise self._fail_on_read
        if not self._open:
            raise TransportClosedError("Attempted to use a port that is not open.")
        deadline = time.monotonic() + self._read_timeout
        while True:
            with self._lock:
                if self._rx:
                    count = min(max(1, int(max_bytes)), len(self._rx))
                    chunk = bytes(self._rx.popleft() for _ in range(count))
                    if not self._rx:
                        self._data_available.clear()
                    return chunk
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._open:
                return b""
            self._data_available.wait(min(remaining, 0.01))

    def write(self, data: bytes) -> int:
        if self._fail_on_write is not None:
            raise self._fail_on_write
        if not self._open:
            raise TransportClosedError("Attempted to use a port that is not open.")
        with self._lock:
            self._tx_log.extend(data)
        reply = b""
        if self._echo:
            reply += data
        if self._responder is not None:
            reply += self._responder(bytes(data))
        if reply:
            self.feed(reply)
        return len(data)

    def in_waiting(self) -> int:
        with self._lock:
            return len(self._rx)

    def flush(self) -> None:
        return None

    def set_control_lines(self, *, dtr: bool | None = None, rts: bool | None = None) -> None:
        return None
