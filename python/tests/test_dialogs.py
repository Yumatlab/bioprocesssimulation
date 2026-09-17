"""The dialogs added in the UX round: parameters, export, data table, plots.

Headless like the rest of the GUI tests. What is checked is not the layout
but the two rules the dialogs live by: nothing is written before Ok, and what
may be edited during a run is decided by the database, not by the widget.
"""

import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from biofermentation.control import PhaseAutomaton, PhaseType
from biofermentation.core.runner import DEFAULT_DT, load_project_state
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import load_phases
from biofermentation.db.models import ProjectInfo
from biofermentation.db.plots import load_plot_styles, load_plot_template
from biofermentation.gui.dialogs.export import ExportDialog, write_table, write_text_table
from biofermentation.gui.dialogs.parameters import (
    SECTION_ORDER,
    ControllerParametersDialog,
    ModeBox,
    ParameterDialog,
)
from biofermentation.gui.dialogs.plot_settings import STANDARD, PlotSettingsDialog, VariableEditor
from biofermentation.gui.widgets.indicators import select_data
from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS, PH_PANEL
from biofermentation.gui.windows.control_app import ControlWindow

# From __file__, like every other test module: a path relative to the
# working directory only holds while pytest is started from one place.
REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
PROJECT = 519


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    target = tmp_path / "sim.db"
    shutil.copy(TEMPLATE, target)
    return target


@pytest.fixture
def window(db, qapp):
    setup = load_phases(db, PROJECT)
    state, organism = load_project_state(db, PROJECT, dt=DEFAULT_DT)
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    control = ControlWindow(setup, runner, db)
    yield control
    control.close()


# ------------------------------------------------- controller parameters --


def test_every_controller_panel_offers_its_gains(window):
    """Point 3: the Parameters button used to lead nowhere."""
    for spec in CONTROL_PANELS:
        dialog = ControllerParametersDialog(
            spec, window.runner.state.p, reservoirs=window.setup.info.reservoirs or 1
        )
        assert dialog._boxes, f"{spec.title} has no parameters"


def test_the_controller_dialog_writes_only_on_ok(window):
    dialog = ControllerParametersDialog(PH_PANEL, window.runner.state.p)
    before = window.runner.state.p["KP_pH"]
    dialog._boxes["KP_pH"].setValue(before + 1.0)

    dialog.reject()
    assert dialog.changes == {}
    assert window.runner.state.p["KP_pH"] == before

    dialog = ControllerParametersDialog(PH_PANEL, window.runner.state.p)
    dialog._boxes["KP_pH"].setValue(before + 1.0)
    dialog.accept()
    assert dialog.changes == {"KP_pH": pytest.approx(before + 1.0)}
    # Still not in the state — the window applies it, inside the guard.
    assert window.runner.state.p["KP_pH"] == before


def test_an_untouched_field_is_not_a_change(window):
    dialog = ControllerParametersDialog(PH_PANEL, window.runner.state.p)
    dialog.accept()
    assert dialog.changes == {}


def test_the_feed_dialog_follows_the_reservoir_count(window):
    """One block per reservoir, and none for one the project has no gains for."""
    feed = next(spec for spec in CONTROL_PANELS if spec.title == "Feed Control")
    p = window.runner.state.p
    assert window.setup.info.reservoirs == 2

    one = ControllerParametersDialog(feed, p, reservoirs=1)
    assert "KP_feedR1" in one._boxes
    assert "KP_feedR2" not in one._boxes

    two = ControllerParametersDialog(feed, p, reservoirs=2)
    assert {"KP_feedR1", "KP_feedR2"} <= set(two._boxes)

    # Asking for a third only shows what the project actually carries.
    three = ControllerParametersDialog(feed, p, reservoirs=3)
    assert set(three._boxes) == set(two._boxes)
    assert "KP_feedR3" not in p


def test_the_control_window_applies_the_gains_through_the_guard(window, monkeypatch):
    def accept_with_change(self):
        self._boxes["KP_pH"].setValue(self._original["KP_pH"] + 2.5)
        type(self).__mro__[1].accept(self)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ControllerParametersDialog, "exec", accept_with_change)
    before = window.runner.state.p["KP_pH"]
    window.open_controller_parameters("pH-Control")
    assert window.runner.state.p["KP_pH"] == pytest.approx(before + 2.5)
    assert any("KP_pH" in entry.message for entry in window.log_view.entries)


# ----------------------------------------------------- parameter dialog --


def test_before_the_start_every_visible_parameter_is_editable(window):
    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=False)
    assert all(box.isEnabled() for box in dialog._boxes.values())


def test_during_the_run_only_cyclic_parameters_stay_editable(window):
    """Point 4: cS1L0 is read at step 0 and must not move afterwards."""
    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=True)
    cyclic = {
        meta["parametername"] for meta in window.setup.p_meta if meta["reading_rate"] == "cyclic"
    }
    assert cyclic, "the fixture project has no cyclic parameters at all"
    for name, box in dialog._boxes.items():
        assert box.isEnabled() is (name in cyclic), name

    assert "cS1L0" in dialog._boxes
    assert dialog._boxes["cS1L0"].isEnabled() is False
    assert dialog._boxes["pHw"].isEnabled() is True


def test_the_sections_come_in_reading_order(window):
    """Parameters first, then the organism, the vessel and the rest.

    The database sorts categories by id, which puts General — calibration
    constants and switches — above the setpoints someone opened the dialog
    for. A section SECTION_ORDER does not know follows rather than pushing in.
    """
    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=False)
    sections = [group.title().split(" — ")[0] for group in dialog._groups]
    seen = list(dict.fromkeys(sections))
    known = [section for section in seen if section in SECTION_ORDER]
    assert known == [section for section in SECTION_ORDER if section in seen]
    assert sections == sorted(
        sections,
        key=lambda name: SECTION_ORDER.index(name) if name in SECTION_ORDER else len(SECTION_ORDER),
    ), "a section appears twice, split by another one"


def test_a_mode_is_a_list_of_names_not_a_number_field(window):
    """Mode_pO2 = 3 says nothing; the database has called it pO2-Gasmix."""
    dialog = ParameterDialog(
        window.setup.p_meta, window.runner.state.p, started=False, modes=window.modes
    )
    box = dialog._boxes["Mode_pO2"]
    assert isinstance(box, ModeBox)
    names = [box.itemText(index) for index in range(box.count())]
    assert names == ["Manual", "pO2-Agitation", "pO2-Aeration", "pO2-Gasmix", "pO2-Feed"]
    assert isinstance(dialog._boxes["pHw"], ModeBox) is False, "a setpoint is still a number"


def test_choosing_a_mode_reports_its_number(window):
    """The names are for reading; what is stored stays the number."""
    dialog = ParameterDialog(
        window.setup.p_meta, window.runner.state.p, started=False, modes=window.modes
    )
    box = dialog._boxes["Mode_pO2"]
    box.setValue(3)
    assert box.currentText() == "pO2-Gasmix"
    dialog.accept()
    assert dialog.changes["Mode_pO2"] == 3.0


def test_a_mode_the_database_does_not_name_is_kept(window):
    """Better an entry reading "7 (unknown)" than silently becoming Manual."""
    p = dict(window.runner.state.p)
    p["Mode_pO2"] = 7.0
    dialog = ParameterDialog(window.setup.p_meta, p, started=False, modes=window.modes)
    box = dialog._boxes["Mode_pO2"]
    assert box.value() == 7.0
    assert "unknown" in box.currentText()
    dialog.accept()
    assert "Mode_pO2" not in dialog.changes, "nothing was touched"


def test_the_log_writes_the_name_of_the_mode(window):
    """A log that records "Mode_pO2 from 1 to 3" records nothing readable."""
    before = window.modes["Mode_pO2"][int(window.runner.state.p["Mode_pO2"])]
    window._apply_changes({"Mode_pO2": 3.0}, "Parameters")
    line = window.log_view.entries[-1].message
    assert f"from {before} to pO2-Gasmix" in line
    assert "3.0" not in line

    window._set_parameter("pHw", 6.9)
    assert "6.900" in window.log_view.entries[-1].message


def test_invisible_parameters_are_not_offered(window):
    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=False)
    hidden = {
        meta["parametername"] for meta in window.setup.p_meta if meta["reading_rate"] == "invisible"
    }
    assert hidden, "the fixture project has no invisible parameters at all"
    assert not hidden & set(dialog._boxes)


