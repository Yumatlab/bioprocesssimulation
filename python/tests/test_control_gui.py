"""The Control App and its pieces (plan section 5).

Headless, like the rest of the GUI tests. The point of interest is not what
the window looks like but that every write into the simulation state goes
through the runner's guard, and that the phase grid says what the phases
actually are.
"""

import itertools
import re
import shutil
from pathlib import Path

import numpy as np
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
from biofermentation.gui.panel_layout import (
    BUNDLED_LAYOUT,
    DEFAULT_MODE_SELECTOR,
    MODE_SELECTORS,
    LayoutError,
    fallback,
    load_layout,
    normalise,
    parse_grid,
    parse_mode_selector,
)
from biofermentation.gui.widgets import (
    CONTROL_PANELS,
    ControlPanel,
    PhaseGrid,
    RotarySelector,
    SegmentedControl,
    ToggleSwitch,
    condition_text,
    select_data,
)
from biofermentation.gui.widgets.control_panel import MANUAL_MODE
from biofermentation.gui.widgets.controller_view import SHARE_COLORS
from biofermentation.gui.widgets.indicators import GREEN, RED
from biofermentation.gui.widgets.log_view import OPERATION_EVENT
from biofermentation.gui.widgets.tex import tex_label, tex_to_html
from biofermentation.gui.windows import ControlWindow
from biofermentation.gui.windows.control_app import PANEL_SPACING
from biofermentation.organisms import discover_organisms, get_organism

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


def test_a_loaded_switch_neither_moves_nor_reports(qapp):
    """Opening a project must not look like somebody threw the switches."""
    switch = ToggleSwitch("Acid")
    seen = []
    switch.toggled.connect(seen.append)

    switch.set_checked(True)
    assert switch.is_checked() is True
    assert switch.switch.travel == 1.0, "it should be over already, not sliding"
    assert seen == []


def test_clicking_a_switch_reports_it_and_slides(qapp):
    switch = ToggleSwitch("Acid")
    seen = []
    switch.toggled.connect(seen.append)

    switch.switch.click()
    assert seen == [True]
    # The animation carries the knob; the state is there the moment it starts.
    assert switch.is_checked() is True


def test_the_selector_answers_the_calls_a_dropdown_would(qapp):
    """select_data and the panels must not care which of the two they hold."""
    selector = SegmentedControl()
    for value, text in ((0, "Manual"), (1, "Auto")):
        selector.addItem(text, value)

    assert selector.count() == 2
    assert selector.currentIndex() == 0
    assert selector.currentData() == 0
    assert selector.findData(1) == 1
    assert selector.findData(7) == -1
    assert select_data(selector, 1) is True
    assert selector.currentData() == 1
    assert selector.currentText() == "Auto"


def test_the_selector_reports_a_change_once(qapp):
    selector = SegmentedControl()
    selector.addItem("Manual", 0)
    selector.addItem("Auto", 1)
    seen = []
    selector.currentIndexChanged.connect(seen.append)

    selector.setCurrentIndex(1)
    selector.setCurrentIndex(1)  # the same key again is not a change
    assert seen == [1]


def test_the_mode_greys_out_what_it_does_not_use(qapp):
    """pO2-agitation drives the stirrer, so its setpoint is not editable."""
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "pO2-Control"))
    select_data(panel.mode_selector, 1)  # pO2-agitation
    assert panel.rows["NStw"].isEnabled() is False
    assert panel.rows["FnAIRw"].isEnabled() is True

    select_data(panel.mode_selector, 0)  # manual
    assert panel.rows["NStw"].isEnabled() is True


def test_the_feed_panel_holds_the_substrate_concentration(qapp):
    """Closed loop feeds against cS{n}Lw — the reason the mode exists.

    The panel had FR1w and FR1max and nothing to aim at; the setpoint the
    controller actually reads could only be reached through the database.
    """
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "Feed Control"))
    assert "cS{n}Lw" in panel.rows

    seen = []
    panel.parameter_changed.connect(lambda name, value: seen.append((name, value)))
    panel.rows["cS{n}Lw"].setpoint.setValue(2.5)
    assert seen == [("cS1Lw", 2.5)], "the reservoir number belongs in the name"

    select_data(panel.mode_selector, 1)  # closed loop
    assert panel.rows["cS{n}Lw"].isEnabled() is True
    assert panel.rows["FR{n}w"].isEnabled() is False
    select_data(panel.mode_selector, 0)  # manual
    assert panel.rows["cS{n}Lw"].isEnabled() is False
    assert panel.rows["FR{n}w"].isEnabled() is True


def test_the_feed_maximum_is_shown_but_not_typed_into(qapp):
    """It belongs to the reservoir, not to the moment — as in the original."""
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "Feed Control"))
    assert panel.rows["FR{n}max"].setpoint.isReadOnly() is True
    assert panel.rows["FR{n}w"].setpoint.isReadOnly() is False


def test_the_feed_panel_follows_its_reservoir(qapp):
    """Every field of the panel belongs to one reservoir; R_feed says which."""
    spec = next(s for s in CONTROL_PANELS if s.title == "Feed Control")
    panel = ControlPanel(spec, reservoirs=3)
    assert panel.reservoir_selector is not None

    panel.load({"Mode_feed": 1, "R_feed": 2, "cS2Lw": 1.5, "FR2w": 0.2, "FR2max": 0.9})
    assert panel.reservoir == 2
    assert panel.rows["cS{n}Lw"].setpoint.value() == pytest.approx(1.5)
    assert "S2Lw" in panel.rows["cS{n}Lw"].setpoint_caption.text()

    seen = []
    panel.parameter_changed.connect(lambda name, value: seen.append((name, value)))
    panel.rows["FR{n}w"].setpoint.setValue(0.3)
    assert seen == [("FR2w", 0.3)]


