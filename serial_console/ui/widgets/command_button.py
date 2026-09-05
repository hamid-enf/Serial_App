"""A single command button widget with drag support and visual feedback."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QDrag,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QPushButton, QSizePolicy, QWidget

from ...models.command import CommandButton

#: Mime type used for intra-application reordering.
COMMAND_MIME = "application/x-serial-console-command-id"

FLASH_MS = 220


class CommandButtonWidget(QPushButton):
    """Renders a :class:`CommandButton` as a two-line push button.

    Interaction model (see README for the reasoning):

    * **Click** — send immediately, with no delay.
    * **Right click** — context menu (edit, duplicate, delete, auto-send…).
    * **Ctrl+Click**, **double click on a blank button**, or double click while
      the panel is in Edit mode — open the editor.
    * **Drag** — reorder.
    """

    sendRequested = Signal(str)
    editRequested = Signal(str)
    contextMenuRequestedFor = Signal(str, QPoint)
    dragStarted = Signal(str)

    def __init__(self, model: CommandButton, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandButton")
        self._model = model
        self._edit_mode = False
        self._drag_origin: QPoint | None = None
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(lambda: self._set_flag("flash", False))

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(52)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.clicked.connect(self._on_clicked)
        self.setAcceptDrops(False)
        self.refresh()

    # ------------------------------------------------------------------
    @property
    def model(self) -> CommandButton:
        return self._model

    @property
    def button_id(self) -> str:
        return self._model.id

    def set_model(self, model: CommandButton) -> None:
        self._model = model
        self.refresh()

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if enabled else Qt.CursorShape.PointingHandCursor
        )

    def set_repeating(self, repeating: bool) -> None:
        self._set_flag("repeating", repeating)

    def flash(self) -> None:
        """Brief highlight confirming the command was queued."""
        self._set_flag("flash", True)
        self._flash_timer.start(FLASH_MS)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        model = self._model
        self.setEnabled(model.enabled)
        self._set_flag("blank", model.is_blank())
        tooltip_lines = [f"<b>{_escape(model.name)}</b>"]
        if model.command:
            payload = model.command if len(model.command) < 200 else model.command[:197] + "…"
            kind = "Hex" if model.hex_mode else "Text"
            tooltip_lines.append(f"<code>{_escape(payload)}</code> <i>({kind})</i>")
        else:
            tooltip_lines.append("<i>No command yet — Ctrl+Click or right-click to set one.</i>")
        if model.line_ending is not None:
            tooltip_lines.append(f"Line ending: {model.line_ending.label}")
        else:
            tooltip_lines.append("Line ending: global")
        if model.auto_send.enabled:
            tooltip_lines.append(f"Auto-send every {model.auto_send.interval_ms} ms")
        if model.description:
            tooltip_lines.append(f"<span>{_escape(model.description)}</span>")
        tooltip_lines.append(
            "<span style='color:#888;'>Click to send · Ctrl+Click to edit · drag to reorder</span>"
        )
        self.setToolTip("<br>".join(tooltip_lines))
        self.update()

    def _set_flag(self, name: str, value: bool) -> None:
        if self.property(name) == value:
            return
        self.setProperty(name, value)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(150, 54)

    def paintEvent(self, event: QPaintEvent) -> None:
        # Let the stylesheet paint the frame/background, then draw two lines of
        # text ourselves: a plain QPushButton cannot show a name and a subtitle.
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = self.rect().adjusted(11, 6, -11, -6)

        name_font = QFont(self.font())
        name_font.setBold(True)
        painter.setFont(name_font)
        pen = painter.pen()
        painter.setPen(self.palette().buttonText().color())
        metrics = QFontMetrics(name_font)
        name = metrics.elidedText(self._model.name, Qt.TextElideMode.ElideRight, rect.width())
        name_height = metrics.height()
        painter.drawText(
            rect.left(),
            rect.top(),
            rect.width(),
            name_height,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            name,
        )

        subtitle_font = QFont(self.font())
        subtitle_font.setPointSizeF(max(7.0, self.font().pointSizeF() - 1.5))
        painter.setFont(subtitle_font)
        color = pen.color()
        color.setAlpha(150)
        painter.setPen(color)
        sub_metrics = QFontMetrics(subtitle_font)
        subtitle = self._subtitle_text()
        subtitle = sub_metrics.elidedText(subtitle, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(
            rect.left(),
            rect.top() + name_height,
            rect.width(),
            sub_metrics.height(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            subtitle,
        )
        painter.end()

    def _subtitle_text(self) -> str:
        model = self._model
        if model.is_blank():
            return "not configured"
        text = model.command.replace("\n", "⏎").replace("\r", "")
        badges: list[str] = []
        if model.hex_mode:
            badges.append("HEX")
        if model.auto_send.enabled:
            badges.append(f"⟳ {model.auto_send.interval_ms} ms")
        if badges:
            return f"{text}   ·   {' · '.join(badges)}"
        return text

    # ------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------
    def _on_clicked(self) -> None:
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.editRequested.emit(self.button_id)
            return
        if self._model.is_blank():
            # An empty slot has nothing to send; opening the editor is the only
            # sensible interpretation of the click.
            self.editRequested.emit(self.button_id)
            return
        self.sendRequested.emit(self.button_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._drag_origin).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._start_drag()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and (
            self._edit_mode or self._model.is_blank()
        ):
            self.editRequested.emit(self.button_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _start_drag(self) -> None:
        self._drag_origin = None
        self.setDown(False)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(COMMAND_MIME, self.button_id.encode("ascii"))
        mime.setText(self._model.command)
        drag.setMimeData(mime)

        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        self.dragStarted.emit(self.button_id)
        drag.exec(Qt.DropAction.MoveAction)

    def _on_context_menu(self, position: QPoint) -> None:
        self.contextMenuRequestedFor.emit(self.button_id, self.mapToGlobal(position))


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
