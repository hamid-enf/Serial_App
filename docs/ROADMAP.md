# Project status and roadmap

**Last updated:** 2026-09-05 · **Branch:** `arena/01a06db5-serial-app` · **PR:** [#1](https://github.com/hamid-enf/Serial_App/pull/1)

This file is the handover note. It records what exists, what was measured, what
was deliberately *not* done and why, and what is worth doing next — so that
picking the project up again does not start with an archaeology session.

---

## 1. Where the project stands

The application is complete against the original 36-section specification and
is in a releasable state.

| | |
| --- | --- |
| Application | `serial_console/` — layered: `core`, `transport`, `services`, `models`, `config`, `commands`, `ui` |
| Entry point | `main.py` (`--demo`, `--verbose`, `--selftest`, `--config PATH`, `--version`) |
| Tests | **411**, ~22 s, 90 % coverage of the non-UI layers (`pytest -q`) |
| Static checks | `ruff check` and `mypy serial_console` both clean |
| Packaging | `packaging/` — PyInstaller spec, `build.bat`, `build.ps1`, Inno Setup script, Windows version resource |
| CI | Written, **staged in `packaging/ci/`** — see §5.1 |
| Docs | `README.md` (full manual), `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/images/`, `docs/promo/` |
| Promo | 57-second clip, 16:9 and 9:16, Persian voiceover, in `docs/promo/` |

Nothing in the specification is outstanding. Everything below is *improvement*,
not completion.

### 1.1 The parts most likely to be touched next

| Path | Lines | What lives there |
| --- | --- | --- |
| `serial_console/ui/main_window.py` | ~1180 | Controller: wires services, panels, menus, shortcuts, autosave |
| `serial_console/ui/widgets/terminal_view.py` | ~470 | Receive pane, adaptive rendering, the `_LogOutput` text widget |
| `serial_console/core/terminal_buffer.py` | ~360 | Chunk store (source of truth) and `TerminalRenderer` |
| `serial_console/core/render_budget.py` | ~165 | `RenderBudget` + `FrameGovernor`, the two adaptive limits |
| `serial_console/core/codec.py` | ~210 | Hex/ASCII formatting, `StreamDecoder`, payload building |
| `serial_console/services/serial_service.py` | ~215 | Frame tick, RX drain, idle back-off, display interval |
| `scripts/bench_terminal.py` | ~215 | The performance harness — start here for any render work |

---

## 2. What has been measured (do not re-derive this)

Reproduce with `python scripts/bench_terminal.py` (needs only PySide6;
`QT_QPA_PLATFORM=offscreen` works headless).

### 2.1 Sustained cost, 40-second simulated sessions

| Scenario | UI thread spent on the log | Frame cost, first → last sixth |
| --- | --- | --- |
| 115200 baud | 10.0 % | 3.18 → 3.42 ms (×1.07) |
| 921600 baud | 12.7 % | 3.89 → 4.35 ms (×1.12) |
| 2 Mbit/s (250 kB/s) | 17.5 % | 5.07 → 5.65 ms (×1.11) |
| 2 Mbit/s, Hex+ASCII | 36.6 % | 11.17 → 12.27 ms (×1.10) |
| 8 Mbit/s (1 MB/s) | 34.0 % | 9.76 → 11.51 ms (×1.18) |
| 2 Mbit/s, machine 6× slower (`--slow 6`) | 38.5 % — was 51 % before the governor | 13.51 → 15.07 ms (×1.12) |

The cost is **flat over time**. There is no leak and no super-linear growth;
the original "it gets heavy after a while" was a fixed-30 fps policy failing on
a slow machine, not a resource leak.

### 2.2 Where a frame goes now (cProfile, 400 frames at 3 000 lines/s)

| | share |
| --- | --- |
| `QTextCursor.endEditBlock` (document edit + block trimming + relayout) | 41 % |
| viewport repaint | 26 % |
| scrolling to the bottom | 13 % |
| rest of the event loop | 11 % |
| `insertText` | 5 % |
| **all of this project's Python** | **~2 %** |

**Consequence: micro-optimising Python here is pointless.** The next real gain
requires not using `QPlainTextEdit` (see §4.1).

### 2.3 Experiments that were tried and rejected

Do not spend time re-testing these; the numbers are from this repository's own
harness on the development machine.

| Idea | Result |
| --- | --- |
| Batched manual block trimming instead of `setMaximumBlockCount` | **Worse**: 9.4 ms vs 7.2 ms steady, with 83 ms spikes |
| `setUpdatesEnabled(False)` around the insertion | **Worse**: 10.3 ms vs 8.3 ms (forces a full repaint on re-enable) |
| `NoWrap` instead of `WrapAnywhere` | No measurable difference |
| Smaller display block cap (5 000 vs 20 000) | No measurable difference |
| Splitting the insertion into 8 calls instead of 1 | No measurable difference (but 1 call is kept — it is simpler) |

### 2.4 Correctness measurements

- Multi-byte characters split across reads corrupted **45 %** of split
  positions before `StreamDecoder`; **0 %** after, verified at every byte
  offset and byte-at-a-time.
- Hex formatting: `format_hex` is ~32× faster and `format_hex_dump` ~7× faster
  than the original per-byte Python, with byte-identical output (asserted
  against a reference implementation kept in the tests).

---

## 3. Design decisions worth knowing before changing anything

1. **`TerminalBuffer` is the source of truth, not the widget.** Everything that
   exports, re-renders or switches display mode reads chunks, never the
   `QPlainTextEdit`. Keep it that way — it is why toggling Hex retroactively
   works.
2. **Capture and display are decoupled.** Every rendering limit gives up
   *pixels*, never bytes. Any new optimisation must preserve that: the buffer,
   the exports and the counters stay complete.
3. **The GUI thread never touches the port.** A dedicated reader thread blocks
   in `read()`; `RxAggregator` hands data over once per frame. Do not add a
   direct call from a widget to the transport.
4. **`APP_SLUG` must not change.** Existing installations would lose their
   config. There is a test asserting this.
5. **Errors become `UserError` in `core/errors.py`.** No raw exception text ever
   reaches a dialog; tests assert the exact wording.
6. **English-only UI and documentation** (owner's explicit instruction). The
   promo clip's *voiceover* and Instagram captions are Persian; nothing in the
   application is.
7. **Branding**: the ENF mark appears in the title bar, `--version`, the About
   dialog, the status bar, the icon, the Windows version resource, the
   installer, `LICENSE`, `pyproject.toml` and the README. `test_branding.py`
   guards all of it.

---

## 4. Ideas, ranked

Ordered by *value per unit of risk*. Each entry says what it is, why it is
worth doing, and roughly how.

### 4.1 A virtualised log widget — the only remaining big performance win

**Why.** §2.2 shows 95 % of a frame is inside Qt's rich-text machinery, doing
work a log viewer does not need: a full `QTextDocument` with per-block
formatting, undo-capable editing and a layout that is recomputed as blocks are
trimmed.

**What.** Replace `QPlainTextEdit` with a custom `QAbstractScrollArea` that
holds a `deque` of rendered lines (text + direction) and paints only the
visible ones with `QPainter.drawText`. Expect 5–10× lower cost per frame,
and trimming becomes `deque.popleft()` — free.

**Cost.** It has to reimplement selection, copy, mouse wheel/keyboard
scrolling, find, and the context menu. Budget a couple of focused days plus a
serious test suite. Keep the current widget behind a setting until the new one
has proved itself; `TerminalBuffer` already makes both views interchangeable.

**Do this only if** a user reports a machine where the current design is still
too slow — at 115200 baud it uses 10 % of one thread today.

### 4.2 Find, filter and highlight in the receive pane

**Why.** This is the feature people actually miss in the Arduino Serial
Monitor, and the buffer already has everything needed. It is a bigger practical
win than any further speed work.

**What.**
- `Ctrl+F` incremental find with next/previous and match count.
- A filter box: show only lines matching a substring or regex ("grep mode"),
  applied at *render* time from the buffer, so clearing the filter restores
  everything instantly and nothing is lost.
- User-defined highlight rules (regex → colour), stored per profile — e.g.
  `ERROR` in red, `OK` in green. This is the kind of thing that makes a tool
  feel professional.

**How.** All three are renderer-level: add an optional predicate and an
optional list of (pattern, format) to `TerminalRenderer`, and a re-render is
already how display settings change. Watch the cost of regex per line at high
rates — apply filters only when one is active, and count them in the frame
budget.

### 4.3 A plot view for numeric telemetry

**Why.** The Arduino Serial Plotter is the one feature people leave the Serial
Monitor for. Parsing `label:value` or CSV lines and drawing a rolling chart
would make this a strict superset.

**How.** A dockable panel; parse lines with a configurable regex into named
series; keep a fixed-size ring buffer per series; draw with `QPainter` (no
extra dependency) or `QtCharts` if a dependency is acceptable. Reuse
`FrameGovernor` for the redraw budget.

### 4.4 Command sequences / macros

**Why.** The saved buttons are the differentiator; the natural next step is a
*sequence*: send A, wait 200 ms, send B, wait for a line matching `OK`, then
send C. Bring-up scripts are exactly this.

**How.** A `Sequence` model beside `CommandButton`, a small step runner in
`services/` driven by the existing frame tick (never a blocking sleep), and an
editor dialog reusing the command editor's widgets. Stop-all already exists
(`Ctrl+Shift+S`) and should stop sequences too.

### 4.5 Smaller, high-value items

| Idea | Why | Sketch |
| --- | --- | --- |
| **Delta timestamps** (`+12.4 ms` since the previous line) | Best single feature for debugging timing, and trivial | A third timestamp mode in `TerminalRenderer._stamp` |
| **Auto-reconnect** when the port re-enumerates | ESP32/Arduino boards disappear on every flash | Watch the port list; if the last port comes back within N seconds, reopen with the same settings and say so in the log |
| **Reset / boot-mode buttons** (toggle DTR/RTS) | Standard need for ESP32 and STM32 | The transport already applies initial DTR/RTS; expose momentary toggles in the connection bar |
| **Auto-save the session to disk** with rotation | Long unattended captures currently rely on the in-memory buffer | Append raw bytes to a file as they arrive, in the reader thread's own writer; keep it independent from the display buffer |
| **Send a file / paste multiple lines with delay** | Bulk provisioning and config dumps | Reuse the sequence runner from §4.4 |
| **Button placeholders** (`{counter}`, `{time}`, `{clipboard}`) | Turns 20 buttons into 20 *parameterised* buttons | Expand in `build_payload`'s caller, not in the codec |
| **Per-button keyboard shortcuts** | Power users | `QShortcut` per button, stored in the model, validated for conflicts |
| **CRC / checksum helpers** in the command editor | Common protocol chore | A small `core/checksums.py` (CRC-8/16/32, XOR, sum) and a placeholder like `{crc16}` |
| **Multiple simultaneous ports** (tabs) | Gateway/bridge debugging | Largest structural change of this list: `MainWindow` currently owns one service; extract a `Session` object first |

### 4.6 Release engineering

- **Code signing.** SmartScreen warns on the unsigned `.exe`. An OV/EV
  certificate is the only real fix; document it in the README when it happens.
- **winget / Chocolatey manifest** once there is a signed release.
- **An update check** (a single HTTPS GET of the latest release tag, opt-in and
  off by default). Say so plainly in the README — a serial tool that phones
  home without asking would deserve the criticism.
- **A soak job in CI**: run `bench_terminal.py --seconds 120` and fail if the
  duty cycle regresses beyond a threshold. Cheap protection for §2.1.

### 4.7 Explicitly *not* planned

- **A Persian (or any other) UI translation.** The owner asked for
  English-only. The application is not internationalised; adding `tr()` calls
  everywhere would be a large change for something explicitly declined.
- **Rendering on a worker thread.** Qt's text layout is GUI-thread only. The
  correct lever is doing *less* work per frame, which is what §2 describes.
- **Replacing pyserial.** It is the right dependency; `QSerialPort` would trade
  a clean blocking read loop for an async API with fewer platform quirks
  handled.

---

## 5. Known gaps and chores

### 5.1 The CI workflows are not active

`packaging/ci/{tests.yml,build-windows.yml}` are finished but sit outside
`.github/workflows/`, because the automated account that wrote them cannot push
workflow files (GitHub rejects it without the `workflows` permission). One
`git mv` from a human clone activates both — see `packaging/ci/README.md`.
**Until then there is no CI, and no automatically built `.exe`.**

### 5.2 Other open items

- **No real-hardware testing.** Everything was exercised against the loopback
  transport, a mock port and the offscreen Qt platform. A pass with a real
  CH340/CP210x board, a USB unplug mid-stream and a 2 Mbaud device is the
  single most valuable manual QA left.
- **No Windows run.** The application has never been executed on Windows in
  this project's history — only Linux headless. High-DPI scaling, the native
  title bar and font rendering deserve a look.
- **UI dialogs are lightly tested** compared with the core (coverage is
  concentrated in the non-UI layers by design).
- **`promo/`** (renderer scratch, voice-over MP3s) is git-ignored on purpose;
  only the finished clips in `docs/promo/` are tracked.
- The branch has never been merged: **`main` is still the empty initial
  commit.** Merging PR #1 is step one of any future work.

---

## 6. Working conventions

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
pytest -q                       # must stay green — 411 tests, ~22 s
ruff check serial_console tests main.py scripts
mypy serial_console
python scripts/bench_terminal.py --rate 250000        # before/after any render change
QT_QPA_PLATFORM=offscreen python scripts/screenshot.py --theme dark --output docs/images/dark.png
```

- Every behavioural change gets a test; every user-visible change gets a
  `CHANGELOG.md` entry under `## [Unreleased]`.
- Comments explain *why*, not *what*. The existing code is written that way;
  match it.
- Performance claims belong in the README only with a number and the command
  that produced it.
