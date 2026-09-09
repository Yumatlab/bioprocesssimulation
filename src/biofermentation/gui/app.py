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

from PySide6.QtWidgets import QApplication, QMessageBox

from ..control import PhaseAutomaton
from ..core.runner import DEFAULT_DT, load_project_state
from ..core.simulation_runner import SimulationRunner
from ..db import load_phases
from ..organisms import discover_organisms
from ..resources import default_database
from .style import load_stylesheet
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
        # The whole look is a text file; see gui/style.py.
        self.setStyleSheet(load_stylesheet())

        # The plugin registry is filled once, at start, before any window can
        # ask what organisms exist.
        discover_organisms()

        self.db_path = Path(db_path) if db_path else default_database()
        self.starting_screen = StartingScreen()
        self.select_window: SelectProjectWindow | None = None
        self.create_window: CreateProjectWindow | None = None
        self.control_window: ControlWindow | None = None
        self.runner: SimulationRunner | None = None

        self.starting_screen.load_project_requested.connect(self.show_select_project)
        self.starting_screen.new_project_requested.connect(self.show_create_project)
        self.starting_screen.quick_start_requested.connect(self.show_create_project)
        self.starting_screen.exit_requested.connect(self.quit)

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

    def show_select_project(self) -> None:
        if self.select_window is None:
            self.select_window = SelectProjectWindow(self.db_path)
            self.select_window.project_selected.connect(self.open_project)
            self.select_window.create_requested.connect(self.show_create_project)
            self.select_window.return_requested.connect(self._back_to_start)
        self.select_window.refresh()
        self.starting_screen.hide()
        self.select_window.show()

    def show_create_project(self) -> None:
        if self.create_window is None:
            self.create_window = CreateProjectWindow(self.db_path)
            self.create_window.project_created.connect(self._project_created)
            self.create_window.return_requested.connect(self._back_from_create)
        self.starting_screen.hide()
        self.create_window.show()

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
