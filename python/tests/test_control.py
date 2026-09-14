"""Phase automaton and batch end detection (plan section 3).

No GUI anywhere: a phase sequence is driven against a real simulation and the
transitions are checked. The phase data of project 519 is used where a real
configuration matters; everything else is built explicitly so a test states
its own premise.
"""

from pathlib import Path

import numpy as np
import pytest

from biofermentation.control import (
    OPERATORS,
    BatchEndDetector,
    EndCondition,
    PhaseAutomaton,
    PhaseStatus,
    PhaseType,
    StartCondition,
    sliding_median,
    theil_sen_slope,
)
from biofermentation.core.runner import build_state, run_steps
from biofermentation.core.state import Namespace, SimulationState
from biofermentation.db import load_phases
from biofermentation.db.models import Condition, Phase
from biofermentation.organisms import discover_organisms, get_organism

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
ECOLI_PROJECT = 716
PICHIA_PROJECT = 519

# variableID and operatorID as the lookup tables define them.
VARIABLES = {1: "cXL", 2: "cS1L", 61: "t"}
OPERATOR_SYMBOLS = {1: ">=", 2: "<=", 3: ">", 4: "<", 5: "="}


@pytest.fixture(scope="module")
def registry():
    return discover_organisms()


@pytest.fixture
def ecoli(registry):
    """A running E. coli simulation — the verified model."""
    p = dict(load_phases(TEMPLATE_DB, ECOLI_PROJECT).p) | {
        "f_Inoc": 1.0,
        "f_InocStart": 1.0,
        "deltatsec": 2.0,
    }
    model = get_organism("escherichia_coli")
    return build_state(p, model, dt=2 / 3600), model


def _automaton(phases: list[Phase], **kwargs) -> PhaseAutomaton:
    return PhaseAutomaton(
        phases, variable_names=VARIABLES, operator_symbols=OPERATOR_SYMBOLS, **kwargs
    )


def _phase(process_id: int, **kwargs) -> Phase:
    kwargs.setdefault("statusID", PhaseStatus.UPCOMING)
    kwargs.setdefault("typeID", PhaseType.MANUAL)
    kwargs.setdefault("name", f"Phase {process_id}")
    kwargs.setdefault("start", Condition(typeID=StartCondition.PREVIOUS_ENDED))
    kwargs.setdefault("end", Condition(typeID=EndCondition.TIMER, value=1.0))
    return Phase(processID=process_id, projectID=1, **kwargs)


# ------------------------------------------------- enums against the DB --


def test_the_enums_match_the_lookup_tables():
    """A renumbered lookup table must not silently change the automaton."""
    import sqlite3

    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        statuses = dict(conn.execute("SELECT status, process_statusID FROM process_statusTab"))
        types = dict(conn.execute("SELECT type, process_typeID FROM process_typeTab"))
        conditions = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT conditiontype, process_conditiontypeID, start_end "
                "FROM process_conditiontypeTab"
            )
        }

    assert statuses == {
        "upcoming": PhaseStatus.UPCOMING,
        "pending": PhaseStatus.PENDING,
        "active": PhaseStatus.ACTIVE,
        "completed": PhaseStatus.COMPLETED,
    }
    assert types["Stop"] == PhaseType.STOP
    assert types["Update Parameter Set"] == PhaseType.PARAMETER_UPDATE
    assert types["Pulse Feed"] == PhaseType.PULSE_FEED
    assert types["Exponential Feed"] == PhaseType.EXPONENTIAL_FEED
    assert conditions["End of previous phase"] == (StartCondition.PREVIOUS_ENDED, 1)
    assert conditions["Timer"] == (EndCondition.TIMER, 2)


def test_every_stored_operator_is_understood():
    """MATLAB's switch tests for '==' and never matches the '=' in the table."""
    import sqlite3

    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        symbols = [row[0] for row in conn.execute("SELECT operator FROM process_operatorTab")]
    unknown = [symbol for symbol in symbols if symbol not in OPERATORS]
    assert unknown == [], f"the automaton cannot evaluate {unknown}"
    assert "=" in symbols and OPERATORS["="](1.0, 1.0)


# -------------------------------------------------------- conditions --


