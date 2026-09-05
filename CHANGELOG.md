# Changelog

All notable changes to the ENF Serial Command Console are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- **Correct handling of multi-byte characters split across reads.** The renderer keeps
  an incremental decoder per direction, so Persian, Arabic, Cyrillic, CJK and emoji
  survive an arbitrary chunk boundary — previously about half of all such characters
  were shown as `�` when a frame boundary landed inside them. Verified at every split
  position, down to one byte at a time.
- **Persian and Arabic display properly.** Paragraph direction is pinned left-to-right
  so timestamps and columns keep their place while the text itself shapes and reads
  right-to-left.
- **Font fallback chain.** The terminal font is now a list — the resolved monospace
  face followed by Vazirmatn, Segoe UI, Tahoma, Noto Sans Arabic, DejaVu Sans and the
  emoji faces — with per-script substitution on Qt 6.8+, full hinting and explicit
  antialiasing. Glyphs the terminal font lacks come from a good face instead of
  whatever the system picks first.
- **Line spacing setting** (Settings → Appearance, 100–200 %, default 118 %), which
  makes dense logs easier to scan and gives Persian ascenders and descenders room.
- `cp1256` (Windows Persian/Arabic) added to the encoding list, and typed text is now
  encoded with the terminal's encoding rather than always UTF-8 — so a device that
  echoes returns exactly what was typed.

### Changed

- **The receive pane now paces itself.** Each display update measures its own cost
  (insertion plus repaint) and the pane asks the serial service for larger batches,
  less often, until rendering fits inside ~30 % of wall-clock time. The refresh rate
  moves between 30 fps and 5 fps by itself, so a slow machine, a large window or a
  2 Mbit/s stream no longer turns the UI sluggish as the session grows.
- **Per-frame render allowance.** The pane measures how many bytes per millisecond it
  can insert and skips anything beyond one frame's worth — now also *within* a single
  oversized chunk, which the previous flood guard could not split. An amber
  `display limited · N MB not shown` badge appears while this is in effect. Nothing is
  lost: the buffer, exports and counters still contain every byte, and toggling any
  display setting re-renders them from the buffer.
- **Hex formatting rewritten on C primitives.** `format_hex` is ~32× faster and
  `format_hex_dump` ~7× faster (`bytes.hex()` / `bytes.translate()` instead of per-byte
  Python loops), cutting whole milliseconds per frame off Hex and Hex+ASCII modes.
  Output is byte-for-byte identical, which is asserted against the old implementation.
- **Timestamp rendering** uses a single `str.replace` instead of a split/append/join
  loop, and neighbouring chunks with the same direction are merged into one insertion
  instead of one per chunk.
- **Nothing is rendered while the window is minimised**; the buffer is replayed on
  restore.
- **An idle connection backs its poll timer off** from 33 ms to 150 ms, so a connected
  but silent port costs almost no CPU. The first byte restores the fast rate.
- Status-bar labels are only repainted when their text actually changes.
- **The page stays still while you read history.** With auto-scroll off, the scroll
  position is compensated for the lines the block cap trims away; previously 4 000
  incoming lines would drag the text being read completely off screen.
- The scrollbar is no longer re-pinned to the bottom on every frame when it is already
  there — Qt keeps a bottom-anchored view pinned by itself, and the redundant call cost
  a scroll and a repaint each time (13 % of a frame, by profile).

### Added

- `scripts/bench_terminal.py` — simulates a session of a given length at a given data
  rate (optionally on a simulated slower machine) and reports the share of the UI
  thread spent rendering, plus per-segment frame costs to expose any degradation.
- `serial_console/core/render_budget.py` — `RenderBudget` and `FrameGovernor`, the two
  Qt-free adaptive limits, with 13 unit tests of their own.
- README: [Staying fast in a long session](README.md#staying-fast-in-a-long-session),
  with the measured numbers.

### Fixed

- A single chunk larger than the flood threshold used to be rendered in full, so one
  64 KB burst could stall a frame the guard was supposed to protect.
- Non-ASCII text was corrupted whenever a character straddled a read boundary.
- A full re-render or export could drop a trailing incomplete character; the renderer
  now flushes it.

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