def test_a_locked_parameter_cannot_smuggle_a_change_through(window):
    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=True)
    dialog._boxes["cS1L0"].setValue(dialog._original["cS1L0"] + 5)
    dialog.accept()
    assert "cS1L0" not in dialog.changes


def test_the_search_narrows_the_list(window):
    dialog = ParameterDialog(window.setup.p_meta, window.runner.state.p, started=False)
    dialog.search.setText("KP_pH")
    visible = [widget for widget, hay, _ in dialog._rows if "kp_ph" in hay]
    assert visible and all(widget.isVisibleTo(dialog) for widget in visible)
    others = [widget for widget, hay, _ in dialog._rows if "cs1l0" in hay]
    assert others and not any(widget.isVisibleTo(dialog) for widget in others)


# --------------------------------------------------------------- export --


def test_write_table_round_trips(tmp_path):
    names = ["t", "cXL"]
    columns = [np.arange(4, dtype=float), np.array([1.0, 2.0, 3.0, 4.0])]
    target = write_table(tmp_path / "x.csv", names, columns)
    lines = target.read_text().splitlines()
    assert lines[0] == "t,cXL"
    assert lines[1] == "0,1"
    assert len(lines) == 5


def test_a_txt_export_is_tab_separated(tmp_path):
    target = write_text_table(tmp_path / "x.txt", ["a", "b"], [["1", "2"]])
    assert target.read_text().splitlines()[0] == "a\tb"


def test_xlsx_falls_back_to_csv_without_openpyxl(tmp_path, monkeypatch):
    """Losing the export silently would be worse than a different suffix."""
    import builtins

    real_import = builtins.__import__

    def no_openpyxl(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_openpyxl)
    target = write_table(tmp_path / "x.xlsx", ["a"], [np.array([1.0])])
    assert target.suffix == ".csv"
    assert target.is_file()


def test_the_export_dialog_writes_the_selected_parts(window, tmp_path):
    window.runner._on_tick()
    dialog = ExportDialog(window.setup, window.runner.state, ["one log line"])
    dialog.folder_edit.setText(str(tmp_path))
    dialog.name_edit.setText("run 1")
    dialog.accept()

    folder = tmp_path / "run_1"
    assert folder.is_dir()
    names = {path.name for path in dialog.written}
    assert names == {
        "variables.csv",
        "parameters.csv",
        "phases.csv",
        "log.txt",
        "Project_Information.txt",
        # Always written: without it the folder is a record, not a package.
        "project.yaml",
    }
    assert "one log line" in (folder / "log.txt").read_text()
    assert "cXL" in (folder / "variables.csv").read_text().splitlines()[0]


def test_the_export_dialog_honours_the_checkboxes(window, tmp_path):
    dialog = ExportDialog(window.setup, window.runner.state, [])
    dialog.folder_edit.setText(str(tmp_path))
    for key, box in dialog.checkboxes.items():
        box.setChecked(key == "phases")
    dialog.accept()
    assert [path.name for path in dialog.written] == ["phases.csv", "project.yaml"]


# ----------------------------------------------------------- data table --


def test_the_data_table_shows_the_ticked_variables(window):
    table = window.open_data_table()
    try:
        window.runner._on_tick()
        table.refresh()
        headers = [
            table.table.horizontalHeaderItem(column).text()
            for column in range(table.table.columnCount())
        ]
        assert headers[0] == "t [h]"
        assert any(header.startswith("cXL") for header in headers)
        assert table.table.rowCount() == window.runner.state.idx + 1

        table.items["cXL"].setCheckState(0, _unchecked())
        assert not any(
            table.table.horizontalHeaderItem(column).text().startswith("cXL")
            for column in range(table.table.columnCount())
        )
    finally:
        table.close()


def _unchecked():
    from PySide6.QtCore import Qt

    return Qt.CheckState.Unchecked


def test_the_data_table_export_matches_the_view(window, tmp_path):
    table = window.open_data_table()
    try:
        names, columns = table.columns()
        target = write_table(tmp_path / "view.csv", names, columns)
        header = target.read_text().splitlines()[0].split(",")
        assert header == names
    finally:
        table.close()


# --------------------------------------------------------- plot editors --


def test_the_variable_editor_writes_colour_and_style(db, qapp):
    template = load_plot_template(db, 1)
    styles = load_plot_styles(db)
    variable = template.variables[0]
    before = (variable.colorID, variable.linestyleID, variable.decimalID)

    editor = VariableEditor(template, styles)
    widgets = editor.rows[variable.name]
    assert select_data(widgets["color"], 4)
    assert select_data(widgets["linestyle"], 2)
    assert select_data(widgets["decimals"], 5)

    editor.reject()
    assert (variable.colorID, variable.linestyleID, variable.decimalID) == before

    editor = VariableEditor(template, styles)
    widgets = editor.rows[variable.name]
    select_data(widgets["color"], 4)
    select_data(widgets["linestyle"], 2)
    select_data(widgets["decimals"], 5)
    editor.accept()

    assert variable.colorID == 4
    assert variable.color == (0, 255, 0)
    assert variable.linestyleID == 2
    assert variable.linestyle == "--"
    assert variable.decimal == "%.4f"


def test_the_variable_editor_survives_a_save(db, qapp):
    from biofermentation.db.plots import save_plot_template

    # Not the default: that one is protected, so the round trip uses the copy
    # the application would make.
    template = load_plot_template(db, 2)
    editor = VariableEditor(template, load_plot_styles(db))
    name = template.variables[0].name
    select_data(editor.rows[name]["color"], 7)
    editor.accept()
    save_plot_template(db, template)

    assert load_plot_template(db, 2).variables[0].colorID == 7


def test_the_settings_dialog_applies_and_resets(db, qapp):
    template = load_plot_template(db, 1)
    dialog = PlotSettingsDialog(template)
    dialog.widgets["graphlinewidth"].setValue(4.0)
    dialog.widgets["axisxlabel"].setText("Zeit")
    dialog.accept()
    assert template.graphlinewidth == 4.0
    assert template.axisxlabel == "Zeit"

    dialog = PlotSettingsDialog(template)
    dialog._reset(["graphlinewidth"])
    assert dialog.widgets["graphlinewidth"].value() == STANDARD["graphlinewidth"]


def test_the_settings_dialog_writes_nothing_on_cancel(db, qapp):
    template = load_plot_template(db, 1)
    before = template.graphfontsize
    dialog = PlotSettingsDialog(template)
    dialog.widgets["graphfontsize"].setValue(before + 3)
    dialog.reject()
    assert template.graphfontsize == before


# -------------------------------------------------------- several plots --


def test_several_plots_can_be_open_at_once(window):
    """Point 13. The original keeps its figures in a cell array; so do we."""
    first = window.open_plot()
    second = window.open_plot(2)
    try:
        assert len(window.figure_windows) == 2
        assert first is not second
        assert first.template.templateID != second.template.templateID
    finally:
        second.close()
        assert len(window.figure_windows) == 1
        first.close()
        assert window.figure_windows == []


def test_a_plot_can_hide_its_side_panels(window):
    """Point 15: full width for the plot itself."""
    figure = window.open_plot()
    figure.show()
    try:
        assert figure.limits_panel.isVisibleTo(figure)
        figure.fullscreen_action.setChecked(True)
        assert not figure.limits_panel.isVisibleTo(figure)
        assert not figure.configuration_panel.isVisibleTo(figure)

        figure.fullscreen_action.setChecked(False)
        assert figure.limits_panel.isVisibleTo(figure)
        assert figure.configuration_panel.isVisibleTo(figure)
    finally:
        figure.close()


def test_loading_another_template_redraws_the_window(window):
    figure = window.open_plot()
    try:
        figure.load_template(2)
        assert figure.template.templateID == 2
        assert set(figure.checkboxes) == {variable.name for variable in figure.template.variables}
        assert len(figure.plot._variables) == len(figure.template.selected())
    finally:
        figure.close()


# ------------------------------------------------------------- menu bar --


