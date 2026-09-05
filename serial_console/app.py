"""Application bootstrap: logging, configuration, theme and the main window."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import APP_NAME, APP_SLUG, ORG_NAME, __version__
from .config.paths import ensure_dirs, log_dir
from .config.store import ConfigStore
from .core.logging_setup import get_logger, setup_logging

_log = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="serial-console", description=f"{APP_NAME} — serial terminal with saved commands"
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to an alternative configuration file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging and mirror the log to the console.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run against a virtual loopback port instead of real hardware.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help=(
            "Build the window, verify the bundled resources and exit. Used by the "
            "packaging pipeline to prove a frozen build actually starts."
        ),
    )
    return parser.parse_args(argv)


def _install_excepthook() -> None:
    """Log unhandled exceptions instead of dying silently.

    Qt swallows exceptions raised inside slots on some platforms; routing them
    through the logger means a bug leaves a trace the user can send us.
    """

    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("serial_console").critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    ensure_dirs()
    setup_logging(
        log_dir(),
        level=logging.DEBUG if args.verbose else logging.INFO,
        console=args.verbose,
    )
    _install_excepthook()
    _log.info("Starting %s %s", APP_NAME, __version__)

    # Imported after logging is configured so Qt import errors are recorded.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .config.paths import resource_dir
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_SLUG)

    icon_path = resource_dir() / "icons" / "app.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    store = ConfigStore(args.config)
    result = store.load()
    config = result.config
    if result.recovered:
        _log.warning("Configuration recovered: %s", result.message)

    apply_theme(app, config.appearance.theme)

    transport = None
    if args.demo:
        from .transport.loopback import LoopbackTransport

        transport = LoopbackTransport(echo=True)
        _log.info("Demo mode: using an in-process loopback transport")

    window = MainWindow(
        config,
        store,
        transport=transport,
        startup_notice=result.message if result.recovered else "",
    )

    if args.selftest:
        return _selftest(window, config)

    window.show()

    exit_code = app.exec()
    _log.info("Exiting with code %s", exit_code)
    return int(exit_code)


def _selftest(window, config) -> int:
    """Headless smoke test of a built (usually frozen) application.

    A frozen build fails in ways a source run never does — a missing hidden
    import, a data file that did not make it into the bundle. Constructing the
    whole window and checking the theme actually loaded catches both, without
    needing an interactive desktop session.
    """
    from .config.paths import resource_dir
    from .ui.theme import load_stylesheet

    problems: list[str] = []
    if not load_stylesheet(config.appearance.theme).strip():
        problems.append("theme stylesheet is empty or missing")
    if window.command_panel is None or len(window.command_panel) == 0:
        problems.append("command panel has no buttons")
    if not (resource_dir() / "icons").is_dir():
        problems.append("bundled icons are missing")
    try:
        import serial.tools.list_ports  # noqa: F401
    except Exception as exc:  # pragma: no cover - defensive
        problems.append(f"pyserial port enumeration unavailable: {exc}")

    window.close()
    if problems:
        for problem in problems:
            _log.error("Self-test failure: %s", problem)
            print(f"SELFTEST FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"SELFTEST OK: {APP_NAME} {__version__}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
