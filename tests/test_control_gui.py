"""The Control App and its pieces (plan section 5).

Headless, like the rest of the GUI tests. The point of interest is not what
the window looks like but that every write into the simulation state goes
through the runner's guard, and that the phase grid says what the phases
actually are.
"""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from biofermentation.control import (
    EndCondition,
    PhaseAutomaton,
    PhaseStatus,
    PhaseType,
    StartCondition,
)
from biofermentation.core.runner import load_project_state
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import load_phases
from biofermentation.db.models import Condition
from biofermentation.gui.dialogs import PhaseEditor
from biofermentation.gui.widgets import (
    CONTROL_PANELS,
    ControlPanel,
    PhaseGrid,
    condition_text,
    select_data,
)
from biofermentation.gui.widgets.tex import tex_label, tex_to_html
from biofermentation.gui.windows import ControlWindow
from biofermentation.organisms import discover_organisms

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
PICHIA_PROJECT = 519


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


@pytest.fixture
def window(qapp, db_copy):
    discover_organisms()
    setup = load_phases(db_copy, PICHIA_PROJECT)
    state, organism = load_project_state(db_copy, PICHIA_PROJECT)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    runner = SimulationRunner(
        organism, state, phases=PhaseAutomaton.from_setup(setup), interval_ms=1
    )
    return ControlWindow(setup, runner, db_copy)


# ------------------------------------------------------------- TeX --


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("c_{XL}", "c<sub>XL</sub>"),
        ("gl^{-1}", "gl<sup>-1</sup>"),
        ("pH_w", "pH<sub>w</sub>"),
        (r"\vartheta_{Lw}", "ϑ<sub>Lw</sub>"),
        (r"\textit{Escherichia coli}", "Escherichia coli"),
        ("", ""),
        (None, ""),
    ],
)
def test_tex_fragments_become_rich_text(source, expected):
    assert tex_to_html(source) == expected


def test_an_unknown_command_is_left_alone_not_mangled():
    """A label reading a little raw beats one that lost a symbol."""
    assert "wobble" in tex_to_html(r"\wobble_{x}")


def test_a_label_carries_its_unit():
    assert tex_label("N_{Stw}", "min^{-1}") == "N<sub>Stw</sub> [min<sup>-1</sup>]"


# --------------------------------------------------- control panels --


def test_every_panel_builds_from_its_specification(qapp):
    for spec in CONTROL_PANELS:
        panel = ControlPanel(spec)
        assert len(panel.rows) == len(spec.fields)
        assert len(panel.switches) == len(spec.switches)


def test_the_mode_greys_out_what_it_does_not_use(qapp):
    """pO2-agitation drives the stirrer, so its setpoint is not editable."""
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "pO2-Control"))
    select_data(panel.mode_box, 1)  # pO2-agitation
    assert panel.rows["NStw"].isEnabled() is False
    assert panel.rows["FnAIRw"].isEnabled() is True

    select_data(panel.mode_box, 0)  # manual
    assert panel.rows["NStw"].isEnabled() is True


def test_loading_a_panel_emits_nothing(qapp):
    """Filling the widgets must not look like the user changed something."""
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "pH-Control"))
    seen = []
    panel.parameter_changed.connect(lambda *args: seen.append(args))
    panel.load({"Mode_pH": 1, "pHw": 6.7, "f_acid": 0, "f_alkali": 0})
    assert seen == []
    assert panel.rows["pHw"].setpoint.value() == pytest.approx(6.7)


def test_changing_a_setpoint_reports_it(qapp):
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "pH-Control"))
    panel.load({"Mode_pH": 1, "pHw": 6.7})
    seen = []
    panel.parameter_changed.connect(lambda name, value: seen.append((name, value)))
    panel.rows["pHw"].setpoint.setValue(7.2)
    assert seen == [("pHw", 7.2)]


# ----------------------------------------------------- phase panels --


def test_a_variable_condition_reads_as_one_line():
    variables = {1: {"name": "cXL", "shorttex": "c_{XL}", "tex_unit": "gl^{-1}"}}
    operators = {3: ">"}
    condition = Condition(typeID=StartCondition.VARIABLE, variableID=1, operatorID=3, value=0.0)
    assert condition_text(condition, "start", variables, operators) == "c_{XL} > 0.00 gl^{-1}"


def test_a_timer_shows_its_end_once_the_phase_runs():
    condition = Condition(typeID=EndCondition.TIMER, value=5.0, time=8.5)
    assert condition_text(condition, "end", {}, {}) == "Timer (5.00 h)"
    running = condition_text(condition, "end", {}, {}, PhaseStatus.ACTIVE)
    assert running == "t = 8.50 h (5.00 h timer)"


def test_the_grid_puts_an_arrow_between_every_pair(qapp, db_copy):
    setup = load_phases(db_copy, PICHIA_PROJECT)
    grid = PhaseGrid()
    grid.rebuild(setup.phases, {}, {}, {}, {})
    assert len(grid.panels) == len(setup.phases)
    assert len(grid.arrows) == len(setup.phases) - 1, "one fewer arrow than panels"


def test_rebuilding_the_grid_twice_does_not_double_it(qapp, db_copy):
    """rebuildGridColumns: throw it away and build again, never patch."""
    setup = load_phases(db_copy, PICHIA_PROJECT)
    grid = PhaseGrid()
    grid.rebuild(setup.phases, {}, {}, {}, {})
    grid.rebuild(setup.phases, {}, {}, {}, {})
    assert len(grid.panels) == len(setup.phases)