def test_one_reservoir_needs_no_selector(qapp):
    """A choice of one is not a choice; the original shows R1 and gets on."""
    spec = next(s for s in CONTROL_PANELS if s.title == "Feed Control")
    panel = ControlPanel(spec, reservoirs=1)
    assert panel.reservoir_selector is None
    assert panel.reservoir == 1


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
    assert condition_text(condition, "start", variables, operators) == "c_{XL} > 0.000 gl^{-1}"


def test_a_condition_keeps_the_decimals_it_has():
    """Three places at least, and more where the number carries more.

    Two places showed a 0.005 h timer as "0.00 h" — a condition that reads as
    "never" and fires on the next step.
    """
    variables = {1: {"name": "cXL", "shorttex": "c_{XL}", "tex_unit": "gl^{-1}"}}
    operators = {3: ">"}
    condition = Condition(typeID=StartCondition.VARIABLE, variableID=1, operatorID=3, value=0.0625)
    assert condition_text(condition, "start", variables, operators) == "c_{XL} > 0.0625 gl^{-1}"
    assert (
        condition_text(Condition(typeID=EndCondition.TIMER, value=0.005), "end", {}, {})
        == "Timer (0.005 h)"
    )


def test_a_timer_shows_its_end_once_the_phase_runs():
    condition = Condition(typeID=EndCondition.TIMER, value=5.0, time=8.5)
    assert condition_text(condition, "end", {}, {}) == "Timer (5.000 h)"
    running = condition_text(condition, "end", {}, {}, PhaseStatus.ACTIVE)
    assert running == "t = 8.500 h (5.000 h timer)"

    # The measured end is rounded; the timer that was set is not. An
    # accumulated time carries its own arithmetic after the third place.
    measured = Condition(typeID=EndCondition.TIMER, value=0.005, time=8.502222222223)
    assert (
        condition_text(measured, "end", {}, {}, PhaseStatus.COMPLETED)
        == "t = 8.502 h (0.005 h timer)"
    )


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
    upcoming = next(
        index
        for index, phase in enumerate(window.setup.phases)
        if phase.statusID == PhaseStatus.UPCOMING
    )
    window.phase_grid.panels[upcoming].delete_button.click()
    assert len(window.setup.phases) == before - 1
    assert len(window.phase_grid.panels) == before - 1


def test_a_running_or_finished_phase_cannot_be_deleted(window):
    """Deleting one would leave a process history that never happened."""
    for phase, panel in zip(window.setup.phases, window.phase_grid.panels, strict=True):
        protected = phase.statusID in (PhaseStatus.ACTIVE, PhaseStatus.COMPLETED)
        assert panel.delete_button.isEnabled() is not protected

    before = len(window.setup.phases)
    completed = next(
        index
        for index, phase in enumerate(window.setup.phases)
        if phase.statusID == PhaseStatus.COMPLETED
    )
    window.phase_grid.panels[completed].delete_button.click()
    assert len(window.setup.phases) == before


def test_a_running_or_finished_phase_cannot_be_edited(window):
    """The automaton has already read it; a change now rewrites the record.

    A completed phase applied its parameters and its end condition decided
    when it stopped. Editing either afterwards would leave a plan that does
    not describe the run that happened.
    """
    for phase, panel in zip(window.setup.phases, window.phase_grid.panels, strict=True):
        protected = phase.statusID in (PhaseStatus.ACTIVE, PhaseStatus.COMPLETED)
        assert panel.edit_button.isEnabled() is not protected, phase.name
        if protected:
            assert "cannot be edited" in panel.edit_button.toolTip()


def test_a_pending_phase_is_editable_again_once_the_process_stands(window):
    """The two reasons a button is dead say different things."""
    upcoming = next(
        panel
        for phase, panel in zip(window.setup.phases, window.phase_grid.panels, strict=True)
        if phase.statusID not in (PhaseStatus.ACTIVE, PhaseStatus.COMPLETED)
    )
    assert upcoming.edit_button.isEnabled() is True

    window.phase_grid.set_editable(False)
    assert upcoming.edit_button.isEnabled() is False
    assert "Pause the process" in upcoming.edit_button.toolTip()

    window.phase_grid.set_editable(True)
    assert upcoming.edit_button.isEnabled() is True


def test_a_phase_that_changes_a_mode_moves_the_panel(window):
    """Project_3 set Mode_feed to closed loop through an "Update Parameter
    Set" phase, and the tab went on showing Manual.

    A phase writes straight into p. refresh() only fills in measured values,
    and ControlPanel.load was otherwise reached only through a dialog — so
    nothing re-read the setpoints the automaton had just changed. The tab is
    the one place someone looks to find out what the process is doing.
    """
    phase = window.setup.phases[-1]
    phase.statusID = PhaseStatus.UPCOMING
    phase.typeID = PhaseType.PARAMETER_UPDATE
    panel = window.panels["Feed Control"]
    state = window.runner.state
    state.p["Mode_feed"] = 0.0
    state.p["pHw"] = 6.0
    window.load_panels()
    assert panel.mode_selector.currentData() == 0

    phase.parameters = {"Mode_feed": 1.0, "pHw": 7.4}
    with window.runner.editing() as editable:
        for name, value in phase.parameters.items():
            editable.p[name] = value
    window._phase_changed(len(window.setup.phases) - 1)

    assert panel.mode_selector.currentData() == 1, "the mode selector followed"
    ph_row = window.panels["pH-Control"].rows["pHw"]
    assert ph_row.setpoint.value() == pytest.approx(7.4), "and so did the setpoint"


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
    window.save(announce=False)
    backup = db_copy.with_suffix(".backup.db")
    assert backup.is_file()
    assert any("Saved" in line for line in window.log_lines)


def test_saving_resumes_a_running_simulation(window):
    window.runner.start()
    window.save(announce=False)
    assert window.runner.running is True


