"""Session counters shown in the status bar."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


def _format_bytes(count: int) -> str:
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{count / 1024:.1f} KB"
    if count < 1024 * 1024 * 1024:
        return f"{count / (1024 * 1024):.2f} MB"
    return f"{count / (1024 * 1024 * 1024):.2f} GB"


@dataclass(slots=True)
class SessionStats:
    """RX/TX byte counters plus a light-weight throughput estimate."""

    rx_bytes: int = 0
    tx_bytes: int = 0
    dropped_bytes: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _last_sample_at: float = field(default_factory=time.monotonic)
    _last_rx: int = 0
    _rx_rate: float = 0.0

    def add_rx(self, count: int) -> None:
        self.rx_bytes += max(0, count)

    def add_tx(self, count: int) -> None:
        self.tx_bytes += max(0, count)

    def add_dropped(self, count: int) -> None:
        self.dropped_bytes += max(0, count)

    def reset(self) -> None:
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.dropped_bytes = 0
        self.started_at = time.monotonic()
        self._last_sample_at = self.started_at
        self._last_rx = 0
        self._rx_rate = 0.0

    # ------------------------------------------------------------------
    def sample_rx_rate(self, now: float | None = None) -> float:
        """Return the smoothed RX rate in bytes/second."""
        current = time.monotonic() if now is None else now
        elapsed = current - self._last_sample_at
        if elapsed < 0.25:
            return self._rx_rate
        delta = self.rx_bytes - self._last_rx
        instant = delta / elapsed if elapsed > 0 else 0.0
        # Exponential smoothing keeps the status bar readable at high rates.
        self._rx_rate = (0.6 * instant) + (0.4 * self._rx_rate)
        self._last_sample_at = current
        self._last_rx = self.rx_bytes
        return self._rx_rate

    # ------------------------------------------------------------------
    @property
    def rx_text(self) -> str:
        return _format_bytes(self.rx_bytes)

    @property
    def tx_text(self) -> str:
        return _format_bytes(self.tx_bytes)

    def rate_text(self) -> str:
        rate = self._rx_rate
        if rate < 1.0:
            return "idle"
        return f"{_format_bytes(int(rate))}/s"


format_bytes = _format_bytes
