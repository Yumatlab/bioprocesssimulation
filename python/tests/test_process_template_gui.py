"""Saving the process as a template from the window — Projektplan_Prozessvorlagen.md, phase 3.

Project 519 (Pichia) has a process to save: a completed batch, an active
fed-batch, pulses and a parameter update. Project 716 has none. The two
questions the window asks — the details and whether to overwrite — are
replaced in the tests; a modal dialog in a test is a run that hangs.
"""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from biofermentation.control import PhaseAutomaton
from biofermentation.core.runner import load_project_state
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import (
    get_connection,
    list_process_templates,
    load_phases,
    load_process_template,
)
from biofermentation.db.migrate import TEMPLATE_TABLES
from biofermentation.gui.dialogs.process_templates import (
    SaveTemplateDialog,
    describe_phase,
    feed_settings_missing,
)
from biofermentation.gui.widgets.log_view import OPERATION_EVENT
from biofermentation.gui.windows import ControlWindow
from biofermentation.organisms import discover_organisms

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


def _window(db, project: int) -> ControlWindow:
    discover_organisms()
    setup = load_phases(db, project)
    state, organism = load_project_state(db, project)
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    return ControlWindow(setup, runner, db)


@pytest.fixture
def pichia(qapp, db, monkeypatch):
    window = _window(db, 519)
    window.answers = {"name": "Pichia standard", "description": "five phases", "author": "Me"}
    window.overwrite = True
    window.asked_overwrite = []
    monkeypatch.setattr(window, "_ask_template_details", lambda phases: window.answers)

    def overwrite(name):
        window.asked_overwrite.append(name)
        return window.overwrite

    monkeypatch.setattr(window, "_confirm_overwrite", overwrite)
    yield window
    window.close()