def test_the_log_tab_collects_what_happened(window):
    """Starting and pausing are recorded, and shown once operations are on.

    They are operations, not process events: the log starts without them,
    because what someone reads it for is what the process did. Recorded all
    the same — ticking the box shows the whole session, not only what came
    after the tick.
    """
    window.run_button.click()
    window.run_button.click()
    written = [entry for entry in window.log_view.entries if entry.event_type == OPERATION_EVENT]
    assert [entry.message for entry in written] == ["Process started", "Process paused"]

    assert "Process paused" not in window.log_view.view.toPlainText()
    window.log_view.operation_checkbox.setChecked(True)
    text = window.log_view.view.toPlainText()
    assert "Process started" in text
    assert "Process paused" in text


def test_a_log_entry_carries_a_title_a_clock_and_the_process_time(window):
    """Point 8: the log reads like a terminal, not like a list of sentences."""
    window.note("Something happened", "Phase Event")
    entry = window.log_view.entries[-1]
    assert entry.event_type == "Phase Event"
    assert entry.message == "Something happened"
    assert entry.process_time == pytest.approx(float(window.runner.state.v.t[0]))
    # dd.mm.yyyy hh:mm:ss.mmm
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}\.\d{3}", entry.datetime)

    line = window.log_view.view.toPlainText().splitlines()[-1]
    assert "Phase Event" in line
    assert "Something happened" in line
    assert entry.datetime in line


def test_a_setpoint_turned_on_a_panel_counts_as_a_parameter_update(window):
    """Es war der häufigste Fall und der einzige, den der Filter nicht sah.

    _set_parameter nahm den Vorgabetyp und landete unter "Process". Wer den
    Haken "Include parameter updates" entfernte, sah die Sollwerte, die er
    gerade selbst am Panel gedreht hatte, weiterhin.
    """
    from biofermentation.gui.widgets.log_view import PARAMETER_EVENT

    window._set_parameter("pHw", 6.9)
    entry = window.log_view.entries[-1]
    assert entry.event_type == PARAMETER_EVENT
    assert "pHw" in entry.message

    window.log_view.parameter_checkbox.setChecked(False)
    assert "pHw" not in window.log_view.view.toPlainText()


def test_the_log_can_hide_parameter_updates(window):
    window.note("Parameter KP_pH has been changed", "Parameter Value Change")
    window.note("Process paused", "Process")
    assert "KP_pH" in window.log_view.view.toPlainText()

    window.log_view.parameter_checkbox.setChecked(False)
    text = window.log_view.view.toPlainText()
    assert "KP_pH" not in text
    assert "Process paused" in text


def test_the_variable_pool_lists_the_current_values(window):
    window.runner._on_tick()
    window.tabs.setCurrentWidget(window.variable_pool)
    window.refresh()

    pool = window.variable_pool
    names = {pool.table.item(row, 0).text() for row in range(pool.table.rowCount())}
    assert names == set(pool.checked())
    assert pool.table.rowCount() == 10, "ten variables are ticked by default"

    # The pump rates and volumes read straight out of v.
    assert pool.readouts["VL"].text() != "—"
    assert "FR3" not in pool.readouts, "project 519 has fewer reservoirs than that"


def test_the_variable_pool_shows_a_trend_arrow(window):
    from biofermentation.gui.widgets.variable_pool import FALLING, FLAT, RISING, trend_arrow

    time = np.arange(10, dtype=float)
    assert trend_arrow(time, time * 2) == RISING
    assert trend_arrow(time, -time * 2) == FALLING
    assert trend_arrow(time, np.full(10, 3.0)) == FLAT
    assert trend_arrow(time, np.full(10, np.nan)) == FLAT


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


def test_the_editor_greys_out_what_the_condition_type_does_not_use(window):
    """Greyed, not hidden — hiding reads as a missing dropdown."""
    phase = window.setup.phases[0]
    dialog = PhaseEditor(phase, window.setup.lookups)
    editor = dialog.end_editor

    assert select_data(editor.type_box, EndCondition.TIMER)
    assert editor.variable_box.isEnabled() is False
    assert editor.variable_box.count() > 0, "still populated, just not usable"
    assert editor.value_label.text() == "Duration [h]:"

    assert select_data(editor.type_box, EndCondition.VARIABLE)
    assert editor.variable_box.isEnabled() is True
    assert editor.value_label.text() == "Value:"


def test_the_variable_entries_are_readable(window):
    """cXL (c_{XL}) is not something to put in front of a user."""
    dialog = PhaseEditor(window.setup.phases[0], window.setup.lookups)
    entries = [
        dialog.start_editor.variable_box.itemText(i)
        for i in range(dialog.start_editor.variable_box.count())
    ]
    assert not any("{" in entry or "}" in entry for entry in entries)
    assert "cXL [gl^-1]" in entries


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


def test_a_stop_phase_has_no_end_condition(window):
    """The process is standing, so no condition on it could ever be met."""
    from biofermentation.control import PhaseType

    phase = window.setup.phases[-1]
    dialog = PhaseEditor(phase, window.setup.lookups, reservoirs=2)
    assert select_data(dialog.type_box, PhaseType.STOP)
    assert dialog.end_editor.isVisibleTo(dialog) is False

    dialog.accept()
    assert phase.end.typeID is None
    assert phase.end.value is None


def test_the_reservoir_only_shows_for_a_feed_phase(window):
    from biofermentation.control import PhaseType

    dialog = PhaseEditor(window.setup.phases[-1], window.setup.lookups, reservoirs=2)
    for phase_type, expected in (
        (PhaseType.PULSE_FEED, True),
        (PhaseType.EXPONENTIAL_FEED, True),
        (PhaseType.MANUAL, False),
        (PhaseType.PARAMETER_UPDATE, False),
        (PhaseType.STOP, False),
    ):
        assert select_data(dialog.type_box, phase_type)
        assert dialog.reservoir_box.isVisibleTo(dialog) is expected, phase_type.name