def test_the_control_window_has_its_menu_bar(window):
    """The menu bar of the original was missing entirely."""
    bar = window.menuBar()
    menus = [action.text() for action in bar.actions()]
    assert menus == ["Project", "Export", "Plots", "Settings"]

    entries = {
        menu.text(): [action.text() for action in menu.menu().actions() if action.text()]
        for menu in bar.actions()
    }
    assert "Parameters…" in entries["Project"]
    assert "Save and exit" in entries["Project"]
    assert "Open data table" in entries["Export"]
    assert "Export project…" in entries["Export"]
    assert "Open plot" in entries["Plots"]
    # Disconnect is gone: pausing the run does the same and says so.
    assert "Disconnect" not in entries["Settings"]


def test_the_template_submenu_lists_what_the_database_has(window):
    window._fill_template_menu()
    names = [action.text() for action in window.template_menu.actions()]
    assert "Default" in names and "Oxygen" in names


def test_the_figure_window_has_its_menu_bar(window):
    figure = window.open_plot()
    try:
        menus = [action.text() for action in figure.menuBar().actions()]
        assert menus == ["Export", "Template", "Options"]
    finally:
        figure.close()


def test_resetting_the_gains_restores_the_model_defaults(window):
    from biofermentation.db import load_model_defaults

    defaults = load_model_defaults(window.db_path, window.setup.info.organismID)
    assert "KP_pH" in defaults

    with window.runner.editing() as state:
        state.p["KP_pH"] = defaults["KP_pH"] + 42.0
    window.reset_controller_gains()
    assert window.runner.state.p["KP_pH"] == pytest.approx(defaults["KP_pH"])


def test_resetting_the_gains_leaves_other_categories_alone(window):
    before = window.runner.state.p["cS1L0"]
    with window.runner.editing() as state:
        state.p["cS1L0"] = before + 1.0
    window.reset_controller_gains()
    assert window.runner.state.p["cS1L0"] == pytest.approx(before + 1.0)


# ------------------------------------------------- the second UX round --


def test_the_timer_runs_at_the_step_width(window):
    """Point 1: refresh rate and Δt are the same number."""
    window.dt_box.setValue(2)
    assert window.runner.interval_ms == 2000
    window.dt_box.setValue(5)
    assert window.runner.interval_ms == 5000
    assert window.runner.state.p["deltatsec"] == 5.0


def test_a_runner_without_an_interval_takes_it_from_the_project(db, qapp):
    from biofermentation.core.simulation_runner import SimulationRunner

    state, organism = load_project_state(db, PROJECT, dt=DEFAULT_DT)
    state.p["deltatsec"] = 3.0
    runner = SimulationRunner(organism, state)
    assert runner.interval_ms == 3000


def test_run_carries_on_after_a_stop_phase(window):
    """Point 29: the stop phase ends when the operator says so."""
    from biofermentation.control import PhaseStatus, PhaseType, StartCondition
    from biofermentation.db.models import Condition

    automaton = window.runner.phases
    for phase in window.setup.phases:
        phase.statusID = PhaseStatus.UPCOMING
    stop, following = window.setup.phases[0], window.setup.phases[1]
    stop.typeID = PhaseType.STOP
    stop.statusID = PhaseStatus.PENDING
    stop.start = Condition(typeID=StartCondition.PREVIOUS_ENDED)
    stop.end = Condition()
    automaton.current = None
    automaton.stop_requested = False

    stopped = []
    window.runner.stopped.connect(stopped.append)
    window.runner._on_tick()

    assert automaton.stop_requested is True
    assert stop.statusID == PhaseStatus.ACTIVE
    assert stopped == ["stop phase"]

    # Run again: the stop is released and the next phase is up.
    window.runner.start()
    try:
        assert automaton.stop_requested is False
        assert stop.statusID == PhaseStatus.COMPLETED
        assert stop.end.time is not None
        assert following.statusID == PhaseStatus.PENDING
        assert automaton.current is None
        assert window.runner.running is True
    finally:
        window.runner.pause()


def test_a_released_stop_does_not_stop_again(window):
    from biofermentation.control import PhaseStatus, PhaseType, StartCondition
    from biofermentation.db.models import Condition

    automaton = window.runner.phases
    for phase in window.setup.phases:
        phase.statusID = PhaseStatus.UPCOMING
    stop = window.setup.phases[0]
    stop.typeID = PhaseType.STOP
    stop.statusID = PhaseStatus.PENDING
    stop.start = Condition(typeID=StartCondition.PREVIOUS_ENDED)
    stop.end = Condition()
    automaton.current = None
    automaton.stop_requested = False

    window.runner._on_tick()
    window.runner.start()
    before = window.runner.state.idx
    window.runner._on_tick()
    assert window.runner.state.idx > before, "the process has to move again"
    window.runner.pause()


def test_phases_cannot_be_changed_while_the_process_runs(window):
    """Point 10: re-planning happens on a standing process."""
    grid = window.phase_grid
    window.runner.start()
    window.refresh_phases()
    try:
        assert grid.add_button.isEnabled() is False
        for panel in grid.panels:
            assert panel.edit_button.isEnabled() is False
            assert panel.delete_button.isEnabled() is False
            assert "Pause" in panel.edit_button.toolTip()
    finally:
        window.runner.pause()

    window.refresh_phases()
    assert grid.add_button.isEnabled() is True
    assert grid.panels[-1].edit_button.isEnabled() is True


def test_pausing_reopens_the_phase_editor(window):
    from biofermentation.control import PhaseStatus

    window.run_button.click()  # start
    assert window.runner.running is True
    assert window.phase_grid.add_button.isEnabled() is False

    window.run_button.click()  # pause
    assert window.runner.running is False
    assert window.phase_grid.add_button.isEnabled() is True
    upcoming = next(
        panel
        for phase, panel in zip(window.setup.phases, window.phase_grid.panels, strict=True)
        if phase.statusID == PhaseStatus.UPCOMING
    )
    assert upcoming.delete_button.isEnabled() is True


def test_the_inoculate_toggle_writes_both_flags(window):
    """Point 6: f_InocStart is the setting, f_Inoc the event."""
    state = window.runner.state
    assert state.idx == 0
    button = window.inoculate_button
    assert button.isCheckable() is True

    button.click()
    assert button.isChecked() is True
    assert state.p["f_InocStart"] == 1.0
    assert state.p["f_Inoc"] == 1.0
    assert state.a["inoc_occ"] == 1
    assert state.v.cXL[0] == pytest.approx(state.p["cXL0"])

    button.click()
    assert button.isChecked() is False
    assert state.p["f_InocStart"] == 0.0
    assert state.p["f_Inoc"] == 0.0
    assert state.a["inoc_occ"] == 0
    assert state.v.cXL[0] == 0.0


def test_the_inoculate_button_is_a_one_shot_once_the_run_started(window):
    state = window.runner.state
    state.p["f_Inoc"] = 0.0
    state.a["inoc_occ"] = 0
    window.runner._on_tick()
    window.refresh()

    assert state.idx > 0
    assert window.inoculate_button.isCheckable() is False
    assert window.inoculate_button.isEnabled() is True

    window.inoculate_button.click()
    assert state.p["f_Inoc"] == 1.0

    state.a["inoc_occ"] = 1
    window.refresh()
    assert window.inoculate_button.isEnabled() is False


def test_the_open_plot_button_does_not_pass_its_checked_state(window):
    """clicked(bool) used to arrive as template_id and raise LookupError."""
    window.plot_button.click()
    try:
        assert len(window.figure_windows) == 1
        assert window.figure_windows[0].template.templateID == 1
    finally:
        for figure in list(window.figure_windows):
            figure.close()


