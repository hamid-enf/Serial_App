"""Tests for the adaptive rendering limits.

These are the mechanisms that keep the receive pane responsive when the data
rate, the display mode or the machine make a naive "draw everything at 30 fps"
policy impossible, so they are worth testing on their own — without Qt, and
without waiting for real time to pass.
"""

from __future__ import annotations

from serial_console.core.render_budget import (
    DEFAULT_FLOOR_BYTES,
    MAX_INTERVAL_MS,
    MIN_INTERVAL_MS,
    FrameGovernor,
    RenderBudget,
)


class TestRenderBudget:
    def test_starts_with_a_usable_allowance(self) -> None:
        budget = RenderBudget()
        assert budget.allowance() >= DEFAULT_FLOOR_BYTES

    def test_allowance_never_drops_below_the_floor(self) -> None:
        budget = RenderBudget()
        for _ in range(50):
            budget.record(64 * 1024, 5000.0)  # a hopelessly slow machine
        assert budget.allowance() == DEFAULT_FLOOR_BYTES

    def test_allowance_never_exceeds_the_ceiling(self) -> None:
        budget = RenderBudget(ceiling_bytes=100_000)
        for _ in range(50):
            budget.record(1_000_000, 0.5)  # absurdly fast
        assert budget.allowance() == 100_000

    def test_allowance_tracks_measured_throughput(self) -> None:
        fast = RenderBudget()
        slow = RenderBudget()
        for _ in range(40):
            fast.record(64 * 1024, 4.0)   # 16 KB per millisecond
            slow.record(8 * 1024, 40.0)   # 0.2 KB per millisecond
        assert fast.allowance() > slow.allowance() * 10

    def test_a_real_serial_rate_never_triggers_decimation(self) -> None:
        """921600 baud is ~3 KB per frame — must always fit."""
        budget = RenderBudget()
        for _ in range(200):
            budget.record(3 * 1024, 2.0)
        assert budget.allowance() >= 3 * 1024

    def test_tiny_frames_do_not_poison_the_estimate(self) -> None:
        budget = RenderBudget()
        before = budget.bytes_per_ms
        for _ in range(20):
            budget.record(20, 3.0)  # 20 bytes, dominated by fixed overhead
        assert budget.bytes_per_ms == before
        assert budget.samples == 0

    def test_estimate_is_smoothed_not_jumpy(self) -> None:
        budget = RenderBudget(initial_bytes_per_ms=10_000)
        budget.record(64 * 1024, 1000.0)  # one terrible frame
        # A single outlier must not collapse the allowance.
        assert budget.bytes_per_ms > 5_000


class TestFrameGovernor:
    def test_cheap_frames_keep_the_fastest_refresh(self) -> None:
        governor = FrameGovernor()
        for _ in range(30):
            governor.record(2.0)
        assert governor.interval_ms() == MIN_INTERVAL_MS

    def test_expensive_frames_stretch_the_interval(self) -> None:
        governor = FrameGovernor(duty_cycle=0.30)
        for _ in range(60):
            governor.record(30.0)
        # 30 ms of work at a 30 % duty cycle needs a 100 ms interval.
        assert 90 <= governor.interval_ms() <= 110

    def test_interval_is_capped(self) -> None:
        governor = FrameGovernor()
        for _ in range(60):
            governor.record(5_000.0)
        assert governor.interval_ms() == MAX_INTERVAL_MS

    def test_duty_cycle_is_respected(self) -> None:
        for duty in (0.2, 0.3, 0.5):
            governor = FrameGovernor(duty_cycle=duty)
            for _ in range(80):
                governor.record(25.0)
            interval = governor.interval_ms()
            assert abs(25.0 / interval - duty) < 0.05

    def test_recovers_when_frames_get_cheap_again(self) -> None:
        governor = FrameGovernor()
        for _ in range(60):
            governor.record(60.0)
        assert governor.interval_ms() > MIN_INTERVAL_MS
        for _ in range(60):
            governor.record(1.0)
        assert governor.interval_ms() == MIN_INTERVAL_MS

    def test_single_slow_frame_does_not_halve_the_frame_rate(self) -> None:
        governor = FrameGovernor()
        for _ in range(30):
            governor.record(3.0)
        governor.record(90.0)  # a GC pause, or the OS scheduling us out
        assert governor.interval_ms() <= 90
