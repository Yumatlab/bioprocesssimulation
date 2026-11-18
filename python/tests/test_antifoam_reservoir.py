"""The antifoam reservoir — an addition to the model, 16.11.2026.

Two parameters (VT30, FT3max) and two series (VT3, FT3), added to a database
by db/additions.py and computed by organisms/shared.antifoam_reservoir. It is
a display: no other series may change because of it.
"""

import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from biofermentation.core.runner import build_state, run_steps
from biofermentation.db import load_phases
from biofermentation.db.additions import (
    ANTIFOAM_PARAMETERS,
    ANTIFOAM_VARIABLES,
    add_antifoam_reservoir,
)
from biofermentation.organisms import discover_organisms, get_organism

RESOURCES = Path(__file__).resolve().parents[1] / "src" / "biofermentation" / "resources"
TEMPLATE_DB = RESOURCES / "SimulationAppDB_template.db"
ORGANISMS = [("escherichia_coli", 716), ("pichia_pastoris", 519)]


@pytest.fixture(autouse=True, scope="module")
def _registry():
    discover_organisms()


def _state(organism: str, project: int, **parameters):
    model = get_organism(organism)
    p = dict(load_phases(TEMPLATE_DB, project).p)
    p.update(f_Inoc=1.0, f_InocStart=1.0)
    p.update(parameters)
    state = build_state(p, model, dt=2 / 3600)
    # Inoculated at t = 0 leaves ToI at 0, and the model doses only while
    # ToI != 0 — as far as the timer knows, a moment after the start.
    state.a.ToI = 1e-6
    return state, model


# ------------------------------------------------------- the model --


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_the_reservoir_empties_at_the_pump_rate(organism, project):
    state, model = _state(organism, project, f_antifoam=1.0, VT30=0.5, FT3max=0.1)
    run_steps(state, model, 900)  # half an hour
    assert state.v.FT3[state.idx] == 0.1
    # The first step still pumps nothing: the flow of a step drains the next.
    hours = float(state.v.t[state.idx - 1])
    assert state.v.VT3[state.idx] == pytest.approx(0.5 - 0.1 * hours, abs=1e-9)


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_the_pump_stops_when_the_reservoir_is_empty(organism, project):
    state, model = _state(organism, project, f_antifoam=1.0, VT30=0.01, FT3max=1.0)
    run_steps(state, model, 60)
    assert state.v.VT3[state.idx] == 0.0
    assert state.v.FT3[state.idx] == 0.0
    assert np.nanmin(state.v.VT3[: state.idx + 1]) >= 0.0


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_without_the_flag_nothing_is_pumped(organism, project):
    state, model = _state(organism, project, f_antifoam=0.0)
    run_steps(state, model, 20)
    assert state.v.FT3[state.idx] == 0.0
    assert state.v.VT3[state.idx] == state.p["VT30"]


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_the_reservoir_changes_no_other_series(organism, project):
    """Bit for bit: a display, not a part of the balances."""
    runs = []
    for rate in (0.0, 5.0):
        state, model = _state(organism, project, f_antifoam=1.0, FT3max=rate)
        run_steps(state, model, 200)
        runs.append(state.trimmed())
    first, second = runs
    assert first.keys() == second.keys()
    for name in first:
        if name in ("VT3", "FT3"):
            continue
        assert np.array_equal(first[name], second[name], equal_nan=True), name
    assert not np.array_equal(first["VT3"], second["VT3"])


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_a_database_from_before_it_still_runs(organism, project):
    """Neither parameter: no volume, no pump, no error."""
    model = get_organism(organism)
    p = dict(load_phases(TEMPLATE_DB, project).p)
    p.update(f_Inoc=1.0, f_InocStart=1.0, f_antifoam=1.0)
    del p["VT30"], p["FT3max"]
    state = build_state(p, model, dt=2 / 3600)
    state.a.ToI = 1e-6
    run_steps(state, model, 20)
    assert state.v.VT3[state.idx] == 0.0
    assert state.v.FT3[state.idx] == 0.0


# ---------------------------------------------------- the database --


def _strip(db: Path) -> None:
    """Take the addition out again: a database as it was before."""
    conn = sqlite3.connect(db)
    names = [entry["name"] for entry in ANTIFOAM_PARAMETERS]
    marks = ", ".join("?" * len(names))
    ids = [
        r[0]
        for r in conn.execute(
            f"SELECT parameterID FROM parameterTab WHERE name IN ({marks})", names
        )
    ]
    for table in (
        "default_bioreactorTab",
        "model_parameterTab",
        "project_parameterTab",
        "parameterTab",
    ):
        conn.executemany(f"DELETE FROM {table} WHERE parameterID = ?", [(i,) for i in ids])
    names = [entry["name"] for entry in ANTIFOAM_VARIABLES]
    ids = [
        r[0]
        for r in conn.execute(f"SELECT variableID FROM variableTab WHERE name IN ({marks})", names)
    ]
    for table in ("variable_handlingTab", "variableTab"):
        conn.executemany(f"DELETE FROM {table} WHERE variableID = ?", [(i,) for i in ids])
    conn.commit()
    conn.close()


@pytest.fixture
def old_db(tmp_path: Path) -> Path:
    target = tmp_path / "old.db"
    shutil.copy(TEMPLATE_DB, target)
    _strip(target)
    return target


def test_the_template_already_has_the_reservoir():
    report = add_antifoam_reservoir(TEMPLATE_DB)
    assert report["parameters"] == []
    assert report["variables"] == []
    p = load_phases(TEMPLATE_DB, 716).p
    assert p["VT30"] == 0.5
    assert p["FT3max"] == 0.1


def test_a_dry_run_says_what_is_missing_and_writes_nothing(old_db):
    before = old_db.read_bytes()
    report = add_antifoam_reservoir(old_db)
    assert report["parameters"] == ["VT30", "FT3max"]
    assert report["variables"] == ["VT3", "FT3"]
    assert report["applied"] is False
    assert "VT30" not in load_phases(old_db, 716).p
    assert old_db.read_bytes() == before


def test_adding_gives_every_project_the_parameters_and_is_idempotent(old_db):
    report = add_antifoam_reservoir(old_db, dry_run=False)
    assert report["rows"] > 0
    for project in (716, 519):
        p = load_phases(old_db, project).p
        assert p["VT30"] == 0.5
        assert p["FT3max"] == 0.1

    again = add_antifoam_reservoir(old_db, dry_run=False)
    assert again["parameters"] == [] and again["variables"] == []
    assert again["rows"] == 0

    conn = sqlite3.connect(old_db)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    handled = conn.execute(
        "SELECT COUNT(*) FROM variable_handlingTab h JOIN variableTab v USING (variableID)"
        " WHERE v.name IN ('VT3', 'FT3')"
    ).fetchone()[0]
    organisms = conn.execute("SELECT COUNT(*) FROM organismTab").fetchone()[0]
    assert handled == 2 * organisms
    conn.close()
