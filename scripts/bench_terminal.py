#!/usr/bin/env python3
"""Measure what the receive pane costs the UI thread over a long session.

The complaint this exists to answer is "after a while, with a lot of data, it
gets heavy" — a question about *sustained cost* and *degradation*, not about
peak throughput. So the headline number here is the **duty cycle**: the share
of wall-clock time the UI thread spends rendering the log. Everything left over
is what keeps typing, clicking and scrolling instant.

    QT_QPA_PLATFORM=offscreen python scripts/bench_terminal.py --rate 250000
    QT_QPA_PLATFORM=offscreen python scripts/bench_terminal.py --window --rate 250000

Time is simulated, not slept through, so a 60-second session takes a few
seconds to measure. Each tick feeds the bytes that would have arrived during
the interval the application itself asked for, so the adaptive refresh is part
of what is measured rather than something the benchmark works around.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BAUD_PRESETS = {
    "9600": 960, "115200": 11_520, "921600": 92_160,
    "2000000": 250_000, "flood": 1_000_000,
}


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=int, default=250_000,
                        help="bytes per second (250000 ≈ 2 Mbit/s of 8N1 traffic)")
    parser.add_argument("--baud", choices=sorted(BAUD_PRESETS),
                        help="preset instead of --rate")
    parser.add_argument("--seconds", type=float, default=60.0,
                        help="length of the simulated session")
    parser.add_argument("--line-length", type=int, default=78)
    parser.add_argument("--mode", choices=("ascii", "hex", "both"), default="ascii")
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--window", action="store_true",
                        help="drive the whole MainWindow, not just the pane")
    parser.add_argument("--fixed-interval", type=int, default=0,
                        help="ignore the adaptive refresh and tick every N ms")
    parser.add_argument("--slow", type=float, default=1.0,
                        help="simulate a machine N× slower at rendering")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--buckets", type=int, default=6)
    args = parser.parse_args()

    rate = BAUD_PRESETS[args.baud] if args.baud else args.rate

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from serial_console.core.terminal_buffer import TerminalBuffer
    from serial_console.models.enums import Direction, DisplayMode, Theme
    from serial_console.models.settings import TerminalSettings
    from serial_console.ui.theme import apply_theme
    from serial_console.ui.widgets.terminal_view import TerminalView

    app = QApplication(sys.argv[:1])
    apply_theme(app, Theme.DARK)

    mode = {"ascii": DisplayMode.ASCII, "hex": DisplayMode.HEX,
            "both": DisplayMode.BOTH}[args.mode]

    if args.window:
        # The whole application: menu bar, command panel, status bar and all.
        from serial_console.config.store import ConfigStore
        from serial_console.models.settings import AppConfig
        from serial_console.transport.loopback import LoopbackTransport
        from serial_console.ui.main_window import MainWindow

        config = AppConfig.create_default()
        config.terminal.display_mode = mode
        config.terminal.show_timestamp = args.timestamps
        window = MainWindow(config, ConfigStore("/tmp/bench-config.json"),
                            transport=LoopbackTransport(echo=False))
        window.resize(max(args.width, 1200), max(args.height, 760))
        window.show()
        target, view = window, window.terminal
        feed = window._on_data_received
    else:
        buffer = TerminalBuffer(5 * 1024 * 1024)
        view = TerminalView(buffer)
        settings = TerminalSettings()
        settings.display_mode = mode
        settings.show_timestamp = args.timestamps
        view.apply_settings(settings, Theme.DARK)
        view.resize(args.width, args.height)
        view.show()
        target = view

        def feed(data: bytes) -> None:
            view.append_chunks(buffer.append(Direction.RX, data))

    if args.slow > 1.0:
        # Pretend the text widget is on a slower machine by burning the extra
        # time *inside* the measured region, so the adaptive logic sees it.
        original_append = view._append_rendered

        def slow_append(chunks) -> None:
            started = time.perf_counter()
            original_append(chunks)
            extra = (time.perf_counter() - started) * (args.slow - 1.0)
            deadline = time.perf_counter() + extra
            while time.perf_counter() < deadline:
                pass

        view._append_rendered = slow_append  # type: ignore[method-assign]

    canvas = QImage(target.width(), target.height(), QImage.Format.Format_RGB32)

    line = "imu ax=+0.123 ay=-0.456 az=+0.789 | mag=214 | t=24.8C | seq=".ljust(
        max(24, args.line_length - 7), "."
    )

    def payload(count: int, start: int) -> bytes:
        needed = max(1, count // (len(line) + 7))
        return "".join(f"{line}{start + i:06d}\n" for i in range(needed)).encode()

    frames: list[float] = []
    intervals: list[int] = []
    simulated = 0.0
    produced = 0
    counter = 0
    spent_ms = 0.0

    while simulated < args.seconds:
        interval_ms = args.fixed_interval or view.suggested_refresh_ms()
        intervals.append(interval_ms)
        data = payload(int(rate * interval_ms / 1000), counter)
        counter += data.count(b"\n")
        produced += len(data)

        started = time.perf_counter()
        feed(data)
        app.processEvents()
        painter = QPainter(canvas)
        target.render(painter, QPoint(0, 0))
        painter.end()
        cost = (time.perf_counter() - started) * 1000.0

        frames.append(cost)
        spent_ms += cost
        simulated += interval_ms / 1000.0

    duty = spent_ms / (args.seconds * 1000.0)
    print(f"\n{'whole window' if args.window else 'receive pane'} "
          f"{target.width()}×{target.height()} · mode={args.mode} · "
          f"timestamps={args.timestamps}")
    print(f"{rate / 1000:.0f} kB/s for {args.seconds:.0f} s "
          f"({produced / 1_048_576:.1f} MB, {counter:,} lines)\n")

    step = max(1, len(frames) // args.buckets)
    print(f"{'segment':>8} {'frames':>7} {'avg ms':>8} {'p95 ms':>8} {'interval':>9}")
    for index in range(0, len(frames), step):
        window_frames = frames[index : index + step]
        window_intervals = intervals[index : index + step]
        if not window_frames:
            continue
        print(f"{index // step + 1:>8} {len(window_frames):>7} "
              f"{statistics.fmean(window_frames):>8.2f} "
              f"{percentile(window_frames, 0.95):>8.2f} "
              f"{statistics.fmean(window_intervals):>8.0f}ms")

    head = frames[: max(1, len(frames) // 6)]
    tail = frames[-max(1, len(frames) // 6) :]
    print(f"\nUI thread spent on the log   {duty * 100:5.1f} %  "
          f"({spent_ms / 1000:.1f} s of {args.seconds:.0f} s)")
    print(f"frame cost first sixth       {statistics.fmean(head):5.2f} ms")
    print(f"frame cost last sixth        {statistics.fmean(tail):5.2f} ms  "
          f"(×{statistics.fmean(tail) / max(1e-9, statistics.fmean(head)):.2f})")
    print(f"worst frame                  {max(frames):5.2f} ms")
    print(f"refresh interval             {min(intervals)}–{max(intervals)} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