@pytest.mark.parametrize(
    ("operator_id", "threshold", "expected"),
    [
        (1, 3.0, True),
        (1, 4.0, False),
        (2, 3.0, True),
        (3, 2.9, True),
        (4, 3.0, False),
        (5, 3.0, True),
    ],
)
def test_variable_conditions_compare_the_current_value(operator_id, threshold, expected):
    state = SimulationState(p=Namespace())
    state.series("cXL", 3.0)
    automaton = _automaton([])
    assert automaton.evaluate_condition(state, 1, operator_id, threshold) is expected


def test_an_unknown_variable_is_reported_not_raised():
    state = SimulationState(p=Namespace())
    automaton = _automaton([])
    assert automaton.evaluate_condition(state, 999, 1, 0.0) is False
    assert any("999" in line for line in automaton.log)


def test_a_condition_without_a_threshold_never_fires():
    state = SimulationState(p=Namespace())
    state.series("cXL", 3.0)
    automaton = _automaton([])
    assert automaton.evaluate_condition(state, 1, 1, None) is False


def test_previous_ended_is_always_true():
    state = SimulationState(p=Namespace())
    automaton = _automaton([_phase(1, start=Condition(typeID=StartCondition.PREVIOUS_ENDED))])
    assert automaton.condition_check(state, "start", 0) is True


def test_a_timer_end_compares_against_process_time():
    state = SimulationState(p=Namespace())
    state.series("t", 0.0)
    state.ensure_capacity(1)
    state.v.t[1] = 2.0
    state.idx = 1
    automaton = _automaton([_phase(1, end=Condition(typeID=EndCondition.TIMER, time=3.0))])
    assert automaton.condition_check(state, "end", 0) is False
    state.v.t[1] = 3.5
    assert automaton.condition_check(state, "end", 0) is True


def test_next_phase_starts_recurses_into_the_following_phase():
    state = SimulationState(p=Namespace())
    state.series("cXL", 5.0)
    phases = [
        _phase(1, end=Condition(typeID=EndCondition.NEXT_PHASE_STARTS)),
        _phase(
            2,
            start=Condition(typeID=StartCondition.VARIABLE, variableID=1, operatorID=3, value=4.0),
        ),
    ]
    automaton = _automaton(phases)
    assert automaton.condition_check(state, "end", 0) is True
    state.v.cXL[0] = 3.0
    assert automaton.condition_check(state, "end", 0) is False


def test_next_phase_starts_on_the_last_phase_never_fires():
    state = SimulationState(p=Namespace())
    automaton = _automaton([_phase(1, end=Condition(typeID=EndCondition.NEXT_PHASE_STARTS))])
    assert automaton.condition_check(state, "end", 0) is False


# ------------------------------------------------------- transitions --


def test_a_phase_starts_and_stamps_its_time(ecoli):
    state, model = ecoli
    automaton = _automaton([_phase(1)])
    model.calculate_step(state)

    assert automaton.check_start(state) == 0
    assert automaton.phases[0].statusID == PhaseStatus.ACTIVE
    assert automaton.phases[0].start.time == pytest.approx(state.v.t[state.idx])
    assert automaton.current == 0


def test_a_timer_phase_gets_its_end_from_its_start(ecoli):
    state, model = ecoli
    phase = _phase(1, end=Condition(typeID=EndCondition.TIMER, value=0.5))
    automaton = _automaton([phase])
    for _ in range(5):
        model.calculate_step(state)
    automaton.check_start(state)
    assert phase.end.time == pytest.approx(phase.start.time + 0.5)


def test_ending_a_phase_hands_over_to_the_next(ecoli):
    state, model = ecoli
    phases = [_phase(1, end=Condition(typeID=EndCondition.TIMER, value=0.0)), _phase(2)]
    automaton = _automaton(phases)
    model.calculate_step(state)

    automaton.check_start(state)
    assert automaton.check_end(state) == 0
    assert phases[0].statusID == PhaseStatus.COMPLETED
    assert phases[1].statusID == PhaseStatus.PENDING
    assert automaton.current is None


def test_only_one_phase_is_active_at_a_time(ecoli):
    state, model = ecoli
    automaton = _automaton([_phase(1), _phase(2)])
    model.calculate_step(state)
    automaton.check_start(state)
    assert automaton.check_start(state) is None
    assert [p.statusID for p in automaton.phases] == [PhaseStatus.ACTIVE, PhaseStatus.UPCOMING]


