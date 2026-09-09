"""Bundled resources and the database the installation works on.

The template that ships with the package is read-only — inside a PyInstaller
bundle it is literally so (plan section 7). The application therefore works on
a copy in the user's own data directory, created on first start.
"""

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Where the bundled resources are, source tree or frozen build alike.

    PyInstaller unpacks its data files into a temporary directory and puts
    the path in sys._MEIPASS. The package modules themselves report a
    __file__ inside that directory too, so both branches usually agree — but
    only usually, and a resource that cannot be found in a frozen build is
    found after the release rather than before it.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is not None:
        return Path(bundle) / "biofermentation" / "resources"
    return Path(__file__).resolve().parent


IS_FROZEN = getattr(sys, "frozen", False)
HERE = resource_root()
TEMPLATE_DB = HERE / "SimulationAppDB_template.db"
DEFAULTS_DIR = HERE / "defaults"
STYLES_DIR = HERE / "styles"

APPLICATION_NAME = "Biofermentation Simulation"
DATABASE_NAME = "SimulationAppDB.db"

# Overrides the location, for tests and for running two installations side by
# side without them sharing a database.
DATABASE_ENV = "BIOFERMENTATION_DB"


def user_data_dir() -> Path:
    """Where this installation keeps its database, per platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APPLICATION_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APPLICATION_NAME
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "biofermentation"


def default_database(*, create: bool = True) -> Path:
    """The database to work on, copied from the template on first start.

    BIOFERMENTATION_DB overrides the path. The copy goes through SQLite's own
    backup API rather than the file system, so a template that still has a
    write-ahead log is copied whole — the lesson of the four orphaned .db-wal
    files in the MATLAB project.
    """
    override = os.environ.get(DATABASE_ENV)
    target = Path(override) if override else user_data_dir() / DATABASE_NAME

    if create and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_template(target)
    return target


def copy_template(target: Path | str) -> Path:
    """Write a fresh copy of the bundled template to target."""
    import sqlite3

    target = Path(target)
    if not TEMPLATE_DB.is_file():
        raise FileNotFoundError(f"the bundled template is missing at {TEMPLATE_DB}")

    source = sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def bundled_files() -> dict[str, Path]:
    """Everything the application needs at runtime and does not compute.

    Used by the packaging test, so a resource that stops being collected is
    noticed by pytest rather than by a user opening the release.
    """
    return {
        "template database": TEMPLATE_DB,
        "default data set": DEFAULTS_DIR,
        "stylesheet": STYLES_DIR / "default.qss",
    }


__all__ = [
    "DATABASE_ENV",
    "DEFAULTS_DIR",
    "IS_FROZEN",
    "STYLES_DIR",
    "TEMPLATE_DB",
    "bundled_files",
    "copy_template",
    "default_database",
    "resource_root",
    "user_data_dir",
]