def _snapshot(db) -> dict[str, list]:
    """Every row of every table but the template tables."""
    with get_connection(db, readonly=True) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
            if row[0] not in TEMPLATE_TABLES
        ]
        return {
            table: [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')]
            for table in tables
        }


# ------------------------------------------------------- the ways in --


def test_the_process_menu_offers_saving(pichia):
    action = pichia.actions_by_name["Save process as template…"]
    menus = [action.text() for action in pichia.menuBar().actions()]
    assert "Process" in menus
    assert action.isEnabled()


def test_the_add_button_is_back_in_the_row_after_the_last_phase(pichia):
    """Where it always was: in the phase row, right of the last panel."""
    grid = pichia.phase_grid
    assert grid.add_button.parent() is grid
    layout = grid.layout()
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    widgets = [widget for widget in widgets if widget is not None]
    assert widgets[-1] is grid.add_button
    assert widgets[-2] is grid.panels[-1]


def test_save_and_load_sit_at_the_bottom_right_below_the_scroll_area(pichia):
    """Always in view, however far the phase row is scrolled."""
    grid = pichia.phase_grid
    bar = grid.template_bar
    assert grid.template_button.parent() is bar
    assert grid.load_template_button.parent() is bar
    page = pichia.process_area.parent()
    column = page.layout()
    assert column.itemAt(0).widget() is pichia.process_area
    assert column.itemAt(1).widget() is bar
    row = bar.layout()
    assert row.itemAt(0).spacerItem() is not None  # pushed to the right
    assert row.itemAt(1).widget() is grid.template_button
    assert row.itemAt(2).widget() is grid.load_template_button
    # Bar and buttons are not inside the scrolled widget.
    assert not grid.isAncestorOf(bar)


def test_the_page_keeps_the_look_of_a_scrolled_tab(pichia):
    from PySide6.QtGui import QPalette

    area = pichia.process_area
    assert area.frameShape() == area.Shape.NoFrame
    assert area.viewport().backgroundRole() == QPalette.ColorRole.Base
    assert area.widget().objectName() == "tabPage"


def test_saving_needs_phases(qapp, db, pichia):
    assert pichia.phase_grid.template_button.isEnabled()
    empty = _window(db, 716)
    assert empty.setup.phases == []
    assert not empty.phase_grid.template_button.isEnabled()
    assert "no phases" in empty.phase_grid.template_button.toolTip()
    empty.close()


def test_the_button_stays_usable_while_the_process_runs(pichia):
    """Saving a plan changes nothing in the run, unlike adding a phase."""
    pichia.phase_grid.set_editable(False)
    assert not pichia.phase_grid.add_button.isEnabled()
    assert pichia.phase_grid.template_button.isEnabled()


def test_the_button_saves(pichia):
    pichia.phase_grid.template_button.click()
    assert [
        row["name"] for row in list_process_templates(pichia.db_path, pichia.setup.info.modelID)
    ] == ["Pichia standard"]


# ---------------------------------------------------------- saving --


def test_saving_writes_the_template_with_its_details(pichia):
    template_id = pichia.save_process_template()
    template = load_process_template(pichia.db_path, template_id)
    assert (template.name, template.description, template.author) == (
        "Pichia standard",
        "five phases",
        "Me",
    )
    assert [phase.name for phase in template.phases] == [
        phase.name for phase in pichia.setup.phases
    ]


def test_saving_a_template_writes_only_the_template_tables(pichia):
    before = _snapshot(pichia.db_path)
    pichia.save_process_template()
    assert _snapshot(pichia.db_path) == before


def test_saving_does_not_save_the_project_or_touch_its_phases(pichia):
    phases = pichia.setup.phases
    states = [(phase.processID, phase.statusID, phase.start.time) for phase in phases]
    running = pichia.runner.running
    pichia.save_process_template()
    assert [(phase.processID, phase.statusID, phase.start.time) for phase in phases] == states
    assert pichia.runner.running == running
    # The window still has unsaved work: the template was no project save.
    assert not any("Project saved" in line for line in pichia.log_lines)


def test_saving_is_logged_as_an_operation(pichia):
    pichia.save_process_template()
    entry = pichia.log_view.entries[-1]
    assert entry.event_type == OPERATION_EVENT
    assert "Pichia standard" in entry.message and "5 phases" in entry.message


def test_cancelling_the_dialog_stores_nothing(pichia, monkeypatch):
    monkeypatch.setattr(pichia, "_ask_template_details", lambda phases: None)
    assert pichia.save_process_template() is None
    assert list_process_templates(pichia.db_path, pichia.setup.info.modelID) == []


def test_an_existing_name_asks_and_replaces_only_with_yes(pichia):
    first = pichia.save_process_template()
    pichia.overwrite = False
    assert pichia.save_process_template() is None
    assert pichia.asked_overwrite == ["Pichia standard"]
    [row] = list_process_templates(pichia.db_path, pichia.setup.info.modelID)
    assert row["templateID"] == first

    pichia.overwrite = True
    pichia.answers = {**pichia.answers, "description": "second version"}
    second = pichia.save_process_template()
    [row] = list_process_templates(pichia.db_path, pichia.setup.info.modelID)
    assert row["templateID"] == second != first
    assert row["description"] == "second version"
    assert "replaced" in pichia.log_view.entries[-1].message


def test_an_unknown_parameter_is_said_not_swallowed(pichia, monkeypatch):
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: told.append(args[2]))
    pichia.setup.phases[3].parameters["noSuchThing"] = 1.0
    assert pichia.save_process_template() is None
    assert told and "noSuchThing" in told[0]
    assert list_process_templates(pichia.db_path, pichia.setup.info.modelID) == []


def test_the_template_is_a_snapshot_of_the_moment(pichia):
    template_id = pichia.save_process_template()
    pichia.setup.phases[0].name = "renamed afterwards"
    template = load_process_template(pichia.db_path, template_id)
    assert template.phases[0].name == "Batch Phase"


# ---------------------------------------------------------- the dialog --


def _types(window) -> dict[int, str]:
    return {row["process_typeID"]: row["type"] for row in window.setup.lookups.process_type}


def test_an_empty_name_cannot_be_saved(pichia):
    dialog = SaveTemplateDialog(pichia.setup.phases, _types(pichia), author="Me")
    assert not dialog.save_button.isEnabled()
    dialog.name_edit.setText("   ")
    assert not dialog.save_button.isEnabled()
    dialog.name_edit.setText("  Standard ")
    assert dialog.save_button.isEnabled()
    assert dialog.values() == {"name": "Standard", "description": "", "author": "Me"}


