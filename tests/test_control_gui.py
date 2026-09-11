"""The Control App and its pieces (plan section 5).

Headless, like the rest of the GUI tests. The point of interest is not what
the window looks like but that every write into the simulation state goes
through the runner's guard, and that the phase grid says what the phases
actually are.
"""

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
from biofermentation.gui.widgets import (
    CONTROL_PANELS,
    ControlPanel,
    PhaseGrid,
    SegmentedControl,
    ToggleSwitch,
    condition_text,
    select_data,
)
from biofermentation.gui.widgets.tex import tex_label, tex_to_html
from biofermentation.gui.windows import ControlWindow
from biofermentation.gui.windows.control_app import PANEL_PLACES, PANEL_SPACING
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
    window.run_button.click()
    window.run_button.click()
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
    window.tabs.setCurrentIndex(1)
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
        selector = panel.mode_selector
        assert selector.width() >= panel.width() - 30, title
        # The lamp sits on the caption line above the keys, not beside them.
        assert panel.lamp.geometry().bottom() <= selector.geometry().top(), title


def test_the_mode_selector_shows_every_mode_at_once(window):
    """That is the point of it: no mode hides behind a click.

    Not necessarily on one row — pO2 has five modes and a panel a third of the
    window wide, so they wrap. Wrapped is still shown; hidden is not.
    """
    for title, panel in window.panels.items():
        selector = panel.mode_selector
        assert selector.count() == len(panel.spec.modes), title
        cells = selector._cells()
        assert len(cells) == selector.count(), title
        for index, cell in cells.items():
            assert cell.right() <= selector.width() + 1, f"{title}: key {index} runs off"
            assert cell.bottom() <= selector.height() + 1, f"{title}: key {index} is cut off"


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


def test_the_panels_sit_where_the_layout_table_says(window):
    """Four columns; Liquid Weight and Feed share the fourth."""
    layout = window.tabs.widget(0).layout()
    assert layout.columnCount() == 4
    for title, (column, row, span) in PANEL_PLACES.items():
        index = layout.indexOf(window.panels[title])
        assert index >= 0, title
        assert layout.getItemPosition(index) == (row, column, span, 1), title


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
        for title, (_, _, span) in PANEL_PLACES.items()
        if span == 2
    ]
    half = [
        window.panels[title]
        for title, (_, _, span) in PANEL_PLACES.items()
        if span == 1
    ]
    assert {panel.height() for panel in half}.__len__() == 1, "the halves differ"
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
    """It asked for 1600 px: a QDoubleSpinBox sizes itself to the widest text
    its range allows, and these accept plus or minus a billion.

    1440 is the narrowest screen this is meant for. Five panels side by side
    cost more width than a grid of six does — that is the price of the row,
    and it has to stay under that number.
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
