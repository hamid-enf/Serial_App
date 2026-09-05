"""Theme loading, palette and font selection."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from ..config.paths import resource_dir
from ..core.logging_setup import get_logger
from ..models.enums import Direction, Theme

_log = get_logger(__name__)

#: Preferred monospace faces, best first.  The first one installed wins.
_MONO_CANDIDATES = (
    "Cascadia Mono",      # Windows 11 / Windows Terminal, excellent hinting
    "Consolas",           # every Windows since Vista
    "JetBrains Mono",
    "Cascadia Code",
    "SF Mono",            # macOS
    "Menlo",
    "DejaVu Sans Mono",   # Linux, and the widest glyph coverage of the list
    "Noto Sans Mono",
    "Liberation Mono",
    "Courier New",        # last resort: present everywhere, pretty nowhere
)

#: Families asked to supply glyphs the monospace font does not have. Qt walks
#: this list per character (per *script* run on Qt 6.8+), so Persian, Arabic,
#: Cyrillic, CJK and box-drawing characters render properly instead of turning
#: into hollow boxes when the terminal font has no coverage for them.
_FALLBACK_CANDIDATES = (
    "Vazirmatn",          # if the user installed a proper Persian font
    "Sahel",
    "Segoe UI",           # Windows: full Arabic/Persian coverage
    "Tahoma",             # the classic Windows Persian face
    "Noto Sans Arabic",
    "Noto Sans",
    "DejaVu Sans",
    "Arial Unicode MS",
    "Segoe UI Emoji",
    "Noto Color Emoji",
)


@cache
def theme_colors(theme: Theme) -> dict[str, str]:
    """Colours the widgets need programmatically (QSS cannot reach them)."""
    if theme is Theme.LIGHT:
        return {
            "rx": "#17202c",
            "tx": "#1857b8",
            "info": "#5b6675",
            "error": "#b3291a",
            "timestamp": "#8a95a3",
            "accent": "#1f6feb",
            "connected": "#1a7f37",
            "disconnected": "#8a95a3",
            "warning": "#b5860b",
            "terminal_bg": "#fbfcfe",
        }
    return {
        "rx": "#cdd6e3",
        "tx": "#6fb4ff",
        "info": "#8b95a5",
        "error": "#ff7b6b",
        "timestamp": "#6b7686",
        "accent": "#4a9eff",
        "connected": "#3fb950",
        "disconnected": "#6b7686",
        "warning": "#d29922",
        "terminal_bg": "#0f1216",
    }


def direction_color(theme: Theme, direction: Direction) -> QColor:
    """Colour used to render one terminal chunk."""
    palette = theme_colors(theme)
    mapping = {
        Direction.RX: palette["rx"],
        Direction.TX: palette["tx"],
        Direction.INFO: palette["info"],
        Direction.ERROR: palette["error"],
    }
    return QColor(mapping.get(direction, palette["rx"]))


def stylesheet_path(theme: Theme) -> Path:
    return resource_dir() / "themes" / f"{theme.value}.qss"


def load_stylesheet(theme: Theme) -> str:
    """Read the QSS for ``theme``; an unreadable file degrades to no styling.

    ``@ICONS@`` is substituted with the absolute icons directory because QSS
    ``url()`` cannot be relative to the stylesheet, and the location differs
    between a source checkout and a PyInstaller bundle.
    """
    path = stylesheet_path(theme)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.error("Could not load theme %s from %s: %s", theme.value, path, exc)
        return ""
    icons = (resource_dir() / "icons").as_posix()
    return text.replace("@ICONS@", icons)


def apply_theme(app: QApplication, theme: Theme) -> None:
    """Apply the theme stylesheet to the whole application."""
    app.setStyleSheet(load_stylesheet(theme))


def resolve_monospace_family(preferred: str = "") -> str:
    """Return the best available monospace family.

    Falling back through a candidate list beats trusting ``StyleHint`` alone,
    which on Windows still tends to produce Courier New.
    """
    families = set(QFontDatabase.families())
    if preferred and preferred in families:
        return preferred
    for candidate in _MONO_CANDIDATES:
        if candidate in families:
            return candidate
    fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    return fallback.family()


def _available_fallbacks() -> list[str]:
    families = set(QFontDatabase.families())
    return [name for name in _FALLBACK_CANDIDATES if name in families]


def monospace_font(family: str = "", size: int = 10) -> QFont:
    """Build the terminal font, with fallbacks for glyphs it does not have.

    A serial device can send anything — Persian status text, a degree sign, a
    box-drawing frame — and no monospace font covers all of it. Listing the
    fallbacks explicitly means Qt reaches for a *good* face when the terminal
    font comes up short, instead of whatever the system picks first.
    """
    primary = resolve_monospace_family(family)
    font = QFont(primary)
    fallbacks = [name for name in _available_fallbacks() if name != primary]
    if fallbacks:
        font.setFamilies([primary, *fallbacks])
    font.setPointSize(max(6, int(size)))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    # Crisper stems at the small sizes a terminal is read at, and — on Qt 6.8+
    # — font substitution decided per script run rather than per character, so
    # a Persian word keeps one face instead of being stitched from several.
    strategy = QFont.StyleStrategy.PreferAntialias
    context_merging = getattr(QFont.StyleStrategy, "ContextFontMerging", None)
    if context_merging is not None:
        strategy |= context_merging
    font.setStyleStrategy(strategy)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font
