"""The serial reader/writer thread.

Deliberately Qt-free so the whole connection lifecycle can be unit tested with
a :class:`~serial_console.transport.loopback.LoopbackTransport` and no
``QApplication``.

Threading model
---------------
* One background thread owns the transport for the whole session.
* Received bytes go into an :class:`RxAggregator`; the GUI pulls them per frame.
* Outgoing frames go through a bounded :class:`queue.Queue`; the GUI never
  touches the port, so a stalled device can never block the event loop.
* Lifecycle notifications are posted as :class:`WorkerEvent` objects onto a
  second queue which the GUI drains on the same timer tick.  Nothing is
  delivered by direct cross-thread callback, so there is no re-entrancy hazard.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..models.settings import SerialSettings
from ..transport.base import Transport
from .errors import UserError, map_open_error, map_read_error, map_write_error
from .logging_setup import get_logger
from .rx_aggregator import RxAggregator

_log = get_logger(__name__)

#: Largest single read; keeps latency low while avoiding syscall storms.
READ_CHUNK_BYTES = 65536
#: Maximum number of queued TX frames before the sender is told to back off.
TX_QUEUE_LIMIT = 2048


class WorkerEventType(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"
    ERROR = "error"
    TX_DONE = "tx_done"


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    """A lifecycle notification produced by the worker thread."""

    type: WorkerEventType
    error: UserError | None = None
    payload: Any = None
    timestamp: float = field(default_factory=time.time)


class SerialWorker:
    """Owns a :class:`Transport` on a dedicated thread."""

    def __init__(
        self,
        transport: Transport,
        *,
        aggregator: RxAggregator | None = None,
        tx_queue_limit: int = TX_QUEUE_LIMIT,
    ) -> None:
        self._transport = transport
        self._aggregator = aggregator or RxAggregator()
        self._events: queue.Queue[WorkerEvent] = queue.Queue()
        self._tx: queue.Queue[bytes] = queue.Queue(maxsize=max(1, tx_queue_limit))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._settings: SerialSettings | None = None
        self._tx_bytes = 0
        self._state_lock = threading.Lock()
        self._running = False
        # Distinct from ``_running``: tracks whether a *session* is logically
        # open, so exactly one CLOSED event is posted no matter whether the
        # thread exits first (fault) or ``stop()`` runs first (user action).
        self._session_active = False

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def aggregator(self) -> RxAggregator:
        return self._aggregator

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def settings(self) -> SerialSettings | None:
        return self._settings

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    @property
    def tx_bytes(self) -> int:
        return self._tx_bytes

    @property
    def rx_bytes(self) -> int:
        return self._aggregator.total_received

    def pending_tx(self) -> int:
        return self._tx.qsize()

    def reset_counters(self) -> None:
        self._tx_bytes = 0
        self._aggregator.reset_counters()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, settings: SerialSettings) -> bool:
        """Open the port and start the reader thread.

        Returns ``True`` on success.  On failure a
        :attr:`WorkerEventType.ERROR` event is queued and ``False`` returned —
        the caller never has to catch a driver exception.
        """
        if self.is_running:
            self.stop()
        self._stop.clear()
        self._drain_queue(self._tx)
        self._settings = settings
        try:
            self._transport.open(settings)
        except Exception as exc:
            _log.warning("Open failed for %s: %s", settings.port, exc, exc_info=True)
            self._post(WorkerEvent(WorkerEventType.ERROR, error=map_open_error(exc, settings.port)))
            return False

        with self._state_lock:
            self._running = True
            self._session_active = True
        self._thread = threading.Thread(
            target=self._run, name="serial-io", daemon=True
        )
        self._thread.start()
        self._post(WorkerEvent(WorkerEventType.OPENED, payload=settings))
        return True

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the thread and close the port. Safe to call repeatedly."""
        self._stop.set()
        thread = self._thread
        # Closing from this thread unblocks a pending read on most drivers; on
        # the rest the read timeout expires within ~50 ms anyway.
        try:
            self._transport.close()
        except Exception:
            _log.debug("Transport close raised during stop", exc_info=True)
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():  # pragma: no cover - driver level hang
                _log.error("Serial thread did not stop within %.1fs", timeout)
        self._thread = None
        with self._state_lock:
            self._running = False
        if self._end_session():
            self._post(WorkerEvent(WorkerEventType.CLOSED, payload="user"))

    # ------------------------------------------------------------------
    # Transmission
    # ------------------------------------------------------------------
    def send(self, data: bytes) -> bool:
        """Queue ``data`` for transmission.

        Returns ``False`` when the port is closed or the queue is saturated;
        the caller reports that to the user instead of blocking the GUI.
        """
        if not data:
            return True
        if not self.is_running:
            return False
        try:
            self._tx.put_nowait(bytes(data))
        except queue.Full:
            _log.warning("TX queue full, dropping %d bytes", len(data))
            self._post(
                WorkerEvent(
                    WorkerEventType.ERROR,
                    error=UserError(
                        message="The send queue is full; the device is not keeping up.",
                        hint="Reduce the auto-send rate or increase the baud rate.",
                        detail=f"tx_queue_limit={self._tx.maxsize}",
                    ),
                )
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Event consumption (GUI thread)
    # ------------------------------------------------------------------
    def poll_events(self, limit: int = 64) -> list[WorkerEvent]:
        """Drain pending lifecycle events, newest last."""
        events: list[WorkerEvent] = []
        for _ in range(max(1, limit)):
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def poll_rx(self, max_bytes: int | None = None):
        """Drain received bytes for this frame."""
        return self._aggregator.drain(max_bytes)

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------
    def _run(self) -> None:
        port = self._settings.port if self._settings else ""
        try:
            while not self._stop.is_set():
                progressed = self._pump_tx(port)
                progressed |= self._pump_rx(port)
                if not progressed and not self._stop.is_set():
                    # Nothing to do: the read timeout already provides the
                    # pacing, this only guards a zero-timeout transport.
                    time.sleep(0.001)
        except _WorkerAbortError:
            pass
        except Exception as exc:
            _log.exception("Unexpected failure in serial thread")
            self._post(
                WorkerEvent(
                    WorkerEventType.ERROR,
                    error=UserError(
                        message="The serial connection stopped because of an internal error.",
                        hint="Reconnect to continue. Details are in the log file.",
                        detail=f"{type(exc).__name__}: {exc}",
                    ),
                )
            )
        finally:
            with self._state_lock:
                self._running = False
            try:
                self._transport.close()
            except Exception:
                _log.debug("Transport close raised at thread exit", exc_info=True)

    def _pump_rx(self, port: str) -> bool:
        try:
            waiting = self._transport.in_waiting()
            want = min(max(1, waiting), READ_CHUNK_BYTES) if waiting else 1
            data = self._transport.read(want)
        except Exception as exc:
            if self._stop.is_set():
                raise _WorkerAbortError from exc
            _log.warning("Read failed on %s: %s", port, exc, exc_info=True)
            self._post(WorkerEvent(WorkerEventType.ERROR, error=map_read_error(exc, port)))
            if self._end_session():
                self._post(WorkerEvent(WorkerEventType.CLOSED, payload="read-error"))
            raise _WorkerAbortError from exc
        if data:
            self._aggregator.push(data)
            return True
        return False

    def _pump_tx(self, port: str) -> bool:
        sent_any = False
        # Bounded per iteration so a saturated TX queue cannot starve RX.
        for _ in range(32):
            try:
                frame = self._tx.get_nowait()
            except queue.Empty:
                break
            try:
                written = self._transport.write(frame)
            except Exception as exc:
                if self._stop.is_set():
                    raise _WorkerAbortError from exc
                _log.warning("Write failed on %s: %s", port, exc, exc_info=True)
                self._post(WorkerEvent(WorkerEventType.ERROR, error=map_write_error(exc, port)))
                if self._end_session():
                    self._post(WorkerEvent(WorkerEventType.CLOSED, payload="write-error"))
                raise _WorkerAbortError from exc
            self._tx_bytes += written or 0
            self._post(WorkerEvent(WorkerEventType.TX_DONE, payload=frame))
            sent_any = True
        return sent_any

    # ------------------------------------------------------------------
    def _end_session(self) -> bool:
        """Atomically claim the right to emit the CLOSED event.

        ``stop()`` and the worker thread can both decide the session is over
        (a user disconnect racing a cable being pulled out); whoever gets here
        first wins, so the UI sees exactly one CLOSED.
        """
        with self._state_lock:
            was_active = self._session_active
            self._session_active = False
        return was_active

    def _post(self, event: WorkerEvent) -> None:
        try:
            self._events.put_nowait(event)
        except queue.Full:  # pragma: no cover - unbounded queue
            _log.error("Event queue full; dropping %s", event.type)

    @staticmethod
    def _drain_queue(q: queue.Queue[Any]) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return


class _WorkerAbortError(Exception):
    """Internal signal used to unwind the worker loop cleanly."""
