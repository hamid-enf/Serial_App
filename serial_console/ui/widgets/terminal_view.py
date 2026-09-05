"""Receive pane: a high-throughput, colour-coded serial log view."""

from __future__ import annotations

import time
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.logging_setup import get_logger
from ...core.render_budget import FrameGovernor, RenderBudget
from ...core.terminal_buffer import TerminalBuffer, TerminalChunk, TerminalRenderer
from ...models.enums import Direction, DisplayMode, Theme
from ...models.settings import TerminalSettings
from ..theme import direction_color, monospace_font

_log = get_logger(__name__)

#: Hard cap on paragraphs held by the widget.  This is the *display* guard;
#: the byte budget lives in :class:`TerminalBuffer`.  Two independent limits
#: mean neither a flood of tiny lines nor a single enormous line can grow the
#: process without bound.
MAX_DISPLAY_BLOCKS = 20000

#: Ceiling for a full re-render (a settings change, or restoring a minimised
#: window).  Beyond this only the newest text is rebuilt, with a note saying so.
RERENDER_BUDGET_BYTES = 4 * 1024 * 1024

#: ``QTextBlockFormat.LineHeightTypes.ProportionalHeight`` as the plain int the
#: PySide6 overload expects.
_PROPORTIONAL_HEIGHT = int(QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)


