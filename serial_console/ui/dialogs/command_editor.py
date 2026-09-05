"""Dialog for editing a single command button."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.codec import build_payload, format_hex
from ...models.command import (
    MAX_AUTO_SEND_INTERVAL_MS,
    MIN_AUTO_SEND_INTERVAL_MS,
    CommandButton,
)
from ...models.enums import LineEnding
from ...models.errors import ValidationError
from ..theme import monospace_font

#: Sentinel used in the line-ending combo for "inherit the global setting".
_INHERIT = "__inherit__"


class CommandEditorDialog(QDialog):
    """Edit name, payload, line ending, auto-send and description."""

    def __init__(
        self,
        button: CommandButton,
        global_line_ending: LineEnding,
        parent: QWidget | None = None,
        *,
        title: str = "Edit Command Button",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        self._original = button
        self._global_line_ending = global_line_ending
        self._build()
        self._load(button)
        self._update_preview()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(64)
        self.name_edit.setPlaceholderText("Read Sensor")
        self.name_edit.textChanged.connect(self._update_preview)
        form.addRow("Button Name", self.name_edit)

        self.command_edit = QPlainTextEdit()
        self.command_edit.setFont(monospace_font())
        self.command_edit.setPlaceholderText("AT+READ_SENSOR")
        self.command_edit.setFixedHeight(80)
        self.command_edit.textChanged.connect(self._update_preview)
        form.addRow("Command", self.command_edit)

        self.hex_check = QCheckBox("Interpret the command as hex bytes (e.g. 48 65 6C 6C 6F)")
        self.hex_check.toggled.connect(self._update_preview)
        form.addRow("", self.hex_check)

        self.line_ending_combo = QComboBox()
        self.line_ending_combo.addItem(
            f"Use global ({self._global_line_ending.label})", _INHERIT
        )
        for ending in LineEnding:
            self.line_ending_combo.addItem(ending.label, ending)
        self.line_ending_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("Line Ending", self.line_ending_combo)

        self.description_edit = QLineEdit()
        self.description_edit.setMaxLength(512)
        self.description_edit.setPlaceholderText("Optional note shown in the tooltip")
        form.addRow("Description", self.description_edit)

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(True)
        form.addRow("", self.enabled_check)

        auto_row = QHBoxLayout()
        auto_row.setSpacing(8)
        self.auto_check = QCheckBox("Auto-send every")
        self.auto_check.toggled.connect(self._on_auto_toggled)
        auto_row.addWidget(self.auto_check)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(MIN_AUTO_SEND_INTERVAL_MS, MAX_AUTO_SEND_INTERVAL_MS)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setValue(1000)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setEnabled(False)
        self.interval_spin.setMaximumWidth(130)
        auto_row.addWidget(self.interval_spin)
        auto_row.addStretch(1)
        auto_container = QWidget()
        auto_container.setLayout(auto_row)
        form.addRow("Auto Repeat", auto_container)

        outer.addLayout(form)

        self.preview_label = QLabel("")
        self.preview_label.setObjectName("HintLabel")
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.preview_label)

        self.error_label = QLabel("")
        self.error_label.setObjectName("BannerError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        outer.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button is not None:
            save_button.setObjectName("PrimaryButton")
            save_button.setDefault(True)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

    # ------------------------------------------------------------------
    def _load(self, button: CommandButton) -> None:
        self.name_edit.setText(button.name)
        self.command_edit.setPlainText(button.command)
        self.hex_check.setChecked(button.hex_mode)
        self.description_edit.setText(button.description)
        self.enabled_check.setChecked(button.enabled)
        self.auto_check.setChecked(button.auto_send.enabled)
        self.interval_spin.setValue(button.auto_send.interval_ms)
        self.interval_spin.setEnabled(button.auto_send.enabled)
        if button.line_ending is None:
            self.line_ending_combo.setCurrentIndex(0)
        else:
            index = self.line_ending_combo.findData(button.line_ending)
            self.line_ending_combo.setCurrentIndex(max(0, index))

    def _on_auto_toggled(self, checked: bool) -> None:
        self.interval_spin.setEnabled(checked)
        self._update_preview()

    # ------------------------------------------------------------------
    def selected_line_ending(self) -> LineEnding | None:
        data = self.line_ending_combo.currentData()
        return None if data == _INHERIT else data

    def _effective_line_ending(self) -> LineEnding:
        chosen = self.selected_line_ending()
        return self._global_line_ending if chosen is None else chosen

    def _update_preview(self) -> None:
        """Show the exact bytes that will go on the wire."""
        text = self.command_edit.toPlainText()
        ending = self._effective_line_ending()
        try:
            payload = build_payload(text, hex_mode=self.hex_check.isChecked(), line_ending=ending)
        except ValidationError as exc:
            self.preview_label.setText("")
            self._show_error(str(exc))
            return
        self._hide_error()
        if not payload:
            self.preview_label.setText("Nothing will be sent — the command is empty.")
            return
        preview = payload[:64]
        suffix = " …" if len(payload) > 64 else ""
        self.preview_label.setText(
            f"On the wire: <code>{format_hex(preview)}{suffix}</code> "
            f"({len(payload)} byte{'s' if len(payload) != 1 else ''})"
        )
        self.preview_label.setTextFormat(Qt.TextFormat.RichText)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _hide_error(self) -> None:
        self.error_label.hide()

    # ------------------------------------------------------------------
    def result_button(self) -> CommandButton:
        """Build the edited model (call only after ``exec()`` returned Accepted)."""
        button = CommandButton(
            id=self._original.id,
            name=self.name_edit.text().strip(),
            command=self.command_edit.toPlainText(),
            line_ending=self.selected_line_ending(),
            hex_mode=self.hex_check.isChecked(),
            enabled=self.enabled_check.isChecked(),
            description=self.description_edit.text().strip(),
            color=self._original.color,
        )
        button.auto_send.enabled = self.auto_check.isChecked()
        button.auto_send.interval_ms = int(self.interval_spin.value())
        return button

    def _on_accept(self) -> None:
        try:
            candidate = self.result_button()
            candidate.validate()
        except ValidationError as exc:
            self._show_error(str(exc))
            return
        self.accept()