def test_saving_reports_back(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window.save()
    assert window.save_button.text() == "Saved ✓"
    assert "Saved" in window.statusBar().currentMessage()
    window._reset_save_button()
    assert window.save_button.text() == "Save"


# ------------------------------------------------------ log persistence --


def test_a_reopened_project_shows_the_log_of_the_run_so_far(window, db):
    """Point 8: the transitions and parameter changes are what one comes back
    for, and they used to be gone."""
    from biofermentation.control import PhaseAutomaton
    from biofermentation.core.simulation_runner import SimulationRunner

    window.note("Process started", "Process")
    window.note("Batch Phase [Phase 1] started at t = 0.000 h.", "Phase Event")
    window.save(announce=False)
    window.close()

    setup = load_phases(db, PROJECT)
    state, organism = load_project_state(db, PROJECT, dt=DEFAULT_DT)
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    reopened = ControlWindow(setup, runner, db)
    try:
        messages = [entry.message for entry in reopened.log_view.entries]
        assert "Process started" in messages
        assert "Batch Phase [Phase 1] started at t = 0.000 h." in messages

        restored = [entry for entry in reopened.log_view.entries if entry.restored]
        assert restored, "nothing was marked as coming from an earlier session"
        assert all(entry.logID is not None for entry in restored)

        # Nothing of this session yet, so no rule either.
        assert "this session" not in reopened.log_view.view.toPlainText()

        reopened.note("Process resumed", "Process")
        text = reopened.log_view.view.toPlainText()
        assert "Process started" in text
        assert text.index("this session") < text.index("Process resumed")
    finally:
        reopened.close()


def test_saving_twice_does_not_double_the_log(window, db):
    from biofermentation.db import load_project_log

    window.note("Only once", "Process")
    window.save(announce=False)
    first = load_project_log(db, PROJECT)
    window.save(announce=False)
    second = load_project_log(db, PROJECT)

    assert [entry["message"] for entry in second].count("Only once") == 1
    # The second save still writes the entry the first one made about itself.
    assert len(second) >= len(first)


def test_a_restored_entry_keeps_its_event_type_and_process_time(window, db):
    from biofermentation.db import load_project_log

    window.runner._on_tick()
    window.note("Something happened", "Phase Information")
    window.save(announce=False)

    stored = next(
        entry for entry in load_project_log(db, PROJECT) if entry["message"] == "Something happened"
    )
    assert stored["event_type"] == "Phase Information"
    assert stored["process_time"] == pytest.approx(float(window.runner.state.v.t[1]))


# ------------------------------------------- phase parameters, point 7 --


def test_a_phase_stores_only_what_was_changed(window):
    """An untouched field means "leave it alone", which is not the same as
    writing the current value back — the operator may move it in between."""
    from biofermentation.gui.dialogs import PhaseParameterDialog

    phase = window.setup.phases[-1]
    phase.parameters = {}
    phase.typeID = PhaseType.PARAMETER_UPDATE
    p = window.runner.state.p
    dialog = PhaseParameterDialog(phase, window.setup.p_meta, p)

    assert dialog._boxes, "no cyclic parameters offered"
    assert "cS1L0" not in dialog._boxes, "an initial value cannot be applied mid-run"

    dialog._boxes["pO2w"].setValue(p["pO2w"] + 15)
    dialog.accept()

    assert phase.parameters == {"pO2w": pytest.approx(p["pO2w"] + 15)}


def test_the_phase_summary_reads_in_names_not_in_numbers(window):
    """The Parameter Update view is where a phase says what it will do."""
    from biofermentation.gui.dialogs import PhaseParameterDialog

    phase = window.setup.phases[-1]
    phase.parameters = {}
    phase.typeID = PhaseType.PARAMETER_UPDATE
    dialog = PhaseParameterDialog(
        phase, window.setup.p_meta, window.runner.state.p, modes=window.modes
    )
    before = window.modes["Mode_pO2"][int(window.runner.state.p["Mode_pO2"])]
    dialog._boxes["Mode_pO2"].setValue(3)
    assert f"Mode_pO2: {before} → pO2-Gasmix" in dialog.summary.toPlainText()

    # A number keeps its decimals rather than collapsing to %g.
    dialog._boxes["pO2w"].setValue(dialog._original["pO2w"] + 15)
    assert "pO2w: " in dialog.summary.toPlainText()

    dialog.accept()
    assert phase.parameters["Mode_pO2"] == 3.0


def test_the_reset_button_appears_only_on_a_changed_parameter(window):
    from biofermentation.gui.dialogs import PhaseParameterDialog

    phase = window.setup.phases[-1]
    phase.parameters = {}
    phase.typeID = PhaseType.PARAMETER_UPDATE
    dialog = PhaseParameterDialog(phase, window.setup.p_meta, window.runner.state.p)

    assert dialog._resets["pO2w"].isVisibleTo(dialog) is False
    dialog._boxes["pO2w"].setValue(dialog._original["pO2w"] + 5)
    assert dialog._resets["pO2w"].isVisibleTo(dialog) is True

    dialog._resets["pO2w"].click()
    assert dialog._boxes["pO2w"].value() == pytest.approx(dialog._original["pO2w"])
    assert dialog._resets["pO2w"].isVisibleTo(dialog) is False


def test_the_dialog_lists_what_the_phase_will_do(window):
    from biofermentation.gui.dialogs import PhaseParameterDialog

    phase = window.setup.phases[-1]
    phase.parameters = {}
    phase.typeID = PhaseType.PARAMETER_UPDATE
    dialog = PhaseParameterDialog(phase, window.setup.p_meta, window.runner.state.p)
    assert "Nothing" in dialog.summary.toPlainText()

    dialog._boxes["pO2w"].setValue(dialog._original["pO2w"] + 5)
    assert "pO2w" in dialog.summary.toPlainText()
    assert "→" in dialog.summary.toPlainText()


def test_only_an_update_phase_offers_the_whole_parameter_set(window):
    """A manual phase applies nothing, so it offers nothing.

    A list of fields that do nothing is worse than no list.
    """
    from biofermentation.gui.dialogs.parameters import offered_parameters

    phase = window.setup.phases[-1]
    p_meta = window.setup.p_meta

    phase.typeID = PhaseType.PARAMETER_UPDATE
    everything = offered_parameters(phase, p_meta)
    assert len(everything) > 50
    assert all(meta["reading_rate"] == "cyclic" for meta in everything)

    for type_id in (PhaseType.MANUAL, PhaseType.STOP):
        phase.typeID = type_id
        assert offered_parameters(phase, p_meta) == []


def test_a_feed_phase_offers_its_own_reservoir_and_nothing_else(window):
    """The five the exponential feed computes FRj from, for that reservoir."""
    from biofermentation.gui.dialogs.parameters import offered_parameters

    phase = window.setup.phases[-1]
    p_meta = window.setup.p_meta

    phase.typeID = PhaseType.EXPONENTIAL_FEED
    phase.reservoirID = 1
    names = [meta["parametername"] for meta in offered_parameters(phase, p_meta)]
    assert names == ["qXpX1w", "qS1pXm", "yXpS1gr", "cS1R1", "FR1max"]

    phase.reservoirID = 2
    names = [meta["parametername"] for meta in offered_parameters(phase, p_meta)]
    assert all(name.count("2") for name in names), names
    assert "qXpX1w" not in names

    phase.typeID = PhaseType.PULSE_FEED
    phase.reservoirID = 1
    names = [meta["parametername"] for meta in offered_parameters(phase, p_meta)]
    assert names == ["kR1", "FR1max"]


def test_the_results_a_feed_phase_writes_are_not_offered(window):
    """t1j, cXL1j and FR1j are its record of what it did, not settings."""
    from biofermentation.gui.dialogs.parameters import offered_parameters

    phase = window.setup.phases[-1]
    phase.typeID = PhaseType.EXPONENTIAL_FEED
    phase.reservoirID = 1
    names = {meta["parametername"] for meta in offered_parameters(phase, window.setup.p_meta)}
    assert names.isdisjoint({"t1j", "cXL1j", "FR1j"})


def test_a_value_the_field_cannot_show_is_not_a_change(window):
    """KD_gasmix is 1e-05, and a box with four decimals handed back 0.

    Every phase then carried "KD_gasmix: 1e-05 → 0" without anyone touching
    it, and the dialog offered to apply that.
    """
    from biofermentation.gui.dialogs import PhaseParameterDialog

    phase = window.setup.phases[-1]
    phase.parameters = {}
    phase.typeID = PhaseType.PARAMETER_UPDATE
    p = window.runner.state.p
    p["KD_gasmix"] = 1e-05

    dialog = PhaseParameterDialog(phase, window.setup.p_meta, p)
    assert dialog._boxes["KD_gasmix"].value() == pytest.approx(1e-05)
    assert "Nothing" in dialog.summary.toPlainText()
    assert dialog._resets["KD_gasmix"].isVisibleTo(dialog) is False

    dialog.accept()
    assert phase.parameters == {}


def test_a_field_gets_enough_places_for_what_is_put_into_it():
    from biofermentation.gui.dialogs.parameters import decimals_for

    assert decimals_for(1.0) == 4, "the ordinary case keeps four"
    assert decimals_for(0.0) == 4
    assert decimals_for(1234.5) == 4
    assert decimals_for(1e-05) == 8, "0.0000 is not 1e-05"
    assert decimals_for(1e-30) == 12, "and there is an end to it"


def test_the_drop_button_is_wide_enough_to_read(window):
    """A fixed 28 px left the stylesheet's padding and clipped the label."""
    from biofermentation.gui.dialogs import PhaseParameterDialog

    phase = window.setup.phases[-1]
    phase.typeID = PhaseType.PARAMETER_UPDATE
    dialog = PhaseParameterDialog(phase, window.setup.p_meta, window.runner.state.p)
    button = next(iter(dialog._resets.values()))
    assert button.width() >= button.sizeHint().width()


def test_an_existing_phase_parameter_comes_back_into_the_dialog(window):
    from biofermentation.gui.dialogs import PhaseParameterDialog

    phase = window.setup.phases[-1]
    phase.parameters = {"pO2w": 42.0}
    phase.typeID = PhaseType.PARAMETER_UPDATE
    dialog = PhaseParameterDialog(phase, window.setup.p_meta, window.runner.state.p)
    assert dialog._boxes["pO2w"].value() == pytest.approx(42.0)
    assert dialog._resets["pO2w"].isVisibleTo(dialog) is True


def test_cancelling_the_phase_editor_drops_the_parameters(window):
    """They are edited on the draft, like everything else in that dialog."""
    from biofermentation.gui.dialogs import PhaseEditor

    phase = window.setup.phases[-1]
    phase.parameters = {}
    phase.typeID = PhaseType.PARAMETER_UPDATE
    dialog = PhaseEditor(
        phase,
        window.setup.lookups,
        reservoirs=2,
        p_meta=window.setup.p_meta,
        p=window.runner.state.p,
    )
    dialog._draft.parameters["pO2w"] = 55.0
    dialog.reject()
    assert phase.parameters == {}

    dialog = PhaseEditor(
        phase,
        window.setup.lookups,
        reservoirs=2,
        p_meta=window.setup.p_meta,
        p=window.runner.state.p,
    )
    dialog._draft.parameters["pO2w"] = 55.0
    dialog.accept()
    assert phase.parameters == {"pO2w": 55.0}


def test_a_stop_phase_has_no_parameters_to_apply(window):
    from biofermentation.control import PhaseType
    from biofermentation.gui.dialogs import PhaseEditor
    from biofermentation.gui.widgets.indicators import select_data

    dialog = PhaseEditor(
        window.setup.phases[-1],
        window.setup.lookups,
        reservoirs=2,
        p_meta=window.setup.p_meta,
        p=window.runner.state.p,
    )
    assert select_data(dialog.type_box, PhaseType.PARAMETER_UPDATE)
    assert dialog.parameters_button.isEnabled() is True

    assert select_data(dialog.type_box, PhaseType.STOP)
    assert dialog.parameters_button.isEnabled() is False


# ------------------------------------------------------- closing a project --


def _answer(monkeypatch, choice):
    """Make the closing dialog answer without being shown."""
    from biofermentation.gui.dialogs.closing import ClosingDialog

    def exec_(self):
        self.choice = choice
        return int(ClosingDialog.DialogCode.Accepted)

    monkeypatch.setattr(ClosingDialog, "exec", exec_)


def test_closing_asks_and_a_cancel_keeps_the_window(window, monkeypatch):
    """Point 4: leaving a project is a decision, not a click on the close box."""
    from biofermentation.gui.dialogs.closing import Choice

    _answer(monkeypatch, Choice.CANCEL)
    window.close()
    assert window._leave_confirmed is False, "cancel must not count as an answer"


def test_closing_with_save_writes_the_three_fields(window, db, monkeypatch):
    from biofermentation.db import load_project_info
    from biofermentation.gui.dialogs.closing import Choice, ClosingDialog

    def exec_(self):
        self.name_field.setText("Renamed")
        self.author_field.setText("Yuma")
        self.description_field.setPlainText("A run to keep")
        self.choice = Choice.SAVE
        return int(ClosingDialog.DialogCode.Accepted)

    monkeypatch.setattr(ClosingDialog, "exec", exec_)
    window.close()

    info = load_project_info(db, PROJECT)
    assert (info.name, info.author, info.description) == ("Renamed", "Yuma", "A run to keep")
    assert window._leave_confirmed is True


def test_closing_with_delete_asks_a_second_time(window, db, monkeypatch):
    """Deleting a project cannot be taken back, so one click is not enough."""
    from PySide6.QtWidgets import QMessageBox

    from biofermentation.db import list_projects
    from biofermentation.gui.dialogs.closing import Choice

    _answer(monkeypatch, Choice.DELETE)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel
    )
    window.close()
    assert PROJECT in [row["projectID"] for row in list_projects(db)]
    assert window._leave_confirmed is False

    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    window.close()
    assert PROJECT not in [row["projectID"] for row in list_projects(db)]


