"""Windows and the timer runner (plan section 4).

Headless throughout — QT_QPA_PLATFORM is offscreen, set in conftest.py. What
is tested is behaviour, not pixels: which button is enabled when, what a
signal carries, and whether the guard flag actually holds the state still.

The application object is a QApplication and only one may exist per process,
so it is session scoped. Anything that writes to a database gets its own copy
and its own window.
"""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.core.state import Namespace, SimulationState
from biofermentation.db import list_projects, load_phases
from biofermentation.gui.windows import (
    CreateProjectWindow,
    SelectProjectWindow,
    StartingScreen,
)
from biofermentation.organisms import discover_organisms, get_organism
from biofermentation.resources import copy_template, default_database

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
ECOLI_PROJECT = 716


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


# --------------------------------------------------- starting screen --


def test_the_starting_screen_only_emits(qapp):
    """It opens nothing itself, which is what makes it testable."""
    screen = StartingScreen()
    seen = []
    screen.load_project_requested.connect(lambda: seen.append("load"))
    screen.new_project_requested.connect(lambda: seen.append("new"))
    screen.exit_requested.connect(lambda: seen.append("exit"))

    screen.load_project_button.click()
    screen.new_project_button.click()
    screen.exit_button.click()
    assert seen == ["load", "new", "exit"]


# ------------------------------------------------------ load project --


def test_the_project_list_shows_what_the_database_holds(qapp, db_copy):
    window = SelectProjectWindow(db_copy)
    assert window.model.rowCount() == len(list_projects(db_copy))
    assert "MB" in window.size_label.text()


def test_a_half_written_project_cannot_be_opened(qapp, db_copy):
    """Nine projects of the production database are in that state."""
    window = SelectProjectWindow(db_copy)
    broken = [row for row in range(window.model.rowCount()) if not window.model.is_usable(row)]
    assert broken, "the template still carries the half-written projects"

    window.table.selectRow(broken[0])
    assert window.select_button.isEnabled() is False
    assert window.delete_button.isEnabled() is True, "but it can be deleted"


def test_selecting_a_usable_project_emits_its_id(qapp, db_copy):
    window = SelectProjectWindow(db_copy)
    usable = next(row for row in range(window.model.rowCount()) if window.model.is_usable(row))
    window.table.selectRow(usable)
    assert window.select_button.isEnabled()

    seen = []
    window.project_selected.connect(seen.append)
    window.select_button.click()
    assert seen == [window.model.project_at(usable)["projectID"]]


def test_nothing_is_enabled_without_a_selection(qapp, db_copy):
    window = SelectProjectWindow(db_copy)
    assert window.delete_button.isEnabled() is False
    assert window.select_button.isEnabled() is False


def test_deleting_refreshes_the_list(qapp, db_copy, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    window = SelectProjectWindow(db_copy)
    before = window.model.rowCount()
    window.table.selectRow(0)
    victim = window.model.project_at(0)["projectID"]

    window.delete_button.click()

    assert window.model.rowCount() == before - 1
    assert victim not in {p["projectID"] for p in list_projects(db_copy)}


def test_a_cancelled_delete_changes_nothing(qapp, db_copy, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel)
    )
    window = SelectProjectWindow(db_copy)
    before = window.model.rowCount()
    window.table.selectRow(0)
    window.delete_button.click()
    assert window.model.rowCount() == before


# ---------------------------------------------------- create project --


def test_only_models_with_a_registered_organism_can_be_chosen(qapp, db_copy):
    """modelTab says what exists, the registry says what can be simulated."""
    discover_organisms()
    window = CreateProjectWindow(db_copy)
    assert window.model.rowCount() > 0
    assert any(window.model.is_selectable(r) for r in range(window.model.rowCount()))


def test_create_needs_a_title_and_a_model(qapp, db_copy):
    window = CreateProjectWindow(db_copy)
    assert window.create_button.isEnabled() is False

    selectable = next(r for r in range(window.model.rowCount()) if window.model.is_selectable(r))
    window.table.selectRow(selectable)
    assert window.create_button.isEnabled() is True

    window.title_edit.setText("   ")
    assert window.create_button.isEnabled() is False


def test_creating_a_project_writes_a_complete_parameter_set(qapp, db_copy):
    window = CreateProjectWindow(db_copy)
    window.title_edit.setText("Phase 4 run")
    selectable = next(r for r in range(window.model.rowCount()) if window.model.is_selectable(r))
    window.table.selectRow(selectable)

    created = []
    window.project_created.connect(created.append)
    window.create_button.click()

    assert len(created) == 1
    project = next(p for p in list_projects(db_copy) if p["projectID"] == created[0])
    assert project["parameters"] == project["expected"] > 0
    assert project["name"] == "Phase 4 run"


def test_a_taken_name_gets_a_suffix(qapp, db_copy):
    """projectTab.name is UNIQUE; uniqueProjectname of the original."""
    existing = list_projects(db_copy)[0]["name"]
    window = CreateProjectWindow(db_copy)
    window.title_edit.setText(existing)
    selectable = next(r for r in range(window.model.rowCount()) if window.model.is_selectable(r))
    window.table.selectRow(selectable)

    created = []
    window.project_created.connect(created.append)
    window.create_button.click()

    name = next(p for p in list_projects(db_copy) if p["projectID"] == created[0])["name"]
    assert name.startswith(existing) and name != existing


