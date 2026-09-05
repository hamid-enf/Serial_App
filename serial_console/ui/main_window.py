"""The main application window: wiring, actions and the top-level layout."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, AUTHOR, COPYRIGHT, WEBSITE, __version__
from ..config.store import ConfigStore
from ..core.codec import build_payload
from ..core.commands import CommandStore
from ..core.errors import Severity, UserError, map_config_error
from ..core.history import CommandHistory
from ..core.logging_setup import get_logger
from ..core.profiles import ProfileManager
from ..core.stats import SessionStats, format_bytes
from ..core.terminal_buffer import TerminalBuffer
from ..models.command import CommandButton
from ..models.enums import Direction, LineEnding, Theme
from ..models.errors import ConfigError, ValidationError
from ..models.settings import AppConfig
from ..services.autosend import AutoSendScheduler
from ..services.serial_service import SerialService
from ..transport.base import Transport
from ._qt_compat import slot, warn
from .dialogs import CommandEditorDialog, LogViewerDialog, ProfileDialog, SettingsDialog
from .theme import apply_theme, theme_colors
from .widgets import CommandPanel, ConnectionBar, SendPanel, StatusBar, TerminalView

_log = get_logger(__name__)

BANNER_TIMEOUT_MS = 9000
STATS_INTERVAL_MS = 500
AUTOSAVE_INTERVAL_MS = 4000


class MainWindow(QMainWindow):
    """Owns the application state and connects every component together."""

    def __init__(
        self,
        config: AppConfig,
        store: ConfigStore,
        *,
        transport: Transport | None = None,
        startup_notice: str = "",
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setMinimumSize(1080, 680)

        self._config = config
        self._config_store = store
        self._profiles = ProfileManager(config)
        self._commands = CommandStore(self._profiles.active())
        self._history = CommandHistory(
            limit=config.commands.history_limit,
            entries=self._profiles.active().history,
        )
        self._buffer = TerminalBuffer(config.terminal.max_buffer_bytes)
        self._stats = SessionStats()

        self._service = SerialService(transport)
        self._autosend = AutoSendScheduler(self._send_button_payload, self)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._connect_signals()
        self._apply_config_to_ui()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(STATS_INTERVAL_MS)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._flush_config)

        self.connection_bar.refresh_ports()
        self.connection_bar.select_port(config.serial.port)
        self._append_info(
            f"{APP_NAME} {__version__} ready. Select a port and press Connect.\n"
        )
        if startup_notice:
            self._show_banner(
                UserError(message=startup_notice, severity=Severity.WARNING)
            )

    # ==================================================================
    # Construction
    # ==================================================================
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.connection_bar = ConnectionBar()
        layout.addWidget(self.connection_bar)

        self.banner = QLabel("")
        self.banner.setObjectName("BannerInfo")
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner.hide()
        banner_wrapper = QWidget()
        banner_layout = QVBoxLayout(banner_wrapper)
        banner_layout.setContentsMargins(10, 8, 10, 0)
        banner_layout.addWidget(self.banner)
        self._banner_wrapper = banner_wrapper
        banner_wrapper.hide()
        layout.addWidget(banner_wrapper)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 8)
        body_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(6)

        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_splitter.setChildrenCollapsible(False)
        self.left_splitter.setHandleWidth(6)

        self.terminal = TerminalView(self._buffer)
        self.left_splitter.addWidget(self.terminal)

        self.send_panel = SendPanel(self._history)
        self.left_splitter.addWidget(self.send_panel)
        self.left_splitter.setStretchFactor(0, 1)
        self.left_splitter.setStretchFactor(1, 0)
        self.left_splitter.setSizes([560, 150])

        self.main_splitter.addWidget(self.left_splitter)

        self.command_panel = CommandPanel(self._commands)
        self.main_splitter.addWidget(self.command_panel)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([760, 380])

        body_layout.addWidget(self.main_splitter)
        layout.addWidget(body, 1)

        self.setCentralWidget(central)

        self.status = StatusBar()
        self.setStatusBar(self.status)

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._hide_banner)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        self.action_save_log = QAction("Save Receive Log…", self)
        self.action_save_log.setShortcut(QKeySequence("Ctrl+S"))
        self.action_save_log.triggered.connect(self._on_save_log)
        file_menu.addAction(self.action_save_log)

        self.action_profiles = QAction("Profiles…", self)
        self.action_profiles.setShortcut(QKeySequence("Ctrl+P"))
        self.action_profiles.triggered.connect(self._on_manage_profiles)
        file_menu.addAction(self.action_profiles)

        file_menu.addSeparator()
        self.action_settings = QAction("Settings…", self)
        self.action_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.action_settings.triggered.connect(self._on_settings)
        file_menu.addAction(self.action_settings)

        file_menu.addSeparator()
        action_quit = QAction("Exit", self)
        action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        action_quit.triggered.connect(self.close)
        file_menu.addAction(action_quit)

        connection_menu = menubar.addMenu("&Connection")
        self.action_connect = QAction("Connect / Disconnect", self)
        self.action_connect.setShortcut(QKeySequence("Ctrl+Return"))
        self.action_connect.triggered.connect(self._toggle_connection)
        connection_menu.addAction(self.action_connect)

        self.action_refresh = QAction("Refresh Ports", self)
        self.action_refresh.setShortcut(QKeySequence("Ctrl+R"))
        self.action_refresh.triggered.connect(self._on_refresh_ports)
        connection_menu.addAction(self.action_refresh)

        connection_menu.addSeparator()
        self.action_reset_counters = QAction("Reset Counters", self)
        self.action_reset_counters.triggered.connect(self._on_reset_counters)
        connection_menu.addAction(self.action_reset_counters)

        view_menu = menubar.addMenu("&View")
        self.action_clear = QAction("Clear Receive", self)
        self.action_clear.setShortcut(QKeySequence("Ctrl+L"))
        self.action_clear.triggered.connect(self._on_clear_terminal)
        view_menu.addAction(self.action_clear)

        self.action_select_all = QAction("Select All (terminal)", self)
        self.action_select_all.setShortcut(QKeySequence("Ctrl+A"))
        self.action_select_all.triggered.connect(self.terminal.select_all)
        view_menu.addAction(self.action_select_all)

        self.action_copy = QAction("Copy Terminal", self)
        self.action_copy.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.action_copy.triggered.connect(self._on_copy_terminal)
        view_menu.addAction(self.action_copy)

        view_menu.addSeparator()
        self.action_toggle_theme = QAction("Toggle Dark / Light Theme", self)
        self.action_toggle_theme.setShortcut(QKeySequence("Ctrl+T"))
        self.action_toggle_theme.triggered.connect(self._toggle_theme)
        view_menu.addAction(self.action_toggle_theme)

        self.action_autoscroll = QAction("Auto Scroll", self)
        self.action_autoscroll.setCheckable(True)
        self.action_autoscroll.setChecked(True)
        self.action_autoscroll.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.action_autoscroll.toggled.connect(self.terminal.set_auto_scroll)
        view_menu.addAction(self.action_autoscroll)

        commands_menu = menubar.addMenu("Co&mmands")
        self.action_add_command = QAction("Add Command Button", self)
        self.action_add_command.setShortcut(QKeySequence("Ctrl+N"))
        self.action_add_command.triggered.connect(self._on_add_command)
        commands_menu.addAction(self.action_add_command)

        self.action_add_many = QAction("Add Multiple Buttons…", self)
        self.action_add_many.triggered.connect(self._on_add_many_commands)
        commands_menu.addAction(self.action_add_many)

        commands_menu.addSeparator()
        self.action_stop_autosend = QAction("Stop All Auto-Send", self)
        self.action_stop_autosend.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.action_stop_autosend.triggered.connect(self._on_stop_all_autosend)
        commands_menu.addAction(self.action_stop_autosend)

        help_menu = menubar.addMenu("&Help")
        self.action_log = QAction("Application Log…", self)
        self.action_log.triggered.connect(self._on_show_log)
        help_menu.addAction(self.action_log)

        self.action_shortcuts = QAction("Keyboard Shortcuts", self)
        self.action_shortcuts.setShortcut(QKeySequence("F1"))
        self.action_shortcuts.triggered.connect(self._on_show_shortcuts)
        help_menu.addAction(self.action_shortcuts)

        self.action_about = QAction("About", self)
        self.action_about.triggered.connect(self._on_about)
        help_menu.addAction(self.action_about)

    def _build_shortcuts(self) -> None:
        self.action_focus_input = QAction(self)
        self.action_focus_input.setShortcut(QKeySequence("Ctrl+K"))
        self.action_focus_input.triggered.connect(self._on_clear_input)
        self.addAction(self.action_focus_input)

    def _connect_signals(self) -> None:
        bar = self.connection_bar
        bar.connectRequested.connect(self._on_connect)
        bar.disconnectRequested.connect(self._on_disconnect)
        bar.refreshRequested.connect(self._on_refresh_ports)
        bar.settingsChanged.connect(self._on_connection_settings_changed)

        self.terminal.clearRequested.connect(self._on_clear_terminal)
        self.terminal.saveRequested.connect(self._on_save_log)
        self.terminal.displaySettingsChanged.connect(self._on_terminal_display_changed)

        self.send_panel.sendRequested.connect(self._on_manual_send)
        self.send_panel.lineEndingChanged.connect(self._on_line_ending_changed)

        panel = self.command_panel
        panel.sendRequested.connect(self._on_command_button_send)
        panel.editRequested.connect(self._on_edit_command)
        panel.contextMenuRequestedFor.connect(self._on_command_context_menu)
        panel.addRequested.connect(self._on_add_command)
        panel.reorderRequested.connect(self._on_reorder_command)
        panel.columnsChanged.connect(self._on_columns_changed)
        panel.profileChangeRequested.connect(self._on_profile_changed)
        panel.manageProfilesRequested.connect(self._on_manage_profiles)
        panel.stopAllAutoSendRequested.connect(self._on_stop_all_autosend)

        self.status.resetCountersRequested.connect(self._on_reset_counters)

        service = self._service
        service.connected.connect(self._on_serial_connected)
        service.disconnected.connect(self._on_serial_disconnected)
        service.errorRaised.connect(self._on_serial_error)
        service.dataReceived.connect(self._on_data_received)
        service.dataSent.connect(self._on_data_sent)
        service.overflowed.connect(self._on_overflow)

        self._autosend.activeCountChanged.connect(self.command_panel.set_auto_send_active)
        self._autosend.jobStarted.connect(
            lambda button_id, _interval: self.command_panel.set_repeating(button_id, True)
        )
        self._autosend.jobStopped.connect(
            lambda button_id: self.command_panel.set_repeating(button_id, False)
        )
        self._autosend.tick.connect(self.command_panel.flash)

    # ==================================================================
    # Configuration <-> UI
    # ==================================================================
    def _apply_config_to_ui(self) -> None:
        config = self._config
        self.connection_bar.apply_settings(config.serial)
        self.terminal.apply_settings(config.terminal, config.appearance.theme)
        self.terminal.apply_font(
            config.appearance.font_family,
            config.appearance.font_size,
            config.appearance.line_spacing,
        )
        self.send_panel.set_line_ending(config.terminal.line_ending)
        self.send_panel.input.setFont(
            self.terminal.output.font()
        )
        self.command_panel.set_columns(config.appearance.command_button_columns)
        self.command_panel.set_store(self._commands)
        self._refresh_profile_combo()
        self.action_autoscroll.setChecked(config.terminal.auto_scroll)
        self._buffer.set_max_bytes(config.terminal.max_buffer_bytes)
        self._history.set_limit(config.commands.history_limit)
        self.send_panel.refresh_history()
        self._restore_geometry()

    def _restore_geometry(self) -> None:
        geometry = self._config.appearance.window_geometry
        state = self._config.appearance.window_state
        try:
            if geometry:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            if state:
                self.restoreState(QByteArray.fromBase64(state.encode("ascii")))
        except (ValueError, TypeError):
            _log.debug("Stored window geometry could not be restored")

    def _store_geometry(self) -> None:
        try:
            self._config.appearance.window_geometry = bytes(
                self.saveGeometry().toBase64().data()
            ).decode("ascii")
            self._config.appearance.window_state = bytes(
                self.saveState().toBase64().data()
            ).decode("ascii")
        except (ValueError, TypeError):  # pragma: no cover - defensive
            _log.debug("Window geometry could not be stored")

    # ------------------------------------------------------------------
    # Public façade
    #
    # The window owns the long-lived objects; exposing them read-only keeps
    # tests and helper scripts (scripts/screenshot.py) off the private
    # attributes without letting anything swap them out underneath us.
    # ------------------------------------------------------------------
    @property
    def service(self) -> SerialService:
        return self._service

    @property
    def profiles(self) -> ProfileManager:
        return self._profiles

    @property
    def commands(self) -> CommandStore:
        return self._commands

    @property
    def history(self) -> CommandHistory:
        return self._history

    @property
    def buffer(self) -> TerminalBuffer:
        return self._buffer

    @property
    def stats(self) -> SessionStats:
        return self._stats

    @property
    def config(self) -> AppConfig:
        return self._config

    def send_manual(self, text: str, hex_mode: bool, line_ending: LineEnding) -> None:
        """Send as if the user had typed into the input box and pressed Enter."""
        self._on_manual_send(text, hex_mode, line_ending)

    def send_command(self, button: CommandButton) -> bool:
        """Send a command button's payload. Returns False if it was rejected."""
        return self._send_button_payload(button)

    def _mark_dirty(self) -> None:
        """Flag the configuration and debounce the write to disk."""
        self._config_store.mark_dirty()
        self._autosave_timer.start()

    def _flush_config(self) -> None:
        self._sync_runtime_state_into_config()
        try:
            self._config_store.save_if_dirty(self._config)
        except ConfigError as exc:
            _log.error("Autosave failed: %s", exc)
            self._show_banner(map_config_error(exc, str(self._config_store.path)))

    def _sync_runtime_state_into_config(self) -> None:
        self._profiles.active().history = self._history.entries()
        self._config.serial.port = (
            self.connection_bar.selected_port() or self._config.serial.port
        )
        settings = self.connection_bar.to_settings(self._config.serial)
        self._config.serial = settings
        self._config.terminal.auto_scroll = self.terminal.auto_scroll
        self._config.terminal.display_mode = self.terminal.display_mode
        self._config.terminal.show_timestamp = self.terminal.show_timestamp
        self._config.terminal.line_ending = self.send_panel.line_ending()
        self._config.appearance.command_button_columns = self.command_panel.grid.columns

    # ==================================================================
    # Connection
    # ==================================================================
    @slot()
    def _on_connect(self) -> None:
        settings = self.connection_bar.to_settings(self._config.serial)
        try:
            settings.validate()
        except ValidationError as exc:
            self._show_banner(
                UserError(
                    message=str(exc),
                    hint="Press Refresh (Ctrl+R) if the device was just plugged in.",
                    severity=Severity.WARNING,
                )
            )
            return
        self._config.serial = settings
        self._mark_dirty()
        self._append_info(f"Opening {settings.describe()} …\n")
        self._service.connect_port(settings)

    @slot()
    def _on_disconnect(self) -> None:
        self._autosend.stop_all()
        self._service.disconnect_port()

    @slot()
    def _toggle_connection(self) -> None:
        if self._service.is_connected:
            self._on_disconnect()
        else:
            self._on_connect()

    @slot()
    def _on_refresh_ports(self) -> None:
        if self._service.is_connected:
            self.status.set_message("Disconnect before re-scanning ports.")
            return
        ports = self.connection_bar.refresh_ports()
        self.status.set_message(
            f"{len(ports)} port{'s' if len(ports) != 1 else ''} found."
            if ports
            else "No serial ports found."
        )

    @slot(object)
    def _on_serial_connected(self, settings) -> None:
        colors = theme_colors(self._config.appearance.theme)
        self.connection_bar.set_connected(True, settings.describe(), colors["connected"])
        self.status.set_connection(
            True, settings.port, settings.baud_rate, colors["connected"]
        )
        self._append_info(f"Connected to {settings.describe()}\n")
        self.status.set_message("Connected.")
        self.send_panel.focus_input()

    @slot(str)
    def _on_serial_disconnected(self, reason: str) -> None:
        colors = theme_colors(self._config.appearance.theme)
        self._autosend.stop_all()
        self.connection_bar.set_connected(False, "", colors["disconnected"])
        self.status.set_connection(False, "", 0, colors["disconnected"])
        readable = {
            "user": "Disconnected.",
            "read-error": "Disconnected after a read error.",
            "write-error": "Disconnected after a write error.",
        }.get(reason, "Disconnected.")
        self._append_info(f"{readable}\n")
        self.status.set_message(readable)

    @slot(object)
    def _on_serial_error(self, error: UserError) -> None:
        self._show_banner(error)
        self._append_error(f"{error.full_text()}\n")

    # ==================================================================
    # Data flow
    # ==================================================================
    @slot(bytes)
    def _on_data_received(self, data: bytes) -> None:
        self._stats.add_rx(len(data))
        chunks = self._buffer.append(Direction.RX, data)
        self.terminal.append_chunks(chunks)
        # Let the display decide how often it wants to be fed. On a fast
        # machine at a modest baud rate this stays at 30 fps; when frames get
        # expensive the service hands over larger batches less often instead
        # of letting the text widget eat the event loop.
        self._service.set_display_interval_ms(self.terminal.suggested_refresh_ms())

    @slot(bytes)
    def _on_data_sent(self, data: bytes) -> None:
        self._stats.add_tx(len(data))
        if self._config.terminal.echo_tx:
            chunks = self._buffer.append(Direction.TX, data)
            self.terminal.append_chunks(chunks)

    @slot(int)
    def _on_overflow(self, dropped: int) -> None:
        self._stats.add_dropped(dropped)
        self._append_error(
            f"[{format_bytes(dropped)} of incoming data was dropped: the display "
            "could not keep up]\n"
        )

    def _append_info(self, text: str) -> None:
        chunks = self._buffer.append_text(Direction.INFO, text)
        self.terminal.append_chunks(chunks)

    def _append_error(self, text: str) -> None:
        chunks = self._buffer.append_text(Direction.ERROR, text)
        self.terminal.append_chunks(chunks)

    # ==================================================================
    # Sending
    # ==================================================================
    @slot(str, bool, object)
    def _on_manual_send(self, text: str, hex_mode: bool, line_ending: LineEnding) -> None:
        try:
            payload = build_payload(
                text,
                hex_mode=hex_mode,
                line_ending=line_ending,
                encoding=self._config.terminal.encoding,
            )
        except ValidationError as exc:
            self.send_panel.show_error(str(exc))
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
            return
        self.send_panel.show_error("")
        if not self._service.send(payload):
            return
        self._history.add(text)
        self.send_panel.refresh_history()
        self.send_panel.input.clear()
        self._mark_dirty()

    def _send_button_payload(self, button: CommandButton) -> bool:
        """Build and queue the payload for a command button."""
        if button.is_blank():
            # Guard before building: with a global LF the payload would be a
            # bare newline, so an unconfigured button would silently poke the
            # device instead of telling the user it needs setting up.
            self._show_banner(
                UserError(
                    message=f"“{button.name}” has no command to send.",
                    hint="Ctrl+Click the button to define one.",
                    severity=Severity.WARNING,
                )
            )
            return False
        ending = button.resolved_line_ending(self.send_panel.line_ending())
        try:
            payload = build_payload(
                button.command,
                hex_mode=button.hex_mode,
                line_ending=ending,
                encoding=self._config.terminal.encoding,
            )
        except ValidationError as exc:
            self._show_banner(
                UserError(
                    message=f"“{button.name}” could not be sent: {exc}",
                    hint="Open the button editor and correct the hex payload.",
                    severity=Severity.WARNING,
                )
            )
            return False
        if not payload:
            self._show_banner(
                UserError(
                    message=f"“{button.name}” produces no bytes to send.",
                    hint="Check the command and the line ending.",
                    severity=Severity.WARNING,
                )
            )
            return False
        return self._service.send(payload)

    @slot(str)
    def _on_command_button_send(self, button_id: str) -> None:
        try:
            button = self._commands.get(button_id)
        except ValidationError:
            self.command_panel.rebuild()
            return
        if self._send_button_payload(button):
            if self._config.commands.flash_on_send:
                self.command_panel.flash(button_id)
            self._history.add(button.command)
            self.send_panel.refresh_history()
            self._mark_dirty()

    # ==================================================================
    # Command button management
    # ==================================================================
    @slot()
    def _on_add_command(self) -> None:
        try:
            button = self._commands.add()
        except ValidationError as exc:
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
            return
        self.command_panel.rebuild()
        self.command_panel.scroll_to(button.id)
        self._mark_dirty()
        self._on_edit_command(button.id)

    @slot()
    def _on_add_many_commands(self) -> None:
        count, ok = QInputDialog.getInt(
            self, "Add Command Buttons", "How many buttons should be added?", 10, 1, 200, 1
        )
        if not ok:
            return
        try:
            self._commands.add_many(count)
        except ValidationError as exc:
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
        self.command_panel.rebuild()
        self._mark_dirty()

    @slot(str)
    def _on_edit_command(self, button_id: str) -> None:
        try:
            button = self._commands.get(button_id)
        except ValidationError:
            self.command_panel.rebuild()
            return
        dialog = CommandEditorDialog(button, self.send_panel.line_ending(), self)
        if dialog.exec() != CommandEditorDialog.DialogCode.Accepted:
            return
        updated = dialog.result_button()
        try:
            self._commands.update(button_id, updated)
        except ValidationError as exc:
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
            return
        self.command_panel.refresh_button(button_id)
        self._sync_autosend(updated)
        self._mark_dirty()

    def _sync_autosend(self, button: CommandButton) -> None:
        """Reconcile a running repeat job with the edited button."""
        if self._autosend.is_running(button.id):
            self._autosend.update_button(button)

    @slot(str, QPoint)
    def _on_command_context_menu(self, button_id: str, global_pos: QPoint) -> None:
        try:
            button = self._commands.get(button_id)
        except ValidationError:
            self.command_panel.rebuild()
            return

        menu = QMenu(self)
        send_action = menu.addAction("Send")
        send_action.setEnabled(button.enabled and not button.is_blank())
        menu.addSeparator()
        edit_action = menu.addAction("Edit…")
        rename_action = menu.addAction("Rename…")
        duplicate_action = menu.addAction("Duplicate")
        menu.addSeparator()

        repeating = self._autosend.is_running(button_id)
        auto_action = menu.addAction("Stop auto-send" if repeating else "Start auto-send")
        auto_action.setEnabled(not button.is_blank())

        enable_action = menu.addAction("Disable" if button.enabled else "Enable")
        menu.addSeparator()

        move_menu = menu.addMenu("Move")
        move_first = move_menu.addAction("To first")
        move_up = move_menu.addAction("Up")
        move_down = move_menu.addAction("Down")
        move_last = move_menu.addAction("To last")

        menu.addSeparator()
        reset_action = menu.addAction("Reset")
        delete_action = menu.addAction("Delete")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return

        try:
            if chosen is send_action:
                self._on_command_button_send(button_id)
                return
            if chosen is edit_action:
                self._on_edit_command(button_id)
                return
            if chosen is rename_action:
                self._rename_command(button_id)
                return
            if chosen is duplicate_action:
                clone = self._commands.duplicate(button_id)
                self.command_panel.rebuild()
                self.command_panel.scroll_to(clone.id)
            elif chosen is auto_action:
                self._toggle_autosend(button_id)
                return
            elif chosen is enable_action:
                self._commands.set_enabled(button_id, not button.enabled)
                if not button.enabled:
                    self._autosend.stop(button_id)
                self.command_panel.refresh_button(button_id)
            elif chosen is move_first:
                self._commands.move(button_id, 0)
                self.command_panel.rebuild()
            elif chosen is move_up:
                self._commands.move_by(button_id, -1)
                self.command_panel.rebuild()
            elif chosen is move_down:
                self._commands.move_by(button_id, 1)
                self.command_panel.rebuild()
            elif chosen is move_last:
                self._commands.move(button_id, len(self._commands))
                self.command_panel.rebuild()
            elif chosen is reset_action:
                self._autosend.stop(button_id)
                self._commands.reset(button_id)
                self.command_panel.refresh_button(button_id)
            elif chosen is delete_action:
                self._delete_command(button_id, button.name)
                return
        except ValidationError as exc:
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
            return
        self._mark_dirty()

    def _rename_command(self, button_id: str) -> None:
        try:
            button = self._commands.get(button_id)
        except ValidationError:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Command Button", "Button name:", text=button.name
        )
        if not ok:
            return
        try:
            self._commands.rename(button_id, name)
        except ValidationError as exc:
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
            return
        self.command_panel.refresh_button(button_id)
        self._mark_dirty()

    def _delete_command(self, button_id: str, name: str) -> None:
        if self._config.commands.confirm_delete:
            answer = QMessageBox.question(
                self,
                "Delete Command Button",
                f"Delete “{name}”?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._autosend.stop(button_id)
        try:
            self._commands.remove(button_id)
        except ValidationError as exc:
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
            return
        self.command_panel.rebuild()
        self._mark_dirty()

    def _toggle_autosend(self, button_id: str) -> None:
        try:
            button = self._commands.get(button_id)
        except ValidationError:
            return
        if self._autosend.is_running(button_id):
            self._autosend.stop(button_id)
            return
        if not self._service.is_connected:
            self._show_banner(
                UserError(
                    message="Connect to a port before starting auto-send.",
                    severity=Severity.WARNING,
                )
            )
            return
        if not button.auto_send.enabled:
            # Starting from the menu implies enabling it on the model too.
            button.auto_send.enabled = True
            self.command_panel.refresh_button(button_id)
            self._mark_dirty()
        self._autosend.start(button)
        self._warn_if_autosend_saturates()

    def _warn_if_autosend_saturates(self) -> None:
        """Tell the user when the combined repeat rate outruns the link."""
        settings = self._service.settings
        if settings is None:
            return
        rate_hz = self._autosend.aggregate_rate_hz()
        if rate_hz <= 0:
            return
        # 10 bits per byte is the usual 8N1 framing approximation.
        bytes_per_second = settings.baud_rate / 10.0
        # Assume a conservative 32-byte average command.
        needed = rate_hz * 32
        if needed > bytes_per_second * 0.8:
            self._show_banner(
                UserError(
                    message=(
                        f"Auto-send is scheduled {rate_hz:.1f} times per second, which is "
                        "close to the capacity of this link."
                    ),
                    hint="Increase the interval or the baud rate to avoid a backlog.",
                    severity=Severity.WARNING,
                )
            )

    @slot()
    def _on_stop_all_autosend(self) -> None:
        self._autosend.stop_all()
        self.status.set_message("All auto-send jobs stopped.")

    @slot(str, int)
    def _on_reorder_command(self, button_id: str, target_index: int) -> None:
        try:
            current = self._commands.index_of(button_id)
        except ValidationError:
            self.command_panel.rebuild()
            return
        # The insertion index is computed against the list *including* the
        # dragged button, so shift when moving forward.
        if target_index > current:
            target_index -= 1
        if target_index == current:
            return
        self._commands.move(button_id, target_index)
        self.command_panel.rebuild()
        self.command_panel.scroll_to(button_id)
        self._mark_dirty()

    @slot(int)
    def _on_columns_changed(self, columns: int) -> None:
        self._config.appearance.command_button_columns = columns
        self._mark_dirty()

    # ==================================================================
    # Profiles
    # ==================================================================
    def _refresh_profile_combo(self) -> None:
        pairs = [(p.id, p.name) for p in self._profiles.profiles]
        self.command_panel.set_profiles(pairs, self._config.active_profile_id)

    @slot(str)
    def _on_profile_changed(self, profile_id: str) -> None:
        if profile_id == self._config.active_profile_id:
            return
        self._autosend.stop_all()
        self._profiles.active().history = self._history.entries()
        try:
            profile = self._profiles.set_active(profile_id)
        except ValidationError as exc:
            self._show_banner(UserError(message=str(exc), severity=Severity.WARNING))
            return
        self._commands.set_profile(profile)
        self._history = CommandHistory(
            limit=self._config.commands.history_limit, entries=profile.history
        )
        self.send_panel.set_history(self._history)
        self.command_panel.set_store(self._commands)
        self._refresh_profile_combo()
        self.status.set_message(f"Profile “{profile.name}” activated.")
        self._mark_dirty()

    @slot()
    def _on_manage_profiles(self) -> None:
        dialog = ProfileDialog(self._profiles, self)
        dialog.exec()
        if not dialog.changed:
            return
        active = self._profiles.active()
        if active.id != self._commands.profile.id:
            self._autosend.stop_all()
            self._commands.set_profile(active)
            self._history = CommandHistory(
                limit=self._config.commands.history_limit, entries=active.history
            )
            self.send_panel.set_history(self._history)
            self.command_panel.set_store(self._commands)
        else:
            self.command_panel.rebuild()
        self._refresh_profile_combo()
        self._mark_dirty()
        self._flush_config()

    # ==================================================================
    # Terminal actions
    # ==================================================================
    @slot()
    def _on_clear_terminal(self) -> None:
        self._buffer.clear()
        self.terminal.clear()
        self.status.set_message("Receive pane cleared.")

    @slot()
    def _on_clear_input(self) -> None:
        self.send_panel.clear_input()
        self.send_panel.focus_input()

    @slot()
    def _on_copy_terminal(self) -> None:
        count = self.terminal.copy_to_clipboard()
        self.status.set_message(f"{format_bytes(count)} copied to the clipboard.")

    @slot()
    def _on_terminal_display_changed(self) -> None:
        self._config.terminal.display_mode = self.terminal.display_mode
        self._config.terminal.show_timestamp = self.terminal.show_timestamp
        self._config.terminal.auto_scroll = self.terminal.auto_scroll
        self.action_autoscroll.blockSignals(True)
        self.action_autoscroll.setChecked(self.terminal.auto_scroll)
        self.action_autoscroll.blockSignals(False)
        self.terminal.apply_settings(self._config.terminal, self._config.appearance.theme)
        self._mark_dirty()

    @slot(object)
    def _on_line_ending_changed(self, ending: LineEnding) -> None:
        self._config.terminal.line_ending = ending
        self.status.set_message(f"Line ending set to {ending.label}.")
        self._mark_dirty()

    @slot()
    def _on_connection_settings_changed(self) -> None:
        self._mark_dirty()

    @slot()
    def _on_save_log(self) -> None:
        default_name = time.strftime("serial-log-%Y%m%d-%H%M%S")
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Receive Log",
            str(Path.home() / f"{default_name}.txt"),
            "Text files (*.txt);;CSV files (*.csv);;Raw binary (*.bin);;All files (*)",
        )
        if not path:
            return
        target = Path(path)
        try:
            if target.suffix.lower() == ".csv" or "CSV" in selected_filter:
                target.write_text(
                    self._buffer.to_csv(self._config.terminal.encoding), encoding="utf-8"
                )
            elif target.suffix.lower() == ".bin" or "binary" in selected_filter.lower():
                target.write_bytes(self._buffer.to_raw_bytes())
            else:
                target.write_text(
                    self._buffer.render(
                        display_mode=self._config.terminal.display_mode,
                        show_timestamp=self._config.terminal.show_timestamp,
                        encoding=self._config.terminal.encoding,
                        hex_bytes_per_line=self._config.terminal.hex_bytes_per_line,
                    ),
                    encoding="utf-8",
                )
        except OSError as exc:
            _log.error("Export failed: %s", exc)
            self._show_banner(
                UserError(
                    message="The receive log could not be saved.",
                    hint=f"{exc.strerror or exc}",
                    detail=str(exc),
                )
            )
            return
        self.status.set_message(f"Receive log saved to {target}.")

    # ==================================================================
    # Settings / appearance
    # ==================================================================
    @slot()
    def _on_settings(self) -> None:
        self._sync_runtime_state_into_config()
        dialog = SettingsDialog(self._config, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        new_config = dialog.config
        # Preserve live-only state that the dialog does not manage.
        new_config.profiles = self._config.profiles
        new_config.active_profile_id = self._config.active_profile_id
        new_config.serial.port = self._config.serial.port
        self._config = new_config
        self._profiles = ProfileManager(self._config)
        self._commands.set_profile(self._profiles.active())

        theme = self._config.appearance.theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        self.terminal.set_theme(theme)
        self.terminal.apply_settings(self._config.terminal, theme)
        self.terminal.apply_font(
            self._config.appearance.font_family,
            self._config.appearance.font_size,
            self._config.appearance.line_spacing,
        )
        self.send_panel.input.setFont(self.terminal.output.font())
        self.send_panel.set_line_ending(self._config.terminal.line_ending)
        self.command_panel.set_columns(self._config.appearance.command_button_columns)
        self._buffer.set_max_bytes(self._config.terminal.max_buffer_bytes)
        self._history.set_limit(self._config.commands.history_limit)
        self.send_panel.refresh_history()
        self._mark_dirty()
        self._flush_config()
        self.status.set_message("Settings applied.")

    @slot()
    def _toggle_theme(self) -> None:
        theme = (
            Theme.LIGHT if self._config.appearance.theme is Theme.DARK else Theme.DARK
        )
        self._config.appearance.theme = theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        self.terminal.set_theme(theme)
        colors = theme_colors(theme)
        connected = self._service.is_connected
        settings = self._service.settings
        self.connection_bar.set_connected(
            connected,
            settings.describe() if (connected and settings) else "",
            colors["connected"] if connected else colors["disconnected"],
        )
        self.status.set_connection(
            connected,
            settings.port if (connected and settings) else "",
            settings.baud_rate if (connected and settings) else 0,
            colors["connected"] if connected else colors["disconnected"],
        )
        self.status.set_message(f"{theme.label} theme applied.")
        self._mark_dirty()

    # ==================================================================
    # Help
    # ==================================================================
    @slot()
    def _on_show_log(self) -> None:
        LogViewerDialog(self).exec()

    @slot()
    def _on_show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "Keyboard Shortcuts",
            "<table cellpadding='4'>"
            "<tr><td><b>Enter</b></td><td>Send the command</td></tr>"
            "<tr><td><b>Shift+Enter</b></td><td>New line in the input box</td></tr>"
            "<tr><td><b>Arrow Up / Down</b></td><td>Walk the send history</td></tr>"
            "<tr><td><b>Ctrl+Enter</b></td><td>Connect / Disconnect</td></tr>"
            "<tr><td><b>Ctrl+R</b></td><td>Refresh ports</td></tr>"
            "<tr><td><b>Ctrl+L</b></td><td>Clear the receive pane</td></tr>"
            "<tr><td><b>Ctrl+K</b></td><td>Clear the input box</td></tr>"
            "<tr><td><b>Ctrl+C</b></td><td>Copy the selection (terminal focus)</td></tr>"
            "<tr><td><b>Ctrl+Shift+C</b></td><td>Copy the whole receive pane</td></tr>"
            "<tr><td><b>Ctrl+A</b></td><td>Select all in the receive pane</td></tr>"
            "<tr><td><b>Ctrl+S</b></td><td>Save the receive log</td></tr>"
            "<tr><td><b>Ctrl+N</b></td><td>Add a command button</td></tr>"
            "<tr><td><b>Ctrl+T</b></td><td>Toggle the theme</td></tr>"
            "<tr><td><b>Ctrl+P</b></td><td>Profiles</td></tr>"
            "<tr><td><b>Ctrl+,</b></td><td>Settings</td></tr>"
            "<tr><td><b>Ctrl+Shift+S</b></td><td>Stop all auto-send</td></tr>"
            "</table>",
        )

    @slot()
    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>A serial terminal built around saved, one-click commands.</p>"
            f"<p><b>Designed and built by {AUTHOR}.</b><br>"
            f"<a href='{WEBSITE}'>{WEBSITE}</a></p>"
            f"<p>Settings: <code>{self._config_store.path}</code></p>"
            f"<p style='color:#8b95a5;'>{COPYRIGHT} — MIT Licence. "
            "Built with PySide6 and pyserial.</p>",
        )

    # ==================================================================
    # Status / banners
    # ==================================================================
    def _refresh_stats(self) -> None:
        self._stats.sample_rx_rate()
        self.status.set_counters(
            self._stats.rx_bytes, self._stats.tx_bytes, self._stats.rate_text()
        )
        buffer_used = self._buffer.total_bytes
        self.terminal.set_throughput_text(
            f"buffer {format_bytes(buffer_used)} / {format_bytes(self._buffer.max_bytes)}"
            + (f"  ·  {self._stats.rate_text()}" if self._service.is_connected else "")
        )

    @slot()
    def _on_reset_counters(self) -> None:
        self._stats.reset()
        self._service.reset_counters()
        self.status.set_counters(0, 0, "idle")
        self.status.set_message("Counters reset.")

    def _show_banner(self, error: UserError) -> None:
        object_name = {
            Severity.INFO: "BannerInfo",
            Severity.WARNING: "BannerWarning",
            Severity.ERROR: "BannerError",
        }[error.severity]
        self.banner.setObjectName(object_name)
        style = self.banner.style()
        style.unpolish(self.banner)
        style.polish(self.banner)
        self.banner.setText(error.full_text())
        self.banner.show()
        self._banner_wrapper.show()
        self._banner_timer.start(BANNER_TIMEOUT_MS)
        if error.detail:
            _log.debug("Banner detail: %s", error.detail)

    def _hide_banner(self) -> None:
        self.banner.hide()
        self._banner_wrapper.hide()

    # ==================================================================
    # Shutdown
    # ==================================================================
    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            self._autosend.stop_all()
            self._service.shutdown()
            self._store_geometry()
            self._sync_runtime_state_into_config()
            self._config_store.save(self._config, force=True)
        except ConfigError as exc:
            _log.error("Could not save settings on exit: %s", exc)
            warn(
                self,
                "Settings",
                map_config_error(exc, str(self._config_store.path)).full_text(),
            )
        except Exception:
            _log.exception("Unexpected error during shutdown")
        super().closeEvent(event)