def test_the_export_button_leaves_the_dialog_open(qapp):
    """Exporting is not a decision about the project; one is still due."""
    from biofermentation.gui.dialogs.closing import Choice, ClosingDialog

    info = ProjectInfo(
        projectID=1,
        name="Demo",
        description="",
        author="",
        created_on=None,
        recent_use=None,
        organismID=1,
        organism_name="E. coli",
        function_file="Escherichia_coli",
        initialization_file=None,
        reservoirs=1,
        bioreactorID=1,
        bioreactor_name="BIOSTAT ED",
        modelID=1,
    )
    dialog = ClosingDialog(info)
    seen = []
    dialog.export_requested.connect(lambda: seen.append(True))
    dialog.export_button.click()
    assert seen == [True]
    assert dialog.choice is Choice.CANCEL, "no decision has been made yet"


# ------------------------------------------------------ the bioreactors --


@pytest.fixture
def reactors(db, qapp):
    from biofermentation.gui.dialogs.bioreactors import BioreactorManager

    return BioreactorManager(db)


def test_the_dialog_shows_a_vessel_with_all_its_parameters(reactors):
    assert reactors.list.count() == 2
    assert reactors._current == "BIOSTAT ED"
    assert len(reactors._boxes) == 60
    assert reactors.name_edit.text() == "BIOSTAT ED"
    assert reactors.manufacturer_edit.text() == "B. Braun Stedim"


def test_a_vessel_something_stands_on_cannot_be_deleted_from_here(reactors):
    assert reactors.delete_button.isEnabled() is False
    reactors.list.setCurrentRow(1)  # BIOSTAT B, used by nothing
    assert reactors._current == "BIOSTAT B"
    assert reactors.delete_button.isEnabled() is True


def test_a_new_vessel_is_a_copy_of_the_one_it_was_made_from(reactors, db):
    """Which parameters make up a vessel is not something a form should ask."""
    from biofermentation.db import export_bioreactor

    assert reactors.create_from_selected("Wubbelbrew 5 l") == "Wubbelbrew 5 l"
    assert reactors._current == "Wubbelbrew 5 l"

    made = export_bioreactor(db, "Wubbelbrew 5 l")
    source = export_bioreactor(db, "BIOSTAT ED")
    assert made.parameters == source.parameters
    assert made.manufacturer == source.manufacturer


