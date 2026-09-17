"""Giving the space of deleted projects back to the disk.

A deletion does not shrink the file: SQLite marks the pages free and keeps
them for the next write. After a term of long runs that have since been
deleted, most of the file is empty space — 119 MB with no project left in it,
on a working copy here.

The window this puts in front of the operator says what will happen in
numbers, because "compact the database" means nothing on its own and the two
questions somebody actually has are *what does it change* (nothing in the
content) and *how long does it take* (seconds, and it says so).
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from ...db import database_size, vacuum_database

#: Below this the busy window never appears — a rebuild of a small database is
#: over before anybody could read it.
SHOW_AFTER_MS = 400


def megabytes(count: int) -> str:
    return f"{count / 1024 / 1024:.2f} MB"


def describe(db_path: Path | str) -> str:
    """What the file costs right now, for the question and for the menu."""
    size = database_size(db_path)
    if not size["reclaimable"]:
        return f"{megabytes(size['bytes'])}, nothing to reclaim"
    return (
        f"{megabytes(size['bytes'])}, about {megabytes(size['reclaimable'])} of it "
        "unused space from deleted projects"
    )


def compact_with_progress(parent: QWidget | None, db_path: Path | str) -> dict | None:
    """Ask, rebuild the file, and say what it gave back. None if declined."""
    size = database_size(db_path)
    answer = QMessageBox.question(
        parent,
        "Compact Database",
        f"<b>Rebuild the database file to give unused space back to the disk?</b>"
        f"<p>The file is {megabytes(size['bytes'])} and about "
        f"{megabytes(size['reclaimable'])} of that is space that deleted projects "
        f"left behind. SQLite keeps those pages for its own later use rather than "
        f"returning them, so the file never shrinks on its own.</p>"
        f"<p><b>Nothing in the database changes</b> — no project, no parameter, no "
        f"measured value. Only the number of pages the same content sits on.</p>"
        f"<p>It takes a few seconds, the application waits for it, and a copy of "
        f"the file is written next to it first.</p>",
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
        QMessageBox.StandardButton.Cancel,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return None

    dialog = QProgressDialog("Rebuilding the database file …", "", 0, 0, parent)
    dialog.setWindowTitle("Compact Database")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setCancelButton(None)  # an interrupted VACUUM would only be a no-op
    dialog.setMinimumDuration(SHOW_AFTER_MS)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    QApplication.processEvents()

    try:
        return vacuum_database(db_path)
    finally:
        dialog.close()


def report(parent: QWidget | None, result: dict) -> None:
    """The one sentence worth reading afterwards: how much came back."""
    QMessageBox.information(
        parent,
        "Compact Database",
        f"{megabytes(result['before'])} → {megabytes(result['after'])}, "
        f"{megabytes(result['saved'])} given back in {result['seconds']:.1f} s.\n\n"
        f"The previous file is beside it as {Path(result['backup']).name}."
        if result.get("backup")
        else f"{megabytes(result['saved'])} given back.",
    )


__all__ = ["SHOW_AFTER_MS", "compact_with_progress", "describe", "megabytes", "report"]