class _LogOutput(QPlainTextEdit):
    """The text widget, instrumented with what its own repaint costs.

    Insertion is only half of a display update; the other half is the repaint
    that follows it, and on a slow machine or a large window that half is the
    bigger one. Measuring it here — rather than guessing a multiplier — is what
    lets :class:`~serial_console.core.render_budget.FrameGovernor` keep the
    real, total cost inside its budget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._paint_ms = 0.0

    @property
    def paint_ms(self) -> float:
        return self._paint_ms

    def paintEvent(self, event) -> None:
        started = time.perf_counter()
        super().paintEvent(event)
        elapsed = (time.perf_counter() - started) * 1000.0
        self._paint_ms += 0.25 * (elapsed - self._paint_ms)


class TerminalView(QWidget):
    """Read-only terminal with auto-scroll, display modes and export hooks."""

    clearRequested = Signal()
    saveRequested = Signal()
    displaySettingsChanged = Signal()

    def __init__(self, buffer: TerminalBuffer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._buffer = buffer
        self._settings = TerminalSettings()
        self._theme = Theme.DARK
        self._renderer = TerminalRenderer()
        self._formats: dict[Direction, QTextCharFormat] = {}
        self._suppress_signals = False
        self._budget = RenderBudget()
        self._governor = FrameGovernor()
        self._line_spacing = 118
        self._skipped_bytes = 0
        self._flood_announced = False
        self._pending_restore = False
        self._build()
        self._rebuild_formats()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("Receive")
        title.setObjectName("SectionTitle")
        header.addWidget(title)

        self.throughput_label = QLabel("")
        self.throughput_label.setObjectName("HintLabel")
        header.addWidget(self.throughput_label)

        # Only visible while the display is deliberately skipping text, so the
        # user is never left wondering whether bytes were lost.  They were not:
        # the buffer and every export still contain them.
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("WarningLabel")
        self.notice_label.setToolTip(
            "Data is arriving faster than the screen can draw it.\n"
            "The newest lines are shown; everything is still buffered and exported."
        )
        self.notice_label.setVisible(False)
        header.addWidget(self.notice_label)

        header.addStretch(1)

        self.display_combo = QComboBox()
        self.display_combo.setToolTip("How received bytes are rendered")
        for mode in DisplayMode:
            self.display_combo.addItem(mode.label, mode)
        self.display_combo.currentIndexChanged.connect(self._on_display_changed)
        header.addWidget(self.display_combo)

        self.timestamp_check = QCheckBox("Timestamp")
        self.timestamp_check.setToolTip("Prefix each line with the local time")
        self.timestamp_check.toggled.connect(self._on_display_changed)
        header.addWidget(self.timestamp_check)

        self.autoscroll_check = QCheckBox("Auto scroll")
        self.autoscroll_check.setChecked(True)
        self.autoscroll_check.setToolTip("Follow new output as it arrives")
        self.autoscroll_check.toggled.connect(self._on_autoscroll_toggled)
        header.addWidget(self.autoscroll_check)

        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy the selection, or everything when nothing is selected")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        header.addWidget(self.copy_button)

        self.save_button = QPushButton("Save…")
        self.save_button.setToolTip("Export the receive log")
        self.save_button.clicked.connect(self.saveRequested.emit)
        header.addWidget(self.save_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Clear the receive pane (Ctrl+L)")
        self.clear_button.clicked.connect(self.clearRequested.emit)
        header.addWidget(self.clear_button)

        outer.addLayout(header)

        self.output = _LogOutput()
        self.output.setObjectName("Terminal")
        self.output.setReadOnly(True)
        self.output.setUndoRedoEnabled(False)
        self.output.setMaximumBlockCount(MAX_DISPLAY_BLOCKS)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.output.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.output.setCenterOnScroll(False)
        self.output.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.output.setFont(monospace_font())
        self._apply_line_spacing()
        self._force_ltr_paragraphs()
        # Scrolling by hand should stop the view chasing the tail, exactly like
        # a terminal emulator.
        self.output.verticalScrollBar().sliderPressed.connect(self._on_user_scroll)
        outer.addWidget(self.output, 1)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def apply_settings(self, settings: TerminalSettings, theme: Theme | None = None) -> None:
        """Apply terminal settings and re-render existing history."""
        self._settings = settings
        if theme is not None:
            self._theme = theme
        self._suppress_signals = True
        try:
            index = self.display_combo.findData(settings.display_mode)
            if index >= 0:
                self.display_combo.setCurrentIndex(index)
            self.timestamp_check.setChecked(settings.show_timestamp)
            self.autoscroll_check.setChecked(settings.auto_scroll)
        finally:
            self._suppress_signals = False
        self._rebuild_formats()
        self.rerender()

    def apply_font(self, family: str, size: int, line_spacing: int = 0) -> None:
        font: QFont = monospace_font(family, size)
        self.output.setFont(font)
        if line_spacing:
            self._line_spacing = max(100, min(200, int(line_spacing)))
        self._apply_line_spacing(whole_document=True)
        self._force_ltr_paragraphs()

    def _apply_line_spacing(self, *, whole_document: bool = False) -> None:
        """Set the terminal's line height.

        Qt has no document-wide line-height property, but a new block inherits
        the format of the block it is created from — so setting it on the last
        block is enough for everything appended afterwards, and the whole
        document only has to be touched when the setting itself changes.
        """
        block_format = QTextBlockFormat()
        block_format.setLineHeight(float(self._line_spacing), _PROPORTIONAL_HEIGHT)
        cursor = QTextCursor(self.output.document())
        if whole_document:
            cursor.select(QTextCursor.SelectionType.Document)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.setBlockFormat(block_format)

    def _force_ltr_paragraphs(self) -> None:
        """Keep the log left-aligned even when a line is Persian or Arabic.

        Qt infers paragraph direction from the first strong character, so a
        line of Persian would otherwise flip the whole line to the right —
        taking its timestamp with it and leaving the log ragged. Pinning the
        paragraph direction to left-to-right keeps every line starting in the
        same place, while the Persian words inside it still shape and read
        right-to-left, which is exactly how a terminal or a code editor
        presents mixed text.
        """
        option = self.output.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.LeftToRight)
        option.setWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.output.document().setDefaultTextOption(option)
        self.output.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._rebuild_formats()
        self.rerender()

    def _rebuild_formats(self) -> None:
        self._formats = {}
        for direction in Direction:
            fmt = QTextCharFormat()
            fmt.setForeground(direction_color(self._theme, direction))
            if direction is Direction.TX or direction is Direction.ERROR:
                fmt.setFontWeight(QFont.Weight.DemiBold)
            elif direction is Direction.INFO:
                fmt.setFontItalic(True)
            self._formats[direction] = fmt

    # ------------------------------------------------------------------
    # State exposed to the controller
    # ------------------------------------------------------------------
    @property
    def auto_scroll(self) -> bool:
        return self.autoscroll_check.isChecked()

    @property
    def display_mode(self) -> DisplayMode:
        data = self.display_combo.currentData()
        return data if isinstance(data, DisplayMode) else DisplayMode.ASCII

    @property
    def show_timestamp(self) -> bool:
        return self.timestamp_check.isChecked()

    def set_throughput_text(self, text: str) -> None:
        self.throughput_label.setText(text)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def append_chunks(self, chunks: Sequence[TerminalChunk]) -> None:
        """Append newly buffered chunks to the view.

        Three things keep this cheap no matter how long the session has run:
        nothing is drawn while the window is minimised, no more than one
        frame's worth of text is rendered (the rest stays in the buffer), and
        neighbouring chunks are merged into a single insertion.
        """
        if not chunks:
            return

        if self._window_is_minimised():
            # Nobody can see the pane; rendering into it is pure cost. The
            # bytes are safe in the buffer and the view rebuilds from it as
            # soon as the window comes back.
            self._pending_restore = True
            return
        if self._pending_restore:
            self._pending_restore = False
            self.rerender()
            return

        total = sum(chunk.size for chunk in chunks)
        allowance = self._budget.allowance()
        if total > allowance:
            self._append_decimated(chunks, total, allowance)
            return

        started = time.perf_counter()
        self._append_rendered(chunks)
        self._note_frame_cost(total, (time.perf_counter() - started) * 1000.0)
        if self._skipped_bytes:
            self._clear_skip_notice()

    def _note_frame_cost(self, rendered_bytes: int, elapsed_ms: float) -> None:
        """Record what this update cost, for both adaptive limits.

        The budget cares about the *insertion* rate (bytes per millisecond),
        while the governor cares about the total time one update takes — which
        includes the repaint the insertion triggers.
        """
        self._budget.record(rendered_bytes, elapsed_ms)
        self._governor.record(elapsed_ms + self.output.paint_ms)

    def suggested_refresh_ms(self) -> int:
        """Display interval that keeps the UI thread mostly free.

        The controller feeds this to the serial service, which decides how
        often to hand over a batch of received bytes.
        """
        return self._governor.interval_ms()

    def frame_cost_ms(self) -> float:
        """Smoothed cost of one display update, in milliseconds."""
        return self._governor.cost_ms

    def _window_is_minimised(self) -> bool:
        window = self.window()
        return bool(window is not None and window.isMinimized())

    def _append_decimated(
        self, chunks: Sequence[TerminalChunk], total: int, allowance: int
    ) -> None:
        """Render only the newest part of an oversized frame.

        Rendering 5 MB of text in one frame would stall the event loop for
        seconds, and the older lines would be scrolled out of the display
        before anyone could read them. The bytes are still in the buffer (and
        therefore still exportable and still visible after a re-render) — only
        the *pixels* are skipped, and the header says so.
        """
        tail: list[TerminalChunk] = []
        collected = 0
        for chunk in reversed(chunks):
            remaining = allowance - collected
            if remaining <= 0:
                break
            if chunk.size <= remaining:
                tail.append(chunk)
                collected += chunk.size
                continue
            # A single chunk can be larger than the whole allowance (the
            # transport hands over up to 64 KB at a time), so the split has to
            # happen *inside* it — otherwise one oversized chunk would sail
            # past the limit and stall the frame it was meant to protect.
            piece = chunk.data[-remaining:]
            newline = piece.find(b"\n")
            if 0 <= newline < len(piece) - 1:
                piece = piece[newline + 1 :]  # never start on half a line
            if piece:
                tail.append(
                    TerminalChunk(
                        direction=chunk.direction,
                        data=piece,
                        timestamp=chunk.timestamp,
                    )
                )
                collected += len(piece)
            break
        tail.reverse()

        skipped = total - collected
        if skipped > 0:
            self._skipped_bytes += skipped
            self._show_skip_notice()
            # The dropped chunks may have ended mid-line; start clean so the
            # tail cannot be spliced onto an unrelated half-line.
            self._renderer.reset()

        started = time.perf_counter()
        self._append_rendered(tail)
        self._note_frame_cost(collected, (time.perf_counter() - started) * 1000.0)

    def _show_skip_notice(self) -> None:
        from ...core.stats import format_bytes

        self.notice_label.setText(
            f"display limited · {format_bytes(self._skipped_bytes)} not shown"
        )
        self.notice_label.setVisible(True)
        if not self._flood_announced:
            self._flood_announced = True
            self._append_rendered(
                [
                    TerminalChunk(
                        direction=Direction.INFO,
                        data=(
                            "\n… data is arriving faster than the display can render it; "
                            "showing the newest lines only. Everything is kept in the "
                            "buffer and included in exports …\n"
                        ).encode(),
                        timestamp=0.0,
                    )
                ]
            )

    def _clear_skip_notice(self) -> None:
        self._skipped_bytes = 0
        self._flood_announced = False
        self.notice_label.clear()
        self.notice_label.setVisible(False)

    def _append_rendered(self, chunks: Sequence[TerminalChunk]) -> None:
        runs = self._renderer.render_runs(chunks)
        if not runs:
            return
        document = self.output.document()
        scrollbar = self.output.verticalScrollBar()
        follow = self.auto_scroll
        previous_value = scrollbar.value()
        blocks_before = document.blockCount()
        added = sum(text.count("\n") for _, text in runs)

        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        try:
            for direction, text in runs:
                cursor.insertText(text, self._formats.get(direction, QTextCharFormat()))
        finally:
            cursor.endEditBlock()

        if follow:
            # Qt already keeps a bottom-anchored view pinned; setting the value
            # again costs a redundant scroll and repaint on every single frame.
            if scrollbar.value() != scrollbar.maximum():
                scrollbar.setValue(scrollbar.maximum())
        else:
            # The user is reading history. Once the block cap starts trimming,
            # the text under their eyes shifts up by however many blocks were
            # dropped — so subtract that back out and the page stays still.
            trimmed = max(0, blocks_before + added - document.blockCount())
            target = min(previous_value - trimmed, scrollbar.maximum())
            scrollbar.setValue(max(scrollbar.minimum(), target))

    def rerender(self) -> None:
        """Rebuild the whole view from the buffer (after a settings change)."""
        self._renderer = TerminalRenderer(
            display_mode=self.display_mode,
            show_timestamp=self.show_timestamp,
            encoding=self._settings.encoding,
            hex_bytes_per_line=self._settings.hex_bytes_per_line,
        )
        self.output.clear()
        self._apply_line_spacing()
        self._clear_skip_notice()
        chunks = self._buffer.chunks()
        if not chunks:
            return
        # Re-rendering a full 50 MB buffer would block; cap it and say so.
        budget = RERENDER_BUDGET_BYTES
        total = sum(c.size for c in chunks)
        if total > budget:
            kept: list[TerminalChunk] = []
            collected = 0
            for chunk in reversed(chunks):
                kept.append(chunk)
                collected += chunk.size
                if collected >= budget:
                    break
            kept.reverse()
            self._append_rendered(
                [
                    TerminalChunk(
                        direction=Direction.INFO,
                        data=(
                            f"… showing the last {collected // 1024:,} KB of "
                            f"{total // 1024:,} KB; the full capture is still exportable …\n"
                        ).encode(),
                        timestamp=kept[0].timestamp if kept else 0.0,
                    )
                ]
            )
            self._append_rendered(kept)
        else:
            self._append_rendered(list(chunks))
        self.scroll_to_end()

    def clear(self) -> None:
        self.output.clear()
        # clear() drops the document's blocks, and with them the block format
        # that carries the line height.
        self._apply_line_spacing()
        self._renderer.reset()
        self._clear_skip_notice()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def copy_to_clipboard(self) -> int:
        """Copy the selection, or the whole pane when nothing is selected."""
        cursor = self.output.textCursor()
        text = (
            cursor.selectedText().replace("\u2029", "\n")
            if cursor.hasSelection()
            else self.output.toPlainText()
        )
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        return len(text)

    def select_all(self) -> None:
        self.output.selectAll()

    def scroll_to_end(self) -> None:
        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_auto_scroll(self, enabled: bool) -> None:
        self.autoscroll_check.setChecked(enabled)

    # ------------------------------------------------------------------
    def _on_autoscroll_toggled(self, enabled: bool) -> None:
        if enabled:
            self.scroll_to_end()
        if not self._suppress_signals:
            self.displaySettingsChanged.emit()

    def _on_user_scroll(self) -> None:
        """Grabbing the scrollbar detaches the view from the tail."""
        if self.autoscroll_check.isChecked():
            scrollbar = self.output.verticalScrollBar()
            if scrollbar.value() < scrollbar.maximum():
                self.autoscroll_check.setChecked(False)

    def _on_display_changed(self, *_args: object) -> None:
        if self._suppress_signals:
            return
        self.displaySettingsChanged.emit()