def test_the_inoculate_button_toggles_before_the_run(window):
    """A setting before the first step, a one-shot event during the run."""
    state = window.runner.state
    state.a["inoc_occ"] = 0
    state.idx = 0
    window.refresh()

    assert window.inoculate_button.isCheckable() is True
    window.inoculate_button.setChecked(True)
    window.inoculate()
    assert state.p["f_Inoc"] == 1.0

    window.inoculate_button.setChecked(False)
    window.inoculate()
    assert state.p["f_Inoc"] == 0.0, "it must be possible to take it back"


def test_the_inoculate_button_fires_once_during_the_run(window):
    state = window.runner.state
    state.p["f_Inoc"] = 0.0
    state.a["inoc_occ"] = 0
    window.runner._on_tick()
    window.refresh()

    assert window.inoculate_button.isCheckable() is False
    assert window.inoculate_button.isEnabled() is True

    window.inoculate()
    assert state.p["f_Inoc"] == 1.0

    state.a["inoc_occ"] = 1
    window.refresh()
    assert window.inoculate_button.isEnabled() is False


def test_the_plot_ticks_point_outwards(qapp):
    from biofermentation.db.plots import PlotTemplate, PlotVariable
    from biofermentation.gui.widgets.plot_view import TICK_LENGTH, MultiAxisPlot

    template = PlotTemplate(
        templateID=0,
        variables=[PlotVariable(variableID=1, name="a", selected=True, color=(0, 0, 0))],
    )
    plot = MultiAxisPlot()
    plot.set_template(template)
    assert TICK_LENGTH > 0
    for axis in [*plot._axes, plot.bottom_axis]:
        assert axis.style["tickLength"] == TICK_LENGTH


def test_the_mode_selector_fills_the_panel(window):
    """It stopped at its own size hint and left a gap beside it."""
    _laid_out(window)
    for title, panel in window.panels.items():
        assert panel.mode_selector.width() >= panel.width() - 30, title


def test_only_the_knob_goes_without_a_lamp(window):
    """A key says which mode is chosen, the lamp whether it is controlling —
    two questions. The knob answers both itself: its dot is green for a
    control mode and red for hand control, so it needs no lamp."""
    for title, panel in window.panels.items():
        knob = isinstance(panel.mode_selector, RotarySelector)
        assert (panel.lamp is None) == knob, title


def test_the_lamp_is_green_once_the_loop_is_not_on_hand_control(qapp):
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "pH-Control"))
    select_data(panel.mode_selector, MANUAL_MODE)
    panel.apply_mode()
    assert panel.lamp.color() == RED
    select_data(panel.mode_selector, 1)
    panel.apply_mode()
    assert panel.lamp.color() == GREEN


def test_the_mode_selector_shows_every_mode_at_once(window):
    """That is the point of it: no mode hides behind a click."""
    for title, panel in window.panels.items():
        selector = panel.mode_selector
        assert selector.count() == len(panel.spec.modes), title
        if not isinstance(selector, SegmentedControl):
            continue
        cells = selector._cells()
        assert len(cells) == selector.count(), title
        for index, cell in cells.items():
            assert cell.right() <= selector.width() + 1, f"{title}: key {index} runs off"
            assert cell.bottom() <= selector.height() + 1, f"{title}: key {index} is cut off"


def test_the_keys_stand_on_one_row_in_the_panel_they_are_given(qapp):
    """Five modes in a quarter-width panel was what wrapped, four times over.

    content_width() asks for the one-row width at the tightest padding, so the
    column is wide enough by construction.
    """
    spec = next(s for s in CONTROL_PANELS if s.title == "pO2-Control")
    panel = ControlPanel(spec, mode_selector="keys")
    panel.resize(panel.content_width(), panel.sizeHint().height())
    panel.show()
    QApplication.processEvents()

    selector = panel.mode_selector
    assert len(selector._rows()) == 1, "the keys wrapped in the width asked for"
    assert selector.MIN_PADDING <= selector._padding(selector.width()) <= selector.PADDING


def test_clicking_a_mode_key_reports_the_mode_behind_it(qapp):
    """The keys carry the numbers parameter_controlmodesTab stores."""
    panel = ControlPanel(next(s for s in CONTROL_PANELS if s.title == "pO2-Control"))
    seen = []
    panel.parameter_changed.connect(lambda name, value: seen.append((name, value)))
    panel.mode_selector.setCurrentIndex(3)  # Gasmix
    assert seen == [("Mode_pO2", 3.0)]
    assert panel.current_mode() == 3


def _laid_out(window):
    """Geometry is only real once the window has been through a layout pass."""
    window.resize(1420, 700)
    window.show()
    QApplication.processEvents()
    return window


def test_the_signal_lights_sit_in_the_menu_bar(window):
    """They used to head the run column, below the tab bar with a strip of
    nothing above them — while the menu bar ran the whole width with four
    entries on it."""
    from PySide6.QtCore import Qt

    corner = window.menuBar().cornerWidget(Qt.Corner.TopRightCorner)
    assert corner is not None
    for name, lamp in window.lamps.items():
        assert corner.isAncestorOf(lamp), name


def test_the_panels_sit_where_the_layout_file_says(window):
    """The arrangement comes out of a text file, not out of the window."""
    layout = window.control_options.layout()
    for title, place in window.placements.items():
        index = layout.indexOf(window.panels[title])
        assert index >= 0, title
        position = (place.row, place.column, place.row_span, place.column_span)
        assert layout.getItemPosition(index) == position, title
    assert window._layout_problem == "", window._layout_problem


