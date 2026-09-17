"""The window that stands there while a project is being deleted.

Deleting a project with a couple of hours of process data used to take long
enough that the window looked dead. With the indexes on the cascade it takes
a fraction of a second on a migrated database — but a database that has not
been migrated yet still takes half a minute, and so does a very long run.

**The bar does not fill up, and no bar could.** The deletion is one SQLite
statement: the cascade runs inside it, SQLite counts virtual-machine
instructions rather than rows, and there is no total to divide by. Showing a
percentage would mean deleting in chunks — several transactions — which is
exactly the mistake that destroyed the MATLAB database. So this says how much
there is to delete, in rows, and then keeps moving until it is done.

What it does have is a **Cancel that works**, and it works *because* of the
one transaction: SQLite aborts the statement, nothing is committed, and the
database is exactly as it was. Measured on a project with 201 656 data rows —
after an abort all 201 656 were still there and `integrity_check` was clean.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from ...db import DeletionCancelledError, delete_project
from ...db.connection import get_connection

#: Below this the dialog never appears. A deletion that takes a quarter of a
#: second should not flash a window at somebody — on an indexed database that
#: is the normal case (0,28 s measured over 201 656 rows).
SHOW_AFTER_MS = 400


def project_size(db_path: Path | str, project_id: int) -> int:
    """How many measured values hang off this project.

    Read before the deletion starts, because it is the one number that can
    honestly be shown: not how far along we are, but how much there is.
    """
    with get_connection(db_path, readonly=True) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM dataTab WHERE timeID IN "
            "(SELECT timeID FROM timeTab WHERE projectID = ?)",
            (project_id,),
        ).fetchone()[0]


def delete_with_progress(
    parent: QWidget | None, db_path: Path | str, project_id: int, name: str = ""
) -> dict[str, int] | None:
    """Delete a project, with a window that stays alive while it happens.

    Returns what was deleted, or None if the user cancelled — in which case
    nothing was deleted at all.
    """
    try:
        rows = project_size(db_path, project_id)
    except Exception:  # a database that will not even count
        rows = 0

    label = f"{name or 'Projekt'} wird gelöscht …"
    if rows:
        # Punkt als Tausendertrennzeichen, von Hand. "{:n}" richtet sich nach
        # der Locale des Prozesses, und die steht ohne setlocale auf "C" —
        # dann steht dort 201656 statt 201.656.
        label += f"\n{rows:,} Messwerte".replace(",", ".")
    dialog = QProgressDialog(label, "Abbrechen", 0, 0, parent)
    dialog.setWindowTitle("Projekt löschen")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    # Not shown for a deletion that is over before anyone could read it.
    dialog.setMinimumDuration(SHOW_AFTER_MS)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    def heartbeat() -> int:
        # The dialog is modal, so this cannot start a second database
        # operation; it repaints the window and reads the Cancel button.
        QApplication.processEvents()
        return 1 if dialog.wasCanceled() else 0

    try:
        return delete_project(db_path, project_id, on_progress=heartbeat)
    except DeletionCancelledError:
        return None
    finally:
        dialog.close()


__all__ = ["SHOW_AFTER_MS", "delete_with_progress", "project_size"]
