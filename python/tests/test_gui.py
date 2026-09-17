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
PICHIA_PROJECT = 519


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
    assert len(written) == 8
    for path in written:
        assert path.is_file() and path.stat().st_size > 2000


def test_every_way_into_a_project_releases_the_one_that_is_open():
    """Point 4: two control windows at once cost the first one its data.

    Closing the second and then the starting screen took the first down with
    it — unsaved and unasked. Every entry point has to let go of the current
    project first, and that is a decision the operator makes in the closing
    dialog.
    """
    import inspect

    from biofermentation.gui import app as app_module

    for name in ("show_create_project", "show_select_project", "open_project"):
        source = inspect.getsource(getattr(app_module.SimulationApp, name))
        assert "release_current_project()" in source, name
        assert "return" in source.split("release_current_project()")[1][:40], (
            f"{name} does not stop when the operator cancels"
        )


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


# ----------------------------------------------- theme and readability --


def test_the_application_brings_its_own_palette(qapp, monkeypatch):
    """A style sheet only sets what it names.

    Everything it leaves out comes from the platform palette, and on a Mac in
    dark mode that meant white text on the light grounds the sheet sets. Half
    the application was unreadable.
    """
    from PySide6.QtGui import QColor, QPalette

    from biofermentation.gui.style import apply_theme

    dark = QPalette()
    dark.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
    dark.setColor(QPalette.ColorRole.Window, QColor("#2b2b2b"))
    dark.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
    qapp.setPalette(dark)

    apply_theme(qapp)
    palette = qapp.palette()
    assert palette.windowText().color().name() == "#1a1a1a"
    assert palette.window().color().name() == "#f2f2f2"
    assert palette.text().color().name() == "#1a1a1a"
    assert palette.base().color().name() == "#ffffff"


def test_the_stylesheet_never_sets_a_background_without_a_colour(qapp):
    """The rule that keeps a dark platform theme out.

    A block that paints a light ground and says nothing about the text hands
    the text colour back to the platform.
    """
    import re

    from biofermentation.gui.style import BUNDLED_STYLE

    sheet = BUNDLED_STYLE.read_text(encoding="utf-8")
    # Strip comments, then look at each block on its own.
    sheet = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)

    offenders = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", sheet):
        selector, body = match.group(1).strip(), match.group(2)
        # Only plain widget rules. A ":hover" or "::handle" block refines one
        # that has already set a colour, and a sub-control draws no text.
        if ":" in selector:
            continue
        sets_background = re.search(r"(^|\s)background\s*:", body)
        sets_color = re.search(r"(^|\s)color\s*:", body)
        if sets_background and not sets_color and "transparent" not in body:
            offenders.append(selector)
    assert offenders == [], f"background without a colour: {offenders}"


@pytest.fixture
def control_window(db_copy, qapp):
    from biofermentation.control import PhaseAutomaton
    from biofermentation.core.runner import DEFAULT_DT, load_project_state
    from biofermentation.gui.windows.control_app import ControlWindow

    discover_organisms()
    setup = load_phases(db_copy, PICHIA_PROJECT)
    state, organism = load_project_state(db_copy, PICHIA_PROJECT, dt=DEFAULT_DT)
    runner = SimulationRunner(
        organism, state, phases=PhaseAutomaton.from_setup(setup), interval_ms=1
    )
    window = ControlWindow(setup, runner, db_copy)
    yield window
    window.close()


def test_every_tab_page_of_the_control_window_is_white(control_window):
    """Point 1 of the second round: the Process Manager stayed grey.

    Its page is a QScrollArea, and the viewport paints its own palette over
    whatever the page was given.
    """
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QScrollArea

    tabs = control_window.tabs
    for index in range(tabs.count()):
        page = tabs.widget(index)
        assert page.objectName() == "tabPage", f"tab {index} was not styled"
        if isinstance(page, QScrollArea):
            viewport = page.viewport()
            assert viewport.backgroundRole() == QPalette.ColorRole.Base
            assert viewport.palette().base().color().name() == "#ffffff"


def test_a_checkbox_draws_a_visible_box(qapp):
    """Styling QCheckBox at all took the box away — the tick was still drawn
    but an unticked entry showed nothing, so a list of them looked empty."""
    import re

    from biofermentation.gui.style import BUNDLED_STYLE

    sheet = BUNDLED_STYLE.read_text(encoding="utf-8")
    indicator = re.search(r"QCheckBox::indicator[^{]*\{([^}]*)\}", sheet, re.S)
    assert indicator, "no rule for the checkbox indicator"
    body = indicator.group(1)
    assert "border:" in body
    assert "background:" in body
    assert re.search(r"QCheckBox::indicator:checked[^{]*\{[^}]*background:", sheet, re.S)


# ------------------------------------------------------- the settings file --


def test_no_settings_file_shows_everything(tmp_path):
    """Settings that hide things must not be able to fail towards hiding."""
    from biofermentation.gui.settings import HIDEABLE_TABS, load_settings

    settings, problem = load_settings(tmp_path / "settings.yaml")
    assert problem == ""
    assert settings.student_view is False
    assert all(settings.shows(name) for name in HIDEABLE_TABS)