def test_the_dialog_lists_every_phase(pichia):
    dialog = SaveTemplateDialog(pichia.setup.phases, _types(pichia), model_name="Pichia")
    lines = [dialog.phase_list.item(i).text() for i in range(dialog.phase_list.count())]
    assert len(lines) == 5
    assert lines[0].startswith("1. Batch Phase — Manual")
    from PySide6.QtWidgets import QLabel

    assert any("'Pichia'" in label.text() for label in dialog.findChildren(QLabel))


def test_a_feed_without_its_own_settings_says_where_they_come_from(pichia):
    """P0-2: the fed batch of 519 carries only results; the pulse on R2 carries kR2."""
    phases = pichia.setup.phases
    types = _types(pichia)
    fed_batch, pulse, update, pulse_two = phases[1], phases[2], phases[3], phases[4]
    assert feed_settings_missing(fed_batch)
    assert "feed settings from the project" in describe_phase(2, fed_batch, types)
    assert "t1j" not in describe_phase(2, fed_batch, types)  # results are not shown as kept
    assert not feed_settings_missing(pulse)
    assert "(kR2)" in describe_phase(3, pulse, types)
    assert not feed_settings_missing(update)  # not a feed at all
    assert feed_settings_missing(pulse_two)  # reservoir 1, nothing of its own


# =================================================== phase 4: loading ==


@pytest.fixture
def loading(pichia, monkeypatch):
    """Project 519 with one stored template, the three questions answered."""
    from biofermentation.db import save_process_template
    from biofermentation.db.models import Condition, Phase

    phases = [
        Phase(
            processID=0,
            projectID=0,
            statusID=None,
            typeID=1,
            name=f"Template {n}",
            reservoirID=1,
            start=Condition(typeID=2),
            end=Condition(typeID=7, value=0.5),
        )
        for n in (1, 2)
    ]
    pichia.template_id = save_process_template(
        pichia.db_path, pichia.setup.info.modelID, "Two steps", "two manual phases", phases
    )
    pichia.placement = "append"
    pichia.replace_confirmed = True
    pichia.placement_asked = []
    monkeypatch.setattr(pichia, "_choose_template", lambda: pichia.template_id)

    def placement(template, going, moving):
        pichia.placement_asked.append(([phase.name for phase in going], moving))
        return pichia.placement

    monkeypatch.setattr(pichia, "_ask_placement", placement)
    monkeypatch.setattr(pichia, "_confirm_replace", lambda going: pichia.replace_confirmed)
    return pichia


def _names(window) -> list[str]:
    return [phase.name for phase in window.setup.phases]


ORIGINAL = ["Batch Phase", "Fed Batch", "Pulse Feed", "Closed-Loop Feed", "Pulse Feed 2"]


def test_the_process_menu_offers_loading(pichia):
    assert "Load process template…" in pichia.actions_by_name


def test_loading_appends_behind_a_running_process(loading):
    """519 is saved with its Fed Batch active."""
    active = loading.runner.phases.current
    assert loading.load_process_template() == loading.template_id
    assert _names(loading) == [*ORIGINAL, "Template 1", "Template 2"]
    assert loading.runner.phases.current == active
    new = loading.setup.phases[-2:]
    assert [phase.statusID for phase in new] == [1, 1]
    assert len({phase.processID for phase in loading.setup.phases}) == 7


def test_replacing_never_touches_a_started_phase(loading):
    started = [
        (p.processID, p.statusID, p.start.time, p.end.time) for p in loading.setup.phases[:2]
    ]
    objects = loading.setup.phases[:2]
    loading.placement = "replace"
    loading.load_process_template()
    assert _names(loading) == ["Batch Phase", "Fed Batch", "Template 1", "Template 2"]
    assert loading.setup.phases[:2] == objects
    assert [
        (p.processID, p.statusID, p.start.time, p.end.time) for p in loading.setup.phases[:2]
    ] == started
    assert loading.placement_asked[0][0] == ["Pulse Feed", "Closed-Loop Feed", "Pulse Feed 2"]