def test_every_column_is_the_same_width_and_full_height(window):
    """Four equal columns, each filled from the top of the tab to the bottom.

    The two panels sharing the fourth column split it into equal halves; the
    three others are one panel from top to bottom.
    """
    _laid_out(window)
    widths = [panel.width() for panel in window.panels.values()]
    assert max(widths) - min(widths) <= 1

    full = [
        window.panels[title]
        for title, place in window.placements.items()
        if place.row_span == 2
    ]
    half = [
        window.panels[title]
        for title, place in window.placements.items()
        if place.row_span == 1
    ]
    assert len({panel.height() for panel in half}) == 1, "the halves differ"
    tallest = max(panel.height() for panel in full)
    assert abs(sum(panel.height() for panel in half) + PANEL_SPACING - tallest) <= 2


def test_a_switch_is_as_wide_as_one_field(window):
    """Label and switch in one slot — not stretched across the whole panel."""
    for title, panel in window.panels.items():
        for name, switch in panel.switches.items():
            field = next(iter(panel.rows.values())).setpoint.width()
            assert switch.width() <= field * 2, f"{title}/{name}"


def test_no_switch_carries_a_lamp(window):
    """The switch is grey when off and green when on; a lamp repeats that."""
    for panel in window.panels.values():
        for switch in panel.switches.values():
            assert not hasattr(switch, "lamp")


def test_every_value_box_in_the_tab_is_the_same_width(window):
    """A lone setpoint used to take the whole panel, one with a measured value
    beside it half of it — two widths in one column of fields."""
    widths = {
        row.setpoint.width() for panel in window.panels.values() for row in panel.rows.values()
    }
    assert len(widths) == 1, sorted(widths)


def test_the_control_window_fits_a_normal_screen(window):
    """1440 is the narrowest screen this is meant for.

    How wide the panels want to be is not a number this project controls: a
    QDoubleSpinBox sizes itself to the widest text its range allows, and the
    range is plus or minus a billion drawn in whatever font the system uses.
    Measured at 1174 px on macOS and 1538 on a Windows runner — with the same
    layout file.

    So the window does not promise to be wide enough for its contents; it
    promises to fit the screen, and Control Options scrolls when the two
    disagree. That is what this checks, and it is the reason the tab sits in
    a scroll area.
    """
    assert window.minimumSizeHint().width() <= 1440
    assert window.width() <= 1440


def test_pressing_inoculate_during_a_run_disables_it_at_once(window):
    """The press is the feedback that it was taken — not the next step."""
    state = window.runner.state
    state.p["f_Inoc"] = 0.0
    state.a["inoc_occ"] = 0
    window.runner._on_tick()
    window.refresh()
    assert window.inoculate_button.isEnabled() is True

    window.inoculate_button.click()
    assert window.inoculate_button.isEnabled() is False
    assert state.p["f_Inoc"] == 1.0

    # And it stays dead once the step has actually done it.
    state.a["inoc_occ"] = 1
    window.refresh()
    assert window.inoculate_button.isEnabled() is False


def test_the_open_loop_parameters_go_into_the_log(window):
    """Point 2: without them there is no telling afterwards what the feed
    profile was computed from."""
    from biofermentation.control import PhaseType

    state = window.runner.state
    phase = next(p for p in window.setup.phases if p.typeID == PhaseType.EXPONENTIAL_FEED)
    index = window.setup.phases.index(phase)

    window.runner.phases._exponential_feed(state, index)
    window._drain_phase_log()

    entry = next(e for e in window.log_view.entries if e.message.startswith("Open loop feed"))
    assert entry.event_type == "Phase Information"
    for name in ("qXpX1w", "qS1pXm", "yXpS1gr", "cS1R1", "VLj", "cXLj", "t1j", "FR1j"):
        assert name in entry.message, name
    # And it reaches the view as more than one line.
    assert entry.message.count("\n") >= 8


def test_the_parameters_dialog_can_hide_what_cannot_be_edited(window):
    """Point 5 of the third round."""
    from biofermentation.gui.dialogs import ParameterDialog

    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=True)
    locked = [w for w, _, editable in dialog._rows if not editable]
    live = [w for w, _, editable in dialog._rows if editable]
    assert locked and live

    dialog.editable_only.setChecked(True)
    assert not any(w.isVisibleTo(dialog) for w in locked)
    assert all(w.isVisibleTo(dialog) for w in live)

    dialog.editable_only.setChecked(False)
    assert all(w.isVisibleTo(dialog) for w in locked)


def test_the_filter_and_the_tick_box_work_together(window):
    from biofermentation.gui.dialogs import ParameterDialog

    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=True)
    dialog.editable_only.setChecked(True)
    dialog.search.setText("cS1L0")
    assert not any(w.isVisibleTo(dialog) for w, hay, _ in dialog._rows if "cs1l0" in hay), (
        "cS1L0 is read once and must stay hidden whatever is searched for"
    )


def test_a_phase_transition_is_logged_once(window):
    """The window used to write its own line next to the automaton's."""
    automaton = window.runner.phases
    automaton.log.clear()
    automaton._drained = 0
    window.log_view.entries.clear()

    automaton._note("Batch Phase [Phase 1] started at t = 0.000 h")
    window._phase_changed(0)

    started = [e for e in window.log_view.entries if "started at t" in e.message]
    assert len(started) == 1
    assert started[0].event_type == "Phase Event"


def test_a_feed_summary_is_information_not_an_event(window):
    automaton = window.runner.phases
    automaton.log.clear()
    automaton._drained = 0
    window.log_view.entries.clear()

    automaton._note("Open loop feed R1\n  qXpX1w = 0.1 1/h")
    window._drain_phase_log()
    assert window.log_view.entries[-1].event_type == "Phase Information"


def test_saving_says_so_in_a_box(window, monkeypatch):
    """The status line and the button flash were both missed."""
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda parent, title, text: shown.append((title, text))
    )
    window.save()

    assert len(shown) == 1
    title, text = shown[0]
    assert title == "Project saved"
    assert window.setup.info.name in text
    assert "time points" in text
    assert "Backup:" in text


