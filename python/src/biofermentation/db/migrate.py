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


#: The indexes on the foreign keys the cascade walks along. Word for word the
#: ones in migrate_schema.sql — there for a full migration, here to add them
#: to a database that already exists, when it is opened.
CASCADE_INDEXES = (
    ("timeTab_projectID", "timeTab (projectID)"),
    ("dataTab_timeID", "dataTab (timeID)"),
    ("dataTab_variableID", "dataTab (variableID)"),
    ("processTab_projectID", "processTab (projectID)"),
    ("logTab_projectID", "logTab (projectID)"),
    ("process_parameterTab_processID", "process_parameterTab (processID)"),
)


def ensure_indexes(db_path: Path | str) -> list[str]:
    """Add what SQLite does not create for a foreign key by itself.

    Without an index on `dataTab.timeID`, deleting a project makes SQLite scan
    the whole `dataTab` for **every** deleted time row. Measured on a real
    working database with 2 195 640 data rows, deleting a project of 342 936
    measured values takes minutes; with the indexes 0.58 s, and building them
    costs 1.8 s once.

    The template ships with them. A database that already exists would
    otherwise need a full migration run — a rebuild of every table for what
    are six additive statements. So this runs when the database is opened:
    `sqlite_master` is asked, only what is missing is built, and when nothing
    is missing it costs one query.

    Returns the names of the indexes that were actually created.
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


#: The tables of the process templates (Projektplan_Prozessvorlagen.md, phase 1),
#: as name -> statement. A template belongs to a model, a template phase to a
#: template, a template parameter to a template phase; each cascades with its
#: parent. No status and no time columns: a template is a plan, not a run.
#:
#: Unlike processTab, start_operatorID points at process_operatorTab — the
#: fault noted under "Offen aus Phase 1" is not copied into new tables.
#:
#: Kept here and only here. apply_migration and the application start both
#: call ensure_template_tables, so the statements exist once and cannot drift.
TEMPLATE_TABLES = {
    "process_templateTab": """
        CREATE TABLE IF NOT EXISTS process_templateTab (
            templateID   INTEGER PRIMARY KEY AUTOINCREMENT,
            modelID      INTEGER NOT NULL
                         REFERENCES modelTab (modelID) ON DELETE CASCADE ON UPDATE CASCADE,
            name         TEXT    NOT NULL,
            description  TEXT,
            author       TEXT,
            created_on   TEXT,
            UNIQUE (modelID, name)
        )""",
    "process_template_phaseTab": """
        CREATE TABLE IF NOT EXISTS process_template_phaseTab (
            template_phaseID INTEGER PRIMARY KEY AUTOINCREMENT,
            templateID       INTEGER NOT NULL
                             REFERENCES process_templateTab (templateID)
                             ON DELETE CASCADE ON UPDATE CASCADE,
            position         INTEGER NOT NULL,
            process_typeID   INTEGER NOT NULL REFERENCES process_typeTab (process_typeID),
            name             TEXT,
            reservoirID      INTEGER,
            start_typeID     INTEGER REFERENCES process_conditiontypeTab (process_conditiontypeID),
            start_variableID INTEGER REFERENCES variableTab (variableID),
            start_operatorID INTEGER REFERENCES process_operatorTab (process_operatorID),
            start_value      REAL,
            end_typeID       INTEGER REFERENCES process_conditiontypeTab (process_conditiontypeID),
            end_variableID   INTEGER REFERENCES variableTab (variableID),
            end_operatorID   INTEGER REFERENCES process_operatorTab (process_operatorID),
            end_value        REAL,
            UNIQUE (templateID, position)
        )""",
    "process_template_parameterTab": """
        CREATE TABLE IF NOT EXISTS process_template_parameterTab (
            template_parameterID INTEGER PRIMARY KEY AUTOINCREMENT,
            template_phaseID     INTEGER NOT NULL
                                 REFERENCES process_template_phaseTab (template_phaseID)
                                 ON DELETE CASCADE ON UPDATE CASCADE,
            parameterID          INTEGER NOT NULL
                                 REFERENCES parameterTab (parameterID)
                                 ON DELETE CASCADE ON UPDATE CASCADE,
            value                REAL NOT NULL,
            UNIQUE (template_phaseID, parameterID)
        )""",
}

#: One index per foreign key a deletion cascades along (Altlast 8).
TEMPLATE_INDEXES = (
    ("process_templateTab_modelID", "process_templateTab (modelID)"),
    ("process_template_phaseTab_templateID", "process_template_phaseTab (templateID)"),
    ("process_template_parameterTab_phaseID", "process_template_parameterTab (template_phaseID)"),
)


def _create_template_tables(conn: sqlite3.Connection) -> list[str]:
    """Create what is missing of TEMPLATE_TABLES and their indexes."""
    present = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    created = []
    for name, statement in TEMPLATE_TABLES.items():
        if name not in present:
            conn.execute(statement)
            created.append(name)
    for name, spec in TEMPLATE_INDEXES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {spec}")
    return created


def ensure_template_tables(db_path: Path | str) -> list[str]:
    """Give a database the process template tables if it predates them.

    Called at application start, like ensure_indexes: a user's database is a
    copy of the template from their first start. One read when nothing is
    missing; otherwise three CREATE TABLE in one transaction, once. Returns
    the tables that were created.
    """
    with get_connection(db_path, readonly=True) as conn:
        present = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    if all(name in present for name in TEMPLATE_TABLES):
        return []
    with get_connection(db_path) as conn:
        return _create_template_tables(conn)


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
        _create_template_tables(conn)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    if violations:
        raise RuntimeError(f"migration left foreign key violations: {violations}")
    return backup_path
