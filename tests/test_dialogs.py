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

from biofermentation.control import PhaseAutomaton
from biofermentation.core.runner import DEFAULT_DT, load_project_state
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import load_phases
from biofermentation.db.plots import load_plot_styles, load_plot_template
from biofermentation.gui.dialogs.export import ExportDialog, write_table, write_text_table
from biofermentation.gui.dialogs.parameters import ControllerParametersDialog, ParameterDialog
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
    visible = [widget for widget, hay in dialog._rows if "kp_ph" in hay]
    assert visible and all(widget.isVisibleTo(dialog) for widget in visible)
    others = [widget for widget, hay in dialog._rows if "cs1l0" in hay]
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
    }
    assert "one log line" in (folder / "log.txt").read_text()
    assert "cXL" in (folder / "variables.csv").read_text().splitlines()[0]


def test_the_export_dialog_honours_the_checkboxes(window, tmp_path):
    dialog = ExportDialog(window.setup, window.runner.state, [])
    dialog.folder_edit.setText(str(tmp_path))
    for key, box in dialog.checkboxes.items():
        box.setChecked(key == "phases")
    dialog.accept()
    assert [path.name for path in dialog.written] == ["phases.csv"]


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

    template = load_plot_template(db, 1)
    editor = VariableEditor(template, load_plot_styles(db))
    name = template.variables[0].name
    select_data(editor.rows[name]["color"], 7)
    editor.accept()
    save_plot_template(db, template)

    assert load_plot_template(db, 1).variables[0].colorID == 7


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


def test_disconnect_stops_the_timer_without_ending_the_session(window):
    window.runner.start()
    window.toggle_connection()
    assert window.runner.running is False
    assert window.disconnect_action.text() == "Reconnect"

    window.toggle_connection()
    assert window.runner.running is True
    assert window.disconnect_action.text() == "Disconnect"
    window.runner.pause()


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
