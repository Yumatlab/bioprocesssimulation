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

from ..core.runner import DEFAULT_DT, load_project_state
from ..core.simulation_runner import SimulationRunner
from ..organisms import discover_organisms
from ..resources import default_database
from .windows import CreateProjectWindow, SelectProjectWindow, StartingScreen


class SimulationApp(QApplication):
    """Owns the windows and the running simulation."""

    def __init__(self, argv: list[str] | None = None, *, db_path: Path | str | None = None):
        super().__init__(argv if argv is not None else sys.argv)
        self.setApplicationName("Biofermentation Simulation")

        # The plugin registry is filled once, at start, before any window can
        # ask what organisms exist.
        discover_organisms()

        self.db_path = Path(db_path) if db_path else default_database()
        self.starting_screen = StartingScreen()
        self.select_window: SelectProjectWindow | None = None
        self.create_window: CreateProjectWindow | None = None
        self.runner: SimulationRunner | None = None

        self.starting_screen.load_project_requested.connect(self.show_select_project)
        self.starting_screen.new_project_requested.connect(self.show_create_project)
        self.starting_screen.quick_start_requested.connect(self.show_create_project)
        self.starting_screen.exit_requested.connect(self.quit)

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

    def open_project(self, project_id: int) -> SimulationRunner | None:
        """Load a project and put a runner behind it.

        Phase 5 replaces this with the control window; until then the runner
        exists and can be started, which is what the phase 4 milestone asks
        for — "a startable prototype, without plot and without phase manager".
        """
        try:
            state, organism = load_project_state(self.db_path, project_id, dt=DEFAULT_DT)
        except LookupError as error:
            QMessageBox.warning(None, "Open Project", str(error))
            return None

        self.runner = SimulationRunner(
            organism, state, speedfactor=int(state.p.get("speedfactor", 1) or 1)
        )
        self.runner.failed.connect(lambda message: QMessageBox.warning(None, "Simulation", message))
        return self.runner


def main(argv: list[str] | None = None) -> int:
    app = SimulationApp(argv)
    app.show_starting_screen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
