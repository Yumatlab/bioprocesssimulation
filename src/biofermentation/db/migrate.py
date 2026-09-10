"""Applies the schema migration of plan section 1.1.

The migration rebuilds tables, so it has to run with foreign keys switched
off on its own connection. That is the opposite of what get_connection()
sets up for normal access, which is why this lives apart from the access
layer and opens its own connection.
"""

import shutil
import sqlite3
from pathlib import Path

MIGRATION_SQL = Path(__file__).with_name("migrate_schema.sql")

#: Columns logTab is missing, as name -> declaration.
#:
#: The application holds five things per log entry — timestamp, event type,
#: message, project and process time — and the table has room for three of
#: them. The event type ended up folded into the message as a "[...]" prefix
#: and the process time was dropped, so a reloaded project could not put its
#: own log back together.
#:
#: Added here and not in migrate_schema.sql because ALTER TABLE ADD COLUMN
#: has no IF NOT EXISTS in SQLite and a .sql script cannot branch. Rebuilding
#: the table the way the script does for the other defects would drop these
#: two columns again on every rerun, taking the entries written since with
#: them.
#:
#: Existing rows get NULL in both. Their text is left exactly as it is —
#: load_project_log() reads the "[...]" prefix back out for them. A schema
#: migration should not rewrite stored data.
LOG_COLUMNS = {
    "event_type": "TEXT",
    "process_time": "REAL",
}


def _add_missing_columns(conn: sqlite3.Connection) -> list[str]:
    """The additive half of the migration. Returns the columns it added."""
    present = {row[1] for row in conn.execute("PRAGMA table_info(logTab)")}
    added = []
    for name, declaration in LOG_COLUMNS.items():
        if name not in present:
            conn.execute(f"ALTER TABLE logTab ADD COLUMN {name} {declaration}")
            added.append(name)
    return added


def ensure_columns(db_path: Path | str) -> list[str]:
    """Add the columns of LOG_COLUMNS if a database predates them.

    The application calls this at start. A user's database is a copy of the
    template taken whenever they first ran the program, so it can be older
    than the schema the code expects — the full migration would be too heavy
    for every launch, but this is two PRAGMA reads and, once, two ALTERs.
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        return _add_missing_columns(conn)
    finally:
        conn.close()


def apply_migration(db_path: Path | str, *, backup: bool = True) -> Path | None:
    """Run migrate_schema.sql against db_path.

    Copies the database to <name>.pre-migration.db first unless backup is
    False, and returns the path of that copy. Raises if the migration leaves
    a foreign key violation behind; the database is untouched in that case,
    because the rebuild itself runs inside a single transaction.

    Runs the script and then adds the logTab columns of LOG_COLUMNS, which
    cannot be expressed idempotently in SQL.
    """
    db_path = Path(db_path)
    backup_path = None
    if backup:
        backup_path = db_path.with_suffix(".pre-migration.db")
        shutil.copy(db_path, backup_path)

    script = MIGRATION_SQL.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.executescript(script)
        _add_missing_columns(conn)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    if violations:
        raise RuntimeError(f"migration left foreign key violations: {violations}")
    return backup_path
