"""Placing a process template into a project — Projektplan_Prozessvorlagen.md, phase 2.

The logic without a window: which phases stay, which go, what the new ones
look like, whether a template fits. The decisive test runs a real process
of project 716 twice — entered by hand, and saved as a template, loaded and
placed — and requires both runs to be identical.
"""

import copy
import shutil
from pathlib import Path

import numpy as np
import pytest

from biofermentation.control import (
    EndCondition,
    PhaseAutomaton,
    PhaseStatus,
    PhaseType,
    StartCondition,
    is_started,
)
from biofermentation.control.templates import (
    APPEND,
    REPLACE,
    check_template,
    check_template_for,
    end_moves_with_replacement,
    hand_over,
    phases_from_template,
    place_template,
    removable,
)
from biofermentation.core.runner import load_project_state
from biofermentation.db import load_phases, load_process_template, save_process_template
from biofermentation.db.models import Condition, Phase, ProcessTemplate
from biofermentation.organisms import discover_organisms

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


def _phase(name, status, *, process_id=0, kind=PhaseType.MANUAL, end=None) -> Phase:
    return Phase(
        processID=process_id,
        projectID=1,
        statusID=status,
        typeID=kind,
        name=name,
        reservoirID=1,
        start=Condition(typeID=StartCondition.PREVIOUS_ENDED),
        end=end or Condition(typeID=EndCondition.TIMER, value=1.0),
    )


def _template(*names: str, model_id: int = 1) -> ProcessTemplate:
    return ProcessTemplate(
        templateID=1,
        modelID=model_id,
        name="T",
        phases=[_phase(name, None) for name in names],
    )


def _project() -> list[Phase]:
    return [
        _phase("P1", PhaseStatus.COMPLETED, process_id=1),
        _phase("P2", PhaseStatus.ACTIVE, process_id=2),
        _phase("P3", PhaseStatus.PENDING, process_id=3),
        _phase("P4", PhaseStatus.UPCOMING, process_id=4),
    ]


# ------------------------------------------------------- placing --


def test_append_keeps_every_phase_and_adds_behind():
    phases = _project()
    new = phases_from_template(_template("T1", "T2"), 10, 1)
    placed = place_template(phases, new, APPEND)
    assert [phase.name for phase in placed.phases] == ["P1", "P2", "P3", "P4", "T1", "T2"]
    assert placed.removed == []
    assert placed.added == new


def test_replace_keeps_active_and_completed_phases():
    phases = _project()
    placed = place_template(phases, phases_from_template(_template("T1"), 10, 1), REPLACE)
    assert placed.phases[:2] == phases[:2]  # the same objects, record intact
    assert [phase.name for phase in placed.phases] == ["P1", "P2", "T1"]


def test_replace_removes_upcoming_and_pending_phases():
    phases = _project()
    placed = place_template(phases, phases_from_template(_template("T1"), 10, 1), REPLACE)
    assert [phase.name for phase in placed.removed] == ["P3", "P4"]
    assert removable(phases) == placed.removed


def test_placing_does_not_change_the_list_it_was_given():
    phases = _project()
    before = [phase.name for phase in phases]
    place_template(phases, phases_from_template(_template("T1"), 10, 1), REPLACE)
    assert [phase.name for phase in phases] == before


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="append"):
        place_template(_project(), [], "insert")


def test_the_panels_and_the_templates_share_one_rule():
    """is_started is what PhasePanel locks and what replacing keeps."""
    statuses = {
        PhaseStatus.UPCOMING: False,
        PhaseStatus.PENDING: False,
        PhaseStatus.ACTIVE: True,
        PhaseStatus.COMPLETED: True,
    }
    for status, started in statuses.items():
        assert is_started(_phase("x", status)) is started
    import inspect

    from biofermentation.gui.widgets import phase_panel

    assert "is_started(phase)" in inspect.getsource(phase_panel.PhasePanel)


# -------------------------------------------- what the new phases are --


def test_loaded_phases_are_upcoming_and_have_no_times():
    template = _template("T1", "T2")
    for phase in template.phases:
        phase.start.time = 3.0  # as if a stale time had come along
        phase.end.time = 4.0
    for phase in phases_from_template(template, 10, 7):
        assert phase.statusID == PhaseStatus.UPCOMING
        assert phase.start.time is None and phase.end.time is None
        assert phase.projectID == 7