def test_nothing_starts_once_every_phase_is_completed(ecoli):
    state, model = ecoli
    phases = [_phase(1, statusID=PhaseStatus.COMPLETED)]
    automaton = _automaton(phases)
    model.calculate_step(state)
    assert automaton.check_start(state) is None


def test_a_forced_status_ends_the_phase_regardless_of_its_condition(ecoli):
    """The editor can end a phase by hand; the automaton has to accept that."""
    state, model = ecoli
    phase = _phase(1, end=Condition(typeID=EndCondition.TIMER, value=99.0))
    automaton = _automaton([phase])
    model.calculate_step(state)
    automaton.check_start(state)

    phase.statusID = PhaseStatus.COMPLETED
    assert automaton.check_end(state) == 0


# ----------------------------------------------------------- actions --


def test_a_parameter_update_writes_into_p(ecoli):
    state, model = ecoli
    before = state.p.NStw
    phase = _phase(1, typeID=PhaseType.PARAMETER_UPDATE, parameters={"NStw": 777.0})
    automaton = _automaton([phase])
    model.calculate_step(state)
    automaton.check_start(state)

    assert state.p.NStw == 777.0
    assert any("NStw" in line for line in automaton.log)
    assert before != 777.0


def test_an_unknown_parameter_name_is_ignored(ecoli):
    state, model = ecoli
    phase = _phase(1, typeID=PhaseType.PARAMETER_UPDATE, parameters={"not_a_parameter": 1.0})
    automaton = _automaton([phase])
    model.calculate_step(state)
    automaton.check_start(state)
    assert "not_a_parameter" not in state.p


def test_a_pulse_feed_sets_the_switch_the_model_reads(ecoli):
    state, model = ecoli
    phase = _phase(1, typeID=PhaseType.PULSE_FEED, reservoirID=1)
    automaton = _automaton([phase])
    model.calculate_step(state)
    automaton.check_start(state)

    assert state.a.switch_pulse is True
    assert state.p.R_feed == 1
    # The model must actually feed on the next step.
    model.calculate_step(state)
    assert state.v.FR1[state.idx] == pytest.approx(state.p.kR1 * state.p.FR1max)


def test_a_reservoir_beyond_the_organism_is_clamped(ecoli):
    """E. coli has one reservoir; a phase asking for the second gets the first."""
    state, model = ecoli
    phase = _phase(1, typeID=PhaseType.PULSE_FEED, reservoirID=2)
    automaton = _automaton([phase])
    model.calculate_step(state)
    automaton.check_start(state)
    assert state.p.R_feed == 1


def test_an_exponential_feed_freezes_its_starting_point(ecoli):
    state, model = ecoli
    phase = _phase(1, typeID=PhaseType.EXPONENTIAL_FEED, reservoirID=1)
    automaton = _automaton([phase])
    for _ in range(10):
        model.calculate_step(state)
    automaton.check_start(state)

    assert state.a.switch_exp is True
    assert state.p.t1j == pytest.approx(state.v.t[state.idx])
    assert state.p.cXL1j == pytest.approx(state.v.cXL[state.idx])

    expected = (
        (state.p.qXpX1w + state.p.qS1pXm * state.p.yXpS1gr)
        * state.v.VL[state.idx]
        * state.v.cXL[state.idx]
    ) / (state.p.yXpS1gr * state.p.cS1R1)
    assert state.p.FR1j == pytest.approx(expected)
    # savePhases writes these back, so the phase has to carry them.
    assert phase.parameters["FR1j"] == pytest.approx(expected)


def test_ending_a_feed_phase_clears_the_switches(ecoli):
    state, model = ecoli
    phase = _phase(
        1, typeID=PhaseType.PULSE_FEED, end=Condition(typeID=EndCondition.TIMER, value=0.0)
    )
    automaton = _automaton([phase])
    model.calculate_step(state)
    automaton.check_start(state)
    assert state.a.switch_pulse is True

    automaton.check_end(state)
    assert state.a.switch_pulse is False
    assert state.a.switch_exp is False


def test_a_stop_phase_stops_the_run(ecoli):
    state, model = ecoli
    automaton = _automaton([_phase(1, typeID=PhaseType.STOP)])
    run_steps(state, model, 500, phases=automaton)
    assert automaton.stop_requested is True
    assert state.idx < 500


# ------------------------------------------------- batch end detection --


