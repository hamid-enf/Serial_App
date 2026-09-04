"""Qt facade over the framework-free :class:`SerialWorker`.

A single ``QTimer`` drives everything the GUI needs from the serial layer:
it drains the RX aggregator and the worker's event queue on the same tick.
Because the timer runs on the GUI thread, every signal this class emits is
already on the GUI thread — no queued-connection subtleties, no risk of a
widget being touched from the reader thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.errors import UserError
from ..core.logging_setup import get_logger
from ..core.rx_aggregator import RxAggregator, RxBatch
from ..core.serial_worker import SerialWorker, WorkerEventType
from ..models.settings import SerialSettings
from ..transport.base import Transport
from ..transport.serial_transport import SerialTransport

_log = get_logger(__name__)

#: ~30 frames per second. Fast enough to feel live, slow enough that the text
#: widget is updated once per frame instead of once per read.
DEFAULT_POLL_INTERVAL_MS = 33

#: Upper bound on bytes handed to the view in a single frame.  Anything beyond
#: this stays queued, keeping frame time bounded at any baud rate.
MAX_BYTES_PER_FRAME = 256 * 1024


class SerialService(QObject):
    """Owns the connection lifecycle and republishes it as Qt signals."""

    connected = Signal(object)
    """Emitted with the :class:`SerialSettings` used to open the port."""

    disconnected = Signal(str)
    """Emitted with a machine-readable reason: ``user``/``read-error``/…"""

    errorRaised = Signal(object)
    """Emitted with a :class:`~serial_console.core.errors.UserError`."""

    dataReceived = Signal(bytes)
    """One batch of received bytes, at most once per frame."""

    dataSent = Signal(bytes)
    """A frame that has actually been written to the port."""

    overflowed = Signal(int)
    """Bytes discarded because the GUI could not keep up."""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._transport = transport if transport is not None else SerialTransport()
        self._worker = SerialWorker(self._transport, aggregator=RxAggregator())
        self._settings: SerialSettings | None = None
        self._timer = QTimer(self)
        self._timer.setTimerType(_precise_timer_type())
        self._timer.setInterval(max(5, int(poll_interval_ms)))
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @property
    def worker(self) -> SerialWorker:
        return self._worker

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def settings(self) -> SerialSettings | None:
        return self._settings

    @property
    def is_connected(self) -> bool:
        return self._worker.is_running

    @property
    def rx_bytes(self) -> int:
        return self._worker.rx_bytes

    @property
    def tx_bytes(self) -> int:
        return self._worker.tx_bytes

    def poll_interval_ms(self) -> int:
        return self._timer.interval()

    def set_poll_interval_ms(self, interval_ms: int) -> None:
        self._timer.setInterval(max(5, int(interval_ms)))

    def reset_counters(self) -> None:
        self._worker.reset_counters()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def connect_port(self, settings: SerialSettings) -> bool:
        """Open the port. Errors are reported via :attr:`errorRaised`."""
        if self.is_connected:
            self.disconnect_port()
        self._settings = settings
        started = self._worker.start(settings)
        # Drain immediately so an open failure surfaces without a frame delay.
        self._drain_events()
        if started:
            self._timer.start()
        return started

    def disconnect_port(self) -> None:
        """Close the port and stop polling."""
        if not self._worker.is_running and not self._timer.isActive():
            return
        self._worker.stop()
        self._timer.stop()
        # Deliver whatever arrived just before the close, then the CLOSED event.
        self._drain_rx()
        self._drain_events()

    def shutdown(self) -> None:
        """Called on application exit; never raises."""
        try:
            self._timer.stop()
            self._worker.stop(timeout=1.0)
        except Exception:
            _log.exception("Error during serial service shutdown")

    # ------------------------------------------------------------------
    # Transmission
    # ------------------------------------------------------------------
    def send(self, data: bytes) -> bool:
        """Queue bytes for transmission; ``False`` if it could not be queued."""
        if not data:
            return True
        if not self.is_connected:
            self.errorRaised.emit(
                UserError(
                    message="Not connected to a serial port.",
                    hint="Choose a port and press Connect (Ctrl+Enter) first.",
                    detail="send() called while disconnected",
                )
            )
            return False
        return self._worker.send(data)

    # ------------------------------------------------------------------
    # Frame tick
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        self._drain_rx()
        self._drain_events()
        if not self._worker.is_running and self._timer.isActive():
            self._timer.stop()

    def _drain_rx(self) -> None:
        batch: RxBatch = self._worker.poll_rx(MAX_BYTES_PER_FRAME)
        if batch.dropped:
            self.overflowed.emit(batch.dropped)
        if batch.data:
            self.dataReceived.emit(batch.data)

    def _drain_events(self) -> None:
        for event in self._worker.poll_events():
            if event.type is WorkerEventType.OPENED:
                self.connected.emit(event.payload)
            elif event.type is WorkerEventType.CLOSED:
                self.disconnected.emit(str(event.payload or "user"))
            elif event.type is WorkerEventType.TX_DONE:
                self.dataSent.emit(bytes(event.payload or b""))
            elif event.type is WorkerEventType.ERROR and event.error is not None:
                self.errorRaised.emit(event.error)


def _precise_timer_type():
    from PySide6.QtCore import Qt

    return Qt.TimerType.PreciseTimer