def test_an_automatic_save_does_not_stop_to_be_acknowledged(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(args))
    window.save(announce=False)
    assert shown == []


# ------------------------------------------------------- the layout file --

TITLES = ["pH-Control", "Temperature-Control", "pO2-Control", "Liquid Weight", "Feed Control"]


def test_the_bundled_layout_is_the_one_the_window_draws():
    """The file is the arrangement — not a copy of something in the code."""
    layout, problem = load_layout(TITLES, BUNDLED_LAYOUT)
    places = layout.places
    assert problem == ""
    assert set(places) == set(TITLES)
    assert places["pO2-Control"].column == 2
    assert places["Liquid Weight"].row == 0
    assert places["Feed Control"].row == 1
    assert places["Feed Control"].column == places["Liquid Weight"].column
    assert set(layout.mode_selectors) == set(TITLES)
    assert set(layout.mode_selectors.values()) <= set(MODE_SELECTORS)
    # What the bundled file asks for: the knob where there are five modes.
    assert layout.selector_for("pO2-Control") == "rotary"
    assert layout.selector_for("pH-Control") == "keys"


def test_one_name_chooses_for_every_panel():
    """Keys or a knob: taste, not wiring — both answer the same calls."""
    assert parse_mode_selector("rotary", TITLES) == dict.fromkeys(TITLES, "rotary")
    assert parse_mode_selector(None, TITLES) == dict.fromkeys(TITLES, DEFAULT_MODE_SELECTOR)


def test_a_mapping_names_the_exceptions():
    """Five modes are a different problem from two, and may want the knob
    while the rest keep their keys."""
    chosen = parse_mode_selector({"default": "keys", "pO2": "rotary"}, TITLES)
    assert chosen["pO2-Control"] == "rotary"
    assert set(chosen.values()) == {"keys", "rotary"}
    assert all(chosen[title] == "keys" for title in TITLES if title != "pO2-Control")

    # Without a default the rest fall back to the built-in one.
    assert parse_mode_selector({"pO2": "rotary"}, TITLES)["pH-Control"] == DEFAULT_MODE_SELECTOR


def test_a_selector_nobody_has_is_refused():
    with pytest.raises(LayoutError, match="unknown mode_selector"):
        parse_mode_selector("wheel", TITLES)
    with pytest.raises(LayoutError, match="unknown panel"):
        parse_mode_selector({"Nonsense": "keys"}, TITLES)


def test_the_panels_build_the_selector_the_file_asked_for(qapp):
    spec = next(s for s in CONTROL_PANELS if s.title == "pO2-Control")
    assert isinstance(ControlPanel(spec, mode_selector="keys").mode_selector, SegmentedControl)
    assert isinstance(ControlPanel(spec, mode_selector="rotary").mode_selector, RotarySelector)


def test_the_knob_answers_the_calls_a_dropdown_would(qapp):
    """Whatever it looks like, the panels talk to it as they would a combo."""
    knob = RotarySelector()
    for value, text in ((0, "Manual"), (1, "Agitation"), (2, "Aeration")):
        knob.addItem(text, value)
    assert knob.count() == 3
    assert knob.currentData() == 0
    assert knob.findData(2) == 2
    assert knob.findData(9) == -1

    seen = []
    knob.currentIndexChanged.connect(seen.append)
    assert select_data(knob, 2) is True
    assert knob.currentText() == "Aeration"
    assert seen == [2]


def test_the_knob_marks_hand_control_in_red(qapp):
    """What the lamp beside the panel used to say, said by the knob."""
    knob = RotarySelector()
    for value, text in ((0, "Manual"), (1, "Agitation")):
        knob.addItem(text, value)
    knob.set_manual_value(0)
    assert knob._manual_value == 0

    panel = ControlPanel(
        next(s for s in CONTROL_PANELS if s.title == "pO2-Control"), mode_selector="rotary"
    )
    # The panel marks it without being told: mode 0 is hand control for every
    # controller in this application.
    assert panel.mode_selector._manual_value == MANUAL_MODE


def test_every_value_box_in_the_tab_is_the_same_width_across_panels(window):
    """A setpoint without a reading beside it used to get half the width.

    Measured as a ratio, not in pixels. A grid hands its leftover pixels to
    whichever column will take them, and how many are left over depends on
    the font: within 2 px on macOS, 140/144/148 on a Windows runner. Neither
    is the defect this guards — that one was 72 against 133, a field at half
    the width of its neighbour.
    """
    _laid_out(window)
    widths = {
        row.setpoint.width() for panel in window.panels.values() for row in panel.rows.values()
    }
    assert min(widths) >= 0.9 * max(widths), sorted(widths)


def test_the_knob_spreads_its_positions_over_the_arc(qapp):
    knob = RotarySelector()
    for index in range(5):
        knob.addItem(f"m{index}", index)
    angles = [knob._angle(index) for index in range(5)]
    assert angles[0] == RotarySelector.START
    assert angles[-1] == RotarySelector.START - RotarySelector.SPAN
    steps = {round(a - b, 6) for a, b in itertools.pairwise(angles)}
    assert len(steps) == 1, "the positions are not evenly spaced"


def test_a_name_repeated_across_cells_covers_them():
    """That is the whole notation: the file looks like the arrangement."""
    places = parse_grid(
        [
            ["pO2", "pO2", "Liquid Weight"],
            ["pH", "Temperature", "Feed"],
        ],
        TITLES,
    )
    assert places["pO2-Control"] == places["pO2-Control"].__class__(0, 0, 1, 2)
    assert places["Feed Control"] == places["Feed Control"].__class__(1, 2, 1, 1)


