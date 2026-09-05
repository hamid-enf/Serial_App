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

#: 256-entry translation table for the ASCII column: printable bytes map to
#: themselves, everything else to ``.``.  Built once so the dump loop can use
#: :meth:`bytes.translate` instead of a per-byte Python comprehension.
_ASCII_TABLE = bytes(b if chr(b) in _PRINTABLE else 0x2E for b in range(256))


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
    """Render ``data`` as ``48 65 6C 6C 6F``.

    This runs on every received byte in Hex display mode, so it delegates to
    :meth:`bytes.hex`, which formats in C. The obvious Python version
    (``separator.join(f"{b:02x}" for b in data)``) is ~30× slower and was
    costing whole milliseconds per frame at high baud rates.
    """
    if not data:
        return ""
    if len(separator) == 1:
        text = data.hex(separator)
    else:  # pragma: no cover - only reachable through a custom separator
        text = separator.join(data.hex()[i : i + 2] for i in range(0, len(data) * 2, 2))
    return text.upper() if uppercase else text


def format_hex_dump(data: bytes, *, bytes_per_line: int = 16, uppercase: bool = True) -> str:
    """Render a classic ``hex | ascii`` dump without an offset column.

    The offset column is intentionally omitted: in a streaming terminal the
    offset resets are meaningless and just add noise.

    Both halves of every line are produced by C-level primitives
    (:meth:`bytes.hex` and :meth:`bytes.translate`); at 16 bytes per line this
    is the single most expensive display mode, so the inner loop does no
    per-byte Python work at all.
    """
    if bytes_per_line <= 0:
        bytes_per_line = 16
    if not data:
        return ""
    width = bytes_per_line * 3 - 1
    lines: list[str] = []
    for start in range(0, len(data), bytes_per_line):
        piece = data[start : start + bytes_per_line]
        hex_part = piece.hex(" ")
        if uppercase:
            hex_part = hex_part.upper()
        ascii_part = piece.translate(_ASCII_TABLE).decode("ascii")
        lines.append(f"{hex_part:<{width}}  |{ascii_part}|")
    return "\n".join(lines)


def to_printable_ascii(data: bytes, placeholder: str = ".") -> str:
    """Map bytes to printable ASCII, replacing control bytes with ``.``."""
    if placeholder == ".":
        return data.translate(_ASCII_TABLE).decode("ascii")
    table = bytes(
        b if chr(b) in _PRINTABLE else ord(placeholder[0]) for b in range(256)
    )
    return data.translate(table).decode("latin-1")


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
