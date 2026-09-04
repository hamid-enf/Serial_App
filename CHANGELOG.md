# Changelog

All notable changes to the ENF Serial Command Console are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [semantic versioning](https://semver.org/).

## [1.0.0] — 2026-09-04

First release. A complete replacement for the Arduino Serial Monitor, built
around saved command buttons.

### Added

**Connection**
- Port picker with live enumeration and device descriptions (`Ctrl+R` to refresh).
- Baud rates 300 – 2 000 000 plus free-text custom values, validated against the driver range.
- Data bits (5/6/7/8), parity (None/Even/Odd/Mark/Space), stop bits (1/1.5/2).
- Flow control: none, RTS/CTS, XON/XOFF, DSR/DTR — mutually exclusive by construction.
- Initial DTR/RTS state applied *before* the port opens, so boards that wire DTR to
  reset are not pulsed on connect.

**Receive**
- Real-time view with auto-scroll that pauses when the user scrolls up.
- Per-line timestamps; distinct RX / TX / notice styling.
- ASCII, Hex and Hex+ASCII display modes, applied retroactively to existing history.
- Copy, Select All, Clear; export to TXT, CSV (`timestamp_iso,direction,text,hex`) and raw binary.
- Configurable buffer ceiling (1/5/10/50 MB) with trimming from the oldest end.

**Transmit**
- Enter to send, Shift+Enter for a newline, HEX input mode.
- Line ending selector (None/LF/CR/CRLF) shared by typed sends and command buttons.
- Command history with Up/Down navigation, de-duplication and a configurable bound.

**Command buttons**
- 20 by default, unlimited in practice, in a scrollable panel with an adjustable column count.
- Per button: name, command, line ending override, HEX mode, enabled flag, description, auto-send interval.
- Add, Edit, Delete, Duplicate, Rename, Reset, Move Up/Down and drag-and-drop reordering.
- Auto-repeat per button (≥ 20 ms) with a visible repeating state and a global stop (`Ctrl+Shift+S`).
- Live byte preview in the editor, so the exact wire payload is never a surprise.

**Profiles**
- Create, Rename, Duplicate, Delete, Import, Export — each owning its buttons,
  serial settings and command history. Imports are re-keyed, so a profile can be
  imported twice without clashing.

**Persistence and robustness**
- Single human-readable `config.json`; atomic writes with a `.bak` and a schema version.
- Corrupt configuration is quarantined (`config.corrupt-<timestamp>.json`, at most six kept),
  the backup is tried, and the app still starts with defaults.
- Portable mode via a `portable.txt` marker next to the executable.
- Every serial and configuration failure is mapped to a plain-English message with a hint;
  no raw exception text ever reaches a dialog.
- Rotating log file, in-app log viewer, and a read-only install directory does not prevent startup.

**Interface**
- Dark and Light themes (`Ctrl+T`), persisted, with a full hand-written stylesheet.
- Settings dialog grouped into Serial / Terminal / Appearance / Commands.
- Status bar with connection state, port, baud, RX/TX counters, throughput and a reset.
- Keyboard shortcuts throughout, listed under `F1`.

**Engineering**
- Six-layer architecture; `core/` and `models/` import no Qt and need no event loop.
- Serial I/O on a dedicated thread with a bounded RX aggregator drained by a 33 ms GUI timer.
- 358 tests, no hardware required, GUI tests offscreen; 90% line coverage of the non-UI code.
- `ruff` and `mypy` clean.
- PyInstaller spec, `build.bat` / `build.ps1`, Inno Setup installer, and GitHub Actions
  workflows for the test matrix and the Windows build.

### Fixed during development

- **Double / missing disconnect events.** `SerialWorker.stop()` decided whether to emit
  `CLOSED` from a flag the exiting thread had already cleared, so a clean disconnect emitted
  none and a cable pulled out mid-click could emit two. An atomic claim now guarantees exactly one.
- **Blank command buttons transmitted a bare line ending.** With the global ending set to LF an
  unconfigured button produced `b"\n"`, which is truthy, so the "nothing to send" guard never
  fired and the device was poked. The guard now tests the button, not the payload.
- **`QScrollArea` stored as `self.scroll`,** shadowing `QWidget.scroll()`. Renamed to `scroll_area`.
- **Qt-facing enums must not subclass `str`** — PySide6 flattens them to plain strings when they
  cross into `QVariant` item data, so `combo.currentData().value` blew up. All enums are plain
  `Enum` with a `.label`.

[1.0.0]: https://github.com/hamid-enf/Serial_App/releases/tag/v1.0.0
