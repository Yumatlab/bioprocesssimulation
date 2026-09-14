"""Tests for the CSV default data set.

The point of the set is that an emptied database can be rebuilt from it, so
that is what gets tested: wipe, reload, compare against the template.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from biofermentation.db.seed import (
    DEFAULT_TABLES,
    DEFAULTS_DIR,
    export_defaults,
    load_defaults,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"


def _dump(conn: sqlite3.Connection, table: str) -> list[tuple]:
    """Rows plus the storage class of every field.

    typeof() is part of the comparison on purpose: a column without affinity,
    such as default_plot_variableTab.selected_variable, silently accepts the
    string '1' where the template holds the integer 1.
    """
    types = ", ".join(
        f'typeof("{row[1]}")' for row in conn.execute(f'PRAGMA table_info("{table}")')
    )
    return conn.execute(f'SELECT *, {types} FROM "{table}" ORDER BY 1').fetchall()


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """A copy of the template with projects and all reference data removed."""
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    conn = sqlite3.connect(target, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM projectTab")
    for table in reversed(DEFAULT_TABLES):
        conn.execute(f'DELETE FROM "{table}"')
    conn.close()
    return target


def test_every_default_table_has_a_csv():
    missing = [t for t in DEFAULT_TABLES if not (DEFAULTS_DIR / f"{t}.csv").is_file()]
    assert missing == [], missing


def test_default_tables_exist_in_the_database():
    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        present = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert set(DEFAULT_TABLES) <= present


def test_project_tables_are_not_part_of_the_default_set():
    """Project data is user data. Shipping it as a default would restore
    somebody else's projects into an empty installation."""
    project_tables = {
        "projectTab",
        "project_parameterTab",
        "processTab",
        "process_parameterTab",
        "timeTab",
        "dataTab",
        "logTab",
    }
    assert project_tables.isdisjoint(DEFAULT_TABLES)


def test_wiped_database_is_restored_exactly(empty_db: Path):
    with sqlite3.connect(empty_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM parameterTab").fetchone()[0] == 0

    counts = load_defaults(empty_db)
    assert sum(counts.values()) > 2000

    with (
        sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as expected,
        sqlite3.connect(f"file:{empty_db}?mode=ro", uri=True) as actual,
    ):
        for table in DEFAULT_TABLES:
            assert _dump(actual, table) == _dump(expected, table), table
        assert list(actual.execute("PRAGMA foreign_key_check")) == []


def test_load_refuses_to_run_while_projects_exist(tmp_path: Path):
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    with pytest.raises(RuntimeError, match="projects in the database"):
        load_defaults(target)


def test_shipped_csvs_match_the_template(tmp_path: Path):
    """The files under resources/defaults must be the current export."""
    export_defaults(TEMPLATE_DB, tmp_path)
    for table in DEFAULT_TABLES:
        fresh = (tmp_path / f"{table}.csv").read_text(encoding="utf-8")
        shipped = (DEFAULTS_DIR / f"{table}.csv").read_text(encoding="utf-8")
        assert fresh == shipped, f"{table}.csv is stale, rerun export_defaults()"


def test_null_and_empty_string_survive_the_round_trip(empty_db: Path):
    """variableTab.description holds 61 empty strings and 3 NULLs.

    Plain CSV cannot tell the two apart, which is what the \\N marker is for.
    """
    load_defaults(empty_db)
    with sqlite3.connect(f"file:{empty_db}?mode=ro", uri=True) as conn:
        empty = conn.execute("SELECT COUNT(*) FROM variableTab WHERE description = ''").fetchone()[
            0
        ]
        null = conn.execute(
            "SELECT COUNT(*) FROM variableTab WHERE description IS NULL"
        ).fetchone()[0]
    assert (empty, null) == (61, 3)