def test_sliding_median_pads_at_the_edges():
    values = np.array([1.0, 100.0, 2.0, 3.0, 4.0])
    assert sliding_median(values, 3).tolist() == [1.0, 2.0, 3.0, 3.0, 4.0]
    assert sliding_median(values, 1).tolist() == values.tolist()


def test_theil_sen_finds_the_slope_through_an_outlier():
    x = np.arange(7, dtype=float)
    y = 2.0 * x
    y[3] = 500.0
    assert theil_sen_slope(x, y) == pytest.approx(2.0)
    assert theil_sen_slope(np.array([1.0]), np.array([1.0])) == 0.0


def _rising(state: SimulationState, n: int, pO2_per_h: float, NSt_per_h: float) -> None:
    state.series("pO2", 20.0)
    state.series("NSt", 1000.0)
    state.series("t", 0.0)
    state.ensure_capacity(n)
    for i in range(n + 1):
        state.v.t[i] = i * state.dt
        state.v.pO2[i] = 20.0 + pO2_per_h * state.v.t[i]
        state.v.NSt[i] = 1000.0 + NSt_per_h * state.v.t[i]
    state.idx = n


def test_the_detector_needs_both_signals_at_once():
    state = SimulationState(p=Namespace({"deltatsec": 2.0}), dt=2 / 3600)
    # 5 %/min and -5 rpm/min are the thresholds; go well past both.
    _rising(state, 20, pO2_per_h=60 * 60, NSt_per_h=-60 * 60)
    detector = BatchEndDetector()
    fired = [detector.detect(state) for _ in range(4)]
    assert fired == [False, False, True, True], "three confirmations, then it holds"

    # pO2 rising alone is not a batch end.
    quiet = SimulationState(p=Namespace({"deltatsec": 2.0}), dt=2 / 3600)
    _rising(quiet, 20, pO2_per_h=60 * 60, NSt_per_h=0.0)
    assert BatchEndDetector().detect(quiet) is False


def test_the_hysteresis_counter_resets_on_a_break():
    state = SimulationState(p=Namespace({"deltatsec": 2.0}), dt=2 / 3600)
    _rising(state, 20, pO2_per_h=60 * 60, NSt_per_h=-60 * 60)
    detector = BatchEndDetector()
    detector.detect(state)
    detector.detect(state)
    assert detector.confirm_count == 2

    _rising(state, 20, pO2_per_h=0.0, NSt_per_h=0.0)
    assert detector.detect(state) is False
    assert detector.confirm_count == 0


def test_two_detectors_do_not_share_a_counter():
    """MATLAB keeps this in a `persistent`, shared across the whole session."""
    state = SimulationState(p=Namespace({"deltatsec": 2.0}), dt=2 / 3600)
    _rising(state, 20, pO2_per_h=60 * 60, NSt_per_h=-60 * 60)
    first, second = BatchEndDetector(), BatchEndDetector()
    first.detect(state)
    first.detect(state)
    assert second.confirm_count == 0
    assert second.detect(state) is False


def test_too_little_history_is_not_a_batch_end():
    state = SimulationState(p=Namespace({"deltatsec": 2.0}), dt=2 / 3600)
    _rising(state, 20, pO2_per_h=60 * 60, NSt_per_h=-60 * 60)
    state.idx = 2
    assert BatchEndDetector().detect(state) is False


def test_the_window_follows_the_unit_it_is_given():
    """deltatsec is seconds; MATLAB passes it where hours are documented."""
    state = SimulationState(p=Namespace({"deltatsec": 2.0}), dt=2 / 3600)
    _rising(state, 200, pO2_per_h=60 * 60, NSt_per_h=-60 * 60)
    seconds = BatchEndDetector(window_in_seconds=True)
    hours = BatchEndDetector(window_in_seconds=False)
    seconds.detect(state)
    hours.detect(state)
    # Same data, same verdict — but the hour version regresses over 90 samples
    # instead of 3, which is what the documentation intends.
    assert seconds.last_slopes != hours.last_slopes


# ------------------------------------------------ the whole sequence --


