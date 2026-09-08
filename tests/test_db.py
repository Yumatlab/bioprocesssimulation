"""Database layer tests.

Covers the bundled template database and the schema migration of plan
section 1.1. The load/save round-trip tests belong to plan section 1.4.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from biofermentation.db.migrate import MIGRATION_SQL, apply_migration

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"

# Tables the MATLAB application relies on; see CLAUDE.md of the MATLAB project.
EXPECTED_TABLES = {
    "projectTab",
    "project_parameterTab",
    "processTab",
    "process_parameterTab",
    "organismTab",
    "modelTab",
    "model_parameterTab",
    "variableTab",
    "variable_handlingTab",
    "parameterTab",
    "categoryTab",
    "timeTab",
    "dataTab",
    "plot_templateTab",
    "plot_variableTab",
    "logTab",
}


def _readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _schema(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    """A writable copy of the template database. Never test on the original."""
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


# --------------------------------------------------------------- template --


def test_template_database_is_bundled():
    assert TEMPLATE_DB.is_file(), f"template database missing at {TEMPLATE_DB}"


def test_template_database_passes_integrity_check():
    with _readonly(TEMPLATE_DB) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_template_database_has_expected_tables():
    with _readonly(TEMPLATE_DB) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        present = {row[0] for row in rows}
    assert present >= EXPECTED_TABLES, f"missing tables: {sorted(EXPECTED_TABLES - present)}"


def test_template_database_knows_both_organisms():
    with _readonly(TEMPLATE_DB) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM organismTab")}
    assert names == {"Escherichia coli", "Pichia pastoris"}


# ------------------------------------------------- migration, plan 1.1 --
# Until the migration was applied, end_typeID referenced process_typeTab while
# holding process_conditiontypeTab ids, which produced twelve violations. The
# template ships migrated, so this is now a plain assertion.


def test_template_database_has_no_foreign_key_violations():
    with _readonly(TEMPLATE_DB) as conn:
        violations = list(conn.execute("PRAGMA foreign_key_check"))
    assert violations == [], violations


def test_no_foreign_key_carries_match_simple():
    with _readonly(TEMPLATE_DB) as conn:
        offenders = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE sql LIKE '%MATCH SIMPLE%'"
            )
        ]
    assert offenders == [], offenders


def test_process_start_and_end_type_reference_condition_types():
    with _readonly(TEMPLATE_DB) as conn:
        targets = {row[3]: row[2] for row in conn.execute("PRAGMA foreign_key_list(processTab)")}
    assert targets["start_typeID"] == "process_conditiontypeTab"
    assert targets["end_typeID"] == "process_conditiontypeTab"


def test_stored_condition_types_exist_in_condition_type_table():
    with _readonly(TEMPLATE_DB) as conn:
        starts = {row[0] for row in conn.execute("SELECT DISTINCT start_typeID FROM processTab")}
        ends = {row[0] for row in conn.execute("SELECT DISTINCT end_typeID FROM processTab")}
        known = {
            row[0]
            for row in conn.execute("SELECT process_conditiontypeID FROM process_conditiontypeTab")
        }
    assert starts <= known and ends <= known
    # The values that made the old foreign key wrong: 6 and 7 are end
    # conditions, and process_typeTab only reaches id 5.
    assert ends == {6, 7}


def test_project_parameter_pair_is_unique(db_copy: Path):
    with sqlite3.connect(db_copy) as conn:
        projectID, parameterID = conn.execute(
            "SELECT projectID, parameterID FROM project_parameterTab LIMIT 1"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO project_parameterTab (projectID, parameterID, value) VALUES (?, ?, ?)",
                (projectID, parameterID, 1.0),
            )


def test_cascade_delete_reaches_project_parameters(db_copy: Path):
    """The symptom defect 1 was blamed for: deleting a project must clear its rows."""
    with sqlite3.connect(db_copy) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        projectID = conn.execute(
            "SELECT projectID FROM project_parameterTab GROUP BY projectID "
            "ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()[0]
        before = conn.execute(
            "SELECT COUNT(*) FROM project_parameterTab WHERE projectID = ?", (projectID,)
        ).fetchone()[0]
        assert before > 0
        conn.execute("DELETE FROM projectTab WHERE projectID = ?", (projectID,))
        after = conn.execute(
            "SELECT COUNT(*) FROM project_parameterTab WHERE projectID = ?", (projectID,)
        ).fetchone()[0]
    assert after == 0


def test_migration_script_is_shipped():
    assert MIGRATION_SQL.is_file(), f"migration script missing at {MIGRATION_SQL}"


def test_migration_is_idempotent(db_copy: Path):
    """Rerunning it on an already migrated database must change nothing."""
    with _readonly(db_copy) as conn:
        before_schema = _schema(conn)
        before_counts = _row_counts(conn)
        before_seq = conn.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name").fetchall()

    apply_migration(db_copy, backup=False)

    with _readonly(db_copy) as conn:
        assert _schema(conn) == before_schema
        assert _row_counts(conn) == before_counts
        after_seq = conn.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name")
        assert after_seq.fetchall() == before_seq
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_migration_writes_a_backup_by_default(db_copy: Path):
    backup_path = apply_migration(db_copy)
    assert backup_path is not None
    assert backup_path.is_file()
    assert backup_path != db_copy


def test_migration_preserves_autoincrement_counters(db_copy: Path):
    """The counters run far ahead of MAX(id); rebuilding must not reset them."""
    with _readonly(db_copy) as conn:
        seq = dict(conn.execute("SELECT name, seq FROM sqlite_sequence"))
    assert seq["dataTab"] > 1_000_000, "expected the template's runaway dataTab counter"

    apply_migration(db_copy, backup=False)

    with _readonly(db_copy) as conn:
        assert dict(conn.execute("SELECT name, seq FROM sqlite_sequence")) == seq


def test_migration_collapses_duplicate_project_parameters(db_copy: Path):
    """Rebuild the pre-migration table, plant a duplicate, migrate, check the winner."""
    with sqlite3.connect(db_copy, isolation_level=None) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            PRAGMA legacy_alter_table = ON;
            CREATE TABLE _legacy (
                project_parameterID INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE NOT NULL,
                projectID INTEGER NOT NULL REFERENCES projectTab (projectID)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                parameterID INTEGER REFERENCES parameterTab (parameterID),
                value REAL,
                description TEXT);
            INSERT INTO _legacy SELECT * FROM project_parameterTab;
            DROP TABLE project_parameterTab;
            ALTER TABLE _legacy RENAME TO project_parameterTab;
            """
        )
        projectID, parameterID = conn.execute(
            "SELECT projectID, parameterID FROM project_parameterTab LIMIT 1"
        ).fetchone()
        newest_id = (
            conn.execute("SELECT MAX(project_parameterID) FROM project_parameterTab").fetchone()[0]
            + 1
        )
        conn.execute(
            "INSERT INTO project_parameterTab (project_parameterID, projectID, parameterID, value)"
            " VALUES (?, ?, ?, ?)",
            (newest_id, projectID, parameterID, 42.0),
        )
        total_before = conn.execute("SELECT COUNT(*) FROM project_parameterTab").fetchone()[0]

    apply_migration(db_copy, backup=False)

    with _readonly(db_copy) as conn:
        rows = conn.execute(
            "SELECT project_parameterID, value FROM project_parameterTab"
            " WHERE projectID = ? AND parameterID = ?",
            (projectID, parameterID),
        ).fetchall()
        total_after = conn.execute("SELECT COUNT(*) FROM project_parameterTab").fetchone()[0]
    assert rows == [(newest_id, 42.0)], "the most recently written row must win"
    assert total_after == total_before - 1


