"""Thread-safe auto-repeat scheduling for command buttons.

All timers live on the GUI thread and only ever *enqueue* work on the serial
worker's TX queue, so repeat jobs can never race with the reader thread or
touch the port directly.  A global stop and a rate guard keep a misconfigured
20-buttons-at-10 ms setup from saturating the link.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.logging_setup import get_logger
from ..models.command import MIN_AUTO_SEND_INTERVAL_MS, CommandButton

_log = get_logger(__name__)


@dataclass(slots=True)
class AutoSendJob:
    """A running repeat job."""

    button_id: str
    interval_ms: int
    timer: QTimer
    sent_count: int = 0


class AutoSendScheduler(QObject):
    """Starts, stops and reports auto-repeat jobs."""

    jobStarted = Signal(str, int)
    """button_id, interval_ms"""

    jobStopped = Signal(str)
    """button_id"""

    tick = Signal(str)
    """button_id — emitted just before each repeat fires."""

    activeCountChanged = Signal(int)

    def __init__(
        self,
        send_callback: Callable[[CommandButton], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._send = send_callback
        self._jobs: dict[str, AutoSendJob] = {}
        self._buttons: dict[str, CommandButton] = {}

    # ------------------------------------------------------------------
    def is_running(self, button_id: str) -> bool:
        return button_id in self._jobs

    def active_ids(self) -> list[str]:
        return list(self._jobs)

    @property
    def active_count(self) -> int:
        return len(self._jobs)

    def aggregate_rate_hz(self) -> float:
        """Combined repeat frequency across all running jobs."""
        return sum(1000.0 / job.interval_ms for job in self._jobs.values() if job.interval_ms)

    # ------------------------------------------------------------------
    def start(self, button: CommandButton) -> None:
        """Start (or restart) the repeat job for ``button``."""
        interval = max(MIN_AUTO_SEND_INTERVAL_MS, int(button.auto_send.interval_ms))
        self.stop(button.id)
        self._buttons[button.id] = button

        timer = QTimer(self)
        from PySide6.QtCore import Qt

        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setInterval(interval)
        timer.timeout.connect(lambda button_id=button.id: self._fire(button_id))
        job = AutoSendJob(button_id=button.id, interval_ms=interval, timer=timer)
        self._jobs[button.id] = job
        timer.start()
        _log.info("Auto-send started for %s every %d ms", button.name, interval)
        self.jobStarted.emit(button.id, interval)
        self.activeCountChanged.emit(len(self._jobs))
        # Fire once immediately so the user sees feedback without waiting.
        self._fire(button.id)

    def stop(self, button_id: str) -> None:
        job = self._jobs.pop(button_id, None)
        self._buttons.pop(button_id, None)
        if job is None:
            return
        job.timer.stop()
        job.timer.deleteLater()
        _log.info("Auto-send stopped for %s", button_id)
        self.jobStopped.emit(button_id)
        self.activeCountChanged.emit(len(self._jobs))

    def stop_all(self) -> None:
        for button_id in list(self._jobs):
            self.stop(button_id)

    def toggle(self, button: CommandButton) -> bool:
        """Start if stopped, stop if running. Returns the new running state."""
        if self.is_running(button.id):
            self.stop(button.id)
            return False
        self.start(button)
        return True

    def update_button(self, button: CommandButton) -> None:
        """Apply an edited button to a running job (interval or payload)."""
        if button.id not in self._jobs:
            return
        if not button.enabled or not button.auto_send.enabled:
            self.stop(button.id)
            return
        job = self._jobs[button.id]
        self._buttons[button.id] = button
        interval = max(MIN_AUTO_SEND_INTERVAL_MS, int(button.auto_send.interval_ms))
        if interval != job.interval_ms:
            job.interval_ms = interval
            job.timer.setInterval(interval)

    # ------------------------------------------------------------------
    def _fire(self, button_id: str) -> None:
        job = self._jobs.get(button_id)
        button = self._buttons.get(button_id)
        if job is None or button is None:
            return
        self.tick.emit(button_id)
        try:
            delivered = self._send(button)
        except Exception:
            _log.exception("Auto-send callback failed for %s", button_id)
            self.stop(button_id)
            return
        if not delivered:
            # The port closed or the queue is saturated: stop rather than
            # spinning a timer that can never succeed.
            _log.warning("Auto-send for %s stopped: send rejected", button.name)
            self.stop(button_id)
            return
        job.sent_count += 1
