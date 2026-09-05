"""Hex/ASCII codec and line-ending behaviour."""

from __future__ import annotations

import pytest

from serial_console.core.codec import (
    StreamDecoder,
    build_payload,
    decode_text,
    format_hex,
    format_hex_dump,
    parse_hex,
    to_printable_ascii,
)
from serial_console.models.enums import LineEnding
from serial_console.models.errors import ValidationError


class TestParseHex:
    @pytest.mark.parametrize(
        "text",
        ["48 65 6C 6C 6F", "48656C6C6F", "0x48 0x65 0x6c 0x6c 0x6f", "48-65-6C-6C-6F", "48,65,6c,6c,6f"],
    )
    def test_accepts_common_notations(self, text: str) -> None:
        assert parse_hex(text) == b"Hello"

    def test_empty_input_is_empty_output(self) -> None:
        assert parse_hex("") == b""
        assert parse_hex("   ") == b""

    def test_odd_digit_count_is_rejected_with_a_helpful_message(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            parse_hex("48 6")
        message = str(excinfo.value)
        assert "even number" in message
        assert "48 65 6C 6C 6F" in message  # shows an example

    def test_non_hex_characters_are_reported(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            parse_hex("48 ZZ")
        assert "not hexadecimal" in str(excinfo.value)

    def test_error_message_never_leaks_a_python_exception(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            parse_hex("nonsense")
        assert "ValueError" not in str(excinfo.value)


class TestFormatHex:
    def test_uppercase_by_default(self) -> None:
        assert format_hex(b"Hello") == "48 65 6C 6C 6F"

    def test_lowercase_and_custom_separator(self) -> None:
        assert format_hex(b"Hi", uppercase=False, separator="-") == "48-69"

    def test_round_trip(self) -> None:
        payload = bytes(range(256))
        assert parse_hex(format_hex(payload)) == payload

    def test_hex_dump_has_ascii_column(self) -> None:
        dump = format_hex_dump(b"Hello\x00world!", bytes_per_line=8)
        lines = dump.split("\n")
        assert len(lines) == 2
        assert lines[0].endswith("|Hello.wo|")
        # Short final lines stay aligned with the ones above them.
        assert len(lines[0].split("|")[0]) == len(lines[1].split("|")[0])

    def test_printable_ascii_replaces_control_bytes(self) -> None:
        assert to_printable_ascii(b"a\x00b\nc") == "a.b.c"


class TestDecodeText:
    def test_invalid_utf8_never_raises(self) -> None:
        assert decode_text(b"\xff\xfe ok") == "\ufffd\ufffd ok"

    def test_unknown_encoding_falls_back(self) -> None:
        assert decode_text(b"ok", encoding="definitely-not-a-codec") == "ok"


class TestBuildPayload:
    @pytest.mark.parametrize(
        ("ending", "expected"),
        [
            (LineEnding.NONE, b"AT+STATUS"),
            (LineEnding.LF, b"AT+STATUS\n"),
            (LineEnding.CR, b"AT+STATUS\r"),
            (LineEnding.CRLF, b"AT+STATUS\r\n"),
        ],
    )
    def test_line_endings(self, ending: LineEnding, expected: bytes) -> None:
        assert build_payload("AT+STATUS", hex_mode=False, line_ending=ending) == expected

    def test_hex_mode_uses_bytes_and_still_appends_the_terminator(self) -> None:
        assert (
            build_payload("48 65 6C 6C 6F", hex_mode=True, line_ending=LineEnding.CRLF)
            == b"Hello\r\n"
        )

    def test_hex_mode_with_no_terminator(self) -> None:
        assert build_payload("DEADBEEF", hex_mode=True, line_ending=LineEnding.NONE) == bytes.fromhex(
            "DEADBEEF"
        )

    def test_non_ascii_text_is_encoded_as_utf8(self) -> None:
        assert build_payload("café", hex_mode=False, line_ending=LineEnding.NONE) == "café".encode()

    def test_invalid_hex_propagates_a_user_facing_error(self) -> None:
        with pytest.raises(ValidationError):
            build_payload("XY", hex_mode=True, line_ending=LineEnding.LF)


class TestLineEndingEnum:
    def test_suffix_bytes(self) -> None:
        assert LineEnding.NONE.suffix == b""
        assert LineEnding.LF.suffix == b"\n"
        assert LineEnding.CR.suffix == b"\r"
        assert LineEnding.CRLF.suffix == b"\r\n"

    def test_coerce_is_tolerant(self) -> None:
        assert LineEnding.coerce("CRLF", LineEnding.NONE) is LineEnding.CRLF
        assert LineEnding.coerce("crlf", LineEnding.NONE) is LineEnding.CRLF
        assert LineEnding.coerce("CRLF (\\r\\n)", LineEnding.NONE) is LineEnding.CRLF
        assert LineEnding.coerce("garbage", LineEnding.LF) is LineEnding.LF
        assert LineEnding.coerce(None, LineEnding.LF) is LineEnding.LF

    def test_members_are_not_plain_strings(self) -> None:
        # Qt flattens str-derived enums into str when used as item data, which
        # silently breaks .value access; guard against a regression.
        assert not isinstance(LineEnding.LF, str)


class TestHexFormattingFastPaths:
    """The hex formatters run on every received byte; they were rewritten to
    use C-level primitives and must stay byte-for-byte identical."""

    @staticmethod
    def _reference_hex(data: bytes, uppercase: bool = True, separator: str = " ") -> str:
        text = separator.join(f"{byte:02x}" for byte in data)
        return text.upper() if uppercase else text

    @staticmethod
    def _reference_printable(data: bytes, placeholder: str = ".") -> str:
        import string

        printable = set(string.printable) - set("\t\n\r\x0b\x0c")
        return "".join(chr(b) if chr(b) in printable else placeholder for b in data)

    def test_format_hex_matches_the_reference(self) -> None:
        for data in (b"", b"Hello", bytes(range(256)), b"\x00\xff" * 100):
            assert format_hex(data) == self._reference_hex(data)
            assert format_hex(data, uppercase=False) == self._reference_hex(
                data, uppercase=False
            )
            assert format_hex(data, separator="-") == self._reference_hex(
                data, separator="-"
            )

    def test_printable_ascii_matches_the_reference(self) -> None:
        for data in (b"", bytes(range(256)), b"tab\there"):
            assert to_printable_ascii(data) == self._reference_printable(data)
            assert to_printable_ascii(data, "?") == self._reference_printable(data, "?")

    def test_hex_dump_columns_stay_aligned(self) -> None:
        dump = format_hex_dump(bytes(range(40)), bytes_per_line=16)
        lines = dump.splitlines()
        assert len(lines) == 3
        # The short final line must still line its ASCII column up with the rest.
        assert len({line.index("|") for line in lines}) == 1

    def test_hex_dump_of_an_empty_payload(self) -> None:
        assert format_hex_dump(b"") == ""


class TestStreamDecoding:
    """A serial port splits multi-byte characters wherever it likes."""

    PERSIAN = "دمای سنسور: ۲۴٫۸ درجه سانتی‌گراد ✓\n"

    def test_every_split_position_survives(self) -> None:
        raw = self.PERSIAN.encode()
        for cut in range(1, len(raw)):
            decoder = StreamDecoder("utf-8")
            out = decoder.decode(raw[:cut]) + decoder.decode(raw[cut:])
            assert out == self.PERSIAN, f"split at byte {cut} corrupted the text"

    def test_byte_at_a_time_is_still_correct(self) -> None:
        decoder = StreamDecoder("utf-8")
        out = "".join(decoder.decode(bytes([byte])) for byte in self.PERSIAN.encode())
        assert out == self.PERSIAN

    def test_emoji_and_cjk(self) -> None:
        for text in ("温度: 24.8°C\n", "status ✅ ok\n", "🚀 launch\n"):
            raw = text.encode()
            for cut in range(1, len(raw)):
                decoder = StreamDecoder()
                assert decoder.decode(raw[:cut]) + decoder.decode(raw[cut:]) == text

    def test_invalid_bytes_become_replacement_characters(self) -> None:
        decoder = StreamDecoder("utf-8")
        assert decoder.decode(b"ok\xff\xfe done") == "ok\ufffd\ufffd done"

    def test_a_dangling_partial_character_is_flushed_on_demand(self) -> None:
        decoder = StreamDecoder("utf-8")
        assert decoder.decode("د".encode()[:1]) == ""
        assert decoder.flush() == "\ufffd"

    def test_unknown_encoding_falls_back_to_utf8(self) -> None:
        decoder = StreamDecoder("definitely-not-a-codec")
        assert decoder.decode("سلام".encode()) == "سلام"

    def test_legacy_encodings_work_too(self) -> None:
        decoder = StreamDecoder("cp1256")
        assert decoder.decode("سلام".encode("cp1256")) == "سلام"


class TestPayloadEncoding:
    def test_persian_is_sent_as_utf8_by_default(self) -> None:
        payload = build_payload("سلام", hex_mode=False, line_ending=LineEnding.LF)
        assert payload == "سلام".encode() + b"\n"

    def test_the_terminal_encoding_is_honoured(self) -> None:
        payload = build_payload(
            "سلام", hex_mode=False, line_ending=LineEnding.NONE, encoding="cp1256"
        )
        assert payload == "سلام".encode("cp1256")

    def test_characters_the_encoding_cannot_represent_do_not_raise(self) -> None:
        payload = build_payload(
            "سلام", hex_mode=False, line_ending=LineEnding.NONE, encoding="ascii"
        )
        assert payload == b"????"

    def test_an_unknown_encoding_falls_back_instead_of_crashing(self) -> None:
        payload = build_payload(
            "hi", hex_mode=False, line_ending=LineEnding.NONE, encoding="nonsense"
        )
        assert payload == b"hi"
