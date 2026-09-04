"""Top bar: port selection, line settings and the connect action."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.logging_setup import get_logger
from ...models.enums import (
    COMMON_BAUD_RATES,
    DataBits,
    FlowControl,
    Parity,
    StopBits,
)
from ...models.settings import MAX_BAUD, MIN_BAUD, SerialSettings
from ...transport.ports import PortInfo, list_ports

_log = get_logger(__name__)


def _labelled(label_text: str, widget: QWidget, minimum_width: int = 0) -> QWidget:
    """Stack a small caption above a control."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    label = QLabel(label_text)
    label.setObjectName("FieldLabel")
    layout.addWidget(label)
    layout.addWidget(widget)
    if minimum_width:
        container.setMinimumWidth(minimum_width)
    container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return container


class ConnectionBar(QWidget):
    """Serial connection controls."""

    connectRequested = Signal()
    disconnectRequested = Signal()
    refreshRequested = Signal()
    settingsChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self._connected = False
        self._known_ports: list[PortInfo] = []
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(9)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(210)
        self.port_combo.setToolTip("Serial port to open")
        self.port_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        layout.addWidget(_labelled("Port", self.port_combo))

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Re-scan available ports (Ctrl+R)")
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        layout.addWidget(_labelled(" ", self.refresh_button))

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.baud_combo.setMinimumWidth(110)
        self.baud_combo.setToolTip(
            "Baud rate. Any value supported by the driver can be typed in."
        )
        self.baud_combo.addItems(str(rate) for rate in COMMON_BAUD_RATES)
        self.baud_combo.lineEdit().setValidator(QIntValidator(MIN_BAUD, MAX_BAUD, self))
        self.baud_combo.setCurrentText("115200")
        layout.addWidget(_labelled("Baud", self.baud_combo))

        self.data_bits_combo = self._enum_combo(DataBits, DataBits.EIGHT, 62)
        layout.addWidget(_labelled("Data", self.data_bits_combo))

        self.parity_combo = self._enum_combo(Parity, Parity.NONE, 84)
        layout.addWidget(_labelled("Parity", self.parity_combo))

        self.stop_bits_combo = self._enum_combo(StopBits, StopBits.ONE, 62)
        layout.addWidget(_labelled("Stop", self.stop_bits_combo))

        self.flow_combo = self._enum_combo(FlowControl, FlowControl.NONE, 150)
        layout.addWidget(_labelled("Flow control", self.flow_combo))

        layout.addStretch(1)

        self.status_label = QLabel("● Disconnected")
        self.status_label.setObjectName("StatusDot")
        self.status_label.setToolTip("Connection state")
        layout.addWidget(self.status_label)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("PrimaryButton")
        self.connect_button.setMinimumWidth(110)
        self.connect_button.setToolTip("Open or close the serial port (Ctrl+Enter)")
        self.connect_button.clicked.connect(self._on_connect_clicked)
        layout.addWidget(_labelled(" ", self.connect_button))

        for combo in (
            self.baud_combo,
            self.data_bits_combo,
            self.parity_combo,
            self.stop_bits_combo,
            self.flow_combo,
            self.port_combo,
        ):
            combo.currentTextChanged.connect(lambda _text: self.settingsChanged.emit())

    def _enum_combo(self, enum_cls, default, width: int) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(width)
        for member in enum_cls:
            combo.addItem(member.label, member)
        combo.setCurrentIndex(list(enum_cls).index(default))
        return combo

    # ------------------------------------------------------------------
    # Ports
    # ------------------------------------------------------------------
    def refresh_ports(self, *, keep_selection: bool = True) -> list[PortInfo]:
        """Re-enumerate ports, preserving the current selection if possible."""
        previous = self.selected_port()
        ports = list_ports()
        self._known_ports = ports

        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for info in ports:
            self.port_combo.addItem(info.display_name(), info.device)
        if not ports:
            self.port_combo.addItem("No ports found", "")
        self.port_combo.blockSignals(False)

        if keep_selection and previous:
            self.select_port(previous)
        self.settingsChanged.emit()
        return ports

    def select_port(self, device: str) -> bool:
        """Select ``device`` if present; returns False when it is gone."""
        if not device:
            return False
        for index in range(self.port_combo.count()):
            if self.port_combo.itemData(index) == device:
                self.port_combo.setCurrentIndex(index)
                return True
        return False

    def selected_port(self) -> str:
        data = self.port_combo.currentData()
        return str(data) if data else ""

    def known_ports(self) -> list[PortInfo]:
        return list(self._known_ports)

    # ------------------------------------------------------------------
    # Settings mapping
    # ------------------------------------------------------------------
    def baud_rate(self) -> int:
        text = self.baud_combo.currentText().strip()
        try:
            return int(text)
        except ValueError:
            return 115200

    def to_settings(self, base: SerialSettings | None = None) -> SerialSettings:
        """Build a :class:`SerialSettings` from the current widget state."""
        settings = SerialSettings() if base is None else base
        settings.port = self.selected_port()
        settings.baud_rate = self.baud_rate()
        settings.data_bits = self.data_bits_combo.currentData()
        settings.parity = self.parity_combo.currentData()
        settings.stop_bits = self.stop_bits_combo.currentData()
        settings.flow_control = self.flow_combo.currentData()
        return settings

    def apply_settings(self, settings: SerialSettings) -> None:
        """Push stored settings into the widgets without emitting churn."""
        widgets = (
            self.baud_combo,
            self.data_bits_combo,
            self.parity_combo,
            self.stop_bits_combo,
            self.flow_combo,
            self.port_combo,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.baud_combo.setCurrentText(str(settings.baud_rate))
            self._select_enum(self.data_bits_combo, settings.data_bits)
            self._select_enum(self.parity_combo, settings.parity)
            self._select_enum(self.stop_bits_combo, settings.stop_bits)
            self._select_enum(self.flow_combo, settings.flow_control)
            self.select_port(settings.port)
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    @staticmethod
    def _select_enum(combo: QComboBox, value) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    # ------------------------------------------------------------------
    # Connection state
    # ------------------------------------------------------------------
    def set_connected(self, connected: bool, description: str = "", color: str = "") -> None:
        """Reflect the connection state; port settings lock while connected."""
        self._connected = connected
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.connect_button.setObjectName("DangerButton" if connected else "PrimaryButton")
        # Re-polish so the object-name driven style is re-evaluated.
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)

        dot_color = color or ("#3fb950" if connected else "#6b7686")
        text = f"Connected — {description}" if connected and description else (
            "Connected" if connected else "Disconnected"
        )
        self.status_label.setText(
            f'<span style="color:{dot_color};">●</span> {text}'
        )
        self.status_label.setTextFormat(Qt.TextFormat.RichText)

        for widget in (
            self.port_combo,
            self.baud_combo,
            self.data_bits_combo,
            self.parity_combo,
            self.stop_bits_combo,
            self.flow_combo,
            self.refresh_button,
        ):
            widget.setEnabled(not connected)

    def _on_connect_clicked(self) -> None:
        if self._connected:
            self.disconnectRequested.emit()
        else:
            self.connectRequested.emit()
