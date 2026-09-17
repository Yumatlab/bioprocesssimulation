"""Reclaiming the space a deleted project leaves behind.

SQLite does not shrink a file when rows are deleted; the pages are marked free
and reused for the next write. A database that has held a few long runs and
lost them is therefore mostly empty space — measured on a working copy here,
119 MB with not a single project left in it, and the productive MATLAB
database was 49.4 MB of which 98.9 % was free.

`VACUUM` rebuilds the file from its live content and gives the rest back to
the disk. It is the same thing `VACUUM INTO` did to produce the shipped
template (0.56 MB out of 49.4).

**This is the one place that does not use `get_connection`.** VACUUM cannot
run inside a transaction, and `get_connection` opens one — it is the whole
point of that helper. So this opens its own connection in autocommit mode,
and the rule it breaks is named here rather than quietly worked around.
"""

import sqlite3
import time
from pathlib import Path

from .connection import backup_database, get_connection


def database_size(db_path: Path | str) -> dict[str, int]:
    """What the file costs and how much of it is free space.

    `page_count` and `freelist_count` are pragmas, so this is two reads and
    no scan however large the file is.
    """
    path = Path(db_path)
    with get_connection(path, readonly=True) as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
    return {
        "bytes": path.stat().st_size if path.is_file() else 0,
        "page_size": page_size,
        "pages": pages,
        "free_pages": free,
        # What a rebuild would hand back, near enough to show somebody.
        "reclaimable": free * page_size,
    }


def vacuum_database(db_path: Path | str, *, backup: bool = True) -> dict:
    """Rebuild the file and give the free pages back. Returns what it saved.

    A backup is written first, through the sqlite3 backup API — VACUUM is
    atomic and rolls back like any other statement, but it rewrites every page
    of the file, and this project does not rewrite a database without a copy
    beside it.

    Nothing about the content changes: no project, no parameter, no measured
    value. What changes is how many pages the same content occupies.
    """
    path = Path(db_path)
    before = database_size(path)
    copy = backup_database(path, ".pre-vacuum.db") if backup else None

    started = time.perf_counter()
    # Its own connection, in autocommit mode: see the module docstring.
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("VACUUM")
        # **And a checkpoint, or nothing shrinks.** This database runs in WAL
        # mode, and there VACUUM writes the rebuilt pages into the
        # write-ahead log; the main file keeps its old size until the log is
        # folded back in and the file truncated. Measured without this line:
        # 78.88 MB before, 78.88 MB after, freelist empty — the work was done
        # and invisible.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    seconds = time.perf_counter() - started

    after = database_size(path)
    return {
        "before": before["bytes"],
        "after": after["bytes"],
        "saved": max(0, before["bytes"] - after["bytes"]),
        "free_pages_before": before["free_pages"],
        "seconds": seconds,
        "backup": copy,
    }


__all__ = ["database_size", "vacuum_database"]
