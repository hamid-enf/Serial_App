"""Status bar showing connection state and live counters."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStatusBar, QWidget

from ... import SIGNATURE, WEBSITE
from ...core.stats import format_bytes


def _separator() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Separator")
    frame.setFixedWidth(1)
    frame.setFrameShape(QFrame.Shape.VLine)
    return frame


class StatusBar(QStatusBar):
    """Connection state, port, baud rate, RX/TX counters and throughput."""

    resetCountersRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(True)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(10)

        self.state_label = QLabel("● Disconnected")
        self.state_label.setToolTip("Connection state")
        layout.addWidget(self.state_label)
        layout.addWidget(_separator())

        self.port_label = QLabel("Port: —")
        layout.addWidget(self.port_label)
        layout.addWidget(_separator())

        self.baud_label = QLabel("Baud: —")
        layout.addWidget(self.baud_label)
        layout.addWidget(_separator())

        self.rx_label = QLabel("RX: 0 B")
        self.rx_label.setToolTip("Bytes received this session")
        layout.addWidget(self.rx_label)

        self.tx_label = QLabel("TX: 0 B")
        self.tx_label.setToolTip("Bytes transmitted this session")
        layout.addWidget(self.tx_label)

        self.rate_label = QLabel("idle")
        self.rate_label.setToolTip("Current receive throughput")
        layout.addWidget(self.rate_label)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Reset the RX/TX counters")
        self.reset_button.setFlat(True)
        self.reset_button.clicked.connect(self.resetCountersRequested.emit)
        layout.addWidget(self.reset_button)

        layout.addWidget(_separator())
        self.message_label = QLabel("")
        self.message_label.setObjectName("HintLabel")
        layout.addWidget(self.message_label, 1)

        layout.addWidget(_separator())
        # Quiet authorship mark, right-aligned so it never competes with the
        # live counters for attention.
        self.signature_label = QLabel(SIGNATURE)
        self.signature_label.setObjectName("SignatureLabel")
        self.signature_label.setToolTip(f"{SIGNATURE} — {WEBSITE}")
        layout.addWidget(self.signature_label)

        self.addPermanentWidget(container, 1)

    # ------------------------------------------------------------------
    def set_connection(
        self, connected: bool, port: str = "", baud: int = 0, color: str = ""
    ) -> None:
        dot = color or ("#3fb950" if connected else "#6b7686")
        text = f"Connected — {port} @ {baud}" if connected else "Disconnected"
        _set_text(self.state_label, f'<span style="color:{dot};">●</span> {text}')
        _set_text(self.port_label, f"Port: {port or '—'}")
        _set_text(self.baud_label, f"Baud: {baud or '—'}")

    def set_counters(self, rx_bytes: int, tx_bytes: int, rate_text: str = "") -> None:
        # QLabel::setText relayouts and repaints even when the string is
        # identical.  Twice a second, forever, with a formatted byte count that
        # rarely changes at low rates — worth the three comparisons.
        _set_text(self.rx_label, f"RX: {format_bytes(rx_bytes)}")
        _set_text(self.tx_label, f"TX: {format_bytes(tx_bytes)}")
        _set_text(self.rate_label, rate_text or "idle")

    def set_message(self, text: str) -> None:
        _set_text(self.message_label, text)


def _set_text(label: QLabel, text: str) -> None:
    """Assign ``text`` only when it differs from what the label already shows."""
    if label.text() != text:
        label.setText(text)
