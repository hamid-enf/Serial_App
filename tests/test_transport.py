"""Tests for the pyserial adapter and port enumeration.

``serial.Serial`` is replaced by a recording fake, so the real driver stack is
never touched: what is under test is the translation of our settings into
pyserial's vocabulary and the defensive behaviour around a misbehaving driver.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

import pytest
import serial

from serial_console.models.enums import DataBits, FlowControl, Parity, StopBits
from serial_console.models.settings import SerialSettings
from serial_console.transport.ports import PortInfo, list_ports
from serial_console.transport.serial_transport import SerialTransport, build_serial_kwargs


class FakeSerial:
    """Stand-in for ``serial.Serial`` that records what the adapter did."""

    instances: ClassVar[list[FakeSerial]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.port = kwargs.get("port")
        self.is_open = False
        self.dtr = None
        self.rts = None
        self.written = bytearray()
        self.to_read = bytearray()
        self.in_waiting = 0
        self.flush_calls = 0
        self.reset_input_calls = 0
        self.reset_output_calls = 0
        self.close_calls = 0
        self.fail_on: dict[str, BaseException] = {}
        FakeSerial.instances.append(self)

    def _maybe_fail(self, name: str) -> None:
        exc = self.fail_on.get(name)
        if exc is not None:
            raise exc

    def open(self) -> None:
        self._maybe_fail("open")
        self.is_open = True

    def close(self) -> None:
        self.close_calls += 1
        self._maybe_fail("close")
        self.is_open = False

    def read(self, size: int) -> bytes:
        self._maybe_fail("read")
        chunk = bytes(self.to_read[:size])
        del self.to_read[: len(chunk)]
        return chunk

    def write(self, data: bytes) -> int:
        self._maybe_fail("write")
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        self.flush_calls += 1
        self._maybe_fail("flush")

    def reset_input_buffer(self) -> None:
        self.reset_input_calls += 1
        self._maybe_fail("reset_input_buffer")

    def reset_output_buffer(self) -> None:
        self.reset_output_calls += 1
        self._maybe_fail("reset_output_buffer")


@pytest.fixture()
def fake_serial(monkeypatch: pytest.MonkeyPatch) -> type[FakeSerial]:
    FakeSerial.instances = []
    monkeypatch.setattr(
        "serial_console.transport.serial_transport.serial.Serial", FakeSerial
    )
    return FakeSerial


@pytest.fixture()
def settings() -> SerialSettings:
    return SerialSettings(port="COM7", baud_rate=115200)


# ----------------------------------------------------------------------
class TestBuildSerialKwargs:
    def test_port_is_deferred_so_control_lines_can_be_set_first(self, settings) -> None:
        # Handing the port to the constructor would open it immediately, which
        # pulses DTR and resets boards that wire it to the reset pin.
        assert build_serial_kwargs(settings)["port"] is None

    def test_framing_is_mapped_to_pyserial_constants(self) -> None:
        settings = SerialSettings(
            port="COM1",
            baud_rate=9600,
            data_bits=DataBits.SEVEN,
            parity=Parity.EVEN,
            stop_bits=StopBits.TWO,
        )
        kwargs = build_serial_kwargs(settings)
        assert kwargs["baudrate"] == 9600
        assert kwargs["bytesize"] == serial.SEVENBITS
        assert kwargs["parity"] == serial.PARITY_EVEN
        assert kwargs["stopbits"] == serial.STOPBITS_TWO

    @pytest.mark.parametrize(
        ("flow", "expected"),
        [
            (FlowControl.NONE, {"xonxoff": False, "rtscts": False, "dsrdtr": False}),
            (FlowControl.XON_XOFF, {"xonxoff": True, "rtscts": False, "dsrdtr": False}),
            (FlowControl.RTS_CTS, {"xonxoff": False, "rtscts": True, "dsrdtr": False}),
            (FlowControl.DSR_DTR, {"xonxoff": False, "rtscts": False, "dsrdtr": True}),
        ],
    )
    def test_only_one_flow_control_scheme_is_ever_enabled(self, flow, expected) -> None:
        # pyserial explicitly warns against combining xonxoff with rtscts.
        kwargs = build_serial_kwargs(SerialSettings(port="COM1", flow_control=flow))
        for key, value in expected.items():
            assert kwargs[key] is value

    def test_timeouts_are_floats(self, settings) -> None:
        kwargs = build_serial_kwargs(settings)
        assert isinstance(kwargs["timeout"], float)
        assert isinstance(kwargs["write_timeout"], float)


# ----------------------------------------------------------------------
class TestOpenClose:
    def test_open_applies_port_and_control_lines_before_opening(
        self, fake_serial, settings
    ) -> None:
        settings.dtr, settings.rts = False, True
        transport = SerialTransport()
        transport.open(settings)

        handle = fake_serial.instances[-1]
        assert handle.port == "COM7"
        assert handle.dtr is False
        assert handle.rts is True
        assert handle.is_open is True
        assert transport.is_open is True

    def test_open_flushes_stale_bytes(self, fake_serial, settings) -> None:
        SerialTransport().open(settings)
        handle = fake_serial.instances[-1]
        assert handle.reset_input_calls == 1
        assert handle.reset_output_calls == 1

    def test_a_driver_that_rejects_control_lines_does_not_abort_the_open(
        self, fake_serial, settings
    ) -> None:
        transport = SerialTransport()
        original_init = FakeSerial.__init__

        def init_with_readonly_dtr(self, **kwargs):
            original_init(self, **kwargs)
            type(self).dtr = property(
                lambda s: None,
                lambda s, v: (_ for _ in ()).throw(OSError("not supported")),
            )

        try:
            fake_serial.__init__ = init_with_readonly_dtr
            transport.open(settings)
            assert transport.is_open is True
        finally:
            fake_serial.__init__ = original_init
            if hasattr(FakeSerial, "dtr") and isinstance(FakeSerial.dtr, property):
                del FakeSerial.dtr

    def test_a_flush_failure_does_not_abort_the_open(self, fake_serial, settings) -> None:
        class FlakyFlush(FakeSerial):
            def reset_input_buffer(self) -> None:
                raise serial.SerialException("device reports readiness but not ready")

        transport = SerialTransport()
        FakeSerial.instances = []
        import serial_console.transport.serial_transport as module

        module.serial.Serial = FlakyFlush  # type: ignore[attr-defined]
        try:
            transport.open(settings)
            assert transport.is_open is True
        finally:
            module.serial.Serial = FakeSerial  # type: ignore[attr-defined]

    def test_open_raises_what_pyserial_raises(self, fake_serial, settings) -> None:
        class Refusing(FakeSerial):
            def open(self) -> None:
                raise serial.SerialException("Access is denied.")

        import serial_console.transport.serial_transport as module

        module.serial.Serial = Refusing  # type: ignore[attr-defined]
        try:
            with pytest.raises(serial.SerialException):
                SerialTransport().open(settings)
        finally:
            module.serial.Serial = FakeSerial  # type: ignore[attr-defined]

    def test_open_replaces_a_previous_handle(self, fake_serial, settings) -> None:
        transport = SerialTransport()
        transport.open(settings)
        first = fake_serial.instances[-1]
        transport.open(settings)
        assert first.close_calls == 1
        assert transport.is_open is True

    def test_close_is_idempotent(self, fake_serial, settings) -> None:
        transport = SerialTransport()
        transport.open(settings)
        transport.close()
        transport.close()
        assert transport.is_open is False

    def test_close_swallows_a_dying_driver(self, fake_serial, settings) -> None:
        transport = SerialTransport()
        transport.open(settings)
        fake_serial.instances[-1].fail_on["close"] = OSError("device disappeared")
        transport.close()  # must not raise: the handle is dead either way
        assert transport.is_open is False

    def test_describe_reports_the_open_port(self, fake_serial, settings) -> None:
        transport = SerialTransport()
        assert transport.describe() == ""
        transport.open(settings)
        assert "COM7" in transport.describe()


# ----------------------------------------------------------------------
class TestIo:
    def test_read_and_write(self, fake_serial, settings) -> None:
        transport = SerialTransport()
        transport.open(settings)
        handle = fake_serial.instances[-1]
        handle.to_read.extend(b"hello")

        assert transport.read(1024) == b"hello"
        assert transport.write(b"AT\r\n") == 4
        assert bytes(handle.written) == b"AT\r\n"

    def test_read_asks_for_at_least_one_byte(self, fake_serial, settings) -> None:
        # A zero-size read would spin the worker loop at 100% CPU.
        captured: list[int] = []

        class Recording(FakeSerial):
            def read(self, size: int) -> bytes:
                captured.append(size)
                return b""

        import serial_console.transport.serial_transport as module

        module.serial.Serial = Recording  # type: ignore[attr-defined]
        try:
            transport = SerialTransport()
            transport.open(settings)
            transport.read(0)
            transport.read(-5)
        finally:
            module.serial.Serial = FakeSerial  # type: ignore[attr-defined]
        assert captured == [1, 1]

    def test_write_returning_none_counts_as_zero(self, fake_serial, settings) -> None:
        class NoneWriter(FakeSerial):
            def write(self, data: bytes) -> None:  # some backends return None
                return None

        import serial_console.transport.serial_transport as module

        module.serial.Serial = NoneWriter  # type: ignore[attr-defined]
        try:
            transport = SerialTransport()
            transport.open(settings)
            assert transport.write(b"x") == 0
        finally:
            module.serial.Serial = FakeSerial  # type: ignore[attr-defined]

    def test_io_on_a_closed_port_raises_a_serial_exception(self, fake_serial) -> None:
        transport = SerialTransport()
        with pytest.raises(serial.SerialException):
            transport.read(16)
        with pytest.raises(serial.SerialException):
            transport.write(b"x")

    def test_in_waiting_reports_zero_when_closed_or_broken(
        self, fake_serial, settings
    ) -> None:
        transport = SerialTransport()
        assert transport.in_waiting() == 0

        transport.open(settings)
        handle = fake_serial.instances[-1]
        handle.in_waiting = 12
        assert transport.in_waiting() == 12

        # Drivers commonly raise here in the moment before a disconnect is
        # detected; the following read surfaces the real error instead.
        type(handle).in_waiting = property(
            lambda s: (_ for _ in ()).throw(OSError("ClearCommError failed"))
        )
        try:
            assert transport.in_waiting() == 0
        finally:
            del type(handle).in_waiting

    def test_flush_is_safe_when_closed_and_when_it_fails(
        self, fake_serial, settings
    ) -> None:
        transport = SerialTransport()
        transport.flush()  # closed: no-op

        transport.open(settings)
        transport.flush()
        handle = fake_serial.instances[-1]
        assert handle.flush_calls == 1

        handle.fail_on["flush"] = serial.SerialException("write failed")
        transport.flush()  # must not propagate

    def test_set_control_lines(self, fake_serial, settings) -> None:
        transport = SerialTransport()
        transport.set_control_lines(dtr=True)  # closed: no-op

        transport.open(settings)
        transport.set_control_lines(dtr=False, rts=False)
        handle = fake_serial.instances[-1]
        assert handle.dtr is False
        assert handle.rts is False

        transport.set_control_lines(rts=True)
        assert handle.rts is True
        assert handle.dtr is False  # untouched when not specified

    def test_set_control_lines_survives_a_driver_refusal(
        self, fake_serial, settings
    ) -> None:
        transport = SerialTransport()
        transport.open(settings)
        handle = fake_serial.instances[-1]
        type(handle).rts = property(
            lambda s: None, lambda s, v: (_ for _ in ()).throw(OSError("EIO"))
        )
        try:
            transport.set_control_lines(rts=True)  # must not raise
        finally:
            del type(handle).rts


# ----------------------------------------------------------------------
class TestPortEnumeration:
    def _fake_comports(self, monkeypatch: pytest.MonkeyPatch, items) -> None:
        from serial.tools import list_ports as pyserial_list_ports

        monkeypatch.setattr(pyserial_list_ports, "comports", lambda: items)

    def test_ports_are_mapped_and_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_comports(
            monkeypatch,
            [
                SimpleNamespace(
                    device="COM3",
                    description="  USB-SERIAL CH340  ",
                    hwid=" USB VID:PID=1A86:7523 ",
                    manufacturer=" wch.cn ",
                )
            ],
        )
        (port,) = list_ports()
        assert port.device == "COM3"
        assert port.description == "USB-SERIAL CH340"
        assert port.hwid == "USB VID:PID=1A86:7523"
        assert port.manufacturer == "wch.cn"

    def test_sorting_is_natural_not_lexicographic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fake_comports(
            monkeypatch,
            [
                SimpleNamespace(device=name, description="", hwid="", manufacturer="")
                for name in ("COM10", "COM2", "COM1", "ttyUSB0")
            ],
        )
        assert [p.device for p in list_ports()] == ["COM1", "COM2", "COM10", "ttyUSB0"]

    def test_entries_without_a_device_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fake_comports(
            monkeypatch,
            [
                SimpleNamespace(device="", description="ghost", hwid="", manufacturer=""),
                SimpleNamespace(device="COM4", description="", hwid="", manufacturer=""),
            ],
        )
        assert [p.device for p in list_ports()] == ["COM4"]

    def test_a_raising_driver_degrades_to_an_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from serial.tools import list_ports as pyserial_list_ports

        def boom():
            raise OSError("The device is not ready")

        monkeypatch.setattr(pyserial_list_ports, "comports", boom)
        assert list_ports() == []  # the UI must not break because a driver did


class TestPortInfoDisplay:
    def test_description_is_appended(self) -> None:
        assert (
            PortInfo("COM5", "Silicon Labs CP210x").display_name()
            == "COM5 — Silicon Labs CP210x"
        )

    def test_manufacturer_is_the_fallback(self) -> None:
        assert PortInfo("COM5", "", manufacturer="FTDI").display_name() == "COM5 — FTDI"

    @pytest.mark.parametrize("noise", ["", "n/a", "N/A", "unknown", "Unknown"])
    def test_useless_descriptions_are_dropped(self, noise: str) -> None:
        assert PortInfo("COM5", noise).display_name() == "COM5"
