#!/usr/bin/env python3
"""Generate the ENF application icon (multi-resolution .ico plus a .png).

Run headlessly; no design tool required::

    QT_QPA_PLATFORM=offscreen python scripts/make_icon.py

Writes resources/icons/app.ico and resources/icons/app.png. The .ico embeds
PNG-compressed frames at 16-256 px; frames below 32 px drop the ENF wordmark
because at that size it degrades into a smudge.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIZES = [16, 24, 32, 48, 64, 128, 256]
WORDMARK_MIN_PX = 32


def render(size: int):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPen

    wordmark = size >= WORDMARK_MIN_PX
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    s = size / 256.0

    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, QColor("#232b36"))
    grad.setColorAt(1.0, QColor("#141920"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(4 * s, 4 * s, size - 8 * s, size - 8 * s), 46 * s, 46 * s)
    p.setPen(QPen(QColor("#39424e"), 3 * s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(4 * s, 4 * s, size - 8 * s, size - 8 * s), 46 * s, 46 * s)

    if wordmark:
        pen = QPen(QColor("#4a9eff"), 16 * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(
            [QPointF(84 * s, 62 * s), QPointF(128 * s, 100 * s), QPointF(84 * s, 138 * s)]
        )
        caret = QPen(QColor("#e3e8ef"), 16 * s)
        caret.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(caret)
        p.drawLine(QPointF(148 * s, 138 * s), QPointF(180 * s, 138 * s))

        font = QFont("DejaVu Sans")
        font.setPixelSize(max(1, int(58 * s)))
        font.setWeight(QFont.Weight.Black)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4 * s)
        p.setFont(font)
        p.setPen(QColor("#e3e8ef"))
        p.drawText(
            QRectF(0, 158 * s, size, 66 * s),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "ENF",
        )
    else:
        pen = QPen(QColor("#4a9eff"), 17 * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(
            [QPointF(72 * s, 88 * s), QPointF(122 * s, 130 * s), QPointF(72 * s, 172 * s)]
        )
        caret = QPen(QColor("#e3e8ef"), 17 * s)
        caret.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(caret)
        p.drawLine(QPointF(146 * s, 172 * s), QPointF(190 * s, 172 * s))
    p.end()
    return img


def png_bytes(img) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def main() -> int:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    QGuiApplication(sys.argv[:1])

    icons = REPO_ROOT / "resources" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    images = [render(size) for size in SIZES]
    images[-1].save(str(icons / "app.png"))

    # Hand-rolled ICO container: Qt's ICO writer is not present in every
    # build, and the format is a header plus one directory entry per frame.
    entries: list[bytes] = []
    blobs: list[bytes] = []
    offset = 6 + 16 * len(images)
    for size, img in zip(SIZES, images, strict=True):
        data = png_bytes(img)
        entries.append(
            struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        )
        blobs.append(data)
        offset += len(data)

    with open(icons / "app.ico", "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(images)))
        for entry in entries:
            fh.write(entry)
        for blob in blobs:
            fh.write(blob)

    print(f"wrote {icons / 'app.ico'} and {icons / 'app.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
