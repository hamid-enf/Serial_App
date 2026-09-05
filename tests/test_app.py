"""The application bootstrap: argument parsing, the excepthook and --selftest."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

from serial_console import APP_NAME, __version__
from serial_console.app import _install_excepthook, parse_args

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestParseArgs:
    def test_defaults(self) -> None:
        args = parse_args([])
        assert args.config is None
        assert args.verbose is False
        assert args.demo is False
        assert args.selftest is False

    def test_config_is_a_path(self) -> None:
        assert parse_args(["--config", "/tmp/other.json"]).config == Path("/tmp/other.json")

    @pytest.mark.parametrize("flag", ["--verbose", "--demo", "--selftest"])
    def test_flags(self, flag: str) -> None:
        assert getattr(parse_args([flag]), flag.lstrip("-")) is True

    def test_version_exits_zero_and_names_the_product(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            parse_args(["--version"])
        assert excinfo.value.code == 0
        printed = capsys.readouterr().out
        assert APP_NAME in printed
        assert __version__ in printed

    def test_an_unknown_flag_is_rejected(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            parse_args(["--nope"])
        assert excinfo.value.code == 2


class TestExceptHook:
    def test_unhandled_exceptions_are_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        original = sys.excepthook
        try:
            _install_excepthook()
            with caplog.at_level(logging.CRITICAL, logger="serial_console"):
                try:
                    raise ValueError("boom")
                except ValueError:
                    sys.excepthook(*sys.exc_info())
            assert "Unhandled exception" in caplog.text
            assert "boom" in caplog.text
        finally:
            sys.excepthook = original

    def test_keyboard_interrupt_is_left_to_python(self) -> None:
        # Ctrl+C must stay a quiet, normal exit rather than a logged crash.
        original = sys.excepthook
        seen: list[type[BaseException]] = []
        try:
            _install_excepthook()
            hook = sys.excepthook
            sys.__excepthook__ = lambda t, v, tb: seen.append(t)  # type: ignore[assignment]
            hook(KeyboardInterrupt, KeyboardInterrupt(), None)
            assert seen == [KeyboardInterrupt]
        finally:
            sys.excepthook = original


@pytest.mark.gui
class TestSelfTest:
    def test_the_app_boots_headlessly_and_reports_ok(self, tmp_path: Path) -> None:
        """End-to-end boot in a fresh process.

        This is the same check the release pipeline runs against the frozen
        .exe, so a missing resource or a broken import fails here first.
        """
        import os

        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["SERIAL_CONSOLE_HOME"] = str(tmp_path / "home")

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "main.py"), "--selftest"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr
        assert "SELFTEST OK" in result.stdout
        # A boot must leave the data directory ready for use.
        assert (tmp_path / "home" / "logs").is_dir()
