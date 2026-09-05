#!/usr/bin/env python3
"""Render the promotional clip for the ENF Serial Command Console.

Everything on screen is the *real* application: the window is driven
frame-by-frame offscreen and grabbed, then composited onto a branded
background with Persian titles. Frames are piped straight into ffmpeg, so no
intermediate images touch the disk.

    QT_QPA_PLATFORM=offscreen python scripts/promo/render_promo.py \
        --aspect 16x9 --out promo/enf-serial-console-16x9.mp4

The timeline is driven by the narration: see SEGMENTS below, whose durations
come from the generated voice-over files.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FPS = 30
WINDOW_W, WINDOW_H = 1680, 945          # app window render size (16:9 master)
WINDOW_PORTRAIT = (1240, 1180)          # roomier shape for the 9:16 cut
FONT_DIR = Path(
    os.environ.get("PROMO_FONT_DIR", "/tmp/vazir/vazirmatn-master/fonts/ttf")
)
"""Directory holding Vazirmatn*.ttf — the Persian titles need it.

Download from https://github.com/rastikerdar/vazirmatn/releases and point
``PROMO_FONT_DIR`` at the ``fonts/ttf`` folder.
"""

# Brand palette
BG_TOP = "#070a10"
BG_BOTTOM = "#101825"
ACCENT = "#4a9eff"
INK = "#e8edf5"
MUTED = "#93a1b5"


# ======================================================================
# Timeline
# ======================================================================
@dataclass
class Cue:
    """A titled moment on the timeline."""

    start: float
    end: float
    scene: str
    title: str = ""          # Persian overlay
    subtitle: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


def build_timeline(vo_offsets: dict[str, tuple[float, float]]) -> list[Cue]:
    """Lay the visuals over the narration timings."""
    s1 = vo_offsets["01"]
    s2 = vo_offsets["02"]
    s3 = vo_offsets["03"]
    s4 = vo_offsets["04"]
    s5 = vo_offsets["05"]
    s6 = vo_offsets["06"]
    s8 = vo_offsets["08"]
    end = s8[1] + 1.7

    return [
        Cue(0.0, s2[0] - 0.25, "cold_open",
            "هر روز، ده‌ها بار…", "همان دستورهای تکراری"),
        Cue(s2[0] - 0.25, s3[0] - 0.35, "logo",
            "کنسول فرمان سریال", "ENF Serial Command Console"),
        Cue(s3[0] - 0.35, s3[1] + 0.15, "buttons",
            "۲۰ دکمه‌ی فرمان، کاملاً دلخواه",
            "نام · دستور · پایان خط · تکرار خودکار"),
        Cue(s3[1] + 0.15, s4[1] + 0.15, "profiles",
            "برای هر برد، یک پروفایل",
            "دکمه‌ها، تنظیمات و تاریخچه‌ی مخصوص خودش"),
        Cue(s4[1] + 0.15, s5[1] + 0.15, "flood",
            "۲ مگابیت بر ثانیه، بدون ذره‌ای لگ",
            "ارتباط سریال روی ترد جدا"),
        Cue(s5[1] + 0.15, s6[1] + 0.15, "features",
            "", ""),  # rotating captions handled inside the scene
        Cue(s6[1] + 0.15, end, "endcard",
            "رایگان و متن‌باز", "github.com/hamid-enf/Serial_App"),
    ]


FEATURE_CAPTIONS = [
    ("نمایش هگز و اَسکی", "همان داده، دو زبان"),
    ("زمان‌نگار دقیق روی هر خط", "برای دیباگ‌های سخت"),
    ("خروجی متنی، CSV و باینری", "لاگ‌ها را نگه دار"),
    ("تم روشن و تیره", "همه چیز ذخیره می‌شود"),
    ("پیام خطای انسانی", "نه یک ارور مبهم"),
]


# ======================================================================
# Application driver
# ======================================================================
class Driver:
    """Owns the real MainWindow and exposes scene-level state changes."""

    def __init__(self) -> None:
        from serial_console.config.store import ConfigStore
        from serial_console.models.settings import AppConfig
        from serial_console.transport.loopback import LoopbackTransport
        from serial_console.ui.main_window import MainWindow

        self.config = AppConfig.create_default()
        self.config.serial.port = "COM7"
        self.config.serial.baud_rate = 115200
        store = ConfigStore("/tmp/promo-home/config.json")
        self.window = MainWindow(
            self.config, store, transport=LoopbackTransport(echo=False)
        )
        self.window.resize(WINDOW_W, WINDOW_H)
        self.window.show()

        # Timers would fight the frame-accurate capture.
        self.window._stats_timer.stop()
        self.window._autosave_timer.stop()
        self.window._banner_timer.stop()

        self._name_buttons()
        self.config.terminal.show_timestamp = False
        self.window.terminal.apply_settings(self.config.terminal, self.config.appearance.theme)
        self.window._buffer.clear()
        self.window.terminal.clear()
        self.set_connected(False)

    # -- setup ---------------------------------------------------------
    def _name_buttons(self) -> None:
        names = [
            ("Read Temp", "AT+TEMP?"), ("Read Sensor", "AT+READ_SENSOR"),
            ("Get Status", "AT+STATUS"), ("Firmware Ver", "AT+GMR"),
            ("Motor ON", "MOTOR ON"), ("Motor OFF", "MOTOR OFF"),
            ("WiFi Scan", "AT+CWLAP"), ("Reset MCU", "AT+RST"),
            ("Calibrate", "CAL START"), ("Dump EEPROM", "EE DUMP 0 256"),
            ("Ping", "PING"), ("Battery", "AT+BAT?"),
        ]
        for index, (name, command) in enumerate(names):
            if index < len(self.window._commands.buttons):
                button = self.window._commands.buttons[index]
                button.name, button.command = name, command
        self.window._commands.buttons[0].auto_send.enabled = True
        self.window._commands.buttons[0].auto_send.interval_ms = 500
        self.window.command_panel.rebuild()

    # -- state ---------------------------------------------------------
    def set_connected(self, connected: bool, port: str = "COM7", baud: int = 115200) -> None:
        self.window.connection_bar.set_connected(connected, f"{port} @ {baud}")
        self.window.status.set_connection(connected, port, baud)

    def feed(self, text: str) -> None:
        from serial_console.models.enums import Direction

        chunks = self.window._buffer.append(Direction.RX, text.encode("utf-8"))
        self.window.terminal.append_chunks(chunks)
        self.window._stats.add_rx(len(text))

    def send(self, text: str) -> None:
        from serial_console.models.enums import Direction

        payload = (text + "\n").encode("utf-8")
        chunks = self.window._buffer.append(Direction.TX, payload)
        self.window.terminal.append_chunks(chunks)
        self.window._stats.add_tx(len(payload))

    def counters(self, rate: str = "") -> None:
        from serial_console.core.stats import format_bytes

        self.window.status.set_counters(
            self.window._stats.rx_bytes, self.window._stats.tx_bytes, rate
        )
        self.window.terminal.set_throughput_text(rate)
        _ = format_bytes

    def type_input(self, text: str) -> None:
        self.window.send_panel.input.set_text_value(text)

    def flash(self, index: int) -> None:
        button = self.window._commands.buttons[index]
        widget = self.window.command_panel.widget_for(button.id)
        if widget is not None:
            widget.flash()

    def repeating(self, index: int, on: bool) -> None:
        button = self.window._commands.buttons[index]
        self.window.command_panel.set_repeating(button.id, on)

    def set_theme(self, theme_name: str) -> None:
        from PySide6.QtWidgets import QApplication

        from serial_console.models.enums import Theme
        from serial_console.ui.theme import apply_theme

        theme = Theme.LIGHT if theme_name == "light" else Theme.DARK
        self.config.appearance.theme = theme
        apply_theme(QApplication.instance(), theme)
        self.window.terminal.apply_settings(self.config.terminal, theme)

    def set_display_mode(self, mode_name: str) -> None:
        from serial_console.models.enums import DisplayMode

        mode = {
            "ascii": DisplayMode.ASCII,
            "hex": DisplayMode.HEX,
            "both": DisplayMode.BOTH,
        }[mode_name]
        self.config.terminal.display_mode = mode
        self.window.terminal.apply_settings(
            self.config.terminal, self.config.appearance.theme
        )

    def set_timestamps(self, enabled: bool) -> None:
        self.config.terminal.show_timestamp = enabled
        self.window.terminal.apply_settings(
            self.config.terminal, self.config.appearance.theme
        )

    def switch_profile(self, name: str, commands: list[tuple[str, str]]) -> None:
        profile = self.window._profiles.create(name, button_count=len(commands))
        for button, (label, cmd) in zip(profile.buttons, commands, strict=False):
            button.name, button.command = label, cmd
        self.window._on_profile_changed(profile.id)
        self.window.command_panel.rebuild()

    def banner(self, message: str, hint: str) -> None:
        from serial_console.core.errors import Severity, UserError

        self.window._show_banner(
            UserError(message=message, hint=hint, severity=Severity.ERROR)
        )
        self.window._banner_timer.stop()

    def hide_banner(self) -> None:
        self.window._hide_banner()

    # -- capture -------------------------------------------------------
    def grab(self):
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        return self.window.grab().toImage()


# ======================================================================
# Compositor
# ======================================================================
def ease(t: float) -> float:
    """Smooth 0..1 ramp."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


