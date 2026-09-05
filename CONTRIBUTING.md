# Contributing

Thanks for taking the time to look at this project. Bug reports, ideas and pull
requests are all welcome.

## Ground rules

- **Reliability first.** This is a debugging tool. A feature that occasionally
  drops bytes or freezes the UI is worse than no feature at all. The priority
  order for every change is: reliability → responsiveness → usability →
  maintainability → visual polish.
- **Never block the GUI thread.** All serial I/O belongs to the reader thread
  (`serial_console/services/serial_service.py`). Data reaches the UI in batched
  signals, never one byte at a time.
- **Keep layers separate.** UI code does not talk to `pyserial`; core code does
  not import Qt. If a change needs a new dependency between layers, say so in
  the pull request so we can discuss it.

## Getting set up

```bash
git clone https://github.com/hamid-enf/Serial_App.git
cd Serial_App
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python main.py --demo        # runs against a virtual loopback port, no hardware needed
```

On Linux you also need `libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0`, and
your user must be in the `dialout` group to open real ports.

## Before you open a pull request

```bash
pytest                       # 358 tests, must stay green
ruff check .
ruff format --check .
mypy serial_console
```

The GitHub Actions workflow runs the same commands on Windows, Linux and macOS.

## Pull request checklist

- [ ] Tests cover the new behaviour (including the failure path, if there is one).
- [ ] No new blocking call on the GUI thread.
- [ ] Errors reach the user as a friendly message, not a raw exception string.
- [ ] `CHANGELOG.md` has an entry under *Unreleased*.
- [ ] Docstrings explain *why*, not *what*.

## Commit messages

Short imperative subject line, optional body explaining the reasoning:

```
Trim the terminal buffer in whole chunks

Trimming byte-by-byte made a 50 MB buffer walk the whole deque on every
append at high baud rates.
```

## Reporting bugs

Please use the issue templates — they ask for the OS, the device, the baud rate
and the log file, which is almost always what a diagnosis needs. The log lives
next to the config file (`Help → Open log folder`).

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
