"""The dialogs added in the UX round: parameters, export, data table, plots.

Headless like the rest of the GUI tests. What is checked is not the layout
but the two rules the dialogs live by: nothing is written before Ok, and what
may be edited during a run is decided by the database, not by the widget.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from biofermentation.control import PhaseAutomaton, PhaseType
from biofermentation.core.runner import DEFAULT_DT, load_project_state
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import load_phases
from biofermentation.db.plots import load_plot_styles, load_plot_template
from biofermentation.gui.dialogs.export import ExportDialog, write_table, write_text_table
from biofermentation.gui.dialogs.parameters import (
    SECTION_ORDER,
    ControllerParametersDialog,
    ParameterDialog,
)
from biofermentation.gui.dialogs.plot_settings import STANDARD, PlotSettingsDialog, VariableEditor
from biofermentation.gui.widgets.indicators import select_data
from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS, PH_PANEL
from biofermentation.gui.windows.control_app import ControlWindow

TEMPLATE = Path("src/biofermentation/resources/SimulationAppDB_template.db")
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
    from biofermentation.db.models import ProjectInfo
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