def test_a_name_that_is_taken_is_refused(reactors, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    assert reactors.create_from_selected("BIOSTAT B") is None
    assert reactors.list.count() == 2


def test_a_new_vessel_reaches_a_project_through_a_model(reactors, db, monkeypatch):
    """The whole chain, because each link alone is useless: a vessel, a model
    on it, and a project that carries its values."""
    from PySide6.QtWidgets import QMessageBox

    from biofermentation.db import create_project, export_bioreactor, load_phases

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    reactors.create_from_selected("Wubbelbrew 5 l")
    reactors._boxes["VLmax"].setValue(4.5)
    assert reactors.save() is True
    assert export_bioreactor(db, "Wubbelbrew 5 l").parameters["VLmax"] == pytest.approx(4.5)

    model_id = reactors.create_model_for_selected(organism_id=1, name="E. coli in Wubbelbrew")
    assert model_id is not None

    project = create_project(db, "On the new vessel", model_id)
    assert load_phases(db, project).p["VLmax"] == pytest.approx(4.5)
    # And the organism's own parameters came along.
    assert load_phases(db, project).p["cS1L0"] > 0


def test_a_rename_moves_the_vessel_rather_than_copying_it(reactors, db, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from biofermentation.db import list_bioreactors

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    reactors.list.setCurrentRow(1)  # BIOSTAT B — nothing stands on it
    reactors.name_edit.setText("BIOSTAT B mk II")
    assert reactors.save() is True

    names = {row["name"] for row in list_bioreactors(db)}
    assert "BIOSTAT B mk II" in names
    assert "BIOSTAT B" not in names
    assert len(names) == 2


def test_a_vessel_without_a_model_cannot_be_chosen_anywhere(reactors, db):
    """Which is why the dialog has a button for it: create_project reads
    nothing but model_parameterTab."""
    from biofermentation.db import list_models

    reactors.create_from_selected("Wubbelbrew 5 l")
    assert all(row["bioreactor_name"] != "Wubbelbrew 5 l" for row in list_models(db))


def test_a_model_carries_each_parameter_once(db):
    """project_parameterTab is UNIQUE on (projectID, parameterID): a model
    that named a parameter twice would make a project that cannot be created."""
    import sqlite3

    from biofermentation.db import create_model

    model_id = create_model(db, "Twice over", 1, 1)
    with sqlite3.connect(db) as conn:
        rows, distinct = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT parameterID) FROM model_parameterTab "
            "WHERE modelID = ?",
            (model_id,),
        ).fetchone()
    assert rows == distinct


def test_deleting_from_the_dialog_takes_the_values_with_it(reactors, db):
    from biofermentation.db import list_bioreactors

    reactors.list.setCurrentRow(1)
    assert reactors.delete_selected(confirmed=True) is True
    assert {row["name"] for row in list_bioreactors(db)} == {"BIOSTAT ED"}


# -------------------------------------------------------- the organisms --


@pytest.fixture
def organisms(db, qapp):
    from biofermentation.gui.dialogs.organisms import OrganismManager

    return OrganismManager(db)


def test_the_organism_dialog_shows_the_values_and_names_the_kinetics(organisms):
    """The kinetics are a plugin, not data — the dialog says so rather than
    offering a field that could point anywhere."""
    assert organisms.list.count() == 2
    assert organisms._current == "Escherichia coli"
    assert len(organisms._boxes) > 100
    assert "Escherichia_coli" in organisms.kinetics_label.text()
    assert organisms.reservoirs_label.text() == "1"
    assert organisms.delete_button.isEnabled() is False


def test_a_copied_organism_keeps_the_kinetics_and_drops_the_models(organisms, db):
    """Same equations, its own numbers — that is what a copy is for. The
    models belong to the original; the copy gets the one it needs."""
    from biofermentation.db.definitions import export_definition
    from biofermentation.db.project import list_models

    assert organisms.create_from_selected("E. coli K-12") == "E. coli K-12"
    copy = export_definition(db, "E. coli K-12")
    source = export_definition(db, "Escherichia coli")

    assert copy.function_file == source.function_file
    assert len(copy.parameters) == len(source.parameters)
    assert all(row["organism_name"] != "E. coli K-12" for row in list_models(db))
    assert organisms.delete_button.isEnabled() is True, "nothing stands on it yet"


def test_a_copied_organism_reaches_a_project_through_a_model(organisms, db, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from biofermentation.db import create_project, load_phases

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    organisms.create_from_selected("E. coli K-12")
    name = next(iter(organisms._boxes))
    organisms._boxes[name].setValue(0.25)
    assert organisms.save(announce=False) is True

    model_id = organisms.create_model_for_selected(bioreactor_id=1, name="K-12 in BIOSTAT ED")
    assert model_id is not None
    project = create_project(db, "On the copy", model_id)
    assert load_phases(db, project).p[name] == pytest.approx(0.25)


def test_renaming_an_organism_keeps_its_models(organisms, db, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from biofermentation.db.definitions import organism_usage

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    before = organism_usage(db, "Escherichia coli")
    organisms.name_edit.setText("E. coli (HAW)")
    assert organisms.save() is True

    assert organisms._current == "E. coli (HAW)"
    assert organism_usage(db, "E. coli (HAW)") == before


def test_a_name_that_is_taken_is_refused_for_organisms(organisms, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    assert organisms.create_from_selected("Pichia pastoris") is None
    assert organisms.list.count() == 2

    organisms.name_edit.setText("Pichia pastoris")
    assert organisms.save() is False


# ------------------------------------------- the resolution that is stored --


def _stored_times(db_path) -> list[float]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT process_time FROM timeTab WHERE projectID = ? ORDER BY 1", (PROJECT,)
            )
        ]


def test_the_closing_dialog_offers_the_stored_resolution(qapp):
    """It defaults to the setting and says what the number costs.

    The moment of saving is the last one at which the decision can be made,
    and the only one at which somebody knows how long the run turned out to
    be — so the dialog asks again rather than only obeying the setting.
    """
    from biofermentation.gui.dialogs.closing import ClosingDialog

    info = ProjectInfo(
        projectID=1,
        name="Demo",
        description="",
        author="",
        created_on=None,
        recent_use=None,
        organismID=1,
        organism_name="E. coli",
        function_file="Escherichia_coli",
        initialization_file=None,
        reservoirs=1,
        bioreactorID=1,
        bioreactor_name="BIOSTAT ED",
        modelID=1,
    )
    dialog = ClosingDialog(info, storage_interval=5, dt_seconds=2.0)
    assert dialog.storage_interval() == 5
    assert "10 s" in dialog.storage_note.text(), "5 steps of 2 s is one point every 10 s"

    dialog.storage_box.setValue(1)
    assert dialog.storage_box.suffix() == " step", "not 'per 1 steps'"
    assert "everything" in dialog.storage_note.text()


def test_saving_writes_only_every_n_th_step_when_asked(window, db, monkeypatch):
    """Δt stays what it is; only the number of rows written changes.

    The run is unaffected — every step is computed and plotted. What the file
    keeps is this question, and it is asked where the answer is known.
    """
    from biofermentation.gui.dialogs.closing import Choice, ClosingDialog

    before = _stored_times(db)
    for _ in range(6):
        window.runner._on_tick()
    state = window.runner.state
    computed = state.idx + 1

    def exec_(self):
        self.storage_box.setValue(3)
        self.choice = Choice.SAVE
        return int(ClosingDialog.DialogCode.Accepted)

    monkeypatch.setattr(ClosingDialog, "exec", exec_)
    window.close()

    after = _stored_times(db)
    new = after[len(before) :]
    assert len(new) == 3, f"{computed} computed points at every third, got {len(new)}"
    assert new[1] - new[0] == pytest.approx(3 * state.dt, rel=1e-9), "an even grid"
    # Whatever the interval, the newest step is stored: a run that is picked
    # up again has to carry on from where it actually stopped.
    assert new[-1] == pytest.approx(state.v.t[computed - 1], abs=1e-9)


# --------------------------------------------------------- managing models --


@pytest.fixture
def models(db, qapp):
    from biofermentation.gui.dialogs.models import ModelManager

    manager = ModelManager(db)
    yield manager
    manager.close()


def _shown(manager) -> list[str]:
    """Which parameter fields the filter lets through.

    `isVisible()` is False for every widget of a dialog that was never shown;
    the state question is `isVisibleTo(parent)`. See CLAUDE.md, UX point 7.
    """
    return [
        name for name, box in manager._boxes.items() if box.isVisibleTo(box.parentWidget())
    ]


def test_the_dialog_lists_every_model_with_its_pair(models, db):
    from biofermentation.db import list_models

    rows = list_models(db)
    assert models.list.count() == len(rows) == 3
    assert models._current is not None
    assert models.organism_label.text()
    assert models.bioreactor_label.text()
    # The parameter set of a model is the union of the organism's and the
    # vessel's; 253 is what this template's Escherichia model carries.
    assert len(models._boxes) == 253


def test_a_new_model_is_an_organism_in_a_vessel(models, db):
    """The pairing is the whole point: create_project reads nothing else."""
    from biofermentation.db import list_bioreactors, list_models
    from biofermentation.db.definitions import list_organisms

    organism = list_organisms(db)[0]
    vessel = next(row for row in list_bioreactors(db) if row["name"] == "BIOSTAT B")
    before = len(list_models(db))

    model_id = models.create_model(
        organism["organismID"], vessel["bioreactorID"], "E. coli in BIOSTAT B"
    )
    assert model_id is not None
    assert len(list_models(db)) == before + 1
    assert models._current == model_id, "the dialog lands on what it just made"
    assert models.bioreactor_label.text() == "BIOSTAT B"
    assert len(models._boxes) > 0


def test_a_model_a_project_stands_on_cannot_be_deleted(models, db):
    """The cascade taking projects with it is how MATLAB lost them."""
    from biofermentation.db import delete_model, model_usage

    used = next(
        row for row in models.models() if model_usage(db, row["modelID"])["projects"]
    )
    models._select(used["modelID"])
    assert models.delete_button.isEnabled() is False
    with pytest.raises(ValueError, match="still used"):
        delete_model(db, used["modelID"])


def test_a_model_nothing_stands_on_goes_with_its_parameters(models, db):
    from biofermentation.db import list_bioreactors, list_models
    from biofermentation.db.definitions import list_organisms

    organism = list_organisms(db)[0]
    vessel = list_bioreactors(db)[0]
    model_id = models.create_model(organism["organismID"], vessel["bioreactorID"], "Throwaway")
    assert models.delete_button.isEnabled() is True

    assert models.delete_selected(confirmed=True) is True
    assert model_id not in [row["modelID"] for row in list_models(db)]
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM model_parameterTab WHERE modelID = ?", (model_id,)
        ).fetchone()[0]
    assert left == 0, "the parameter rows cascade with the model row"


