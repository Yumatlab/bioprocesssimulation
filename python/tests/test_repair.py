"""Data repair of the damage the MATLAB create and delete paths left.

Not schema repair — that is migrate_schema.sql. These are rows that a
half-finished transaction left in a state the application cannot use.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from biofermentation.db.repair import (
    find_broken_projects,
    find_corrupted_project_parameters,
    find_duplicate_model_defaults,
    repair,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"

# Projects whose parameters are missing entirely, plus 732 with 42 of 250.
BROKEN = {707, 708, 709, 711, 712, 714, 715, 732, 733}
# Projects that are complete and must survive any repair.
INTACT = {519, 520, 716, 725, 727}


#: The three parameters the strays sat on, with the parameter whose value and
#: description they carried and the value the project should have had.
STRAYS = (
    ("yXpOgr", "kS2tox", "Methanol toxicity concentration [5%v/v]", 40.0, 1.773),
    ("yCpO", "kappatox", "Slope of toxicity turn on function", 15.0, 1.375),
    ("qOpXm", "qXpXtox", "Methanol death rate", 0.5, 0.0117),
)


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    """A copy of the template with the parameter damage put back.

    The template carried it until it was repaired. A test that relies on a
    fixture being broken stops testing anything the moment the fixture is
    fixed, so the damage is made here instead — from the description of it in
    the module docstring of db/repair.py, not from whatever happens to be in
    the file.
    """
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)

    with sqlite3.connect(target) as conn:
        pichia = conn.execute(
            "SELECT organismID FROM organismTab WHERE name = 'Pichia pastoris'"
        ).fetchone()[0]
        for name, _, description, value, _ in STRAYS:
            parameter = conn.execute(
                "SELECT parameterID FROM parameterTab WHERE name = ?", (name,)
            ).fetchone()[0]
            # The misfiled second row, as MATLAB left it.
            conn.execute(
                "INSERT INTO default_modelTab (organismID, parameterID, value, description) "
                "VALUES (?, ?, ?, ?)",
                (pichia, parameter, value, description),
            )
            # And the value it carried into the projects created from it.
            conn.execute(
                """
                UPDATE project_parameterTab SET value = ?
                 WHERE parameterID = ?
                   AND projectID IN (SELECT projectID FROM projectTab WHERE organismID = ?)
                """,
                (value, parameter, pichia),
            )
    return target


def test_the_fixture_really_is_damaged(db_copy: Path):
    """Otherwise every test below would pass against a clean database."""
    assert len(find_duplicate_model_defaults(db_copy)) == len(STRAYS)
    assert find_corrupted_project_parameters(db_copy)


def _count(db_path: Path, sql: str, params: tuple = ()) -> int:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        return conn.execute(sql, params).fetchone()[0]


def test_the_half_written_projects_are_found(db_copy: Path):
    found = {row["projectID"] for row in find_broken_projects(db_copy)}
    assert found == BROKEN


def test_project_732_is_the_interrupted_write(db_copy: Path):
    """42 rows, contiguous, ending on the highest id ever assigned.

    MATLAB was writing 250 of them. The expectation is 253 today because
    `tmax` has since been dropped and the four anti-windup switches added —
    the 42 that were written are history and do not change, what they are
    measured against does.

    The contiguity is the evidence, which is why `add_flags` leaves the nine
    half-created projects alone: four rows with today's ids appended here
    would put a gap in the one record of what the MATLAB path did.
    """
    row = next(r for r in find_broken_projects(db_copy) if r["projectID"] == 732)
    assert (row["parameters"], row["expected"]) == (42, 253)

    with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
        lo, hi, n = conn.execute(
            "SELECT MIN(project_parameterID), MAX(project_parameterID), COUNT(*) "
            "FROM project_parameterTab WHERE projectID = 732"
        ).fetchone()
        intruders = conn.execute(
            "SELECT COUNT(*) FROM project_parameterTab "
            "WHERE projectID != 732 AND project_parameterID BETWEEN ? AND ?",
            (lo, hi),
        ).fetchone()[0]
    assert hi - lo + 1 == n, "an interrupted write leaves no gaps"
    # Not "nothing was written afterwards" — this application writes to that
    # table too, and `add_flags` already has. What cannot change is that these
    # 42 rows are one unbroken run belonging to one project: a write that was
    # cut off partway, with nothing of anyone else's between its first row and
    # its last.
    assert intruders == 0, "the interrupted write is one unbroken block"


def test_the_stray_defaults_are_found(db_copy: Path):
    strays = find_duplicate_model_defaults(db_copy)
    assert {row["name"] for row in strays} == {"yXpOgr", "yCpO", "qOpXm"}
    # Each stray carries the value of the parameter its description names.
    with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
        for row in strays:
            owner = conn.execute(
                "SELECT d.value FROM default_modelTab d JOIN parameterTab p "
                "USING (parameterID) WHERE p.name = ? AND d.organismID = ?",
                (row["belongs_to"], row["organismID"]),
            ).fetchone()[0]
            assert row["value"] == owner, f"{row['name']} holds {row['belongs_to']}'s value"


def test_corrupted_project_values_are_found(db_copy: Path):
    found = find_corrupted_project_parameters(db_copy)
    assert {row["projectID"] for row in found} == {519, 520}
    assert {row["name"] for row in found} == {"yXpOgr", "yCpO", "qOpXm"}


def test_a_dry_run_changes_nothing(db_copy: Path):
    before = _count(db_copy, "SELECT COUNT(*) FROM projectTab")
    report = repair(db_copy, dry_run=True)
    assert report["applied"] is False
    assert _count(db_copy, "SELECT COUNT(*) FROM projectTab") == before


def test_a_broken_project_is_only_removed_when_asked_for(db_copy: Path):
    """It is unopenable, but it is also the only record of what the MATLAB
    create path did."""
    before = _count(db_copy, "SELECT COUNT(*) FROM projectTab")
    report = repair(db_copy, dry_run=False)

    assert report["broken_projects"], "the fixture proves nothing otherwise"
    assert report["removed_projects"] is False
    assert _count(db_copy, "SELECT COUNT(*) FROM projectTab") == before


def test_repair_removes_only_the_unusable_projects(db_copy: Path):
    repair(db_copy, dry_run=False, remove_broken_projects=True)
    with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
        remaining = {row[0] for row in conn.execute("SELECT projectID FROM projectTab")}
    assert remaining == INTACT


def test_repair_cascades_instead_of_deleting_by_hand(db_copy: Path):
    """The defect being repaired was a manual cascade with foreign keys off."""
    assert _count(db_copy, "SELECT COUNT(*) FROM project_parameterTab WHERE projectID = 732") == 42
    repair(db_copy, dry_run=False, remove_broken_projects=True)
    assert _count(db_copy, "SELECT COUNT(*) FROM project_parameterTab WHERE projectID = 732") == 0


def test_repair_restores_the_three_parameter_values(db_copy: Path):
    repair(db_copy, dry_run=False)
    with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
        values = dict(
            conn.execute(
                "SELECT p.name, pp.value FROM project_parameterTab pp "
                "JOIN parameterTab p USING (parameterID) "
                "WHERE pp.projectID = 519 AND p.name IN ('yXpOgr','yCpO','qOpXm')"
            )
        )
    assert values == pytest.approx({"yXpOgr": 1.773, "yCpO": 1.375, "qOpXm": 0.0117})


def test_operator_settings_are_left_alone(db_copy: Path):
    """Only the three known names are touched; NStw is somebody's decision."""
    before = _count(
        db_copy,
        "SELECT pp.value FROM project_parameterTab pp JOIN parameterTab p "
        "USING (parameterID) WHERE pp.projectID = 519 AND p.name = 'NStw'",
    )
    repair(db_copy, dry_run=False)
    after = _count(
        db_copy,
        "SELECT pp.value FROM project_parameterTab pp JOIN parameterTab p "
        "USING (parameterID) WHERE pp.projectID = 519 AND p.name = 'NStw'",
    )
    assert before == after == 1000


