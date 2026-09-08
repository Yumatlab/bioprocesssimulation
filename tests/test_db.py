"""Database layer tests.

Phase 0 covers only the bundled template database. The load/save round-trip
tests belong to phase 1 (plan 1.4) and are marked as expected-missing until
then.
"""

import sqlite3
from pathlib import Path

import pytest

TEMPLATE_DB = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "biofermentation"
    / "resources"
    / "SimulationAppDB_template.db"
)

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


def test_template_database_is_bundled():
    assert TEMPLATE_DB.is_file(), f"template database missing at {TEMPLATE_DB}"


def test_template_database_passes_integrity_check():
    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_template_database_has_expected_tables():
    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        present = {row[0] for row in rows}
    assert present >= EXPECTED_TABLES, f"missing tables: {sorted(EXPECTED_TABLES - present)}"


def test_template_database_knows_both_organisms():
    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM organismTab")}
    assert names == {"Escherichia coli", "Pichia pastoris"}


@pytest.mark.xfail(
    reason="processTab.end_typeID references process_typeTab but holds "
    "process_conditiontypeTab ids; fixed by the schema migration in phase 1.1",
    strict=True,
)
def test_template_database_has_no_foreign_key_violations():
    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        violations = list(conn.execute("PRAGMA foreign_key_check"))
    assert violations == [], violations
