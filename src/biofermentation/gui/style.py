"""Loading the stylesheet and fixing the palette (plan section 5.1).

Qt Style Sheets are CSS for widgets, so the whole look of the application is
a text file. The bundled one is resources/styles/default.qss; a style.qss
next to the database replaces it, which lets somebody change colours,
spacing or fonts without a Python file or a rebuild.

The palette is not left to the system. A style sheet only sets what it names,
and everything it does not name comes from the platform palette — so on a Mac
in dark mode the application drew its own light backgrounds and let macOS
supply white text on top of them. Half the window was unreadable.

The application therefore brings its own light palette and asks for the
Fusion style, which honours a palette on every platform. The look is then the
same on Windows and macOS, in light mode and in dark mode, and a user
stylesheet is still the last word.
"""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette

from ..resources import STYLES_DIR, default_database

BUNDLED_STYLE = STYLES_DIR / "default.qss"
USER_STYLE_NAME = "style.qss"

#: The light palette the application draws itself in, whatever the system
#: theme is. Keep in step with the colours in default.qss.
PALETTE_COLORS = {
    QPalette.ColorRole.Window: "#f2f2f2",
    QPalette.ColorRole.WindowText: "#1a1a1a",
    QPalette.ColorRole.Base: "#ffffff",
    QPalette.ColorRole.AlternateBase: "#f7f7f7",
    QPalette.ColorRole.Text: "#1a1a1a",
    QPalette.ColorRole.Button: "#f0f0f0",
    QPalette.ColorRole.ButtonText: "#1a1a1a",
    QPalette.ColorRole.ToolTipBase: "#ffffe1",
    QPalette.ColorRole.ToolTipText: "#1a1a1a",
    QPalette.ColorRole.PlaceholderText: "#8a8a8a",
    QPalette.ColorRole.BrightText: "#c0392b",
    QPalette.ColorRole.Link: "#2f7fd1",
    QPalette.ColorRole.Highlight: "#2f7fd1",
    QPalette.ColorRole.HighlightedText: "#ffffff",
}

#: What a disabled widget is drawn in. Without these the disabled colours
#: come from the system palette again, which is where dark mode got back in.
DISABLED_COLORS = {
    QPalette.ColorRole.WindowText: "#9a9a9a",
    QPalette.ColorRole.Text: "#9a9a9a",
    QPalette.ColorRole.ButtonText: "#9a9a9a",
    QPalette.ColorRole.Highlight: "#d0d0d0",
    QPalette.ColorRole.HighlightedText: "#6a6a6a",
}


def light_palette() -> QPalette:
    """The application's own palette, independent of the system theme."""
    palette = QPalette()
    for role, color in PALETTE_COLORS.items():
        palette.setColor(role, QColor(color))
    for role, color in DISABLED_COLORS.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return palette


def apply_theme(app) -> None:
    """Style, palette and stylesheet — in that order, because each overrides
    the one before it."""
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    app.setStyleSheet(load_stylesheet())


def user_style_path() -> Path:
    """Where a user's own stylesheet goes: next to their database."""
    return default_database(create=False).parent / USER_STYLE_NAME


def load_stylesheet() -> str:
    """The user's stylesheet if there is one, otherwise the bundled default."""
    user = user_style_path()
    if user.is_file():
        return user.read_text(encoding="utf-8")
    if BUNDLED_STYLE.is_file():
        return BUNDLED_STYLE.read_text(encoding="utf-8")
    return ""