def test_the_names_are_forgiving():
    """A layout that breaks over a capital letter is one nobody edits twice."""
    assert normalise("pH-Control") == normalise("PH control") == normalise("ph")
    assert normalise("Liquid Weight") == normalise("liquid_weight")


def test_an_empty_cell_stays_empty():
    places = parse_grid(
        [
            ["pH", "Temperature", "pO2"],
            ["Liquid Weight", "Feed", "~"],
        ],
        TITLES,
    )
    assert len(places) == len(TITLES)
    assert max(p.column for p in places.values()) == 2


@pytest.mark.parametrize(
    ("grid", "complaint"),
    [
        ([["pH", "Temperature"]], "not placed anywhere"),
        ([["pH", "Nonsense", "pO2", "Liquid Weight", "Feed"]], "unknown panel"),
        ([["pH", "pO2", "pH", "Temperature", "Liquid Weight", "Feed"]], "rectangle"),
        ([["pH", "Temperature"], ["pO2"]], "same number of cells"),
        ("not a grid", "list of rows"),
    ],
)
def test_a_layout_that_cannot_be_drawn_is_refused(grid, complaint):
    with pytest.raises(LayoutError, match=complaint):
        parse_grid(grid, TITLES)


def test_a_broken_file_falls_back_and_says_why(tmp_path):
    """Half a tab because of a typo is not a trade anybody would take."""
    broken = tmp_path / "control_options.yaml"
    broken.write_text("grid:\n  - [pH, Nonsense]\n", encoding="utf-8")

    layout, problem = load_layout(TITLES, broken)
    assert set(layout.places) == set(TITLES)
    assert "unknown panel" in problem
    assert layout.places == fallback(TITLES)


def test_the_fallback_needs_no_file_at_all():
    """It runs when even the bundled file could not be read."""
    places = fallback(TITLES)
    assert [p.column for p in places.values()] == list(range(len(TITLES)))
    assert {p.row for p in places.values()} == {0}


# ------------------------------------------------------ the control loops --


def test_both_organisms_declare_their_loops():
    """The tab draws what the model says it runs, not what the GUI guesses."""
    discover_organisms()
    for name in ("escherichia_coli", "pichia_pastoris"):
        loops = get_organism(name).control_loops
        assert len(loops) == 8, name
        assert [loop.name for loop in loops][:3] == ["pH", "Temperature", "pO2 — agitation"]


def test_a_loop_with_a_reservoir_resolves_its_names():
    loop = next(
        loop for loop in get_organism("escherichia_coli").control_loops if "{n}" in loop.name
    )
    second = loop.resolve(2)
    assert second.name == "Feed R2"
    assert second.setpoint == "cS2Lw"
    assert second.p_share == "cP_feedR2"
    assert second.outputs == ("FR2",)
    assert loop.resolve(1).name == "Feed R1", "the template itself is untouched"


def test_the_tab_has_a_panel_per_loop_and_per_reservoir(qapp):
    from biofermentation.gui.widgets import ControllerView

    loops = get_organism("escherichia_coli").control_loops
    view = ControllerView(loops, reservoirs=3)
    # Seven loops without a reservoir, one with — three times.
    assert len(view.panels) == len(loops) + 2
    assert [panel.loop.name for panel in view.panels][-3:] == ["Feed R1", "Feed R2", "Feed R3"]


def test_a_loop_that_is_not_running_shows_nothing(window):
    """`a` keeps the last values of a loop that has been switched off, and
    showing them would be showing the past as the present."""
    view = window.controller_view
    state = window.runner.state
    state.p["Mode_pO2"] = 0.0
    view.refresh(state)

    panel = next(p for p in view.panels if p.loop.name == "pO2 — agitation")
    assert panel.state_label.text() == "off"
    assert panel.values["setpoint"].text() == "—"
    assert all(panel.share_values[letter].text() == "—" for letter in "PID")


def test_a_running_loop_shows_every_share(window):
    """The regression this tab was built on: a numpy float64 is a
    0-dimensional array and answers size == 1, so every scalar share looked
    like a one-element series and read as empty at any later index."""
    from biofermentation.core.runner import run_steps

    state = window.runner.state
    state.p["Mode_pO2"] = 1.0
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    run_steps(state, window.runner.organism, 40)
    window.controller_view.refresh(state)

    panel = next(p for p in window.controller_view.panels if p.loop.name == "pO2 — agitation")
    assert panel.state_label.text() == "controlling"
    for letter in "PID":
        assert panel.share_values[letter].text() not in ("—", ""), letter
    assert "NSt" in panel.output_label.text()
    assert "K<sub>P</sub>" in panel.gain_labels["P"].text()


def test_the_shares_the_model_only_kept_locally_are_there_now(window):
    """The pH master and the liquid weight held P and D in local variables;
    nothing outside the function could see them."""
    from biofermentation.core.runner import run_steps

    state = window.runner.state
    state.p["Mode_pH"] = 1.0
    state.p["Mode_harvest"] = 1.0
    run_steps(state, window.runner.organism, 40)
    for key in ("ce_pH", "cP_pH", "cP_LW", "cD_LW", "cI_LW"):
        assert state.a.get(key) is not None, key


def test_the_bars_of_one_loop_share_a_scale(qapp):
    """Their lengths are only comparable if they are measured against the
    same number — which is the whole reason for drawing them."""
    from biofermentation.gui.widgets.controller_view import ShareBar

    bar = ShareBar(SHARE_COLORS["I"])
    bar.set_value(0.5, 2.0)
    assert bar._value == 0.5
    assert bar._scale == 2.0
    bar.set_value(1.0, 0.0)
    assert bar._scale == 1.0, "a zero scale would divide by zero on the next paint"


# ------------------------------------------- what the settings switch off --