# ---------------------------------------------------- timer runner --


@pytest.fixture
def runner(qapp):
    discover_organisms()
    p = dict(load_phases(TEMPLATE_DB, ECOLI_PROJECT).p) | {
        "f_Inoc": 1.0,
        "f_InocStart": 1.0,
        "deltatsec": 2.0,
    }
    model = get_organism("escherichia_coli")
    state = SimulationState(p=Namespace(p), dt=2 / 3600)
    model.initialize(state)
    return SimulationRunner(model, state, interval_ms=1)


def test_a_tick_advances_the_simulation(runner):
    runner._on_tick()
    assert runner.state.idx == 1


def test_speedfactor_is_the_number_of_steps_per_tick(runner):
    runner.set_speedfactor(7)
    runner._on_tick()
    assert runner.state.idx == 7


def test_the_guard_holds_the_state_still(runner):
    """A tick that fires while a UI callback edits must do nothing."""
    runner._on_tick()
    before = runner.state.idx

    with runner.editing() as state:
        state.p.NStw = 500.0
        runner._on_tick()
        runner._on_tick()
    assert runner.state.idx == before, "the timer wrote during an edit"

    runner._on_tick()
    assert runner.state.idx == before + 1, "and it works again afterwards"


def test_the_guard_is_released_even_on_an_exception(runner):
    with pytest.raises(ZeroDivisionError), runner.editing():
        raise ZeroDivisionError
    runner._on_tick()
    assert runner.state.idx == 1, "a failed edit must not freeze the simulation"


def test_a_failing_step_pauses_and_reports(runner):
    """A broken simulation must not take the window down with it."""

    def explode(state):
        raise RuntimeError("no")

    runner.organism.calculate_step = explode
    runner.start()
    messages = []
    runner.failed.connect(messages.append)

    runner._on_tick()

    assert runner.running is False
    assert messages and "RuntimeError" in messages[0]


def test_signals_report_every_step_and_every_block(runner):
    runner.set_speedfactor(3)
    steps, blocks = [], []
    runner.step_completed.connect(steps.append)
    runner.block_completed.connect(blocks.append)

    runner._on_tick()
    runner._on_tick()

    assert steps == [1, 2, 3, 4, 5, 6]
    assert blocks == [3, 6]


def test_the_timer_actually_runs(qapp, runner):
    runner.start()
    assert runner.running is True
    QTimer.singleShot(60, qapp.quit)
    qapp.exec()
    runner.pause()
    assert runner.state.idx > 0
    assert runner.running is False


def test_a_stop_phase_stops_the_timer(qapp, runner):
    from biofermentation.control import PhaseAutomaton, PhaseStatus, PhaseType
    from biofermentation.db.models import Condition, Phase

    phase = Phase(
        processID=1,
        projectID=1,
        statusID=PhaseStatus.UPCOMING,
        typeID=PhaseType.STOP,
        name="Stop",
        start=Condition(typeID=2),
        end=Condition(typeID=7, value=1.0),
    )
    runner.phases = PhaseAutomaton([phase])
    reasons = []
    runner.stopped.connect(reasons.append)
    runner.start()

    runner._on_tick()

    assert runner.running is False
    assert reasons == ["stop phase"]


# ------------------------------------------------------- the database --


def test_the_bundled_template_is_never_written_to(tmp_path, monkeypatch):
    """Inside a PyInstaller bundle it is read-only; the app works on a copy."""
    target = tmp_path / "own.db"
    monkeypatch.setenv("BIOFERMENTATION_DB", str(target))

    assert default_database() == target
    assert target.is_file()

    before = TEMPLATE_DB.stat().st_mtime
    copy_template(tmp_path / "second.db")
    assert TEMPLATE_DB.stat().st_mtime == before


def test_an_existing_database_is_not_overwritten(tmp_path, monkeypatch):
    target = tmp_path / "own.db"
    monkeypatch.setenv("BIOFERMENTATION_DB", str(target))
    default_database()
    marker = target.stat().st_mtime_ns

    assert default_database() == target
    assert target.stat().st_mtime_ns == marker


def test_the_windows_render_to_png(tmp_path, qapp):
    """A layout error that only shows on paint would slip past every other test."""
    from biofermentation.gui.screenshots import render

    written = render(tmp_path)
    assert len(written) == 7
    for path in written:
        assert path.is_file() and path.stat().st_size > 2000


def test_every_starting_screen_button_leads_somewhere(qapp):
    """A button that emits into nothing is worse than one that says so.

    The model configurator is not ported, so the application disables its
    button. Every other button has a target in SimulationApp.
    """
    import inspect

    from biofermentation.gui import app as app_module

    source = inspect.getsource(app_module.SimulationApp.__init__)
    screen = StartingScreen()
    signals = [name for name in dir(screen) if name.endswith("_requested")]

    connected = {name for name in signals if f"{name}.connect" in source}
    disabled = {
        name
        for name in signals
        if f"{name.removesuffix('_requested')}_button.setEnabled(False)" in source
    }
    assert set(signals) == connected | disabled, (
        f"no target and not disabled: {set(signals) - connected - disabled}"
    )
