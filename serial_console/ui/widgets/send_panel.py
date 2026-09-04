"""Send pane: command entry, line ending selection and history navigation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.history import CommandHistory
from ...models.enums import LineEnding
from ..theme import monospace_font


class CommandInput(QPlainTextEdit):
    """Entry box with shell-style history and Enter-to-send.

    A ``QPlainTextEdit`` rather than a ``QLineEdit`` so multi-line payloads are
    possible without a mode switch: **Enter** sends, **Shift+Enter** inserts a
    newline.  History navigation only triggers at the first/last line so it
    never fights ordinary text editing.
    """

    submitted = Signal()
    historyPrevious = Signal()
    historyNext = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabChangesFocus(True)
        self.setPlaceholderText("Type a command and press Enter…   (Shift+Enter for a new line)")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._update_height()
        self.textChanged.connect(self._update_height)

    def _update_height(self) -> None:
        """Grow with the content up to four lines, then scroll."""
        metrics = self.fontMetrics()
        lines = min(4, max(1, self.document().blockCount()))
        margin = int(self.document().documentMargin() * 2) + 12
        self.setFixedHeight(metrics.lineSpacing() * lines + margin)

    def text_value(self) -> str:
        return self.toPlainText()

    def set_text_value(self, text: str, *, select: bool = False) -> None:
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        if select:
            self.selectAll()

    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                # Ctrl+Enter is reserved for Connect/Disconnect at window level.
                event.ignore()
                return
            self.submitted.emit()
            event.accept()
            return

        if key == Qt.Key.Key_Up and not modifiers:
            cursor = self.textCursor()
            if cursor.blockNumber() == 0:
                self.historyPrevious.emit()
                event.accept()
                return

        if key == Qt.Key.Key_Down and not modifiers:
            cursor = self.textCursor()
            if cursor.blockNumber() == self.document().blockCount() - 1:
                self.historyNext.emit()
                event.accept()
                return

        super().keyPressEvent(event)


class SendPanel(QWidget):
    """The manual send area."""

    sendRequested = Signal(str, bool, object)
    """text, hex_mode, line_ending"""

    historyPicked = Signal(str)
    clearRequested = Signal()
    lineEndingChanged = Signal(object)

    def __init__(self, history: CommandHistory, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._history = history
        self._suppress = False
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Send")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)

        ending_label = QLabel("Line Ending:")
        ending_label.setObjectName("FieldLabel")
        header.addWidget(ending_label)

        self.line_ending_combo = QComboBox()
        self.line_ending_combo.setMinimumWidth(120)
        self.line_ending_combo.setToolTip(
            "Appended to every command — both typed commands and command buttons\n"
            "that are set to “Use global”."
        )
        for ending in LineEnding:
            self.line_ending_combo.addItem(ending.label, ending)
        self.line_ending_combo.setCurrentIndex(list(LineEnding).index(LineEnding.LF))
        self.line_ending_combo.currentIndexChanged.connect(self._on_line_ending_changed)
        header.addWidget(self.line_ending_combo)

        self.hex_button = QToolButton()
        self.hex_button.setText("HEX")
        self.hex_button.setCheckable(True)
        self.hex_button.setToolTip(
            "Interpret the input as hex bytes, e.g. 48 65 6C 6C 6F for “Hello”"
        )
        self.hex_button.toggled.connect(self._on_hex_toggled)
        header.addWidget(self.hex_button)

        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(150)
        self.history_combo.setMaxVisibleItems(20)
        self.history_combo.setToolTip("Previously sent commands (Arrow Up in the input box)")
        self.history_combo.activated.connect(self._on_history_activated)
        header.addWidget(self.history_combo)

        outer.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.input = CommandInput()
        self.input.setFont(monospace_font())
        self.input.submitted.connect(self._on_submit)
        self.input.historyPrevious.connect(self._on_history_previous)
        self.input.historyNext.connect(self._on_history_next)
        row.addWidget(self.input, 1)

        buttons = QVBoxLayout()
        buttons.setSpacing(5)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.setMinimumWidth(96)
        self.send_button.setToolTip("Send the command (Enter)")
        self.send_button.clicked.connect(self._on_submit)
        buttons.addWidget(self.send_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setMinimumWidth(96)
        self.clear_button.setToolTip("Clear the input box (Ctrl+K)")
        self.clear_button.clicked.connect(self.clear_input)
        buttons.addWidget(self.clear_button)
        row.addLayout(buttons)

        outer.addLayout(row)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("HintLabel")
        outer.addWidget(self.hint_label)

        self.refresh_history()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def line_ending(self) -> LineEnding:
        data = self.line_ending_combo.currentData()
        return data if isinstance(data, LineEnding) else LineEnding.NONE

    def set_line_ending(self, ending: LineEnding) -> None:
        self._suppress = True
        try:
            index = self.line_ending_combo.findData(ending)
            if index >= 0:
                self.line_ending_combo.setCurrentIndex(index)
        finally:
            self._suppress = False

    def hex_mode(self) -> bool:
        return self.hex_button.isChecked()

    def set_hex_mode(self, enabled: bool) -> None:
        self._suppress = True
        try:
            self.hex_button.setChecked(enabled)
        finally:
            self._suppress = False
        self._update_hint()

    def clear_input(self) -> None:
        self.input.clear()
        self._history.reset_cursor()
        self.clearRequested.emit()

    def focus_input(self) -> None:
        self.input.setFocus()

    def set_history(self, history: CommandHistory) -> None:
        self._history = history
        self.refresh_history()

    def refresh_history(self) -> None:
        """Reload the dropdown from the history model."""
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        entries = self._history.entries()
        self.history_combo.addItem(f"History ({len(entries)})", "")
        for entry in entries:
            label = entry if len(entry) <= 60 else entry[:57] + "…"
            self.history_combo.addItem(label.replace("\n", "⏎"), entry)
        self.history_combo.setCurrentIndex(0)
        self.history_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_submit(self) -> None:
        text = self.input.text_value()
        if not text.strip():
            return
        self.sendRequested.emit(text, self.hex_mode(), self.line_ending())

    def _on_history_previous(self) -> None:
        entry = self._history.previous()
        if entry is not None:
            self.input.set_text_value(entry)

    def _on_history_next(self) -> None:
        entry = self._history.next_entry()
        if entry is not None:
            self.input.set_text_value(entry)

    def _on_history_activated(self, index: int) -> None:
        entry = self.history_combo.itemData(index)
        self.history_combo.setCurrentIndex(0)
        if entry:
            self.input.set_text_value(str(entry))
            self.input.setFocus()
            self.historyPicked.emit(str(entry))

    def _on_line_ending_changed(self, _index: int) -> None:
        if self._suppress:
            return
        self.lineEndingChanged.emit(self.line_ending())

    def _on_hex_toggled(self, _checked: bool) -> None:
        self._update_hint()

    def _update_hint(self) -> None:
        if self.hex_mode():
            self.hint_label.setText(
                "Hex mode: enter bytes as 48 65 6C 6C 6F, 0x48 0x65 or 4865."
            )
        else:
            self.hint_label.setText("")

    def show_error(self, message: str) -> None:
        self.hint_label.setText(message)