def test_the_automaton_sees_the_new_phases(loading):
    loading.placement = "replace"
    loading.load_process_template()
    automaton = loading.runner.phases
    assert automaton.phases is loading.setup.phases
    assert automaton.current == 1
    assert automaton.phases[automaton.current].name == "Fed Batch"


def test_cancelling_the_placement_or_the_second_question_changes_nothing(loading):
    loading.placement = None
    assert loading.load_process_template() is None
    assert _names(loading) == ORIGINAL
    loading.placement = "replace"
    loading.replace_confirmed = False
    assert loading.load_process_template() is None
    assert _names(loading) == ORIGINAL


def test_without_phases_to_replace_there_is_no_question(qapp, db, monkeypatch):
    """Project 716 has no phases: the template simply becomes the process."""
    from biofermentation.db import save_process_template
    from biofermentation.db.models import Condition, Phase

    window = _window(db, 716)
    template_id = save_process_template(
        db,
        window.setup.info.modelID,
        "One",
        None,
        [Phase(0, 0, None, 1, "Only", 1, Condition(typeID=2), Condition(typeID=7, value=1.0))],
    )
    monkeypatch.setattr(window, "_choose_template", lambda: template_id)
    monkeypatch.setattr(
        window, "_ask_placement", lambda *args: pytest.fail("nothing to replace, nothing to ask")
    )
    assert window.load_process_template() == template_id
    assert [phase.name for phase in window.setup.phases] == ["Only"]
    window.close()


def test_loading_while_running_is_refused(loading, monkeypatch):
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    loading.runner.start()
    try:
        assert loading.load_process_template() is None
    finally:
        loading.runner.pause()
    assert _names(loading) == ORIGINAL
    assert told and "Pause" in told[0]
    loading.phase_grid.set_editable(False)
    assert not loading.phase_grid.load_template_button.isEnabled()
    assert "Pause" in loading.phase_grid.load_template_button.toolTip()


def test_a_model_without_templates_says_how_to_make_one(pichia, monkeypatch):
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    assert pichia.load_process_template() is None
    assert told and "Save process as template" in told[0]


def test_a_template_that_does_not_fit_is_refused_with_its_reasons(qapp, db, monkeypatch):
    """519's process stored for the E. coli model: reservoir 2, Pichia setpoints."""
    from biofermentation.db import save_process_template

    window = _window(db, 716)
    pichia_phases = load_phases(db, 519).phases
    template_id = save_process_template(
        db, window.setup.info.modelID, "Wrong organism", None, pichia_phases
    )
    monkeypatch.setattr(window, "_choose_template", lambda: template_id)
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: told.append(args[2]))
    assert window.load_process_template() is None
    assert window.setup.phases == []
    assert told and "does not fit" in told[0]
    assert "reservoir 2" in told[0]
    window.close()


def test_the_next_phase_warning_reaches_the_question(loading):
    """P0-4: an active phase that ends when the next one may start."""
    from biofermentation.control import EndCondition

    fed_batch = loading.setup.phases[1]
    fed_batch.end.typeID = EndCondition.NEXT_PHASE_STARTS
    loading.placement = None
    loading.load_process_template()
    assert loading.placement_asked[0][1] is fed_batch


def test_a_loaded_template_is_logged(loading):
    loading.load_process_template()
    entry = loading.log_view.entries[-1]
    assert entry.event_type == OPERATION_EVENT
    assert "'Two steps' loaded: 2 phases, appended" in entry.message
    loading.placement = "replace"
    loading.load_process_template()
    assert "replacing 5 phase(s)" in loading.log_view.entries[-1].message


def test_a_loaded_process_is_saved_with_the_project(loading):
    loading.load_process_template()
    loading.save(announce=False)
    stored = load_phases(loading.db_path, 519).phases
    assert [phase.name for phase in stored] == [*ORIGINAL, "Template 1", "Template 2"]
    assert [phase.statusID for phase in stored[-2:]] == [1, 1]
    assert [phase.end.value for phase in stored[-2:]] == [0.5, 0.5]