def test_renaming_a_model_is_an_update_not_a_second_model(models, db):
    """Projects point at modelID; a rename must not strand them."""
    from biofermentation.db import list_models, model_usage

    current = next(row for row in models.models() if model_usage(db, row["modelID"])["projects"])
    models._select(current["modelID"])
    projects = model_usage(db, current["modelID"])["projects"]

    models.name_edit.setText("Escherichia coli — teaching")
    assert models.save(announce=False) is True

    rows = list_models(db)
    assert len(rows) == 3, "renamed, not duplicated"
    renamed = next(row for row in rows if row["modelID"] == current["modelID"])
    assert renamed["name"] == "Escherichia coli — teaching"
    assert model_usage(db, current["modelID"])["projects"] == projects


def test_a_duplicate_carries_the_values_as_they_are_now(models, db):
    """A variant is made from the model, not from the defaults it came from."""
    from biofermentation.db import model_parameters

    name = next(iter(models._boxes))
    models._boxes[name].setValue(models._boxes[name].value() + 1.5)
    edited = models._boxes[name].value()
    assert models.save(announce=False) is True

    copy_id = models.duplicate_selected("A copy of it")
    assert copy_id is not None
    values = {row["parametername"]: row["value"] for row in model_parameters(db, copy_id)}
    assert values[name] == pytest.approx(edited)


def test_the_filter_narrows_the_parameter_list(models):
    """253 parameters is four times what a vessel has; scrolling is not a plan."""
    everything = len(_shown(models))
    assert everything == len(models._boxes)

    models.filter_edit.setText("KP_")
    gains = _shown(models)
    assert 0 < len(gains) < everything
    assert all(name.startswith("KP_") for name in gains)

    models.filter_edit.clear()
    assert len(_shown(models)) == everything


def test_the_organism_and_the_vessel_are_shown_and_not_editable(models):
    """A different pairing is a different model, not an edit to this one."""
    from PySide6.QtWidgets import QLabel

    assert isinstance(models.organism_label, QLabel)
    assert isinstance(models.bioreactor_label, QLabel)
    assert not hasattr(models, "organism_box")


def test_the_new_model_dialog_suggests_a_name_and_then_leaves_it_alone(qapp, db):
    from biofermentation.db import list_bioreactors
    from biofermentation.db.definitions import list_organisms
    from biofermentation.gui.dialogs.models import NewModelDialog

    organisms, vessels = list_organisms(db), list_bioreactors(db)
    dialog = NewModelDialog(organisms, vessels)
    assert dialog.name_edit.text() == f"{organisms[0]['name']} in {vessels[0]['name']}"

    dialog.bioreactor_box.setCurrentIndex(1)
    assert dialog.name_edit.text() == f"{organisms[0]['name']} in {vessels[1]['name']}"

    # A name somebody typed is theirs from then on.
    dialog.name_edit.setText("My own name")
    dialog.name_edit.textEdited.emit("My own name")
    dialog.organism_box.setCurrentIndex(1)
    assert dialog.name_edit.text() == "My own name"


# ------------------------------------------------ the anti-windup switch --


def _controller_dialog(window, title: str):
    from biofermentation.gui.dialogs.parameters import ControllerParametersDialog

    spec = next(s for s in CONTROL_PANELS if s.title == title)
    return spec, ControllerParametersDialog(
        spec, window.runner.state.p, reservoirs=window.setup.info.reservoirs or 1
    )


def test_each_controller_that_can_wind_up_carries_its_own_switch(window):
    """One switch per loop, in the dialog the gains live in.

    It belongs with the gains rather than on the panel: it changes how the
    integrator behaves, not what the operator asks the process for.
    """
    from biofermentation.gui.dialogs.parameters import SwitchBox

    for title in ("pO2-Control", "Liquid Weight", "Feed Control"):
        spec, dialog = _controller_dialog(window, title)
        assert spec.anti_windup, title
        widget = dialog._boxes.get(spec.anti_windup)
        assert isinstance(widget, SwitchBox), f"{title} has no switch"
        assert widget.value() == 0.0, "off is the default in every project"

    for title in ("pH-Control", "Temperature-Control"):
        spec, dialog = _controller_dialog(window, title)
        assert spec.anti_windup is None
        assert not any("f_aw" in name for name in dialog._boxes), title


def test_throwing_the_switch_is_the_only_change_it_reports(window):
    """An untouched switch is not a change, a thrown one is exactly one."""
    spec, dialog = _controller_dialog(window, "Feed Control")
    dialog.accept()
    assert dialog.changes == {}, "opening and confirming changes nothing"

    spec, dialog = _controller_dialog(window, "Feed Control")
    dialog._boxes[spec.anti_windup].switch.setChecked(True)
    dialog.accept()
    assert dialog.changes == {spec.anti_windup: 1.0}


def test_the_switch_says_which_way_it_points(window):
    """0 and 1 are a position, not a quantity — so the label reads as one."""
    spec, dialog = _controller_dialog(window, "pO2-Control")
    widget = dialog._boxes[spec.anti_windup]
    assert "integrat" in widget.label.text().lower()
    widget.switch.setChecked(True)
    assert "limit" in widget.label.text().lower()
    assert widget.value() == 1.0


def test_a_project_without_the_parameter_says_so_instead_of_hiding_it(window, qapp):
    """An absent control is indistinguishable from one nobody found."""
    from PySide6.QtWidgets import QLabel

    from biofermentation.gui.dialogs.parameters import ControllerParametersDialog

    spec = next(s for s in CONTROL_PANELS if s.title == "Feed Control")
    older = {name: value for name, value in window.runner.state.p.items() if name != "f_awfeed"}
    dialog = ControllerParametersDialog(spec, older, reservoirs=1)

    assert spec.anti_windup not in dialog._boxes
    said = [
        label.text()
        for label in dialog.findChildren(QLabel)
        if "anti-windup switch" in label.text()
    ]
    assert said, "the dialog is silent about the missing switch"


def test_an_older_database_is_given_the_switches_when_it_is_opened(db):
    """The database a student already has is a copy of an older template.

    Adding the four flags changes no behaviour — every row is written as 0,
    which is what a missing parameter already meant — but without them the
    switch in the dialog has nothing to write to.
    """
    from biofermentation.db import get_connection
    from biofermentation.gui.app import _ensure_switch_parameters

    with get_connection(db) as conn:
        for table in ("project_parameterTab", "model_parameterTab", "default_modelTab"):
            conn.execute(
                f"DELETE FROM {table} WHERE parameterID IN "
                "(SELECT parameterID FROM parameterTab WHERE name LIKE 'f_aw%')"
            )
        conn.execute("DELETE FROM parameterTab WHERE name LIKE 'f_aw%'")

    added = _ensure_switch_parameters(db)
    assert sorted(added) == ["f_awLW", "f_awfeed", "f_awpO2", "f_awtemp"]

    with get_connection(db, readonly=True) as conn:
        values = [
            row[0]
            for row in conn.execute(
                "SELECT pp.value FROM project_parameterTab pp JOIN parameterTab p "
                "ON p.parameterID = pp.parameterID WHERE p.name LIKE 'f_aw%'"
            )
        ]
    assert values and set(values) == {0.0}, "added as off, so nothing computes differently"
    # Idempotent: opening the application twice adds them once.
    assert _ensure_switch_parameters(db) == []