def test_only_the_arrow_after_the_active_phase_is_live(qapp, db_copy):
    setup = load_phases(db_copy, PICHIA_PROJECT)
    for phase in setup.phases:
        phase.statusID = PhaseStatus.UPCOMING
    setup.phases[1].statusID = PhaseStatus.ACTIVE

    grid = PhaseGrid()
    grid.rebuild(setup.phases, {}, {}, {}, {})
    enabled = [arrow.index for arrow in grid.arrows if arrow.isEnabled()]
    assert enabled == [2], "the arrow that starts phase 3"


# ---------------------------------------------------- the window --


def test_the_window_shows_the_project(window):
    assert "MyProject" in window.windowTitle()
    assert "Pichia pastoris" in window.windowTitle()
    assert len(window.phase_grid.panels) == 5


def test_a_setpoint_change_goes_through_the_guard(window, monkeypatch):
    """A tick during the write is what the guard exists for."""
    seen = []
    original = window.runner.editing

    def watched():
        seen.append("guarded")
        return original()

    monkeypatch.setattr(window.runner, "editing", watched)
    window.panels["pH-Control"].rows["pHw"].setpoint.setValue(7.1)

    assert seen == ["guarded"]
    assert window.runner.state.p["pHw"] == pytest.approx(7.1)


def test_run_and_pause_toggle_the_timer(window):
    assert window.runner.running is False
    window.run_button.click()
    assert window.runner.running is True
    assert window.run_button.text() == "Pause"
    window.run_button.click()
    assert window.runner.running is False
    assert window.run_button.text() == "Run"


def test_the_clock_follows_the_simulation(window):
    window.runner._on_tick()
    window.refresh()
    assert window.time_label.text() != "0.000"


def test_changing_the_step_width_reaches_the_state(window):
    window.dt_box.setValue(5)
    assert window.runner.state.p["deltatsec"] == 5.0
    assert window.runner.state.dt == pytest.approx(5 / 3600)


def test_adding_a_phase_extends_the_grid(window):
    before = len(window.setup.phases)
    window.phase_grid.add_button.click()
    assert len(window.setup.phases) == before + 1
    assert len(window.phase_grid.panels) == before + 1
    # The automaton has to see the same list, not a copy.
    assert window.runner.phases.phases is window.setup.phases


def test_deleting_a_phase_shrinks_the_grid(window):
    before = len(window.setup.phases)
    window.phase_grid.panels[0].delete_button.click()
    assert len(window.setup.phases) == before - 1
    assert len(window.phase_grid.panels) == before - 1


def test_the_arrow_forces_the_next_phase(window):
    for phase in window.setup.phases:
        phase.statusID = PhaseStatus.UPCOMING
    window.setup.phases[0].statusID = PhaseStatus.ACTIVE
    window.refresh_phases()

    window.phase_grid.arrows[0].click()

    assert window.setup.phases[0].statusID == PhaseStatus.COMPLETED
    assert window.setup.phases[1].statusID == PhaseStatus.PENDING
    assert window.runner.phases.current is None


def test_saving_writes_and_leaves_a_backup(window, db_copy):
    window.runner._on_tick()
    window.save()
    backup = db_copy.with_suffix(".backup.db")
    assert backup.is_file()
    assert any("Saved" in line for line in window.log_lines)


def test_saving_resumes_a_running_simulation(window):
    window.runner.start()
    window.save()
    assert window.runner.running is True


def test_the_log_tab_collects_what_happened(window):
    window.run_button.click()
    window.run_button.click()
    assert "Process started" in window.log_view.toPlainText()
    assert "Process paused" in window.log_view.toPlainText()


def test_the_variable_pool_lists_the_current_values(window):
    window.runner._on_tick()
    window.tabs.setCurrentIndex(1)
    window.refresh()
    assert window.variable_table.rowCount() > 50
    names = {
        window.variable_table.item(row, 0).text() for row in range(window.variable_table.rowCount())
    }
    assert {"cXL", "pO2", "thetaL"} <= names


# ------------------------------------------------------ the editor --


def test_cancelling_the_editor_changes_nothing(window):
    """MATLAB's editors write straight into app.Phases; this one does not."""
    phase = window.setup.phases[0]
    before = (phase.name, phase.typeID, phase.end.value)

    dialog = PhaseEditor(phase, window.setup.lookups, reservoirs=2)
    dialog.name_edit.setText("Something else")
    dialog.reject()

    assert (phase.name, phase.typeID, phase.end.value) == before


def test_accepting_the_editor_writes_back(window):
    phase = window.setup.phases[0]
    dialog = PhaseEditor(phase, window.setup.lookups, reservoirs=2)
    dialog.name_edit.setText("Renamed phase")
    assert select_data(dialog.type_box, PhaseType.PULSE_FEED)
    dialog.accept()

    assert phase.name == "Renamed phase"
    assert phase.typeID == PhaseType.PULSE_FEED
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_the_editor_only_shows_what_the_condition_type_needs(window):
    phase = window.setup.phases[0]
    dialog = PhaseEditor(phase, window.setup.lookups)
    editor = dialog.end_editor

    assert select_data(editor.type_box, EndCondition.TIMER)
    assert editor.variable_box.isVisible() is False
    assert editor.value_label.text() == "Duration [h]:"

    assert select_data(editor.type_box, EndCondition.VARIABLE)
    assert editor.value_label.text() == "Value:"


def test_select_data_survives_an_int_enum(qapp):
    """QComboBox.findData does not unwrap an IntEnum; select_data does."""
    from PySide6.QtWidgets import QComboBox

    box = QComboBox()
    box.addItem("Timer", 7)
    assert box.findData(EndCondition.TIMER) == -1, "the trap this helper exists for"
    assert select_data(box, EndCondition.TIMER) is True
    assert box.currentIndex() == 0
    assert select_data(box, 99) is False
    assert select_data(box, None) is False