# ------------------------------------------------------- the dialog --


def test_the_dialog_lists_only_templates_of_this_model(loading):
    from biofermentation.db import save_process_template
    from biofermentation.gui.dialogs.process_templates import LoadTemplateDialog

    other_model = load_phases(loading.db_path, 716).info.modelID
    assert other_model != loading.setup.info.modelID
    save_process_template(
        loading.db_path, other_model, "E. coli only", None, loading.setup.phases[:1]
    )
    dialog = LoadTemplateDialog(loading.db_path, loading.setup.info.modelID, _types(loading))
    names = [dialog.list.item(i).text() for i in range(dialog.list.count())]
    assert names == ["Two steps"]


def test_the_dialog_previews_the_selected_template(loading):
    from biofermentation.gui.dialogs.process_templates import LoadTemplateDialog

    dialog = LoadTemplateDialog(loading.db_path, loading.setup.info.modelID, _types(loading))
    assert dialog.selected_template_id() == loading.template_id
    assert dialog.description_label.text() == "two manual phases"
    assert dialog.meta_label.text().startswith("2 phases")
    preview = [dialog.preview.item(i).text() for i in range(dialog.preview.count())]
    assert preview == ["1. Template 1 — Manual", "2. Template 2 — Manual"]


def test_renaming_and_deleting_in_the_dialog(loading, monkeypatch):
    from biofermentation.db import list_process_templates, save_process_template
    from biofermentation.gui.dialogs.process_templates import LoadTemplateDialog

    save_process_template(
        loading.db_path, loading.setup.info.modelID, "Other", None, loading.setup.phases[:1]
    )
    dialog = LoadTemplateDialog(loading.db_path, loading.setup.info.modelID, _types(loading))
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: told.append(args[2]))
    assert not dialog.rename(loading.template_id, "Other")  # taken
    assert told
    assert dialog.rename(loading.template_id, "Renamed")
    assert dialog.list.currentItem().text() == "Renamed"
    assert dialog.delete_selected(confirmed=True)
    names = [
        row["name"] for row in list_process_templates(loading.db_path, loading.setup.info.modelID)
    ]
    assert names == ["Other"]


def test_an_empty_list_offers_nothing_to_press(pichia):
    from biofermentation.gui.dialogs.process_templates import LoadTemplateDialog

    dialog = LoadTemplateDialog(pichia.db_path, pichia.setup.info.modelID, _types(pichia))
    assert dialog.list.count() == 0
    assert not dialog.load_button.isEnabled()
    assert not dialog.delete_button.isEnabled()
    assert "no process templates" in dialog.description_label.text()


# ------------------------------------------------------- the switch --


def test_the_switch_is_on_by_default_and_survives_the_file(tmp_path):
    from biofermentation.gui.settings import Settings, load_settings, save_settings

    assert Settings().process_templates is True
    path = tmp_path / "settings.yaml"
    save_settings(Settings(process_templates=False), path)
    settings, problem = load_settings(path)
    assert problem == "" and settings.process_templates is False
    assert "process_templates" in path.read_text(encoding="utf-8")


def test_the_settings_dialog_carries_the_switch(qapp, tmp_path):
    from biofermentation.gui.dialogs.settings import SettingsDialog

    dialog = SettingsDialog(path=tmp_path / "settings.yaml")
    assert dialog.templates_box.isChecked()
    dialog.templates_box.setChecked(False)
    assert dialog.settings().process_templates is False


def test_switched_off_there_is_no_way_to_templates(qapp, db, monkeypatch):
    from biofermentation.gui.settings import Settings
    from biofermentation.gui.windows import control_app

    monkeypatch.setattr(
        control_app, "load_settings", lambda: (Settings(process_templates=False), "")
    )
    window = _window(db, 519)
    menus = [action.text() for action in window.menuBar().actions()]
    assert "Process" not in menus
    assert "Save process as template…" not in window.actions_by_name
    assert "Load process template…" not in window.actions_by_name
    assert window.phase_grid.template_bar.isHidden()
    # The rest of the Process Manager is as it was.
    assert not window.phase_grid.add_button.isHidden()
    window.close()
