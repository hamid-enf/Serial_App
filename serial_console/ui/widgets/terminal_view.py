"""Receive pane: a high-throughput, colour-coded serial log view."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor, QTextOption
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

#: Above this many bytes in one frame the view stops rendering every byte and
#: shows a summary instead, so the GUI stays interactive during a flood.
FLOOD_THRESHOLD_BYTES = 96 * 1024


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

        self.output = QPlainTextEdit()
        self.output.setObjectName("Terminal")
        self.output.setReadOnly(True)
        self.output.setUndoRedoEnabled(False)
        self.output.setMaximumBlockCount(MAX_DISPLAY_BLOCKS)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.output.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.output.setCenterOnScroll(False)
        self.output.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.output.setFont(monospace_font())
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

    def apply_font(self, family: str, size: int) -> None:
        font: QFont = monospace_font(family, size)
        self.output.setFont(font)

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
        """Append newly buffered chunks to the view."""
        if not chunks:
            return
        total = sum(chunk.size for chunk in chunks)
        if total > FLOOD_THRESHOLD_BYTES:
            self._append_flood_summary(chunks, total)
            return
        self._append_rendered(chunks)

    def _append_rendered(self, chunks: Sequence[TerminalChunk]) -> None:
        scrollbar = self.output.verticalScrollBar()
        follow = self.auto_scroll
        previous_value = scrollbar.value()

        cursor = QTextCursor(self.output.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        try:
            for chunk in chunks:
                text = self._renderer.render(chunk)
                if not text:
                    continue
                cursor.insertText(text, self._formats.get(chunk.direction, QTextCharFormat()))
        finally:
            cursor.endEditBlock()

        if follow:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(min(previous_value, scrollbar.maximum()))

    def _append_flood_summary(self, chunks: Sequence[TerminalChunk], total: int) -> None:
        """Render only the tail of an oversized frame.

        Rendering 5 MB of text in a single frame would stall the event loop for
        seconds.  The bytes are still in the buffer (and therefore still
        exportable) — only the *pixels* are skipped.
        """
        tail_budget = FLOOD_THRESHOLD_BYTES // 2
        tail: list[TerminalChunk] = []
        collected = 0
        for chunk in reversed(chunks):
            tail.append(chunk)
            collected += chunk.size
            if collected >= tail_budget:
                break
        tail.reverse()
        skipped = total - collected
        if skipped > 0:
            note = TerminalChunk(
                direction=Direction.INFO,
                data=(
                    f"\n… {skipped:,} bytes received faster than the display can render; "
                    "they are kept in the buffer and included in exports …\n"
                ).encode(),
                timestamp=tail[0].timestamp if tail else 0.0,
            )
            self._append_rendered([note])
        self._append_rendered(tail)

    def rerender(self) -> None:
        """Rebuild the whole view from the buffer (after a settings change)."""
        self._renderer = TerminalRenderer(
            display_mode=self.display_mode,
            show_timestamp=self.show_timestamp,
            encoding=self._settings.encoding,
            hex_bytes_per_line=self._settings.hex_bytes_per_line,
        )
        self.output.clear()
        chunks = self._buffer.chunks()
        if not chunks:
            return
        # Re-rendering a full 50 MB buffer would block; cap it and say so.
        budget = 4 * 1024 * 1024
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
        self._renderer.reset()

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
