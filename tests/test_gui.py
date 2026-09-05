"""Qt-level tests: service plumbing, auto-send and main-window behaviour.

These need a ``QApplication`` but no display: ``QT_QPA_PLATFORM=offscreen`` is
set in ``conftest``, which is also how they run in CI.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is required for the GUI tests")

from conftest import spin, spin_until
from PySide6.QtWidgets import QApplication

from serial_console.config.store import ConfigStore
from serial_console.core.history import CommandHistory
from serial_console.models.command import AutoSendSpec, CommandButton
from serial_console.models.enums import Direction, DisplayMode, LineEnding, Theme
from serial_console.models.settings import AppConfig, SerialSettings
from serial_console.services.autosend import AutoSendScheduler
from serial_console.services.serial_service import SerialService
from serial_console.transport.loopback import LoopbackTransport

pytestmark = pytest.mark.gui


@pytest.fixture()
def settings() -> SerialSettings:
    return SerialSettings(port="VIRTUAL", baud_rate=115200, read_timeout_s=0.01)


# ----------------------------------------------------------------------
class TestSerialService:
    def test_connect_emits_connected(self, qapp: QApplication, settings) -> None:
        service = SerialService(LoopbackTransport(), poll_interval_ms=10)
        seen: list[object] = []
        service.connected.connect(seen.append)
        try:
            assert service.connect_port(settings) is True
            assert spin_until(lambda: bool(seen))
            assert service.is_connected
        finally:
            service.shutdown()

    def test_received_data_is_delivered_in_batches(
        self, qapp: QApplication, settings
    ) -> None:
        transport = LoopbackTransport(echo=False)
        service = SerialService(transport, poll_interval_ms=10)
        batches: list[bytes] = []
        service.dataReceived.connect(batches.append)
        try:
            service.connect_port(settings)
            spin(60)
            for _ in range(50):
                transport.feed(b"0123456789")
            assert spin_until(lambda: sum(len(b) for b in batches) == 500)
            # Coalescing means far fewer signals than reads.
            assert len(batches) < 50
        finally:
            service.shutdown()

    def test_send_round_trips_through_the_loopback(
        self, qapp: QApplication, settings
    ) -> None:
        service = SerialService(LoopbackTransport(echo=True), poll_interval_ms=10)
        received = bytearray()
        service.dataReceived.connect(received.extend)
        try:
            service.connect_port(settings)
            spin(60)
            assert service.send(b"PING\n") is True
            assert spin_until(lambda: bytes(received) == b"PING\n")
        finally:
            service.shutdown()

    def test_send_while_disconnected_reports_a_user_error(
        self, qapp: QApplication
    ) -> None:
        service = SerialService(LoopbackTransport(), poll_interval_ms=10)
        errors: list[object] = []
        service.errorRaised.connect(errors.append)
        assert service.send(b"x") is False
        assert errors
        assert "Not connected" in errors[0].message
        service.shutdown()

    def test_open_failure_emits_error_immediately(
        self, qapp: QApplication, settings
    ) -> None:
        import serial

        service = SerialService(
            LoopbackTransport(fail_on_open=serial.SerialException("Access is denied")),
            poll_interval_ms=10,
        )
        errors: list[object] = []
        service.errorRaised.connect(errors.append)
        assert service.connect_port(settings) is False
        assert errors, "the error must not wait for the next timer tick"
        service.shutdown()

    def test_disconnect_stops_polling(self, qapp: QApplication, settings) -> None:
        service = SerialService(LoopbackTransport(), poll_interval_ms=10)
        reasons: list[str] = []
        service.disconnected.connect(reasons.append)
        service.connect_port(settings)
        spin(50)
        service.disconnect_port()
        assert spin_until(lambda: reasons == ["user"])
        assert service.is_connected is False
        service.shutdown()

    def test_shutdown_is_safe_when_never_connected(self, qapp: QApplication) -> None:
        SerialService(LoopbackTransport()).shutdown()


# ----------------------------------------------------------------------
class TestAutoSendScheduler:
    def test_start_fires_immediately_then_repeats(self, qapp: QApplication) -> None:
        calls: list[str] = []
        scheduler = AutoSendScheduler(lambda button: (calls.append(button.id), True)[1])
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=25)
        try:
            scheduler.start(button)
            assert len(calls) == 1  # immediate feedback
            assert spin_until(lambda: len(calls) >= 3, timeout_ms=2000)
        finally:
            scheduler.stop_all()

    def test_stop_halts_the_timer(self, qapp: QApplication) -> None:
        calls: list[str] = []
        scheduler = AutoSendScheduler(lambda button: (calls.append(button.id), True)[1])
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=20)
        scheduler.start(button)
        spin(80)
        scheduler.stop(button.id)
        count = len(calls)
        spin(120)
        assert len(calls) == count

    def test_toggle(self, qapp: QApplication) -> None:
        scheduler = AutoSendScheduler(lambda button: True)
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=100)
        assert scheduler.toggle(button) is True
        assert scheduler.is_running(button.id)
        assert scheduler.toggle(button) is False
        assert not scheduler.is_running(button.id)

    def test_a_rejected_send_stops_the_job(self, qapp: QApplication) -> None:
        scheduler = AutoSendScheduler(lambda button: False)
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=20)
        scheduler.start(button)
        assert scheduler.active_count == 0

    def test_a_raising_callback_stops_the_job_instead_of_spinning(
        self, qapp: QApplication
    ) -> None:
        def boom(button: CommandButton) -> bool:
            raise RuntimeError("bad payload")

        scheduler = AutoSendScheduler(boom)
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=20)
        scheduler.start(button)
        assert scheduler.active_count == 0

    def test_interval_below_the_floor_is_clamped(self, qapp: QApplication) -> None:
        scheduler = AutoSendScheduler(lambda button: True)
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=1)
        scheduler.start(button)
        try:
            assert scheduler.aggregate_rate_hz() <= 1000 / 20 + 0.001
        finally:
            scheduler.stop_all()

    def test_update_applies_a_new_interval_to_a_running_job(
        self, qapp: QApplication
    ) -> None:
        scheduler = AutoSendScheduler(lambda button: True)
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=1000)
        scheduler.start(button)
        button.auto_send.interval_ms = 50
        scheduler.update_button(button)
        assert scheduler.aggregate_rate_hz() == pytest.approx(20.0)
        scheduler.stop_all()

    def test_disabling_a_button_stops_its_job(self, qapp: QApplication) -> None:
        scheduler = AutoSendScheduler(lambda button: True)
        button = CommandButton(name="Poll", command="AT")
        button.auto_send = AutoSendSpec(enabled=True, interval_ms=100)
        scheduler.start(button)
        button.enabled = False
        scheduler.update_button(button)
        assert scheduler.active_count == 0

    def test_stop_all(self, qapp: QApplication) -> None:
        scheduler = AutoSendScheduler(lambda button: True)
        for index in range(5):
            button = CommandButton(name=f"P{index}", command="AT")
            button.auto_send = AutoSendSpec(enabled=True, interval_ms=200)
            scheduler.start(button)
        assert scheduler.active_count == 5
        scheduler.stop_all()
        assert scheduler.active_count == 0


# ----------------------------------------------------------------------
class TestMainWindow:
    def test_constructs_with_all_panels(self, window) -> None:
        assert window.terminal is not None
        assert window.send_panel is not None
        assert window.command_panel is not None
        assert len(window.command_panel._widgets) == 20  # default button count

    def test_manual_send_appends_to_history_and_terminal(self, window) -> None:
        window._service.connect_port(SerialSettings(port="VIRTUAL", read_timeout_s=0.01))
        spin(80)
        window._on_manual_send("AT+STATUS", False, LineEnding.CRLF)
        assert spin_until(lambda: b"AT+STATUS\r\n" in window._buffer.to_raw_bytes())
        assert window._history.entries()[0] == "AT+STATUS"

    def test_line_ending_is_applied_to_command_buttons(self, window) -> None:
        window._service.connect_port(SerialSettings(port="VIRTUAL", read_timeout_s=0.01))
        spin(80)
        window.send_panel.set_line_ending(LineEnding.CR)
        button = window._commands.buttons[0]
        button.name, button.command, button.line_ending = "Probe", "AT", None
        assert window._send_button_payload(button) is True
        assert spin_until(
            lambda: window._service.transport.written.endswith(b"AT\r")
        )

    def test_a_per_button_line_ending_overrides_the_global_one(self, window) -> None:
        window._service.connect_port(SerialSettings(port="VIRTUAL", read_timeout_s=0.01))
        spin(80)
        window.send_panel.set_line_ending(LineEnding.LF)
        button = window._commands.buttons[0]
        button.command, button.line_ending = "AT", LineEnding.CRLF
        window._send_button_payload(button)
        assert spin_until(
            lambda: window._service.transport.written.endswith(b"AT\r\n")
        )

    def test_blank_button_reports_instead_of_sending(self, window) -> None:
        blank = window._commands.buttons[-1]
        blank.command = ""
        assert window._send_button_payload(blank) is False
        # The window is never shown in tests, so check the content not visibility.
        assert "no command to send" in window.banner.text()

    def test_clear_empties_buffer_and_view(self, window) -> None:
        window._append_info("noise\n")
        window._on_clear_terminal()
        assert window._buffer.total_bytes == 0
        assert window.terminal.output.toPlainText() == ""

    def test_adding_and_deleting_a_command_button(self, window) -> None:
        before = len(window._commands)
        window._commands.add(CommandButton(name="Extra", command="X"))
        window.command_panel.rebuild()
        assert len(window.command_panel._widgets) == before + 1
        target = window._commands.buttons[-1]
        window._config.commands.confirm_delete = False
        window._delete_command(target.id, target.name)
        assert len(window._commands) == before

    def test_reorder_moves_the_button(self, window) -> None:
        first = window._commands.buttons[0]
        window._on_reorder_command(first.id, 3)
        assert window._commands.index_of(first.id) == 2

    def test_theme_toggle_switches_and_persists(self, window) -> None:
        original = window._config.appearance.theme
        window._toggle_theme()
        assert window._config.appearance.theme is not original
        window._flush_config()
        reloaded = ConfigStore(window._config_store.path).load().config
        assert reloaded.appearance.theme is not original

    def test_settings_survive_a_close(self, window, tmp_path: Path) -> None:
        window._commands.buttons[0].name = "Persisted"
        window._commands.buttons[0].command = "PERSIST"
        window.close()
        reloaded = ConfigStore(window._config_store.path).load().config
        assert reloaded.active_profile().buttons[0].name == "Persisted"
        assert reloaded.active_profile().buttons[0].command == "PERSIST"

    def test_display_mode_change_rerenders_history(self, window) -> None:
        window._buffer.append(Direction.RX, b"Hi")
        window.terminal.rerender()
        assert "Hi" in window.terminal.output.toPlainText()
        window._config.terminal.display_mode = DisplayMode.HEX
        window.terminal.apply_settings(window._config.terminal, Theme.DARK)
        assert "48 69" in window.terminal.output.toPlainText()

    def test_high_rate_stream_does_not_stall_the_event_loop(self, window) -> None:
        transport = window._service.transport
        window._service.connect_port(SerialSettings(port="VIRTUAL", read_timeout_s=0.01))
        spin(80)
        payload = b"A" * 4096
        start = time.monotonic()
        for _ in range(256):  # 1 MiB
            transport.feed(payload)
        assert spin_until(
            lambda: window._stats.rx_bytes >= 1024 * 1024, timeout_ms=15000
        )
        # The whole megabyte is accounted for and the loop stayed responsive.
        assert time.monotonic() - start < 15
        assert window._buffer.total_bytes <= window._buffer.max_bytes

    def test_terminal_buffer_limit_is_honoured_during_a_flood(self, window) -> None:
        window._buffer.set_max_bytes(64 * 1024)
        for _ in range(200):
            window._on_data_received(b"z" * 4096)
        assert window._buffer.total_bytes <= 64 * 1024

    def test_export_text_csv_and_binary(self, window, tmp_path: Path) -> None:
        window._buffer.clear()  # drop the startup banner line
        window._buffer.append(Direction.RX, b"hello\n")
        (tmp_path / "out.txt").write_text(window._buffer.render(), encoding="utf-8")
        (tmp_path / "out.csv").write_text(window._buffer.to_csv(), encoding="utf-8")
        (tmp_path / "out.bin").write_bytes(window._buffer.to_raw_bytes())
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello\n"
        assert "hello" in (tmp_path / "out.csv").read_text(encoding="utf-8")
        assert (tmp_path / "out.bin").read_bytes() == b"hello\n"

    def test_profile_switch_swaps_buttons_and_history(self, window) -> None:
        window._history.add("first-profile-command")
        second = window._profiles.create("Second", button_count=3)
        window._on_profile_changed(second.id)
        assert len(window._commands) == 3
        assert window._history.entries() == []
        window._on_profile_changed(window._profiles.profiles[0].id)
        assert "first-profile-command" in window._history.entries()

    def test_counters_reset(self, window) -> None:
        window._stats.add_rx(1000)
        window._on_reset_counters()
        assert window._stats.rx_bytes == 0


# ----------------------------------------------------------------------
class TestSendPanel:
    def test_arrow_up_walks_history(self, qapp: QApplication) -> None:
        from serial_console.ui.widgets.send_panel import SendPanel

        history = CommandHistory()
        for command in ("one", "two"):
            history.add(command)
        panel = SendPanel(history)
        panel._on_history_previous()
        assert panel.input.text_value() == "two"
        panel._on_history_previous()
        assert panel.input.text_value() == "one"
        panel._on_history_next()
        assert panel.input.text_value() == "two"
        panel.deleteLater()

    def test_hex_toggle_shows_a_hint(self, qapp: QApplication) -> None:
        from serial_console.ui.widgets.send_panel import SendPanel

        panel = SendPanel(CommandHistory())
        panel.set_hex_mode(True)
        assert "48 65 6C 6C 6F" in panel.hint_label.text()
        panel.deleteLater()

    def test_send_signal_carries_mode_and_ending(self, qapp: QApplication) -> None:
        from serial_console.ui.widgets.send_panel import SendPanel

        panel = SendPanel(CommandHistory())
        payloads: list[tuple] = []
        panel.sendRequested.connect(lambda *args: payloads.append(args))
        panel.set_line_ending(LineEnding.CRLF)
        panel.input.set_text_value("AT")
        panel._on_submit()
        assert payloads == [("AT", False, LineEnding.CRLF)]
        panel.deleteLater()

    def test_blank_input_does_not_send(self, qapp: QApplication) -> None:
        from serial_console.ui.widgets.send_panel import SendPanel

        panel = SendPanel(CommandHistory())
        payloads: list[tuple] = []
        panel.sendRequested.connect(lambda *args: payloads.append(args))
        panel.input.set_text_value("   ")
        panel._on_submit()
        assert payloads == []
        panel.deleteLater()


class TestCommandEditorDialog:
    def test_round_trips_a_button(self, qapp: QApplication) -> None:
        from serial_console.ui.dialogs.command_editor import CommandEditorDialog

        button = CommandButton(
            name="Read Temp", command="AT+TEMP?", line_ending=LineEnding.CRLF
        )
        dialog = CommandEditorDialog(button, LineEnding.LF)
        result = dialog.result_button()
        assert result.id == button.id
        assert result.name == "Read Temp"
        assert result.command == "AT+TEMP?"
        assert result.line_ending is LineEnding.CRLF
        dialog.deleteLater()

    def test_inherit_is_preserved(self, qapp: QApplication) -> None:
        from serial_console.ui.dialogs.command_editor import CommandEditorDialog

        dialog = CommandEditorDialog(CommandButton(name="A", command="X"), LineEnding.LF)
        assert dialog.result_button().line_ending is None
        dialog.deleteLater()

    def test_preview_shows_the_wire_bytes(self, qapp: QApplication) -> None:
        from serial_console.ui.dialogs.command_editor import CommandEditorDialog

        button = CommandButton(name="A", command="Hi", line_ending=LineEnding.CRLF)
        dialog = CommandEditorDialog(button, LineEnding.NONE)
        assert "48 69 0D 0A" in dialog.preview_label.text()
        dialog.deleteLater()

    def test_invalid_hex_is_reported_in_the_dialog(self, qapp: QApplication) -> None:
        from serial_console.ui.dialogs.command_editor import CommandEditorDialog

        button = CommandButton(name="A", command="ZZ", hex_mode=True)
        dialog = CommandEditorDialog(button, LineEnding.NONE)
        assert dialog.error_label.isVisible() or dialog.error_label.text()
        dialog.deleteLater()


class TestSettingsDialog:
    def test_edits_a_copy_not_the_live_config(self, qapp: QApplication) -> None:
        from serial_console.ui.dialogs.settings_dialog import SettingsDialog

        config = AppConfig.create_default()
        dialog = SettingsDialog(config)
        dialog.font_size_spin.setValue(20)
        dialog._collect()
        assert dialog.config.appearance.font_size == 20
        assert config.appearance.font_size != 20
        dialog.deleteLater()

    def test_rejects_an_unknown_encoding(self, qapp: QApplication) -> None:
        from serial_console.models.errors import ValidationError
        from serial_console.ui.dialogs.settings_dialog import SettingsDialog

        dialog = SettingsDialog(AppConfig.create_default())
        dialog.encoding_combo.setCurrentText("not-a-codec")
        with pytest.raises(ValidationError):
            dialog._collect()
        dialog.deleteLater()


# ----------------------------------------------------------------------
class TestTerminalPerformanceGuards:
    """The mechanisms that keep the pane responsive in a long, busy session.

    Every one of them trades *pixels* for responsiveness and never bytes: the
    buffer — the thing that gets exported — must always come out complete.
    """

    def _view(self, qapp: QApplication):
        from serial_console.core.terminal_buffer import TerminalBuffer
        from serial_console.ui.widgets.terminal_view import TerminalView

        buffer = TerminalBuffer(8 * 1024 * 1024)
        view = TerminalView(buffer)
        view.resize(900, 500)
        return buffer, view

    def test_oversized_frame_renders_only_the_tail(self, qapp: QApplication) -> None:
        buffer, view = self._view(qapp)
        payload = b"".join(b"line %05d\n" % i for i in range(40_000))  # ~440 KB
        view.append_chunks(buffer.append(Direction.RX, payload))

        shown = view.output.toPlainText()
        assert "line 39999" in shown, "the newest data must always be visible"
        assert "line 00000" not in shown, "the head of a flood is not drawn"
        # Nothing was lost where it matters: the buffer still has everything.
        assert buffer.total_bytes == len(payload)
        assert "line 00000" in buffer.render()

    def test_flood_is_announced_and_the_notice_clears(self, qapp: QApplication) -> None:
        buffer, view = self._view(qapp)
        view.append_chunks(buffer.append(Direction.RX, b"x" * (2 * 1024 * 1024)))
        assert not view.notice_label.isHidden()
        assert "not shown" in view.notice_label.text()
        assert "faster than the display" in view.output.toPlainText()

        view.append_chunks(buffer.append(Direction.RX, b"calm\n"))
        assert view.notice_label.isHidden()
        assert view.notice_label.text() == ""

    def test_decimated_output_never_starts_mid_line(self, qapp: QApplication) -> None:
        buffer, view = self._view(qapp)
        payload = b"".join(b"%05d-abcdefghijklmnop\n" % i for i in range(30_000))
        view.append_chunks(buffer.append(Direction.RX, payload))
        for line in view.output.toPlainText().splitlines():
            if line.startswith("…") or not line.strip():
                continue
            assert line[:5].isdigit() and line[5] == "-", f"half a line: {line!r}"

    def test_nothing_is_rendered_while_the_window_is_minimised(
        self, qapp: QApplication
    ) -> None:
        from PySide6.QtWidgets import QMainWindow

        from serial_console.core.terminal_buffer import TerminalBuffer
        from serial_console.ui.widgets.terminal_view import TerminalView

        buffer = TerminalBuffer(1024 * 1024)
        view = TerminalView(buffer)
        host = QMainWindow()
        host.setCentralWidget(view)
        host.showMinimized()

        view.append_chunks(buffer.append(Direction.RX, b"while minimised\n"))
        assert "while minimised" not in view.output.toPlainText()

        host.showNormal()
        view.append_chunks(buffer.append(Direction.RX, b"after restore\n"))
        shown = view.output.toPlainText()
        assert "while minimised" in shown, "the buffer is replayed on restore"
        assert buffer.total_bytes == len(b"while minimised\nafter restore\n")

    def test_display_interval_follows_the_measured_cost(self, window) -> None:
        from serial_console.core.render_budget import MIN_INTERVAL_MS

        assert window.terminal.suggested_refresh_ms() == MIN_INTERVAL_MS
        # Pretend every update is expensive; the window must slow the feed down
        # instead of letting the text widget monopolise the event loop.
        for _ in range(60):
            window.terminal._governor.record(45.0)
        window._on_data_received(b"tick\n")
        assert window.terminal.suggested_refresh_ms() > MIN_INTERVAL_MS
        assert window._service.poll_interval_ms() >= MIN_INTERVAL_MS

    def test_chunks_are_coalesced_into_one_insertion(self, qapp: QApplication) -> None:
        buffer, view = self._view(qapp)
        chunks = []
        for index in range(20):
            chunks.extend(buffer.append(Direction.RX, b"part-%02d " % index))
        view.append_chunks(chunks)
        text = view.output.toPlainText()
        assert text.startswith("part-00 part-01 ")
        assert text.endswith("part-19 ")

    def test_idle_connection_backs_the_poll_timer_off(
        self, qapp: QApplication, settings
    ) -> None:
        from serial_console.services.serial_service import (
            IDLE_POLL_INTERVAL_MS,
            SerialService,
        )

        service = SerialService(LoopbackTransport(echo=False), poll_interval_ms=10)
        try:
            service.connect_port(settings)
            assert service.poll_interval_ms() == 10
            service._last_activity -= 10.0  # pretend the line has been quiet
            service._on_tick()
            assert service.poll_interval_ms() == IDLE_POLL_INTERVAL_MS
            # …and the first byte restores the responsive rate.
            received: list[bytes] = []
            service.dataReceived.connect(received.append)
            service.transport.feed(b"wake up\n")
            assert spin_until(lambda: bool(received), timeout_ms=3000)
            assert service.poll_interval_ms() == 10
        finally:
            service.shutdown()
