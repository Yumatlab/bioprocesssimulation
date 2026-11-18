"""The data limit: what a project may hold, and what the window does near it.

The limit itself is a choice on measurements (core/data_budget.py). The
tests take a small limit, so that a few hundred steps reach it, and check the
counting against what a save really writes.
"""

import shutil
from pathlib import Path

import pytest

from biofermentation.core import data_budget
from biofermentation.core.data_budget import stored_values

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
PROJECT = 716


# ------------------------------------------------------- the counting --


def test_every_step_stored_counts_every_step():
    assert stored_values(0, 100, 1, 58) == 100 * 58


def test_a_coarser_resolution_counts_one_step_in_n_and_the_last():
    # Indices 0 to 99: 0, 10, ..., 90 and the last, 99.
    assert stored_values(0, 100, 10, 58) == 11 * 58
    # Indices 0 to 100: the last is a multiple itself.
    assert stored_values(0, 101, 10, 58) == 11 * 58


def test_what_was_stored_before_counts_whole():
    """Thinned when it was saved, it is what it is now."""
    # New indices 500 to 599: 500, 510, ..., 590 and the last, 599.
    assert stored_values(500, 600, 10, 58) == (500 + 11) * 58


def test_the_limit_leaves_room_for_a_teaching_run():
    """14 h of E. coli at Δt = 2 s, every step stored — a run the user had."""
    teaching = stored_values(0, 14 * 1800, 1, 58)
    assert data_budget.share_of_limit(teaching) < data_budget.WARN_SHARE


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


@pytest.mark.parametrize("every", [1, 7, 10])
def test_the_count_is_what_a_save_writes(db_copy, every):
    """No NaN in a fresh E. coli run: the upper bound is met exactly."""
    from biofermentation.core.runner import load_project_state, run_steps
    from biofermentation.db import load_phases
    from biofermentation.db.models import VariableSeries
    from biofermentation.db.project import save_project

    setup = load_phases(db_copy, PROJECT)
    state, model = load_project_state(db_copy, PROJECT)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    run_steps(state, model, 120)
    trimmed = state.trimmed()
    series = VariableSeries(t=trimmed.get("t"), v=trimmed, real_t=[""] * (state.idx + 1))
    result = save_project(db_copy, PROJECT, p=dict(state.p), series=series, storage_interval=every)
    names = sum(1 for name in setup.lookups.stored_variables if name in state.v)
    assert result["values"] == stored_values(0, state.idx + 1, every, names)


# --------------------------------------------------------- the window --


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, db_copy, monkeypatch):
    from biofermentation.control import PhaseAutomaton
    from biofermentation.core.runner import load_project_state
    from biofermentation.core.simulation_runner import SimulationRunner
    from biofermentation.db import load_phases
    from biofermentation.gui.windows import ControlWindow
    from biofermentation.organisms import discover_organisms

    discover_organisms()
    setup = load_phases(db_copy, PROJECT)
    state, organism = load_project_state(db_copy, PROJECT)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    window = ControlWindow(setup, runner, db_copy)
    # 100 steps of 58 values: 90 % after 90 steps, 99 % after 99.
    monkeypatch.setattr(data_budget, "MAX_STORED_VALUES", 100 * 58)
    window.asked = []
    window.told = []
    window.answer = True
    monkeypatch.setattr(
        window,
        "_ask_past_data_warning",
        lambda values, share: window.asked.append(share) or window.answer,
    )
    monkeypatch.setattr(
        window, "_tell_data_limit_reached", lambda values, share: window.told.append(share)
    )
    yield window
    window.runner.pause()
    window.close()


def _block(window, steps: int) -> None:
    """One timer block as the runner computes it, then the window's refresh."""
    from biofermentation.core.runner import run_steps

    run_steps(window.runner.state, window.runner.organism, steps)
    window.refresh()


def test_below_ninety_percent_nothing_happens(window):
    window.toggle_run()
    _block(window, 80)
    assert window.runner.running
    assert window.asked == [] and window.told == []


def test_at_ninety_percent_the_run_pauses_and_asks(window):
    window.answer = False
    window.toggle_run()
    _block(window, 90)
    assert not window.runner.running
    assert len(window.asked) == 1 and window.asked[0] >= 0.9
    assert any("paused at" in line and "data limit" in line for line in window.log_lines)


def test_confirming_the_warning_carries_on_and_does_not_ask_again(window):
    window.toggle_run()
    _block(window, 90)
    assert window.runner.running
    _block(window, 4)
    assert len(window.asked) == 1
    assert window.runner.running


def test_declining_keeps_it_paused_and_run_asks_again(window):
    window.answer = False
    window.toggle_run()
    _block(window, 90)
    assert not window.runner.running
    window.toggle_run()  # Run pressed: asked once more, declined again
    assert len(window.asked) == 2
    assert not window.runner.running
    window.answer = True
    window.toggle_run()
    assert window.runner.running


def test_at_ninety_nine_percent_the_run_stops_and_does_not_start_again(window):
    window.toggle_run()
    _block(window, 90)
    _block(window, 9)
    assert not window.runner.running
    assert len(window.told) == 1
    window.toggle_run()
    assert not window.runner.running
    assert len(window.told) == 2
    assert any("stopped at" in line for line in window.log_lines)


def test_a_coarser_resolution_runs_longer(window, monkeypatch):
    monkeypatch.setattr(window.settings, "storage_interval", 10)
    window.toggle_run()
    _block(window, 500)  # about 51 stored steps: half the limit
    assert window.runner.running
    assert window.asked == []


def test_a_reopened_project_is_counted_as_the_database_holds_it(db_copy):
    """Saved thinned, reopened, run on, saved again: the count is the rows."""
    from biofermentation.core.runner import load_project_state, run_steps
    from biofermentation.db import get_connection, load_phases
    from biofermentation.db.models import VariableSeries
    from biofermentation.db.project import save_project

    def session(steps: int) -> int:
        state, model = load_project_state(db_copy, PROJECT)
        opened = state.idx + 1 if state.idx > 0 else 0
        state.p["f_Inoc"] = 1.0
        state.p["f_InocStart"] = 1.0
        run_steps(state, model, steps)
        trimmed = state.trimmed()
        series = VariableSeries(t=trimmed.get("t"), v=trimmed, real_t=[""] * (state.idx + 1))
        save_project(db_copy, PROJECT, p=dict(state.p), series=series, storage_interval=5)
        names = load_phases(db_copy, PROJECT).lookups.stored_variables
        return stored_values(opened, state.idx + 1, 5, sum(1 for n in names if n in state.v))

    session(103)
    expected = session(57)
    with get_connection(db_copy, readonly=True) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM dataTab d JOIN timeTab t ON t.timeID = d.timeID"
            " WHERE t.projectID = ?",
            (PROJECT,),
        ).fetchone()[0]
    assert rows == expected
