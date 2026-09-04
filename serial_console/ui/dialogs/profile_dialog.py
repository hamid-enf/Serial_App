"""Profile management dialog: create, rename, duplicate, delete, import/export."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config.paths import profiles_dir
from ...core.logging_setup import get_logger
from ...core.profiles import ProfileManager
from ...models.errors import ValidationError

_log = get_logger(__name__)


class ProfileDialog(QDialog):
    """CRUD over the profile list.

    The dialog mutates the :class:`ProfileManager` directly; the caller saves
    the configuration and refreshes the UI once the dialog closes.
    """

    def __init__(self, manager: ProfileManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Profiles")
        self.setModal(True)
        self.setMinimumSize(520, 400)
        self._manager = manager
        self._changed = False
        self._build()
        self._reload()

    # ------------------------------------------------------------------
    @property
    def changed(self) -> bool:
        return self._changed

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        intro = QLabel(
            "A profile holds its own set of command buttons and its own send history. "
            "Export a profile to share a command set with a colleague."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(10)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._update_buttons)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_rename())
        body.addWidget(self.list_widget, 1)

        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        self.new_button = self._add_button(buttons, "New…", self._on_new)
        self.rename_button = self._add_button(buttons, "Rename…", self._on_rename)
        self.duplicate_button = self._add_button(buttons, "Duplicate", self._on_duplicate)
        self.delete_button = self._add_button(buttons, "Delete", self._on_delete)
        self.delete_button.setObjectName("DangerButton")
        buttons.addSpacing(10)
        self.import_button = self._add_button(buttons, "Import…", self._on_import)
        self.export_button = self._add_button(buttons, "Export…", self._on_export)
        buttons.addStretch(1)
        self.activate_button = self._add_button(buttons, "Set Active", self._on_activate)
        self.activate_button.setObjectName("PrimaryButton")
        body.addLayout(buttons)

        outer.addLayout(body, 1)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("HintLabel")
        outer.addWidget(self.detail_label)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.accept)
        box.accepted.connect(self.accept)
        outer.addWidget(box)

    @staticmethod
    def _add_button(layout: QVBoxLayout, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    # ------------------------------------------------------------------
    def _reload(self, select_id: str | None = None) -> None:
        target = select_id or self._current_id() or self._manager.config.active_profile_id
        self.list_widget.clear()
        for profile in self._manager.profiles:
            configured = sum(1 for b in profile.buttons if not b.is_blank())
            suffix = "  (active)" if profile.id == self._manager.config.active_profile_id else ""
            item = QListWidgetItem(
                f"{profile.name}{suffix}\n{configured} configured / {len(profile.buttons)} buttons"
            )
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.list_widget.addItem(item)
            if profile.id == target:
                self.list_widget.setCurrentItem(item)
        if self.list_widget.currentRow() < 0 and self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self._update_buttons()

    def _current_id(self) -> str:
        item = self.list_widget.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _update_buttons(self, *_args: object) -> None:
        has_selection = bool(self._current_id())
        for button in (
            self.rename_button,
            self.duplicate_button,
            self.export_button,
            self.activate_button,
        ):
            button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection and len(self._manager) > 1)
        profile_id = self._current_id()
        if profile_id:
            try:
                profile = self._manager.get(profile_id)
            except ValidationError:
                self.detail_label.setText("")
                return
            self.detail_label.setText(profile.description or "No description.")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not ok:
            return
        count, ok = QInputDialog.getInt(
            self, "New Profile", "Number of command buttons:", 20, 0, 500, 5
        )
        if not ok:
            return
        try:
            profile = self._manager.create(name, button_count=count)
        except ValidationError as exc:
            self._warn(str(exc))
            return
        self._changed = True
        self._reload(profile.id)

    def _on_rename(self) -> None:
        profile_id = self._current_id()
        if not profile_id:
            return
        current = self._manager.get(profile_id)
        name, ok = QInputDialog.getText(
            self, "Rename Profile", "Profile name:", text=current.name
        )
        if not ok:
            return
        try:
            self._manager.rename(profile_id, name)
        except ValidationError as exc:
            self._warn(str(exc))
            return
        self._changed = True
        self._reload(profile_id)

    def _on_duplicate(self) -> None:
        profile_id = self._current_id()
        if not profile_id:
            return
        try:
            clone = self._manager.duplicate(profile_id)
        except ValidationError as exc:
            self._warn(str(exc))
            return
        self._changed = True
        self._reload(clone.id)

    def _on_delete(self) -> None:
        profile_id = self._current_id()
        if not profile_id:
            return
        profile = self._manager.get(profile_id)
        answer = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete “{profile.name}” and its {len(profile.buttons)} command buttons?\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._manager.delete(profile_id)
        except ValidationError as exc:
            self._warn(str(exc))
            return
        self._changed = True
        self._reload()

    def _on_activate(self) -> None:
        profile_id = self._current_id()
        if not profile_id:
            return
        self._manager.set_active(profile_id)
        self._changed = True
        self._reload(profile_id)

    def _on_export(self) -> None:
        profile_id = self._current_id()
        if not profile_id:
            return
        profile = self._manager.get(profile_id)
        suggested = profiles_dir() / f"{_safe_filename(profile.name)}.json"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export Profile", str(suggested), "Profile files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            self._manager.export_to_file(profile_id, path)
        except (OSError, ValidationError) as exc:
            _log.error("Profile export failed: %s", exc)
            self._warn(f"The profile could not be exported.\n\n{exc}")
            return
        QMessageBox.information(self, "Export Profile", f"Profile exported to:\n{path}")

    def _on_import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Import Profile",
            str(profiles_dir()),
            "Profile files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            profile = self._manager.import_from_file(path, activate=False)
        except ValidationError as exc:
            self._warn(str(exc))
            return
        self._changed = True
        self._reload(profile.id)

    # ------------------------------------------------------------------
    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Profiles", message)


def _safe_filename(name: str) -> str:
    keep = "-_ ()"
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in keep).strip()
    return cleaned or "profile"
