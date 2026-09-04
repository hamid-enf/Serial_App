"""Transport abstraction.

The rest of the application talks to a :class:`Transport`, never to
``pyserial`` directly.  That keeps the worker unit-testable against
:class:`~serial_console.transport.loopback.LoopbackTransport` and leaves room
for TCP/RFC2217 or BLE backends later without touching the UI.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models.settings import SerialSettings


@runtime_checkable
class Transport(Protocol):
    """Minimal byte-stream interface required by the serial worker."""

    @property
    def is_open(self) -> bool:
        """True while the underlying device is usable."""
        ...

    def open(self, settings: SerialSettings) -> None:
        """Open the device. Raises on failure."""
        ...

    def close(self) -> None:
        """Close the device. Must be safe to call when already closed."""
        ...

    def read(self, max_bytes: int) -> bytes:
        """Block up to the configured read timeout, returning 0..max_bytes."""
        ...

    def write(self, data: bytes) -> int:
        """Write ``data``, returning the number of bytes accepted."""
        ...

    def in_waiting(self) -> int:
        """Bytes currently buffered by the driver (0 if unknown)."""
        ...

    def describe(self) -> str:
        """Short label such as ``COM5 @ 115200 8N1``."""
        ...
