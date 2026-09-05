"""Scrollable, reorderable grid of command buttons."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.commands import CommandStore
from ...core.logging_setup import get_logger
from .command_button import COMMAND_MIME, CommandButtonWidget

_log = get_logger(__name__)


class _ButtonGrid(QWidget):
    """Inner widget hosting the grid and handling drops."""

    dropRequested = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setHorizontalSpacing(8)
        self._layout.setVerticalSpacing(8)
        self._widgets: list[CommandButtonWidget] = []
        self._columns = 2
        self._indicator = QWidget(self)
        self._indicator.setObjectName("DropIndicator")
        self._indicator.setFixedWidth(3)
        self._indicator.hide()

    # ------------------------------------------------------------------
    @property
    def widgets(self) -> list[CommandButtonWidget]:
        return self._widgets

    def set_columns(self, columns: int) -> None:
        columns = max(1, int(columns))
        if columns == self._columns:
            return
        self._columns = columns
        self.relayout()

    @property
    def columns(self) -> int:
        return self._columns

    def set_widgets(self, widgets: list[CommandButtonWidget]) -> None:
        self._widgets = widgets
        self.relayout()

    def relayout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
        for index, widget in enumerate(self._widgets):
            widget.setParent(self)
            widget.show()
            self._layout.addWidget(widget, index // self._columns, index % self._columns)
        for column in range(self._columns):
            self._layout.setColumnStretch(column, 1)
        # Keep the last row from stretching vertically.
        self._layout.setRowStretch(self._layout.rowCount(), 1)

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(COMMAND_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if not event.mimeData().hasFormat(COMMAND_MIME):
            event.ignore()
            return
        index = self._insertion_index(event.position().toPoint())
        self._show_indicator(index)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._indicator.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._indicator.hide()
        data = event.mimeData().data(COMMAND_MIME)
        if not data:
            event.ignore()
            return
        button_id = bytes(data.data()).decode("ascii", errors="ignore")
        index = self._insertion_index(event.position().toPoint())
        event.acceptProposedAction()
        self.dropRequested.emit(button_id, index)

    def _insertion_index(self, position: QPoint) -> int:
        """Index the dragged button would occupy if dropped at ``position``."""
        if not self._widgets:
            return 0
        for index, widget in enumerate(self._widgets):
            geometry = widget.geometry()
            if position.y() < geometry.bottom():
                if position.x() < geometry.center().x():
                    return index
                if position.x() < geometry.right():
                    return index + 1
        return len(self._widgets)

    def _show_indicator(self, index: int) -> None:
        if not self._widgets:
            self._indicator.hide()
            return
        clamped = max(0, min(index, len(self._widgets)))
        if clamped >= len(self._widgets):
            reference = self._widgets[-1].geometry()
            x = reference.right() + 2
            y = reference.top()
            height = reference.height()
        else:
            reference = self._widgets[clamped].geometry()
            x = reference.left() - 5
            y = reference.top()
            height = reference.height()
        self._indicator.setGeometry(x, y, 3, height)
        self._indicator.raise_()
        self._indicator.show()


class CommandPanel(QWidget):
    """Command buttons plus their management toolbar."""

    sendRequested = Signal(str)
    editRequested = Signal(str)
    contextMenuRequestedFor = Signal(str, QPoint)
    addRequested = Signal()
    reorderRequested = Signal(str, int)
    columnsChanged = Signal(int)
    profileChangeRequested = Signal(str)
    manageProfilesRequested = Signal()
    stopAllAutoSendRequested = Signal()

    def __init__(self, store: CommandStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._store = store
        self._widgets: dict[str, CommandButtonWidget] = {}
        self._edit_mode = False
        self._suppress = False
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Commands")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("HintLabel")
        header.addWidget(self.count_label)
        outer.addLayout(header)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(6)
        profile_label = QLabel("Profile")
        profile_label.setObjectName("FieldLabel")
        profile_row.addWidget(profile_label)

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(120)
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.profile_combo.setToolTip("Active command profile")
        self.profile_combo.activated.connect(self._on_profile_activated)
        profile_row.addWidget(self.profile_combo, 1)

        self.manage_button = QToolButton()
        self.manage_button.setText("⚙")
        self.manage_button.setToolTip("Manage profiles — create, rename, duplicate, import, export")
        self.manage_button.clicked.connect(self.manageProfilesRequested.emit)
        profile_row.addWidget(self.manage_button)
        outer.addLayout(profile_row)

        tools = QHBoxLayout()
        tools.setSpacing(6)

        self.add_button = QPushButton("+  Add")
        self.add_button.setToolTip("Add a command button (Ctrl+N)")
        self.add_button.clicked.connect(self.addRequested.emit)
        tools.addWidget(self.add_button)

        self.edit_mode_button = QToolButton()
        self.edit_mode_button.setText("Edit mode")
        self.edit_mode_button.setCheckable(True)
        self.edit_mode_button.setToolTip(
            "While Edit mode is on, double-clicking a button opens its editor\n"
            "instead of relying on Ctrl+Click."
        )
        self.edit_mode_button.toggled.connect(self.set_edit_mode)
        tools.addWidget(self.edit_mode_button)

        tools.addStretch(1)

        columns_label = QLabel("Cols")
        columns_label.setObjectName("FieldLabel")
        tools.addWidget(columns_label)

        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(1, 8)
        self.columns_spin.setMinimumWidth(58)
        self.columns_spin.setValue(2)
        self.columns_spin.setToolTip("Number of columns in the command grid")
        self.columns_spin.valueChanged.connect(self._on_columns_changed)
        tools.addWidget(self.columns_spin)
        outer.addLayout(tools)

        self.stop_all_button = QPushButton("■  Stop all auto-send")
        self.stop_all_button.setObjectName("DangerButton")
        self.stop_all_button.setToolTip("Stop every running auto-repeat job")
        self.stop_all_button.clicked.connect(self.stopAllAutoSendRequested.emit)
        self.stop_all_button.hide()
        outer.addWidget(self.stop_all_button)

        separator = QFrame()
        separator.setObjectName("HSeparator")
        separator.setFixedHeight(1)
        outer.addWidget(separator)

        # Named scroll_area, not scroll: QWidget already has a scroll() method and
# shadowing it on the Python side is a trap waiting to be sprung.
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid = _ButtonGrid()
        self.grid.dropRequested.connect(self.reorderRequested.emit)
        self.scroll_area.setWidget(self.grid)
        outer.addWidget(self.scroll_area, 1)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------
    def set_store(self, store: CommandStore) -> None:
        self._store = store
        self.rebuild()

    def rebuild(self) -> None:
        """Recreate every button widget from the store."""
        for widget in self._widgets.values():
            widget.setParent(None)
            widget.deleteLater()
        self._widgets.clear()

        widgets: list[CommandButtonWidget] = []
        for model in self._store.buttons:
            widget = CommandButtonWidget(model)
            widget.set_edit_mode(self._edit_mode)
            widget.sendRequested.connect(self.sendRequested.emit)
            widget.editRequested.connect(self.editRequested.emit)
            widget.contextMenuRequestedFor.connect(self.contextMenuRequestedFor.emit)
            self._widgets[model.id] = widget
            widgets.append(widget)
        self.grid.set_widgets(widgets)
        self._update_count()

    def refresh_button(self, button_id: str) -> None:
        """Re-read one model after an edit."""
        widget = self._widgets.get(button_id)
        if widget is None:
            self.rebuild()
            return
        model = self._store.profile.find(button_id)
        if model is None:
            self.rebuild()
            return
        widget.set_model(model)
        self._update_count()

    def widget_for(self, button_id: str) -> CommandButtonWidget | None:
        return self._widgets.get(button_id)

    def __len__(self) -> int:
        return len(self._widgets)

    def flash(self, button_id: str) -> None:
        widget = self._widgets.get(button_id)
        if widget is not None:
            widget.flash()

    def set_repeating(self, button_id: str, repeating: bool) -> None:
        widget = self._widgets.get(button_id)
        if widget is not None:
            widget.set_repeating(repeating)

    def set_auto_send_active(self, count: int) -> None:
        self.stop_all_button.setVisible(count > 0)
        self.stop_all_button.setText(
            f"■  Stop auto-send ({count})" if count else "■  Stop all auto-send"
        )

    def scroll_to(self, button_id: str) -> None:
        widget = self._widgets.get(button_id)
        if widget is not None:
            self.scroll_area.ensureWidgetVisible(widget, 20, 20)

    # ------------------------------------------------------------------
    # Profiles / layout
    # ------------------------------------------------------------------
    def set_profiles(self, profiles: list[tuple[str, str]], active_id: str) -> None:
        """``profiles`` is a list of ``(id, name)`` pairs."""
        self._suppress = True
        try:
            self.profile_combo.clear()
            for profile_id, name in profiles:
                self.profile_combo.addItem(name, profile_id)
            index = self.profile_combo.findData(active_id)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        finally:
            self._suppress = False

    def set_columns(self, columns: int) -> None:
        self._suppress = True
        try:
            self.columns_spin.setValue(max(1, min(8, int(columns))))
        finally:
            self._suppress = False
        self.grid.set_columns(self.columns_spin.value())

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        if self.edit_mode_button.isChecked() != enabled:
            self.edit_mode_button.setChecked(enabled)
        for widget in self._widgets.values():
            widget.set_edit_mode(enabled)

    # ------------------------------------------------------------------
    def _on_columns_changed(self, value: int) -> None:
        self.grid.set_columns(value)
        if not self._suppress:
            self.columnsChanged.emit(value)

    def _on_profile_activated(self, index: int) -> None:
        if self._suppress:
            return
        profile_id = self.profile_combo.itemData(index)
        if profile_id:
            self.profileChangeRequested.emit(str(profile_id))

    def _update_count(self) -> None:
        total = len(self._store.buttons)
        configured = sum(1 for b in self._store.buttons if not b.is_blank())
        self.count_label.setText(f"{configured} configured / {total} buttons")