class Compositor:
    def __init__(self, width: int, height: int, vertical: bool) -> None:
        from PySide6.QtGui import QFontDatabase

        self.w, self.h = width, height
        self.vertical = vertical
        self.fa_family = "DejaVu Sans"
        for weight in ("Regular", "Bold", "Black", "Medium"):
            path = FONT_DIR / f"Vazirmatn-{weight}.ttf"
            if path.exists():
                fid = QFontDatabase.addApplicationFont(str(path))
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    self.fa_family = families[0]
        self._bg = self._make_background()

    # -- background ----------------------------------------------------
    def _make_background(self):
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient

        img = QImage(self.w, self.h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.black)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        grad = QLinearGradient(0, 0, self.w * 0.3, self.h)
        grad.setColorAt(0.0, QColor(BG_TOP))
        grad.setColorAt(1.0, QColor(BG_BOTTOM))
        p.fillRect(0, 0, self.w, self.h, grad)

        glow = QRadialGradient(QPointF(self.w * 0.5, self.h * 0.42), self.w * 0.65)
        glow.setColorAt(0.0, QColor(74, 158, 255, 46))
        glow.setColorAt(1.0, QColor(74, 158, 255, 0))
        p.fillRect(QRectF(0, 0, self.w, self.h), glow)

        # Faint engineering grid — reads as "instrument", not "wallpaper".
        p.setPen(QColor(255, 255, 255, 8))
        step = 64
        for x in range(0, self.w, step):
            p.drawLine(x, 0, x, self.h)
        for y in range(0, self.h, step):
            p.drawLine(0, y, self.w, y)
        p.end()
        return img

    def new_frame(self):
        return self._bg.copy()

    # -- helpers -------------------------------------------------------
    def font(self, size: int, weight: str = "Bold", family: str | None = None):
        from PySide6.QtGui import QFont

        f = QFont(family or self.fa_family)
        f.setPixelSize(size)
        f.setWeight(
            {"Regular": QFont.Weight.Normal, "Medium": QFont.Weight.Medium,
             "Bold": QFont.Weight.Bold, "Black": QFont.Weight.Black}[weight]
        )
        return f

    def draw_window(self, painter, shot, rect, radius: int = 16, shadow: bool = True):
        """Draw the app screenshot as a floating, rounded, shadowed panel."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QBrush, QColor, QPainterPath

        if shadow:
            for i in range(18, 0, -1):
                alpha = int(70 * (i / 18) ** 3)
                spread = i * 2.4
                shadow_rect = QRectF(
                    rect.x() - spread, rect.y() - spread * 0.35 + 14,
                    rect.width() + spread * 2, rect.height() + spread * 2,
                )
                path = QPainterPath()
                path.addRoundedRect(shadow_rect, radius + spread * 0.5, radius + spread * 0.5)
                painter.fillPath(path, QColor(0, 0, 0, alpha // 3))

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.drawImage(rect, shot)
        painter.restore()

        painter.setBrush(QBrush())
        painter.setPen(QColor(255, 255, 255, 26))
        painter.drawPath(path)

    def draw_title(self, painter, title: str, subtitle: str, alpha: float,
                   y: int | None = None) -> None:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor

        if alpha <= 0.01 or not (title or subtitle):
            return
        a = max(0.0, min(1.0, alpha))
        big = self.font(58 if not self.vertical else 62, "Black")
        small = self.font(30 if not self.vertical else 34, "Medium")
        base_y = y if y is not None else (self.h - (178 if not self.vertical else 400))

        painter.setFont(big)
        painter.setPen(QColor(232, 237, 245, int(255 * a)))
        painter.drawText(
            QRectF(60, base_y, self.w - 120, 76),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            title,
        )
        if subtitle:
            painter.setFont(small)
            painter.setPen(QColor(147, 161, 181, int(235 * a)))
            painter.drawText(
                QRectF(60, base_y + 74, self.w - 120, 46),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                subtitle,
            )

    def draw_wordmark(self, painter, alpha: float = 1.0) -> None:
        """Top-of-frame branding for the vertical cut."""
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor

        painter.setFont(self.font(46, "Black", "DejaVu Sans"))
        painter.setPen(QColor(232, 237, 245, int(235 * alpha)))
        painter.drawText(
            QRectF(0, self.h * 0.075, self.w, 60),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            "ENF Serial Command Console",
        )
        painter.setFont(self.font(30, "Medium"))
        painter.setPen(QColor(74, 158, 255, int(235 * alpha)))
        painter.drawText(
            QRectF(0, self.h * 0.075 + 58, self.w, 46),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            "\u06a9\u0646\u0633\u0648\u0644 \u0641\u0631\u0645\u0627\u0646 \u0633\u0631\u06cc\u0627\u0644",
        )

    def draw_watermark(self, painter, alpha: float = 1.0) -> None:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor

        painter.setFont(self.font(22, "Black", "DejaVu Sans"))
        painter.setPen(QColor(147, 161, 181, int(150 * alpha)))
        painter.drawText(
            QRectF(0, self.h - 58, self.w - 46, 34),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            "ENF",
        )


# ======================================================================
# Scenes
# ======================================================================
class Renderer:
    def __init__(self, driver: Driver, comp: Compositor, timeline: list[Cue]) -> None:
        self.d = driver
        self.c = comp
        self.timeline = timeline
        self.total = timeline[-1].end
        self._state: dict[str, object] = {}
        self._shot = None
        self._shot_dirty = True

    # -- app frame cache ----------------------------------------------
    def shot(self):
        if self._shot_dirty or self._shot is None:
            self._shot = self.d.grab()
            self._shot_dirty = False
        return self._shot

    def touch(self) -> None:
        self._shot_dirty = True

    # -- main ----------------------------------------------------------
    def render_frame(self, t: float):
        from PySide6.QtGui import QPainter

        cue = self.timeline[-1]
        for candidate in self.timeline:
            if candidate.start <= t < candidate.end:
                cue = candidate
                break
        local = t - cue.start

        frame = self.c.new_frame()
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        getattr(self, f"scene_{cue.scene}")(painter, cue, local)

        # Global fade in / out.
        if t < 0.5 or t > self.total - 0.6:
            from PySide6.QtGui import QColor

            k = 1 - ease(t / 0.5) if t < 0.5 else ease((t - (self.total - 0.6)) / 0.6)
            painter.fillRect(0, 0, self.c.w, self.c.h, QColor(0, 0, 0, int(255 * k)))
        painter.end()
        return frame

    # -- window placement ---------------------------------------------
    def window_rect(self, scale: float = 1.0, dy: int = 0):
        from PySide6.QtCore import QRect

        if self.c.vertical:
            width = int(self.c.w * 0.93 * scale)
        else:
            width = int(self.c.w * 0.76 * scale)
        height = int(width * WINDOW_H / WINDOW_W)
        x = (self.c.w - width) // 2
        y = int(self.c.h * (0.43 if self.c.vertical else 0.415)) - height // 2 + dy
        return QRect(x, y, width, height)

    def draw_app(self, painter, cue: Cue, local: float, scale: float = 1.0,
                 crop=None, dy: int = 0, title_alpha: float | None = None) -> None:
        shot = self.shot()
        if crop is not None:
            shot = shot.copy(crop)
        # A hair of drift keeps a static screenshot from looking like a still.
        drift = 1.0 + 0.012 * (local / max(0.5, cue.duration))
        rect = self.window_rect(scale * drift, dy)
        self.c.draw_window(painter, shot, rect)
        if self.c.vertical:
            self.c.draw_wordmark(painter)
        alpha = title_alpha
        if alpha is None:
            alpha = min(ease(local / 0.5), ease((cue.duration - local) / 0.5))
        self.c.draw_title(painter, cue.title, cue.subtitle, alpha)
        self.c.draw_watermark(painter)

    # ------------------------------------------------------------------
    def scene_cold_open(self, painter, cue: Cue, local: float) -> None:
        """A dark terminal, retyping the same commands. The problem statement."""
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor

        lines = [
            "> AT+GMR", "> AT+CWLAP", "> MOTOR ON", "> AT+TEMP?",
            "> AT+GMR", "> AT+STATUS", "> MOTOR OFF", "> AT+CWLAP",
            "> AT+TEMP?", "> AT+GMR", "> MOTOR ON", "> AT+STATUS",
        ]
        mono = self.c.font(44 if not self.c.vertical else 40, "Bold", "DejaVu Sans Mono")
        painter.setFont(mono)

        # Type progressively faster: 12 lines in the available time.
        progress = min(1.0, local / max(0.1, cue.duration - 1.0))
        shown = progress ** 1.7 * len(lines)
        first = max(0, int(shown) - 7)
        y = self.c.h * (0.30 if not self.c.vertical else 0.26)
        left = self.c.w / 2 - (self.c.w * 0.16)

        for index in range(first, min(len(lines), int(shown) + 1)):
            fade = 1.0
            if index == int(shown):
                partial = shown - index
                text = lines[index][: max(1, int(len(lines[index]) * min(1.0, partial * 1.6)))]
                if int(local * 3) % 2 == 0:
                    text += "_"
            else:
                text = lines[index]
                fade = 0.30 + 0.55 * ((index - first) / 7.0)
            painter.setPen(QColor(147, 161, 181, int(255 * fade)))
            painter.drawText(
                QRectF(left, y, self.c.w, 58),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )
            y += 56

        alpha = ease((local - 1.6) / 0.8) * min(1.0, ease((cue.duration - local) / 0.6))
        self.c.draw_title(painter, cue.title, cue.subtitle, alpha)
        self.c.draw_watermark(painter, 0.6)

    # ------------------------------------------------------------------
    def scene_logo(self, painter, cue: Cue, local: float) -> None:
        """Brand card, then the real window rises into place."""
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QImage

        hold = 2.5
        if local >= hold:
            reveal = ease(min(1.0, (local - hold) / 0.9))
            if "logo_connect" not in self._state:
                self.d.set_connected(True)
                self.d.feed("[boot] ESP32 rev1, 4MB flash\n"
                            "[wifi] connected \u00b7 192.168.4.27\nOK\n")
                self.d.counters("1.2 kB/s")
                self._state["logo_connect"] = True
                self.touch()
            painter.setOpacity(reveal)
            self.draw_app(
                painter, cue, local, scale=0.94 + 0.06 * reveal,
                dy=int(70 * (1 - reveal)), title_alpha=reveal,
            )
            painter.setOpacity(1.0)
            return

        icon_path = REPO_ROOT / "resources" / "icons" / "app.png"
        if "icon" not in self._state:
            self._state["icon"] = QImage(str(icon_path))
        icon: QImage = self._state["icon"]  # type: ignore[assignment]

        k = ease_out(min(1.0, local / 0.9))
        size = int((self.c.w * (0.13 if not self.c.vertical else 0.30)) * (0.86 + 0.14 * k))
        cx, cy = self.c.w // 2, int(self.c.h * (0.40 if not self.c.vertical else 0.36))
        rect = QRectF(cx - size / 2, cy - size / 2, size, size)
        painter.setOpacity(k)
        painter.drawImage(rect, icon)
        painter.setOpacity(1.0)

        name_alpha = ease((local - 0.55) / 0.7)
        painter.setFont(self.c.font(64 if not self.c.vertical else 56, "Black", "DejaVu Sans"))
        painter.setPen(QColor(232, 237, 245, int(255 * name_alpha)))
        painter.drawText(
            QRectF(0, cy + size * 0.62, self.c.w, 80),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            "ENF Serial Command Console",
        )
        painter.setFont(self.c.font(34, "Medium"))
        painter.setPen(QColor(74, 158, 255, int(255 * name_alpha)))
        painter.drawText(
            QRectF(0, cy + size * 0.62 + 74, self.c.w, 56),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            cue.title,
        )
        self.c.draw_watermark(painter, 0.6)

    # ------------------------------------------------------------------
    def scene_buttons(self, painter, cue: Cue, local: float) -> None:
        """The differentiator: configurable one-click command buttons."""
        d = self.d
        beat = local / cue.duration

        if "buttons_init" not in self._state:
            if "logo_connect" not in self._state:   # standalone preview of this scene
                d.set_connected(True)
                d.feed("[boot] ESP32 rev1, 4MB flash\n[wifi] connected · 192.168.4.27\nOK\n")
                d.counters("1.2 kB/s")
            self._state["buttons_init"] = True
            self._state["clicks"] = 0
            self.touch()

        # Three clicks, evenly spaced through the segment.
        schedule = [(0.20, 0, "AT+TEMP?", "+TEMP: 24.8 C\nOK\n"),
                    (0.42, 2, "AT+STATUS", "+STATUS: READY  vref=3.301V  rssi=-58dBm\nOK\n"),
                    (0.62, 4, "MOTOR ON", "MOTOR: running  rpm=1450\nOK\n")]
        done = int(self._state["clicks"])  # type: ignore[arg-type]
        for index, (at, button, sent, reply) in enumerate(schedule):
            if beat >= at and done <= index:
                d.flash(button)
                d.send(sent)
                d.feed(reply)
                d.counters(f"{1.2 + index * 0.7:.1f} kB/s")
                self._state["clicks"] = index + 1
                self.touch()

        # Slow push-in towards the command panel.
        scale = 1.0 + 0.05 * ease(min(1.0, local / cue.duration))
        self.draw_app(painter, cue, local, scale=scale)

    # ------------------------------------------------------------------
    def scene_profiles(self, painter, cue: Cue, local: float) -> None:
        d = self.d
        if local > 0.8 and "profile_switched" not in self._state:
            d.switch_profile(
                "STM32",
                [("Read ADC", "adc read 0"), ("Set PWM", "pwm 1 128"),
                 ("Sys Info", "sys info"), ("Flash ID", "flash id"),
                 ("Reset", "sys reset"), ("Uptime", "sys uptime")],
            )
            d.feed("[profile] STM32 loaded — 6 commands\n")
            self._state["profile_switched"] = True
            self.touch()
        if local > 2.2 and "profile_demo" not in self._state:
            d.flash(0)
            d.send("adc read 0")
            d.feed("ADC0: 2048  (1.65 V)\n")
            self._state["profile_demo"] = True
            self.touch()
        if local > 3.6 and "profile_repeat" not in self._state:
            d.repeating(2, True)
            d.send("sys info")
            d.feed("STM32F407 @168MHz  flash 1M  ram 192K\n")
            self._state["profile_repeat"] = True
            self.touch()
        self.draw_app(painter, cue, local, scale=1.02)

    # ------------------------------------------------------------------
    def scene_flood(self, painter, cue: Cue, local: float) -> None:
        """High-rate stream: the UI stays smooth, counters climb."""
        d = self.d
        if "flood_init" not in self._state:
            d.repeating(2, False)
            self._state["flood_init"] = True
            self._state["flood_line"] = 0

        target = int((local / cue.duration) * 150)
        emitted = int(self._state.get("flood_line", 0))  # type: ignore[arg-type]
        if target > emitted:
            batch = []
            for i in range(emitted, target):
                batch.append(
                    f"[{i:05d}] imu ax={math.sin(i / 7):+.3f} ay={math.cos(i / 5):+.3f} "
                    f"az={math.sin(i / 3):+.3f} | mag={i % 360:03d}° | t={20 + i % 7}.{i % 10}C"
                )
            d.feed("\n".join(batch) + "\n")
            self._state["flood_line"] = target
            rate = 240 + int(local * 30)
            d.counters(f"{rate} kB/s")
            self.touch()
        self.draw_app(painter, cue, local, scale=1.0)

    # ------------------------------------------------------------------
    def scene_features(self, painter, cue: Cue, local: float) -> None:
        """Rapid-fire feature montage with rotating captions."""
        d = self.d
        slot = cue.duration / len(FEATURE_CAPTIONS)
        index = min(len(FEATURE_CAPTIONS) - 1, int(local / slot))
        key = f"feature_{index}"
        if key not in self._state:
            if index == 0:
                d.set_display_mode("both")
            elif index == 1:
                d.set_timestamps(True)
                d.feed("+GPS: 35.6892N 51.3890E  sats=11  hdop=0.8\n")
            elif index == 2:
                d.set_display_mode("ascii")
                d.feed("[log] 1.4 MB captured — exporting session.csv\n")
            elif index == 3:
                d.set_theme("light")
            elif index == 4:
                d.set_theme("dark")
                d.banner(
                    "COM7 was disconnected.",
                    "Reconnect the cable and press Connect (Ctrl+Enter) again.",
                )
            self._state[key] = True
            self.touch()

        title, subtitle = FEATURE_CAPTIONS[index]
        local_in_slot = local - index * slot
        alpha = min(ease(local_in_slot / 0.35), ease((slot - local_in_slot) / 0.35))
        self.draw_app(painter, cue, local, scale=1.0, title_alpha=0.0)
        self.c.draw_title(painter, title, subtitle, alpha)

    # ------------------------------------------------------------------
    def scene_endcard(self, painter, cue: Cue, local: float) -> None:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QImage

        d = self.d
        if "endcard_init" not in self._state:
            d.hide_banner()
            self._state["endcard_init"] = True
            self.touch()

        # The app slides down and dims as the card takes over.
        k = ease(min(1.0, local / 1.0))
        shot = self.shot()
        rect = self.window_rect(1.0 - 0.22 * k, dy=int(160 * k))
        painter.setOpacity(1.0 - 0.55 * k)
        self.c.draw_window(painter, shot, rect, shadow=False)
        painter.setOpacity(1.0)
        painter.fillRect(0, 0, self.c.w, self.c.h, QColor(9, 13, 20, int(232 * k)))

        icon = self._state.get("icon")
        if icon is None:
            icon = QImage(str(REPO_ROOT / "resources" / "icons" / "app.png"))
            self._state["icon"] = icon
        size = int(self.c.w * (0.115 if not self.c.vertical else 0.26))
        cy = int(self.c.h * (0.38 if not self.c.vertical else 0.34))
        painter.setOpacity(k)
        painter.drawImage(QRectF(self.c.w / 2 - size / 2, cy - size / 2, size, size), icon)

        painter.setFont(self.c.font(62 if not self.c.vertical else 54, "Black", "DejaVu Sans"))
        painter.setPen(QColor(232, 237, 245, int(255 * k)))
        painter.drawText(
            QRectF(0, cy + size * 0.62, self.c.w, 78),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            "ENF Serial Command Console",
        )
        painter.setFont(self.c.font(46 if not self.c.vertical else 44, "Black"))
        painter.setPen(QColor(74, 158, 255, int(255 * k)))
        painter.drawText(
            QRectF(0, cy + size * 0.62 + 82, self.c.w, 64),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            cue.title,
        )
        painter.setFont(self.c.font(32, "Medium", "DejaVu Sans"))
        painter.setPen(QColor(147, 161, 181, int(240 * k)))
        painter.drawText(
            QRectF(0, cy + size * 0.62 + 152, self.c.w, 52),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            cue.subtitle,
        )
        painter.setOpacity(1.0)
        self.c.draw_watermark(painter, k)


# ======================================================================
def vo_layout(vo_dir: Path, gap: float, lead_in: float, tempo: float):
    """Where each narration line lands on the timeline: {id: (start, end)}.

    Mirrors ``scripts/promo/build_narration.py`` so picture and voice agree.
    """
    import wave

    order = ["01", "02", "03", "04", "05", "06", "08"]
    offsets: dict[str, tuple[float, float]] = {}
    cursor = lead_in
    for name in order:
        with wave.open(str(vo_dir / f"{name}.wav"), "rb") as handle:
            length = handle.getnframes() / float(handle.getframerate()) / tempo
        offsets[name] = (cursor, cursor + length)
        cursor += length + gap
    return offsets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aspect", choices=("16x9", "9x16"), default="16x9")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--vo", type=Path, default=Path("/tmp/vo"))
    parser.add_argument("--audio", type=Path, default=Path("/tmp/vo/mix.wav"))
    parser.add_argument("--tempo", type=float, default=1.10)
    parser.add_argument("--gap", type=float, default=0.28)
    parser.add_argument("--lead-in", type=float, default=1.15)
    parser.add_argument("--preview", type=float, default=None,
                        help="render a single frame at this timestamp to --out (png)")
    args = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("SERIAL_CONSOLE_HOME", "/tmp/promo-home")

    from PySide6.QtWidgets import QApplication

    from serial_console.ui.theme import apply_theme
    from serial_console.models.enums import Theme

    app = QApplication(sys.argv[:1])
    apply_theme(app, Theme.DARK)

    width, height = (1920, 1080) if args.aspect == "16x9" else (1080, 1920)
    if args.aspect == "9x16":
        global WINDOW_W, WINDOW_H
        WINDOW_W, WINDOW_H = WINDOW_PORTRAIT
    offsets = vo_layout(args.vo, args.gap, args.lead_in, args.tempo)
    timeline = build_timeline(offsets)

    driver = Driver()
    comp = Compositor(width, height, vertical=args.aspect == "9x16")
    renderer = Renderer(driver, comp, timeline)

    if args.preview is not None:
        frame = renderer.render_frame(args.preview)
        frame.save(str(args.out))
        print(f"preview {args.preview:.2f}s -> {args.out}")
        return 0

    total_frames = int(renderer.total * FPS)
    ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
        "-r", str(FPS), "-i", "-",
    ]
    if args.audio.exists():
        cmd += ["-i", str(args.audio)]
    cmd += [
        "-map", "0:v", *(["-map", "1:a"] if args.audio.exists() else []),
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
        "-movflags", "+faststart", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(args.out),
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None

    for index in range(total_frames):
        frame = renderer.render_frame(index / FPS)
        proc.stdin.write(frame.constBits().tobytes())
        if index % 60 == 0:
            print(f"  {index / FPS:5.1f}s / {renderer.total:.1f}s", flush=True)
    proc.stdin.close()
    code = proc.wait()
    print(f"wrote {args.out} ({total_frames} frames, {renderer.total:.1f}s) exit={code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
