"""Applies the schema migration of plan section 1.1.

The migration rebuilds tables, so it has to run with foreign keys switched
off on its own connection. That is the opposite of what get_connection()
sets up for normal access, which is why this lives apart from the access
layer and opens its own connection.

`ensure_columns` and `ensure_indexes` are the exception and use the normal
access layer: they add, they never rebuild, and something that only adds
belongs inside the usual transaction with foreign keys on.
"""

import shutil
import sqlite3
from pathlib import Path

from .connection import get_connection

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


#: Die Indizes auf den Fremdschlüsseln, an denen die Kaskade entlangläuft.
#: Wortgleich mit denen in migrate_schema.sql — dort für eine vollständige
#: Migration, hier zum Nachrüsten beim Öffnen einer bestehenden Datenbank.
CASCADE_INDEXES = (
    ("timeTab_projectID", "timeTab (projectID)"),
    ("dataTab_timeID", "dataTab (timeID)"),
    ("dataTab_variableID", "dataTab (variableID)"),
    ("processTab_projectID", "processTab (projectID)"),
    ("logTab_projectID", "logTab (projectID)"),
    ("process_parameterTab_processID", "process_parameterTab (processID)"),
)


def ensure_indexes(db_path: Path | str) -> list[str]:
    """Nachrüsten, was SQLite für Fremdschlüssel nicht selbst anlegt.

    Ohne einen Index auf `dataTab.timeID` muss SQLite beim Löschen eines
    Projekts für **jede** gelöschte Zeitzeile die ganze `dataTab` durchsuchen.
    Gemessen an einer echten Arbeitsdatenbank mit 2 195 640 Datenzeilen dauert
    das Löschen eines Projekts mit 342 936 Messwerten Minuten; mit den Indizes
    0,58 s, und ihr Aufbau kostet einmalig 1,8 s.

    Das Template bringt sie mit. Wer schon eine Datenbank hat, bekäme sie sonst
    nur über einen vollständigen Migrationslauf — und das ist ein Neuaufbau
    aller Tabellen für etwas, das sechs additive Anweisungen sind. Deshalb
    läuft das hier beim Öffnen: geprüft wird über `sqlite_master`, gebaut wird
    nur, was fehlt, und wenn nichts fehlt, kostet es eine Abfrage.

    Gibt die Namen der Indizes zurück, die tatsächlich angelegt wurden.
    """
    with get_connection(db_path, readonly=True) as conn:
        present = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            )
        }
    missing = [(name, spec) for name, spec in CASCADE_INDEXES if name not in present]
    if not missing:
        return []

    with get_connection(db_path) as conn:
        for name, spec in missing:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {spec}")
    return [name for name, _ in missing]


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
