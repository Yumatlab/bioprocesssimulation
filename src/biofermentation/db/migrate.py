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


def apply_migration(db_path: Path | str, *, backup: bool = True) -> Path | None:
    """Run migrate_schema.sql against db_path.

    Copies the database to <name>.pre-migration.db first unless backup is
    False, and returns the path of that copy. Raises if the migration leaves
    a foreign key violation behind; the database is untouched in that case,
    because the rebuild itself runs inside a single transaction.
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
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    if violations:
        raise RuntimeError(f"migration left foreign key violations: {violations}")
    return backup_path
