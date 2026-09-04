"""Bounded terminal scrollback shared by the view and the exporters.

The buffer is the single source of truth for what the terminal "contains".
It stores raw bytes grouped into timestamped chunks and enforces a byte budget,
so a multi-day capture session has a flat memory profile.  The Qt view renders
incrementally from the same chunks, which means switching between ASCII and Hex
can re-render existing history instead of only affecting new data.
"""

from __future__ import annotations

import csv
import io
import time
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from ..models.enums import Direction, DisplayMode
from . import codec

#: Chunks larger than this are split so trimming stays fine-grained.
MAX_CHUNK_BYTES = 64 * 1024


@dataclass(slots=True)
class TerminalChunk:
    """A contiguous run of bytes from one direction at one moment in time."""

    direction: Direction
    data: bytes
    timestamp: float

    @property
    def size(self) -> int:
        return len(self.data)


class TerminalBuffer:
    """Byte-budgeted FIFO of :class:`TerminalChunk`."""

    def __init__(self, max_bytes: int = 5 * 1024 * 1024) -> None:
        self._max_bytes = max(1024, int(max_bytes))
        self._chunks: deque[TerminalChunk] = deque()
        self._total_bytes = 0
        self._dropped_bytes = 0

    # ------------------------------------------------------------------
    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def dropped_bytes(self) -> int:
        """Bytes evicted by the budget since the last :meth:`clear`."""
        return self._dropped_bytes

    def set_max_bytes(self, max_bytes: int) -> None:
        self._max_bytes = max(1024, int(max_bytes))
        self._trim()

    def __len__(self) -> int:
        return len(self._chunks)

    def __iter__(self) -> Iterator[TerminalChunk]:
        return iter(tuple(self._chunks))

    def chunks(self) -> tuple[TerminalChunk, ...]:
        return tuple(self._chunks)

    # ------------------------------------------------------------------
    def append(
        self, direction: Direction, data: bytes, timestamp: float | None = None
    ) -> list[TerminalChunk]:
        """Append ``data`` and return the chunks that were actually stored."""
        if not data:
            return []
        now = time.time() if timestamp is None else timestamp
        added: list[TerminalChunk] = []
        for start in range(0, len(data), MAX_CHUNK_BYTES):
            piece = data[start : start + MAX_CHUNK_BYTES]
            chunk = TerminalChunk(direction=direction, data=piece, timestamp=now)
            self._chunks.append(chunk)
            self._total_bytes += chunk.size
            added.append(chunk)
        self._trim()
        return added

    def append_text(
        self, direction: Direction, text: str, timestamp: float | None = None
    ) -> list[TerminalChunk]:
        """Convenience wrapper for INFO/ERROR annotations."""
        return self.append(direction, text.encode("utf-8", errors="replace"), timestamp)

    def clear(self) -> None:
        self._chunks.clear()
        self._total_bytes = 0
        self._dropped_bytes = 0

    def _trim(self) -> None:
        while self._total_bytes > self._max_bytes and self._chunks:
            oldest = self._chunks.popleft()
            self._total_bytes -= oldest.size
            self._dropped_bytes += oldest.size

    # ------------------------------------------------------------------
    # Rendering / export
    # ------------------------------------------------------------------
    def render(
        self,
        *,
        display_mode: DisplayMode = DisplayMode.ASCII,
        show_timestamp: bool = False,
        encoding: str = "utf-8",
        hex_bytes_per_line: int = 16,
    ) -> str:
        """Render the whole buffer to plain text (used for re-render/export)."""
        renderer = TerminalRenderer(
            display_mode=display_mode,
            show_timestamp=show_timestamp,
            encoding=encoding,
            hex_bytes_per_line=hex_bytes_per_line,
        )
        return "".join(renderer.render(chunk) for chunk in self._chunks)

    def to_raw_bytes(self, directions: Sequence[Direction] | None = None) -> bytes:
        """Concatenate raw payload bytes, for binary export."""
        wanted = set(directions) if directions else {Direction.RX, Direction.TX}
        return b"".join(c.data for c in self._chunks if c.direction in wanted)

    def to_csv(self, encoding: str = "utf-8") -> str:
        """Render as CSV with one row per chunk."""
        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["timestamp_iso", "epoch", "direction", "length", "text", "hex"])
        for chunk in self._chunks:
            writer.writerow(
                [
                    format_timestamp(chunk.timestamp, iso=True),
                    f"{chunk.timestamp:.6f}",
                    chunk.direction.value,
                    chunk.size,
                    codec.decode_text(chunk.data, encoding)
                    .replace("\r", "\\r")
                    .replace("\n", "\\n"),
                    codec.format_hex(chunk.data),
                ]
            )
        return out.getvalue()


