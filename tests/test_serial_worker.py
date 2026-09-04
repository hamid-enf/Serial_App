"""End-to-end worker behaviour against virtual serial ports."""

from __future__ import annotations

import threading
import time

import pytest
import serial

from serial_console.core.errors import Severity
from serial_console.core.rx_aggregator import RxAggregator
from serial_console.core.serial_worker import SerialWorker, WorkerEventType
from serial_console.models.settings import SerialSettings
from serial_console.transport.loopback import LoopbackTransport, TransportClosedError


def wait_for(predicate, timeout: float = 3.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def collect_rx(worker: SerialWorker, expected: int, timeout: float = 3.0) -> bytes:
    """Drain the aggregator until ``expected`` bytes have been seen."""
    buffer = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(buffer) < expected:
        buffer.extend(worker.poll_rx().data)
        time.sleep(0.005)
    return bytes(buffer)


def event_types(worker: SerialWorker) -> list[WorkerEventType]:
    return [event.type for event in worker.poll_events()]


@pytest.fixture()
def settings() -> SerialSettings:
    return SerialSettings(port="VIRTUAL", baud_rate=115200, read_timeout_s=0.01)


class TestLifecycle:
    def test_start_opens_the_port_and_reports_opened(
        self, settings: SerialSettings
    ) -> None:
        worker = SerialWorker(LoopbackTransport())
        try:
            assert worker.start(settings) is True
            assert worker.is_running
            assert WorkerEventType.OPENED in event_types(worker)
        finally:
            worker.stop()

    def test_stop_closes_the_port_and_reports_closed(
        self, settings: SerialSettings
    ) -> None:
        transport = LoopbackTransport()
        worker = SerialWorker(transport)
        worker.start(settings)
        worker.poll_events()
        worker.stop()
        assert worker.is_running is False
        assert transport.is_open is False
        assert WorkerEventType.CLOSED in event_types(worker)

    def test_stop_is_idempotent(self, settings: SerialSettings) -> None:
        worker = SerialWorker(LoopbackTransport())
        worker.start(settings)
        worker.stop()
        worker.stop()  # must not raise

    def test_restart_reuses_the_worker(self, settings: SerialSettings) -> None:
        worker = SerialWorker(LoopbackTransport())
        try:
            assert worker.start(settings)
            assert worker.start(settings)  # implicit stop then start
            assert worker.is_running
        finally:
            worker.stop()

    def test_no_thread_survives_stop(self, settings: SerialSettings) -> None:
        before = threading.active_count()
        worker = SerialWorker(LoopbackTransport())
        worker.start(settings)
        assert threading.active_count() > before
        worker.stop()
        assert wait_for(lambda: threading.active_count() == before)


class TestDataFlow:
    def test_received_bytes_reach_the_aggregator(self, settings: SerialSettings) -> None:
        transport = LoopbackTransport(echo=False)
        worker = SerialWorker(transport)
        worker.start(settings)
        try:
            transport.feed(b"hello world")
            assert collect_rx(worker, 11) == b"hello world"
        finally:
            worker.stop()

    def test_send_writes_to_the_port(self, settings: SerialSettings) -> None:
        transport = LoopbackTransport(echo=False)
        worker = SerialWorker(transport)
        worker.start(settings)
        try:
            assert worker.send(b"AT+STATUS\r\n") is True
            assert wait_for(lambda: transport.written == b"AT+STATUS\r\n")
        finally:
            worker.stop()

    def test_tx_done_event_is_emitted(self, settings: SerialSettings) -> None:
        worker = SerialWorker(LoopbackTransport(echo=False))
        worker.start(settings)
        try:
            worker.send(b"PING")
            assert wait_for(lambda: WorkerEventType.TX_DONE in event_types(worker))
        finally:
            worker.stop()

    def test_loopback_echo_round_trip(self, settings: SerialSettings) -> None:
        worker = SerialWorker(LoopbackTransport(echo=True))
        worker.start(settings)
        try:
            worker.send(b"ECHO\n")
            assert collect_rx(worker, 5) == b"ECHO\n"
        finally:
            worker.stop()

    def test_responder_simulates_a_device(self, settings: SerialSettings) -> None:
        def responder(data: bytes) -> bytes:
            return b"OK\r\n" if data.startswith(b"AT") else b"ERROR\r\n"

        worker = SerialWorker(LoopbackTransport(echo=False, responder=responder))
        worker.start(settings)
        try:
            worker.send(b"AT+STATUS\r\n")
            assert collect_rx(worker, 4) == b"OK\r\n"
        finally:
            worker.stop()

    def test_send_is_rejected_when_disconnected(self, settings: SerialSettings) -> None:
        worker = SerialWorker(LoopbackTransport())
        assert worker.send(b"data") is False

    def test_empty_send_is_a_no_op(self, settings: SerialSettings) -> None:
        worker = SerialWorker(LoopbackTransport())
        assert worker.send(b"") is True

    def test_counters_track_traffic(self, settings: SerialSettings) -> None:
        transport = LoopbackTransport(echo=False)
        worker = SerialWorker(transport)
        worker.start(settings)
        try:
            worker.send(b"12345")
            transport.feed(b"abc")
            assert wait_for(lambda: worker.tx_bytes == 5)
            collect_rx(worker, 3)
            assert worker.rx_bytes == 3
            worker.reset_counters()
            assert worker.tx_bytes == 0 and worker.rx_bytes == 0
        finally:
            worker.stop()


class TestHighThroughput:
    def test_one_megabyte_burst_is_not_lost(self, settings: SerialSettings) -> None:
        transport = LoopbackTransport(echo=False)
        worker = SerialWorker(transport)
        worker.start(settings)
        try:
            payload = bytes(range(256)) * 4096  # 1 MiB
            transport.feed(payload)
            received = collect_rx(worker, len(payload), timeout=20.0)
            assert len(received) == len(payload)
            assert received == payload
        finally:
            worker.stop()

    def test_continuous_stream_keeps_memory_bounded(
        self, settings: SerialSettings
    ) -> None:
        transport = LoopbackTransport(echo=False)
        aggregator = RxAggregator(ceiling_bytes=64 * 1024)
        worker = SerialWorker(transport, aggregator=aggregator)
        worker.start(settings)
        try:
            for _ in range(40):
                transport.feed(b"x" * 8192)
                time.sleep(0.002)
            # Nothing drains the aggregator here: the ceiling must hold.
            assert wait_for(lambda: aggregator.pending() > 0)
            assert aggregator.pending() <= aggregator.ceiling_bytes
        finally:
            worker.stop()

    def test_saturated_tx_queue_reports_instead_of_blocking(
        self, settings: SerialSettings
    ) -> None:
        # A transport that never accepts data, so the queue backs up.
        blocked = threading.Event()

        class StalledTransport(LoopbackTransport):
            def write(self, data: bytes) -> int:
                blocked.wait(0.2)
                return len(data)

        worker = SerialWorker(StalledTransport(echo=False), tx_queue_limit=4)
        worker.start(settings)
        try:
            results = [worker.send(b"x") for _ in range(200)]
            assert False in results  # back-pressure surfaced to the caller
            errors = [e for e in worker.poll_events(limit=500) if e.type is WorkerEventType.ERROR]
            assert errors
            assert "send queue is full" in errors[0].error.message
        finally:
            blocked.set()
            worker.stop()


class TestErrorHandling:
    def test_open_failure_is_reported_as_a_user_error(self, settings: SerialSettings) -> None:
        transport = LoopbackTransport(
            fail_on_open=serial.SerialException(
                "could not open port COM5: Access is denied."
            )
        )
        worker = SerialWorker(transport)
        assert worker.start(settings) is False
        errors = [e for e in worker.poll_events() if e.type is WorkerEventType.ERROR]
        assert errors
        message = errors[0].error.message
        assert "in use by another application" in message
        assert "SerialException" not in message  # never a raw exception

    def test_invalid_configuration_is_reported_clearly(
        self, settings: SerialSettings
    ) -> None:
        worker = SerialWorker(LoopbackTransport(fail_on_open=ValueError("bad baudrate")))
        assert worker.start(settings) is False
        error = next(e for e in worker.poll_events() if e.type is WorkerEventType.ERROR).error
        assert "not valid" in error.message

    def test_missing_port_is_reported_clearly(self, settings: SerialSettings) -> None:
        worker = SerialWorker(LoopbackTransport(fail_on_open=FileNotFoundError("nope")))
        assert worker.start(settings) is False
        error = next(e for e in worker.poll_events() if e.type is WorkerEventType.ERROR).error
        assert "not available" in error.message
        assert "Refresh Ports" in error.hint

    def test_read_failure_closes_the_connection_without_crashing(
        self, settings: SerialSettings
    ) -> None:
        transport = LoopbackTransport(fail_on_read=OSError(5, "Input/output error"))
        worker = SerialWorker(transport)
        worker.start(settings)
        assert wait_for(lambda: not worker.is_running)
        types = event_types(worker)
        assert WorkerEventType.ERROR in types
        assert WorkerEventType.CLOSED in types
        worker.stop()

    def test_device_unplugged_mid_session_is_explained(
        self, settings: SerialSettings
    ) -> None:
        transport = LoopbackTransport()
        worker = SerialWorker(transport)
        worker.start(settings)
        worker.poll_events()
        transport._fail_on_read = serial.SerialException(
            "device reports readiness to read but returned no data"
        )
        assert wait_for(lambda: not worker.is_running)
        errors = [e for e in worker.poll_events() if e.type is WorkerEventType.ERROR]
        assert errors
        assert "disconnected" in errors[0].error.message
        assert errors[0].error.severity is Severity.WARNING
        worker.stop()

    def test_write_failure_is_reported_and_closes(self, settings: SerialSettings) -> None:
        transport = LoopbackTransport()
        worker = SerialWorker(transport)
        worker.start(settings)
        worker.poll_events()
        transport._fail_on_write = TransportClosedError(
            "handle is invalid"
        )
        worker.send(b"data")
        assert wait_for(lambda: not worker.is_running)
        errors = [e for e in worker.poll_events() if e.type is WorkerEventType.ERROR]
        assert errors
        assert "disconnected while sending" in errors[0].error.message
        worker.stop()

    def test_write_timeout_gets_a_flow_control_hint(self, settings: SerialSettings) -> None:
        transport = LoopbackTransport()
        worker = SerialWorker(transport)
        worker.start(settings)
        transport._fail_on_write = serial.SerialTimeoutException(
            "Write timeout"
        )
        worker.send(b"data")
        assert wait_for(lambda: not worker.is_running)
        errors = [e for e in worker.poll_events() if e.type is WorkerEventType.ERROR]
        assert "timed out" in errors[0].error.message
        assert "CTS" in errors[0].error.hint
        worker.stop()

    def test_exactly_one_closed_event_when_a_fault_races_with_stop(
        self, settings: SerialSettings
    ) -> None:
        # The thread detects the fault and posts CLOSED; the user then presses
        # Disconnect. The UI must not see two CLOSED events.
        transport = LoopbackTransport(fail_on_read=OSError(5, "Input/output error"))
        worker = SerialWorker(transport)
        worker.start(settings)
        assert wait_for(lambda: not worker.is_running)
        worker.stop()
        closes = [t for t in event_types(worker) if t is WorkerEventType.CLOSED]
        assert len(closes) == 1

    def test_worker_never_raises_into_the_caller(self, settings: SerialSettings) -> None:
        # Every failure mode above returns False / posts an event instead of
        # propagating; assert the contract explicitly for a hostile transport.
        worker = SerialWorker(LoopbackTransport(fail_on_open=RuntimeError("boom")))
        assert worker.start(settings) is False
        worker.stop()
