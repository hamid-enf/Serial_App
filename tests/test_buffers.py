"""RX aggregator, terminal buffer bounds and rendering."""

from __future__ import annotations

import threading
import time

import pytest

from serial_console.core.rx_aggregator import RxAggregator
from serial_console.core.terminal_buffer import (
    MAX_CHUNK_BYTES,
    TerminalBuffer,
    TerminalChunk,
    TerminalRenderer,
    format_timestamp,
)
from serial_console.models.enums import Direction, DisplayMode


class TestRxAggregator:
    def test_push_then_drain(self) -> None:
        aggregator = RxAggregator()
        aggregator.push(b"abc")
        aggregator.push(b"def")
        batch = aggregator.drain()
        assert batch.data == b"abcdef"
        assert aggregator.drain().data == b""

    def test_drain_can_be_capped_per_frame(self) -> None:
        aggregator = RxAggregator()
        aggregator.push(b"0123456789")
        assert aggregator.drain(4).data == b"0123"
        assert aggregator.drain().data == b"456789"

    def test_ceiling_drops_the_oldest_and_counts_it(self) -> None:
        aggregator = RxAggregator(ceiling_bytes=64 * 1024)
        aggregator.push(b"A" * 64 * 1024)
        aggregator.push(b"B" * 1024)
        batch = aggregator.drain()
        assert len(batch.data) == 64 * 1024
        assert batch.dropped == 1024
        assert batch.data.endswith(b"B" * 1024)  # newest data is preserved
        assert aggregator.total_dropped == 1024

    def test_dropped_counter_resets_each_drain(self) -> None:
        aggregator = RxAggregator(ceiling_bytes=64 * 1024)
        aggregator.push(b"A" * 70 * 1024)
        assert aggregator.drain().dropped > 0
        aggregator.push(b"x")
        assert aggregator.drain().dropped == 0

    def test_totals_and_reset(self) -> None:
        aggregator = RxAggregator()
        aggregator.push(b"12345")
        assert aggregator.total_received == 5
        aggregator.reset_counters()
        assert aggregator.total_received == 0

    def test_concurrent_producers_lose_nothing(self) -> None:
        aggregator = RxAggregator(ceiling_bytes=8 * 1024 * 1024)
        threads = [
            threading.Thread(target=lambda: [aggregator.push(b"x" * 64) for _ in range(500)])
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(aggregator.drain().data) == 8 * 500 * 64

    def test_producer_and_consumer_race(self) -> None:
        aggregator = RxAggregator(ceiling_bytes=8 * 1024 * 1024)
        stop = threading.Event()
        received = bytearray()

        def produce() -> None:
            for _ in range(2000):
                aggregator.push(b"abcd")
            stop.set()

        producer = threading.Thread(target=produce)
        producer.start()
        while not stop.is_set() or aggregator.pending():
            received.extend(aggregator.drain().data)
            time.sleep(0.001)
        producer.join()
        received.extend(aggregator.drain().data)
        assert len(received) == 2000 * 4


class TestTerminalBuffer:
    def test_append_and_total(self) -> None:
        buffer = TerminalBuffer(max_bytes=1024)
        buffer.append(Direction.RX, b"hello")
        assert buffer.total_bytes == 5
        assert len(buffer) == 1

    def test_large_appends_are_split_into_chunks(self) -> None:
        buffer = TerminalBuffer(max_bytes=10 * 1024 * 1024)
        chunks = buffer.append(Direction.RX, b"x" * (MAX_CHUNK_BYTES * 2 + 10))
        assert len(chunks) == 3
        assert all(chunk.size <= MAX_CHUNK_BYTES for chunk in chunks)

    def test_budget_evicts_oldest_data(self) -> None:
        buffer = TerminalBuffer(max_bytes=4096)
        for index in range(100):
            buffer.append(Direction.RX, bytes([index % 256]) * 1024)
        assert buffer.total_bytes <= 4096
        assert buffer.dropped_bytes > 0

    def test_memory_stays_flat_over_a_long_session(self) -> None:
        buffer = TerminalBuffer(max_bytes=256 * 1024)
        for _ in range(5000):
            buffer.append(Direction.RX, b"y" * 1024)
        assert buffer.total_bytes <= 256 * 1024
        assert len(buffer) <= 256  # chunk count is bounded too

    def test_shrinking_the_budget_trims_immediately(self) -> None:
        buffer = TerminalBuffer(max_bytes=1024 * 1024)
        buffer.append(Direction.RX, b"z" * 512 * 1024)
        buffer.set_max_bytes(64 * 1024)
        assert buffer.total_bytes <= 64 * 1024

    def test_clear_resets_counters(self) -> None:
        buffer = TerminalBuffer(max_bytes=1024)
        buffer.append(Direction.RX, b"x" * 4096)
        buffer.clear()
        assert buffer.total_bytes == 0
        assert buffer.dropped_bytes == 0

    def test_empty_append_is_ignored(self) -> None:
        buffer = TerminalBuffer()
        assert buffer.append(Direction.RX, b"") == []


class TestRendering:
    def test_ascii_passthrough(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"hello\nworld\n")
        assert buffer.render() == "hello\nworld\n"

    def test_crlf_is_normalised_to_lf(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"a\r\nb\r\n")
        assert buffer.render() == "a\nb\n"

    def test_bare_cr_becomes_a_newline(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"50%\r100%\r")
        assert buffer.render() == "50%\n100%\n"

    def test_timestamp_only_at_line_starts(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"hel", timestamp=0.0)
        buffer.append(Direction.RX, b"lo\nnext\n", timestamp=0.0)
        rendered = buffer.render(show_timestamp=True)
        stamp = f"[{format_timestamp(0.0)}] "
        assert rendered == f"{stamp}hello\n{stamp}next\n"
        assert rendered.count(stamp) == 2  # not once per chunk

    def test_direction_change_breaks_the_line(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"partial")
        buffer.append(Direction.TX, b"CMD\n")
        assert buffer.render() == "partial\nCMD\n"

    def test_hex_mode(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"Hi")
        assert buffer.render(display_mode=DisplayMode.HEX) == "48 69\n"

    def test_hex_and_ascii_mode(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"Hi")
        rendered = buffer.render(display_mode=DisplayMode.BOTH, hex_bytes_per_line=4)
        assert rendered.startswith("48 69")
        assert "|Hi|" in rendered

    def test_switching_display_mode_rerenders_identically(self) -> None:
        buffer = TerminalBuffer()
        for piece in (b"one\n", b"two\n", b"thr"):
            buffer.append(Direction.RX, piece)
        streamed = TerminalRenderer(display_mode=DisplayMode.ASCII)
        incremental = "".join(streamed.render(chunk) for chunk in buffer.chunks())
        assert incremental == buffer.render(display_mode=DisplayMode.ASCII)

    def test_info_lines_are_never_hex_encoded(self) -> None:
        buffer = TerminalBuffer()
        buffer.append_text(Direction.INFO, "Connected\n")
        assert "Connected" in buffer.render(display_mode=DisplayMode.HEX)

    def test_invalid_utf8_does_not_break_rendering(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"\xff\xfe")
        assert buffer.render()


class TestExport:
    def test_raw_bytes_exclude_annotations(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"DATA")
        buffer.append_text(Direction.INFO, "note")
        assert buffer.to_raw_bytes() == b"DATA"

    def test_raw_bytes_can_be_filtered_by_direction(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"RX")
        buffer.append(Direction.TX, b"TX")
        assert buffer.to_raw_bytes([Direction.TX]) == b"TX"

    def test_csv_has_a_header_and_one_row_per_chunk(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"a\n")
        buffer.append(Direction.TX, b"b\n")
        lines = buffer.to_csv().strip().split("\n")
        assert lines[0].startswith("timestamp_iso,")
        assert len(lines) == 3

    def test_csv_escapes_newlines(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"line\r\n")
        assert "\\r\\n" in buffer.to_csv()

    def test_csv_includes_a_hex_column(self) -> None:
        buffer = TerminalBuffer()
        buffer.append(Direction.RX, b"Hi")
        assert "48 69" in buffer.to_csv()


class TestRendererFastPaths:
    """Rendering was rewritten for speed; the output must not move."""

    @staticmethod
    def _reference_line_oriented(renderer, text: str, epoch: float) -> str:
        """The original split/append/join implementation, kept as an oracle."""
        if not text:
            return ""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not renderer._show_timestamp:
            renderer._at_line_start = text.endswith("\n")
            return text
        stamp = renderer._stamp(epoch)
        parts = text.split("\n")
        out: list[str] = []
        last_index = len(parts) - 1
        for index, part in enumerate(parts):
            has_newline = index < last_index
            if renderer._at_line_start and (part or has_newline):
                out.append(stamp)
                renderer._at_line_start = False
            out.append(part)
            if has_newline:
                out.append("\n")
                renderer._at_line_start = True
        return "".join(out)

    @pytest.mark.parametrize("timestamps", [False, True])
    def test_streaming_output_matches_the_reference(self, timestamps: bool) -> None:
        fragments = ["", "\n", "a", "ab\n", "\nx", "a\n\nb\n", "one\ntwo", "\r\n",
                     "x\ry\r\n", "\n\n\n", "tail"]
        directions = [Direction.RX, Direction.TX, Direction.INFO, Direction.RX]
        fast = TerminalRenderer(show_timestamp=timestamps)
        oracle = TerminalRenderer(show_timestamp=timestamps)
        for index, fragment in enumerate(fragments):
            direction = directions[index % len(directions)]
            chunk = TerminalChunk(
                direction=direction, data=fragment.encode(), timestamp=1_700_000_000.5
            )
            expected_prefix = ""
            if (
                oracle._last_direction is not None
                and direction is not oracle._last_direction
                and not oracle._at_line_start
            ):
                expected_prefix = "\n"
                oracle._at_line_start = True
            oracle._last_direction = direction
            expected = expected_prefix + self._reference_line_oriented(
                oracle, fragment, chunk.timestamp
            )
            assert fast.render(chunk) == expected

    @pytest.mark.parametrize("timestamps", [False, True])
    def test_render_runs_preserves_the_stream(self, timestamps: bool) -> None:
        chunks = [
            TerminalChunk(direction=Direction.RX, data=b"one\n", timestamp=1.0),
            TerminalChunk(direction=Direction.RX, data=b"two\n", timestamp=2.0),
            TerminalChunk(direction=Direction.TX, data=b"cmd\n", timestamp=3.0),
            TerminalChunk(direction=Direction.RX, data=b"three\n", timestamp=4.0),
        ]
        per_chunk = TerminalRenderer(show_timestamp=timestamps)
        runs_renderer = TerminalRenderer(show_timestamp=timestamps)
        flat = "".join(per_chunk.render(chunk) for chunk in chunks)
        runs = runs_renderer.render_runs(chunks)
        assert "".join(text for _, text in runs) == flat
        # Neighbouring chunks of the same direction become one insertion.
        assert [direction for direction, _ in runs] == [
            Direction.RX,
            Direction.TX,
            Direction.RX,
        ]

    def test_render_runs_skips_empty_chunks(self) -> None:
        renderer = TerminalRenderer()
        chunks = [
            TerminalChunk(direction=Direction.RX, data=b"", timestamp=1.0),
            TerminalChunk(direction=Direction.RX, data=b"data", timestamp=2.0),
        ]
        assert renderer.render_runs(chunks) == [(Direction.RX, "data")]
