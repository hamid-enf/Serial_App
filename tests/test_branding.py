"""The ENF branding is part of the product, so it gets a test like anything else.

These are cheap guards against a rename or a refactor quietly dropping the
authorship marks from the binary, the installer or the UI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from serial_console import APP_NAME, AUTHOR, COPYRIGHT, ORG_NAME, SIGNATURE, __version__

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestIdentity:
    def test_constants(self) -> None:
        assert AUTHOR == "ENF"
        assert SIGNATURE == "ENF"
        assert ORG_NAME == "ENF"
        assert "ENF" in APP_NAME
        assert "ENF" in COPYRIGHT

    def test_config_slug_is_unchanged(self) -> None:
        # Renaming the product must not move a user's existing settings folder.
        from serial_console import APP_SLUG

        assert APP_SLUG == "SerialCommandConsole"


class TestPackagingMetadata:
    """The strings Windows shows in file properties and Add/Remove Programs."""

    def test_version_resource_credits_enf(self) -> None:
        text = (REPO_ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
        assert "StringStruct('CompanyName', 'ENF')" in text
        assert "ENF" in re.search(r"ProductName', '([^']+)'", text).group(1)
        assert "ENF" in re.search(r"LegalCopyright', '([^']+)'", text).group(1)

    def test_version_resource_matches_the_package_version(self) -> None:
        text = (REPO_ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
        expected = f"{__version__}.0"
        assert f"StringStruct('FileVersion', '{expected}')" in text
        assert f"StringStruct('ProductVersion', '{expected}')" in text

    def test_installer_publisher_is_enf(self) -> None:
        text = (REPO_ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        assert '#define AppPublisher   "ENF"' in text
        assert "AppCopyright=Copyright (c) 2026 ENF" in text
        assert f'#define AppVersion     "{__version__}"' in text

    def test_licence_is_held_by_enf(self) -> None:
        text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
        assert "Copyright (c) 2026 ENF" in text

    def test_readme_carries_the_mark(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert text.startswith("# ENF Serial Command Console")

    def test_icon_is_a_multi_resolution_ico(self) -> None:
        data = (REPO_ROOT / "resources" / "icons" / "app.ico").read_bytes()
        assert data[:4] == b"\x00\x00\x01\x00", "not an ICO container"
        frame_count = int.from_bytes(data[4:6], "little")
        assert frame_count >= 5, "Windows wants several sizes, not just one"


@pytest.mark.gui
class TestUiSignature:
    def test_status_bar_shows_the_mark(self, qapp) -> None:
        from serial_console.ui.widgets.status_bar import StatusBar

        bar = StatusBar()
        assert bar.signature_label.text() == "ENF"
        bar.deleteLater()

    def test_window_title_carries_the_product_name(self, window) -> None:
        assert "ENF" in window.windowTitle()

    def test_about_text_credits_enf(self, window, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[str] = []
        monkeypatch.setattr(
            "serial_console.ui.main_window.QMessageBox.about",
            lambda parent, title, text: captured.append(text),
        )
        window._on_about()
        assert captured and "ENF" in captured[0]
        assert "MIT" in captured[0]
