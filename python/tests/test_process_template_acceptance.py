"""Acceptance of the process templates — Projektplan_Prozessvorlagen.md, phase 5.

The whole way, through the window as an operator takes it: a process is
designed for project 716 and saved as a template; two **new** projects of the
same model are created; one loads the template, the other gets the same
phases entered by hand (+ and then the fields of each phase). Both run on the
window's own runner, tick by tick. The two runs must be identical.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from biofermentation.control import (
    EndCondition,
    PhaseAutomaton,
    PhaseStatus,
    PhaseType,
    StartCondition,
)
from biofermentation.core.runner import load_project_state
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import create_project, load_phases
from biofermentation.gui.windows import ControlWindow
from biofermentation.organisms import discover_organisms

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
TICKS = 240


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


def _window(db, project: int) -> ControlWindow:
    discover_organisms()
    setup = load_phases(db, project)
    state, organism = load_project_state(db, project)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    runner = SimulationRunner(
        organism, state, phases=PhaseAutomaton.from_setup(setup), speedfactor=1
    )
    return ControlWindow(setup, runner, db)


def _design(window) -> None:
    """The process, entered the way an operator does: + four times, then each phase."""
    cxl = next(r["variableID"] for r in window.setup.lookups.process_variable if r["name"] == "cXL")
    for _ in range(4):
        window.add_phase()
    batch, warmer, feed, hold = window.setup.phases
    batch.name = "Batch"
    batch.end.typeID, batch.end.value = EndCondition.TIMER, 0.05

    warmer.name, warmer.typeID = "Warmer", PhaseType.PARAMETER_UPDATE
    warmer.end.typeID, warmer.end.value = EndCondition.TIMER, 0.05
    warmer.parameters = {"thetaLw": 34.0}

    feed.name, feed.typeID, feed.reservoirID = "Fed batch", PhaseType.EXPONENTIAL_FEED, 1
    feed.start.typeID = StartCondition.VARIABLE
    feed.start.variableID, feed.start.operatorID, feed.start.value = cxl, 1, 0.1
    feed.end.typeID, feed.end.value = EndCondition.TIMER, 0.1
    feed.parameters = {"qXpX1w": 0.15}

    hold.name = "Hold"
    hold.end.typeID, hold.end.value = EndCondition.TIMER, 1.0


def _run(window) -> None:
    for _ in range(TICKS):
        window.runner._on_tick()
    window.refresh()


def test_a_template_from_716_runs_in_a_new_project_exactly_as_entered_by_hand(
    qapp, db, monkeypatch
):
    # 1. Designed on 716 and saved as a template, through the window.
    source = _window(db, 716)
    _design(source)
    monkeypatch.setattr(
        source,
        "_ask_template_details",
        lambda phases: {"name": "716 standard", "description": "", "author": ""},
    )
    template_id = source.save_process_template()
    assert template_id is not None
    model = source.setup.info.modelID
    source.close()

    # 2. Two new projects of the same model.
    loaded = _window(db, create_project(db, "From the template", model))
    by_hand = _window(db, create_project(db, "By hand", model))
    assert loaded.setup.phases == [] and by_hand.setup.phases == []

    # 3. One loads the template, the other gets the phases by hand.
    monkeypatch.setattr(loaded, "_choose_template", lambda: template_id)
    assert loaded.load_process_template() == template_id
    _design(by_hand)
    assert [p.name for p in loaded.setup.phases] == [p.name for p in by_hand.setup.phases]

    # 4. Both run on their own runner.
    _run(loaded)
    _run(by_hand)

    statuses = [phase.statusID for phase in by_hand.setup.phases]
    assert statuses == [PhaseStatus.COMPLETED] * 3 + [PhaseStatus.ACTIVE]
    for hand, template in zip(by_hand.setup.phases, loaded.setup.phases, strict=True):
        assert (hand.statusID, hand.start.time, hand.end.time, hand.parameters) == (
            template.statusID,
            template.start.time,
            template.end.time,
            template.parameters,
        ), hand.name
    first, second = by_hand.runner.state.trimmed(), loaded.runner.state.trimmed()
    assert first.keys() == second.keys()
    for name in first:
        assert np.array_equal(first[name], second[name], equal_nan=True), name
    # The feed really ran: its results were written into the phase.
    assert by_hand.setup.phases[2].parameters["FR1j"] > 0
    loaded.close()
    by_hand.close()