def test_loaded_phases_get_fresh_process_ids():
    new = phases_from_template(_template("T1", "T2", "T3"), 42, 1)
    assert [phase.processID for phase in new] == [42, 43, 44]


def test_the_template_itself_stays_as_it_was_loaded():
    """Placing twice must give two independent sets of phases."""
    template = _template("T1")
    template.phases[0].parameters["pHw"] = 6.5
    first = phases_from_template(template, 10, 1)
    first[0].parameters["pHw"] = 7.0
    first[0].end.value = 9.0
    assert template.phases[0].parameters["pHw"] == 6.5
    assert template.phases[0].end.value == 1.0


# ------------------------------------------------------- checking --

PARAMETERS = {"pHw", "thetaLw", "kR1", "FR1max", "qXpX1w"}


def _check(template, reservoirs=1, model_id=1):
    return check_template(
        template,
        model_id=model_id,
        parameters=PARAMETERS,
        variables=[1, 8, 61],
        reservoirs=reservoirs,
    )


def test_a_fitting_template_has_nothing_to_report():
    assert _check(_template("T1", "T2")) == []


def test_a_template_with_an_unknown_parameter_is_refused_with_its_name():
    template = _template("Update")
    template.phases[0].parameters = {"pHw": 6.8, "cS9Lw": 1.0}
    [problem] = _check(template)
    assert "cS9Lw" in problem and "Update" in problem


def test_a_template_with_a_reservoir_the_model_lacks_is_refused():
    template = _template("Feed")
    template.phases[0].reservoirID = 2
    [problem] = _check(template, reservoirs=1)
    assert "reservoir 2" in problem
    assert _check(template, reservoirs=2) == []


def test_a_condition_on_a_variable_the_organism_lacks_is_refused():
    template = _template("Wait")
    template.phases[0].end = Condition(typeID=EndCondition.VARIABLE, variableID=99, operatorID=1)
    [problem] = _check(template)
    assert "99" in problem and "end condition" in problem


def test_a_template_of_another_model_is_refused():
    assert _check(_template("T1", model_id=2), model_id=1) == [
        "The template belongs to another model."
    ]


def test_the_check_reads_a_real_project(db):
    """Against what load_phases gives, the way the window will call it."""
    setup = load_phases(db, 519)
    template = ProcessTemplate(
        templateID=1, modelID=setup.info.modelID, name="T", phases=copy.deepcopy(setup.phases)
    )
    # Its feed phases carry results, which the database would not have kept;
    # everything else of 519 fits 519.
    for phase in template.phases:
        phase.parameters = {k: v for k, v in phase.parameters.items() if not k.endswith("j")}
    assert check_template_for(template, setup, reservoirs=2) == []
    assert check_template_for(template, setup, reservoirs=1)  # reservoir 2 is used


# ------------------------------------------- a running phase (P0-1, P0-4) --


def test_replacing_behind_an_active_phase_keeps_it_running(db):
    """Project 519, saved with its Fed Batch active: replace, then a real block."""
    discover_organisms()
    setup = load_phases(db, 519)
    state, model = load_project_state(db, 519)
    automaton = PhaseAutomaton.from_setup(setup)
    active = automaton.current
    fed_batch = setup.phases[active]
    started, feed = fed_batch.start.time, fed_batch.parameters["FR1j"]

    template = ProcessTemplate(
        templateID=1,
        modelID=setup.info.modelID,
        name="T",
        phases=[_phase("Next", None, end=Condition(typeID=EndCondition.TIMER, value=0.5))],
    )
    placed = place_template(
        setup.phases, phases_from_template(template, setup.next_process_id, 519), REPLACE
    )
    assert [phase.name for phase in placed.removed] == [
        "Pulse Feed",
        "Closed-Loop Feed",
        "Pulse Feed 2",
    ]
    hand_over(automaton, placed.phases)
    assert automaton.current == active

    # One block as the runner computes it.
    automaton.check_start(state)
    model.calculate_step(state)
    automaton.check_end(state)

    assert fed_batch.statusID == PhaseStatus.ACTIVE
    assert fed_batch.start.time == started
    assert fed_batch.parameters["FR1j"] == feed
    assert placed.phases[-1].statusID == PhaseStatus.UPCOMING


