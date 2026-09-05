"""Thread-safe RX accumulator sitting between the reader thread and the GUI.

Design rationale
----------------
Emitting a Qt signal per ``read()`` looks tidy but collapses at high baud
rates: the event queue fills faster than the GUI can drain it, latency grows
without bound and the application eventually dies.  Instead the reader thread
appends into a plain ``bytearray`` under a lock and the GUI *pulls* everything
accumulated once per frame.  Producer and consumer are then fully decoupled and
the queue can never grow beyond one frame's worth of data.

A hard ceiling protects against the pathological case where the GUI is blocked
(for example while a modal dialog is open) and data keeps arriving: the oldest
bytes are discarded and counted, so the user can be told data was lost instead
of the process being OOM-killed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

DEFAULT_CEILING_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RxBatch:
    """One frame's worth of received data."""

    data: bytes
    dropped: int = 0
    """Bytes discarded by the overflow guard since the previous batch."""

    def __bool__(self) -> bool:
        return bool(self.data) or bool(self.dropped)

    def __len__(self) -> int:
        return len(self.data)


class RxAggregator:
    """Accumulates bytes from the reader thread for batched GUI consumption."""

    def __init__(self, ceiling_bytes: int = DEFAULT_CEILING_BYTES) -> None:
        self._ceiling = max(64 * 1024, int(ceiling_bytes))
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._dropped_since_drain = 0
        self._total_received = 0
        self._total_dropped = 0

    # ------------------------------------------------------------------
    @property
    def ceiling_bytes(self) -> int:
        return self._ceiling

    def set_ceiling(self, ceiling_bytes: int) -> None:
        with self._lock:
            self._ceiling = max(64 * 1024, int(ceiling_bytes))

    @property
    def total_received(self) -> int:
        return self._total_received

    @property
    def total_dropped(self) -> int:
        return self._total_dropped

    def pending(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ------------------------------------------------------------------
    def push(self, data: bytes) -> None:
        """Called from the reader thread for every successful read."""
        if not data:
            return
        with self._lock:
            self._buffer.extend(data)
            self._total_received += len(data)
            overflow = len(self._buffer) - self._ceiling
            if overflow > 0:
                del self._buffer[:overflow]
                self._dropped_since_drain += overflow
                self._total_dropped += overflow

    def drain(self, max_bytes: int | None = None) -> RxBatch:
        """Called from the GUI thread once per frame.

        Args:
            max_bytes: Optional cap so a single frame cannot spend unbounded
                time rendering; the remainder stays queued for the next frame.
        """
        with self._lock:
            if max_bytes is not None and 0 < max_bytes < len(self._buffer):
                data = bytes(self._buffer[:max_bytes])
                del self._buffer[:max_bytes]
            else:
                data = bytes(self._buffer)
                self._buffer.clear()
            dropped = self._dropped_since_drain
            self._dropped_since_drain = 0
        return RxBatch(data=data, dropped=dropped)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._dropped_since_drain = 0

    def reset_counters(self) -> None:
        with self._lock:
            self._total_received = 0
            self._total_dropped = 0
