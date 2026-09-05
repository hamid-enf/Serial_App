"""Self-calibrating limit on how much text the terminal renders per frame.

Why this exists
---------------
A terminal has two independent jobs: *keep* every byte (so it can be exported)
and *show* the stream (so a human can follow it). The first is cheap and is
handled by :class:`~serial_console.core.terminal_buffer.TerminalBuffer`. The
second is not: inserting text into a rich text widget costs roughly linear time
in the number of characters, and at 2 Mbit/s the arriving text is far more than
any screen can display in a 33 ms frame. Rendering it anyway is pure waste —
those lines are pushed off the top of the scrollback before anyone can read
them — and it is exactly what makes a serial terminal feel heavy after a while.

Rather than hard-coding "N kilobytes per frame" (which is wrong on both a slow
laptop and a fast workstation), this class *measures* what the machine actually
achieves and converts a time budget into a byte allowance. It contains no Qt
and no I/O, so its behaviour can be tested directly.
"""

from __future__ import annotations

#: How much of a 33 ms display frame the terminal may spend on rendering.
#: A third leaves ample room for the rest of the UI — menus, the command panel,
#: the status bar — to stay responsive while data floods in.
DEFAULT_TARGET_MS = 11.0

#: Never render less than this per frame, however slow the machine looks.
#: Chosen so decimation cannot engage at real serial rates: 921600 baud is
#: ~92 kB/s, i.e. ~3 KB in a 33 ms frame, comfortably under this floor.
DEFAULT_FLOOR_BYTES = 4 * 1024

#: Never render more than this in one frame even on a very fast machine, so a
#: single burst cannot stall the event loop.
DEFAULT_CEILING_BYTES = 512 * 1024

#: Weight of the newest measurement in the throughput estimate. Low enough to
#: ignore a single unlucky frame (a GC pause, a background process), high
#: enough to follow a real change within a second.
_SMOOTHING = 0.25


class RenderBudget:
    """Converts "how fast is this machine?" into "how many bytes this frame?".

    Args:
        target_ms: Time budget for one frame's rendering.
        floor_bytes: Lower bound on the allowance.
        ceiling_bytes: Upper bound on the allowance.
        initial_bytes_per_ms: Starting estimate, refined by :meth:`record`.
    """

    __slots__ = ("_bytes_per_ms", "_ceiling", "_floor", "_samples", "_target_ms")

    def __init__(
        self,
        *,
        target_ms: float = DEFAULT_TARGET_MS,
        floor_bytes: int = DEFAULT_FLOOR_BYTES,
        ceiling_bytes: int = DEFAULT_CEILING_BYTES,
        initial_bytes_per_ms: float = 8192.0,
    ) -> None:
        self._target_ms = max(1.0, float(target_ms))
        self._floor = max(1024, int(floor_bytes))
        self._ceiling = max(self._floor, int(ceiling_bytes))
        self._bytes_per_ms = max(1.0, float(initial_bytes_per_ms))
        self._samples = 0

    # ------------------------------------------------------------------
    @property
    def bytes_per_ms(self) -> float:
        """Current estimate of rendering throughput."""
        return self._bytes_per_ms

    @property
    def samples(self) -> int:
        return self._samples

    def allowance(self) -> int:
        """Bytes that may be rendered in the current frame."""
        estimate = int(self._bytes_per_ms * self._target_ms)
        return max(self._floor, min(self._ceiling, estimate))

    def record(self, rendered_bytes: int, elapsed_ms: float) -> None:
        """Feed back what the last frame actually cost.

        Measurements from trivially small frames are ignored: they are
        dominated by fixed per-frame overhead and would make the estimate
        pessimistic, shrinking the allowance for no reason.
        """
        if rendered_bytes < 2048 or elapsed_ms <= 0.05:
            return
        observed = rendered_bytes / elapsed_ms
        self._bytes_per_ms += _SMOOTHING * (observed - self._bytes_per_ms)
        self._bytes_per_ms = max(256.0, self._bytes_per_ms)
        self._samples += 1

    def reset(self) -> None:
        self._samples = 0


#: Share of wall-clock time the UI thread may spend drawing the terminal.
#: The rest is what keeps typing, clicking and scrolling instant while data
#: floods in — the thing users actually mean by "it feels heavy".
DEFAULT_DUTY_CYCLE = 0.30

#: Fastest and slowest display refresh. 33 ms is one 30 fps frame, which is
#: what an interactive command/response session needs; 200 ms is still five
#: updates a second, which reads as continuous for a scrolling log.
MIN_INTERVAL_MS = 33
MAX_INTERVAL_MS = 200


class FrameGovernor:
    """Chooses a display refresh interval from what the last frames cost.

    A fixed 30 fps refresh is the right answer only while frames are cheap. As
    soon as they are not — a slower machine, a 2 Mbit/s stream, a hex dump of
    everything — insisting on 30 fps means the event loop spends nearly all of
    its time in the text widget and the window stops feeling responsive.

    So instead of fixing the frame *rate*, this fixes the frame *share*: the
    interval is stretched until rendering costs at most :data:`DEFAULT_DUTY_CYCLE`
    of wall-clock time. Fewer, larger updates cost less in total than many
    small ones (the per-frame layout and repaint overhead is paid once), so the
    log keeps up while the rest of the UI stays free.
    """

    __slots__ = ("_cost_ms", "_duty", "_max_ms", "_min_ms")

    def __init__(
        self,
        *,
        duty_cycle: float = DEFAULT_DUTY_CYCLE,
        min_interval_ms: int = MIN_INTERVAL_MS,
        max_interval_ms: int = MAX_INTERVAL_MS,
    ) -> None:
        self._duty = min(0.9, max(0.05, float(duty_cycle)))
        self._min_ms = max(5, int(min_interval_ms))
        self._max_ms = max(self._min_ms, int(max_interval_ms))
        self._cost_ms = 0.0

    @property
    def cost_ms(self) -> float:
        """Smoothed cost of one display update."""
        return self._cost_ms

    def interval_ms(self) -> int:
        """Interval that keeps rendering within the duty cycle."""
        if self._cost_ms <= 0.0:
            return self._min_ms
        needed = self._cost_ms / self._duty
        return int(max(self._min_ms, min(self._max_ms, needed)))

    def record(self, cost_ms: float) -> int:
        """Feed in the cost of the frame just rendered; returns the interval."""
        if cost_ms >= 0.0:
            self._cost_ms += _SMOOTHING * (cost_ms - self._cost_ms)
        return self.interval_ms()

    def reset(self) -> None:
        self._cost_ms = 0.0
