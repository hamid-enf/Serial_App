#!/usr/bin/env python3
"""Render documentation screenshots headlessly.

Runs the real application against the in-process loopback transport, stages a
plausible session and grabs the window — no display and no hardware required,
so the images in the README can be regenerated in CI whenever the UI changes.

Usage::

    QT_QPA_PLATFORM=offscreen python scripts/screenshot.py
    QT_QPA_PLATFORM=offscreen python scripts/screenshot.py --theme light \\
        --output docs/images/light.png
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_COMMANDS = [
    ("Read Sensor", "AT+READ_SENSOR"),
    ("Read Temp", "AT+TEMP?"),
    ("Motor ON", "MOTOR ON"),
    ("Motor OFF", "MOTOR OFF"),
    ("Get Status", "AT+STATUS"),
    ("Firmware Ver", "AT+GMR"),
    ("WiFi Scan", "AT+CWLAP"),
    ("Reset MCU", "AT+RST"),
    ("Calibrate", "CAL START"),
    ("Dump EEPROM", "EE DUMP 0 256"),
]

DEMO_TRAFFIC = [
    b"[boot] ESP32 rev1, 4MB flash\r\n",
    b"[wifi] connecting to lab-net ...\r\n",
    b"[wifi] got ip 192.168.4.27\r\n",
    b"OK\r\n",
    b"+TEMP: 24.8 C\r\n",
    b"+HUMIDITY: 41.2 %\r\n",
    b"+SENSOR: 0x1A2B  vref=3.301V  rssi=-58dBm\r\n",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/images/dark.png"))
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=880)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Never touch the developer's real configuration.
    scratch = tempfile.mkdtemp(prefix="serial-console-shot-")
    os.environ["SERIAL_CONSOLE_HOME"] = scratch

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from serial_console.config.paths import ensure_dirs, log_dir
    from serial_console.config.store import ConfigStore
    from serial_console.core.logging_setup import setup_logging
    from serial_console.models.enums import Theme
    from serial_console.transport.loopback import LoopbackTransport
    from serial_console.ui.main_window import MainWindow
    from serial_console.ui.theme import apply_theme

    ensure_dirs()
    setup_logging(log_dir())

    app = QApplication([])
    config = ConfigStore().load().config
    theme = Theme.LIGHT if args.theme == "light" else Theme.DARK
    config.appearance.theme = theme
    apply_theme(app, theme)

    transport = LoopbackTransport(echo=False)
    window = MainWindow(config, store=ConfigStore(), transport=transport)
    window.resize(args.width, args.height)
    window.show()

    profile = window.profiles.active()
    for index, (name, command) in enumerate(DEMO_COMMANDS):
        if index < len(profile.buttons):
            profile.buttons[index].name = name
            profile.buttons[index].command = command
    profile.buttons[0].auto_send.enabled = True
    profile.buttons[0].auto_send.interval_ms = 500
    window.command_panel.rebuild()

    settings = window.connection_bar.to_settings(config.serial)
    settings.port = "LOOPBACK"
    settings.baud_rate = 115200

    def stage() -> None:
        window.service.connect_port(settings)
        for line in DEMO_TRAFFIC:
            transport.feed(line)

    def send_one() -> None:
        window.send_panel.input.set_text_value("AT+READ_SENSOR")
        window.send_manual("AT+READ_SENSOR", False, window.send_panel.line_ending())
        transport.feed(b"+SENSOR: 0x1A2C  vref=3.299V  rssi=-57dBm\r\nOK\r\n")

    def shoot() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(args.output))
        print(f"saved {args.output}")
        window.service.shutdown()
        app.quit()

    QTimer.singleShot(200, stage)
    QTimer.singleShot(700, send_one)
    QTimer.singleShot(1400, shoot)
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
