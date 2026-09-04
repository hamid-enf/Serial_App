"""Application settings dialog, grouped into Serial / Terminal / Appearance / Commands."""

from __future__ import annotations

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...models.enums import (
    BUFFER_PRESETS,
    COMMON_BAUD_RATES,
    DataBits,
    DisplayMode,
    FlowControl,
    LineEnding,
    Parity,
    StopBits,
    Theme,
)
from ...models.errors import ValidationError
from ...models.settings import (
    MAX_BAUD,
    MAX_HISTORY,
    MIN_BAUD,
    AppConfig,
)


class SettingsDialog(QDialog):
    """Edits a *copy* of the configuration; the caller applies it on accept."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._config = deepcopy_config(config)
        self._build()
        self._load()

    # ------------------------------------------------------------------
    @property
    def config(self) -> AppConfig:
        """The edited configuration copy."""
        return self._config

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_serial_tab(), "Serial")
        self.tabs.addTab(self._build_terminal_tab(), "Terminal")
        self.tabs.addTab(self._build_appearance_tab(), "Appearance")
        self.tabs.addTab(self._build_commands_tab(), "Commands")
        outer.addWidget(self.tabs)

        self.error_label = QLabel("")
        self.error_label.setObjectName("BannerError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        outer.addWidget(self.error_label)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        ok_button = box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setObjectName("PrimaryButton")
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        restore = box.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if restore is not None:
            restore.clicked.connect(self._on_restore_defaults)
        outer.addWidget(box)

    # ------------------------------------------------------------------
    def _build_serial_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(9)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(rate) for rate in COMMON_BAUD_RATES])
        baud_edit = self.baud_combo.lineEdit()
        if baud_edit is not None:
            baud_edit.setValidator(QIntValidator(MIN_BAUD, MAX_BAUD, self))
        form.addRow("Baud Rate", self.baud_combo)

        self.data_bits_combo = _enum_combo(DataBits)
        form.addRow("Data Bits", self.data_bits_combo)

        self.parity_combo = _enum_combo(Parity)
        form.addRow("Parity", self.parity_combo)

        self.stop_bits_combo = _enum_combo(StopBits)
        form.addRow("Stop Bits", self.stop_bits_combo)

        self.flow_combo = _enum_combo(FlowControl)
        form.addRow("Flow Control", self.flow_combo)

        self.dtr_check = QCheckBox("Assert DTR on connect")
        self.dtr_check.setToolTip(
            "Some boards reset when DTR is asserted. Turn this off to keep the\n"
            "device running when you open the port."
        )
        form.addRow("", self.dtr_check)

        self.rts_check = QCheckBox("Assert RTS on connect")
        form.addRow("", self.rts_check)

        self.write_timeout_spin = QSpinBox()
        self.write_timeout_spin.setRange(1, 120)
        self.write_timeout_spin.setSuffix(" s")
        self.write_timeout_spin.setToolTip(
            "How long a blocked write may wait before it is reported as a timeout."
        )
        form.addRow("Write Timeout", self.write_timeout_spin)

        note = QLabel(
            "These values are the defaults used when connecting; the top bar always "
            "reflects the current session."
        )
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        form.addRow("", note)
        return page

    def _build_terminal_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(9)

        self.timestamp_check = QCheckBox("Show a timestamp at the start of each line")
        form.addRow("Timestamp", self.timestamp_check)

        self.autoscroll_check = QCheckBox("Follow new output automatically")
        form.addRow("Auto Scroll", self.autoscroll_check)

        self.echo_check = QCheckBox("Echo sent commands in the receive pane")
        form.addRow("Echo TX", self.echo_check)

        self.buffer_combo = QComboBox()
        for label, value in BUFFER_PRESETS:
            self.buffer_combo.addItem(label, value)
        self.buffer_combo.setToolTip(
            "Maximum scrollback kept in memory. Older data is discarded once the\n"
            "limit is reached, so memory stays flat during long captures."
        )
        form.addRow("Maximum Buffer", self.buffer_combo)

        self.display_combo = _enum_combo(DisplayMode)
        form.addRow("Display Mode", self.display_combo)

        self.line_ending_combo = _enum_combo(LineEnding)
        self.line_ending_combo.setToolTip(
            "Global line ending, applied to typed commands and to any command\n"
            "button set to “Use global”."
        )
        form.addRow("Line Ending", self.line_ending_combo)

        self.hex_width_spin = QSpinBox()
        self.hex_width_spin.setRange(1, 64)
        self.hex_width_spin.setToolTip("Bytes per line in the Hex + ASCII display mode")
        form.addRow("Hex Bytes / Line", self.hex_width_spin)

        self.encoding_combo = QComboBox()
        self.encoding_combo.setEditable(True)
        self.encoding_combo.addItems(
            ["utf-8", "ascii", "latin-1", "cp1252", "utf-16-le", "shift_jis"]
        )
        form.addRow("Text Encoding", self.encoding_combo)
        return page

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(9)

        self.theme_combo = _enum_combo(Theme)
        form.addRow("Theme", self.theme_combo)

        self.font_combo = QFontComboBox()
        self.font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self.font_combo.setToolTip("Font used by the terminal and the input box")
        form.addRow("Font", self.font_combo)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 32)
        form.addRow("Font Size", self.font_size_spin)

        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(1, 8)
        form.addRow("Command Columns", self.columns_spin)
        return page

    def _build_commands_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(9)

        self.history_spin = QSpinBox()
        self.history_spin.setRange(0, MAX_HISTORY)
        self.history_spin.setToolTip(
            "How many sent commands are remembered per profile. 0 disables history."
        )
        form.addRow("History Size", self.history_spin)

        self.confirm_delete_check = QCheckBox("Ask before deleting a command button")
        form.addRow("", self.confirm_delete_check)

        self.flash_check = QCheckBox("Flash a command button when it is sent")
        form.addRow("", self.flash_check)

        note = QLabel(
            "Profiles are managed from the ⚙ button next to the profile selector "
            "in the Commands panel."
        )
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        form.addRow("", note)
        return page

    # ------------------------------------------------------------------
    def _load(self) -> None:
        config = self._config
        self.baud_combo.setCurrentText(str(config.serial.baud_rate))
        _select(self.data_bits_combo, config.serial.data_bits)
        _select(self.parity_combo, config.serial.parity)
        _select(self.stop_bits_combo, config.serial.stop_bits)
        _select(self.flow_combo, config.serial.flow_control)
        self.dtr_check.setChecked(config.serial.dtr)
        self.rts_check.setChecked(config.serial.rts)
        self.write_timeout_spin.setValue(max(1, int(config.serial.write_timeout_s)))

        self.timestamp_check.setChecked(config.terminal.show_timestamp)
        self.autoscroll_check.setChecked(config.terminal.auto_scroll)
        self.echo_check.setChecked(config.terminal.echo_tx)
        index = self.buffer_combo.findData(config.terminal.max_buffer_bytes)
        if index < 0:
            self.buffer_combo.addItem(
                f"{config.terminal.max_buffer_bytes // (1024 * 1024)} MB",
                config.terminal.max_buffer_bytes,
            )
            index = self.buffer_combo.count() - 1
        self.buffer_combo.setCurrentIndex(index)
        _select(self.display_combo, config.terminal.display_mode)
        _select(self.line_ending_combo, config.terminal.line_ending)
        self.hex_width_spin.setValue(config.terminal.hex_bytes_per_line)
        self.encoding_combo.setCurrentText(config.terminal.encoding)

        _select(self.theme_combo, config.appearance.theme)
        if config.appearance.font_family:
            self.font_combo.setCurrentText(config.appearance.font_family)
        self.font_size_spin.setValue(config.appearance.font_size)
        self.columns_spin.setValue(config.appearance.command_button_columns)

        self.history_spin.setValue(config.commands.history_limit)
        self.confirm_delete_check.setChecked(config.commands.confirm_delete)
        self.flash_check.setChecked(config.commands.flash_on_send)

    def _collect(self) -> None:
        config = self._config
        try:
            config.serial.baud_rate = int(self.baud_combo.currentText().strip())
        except ValueError as exc:
            raise ValidationError("Baud rate must be a whole number.") from exc
        config.serial.data_bits = self.data_bits_combo.currentData()
        config.serial.parity = self.parity_combo.currentData()
        config.serial.stop_bits = self.stop_bits_combo.currentData()
        config.serial.flow_control = self.flow_combo.currentData()
        config.serial.dtr = self.dtr_check.isChecked()
        config.serial.rts = self.rts_check.isChecked()
        config.serial.write_timeout_s = float(self.write_timeout_spin.value())

        config.terminal.show_timestamp = self.timestamp_check.isChecked()
        config.terminal.auto_scroll = self.autoscroll_check.isChecked()
        config.terminal.echo_tx = self.echo_check.isChecked()
        config.terminal.max_buffer_bytes = int(self.buffer_combo.currentData())
        config.terminal.display_mode = self.display_combo.currentData()
        config.terminal.line_ending = self.line_ending_combo.currentData()
        config.terminal.hex_bytes_per_line = int(self.hex_width_spin.value())
        config.terminal.encoding = self.encoding_combo.currentText().strip() or "utf-8"

        config.appearance.theme = self.theme_combo.currentData()
        config.appearance.font_family = self.font_combo.currentFont().family()
        config.appearance.font_size = int(self.font_size_spin.value())
        config.appearance.command_button_columns = int(self.columns_spin.value())

        config.commands.history_limit = int(self.history_spin.value())
        config.commands.confirm_delete = self.confirm_delete_check.isChecked()
        config.commands.flash_on_send = self.flash_check.isChecked()

        _validate_encoding(config.terminal.encoding)
        config.serial.baud_rate = max(MIN_BAUD, min(MAX_BAUD, config.serial.baud_rate))
        config.terminal.validate()
        config.appearance.validate()
        config.commands.validate()

    def _on_accept(self) -> None:
        try:
            self._collect()
        except ValidationError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.accept()

    def _on_restore_defaults(self) -> None:
        defaults = AppConfig.create_default()
        self._config.serial.baud_rate = defaults.serial.baud_rate
        self._config.serial.data_bits = defaults.serial.data_bits
        self._config.serial.parity = defaults.serial.parity
        self._config.serial.stop_bits = defaults.serial.stop_bits
        self._config.serial.flow_control = defaults.serial.flow_control
        self._config.serial.dtr = defaults.serial.dtr
        self._config.serial.rts = defaults.serial.rts
        self._config.serial.write_timeout_s = defaults.serial.write_timeout_s
        self._config.terminal = defaults.terminal
        self._config.appearance.theme = defaults.appearance.theme
        self._config.appearance.font_family = defaults.appearance.font_family
        self._config.appearance.font_size = defaults.appearance.font_size
        self._config.appearance.command_button_columns = (
            defaults.appearance.command_button_columns
        )
        self._config.commands = defaults.commands
        self._load()


def _enum_combo(enum_cls) -> QComboBox:
    combo = QComboBox()
    for member in enum_cls:
        combo.addItem(member.label, member)
    return combo


def _select(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _validate_encoding(name: str) -> None:
    try:
        "probe".encode(name)
    except LookupError as exc:
        raise ValidationError(f"“{name}” is not a text encoding Python knows about.") from exc


def deepcopy_config(config: AppConfig) -> AppConfig:
    """Round-trip through the serialiser to get an independent copy."""
    return AppConfig.from_dict(config.to_dict())
