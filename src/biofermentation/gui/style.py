"""Loading the stylesheet (plan section 5.1).

Qt Style Sheets are CSS for widgets, so the whole look of the application is
a text file. The bundled one is resources/styles/default.qss; a style.qss
next to the database replaces it, which lets somebody change colours,
spacing or fonts without a Python file or a rebuild.
"""

from pathlib import Path

from ..resources import STYLES_DIR, default_database

BUNDLED_STYLE = STYLES_DIR / "default.qss"
USER_STYLE_NAME = "style.qss"


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
