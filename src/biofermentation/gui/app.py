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
from ..db import ensure_columns, load_phases
from ..organisms import discover_organisms
from ..resources import app_icon_path, default_database
from .style import apply_theme
from .windows import (
    ControlWindow,
    CreateProjectWindow,
    SelectProjectWindow,
    StartingScreen,
)


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

        # The model configurator is not ported. A button that emits into
        # nothing is worse than one that says so.
        self.starting_screen.model_configurator_button.setEnabled(False)
        self.starting_screen.model_configurator_button.setToolTip(
            "Not ported yet — models are edited in the database or through "
            "an organism definition.yaml"
        )

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
        if name == "Bioreactors…":
            self.manage_bioreactors()
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
        self.runner = SimulationRunner(
            organism,
            state,
            phases=automaton,
            speedfactor=int(state.p.get("speedfactor", 1) or 1),
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