def test_biostat_b_has_its_own_instrumentation_values():
    """Defect 4: the BIOSTAT B used to carry the BIOSTAT ED's figures.

    Values from the spreadsheet, sheet 'bioreactors', column BBI_ED. This is
    the one place where the spreadsheet outranks the database.
    """
    expected = {
        "FnAIRmax": 10.0,
        "FnGmax": 17.0,
        "FT1max": 1.0,
        "FT2max": 1.0,
        "mdotCmax": 150.0,
        "mdotHmax": 6.0,
        "PHmax": 2000.0,
    }
    with _readonly(TEMPLATE_DB) as conn:
        actual = dict(
            conn.execute(
                "SELECT p.name, d.value FROM default_bioreactorTab d "
                "JOIN parameterTab p USING (parameterID) "
                "WHERE d.bioreactorID = 2 AND p.name IN "
                "('FnAIRmax','FnGmax','FT1max','FT2max','mdotCmax','mdotHmax','PHmax')"
            )
        )
    assert actual == expected


def test_both_bioreactors_are_fully_populated():
    """Eight rows were missing for the BIOSTAT B; both must now be complete."""
    with _readonly(TEMPLATE_DB) as conn:
        counts = dict(
            conn.execute(
                "SELECT bioreactorID, COUNT(*) FROM default_bioreactorTab GROUP BY bioreactorID"
            )
        )
        missing = conn.execute(
            "SELECT COUNT(*) FROM default_bioreactorTab a "
            " WHERE a.bioreactorID = 1 AND NOT EXISTS ("
            "   SELECT 1 FROM default_bioreactorTab b"
            "    WHERE b.bioreactorID = 2 AND b.parameterID = a.parameterID)"
        ).fetchone()[0]
    assert counts == {1: 60, 2: 60}
    assert missing == 0