def test_the_stored_resolution_can_be_hidden_from_the_closing_dialog(qapp):
    """Hidden, the field still carries the setting into the save.

    The box exists either way, so `storage_interval()` answers the same
    question whether or not anybody was asked it.
    """
    from biofermentation.gui.dialogs.closing import ClosingDialog

    info = ProjectInfo(
        projectID=1,
        name="Demo",
        description="",
        author="",
        created_on=None,
        recent_use=None,
        organismID=1,
        organism_name="E. coli",
        function_file="Escherichia_coli",
        initialization_file=None,
        reservoirs=1,
        bioreactorID=1,
        bioreactor_name="BIOSTAT ED",
        modelID=1,
    )
    asked = ClosingDialog(info, storage_interval=5, dt_seconds=2.0, ask_storage=True)
    assert asked.storage_box.isVisibleTo(asked)
    assert asked.storage_interval() == 5

    quiet = ClosingDialog(info, storage_interval=5, dt_seconds=2.0, ask_storage=False)
    assert not quiet.storage_box.isVisibleTo(quiet), "the row is not built"
    assert quiet.storage_interval() == 5, "and the setting still reaches the save"


def test_the_feed_panel_shows_three_decimals(qapp):
    """Four was more than a pump rate is known to."""
    from biofermentation.gui.widgets.panel_specs import FEED_PANEL

    decimals = {spec.parameter: spec.decimals for spec in FEED_PANEL.fields}
    assert decimals == {"cS{n}Lw": 3, "FR{n}w": 3, "FR{n}max": 3}


# ------------------------------------------- a flag is drawn as a switch --


def _update_phase(window):
    """The first phase of the project, turned into an Update Parameter Set."""
    from biofermentation.control import PhaseType

    phase = window.setup.phases[0]
    phase.typeID = int(PhaseType.PARAMETER_UPDATE)
    return phase


def test_a_flag_in_the_phase_dialog_is_a_switch_not_a_number(window):
    """0 and 1 are a position. The database has said so all along.

    `parameterTab.type` carries `switch` for 22 parameters, `dropdown` for the
    five modes and `editfield` for the rest; the editors drew every one of them
    as an edit field.
    """
    from biofermentation.gui.dialogs.parameters import ModeBox, PhaseParameterDialog, SwitchBox

    phase = _update_phase(window)
    dialog = PhaseParameterDialog(
        phase, window.setup.p_meta, window.runner.state.p, modes=window.modes
    )
    kinds = {meta["parametername"]: meta.get("type") for meta in window.setup.p_meta}
    for name, widget in dialog._boxes.items():
        if kinds.get(name) == "switch":
            assert isinstance(widget, SwitchBox), f"{name} is a flag"
        elif kinds.get(name) == "dropdown":
            assert isinstance(widget, ModeBox), f"{name} is a mode"
        else:
            assert not isinstance(widget, SwitchBox), f"{name} is not a flag"

    switches = [n for n, w in dialog._boxes.items() if isinstance(w, SwitchBox)]
    assert len(switches) > 10, "an Update Parameter Set phase offers every cyclic flag"


def test_the_phase_summary_reads_a_switch_as_a_position(window):
    from biofermentation.gui.dialogs.parameters import PhaseParameterDialog

    phase = _update_phase(window)
    dialog = PhaseParameterDialog(
        phase, window.setup.p_meta, window.runner.state.p, modes=window.modes
    )
    before = float(window.runner.state.p["f_acid"])
    dialog._boxes["f_acid"].switch.setChecked(not before)

    assert "f_acid: Off → On" in dialog.summary.toPlainText() or (
        "f_acid: On → Off" in dialog.summary.toPlainText()
    )
    assert "f_acid: 0" not in dialog.summary.toPlainText(), "not as a number"

    # And the Drop button comes back the way it does for any other field.
    assert dialog._resets["f_acid"].isVisibleTo(dialog)
    dialog._reset("f_acid")
    assert dialog._boxes["f_acid"].value() == before
    assert "Nothing" in dialog.summary.toPlainText()


def test_a_thrown_switch_is_stored_as_one(window):
    from biofermentation.gui.dialogs.parameters import PhaseParameterDialog

    phase = _update_phase(window)
    dialog = PhaseParameterDialog(
        phase, window.setup.p_meta, window.runner.state.p, modes=window.modes
    )
    dialog._boxes["f_harvest"].switch.setChecked(True)
    dialog.accept()
    assert dialog.changes == {"f_harvest": 1.0}


def test_the_full_parameter_dialog_draws_flags_the_same_way(window):
    """One helper serves both dialogs, so both tell the same story."""
    from biofermentation.gui.dialogs.parameters import ParameterDialog, SwitchBox

    dialog = ParameterDialog(
        window.setup.p_meta, window.runner.state.p, started=True, modes=window.modes
    )
    assert isinstance(dialog._boxes["f_acid"], SwitchBox)
    assert not isinstance(dialog._boxes["pHw"], SwitchBox)


# ------------------------------------------------- how a dialog is shaped --


def _group_boxes(dialog):
    from PySide6.QtWidgets import QGroupBox

    dialog.resize(dialog.sizeHint())
    dialog.show()
    return [box for box in dialog.findChildren(QGroupBox) if box.title()]


def test_the_po2_gains_stand_two_by_two(window):
    """Five groups in a column made a dialog taller than a laptop screen.

    pO2 is the only controller with more than four: the four manipulated
    variables and the sensor. Measured before and after, at the same width:
    837 px tall against 557.
    """
    from biofermentation.gui.dialogs.parameters import ControllerParametersDialog
    from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS

    spec = next(s for s in CONTROL_PANELS if s.title == "pO2-Control")
    dialog = ControllerParametersDialog(spec, window.runner.state.p, reservoirs=1)
    boxes = {box.title(): box.geometry() for box in _group_boxes(dialog)}

    assert boxes["Agitation"].y() == boxes["Gasmix"].y(), "first row"
    assert boxes["Agitation"].x() < boxes["Gasmix"].x()
    assert boxes["Aeration"].y() == boxes["Feed"].y(), "second row"
    assert boxes["Aeration"].y() > boxes["Agitation"].y()
    # The odd one out takes the whole row rather than half of it.
    assert boxes["Sensor"].width() > boxes["Agitation"].width()
    assert boxes["Anti-windup"].y() > boxes["Sensor"].y()

    # **A relation, not a pixel count.** Font metrics differ per system —
    # this project has been caught by that twice — so what is asserted is
    # that the grid is shorter than the same groups in a column would be,
    # which holds whatever the font.
    stacked = sum(box.height() for box in boxes.values())
    assert dialog.height() < stacked, f"{dialog.height()} px against {stacked} stacked"


def test_a_controller_with_three_groups_stays_in_one_column(window):
    """The rule earns its keep only where it is needed."""
    from biofermentation.gui.dialogs.parameters import ControllerParametersDialog
    from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS

    for title in ("pH-Control", "Temperature-Control"):
        spec = next(s for s in CONTROL_PANELS if s.title == title)
        dialog = ControllerParametersDialog(spec, window.runner.state.p, reservoirs=1)
        tops = [box.geometry().y() for box in _group_boxes(dialog)]
        assert len(tops) == len(set(tops)), f"{title} put two groups on one row"


def test_the_settings_dialog_is_wide_enough_to_read(qapp, tmp_path):
    """It is mostly explanation, and at 440 px every note wrapped five times."""
    from PySide6.QtWidgets import QLabel

    from biofermentation.gui.dialogs.settings import SettingsDialog

    dialog = SettingsDialog(path=tmp_path / "settings.yaml")
    dialog.show()
    assert dialog.width() >= 680

    # Nothing may be cut off at the bottom: a dialog that hides the end of a
    # sentence is worse than one with room to spare.
    for label in dialog.findChildren(QLabel):
        bottom = label.mapTo(dialog, label.rect().bottomLeft()).y()
        assert bottom <= dialog.height(), f"clipped: {label.text()[:40]}"
