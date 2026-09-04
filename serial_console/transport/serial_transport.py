"""``pyserial`` backed :class:`~serial_console.transport.base.Transport`."""

from __future__ import annotations

import threading
from typing import Any

import serial

from ..core.logging_setup import get_logger
from ..models.enums import DataBits, FlowControl, Parity, StopBits
from ..models.settings import SerialSettings

_log = get_logger(__name__)

_PARITY_MAP: dict[Parity, str] = {
    Parity.NONE: serial.PARITY_NONE,
    Parity.EVEN: serial.PARITY_EVEN,
    Parity.ODD: serial.PARITY_ODD,
    Parity.MARK: serial.PARITY_MARK,
    Parity.SPACE: serial.PARITY_SPACE,
}

_STOPBITS_MAP: dict[StopBits, float] = {
    StopBits.ONE: serial.STOPBITS_ONE,
    StopBits.ONE_POINT_FIVE: serial.STOPBITS_ONE_POINT_FIVE,
    StopBits.TWO: serial.STOPBITS_TWO,
}

_BYTESIZE_MAP: dict[DataBits, int] = {
    DataBits.FIVE: serial.FIVEBITS,
    DataBits.SIX: serial.SIXBITS,
    DataBits.SEVEN: serial.SEVENBITS,
    DataBits.EIGHT: serial.EIGHTBITS,
}


def build_serial_kwargs(settings: SerialSettings) -> dict[str, Any]:
    """Translate :class:`SerialSettings` into ``serial.Serial`` keyword args."""
    flow = settings.flow_control
    return {
        "port": None,  # opened explicitly so we can set DTR/RTS first
        "baudrate": int(settings.baud_rate),
        "bytesize": _BYTESIZE_MAP[settings.data_bits],
        "parity": _PARITY_MAP[settings.parity],
        "stopbits": _STOPBITS_MAP[settings.stop_bits],
        "timeout": float(settings.read_timeout_s),
        "write_timeout": float(settings.write_timeout_s),
        "xonxoff": flow is FlowControl.XON_XOFF,
        "rtscts": flow is FlowControl.RTS_CTS,
        "dsrdtr": flow is FlowControl.DSR_DTR,
    }


class SerialTransport:
    """Thread-confined wrapper around ``serial.Serial``.

    All I/O is performed by the worker thread.  ``close()`` may be called from
    another thread to force a blocking read to unwind, which is why the handle
    is guarded by a lock.
    """

    def __init__(self) -> None:
        self._serial: serial.Serial | None = None
        self._lock = threading.RLock()
        self._label = ""

    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._serial is not None and bool(self._serial.is_open)

    def describe(self) -> str:
        return self._label

    # ------------------------------------------------------------------
    def open(self, settings: SerialSettings) -> None:
        settings.validate()
        kwargs = build_serial_kwargs(settings)
        with self._lock:
            self.close()
            handle = serial.Serial(**kwargs)
            handle.port = settings.port
            # Applying DTR/RTS before open avoids the classic auto-reset glitch
            # on boards that wire DTR to the MCU reset line.
            try:
                handle.dtr = settings.dtr
                handle.rts = settings.rts
            except (OSError, ValueError, AttributeError):
                _log.debug("Driver rejected pre-open DTR/RTS for %s", settings.port)
            handle.open()
            try:
                handle.reset_input_buffer()
                handle.reset_output_buffer()
            except (OSError, serial.SerialException):
                _log.debug("Could not flush buffers on %s after open", settings.port)
            self._serial = handle
            self._label = settings.describe()
            _log.info("Opened %s", self._label)

    def close(self) -> None:
        with self._lock:
            handle, self._serial = self._serial, None
        if handle is None:
            return
        try:
            handle.close()
        except (OSError, serial.SerialException) as exc:
            # A device yanked out of the USB socket often fails to close
            # cleanly; the handle is dead either way.
            _log.debug("Ignoring error while closing %s: %s", self._label, exc)
        else:
            _log.info("Closed %s", self._label)

    # ------------------------------------------------------------------
    def read(self, max_bytes: int) -> bytes:
        handle = self._require_handle()
        return handle.read(max(1, int(max_bytes)))

    def write(self, data: bytes) -> int:
        handle = self._require_handle()
        written = handle.write(data)
        return int(written or 0)

    def in_waiting(self) -> int:
        with self._lock:
            handle = self._serial
        if handle is None:
            return 0
        try:
            return int(handle.in_waiting)
        except (OSError, serial.SerialException, AttributeError):
            # Reported by some drivers right before a disconnect is detected;
            # the read call that follows surfaces the real error.
            return 0

    def flush(self) -> None:
        with self._lock:
            handle = self._serial
        if handle is None:
            return
        try:
            handle.flush()
        except (OSError, serial.SerialException) as exc:
            _log.debug("flush() failed on %s: %s", self._label, exc)

    def set_control_lines(self, *, dtr: bool | None = None, rts: bool | None = None) -> None:
        """Toggle DTR/RTS at runtime (used for manual board reset)."""
        with self._lock:
            handle = self._serial
        if handle is None:
            return
        try:
            if dtr is not None:
                handle.dtr = dtr
            if rts is not None:
                handle.rts = rts
        except (OSError, serial.SerialException, ValueError) as exc:
            _log.debug("Could not change control lines on %s: %s", self._label, exc)

    # ------------------------------------------------------------------
    def _require_handle(self) -> serial.Serial:
        with self._lock:
            handle = self._serial
        if handle is None or not handle.is_open:
            raise serial.SerialException("Attempted to use a port that is not open.")
        return handle