def _window_with(db_copy, monkeypatch, settings):
    """A control window built with these settings, whatever the machine has."""
    from biofermentation.gui.windows import control_app

    monkeypatch.setattr(control_app, "load_settings", lambda: (settings, ""))
    setup = load_phases(db_copy, PICHIA_PROJECT)
    state, organism = load_project_state(db_copy, PICHIA_PROJECT)
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    return ControlWindow(setup, runner, db_copy)


def test_a_hidden_tab_is_not_in_the_tab_bar(qapp, db_copy, monkeypatch):
    from biofermentation.gui.settings import Settings

    window = _window_with(db_copy, monkeypatch, Settings(hidden_tabs={"Log", "Process Manager"}))
    titles = {window.tabs.tabText(index) for index in range(window.tabs.count())}
    assert "Log" not in titles
    assert "Process Manager" not in titles
    assert {"Control Options", "Controllers", "Variable Pool", "Information"} <= titles


def test_a_hidden_tab_is_still_built(qapp, db_copy, monkeypatch):
    """The window refreshes its pages by name; one that does not exist would
    have to be checked for everywhere instead of once here."""
    from biofermentation.gui.settings import Settings

    window = _window_with(db_copy, monkeypatch, Settings(hidden_tabs={"Log"}))
    window.note("still writing", "Process")
    assert window.log_view.entries, "the log kept working while not shown"
    assert window.pages["Log"] is window.log_view


def test_the_student_view_locks_the_step_width_and_hides_the_speed(qapp, db_copy, monkeypatch):
    from biofermentation.gui.settings import Settings

    window = _window_with(db_copy, monkeypatch, Settings(student_view=True))
    assert window.dt_box.isReadOnly() is True
    assert window.dt_box.value() > 0, "shown, not removed"
    assert window.speed_box.parent() is None, "the speed factor is not in the window at all"

    ordinary = _window_with(db_copy, monkeypatch, Settings())
    assert ordinary.dt_box.isReadOnly() is False
    assert ordinary.speed_box.parent() is not None


def test_the_inoculated_lamp_is_on_before_the_first_step(qapp, db_copy):
    """A project that was inoculated comes back inoculated.

    It used to take a step to find out: `a` is not persisted, the lamp reads
    `inoc_occ`, and that was 0 until the model had recomputed it. The lamp
    was the visible half of it — the invisible half was the model reading the
    same 0 as "inoculate now" and resetting the biomass.
    """
    from biofermentation.db import save_project
    from biofermentation.db.models import VariableSeries

    setup = load_phases(db_copy, PICHIA_PROJECT)
    state, organism = load_project_state(db_copy, PICHIA_PROJECT)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    state.v.cXL[0] = float(state.p["cXL0"])
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    for _ in range(3):
        runner._on_tick()
    save_project(
        db_copy,
        PICHIA_PROJECT,
        p=dict(state.p),
        series=VariableSeries(
            t=state.trimmed()["t"], v=state.trimmed(), real_t=[""] * (state.idx + 1)
        ),
    )

    reopened, organism = load_project_state(db_copy, PICHIA_PROJECT)
    window = ControlWindow(
        load_phases(db_copy, PICHIA_PROJECT),
        SimulationRunner(organism, reopened),
        db_copy,
    )
    assert window.lamps["Inoculated"].color() == GREEN
    assert window.inoculate_button.isEnabled() is False


def test_a_resumed_run_says_what_it_could_not_bring_back(qapp, db_copy):
    """xO2 and xCO2 are ODE states and are not stored for either organism.

    load_project_state has always worked this out; nothing read it. A run that
    quietly restarts an ODE state is a run whose numbers cannot be accounted
    for afterwards, so the window says it out loud.
    """
    from biofermentation.db import save_project
    from biofermentation.db.models import VariableSeries

    setup = load_phases(db_copy, PICHIA_PROJECT)
    state, organism = load_project_state(db_copy, PICHIA_PROJECT)
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    for _ in range(3):
        runner._on_tick()
    save_project(
        db_copy,
        PICHIA_PROJECT,
        series=VariableSeries(
            t=state.trimmed()["t"], v=state.trimmed(), real_t=[""] * (state.idx + 1)
        ),
    )

    resumed, organism = load_project_state(db_copy, PICHIA_PROJECT)
    assert resumed.a.restarted_variables, "the fixture resumed nothing"
    window = ControlWindow(
        load_phases(db_copy, PICHIA_PROJECT), SimulationRunner(organism, resumed), db_copy
    )
    said = [entry.message for entry in window.log_view.entries if not entry.restored]
    restarted = next(line for line in said if "restart from their initial values" in line)
    for name in resumed.a.restarted_variables:
        assert name in restarted


def test_a_fresh_project_reports_nothing_about_resuming(qapp, db_copy):
    """There is nothing to warn about when nothing was resumed."""
    setup = load_phases(db_copy, PICHIA_PROJECT)
    state, organism = load_project_state(db_copy, PICHIA_PROJECT)
    assert state.idx == 0
    window = ControlWindow(setup, SimulationRunner(organism, state), db_copy)
    said = [entry.message for entry in window.log_view.entries if not entry.restored]
    assert not any("restart from their initial values" in line for line in said)


def test_the_window_shows_the_package_version(qapp):
    """The window said 3.0 while the package said 0.1.0 — one number, please."""
    import biofermentation
    from biofermentation.gui.windows.starting_screen import VERSION

    assert biofermentation.__version__ == VERSION


def test_the_student_view_says_so_in_the_title(qapp, db_copy, monkeypatch):
    """A locked Δt with nothing to explain it reads as a defect."""
    from biofermentation.gui.settings import Settings

    window = _window_with(db_copy, monkeypatch, Settings(student_view=True))
    assert window.windowTitle().endswith(" - Student View")

    ordinary = _window_with(db_copy, monkeypatch, Settings())
    assert "Student View" not in ordinary.windowTitle()