def test_a_next_phase_end_before_a_replacement_is_reported():
    phases = _project()
    phases[1].end = Condition(typeID=EndCondition.NEXT_PHASE_STARTS)
    assert end_moves_with_replacement(phases, REPLACE) is phases[1]
    assert end_moves_with_replacement(phases, APPEND) is None
    phases[1].end = Condition(typeID=EndCondition.TIMER, value=1.0)
    assert end_moves_with_replacement(phases, REPLACE) is None


def test_no_active_phase_means_nothing_to_report():
    phases = [_phase("P1", PhaseStatus.COMPLETED), _phase("P2", PhaseStatus.UPCOMING)]
    assert end_moves_with_replacement(phases, REPLACE) is None


# ---------------------------------------------- the decisive run --


def _by_hand(setup) -> list[Phase]:
    """A process for project 716, entered the way an operator would."""
    cxl = next(r["variableID"] for r in setup.lookups.process_variable if r["name"] == "cXL")
    return [
        Phase(
            processID=1,
            projectID=716,
            statusID=PhaseStatus.UPCOMING,
            typeID=PhaseType.MANUAL,
            name="Batch",
            reservoirID=1,
            start=Condition(typeID=StartCondition.PREVIOUS_ENDED),
            end=Condition(typeID=EndCondition.TIMER, value=0.05),
        ),
        Phase(
            processID=2,
            projectID=716,
            statusID=PhaseStatus.UPCOMING,
            typeID=PhaseType.PARAMETER_UPDATE,
            name="Warmer",
            reservoirID=1,
            start=Condition(typeID=StartCondition.PREVIOUS_ENDED),
            end=Condition(typeID=EndCondition.TIMER, value=0.05),
            parameters={"thetaLw": 34.0},
        ),
        Phase(
            processID=3,
            projectID=716,
            statusID=PhaseStatus.UPCOMING,
            typeID=PhaseType.EXPONENTIAL_FEED,
            name="Fed batch",
            reservoirID=1,
            start=Condition(
                typeID=StartCondition.VARIABLE, variableID=cxl, operatorID=1, value=0.1
            ),
            end=Condition(typeID=EndCondition.TIMER, value=0.1),
            parameters={"qXpX1w": 0.15},
        ),
        Phase(
            processID=4,
            projectID=716,
            statusID=PhaseStatus.UPCOMING,
            typeID=PhaseType.MANUAL,
            name="Hold",
            reservoirID=1,
            start=Condition(typeID=StartCondition.PREVIOUS_ENDED),
            end=Condition(typeID=EndCondition.TIMER, value=1.0),
        ),
    ]


def _run(db, setup, phases, steps=240):
    """The runner's block, speed factor 1, with the given phases."""
    discover_organisms()
    state, model = load_project_state(db, 716)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    automaton = PhaseAutomaton(
        phases,
        variable_names={r["variableID"]: r["name"] for r in setup.lookups.process_variable},
        operator_symbols={
            r["process_operatorID"]: r["operator"] for r in setup.lookups.process_operator
        },
    )
    for _ in range(steps):
        automaton.check_start(state)
        model.calculate_step(state)
        automaton.check_end(state)
    return state, phases


def test_loading_into_a_run_gives_the_same_run_as_entering_the_phases_by_hand(db):
    setup = load_phases(db, 716)
    hand_state, hand_phases = _run(db, setup, _by_hand(setup))

    template_id = save_process_template(
        db, setup.info.modelID, "716 standard", None, _by_hand(setup)
    )
    template = load_process_template(db, template_id)
    assert check_template_for(template, setup, reservoirs=1) == []
    placed = place_template([], phases_from_template(template, 1, 716), APPEND)
    loaded_state, loaded_phases = _run(db, setup, placed.phases)

    # The process went through every phase it was meant to, in both runs.
    assert [phase.statusID for phase in hand_phases] == [
        PhaseStatus.COMPLETED,
        PhaseStatus.COMPLETED,
        PhaseStatus.COMPLETED,
        PhaseStatus.ACTIVE,
    ]
    for hand, loaded in zip(hand_phases, loaded_phases, strict=True):
        assert (hand.statusID, hand.start.time, hand.end.time) == (
            loaded.statusID,
            loaded.start.time,
            loaded.end.time,
        ), hand.name
        assert hand.parameters == loaded.parameters, hand.name
    first, second = hand_state.trimmed(), loaded_state.trimmed()
    assert first.keys() == second.keys()
    for name in first:
        assert np.array_equal(first[name], second[name], equal_nan=True), name
    assert hand_state.p == loaded_state.p