def test_the_settings_round_trip(tmp_path):
    from biofermentation.gui.settings import Settings, load_settings, save_settings

    path = tmp_path / "settings.yaml"
    save_settings(Settings(hidden_tabs={"Log", "Process Manager"}, student_view=True), path)

    settings, problem = load_settings(path)
    assert problem == ""
    assert settings.hidden_tabs == {"Log", "Process Manager"}
    assert settings.student_view is True
    assert settings.shows("Controllers") is True
    assert settings.shows("Log") is False


def test_a_broken_settings_file_shows_everything_and_says_why(tmp_path):
    from biofermentation.gui.settings import load_settings

    path = tmp_path / "settings.yaml"
    path.write_text("hidden_tabs: [Nonsense]\n", encoding="utf-8")
    settings, problem = load_settings(path)
    assert settings.hidden_tabs == set()
    assert "unknown tab" in problem

    path.write_text("just a string\n", encoding="utf-8")
    settings, problem = load_settings(path)
    assert settings.hidden_tabs == set()
    assert "mapping" in problem


def test_the_refresh_follows_delta_t_unless_it_is_uncoupled():
    """Der Takt bestimmt zweierlei: wie oft man hinsieht und wie schnell es geht.

    Gekoppelt ist ein Tick ein Rechenschritt, ein Speedfactor von 1 also
    Echtzeit. Entkoppelt gilt der eingetragene Wert — und das Verhältnis
    Δt/Refresh ist dann genau der Faktor, um den der Lauf schneller ist als
    der echte Prozess.
    """
    from biofermentation.gui.settings import Settings

    coupled = Settings()
    assert coupled.interval_ms(2.0) == 2000
    assert coupled.interval_ms(10.0) == 10000, "gekoppelt folgt der Takt Δt"

    free = Settings(couple_refresh_to_dt=False, refresh_seconds=2.0)
    assert free.interval_ms(2.0) == 2000
    assert free.interval_ms(10.0) == 2000, "entkoppelt bleibt der Takt stehen"


def test_an_impossible_refresh_is_refused_rather_than_used(tmp_path):
    """Eine Datei, die einen 0-Sekunden-Takt verlangt, darf ihn nicht bekommen.

    Ein Timer mit Intervall 0 feuert, so schnell die Ereignisschleife kann —
    das Fenster wäre nicht mehr zu bedienen.
    """
    from biofermentation.gui.settings import load_settings

    path = tmp_path / "settings.yaml"
    path.write_text("couple_refresh_to_dt: false\nrefresh_seconds: 0\n", encoding="utf-8")
    settings, problem = load_settings(path)
    assert "refresh_seconds" in problem
    assert settings.couple_refresh_to_dt is True, "die Vorgabe, nicht die kaputte Datei"


def test_the_refresh_survives_a_round_trip(tmp_path):
    from biofermentation.gui.settings import Settings, load_settings, save_settings

    path = tmp_path / "settings.yaml"
    save_settings(Settings(couple_refresh_to_dt=False, refresh_seconds=0.5), path)
    back, problem = load_settings(path)
    assert problem == ""
    assert back.couple_refresh_to_dt is False
    assert back.refresh_seconds == 0.5


def test_the_stored_resolution_survives_a_round_trip(tmp_path):
    from biofermentation.gui.settings import Settings, load_settings, save_settings

    path = tmp_path / "settings.yaml"
    save_settings(Settings(storage_interval=5), path)
    back, problem = load_settings(path)
    assert problem == ""
    assert back.storage_interval == 5
    assert back.storage_seconds(2.0) == 10.0, "fünf Schritte zu 2 s"


def test_a_stored_resolution_of_zero_is_refused(tmp_path):
    """Jeder nullte Schritt ist kein Schritt — und wäre eine leere Zeitreihe."""
    from biofermentation.gui.settings import load_settings

    path = tmp_path / "settings.yaml"
    path.write_text("storage_interval: 0\n", encoding="utf-8")
    settings, problem = load_settings(path)
    assert "storage_interval" in problem
    assert settings.storage_interval == 1, "die Vorgabe, nicht die kaputte Datei"


def test_control_options_and_information_cannot_be_switched_off():
    """A window without them is not a control window."""
    from biofermentation.gui.settings import HIDEABLE_TABS

    assert "Control Options" not in HIDEABLE_TABS
    assert "Information" not in HIDEABLE_TABS


def test_the_dialog_writes_what_its_boxes_say(tmp_path, qapp):
    from biofermentation.gui.dialogs.settings import SettingsDialog
    from biofermentation.gui.settings import load_settings

    path = tmp_path / "settings.yaml"
    dialog = SettingsDialog(path=path)
    dialog.boxes["Log"].setChecked(False)
    dialog.student_box.setChecked(True)
    dialog.storage_box.setValue(5)
    dialog.accept()

    settings, problem = load_settings(path)
    assert problem == ""
    assert settings.hidden_tabs == {"Log"}
    assert settings.student_view is True
    assert settings.storage_interval == 5


def test_the_starting_screen_offers_settings_where_the_configurator_was(qapp):
    """That button was never ported and sat there disabled."""
    screen = StartingScreen()
    assert hasattr(screen, "settings_button")
    assert not hasattr(screen, "model_configurator_button")
    assert screen.settings_button.isEnabled()
