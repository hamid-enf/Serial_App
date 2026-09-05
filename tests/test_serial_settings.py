"""Serial configuration validation and the pyserial parameter mapping."""

from __future__ import annotations

import pytest
import serial

from serial_console.models.enums import DataBits, FlowControl, Parity, StopBits
from serial_console.models.errors import ValidationError
from serial_console.models.settings import (
    MAX_BAUD,
    MIN_BAUD,
    AppearanceSettings,
    CommandSettings,
    SerialSettings,
    TerminalSettings,
)
from serial_console.transport.serial_transport import build_serial_kwargs


class TestSerialSettingsValidation:
    def test_missing_port_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Select a COM port"):
            SerialSettings(port="").validate()

    @pytest.mark.parametrize("baud", [0, -1, MIN_BAUD - 1, MAX_BAUD + 1])
    def test_out_of_range_baud_is_rejected(self, baud: int) -> None:
        with pytest.raises(ValidationError, match="Baud rate"):
            SerialSettings(port="COM1", baud_rate=baud).validate()

    @pytest.mark.parametrize("baud", [300, 9600, 115200, 921600, 2000000, 3000000])
    def test_common_baud_rates_are_accepted(self, baud: int) -> None:
        SerialSettings(port="COM1", baud_rate=baud).validate()

    def test_five_data_bits_with_two_stop_bits_is_rejected(self) -> None:
        settings = SerialSettings(
            port="COM1", data_bits=DataBits.FIVE, stop_bits=StopBits.TWO
        )
        with pytest.raises(ValidationError, match="5 data bits"):
            settings.validate()

    def test_one_and_a_half_stop_bits_requires_five_data_bits(self) -> None:
        settings = SerialSettings(
            port="COM1", data_bits=DataBits.EIGHT, stop_bits=StopBits.ONE_POINT_FIVE
        )
        with pytest.raises(ValidationError, match="1.5 stop bits"):
            settings.validate()
        settings.data_bits = DataBits.FIVE
        settings.validate()

    def test_describe_is_the_conventional_shorthand(self) -> None:
        settings = SerialSettings(port="COM5", baud_rate=115200)
        assert settings.describe() == "COM5 @ 115200 8N1"

    def test_describe_reflects_parity_and_stop_bits(self) -> None:
        settings = SerialSettings(
            port="COM5", baud_rate=9600, parity=Parity.EVEN, stop_bits=StopBits.TWO
        )
        assert settings.describe() == "COM5 @ 9600 8E2"


class TestPySerialMapping:
    def test_defaults_map_to_8n1(self) -> None:
        kwargs = build_serial_kwargs(SerialSettings(port="COM1"))
        assert kwargs["baudrate"] == 115200
        assert kwargs["bytesize"] == serial.EIGHTBITS
        assert kwargs["parity"] == serial.PARITY_NONE
        assert kwargs["stopbits"] == serial.STOPBITS_ONE

    @pytest.mark.parametrize(
        ("parity", "expected"),
        [
            (Parity.NONE, serial.PARITY_NONE),
            (Parity.EVEN, serial.PARITY_EVEN),
            (Parity.ODD, serial.PARITY_ODD),
            (Parity.MARK, serial.PARITY_MARK),
            (Parity.SPACE, serial.PARITY_SPACE),
        ],
    )
    def test_parity_mapping(self, parity: Parity, expected: str) -> None:
        kwargs = build_serial_kwargs(SerialSettings(port="COM1", parity=parity))
        assert kwargs["parity"] == expected

    @pytest.mark.parametrize(
        ("bits", "expected"),
        [
            (DataBits.FIVE, serial.FIVEBITS),
            (DataBits.SIX, serial.SIXBITS),
            (DataBits.SEVEN, serial.SEVENBITS),
            (DataBits.EIGHT, serial.EIGHTBITS),
        ],
    )
    def test_data_bits_mapping(self, bits: DataBits, expected: int) -> None:
        settings = SerialSettings(port="COM1", data_bits=bits)
        assert build_serial_kwargs(settings)["bytesize"] == expected

    @pytest.mark.parametrize(
        ("stop", "expected"),
        [
            (StopBits.ONE, serial.STOPBITS_ONE),
            (StopBits.ONE_POINT_FIVE, serial.STOPBITS_ONE_POINT_FIVE),
            (StopBits.TWO, serial.STOPBITS_TWO),
        ],
    )
    def test_stop_bits_mapping(self, stop: StopBits, expected: float) -> None:
        settings = SerialSettings(port="COM1", data_bits=DataBits.FIVE, stop_bits=stop)
        assert build_serial_kwargs(settings)["stopbits"] == expected

    @pytest.mark.parametrize(
        ("flow", "flags"),
        [
            (FlowControl.NONE, {"xonxoff": False, "rtscts": False, "dsrdtr": False}),
            (FlowControl.XON_XOFF, {"xonxoff": True, "rtscts": False, "dsrdtr": False}),
            (FlowControl.RTS_CTS, {"xonxoff": False, "rtscts": True, "dsrdtr": False}),
            (FlowControl.DSR_DTR, {"xonxoff": False, "rtscts": False, "dsrdtr": True}),
        ],
    )
    def test_flow_control_mapping(self, flow: FlowControl, flags: dict) -> None:
        kwargs = build_serial_kwargs(SerialSettings(port="COM1", flow_control=flow))
        for key, value in flags.items():
            assert kwargs[key] is value

    def test_port_is_opened_explicitly_not_in_the_constructor(self) -> None:
        # Passing port=None keeps the constructor from opening the device before
        # DTR/RTS have been applied.
        assert build_serial_kwargs(SerialSettings(port="COM1"))["port"] is None

    def test_timeouts_are_propagated(self) -> None:
        settings = SerialSettings(port="COM1", read_timeout_s=0.2, write_timeout_s=3.5)
        kwargs = build_serial_kwargs(settings)
        assert kwargs["timeout"] == pytest.approx(0.2)
        assert kwargs["write_timeout"] == pytest.approx(3.5)


class TestOtherSettings:
    def test_terminal_buffer_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TerminalSettings(max_buffer_bytes=10).validate()

    def test_appearance_font_bounds(self) -> None:
        with pytest.raises(ValidationError, match="Font size"):
            AppearanceSettings(font_size=99).validate()

    def test_appearance_column_bounds(self) -> None:
        with pytest.raises(ValidationError, match="columns"):
            AppearanceSettings(command_button_columns=0).validate()

    def test_history_bounds(self) -> None:
        with pytest.raises(ValidationError, match="History size"):
            CommandSettings(history_limit=-1).validate()

    def test_from_dict_clamps_hostile_values(self) -> None:
        terminal = TerminalSettings.from_dict({"max_buffer_bytes": 10**12})
        terminal.validate()
        appearance = AppearanceSettings.from_dict({"font_size": 1000})
        appearance.validate()