# ----------------------------------------------------------------------
# Rendering helpers (module level so the Qt view can reuse them)
# ----------------------------------------------------------------------
def format_timestamp(epoch: float, *, iso: bool = False) -> str:
    local = time.localtime(epoch)
    millis = int((epoch - int(epoch)) * 1000)
    if iso:
        return f"{time.strftime('%Y-%m-%dT%H:%M:%S', local)}.{millis:03d}"
    return f"{time.strftime('%H:%M:%S', local)}.{millis:03d}"


def render_chunk(
    chunk: TerminalChunk,
    *,
    display_mode: DisplayMode = DisplayMode.ASCII,
    show_timestamp: bool = False,
    encoding: str = "utf-8",
    hex_bytes_per_line: int = 16,
) -> str:
    """Render a single chunk in isolation (stateless convenience wrapper)."""
    renderer = TerminalRenderer(
        display_mode=display_mode,
        show_timestamp=show_timestamp,
        encoding=encoding,
        hex_bytes_per_line=hex_bytes_per_line,
    )
    return renderer.render(chunk)


class TerminalRenderer:
    """Stateful chunk → text renderer shared by the view and the exporters.

    Statefulness matters for two reasons:

    * a timestamp must be inserted at the *start of a line*, and a chunk very
      often stops in the middle of one — the naive "prefix every line of every
      chunk" approach produces stamps in the middle of sentences;
    * when the direction changes mid-line (a TX echo landing inside a partial
      RX line) a break is inserted so the two never run together.

    Because the live view and a full re-render use the same class, toggling
    Hex or Timestamp reproduces byte-for-byte what streaming would have shown.
    """

    __slots__ = (
        "_at_line_start",
        "_display_mode",
        "_encoding",
        "_hex_bytes_per_line",
        "_last_direction",
        "_show_timestamp",
    )

    def __init__(
        self,
        *,
        display_mode: DisplayMode = DisplayMode.ASCII,
        show_timestamp: bool = False,
        encoding: str = "utf-8",
        hex_bytes_per_line: int = 16,
    ) -> None:
        self._display_mode = display_mode
        self._show_timestamp = show_timestamp
        self._encoding = encoding
        self._hex_bytes_per_line = max(1, int(hex_bytes_per_line))
        self._at_line_start = True
        self._last_direction: Direction | None = None

    # ------------------------------------------------------------------
    @property
    def at_line_start(self) -> bool:
        return self._at_line_start

    def reset(self) -> None:
        self._at_line_start = True
        self._last_direction = None

    # ------------------------------------------------------------------
    def render(self, chunk: TerminalChunk) -> str:
        prefix = ""
        if (
            self._last_direction is not None
            and chunk.direction is not self._last_direction
            and not self._at_line_start
        ):
            # A direction switch mid-line would splice TX into an unfinished RX
            # line; break first so the two stay visually distinct.
            prefix = "\n"
            self._at_line_start = True
        self._last_direction = chunk.direction

        if chunk.direction in (Direction.INFO, Direction.ERROR):
            body = self._render_line_oriented(
                codec.decode_text(chunk.data, self._encoding), chunk.timestamp
            )
        elif self._display_mode is DisplayMode.HEX:
            body = self._render_block(codec.format_hex(chunk.data), chunk.timestamp)
        elif self._display_mode is DisplayMode.BOTH:
            body = self._render_block(
                codec.format_hex_dump(
                    chunk.data, bytes_per_line=self._hex_bytes_per_line
                ),
                chunk.timestamp,
            )
        else:
            body = self._render_line_oriented(
                codec.decode_text(chunk.data, self._encoding), chunk.timestamp
            )
        return prefix + body

    # ------------------------------------------------------------------
    def _stamp(self, epoch: float) -> str:
        return f"[{format_timestamp(epoch)}] " if self._show_timestamp else ""

    def _render_line_oriented(self, text: str, epoch: float) -> str:
        """Emit ``text`` verbatim, inserting a stamp at every real line start."""
        if not text:
            return ""
        # Normalise a bare CR (progress-bar style output) so it does not eat
        # the previous line inside a plain text widget.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not self._show_timestamp:
            self._at_line_start = text.endswith("\n")
            return text

        stamp = self._stamp(epoch)
        parts = text.split("\n")
        out: list[str] = []
        last_index = len(parts) - 1
        for index, part in enumerate(parts):
            has_newline = index < last_index
            if self._at_line_start and (part or has_newline):
                out.append(stamp)
                self._at_line_start = False
            out.append(part)
            if has_newline:
                out.append("\n")
                self._at_line_start = True
        return "".join(out)

    def _render_block(self, text: str, epoch: float) -> str:
        """Hex modes always occupy whole lines."""
        stamp = self._stamp(epoch)
        lines = text.split("\n") if text else []
        rendered = "".join(f"{stamp}{line}\n" for line in lines)
        self._at_line_start = True
        return rendered