def test_a_real_phase_sequence_runs_through(registry):
    """Project 519: batch, exponential feed, pulse feed, update, pulse feed."""
    setup = load_phases(TEMPLATE_DB, PICHIA_PROJECT)
    for phase in setup.phases:
        phase.statusID = PhaseStatus.UPCOMING
        phase.start.time = phase.end.time = None

    p = dict(setup.p) | {"f_Inoc": 1.0, "f_InocStart": 1.0, "deltatsec": 2.0}
    model = get_organism("pichia_pastoris")
    state = build_state(p, model, dt=2 / 3600)
    automaton = PhaseAutomaton.from_setup(setup)

    run_steps(state, model, 7000, phases=automaton)

    batch, fed_batch = setup.phases[0], setup.phases[1]
    assert batch.statusID == PhaseStatus.COMPLETED
    assert batch.start.time == pytest.approx(0.0, abs=1e-9)
    assert 0 < batch.end.time < state.v.t[state.idx]
    assert fed_batch.statusID == PhaseStatus.ACTIVE
    assert fed_batch.start.time == pytest.approx(batch.end.time)
    # A timer phase ends value hours after it started.
    assert fed_batch.end.time == pytest.approx(fed_batch.start.time + fed_batch.end.value)
    assert state.a.switch_exp is True


def test_phases_survive_a_round_trip_through_the_database(tmp_path, registry):
    """What the automaton changed has to be what save_project writes."""
    import shutil

    from biofermentation.db import save_project

    db = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, db)

    setup = load_phases(db, PICHIA_PROJECT)
    for phase in setup.phases:
        phase.statusID = PhaseStatus.UPCOMING
        phase.start.time = phase.end.time = None

    p = dict(setup.p) | {"f_Inoc": 1.0, "f_InocStart": 1.0, "deltatsec": 2.0}
    model = get_organism("pichia_pastoris")
    state = build_state(p, model, dt=2 / 3600)
    automaton = PhaseAutomaton.from_setup(setup)
    run_steps(state, model, 7000, phases=automaton)

    save_project(db, PICHIA_PROJECT, phases=setup.phases)
    reloaded = load_phases(db, PICHIA_PROJECT).phases

    assert [ph.statusID for ph in reloaded] == [ph.statusID for ph in setup.phases]
    assert reloaded[0].end.time == pytest.approx(setup.phases[0].end.time)
    # The exponential feed wrote its starting point into the phase parameters.
    assert "FR1j" in reloaded[1].parameters


def test_steps_per_check_delays_the_transition(ecoli):
    """speedfactor > 1 lets a phase overrun its condition by up to that many steps."""
    state, model = ecoli
    phase = _phase(1, end=Condition(typeID=EndCondition.TIMER, value=0.0))
    automaton = _automaton([phase, _phase(2)])
    run_steps(state, model, 40, phases=automaton, steps_per_check=20)

    assert phase.statusID == PhaseStatus.COMPLETED
    # The end is stamped at the end of the block, not when the timer expired.
    assert phase.end.time > phase.start.time


@pytest.fixture
def saved_setup():
    """A project whose phases were stored mid-run, as load_phases returns it."""
    return load_phases(TEMPLATE_DB, PICHIA_PROJECT)


def test_a_reloaded_automaton_picks_up_the_running_phase(saved_setup):
    """processTab knows which phase was active; the automaton has to use it.

    Starting blank, it finds no PENDING phase, moves the *next* one to PENDING
    and restarts it — overwriting the start time of the phase that was really
    running and applying its actions twice.
    """
    automaton = PhaseAutomaton.from_setup(saved_setup)
    active = [
        index
        for index, phase in enumerate(saved_setup.phases)
        if phase.statusID == PhaseStatus.ACTIVE
    ]
    assert active, "the fixture project has no phase in progress"
    assert automaton.current == active[0]


def test_a_finished_project_adopts_nothing(saved_setup):
    for phase in saved_setup.phases:
        phase.statusID = PhaseStatus.COMPLETED
    assert PhaseAutomaton.from_setup(saved_setup).current is None


def test_the_running_phase_is_not_restarted_on_reload(saved_setup, ecoli):
    state, _ = ecoli
    automaton = PhaseAutomaton.from_setup(saved_setup)
    running = saved_setup.phases[automaton.current]
    started_at = running.start.time
    following = saved_setup.phases[automaton.current + 1]

    assert automaton.check_start(state) is None, "nothing may start under it"
    assert running.start.time == started_at
    assert running.statusID == PhaseStatus.ACTIVE
    assert following.statusID == PhaseStatus.UPCOMING, "the next one was pulled forward"
