"""Encoding helpers: hex parsing/formatting and payload construction.

Keeping this logic in one small, dependency-free module means the hex feature
never leaks into the text path: :func:`build_payload` is the single place where
"what the user typed" becomes "bytes on the wire".
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

from ..models.enums import LineEnding
from ..models.errors import ValidationError

_HEX_SEPARATORS = re.compile(r"[\s,;:_\-]+")
_HEX_PREFIX = re.compile(r"^0[xX]")

#: Characters rendered verbatim in the ASCII column of a hex dump.
_PRINTABLE = set(string.printable) - set("\t\n\r\x0b\x0c")


def parse_hex(text: str) -> bytes:
    """Parse a permissive hex string into bytes.

    Accepts ``"48 65 6C 6C 6F"``, ``"48656C6C6F"``, ``"0x48,0x65"`` and
    ``"48-65-6c"``.  Raises :class:`ValidationError` with an actionable message
    when the input is not valid hex.
    """
    if text is None:
        return b""
    cleaned = _HEX_SEPARATORS.sub(" ", text.strip())
    if not cleaned:
        return b""

    tokens = [_HEX_PREFIX.sub("", token) for token in cleaned.split(" ") if token]
    joined = "".join(tokens)
    if not joined:
        return b""
    invalid = {ch for ch in joined if ch not in string.hexdigits}
    if invalid:
        bad = ", ".join(sorted(repr(ch) for ch in invalid))
        raise ValidationError(
            f"Hex input contains characters that are not hexadecimal digits: {bad}."
        )
    if len(joined) % 2 != 0:
        raise ValidationError(
            "Hex input must contain an even number of digits "
            f"(got {len(joined)}). Example: 48 65 6C 6C 6F"
        )
    return bytes.fromhex(joined)


def format_hex(data: bytes, *, uppercase: bool = True, separator: str = " ") -> str:
    """Render ``data`` as ``48 65 6C 6C 6F``."""
    text = separator.join(f"{byte:02x}" for byte in data)
    return text.upper() if uppercase else text


def format_hex_dump(data: bytes, *, bytes_per_line: int = 16, uppercase: bool = True) -> str:
    """Render a classic ``hex | ascii`` dump without an offset column.

    The offset column is intentionally omitted: in a streaming terminal the
    offset resets are meaningless and just add noise.
    """
    if bytes_per_line <= 0:
        bytes_per_line = 16
    lines: list[str] = []
    for start in range(0, len(data), bytes_per_line):
        chunk = data[start : start + bytes_per_line]
        hex_part = format_hex(chunk, uppercase=uppercase)
        pad = "   " * (bytes_per_line - len(chunk))
        lines.append(f"{hex_part}{pad}  |{to_printable_ascii(chunk)}|")
    return "\n".join(lines)


def to_printable_ascii(data: bytes, placeholder: str = ".") -> str:
    """Map bytes to printable ASCII, replacing control bytes with ``.``."""
    return "".join(chr(b) if chr(b) in _PRINTABLE else placeholder for b in data)


def decode_text(data: bytes, encoding: str = "utf-8") -> str:
    """Decode bytes for display, never raising on malformed input."""
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        # Unknown codec in a hand-edited config: fall back rather than crash.
        return data.decode("utf-8", errors="replace")


def build_payload(text: str, *, hex_mode: bool, line_ending: LineEnding) -> bytes:
    """Turn user input into the exact byte sequence to transmit.

    In hex mode the line ending is still appended, because devices that accept
    binary framing often still expect a terminator; users who do not want one
    select ``None``.
    """
    payload = parse_hex(text) if hex_mode else text.encode("utf-8", errors="replace")
    return payload + line_ending.suffix


def split_lines_keepends(data: bytes) -> Iterable[bytes]:
    """Split on CR, LF or CRLF while preserving the terminator."""
    return data.splitlines(keepends=True)