def test_a_repaired_database_is_clean_and_stays_clean(db_copy: Path):
    repair(db_copy, dry_run=False, remove_broken_projects=True)

    with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert list(conn.execute("PRAGMA foreign_key_check")) == []
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0

    second = repair(db_copy, dry_run=True)
    assert second["broken_projects"] == []
    assert second["stray_defaults"] == []
    assert second["corrupted_parameters"] == []


def test_the_repaired_database_still_runs_both_models(db_copy: Path):
    from biofermentation.core.runner import run_simulation
    from biofermentation.db import load_phases

    repair(db_copy, dry_run=False)
    for project, organism in ((716, "escherichia_coli"), (519, "pichia_pastoris")):
        p = dict(load_phases(db_copy, project).p) | {"f_Inoc": 1.0, "f_InocStart": 1.0}
        state = run_simulation(organism, p, 20)
        assert state.idx == 20
        assert state.v.cXL[20] > 0


# ------------------------------------------------- parameters nobody reads --


def test_the_template_carries_no_parameter_nothing_reads():
    """tmax is gone from the shipped database; the list is empty from here on."""
    from biofermentation.db.repair import find_dead_parameters

    assert find_dead_parameters(TEMPLATE_DB) == []


def test_a_dead_parameter_is_removed_everywhere_it_sat(tmp_path):
    """Put it back the way the template carried it, then take it out again."""
    import sqlite3

    from biofermentation.db.repair import find_dead_parameters, remove_dead_parameters

    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    with sqlite3.connect(target) as conn:
        conn.execute(
            "INSERT INTO parameterTab (parameterID, categoryID, name, tex, unit, tex_unit, "
            "type, internal_order, external_order) VALUES (231, 15, 'tmax', 't_{max}', 'h', "
            "'h', 'editfield', 3, 1503)"
        )
        conn.execute(
            "INSERT INTO default_modelTab (organismID, parameterID, value, description) "
            "VALUES (1, 231, 5.0, 'Time limit for cultivation')"
        )
        conn.execute(
            "INSERT INTO project_parameterTab (projectID, parameterID, value) "
            "VALUES (716, 231, 5.0)"
        )

    assert find_dead_parameters(target)[0]["name"] == "tmax"
    report = remove_dead_parameters(target, dry_run=False)
    assert report["rows"] == 3
    assert find_dead_parameters(target) == []

    # And again: a parameter that is already gone is not an error.
    assert remove_dead_parameters(target, dry_run=False)["rows"] == 0


def test_a_dry_run_removes_nothing(tmp_path):
    import sqlite3

    from biofermentation.db.repair import remove_dead_parameters

    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    with sqlite3.connect(target) as conn:
        conn.execute(
            "INSERT INTO parameterTab (parameterID, categoryID, name) VALUES (231, 15, 'tmax')"
        )
    report = remove_dead_parameters(target)
    assert report["applied"] is False
    assert report["parameters"][0]["name"] == "tmax"
    with sqlite3.connect(target) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM parameterTab WHERE name = 'tmax'"
        ).fetchone()[0] == 1


def test_the_reference_run_keeps_its_record_of_tmax():
    """The reference CSVs are what the MATLAB run had, not what this database
    should have. They are evidence and stay as they are — the comparison
    builds its state from them and never asks the database."""
    reference = REPO_ROOT / "tests" / "reference_data" / "ecoli_reference_p.csv"
    assert "tmax" in reference.read_text(encoding="utf-8")
