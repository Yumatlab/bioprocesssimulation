"""Render the windows to PNG without a display (plan section 4).

Useful for a look at the layout while the application has no run loop yet,
and for the handbook of phase 8. Runs offscreen, so it works over SSH and in
CI.

    python -m biofermentation.gui.screenshots --out shots/
"""

import argparse
import os
import shutil
from pathlib import Path

# Has to be set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ..organisms import discover_organisms
from ..resources import TEMPLATE_DB
from .windows import CreateProjectWindow, SelectProjectWindow, StartingScreen


def render(out_dir: Path, db_path: Path | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if db_path is None:
        db_path = out_dir / "screenshot.db"
        shutil.copy(TEMPLATE_DB, db_path)

    app = QApplication.instance() or QApplication([])
    discover_organisms()
    written = []

    def shoot(widget, name: str, size: tuple[int, int]) -> None:
        widget.resize(*size)
        widget.show()
        app.processEvents()
        path = out_dir / name
        widget.grab().save(str(path))
        written.append(path)

    shoot(StartingScreen(), "01_starting_screen.png", (430, 560))

    select = SelectProjectWindow(db_path)
    select.table.resizeColumnsToContents()
    if select.model.rowCount():
        select.table.selectRow(0)
    shoot(select, "02_load_project.png", (1000, 460))

    create = CreateProjectWindow(db_path)
    create.title_edit.setText("MyProject")
    if create.model.rowCount():
        create.table.selectRow(0)
    shoot(create, "03_create_project.png", (600, 620))

    control = _control_window(db_path)
    if control is not None:
        shoot(control, "04_control_app.png", (1290, 690))
        control.tabs.setCurrentWidget(control.controller_view)
        control.refresh()
        shoot(control, "05_controllers.png", (1290, 690))
        control.tabs.setCurrentWidget(control.variable_pool)
        control.refresh()
        shoot(control, "06_variable_pool.png", (1290, 690))
        control.tabs.setCurrentIndex(control.tabs.indexOf(control.variable_pool) + 1)
        shoot(control, "07_process_manager.png", (1290, 690))

        figure = control.open_plot()
        figure.resize(1500, 815)
        figure.show()
        app.processEvents()
        figure.refresh()
        shoot(figure, "07_figure_app.png", (1500, 815))

    return written


def _control_window(db_path: Path):
    """The Control App on the first project that can be opened."""
    from ..control import PhaseAutomaton
    from ..core.runner import load_project_state
    from ..core.simulation_runner import SimulationRunner
    from ..db import list_projects, load_phases
    from .windows import ControlWindow

    usable = [p for p in list_projects(db_path) if p["parameters"] >= p["expected"] > 0]
    if not usable:
        return None
    project_id = usable[0]["projectID"]

    setup = load_phases(db_path, project_id)
    state, organism = load_project_state(db_path, project_id)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    # The step width the project is configured with, not the default — an
    # 18 hour run makes a poor picture of a 5 hour template.
    seconds = float(state.p.get("deltatsec", 0) or 0)
    if seconds > 0:
        state.dt = seconds / 3600
    runner = SimulationRunner(
        organism, state, phases=PhaseAutomaton.from_setup(setup), speedfactor=30
    )
    for _ in range(120):
        runner._on_tick()
    window = ControlWindow(setup, runner, db_path)
    window.refresh()
    return window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("screenshots"))
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    for path in render(args.out, args.db):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
