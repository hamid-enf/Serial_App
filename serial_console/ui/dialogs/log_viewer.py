"""Built-in log viewer so users can report issues without hunting for files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.logging_setup import log_file_path, memory_handler
from ..theme import monospace_font


class LogViewerDialog(QDialog):
    """Tail of the in-memory log ring, refreshed while open."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Application Log")
        self.setMinimumSize(760, 460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(9)

        path: Path | None = log_file_path()
        header = QLabel(
            f"Log file: {path}" if path else "File logging is not available in this session."
        )
        header.setObjectName("HintLabel")
        header.setTextInteractionFlags(
            header.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        header.setWordWrap(True)
        outer.addWidget(header)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(monospace_font(size=9))
        self.view.setMaximumBlockCount(5000)
        outer.addWidget(self.view, 1)

        row = QHBoxLayout()
        self.copy_button = QPushButton("Copy All")
        self.copy_button.clicked.connect(self._copy_all)
        row.addWidget(self.copy_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear)
        row.addWidget(self.clear_button)
        row.addStretch(1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.accept)
        box.accepted.connect(self.accept)
        row.addWidget(box)
        outer.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.reload)
        self._timer.start()
        self.reload()

    # ------------------------------------------------------------------
    def reload(self) -> None:
        handler = memory_handler()
        if handler is None:
            self.view.setPlainText("No log records have been captured yet.")
            return
        scrollbar = self.view.verticalScrollBar()
        at_end = scrollbar.value() >= scrollbar.maximum() - 4
        self.view.setPlainText("\n".join(handler.lines()))
        if at_end:
            scrollbar.setValue(scrollbar.maximum())

    def _copy_all(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.view.toPlainText())

    def _clear(self) -> None:
        handler = memory_handler()
        if handler is not None:
            handler.clear()
        self.view.clear()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
