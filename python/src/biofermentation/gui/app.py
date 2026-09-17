"""The application object and the navigation between windows (plan 4.1).

The windows themselves know nothing about each other — each emits what the
user asked for and this class decides what opens. That is what lets every
window be tested on its own.

Phase 4 ends here: a project can be created, loaded and simulated in the
background. The control surface and the plot are phases 5 and 6, so opening a
project currently starts a headless run and reports its progress.
"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from ..control import PhaseAutomaton
from ..core.runner import DEFAULT_DT, load_project_state
from ..core.simulation_runner import SimulationRunner
from ..db import ensure_columns, ensure_indexes, load_phases
from ..db.repair import add_flags
from ..organisms import discover_organisms
from ..resources import app_icon_path, default_database
from .settings import load_settings
from .style import apply_theme
from .windows import (
    ControlWindow,
    CreateProjectWindow,
    SelectProjectWindow,
    StartingScreen,
)


def _ensure_cascade_indexes(db_path) -> list[str]:
    """Add what the template ships with and an older database does not.

    SQLite creates no index for a foreign key, and without one on
    `dataTab.timeID` it scans the whole table for every deleted time row when
    a project is removed. Measured on a real working database with 2 195 640
    data rows, that turns a deletion into minutes instead of 0.58 s.

    Here rather than in the full migration, because these are six additive
    statements and the migration is a rebuild of every table. If nothing is
    missing the call costs one query; if something is, it costs a second or
    two, once.

    A failure here must not stop the application from opening: a database
    without indexes is slow, an application that will not start is useless.
    """
    try:
        return ensure_indexes(db_path)
    except Exception:
        return []


def _ensure_switch_parameters(db_path) -> list[str]:
    """Give an older database the four anti-windup switches.

    The same case as `_ensure_cascade_indexes`: a user's database is a copy of
    the template taken when they first ran the program, and it can be older
    than the code. Here that is not a slow deletion but a control that cannot
    be reached — the controller dialogs offer the switch, `p.get(flag, 0)`
    reads it as off, and nothing says why it is missing.

    Adding it changes no behaviour: every row is written as 0, which is
    exactly what a missing parameter already meant. The switch has to be
    thrown.

    A failure here must not stop the application from opening.
    """
    try:
        return add_flags(db_path, dry_run=False)["added"]
    except Exception:
        return []


class SimulationApp(QApplication):
    """Owns the windows and the running simulation."""

    def __init__(self, argv: list[str] | None = None, *, db_path: Path | str | None = None):
        super().__init__(argv if argv is not None else sys.argv)
        self.setApplicationName("Biofermentation Simulation")
        # Set on the application, so every window and the dock entry inherit it.
        icon = app_icon_path()
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        # Style, palette and stylesheet. The palette is ours, not the
        # system's — see gui/style.py.
        apply_theme(self)

        # The plugin registry is filled once, at start, before any window can
        # ask what organisms exist.
        discover_organisms()

        self.db_path = Path(db_path) if db_path else default_database()
        self._new_indexes = _ensure_cascade_indexes(self.db_path)
        self._new_switches = _ensure_switch_parameters(self.db_path)
        # A user's database is a copy of the template taken when they first
        # ran the program; it can be older than the schema this code expects.
        ensure_columns(self.db_path)
        self.starting_screen = StartingScreen()
        self.select_window: SelectProjectWindow | None = None
        self.create_window: CreateProjectWindow | None = None
        self.control_window: ControlWindow | None = None
        self.runner: SimulationRunner | None = None

        self.starting_screen.load_project_requested.connect(self.show_select_project)
        self.starting_screen.new_project_requested.connect(self.show_create_project)
        self.starting_screen.exit_requested.connect(self.quit)
        self.starting_screen.library_requested.connect(self.library_action)
        self.starting_screen.settings_requested.connect(self.show_settings)

    # ------------------------------------------------------ navigation --

    def show_starting_screen(self) -> None:
        self.starting_screen.show()
        self.starting_screen.raise_()

    def release_current_project(self) -> bool:
        """Close the open project, asking what is to become of it first.

        Only one project at a time. Before this, "Start new project" left the
        control window standing and opened a second one next to it: closing
        that one and then the starting screen took the first one down with it,
        unsaved and unasked.

        Returns False when the operator cancelled — the caller must then do
        nothing at all.
        """
        window = self.control_window
        if window is None:
            return True
        window.close()
        # close() is refused by the window itself when the question was
        # cancelled; _control_closed clears the attribute when it went through.
        return self.control_window is None

    def show_select_project(self) -> None:
        if not self.release_current_project():
            return
        if self.select_window is None:
            self.select_window = SelectProjectWindow(self.db_path)
            self.select_window.project_selected.connect(self.open_project)
            self.select_window.create_requested.connect(self.show_create_project)
            self.select_window.return_requested.connect(self._back_to_start)
            self.select_window.import_requested.connect(self.import_project)
        self.select_window.refresh()
        self.starting_screen.hide()
        self.select_window.show()

    def show_create_project(self) -> None:
        if not self.release_current_project():
            return
        if self.create_window is None:
            self.create_window = CreateProjectWindow(self.db_path)
            self.create_window.project_created.connect(self._project_created)
            self.create_window.return_requested.connect(self._back_from_create)
        self.starting_screen.hide()
        self.create_window.show()

    # ------------------------------------------------------- library --

    def library_action(self, name: str) -> None:
        """One entry of the starting screen's Library menu.

        The windows name what the user asked for; this class decides what
        happens — the same split as everywhere else here.
        """
        from .dialogs.library import (
            export_bioreactor_file,
            export_organism_file,
            import_bioreactor_file,
            import_organism_file,
        )

        window = self.starting_screen
        if name == "Organisms…":
            self.manage_organisms()
        elif name == "Bioreactors…":
            self.manage_bioreactors()
        elif name == "Models…":
            self.manage_models()
        elif name == "Import organism…":
            import_organism_file(window, self.db_path)
        elif name == "Export organism…":
            export_organism_file(window, self.db_path)
        elif name == "Import bioreactor…":
            import_bioreactor_file(window, self.db_path)
        elif name == "Export bioreactor…":
            export_bioreactor_file(window, self.db_path)
        elif name == "Import project…":
            self.import_project()

    def manage_bioreactors(self) -> None:
        """Create and edit vessels without a YAML file and without SQL.

        A bioreactor is a name and sixty values; adding one should not need
        an editor and an import menu.
        """
        from .dialogs.bioreactors import BioreactorManager

        dialog = BioreactorManager(self.db_path, parent=self.starting_screen)
        dialog.exec()

    def manage_models(self) -> None:
        """An organism in a vessel — what a project is actually created from.

        The two dialogs above can make one in passing ("Make selectable…");
        this is the one that can also show, rename, correct and remove one.
        """
        from .dialogs.models import ModelManager

        ModelManager(self.db_path, parent=self.starting_screen).exec()

    def show_settings(self) -> None:
        """What this installation shows. Read again when a project opens."""
        from .dialogs.settings import SettingsDialog

        SettingsDialog(self.starting_screen).exec()

    def manage_organisms(self) -> None:
        """Copy an organism and change its values — the kinetics stay put."""
        from .dialogs.organisms import OrganismManager

        OrganismManager(self.db_path, parent=self.starting_screen).exec()

    def import_project(self) -> int | None:
        """Read an export back in and open what it produced."""
        from .dialogs.library import import_project_folder

        parent = self.select_window or self.starting_screen
        project_id = import_project_folder(parent, self.db_path)
        if project_id is None:
            return None
        if self.select_window is not None:
            self.select_window.refresh()
        return project_id

    def _back_to_start(self) -> None:
        if self.select_window is not None:
            self.select_window.hide()
        self.show_starting_screen()

    def _back_from_create(self) -> None:
        if self.create_window is not None:
            self.create_window.hide()
        if self.select_window is not None and self.select_window.isVisible():
            self.select_window.refresh()
        else:
            self.show_starting_screen()

    def _project_created(self, project_id: int) -> None:
        if self.create_window is not None:
            self.create_window.hide()
        if self.select_window is not None:
            self.select_window.refresh()
        self.open_project(project_id)

    # ------------------------------------------------------ simulation --

    def open_project(self, project_id: int) -> ControlWindow | None:
        """Load a project, wire up its phases and open the control window.

        The three reads of load_phases, load_project_variables and the
        organism plugin happen here and nowhere else — the two-accesses rule
        of plan section 1.2 means the window that follows never touches the
        database until it saves.
        """
        if not self.release_current_project():
            return None

        try:
            setup = load_phases(self.db_path, project_id)
            state, organism = load_project_state(self.db_path, project_id, dt=DEFAULT_DT)
        except LookupError as error:
            QMessageBox.warning(None, "Open Project", str(error))
            return None

        # The step width the project was configured with, not the default.
        seconds = float(state.p.get("deltatsec", 0) or 0)
        if seconds > 0:
            state.dt = seconds / 3600

        automaton = PhaseAutomaton.from_setup(setup)
        # The pace comes from the settings: tied it follows Δt, untied it is
        # whatever was entered there. Without interval_ms the runner would tie
        # itself to Δt and the setting would do nothing.
        settings, _ = load_settings()
        self.runner = SimulationRunner(
            organism,
            state,
            phases=automaton,
            speedfactor=int(state.p.get("speedfactor", 1) or 1),
            interval_ms=settings.interval_ms(seconds),
        )

        self.control_window = ControlWindow(setup, self.runner, self.db_path)
        self.control_window.closed.connect(self._control_closed)
        # The Project menu asks; only this class knows what opens.
        self.control_window.requested_new_project.connect(self.show_create_project)
        self.control_window.requested_open_project.connect(self.show_select_project)
        for window in (self.starting_screen, self.select_window, self.create_window):
            if window is not None:
                window.hide()
        self.control_window.show()
        return self.control_window

    def _control_closed(self) -> None:
        self.control_window = None
        self.runner = None
        if self.select_window is not None:
            self.select_window.refresh()
            self.select_window.show()
        else:
            self.show_starting_screen()


def main(argv: list[str] | None = None) -> int:
    app = SimulationApp(argv)
    app.show_starting_screen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
