"""Render the windows to PNG without a display (plan section 4).

Useful for a look at the layout while the application has no run loop yet,
and for the handbook of phase 8. Runs offscreen, so it works over SSH and in
CI.

    python -m biofermentation.gui.screenshots --out shots/
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Has to be set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform looks for fonts in QT_QPA_FONTDIR, and the PySide6
# wheels for Windows ship no font folder. Without one Qt draws every glyph as
# a box as wide as the font is high — a reading of 14 characters came out
# 172 px wide on the Windows runner against 81 px with a real font, and the
# flow-sheet layout tests failed on boxes, not on the layout. The system's
# fonts are what a real Windows desktop draws with.
if sys.platform == "win32":
    os.environ.setdefault(
        "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    )

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

    shoot(_pcs_elements(), "08_pcs_elements.png", (980, 260))

    control = _control_window(db_path)
    if control is not None:
        shoot(control, "04_control_app.png", (1290, 690))
        control.tabs.setCurrentWidget(control.controller_view)
        control.refresh()
        shoot(control, "05_controllers.png", (1290, 690))
        control.tabs.setCurrentWidget(control.variable_pool)
        control.refresh()
        shoot(control, "06_variable_pool.png", (1290, 690))
        control.tabs.setCurrentWidget(control.pcs_view)
        control.load_panels()
        control.refresh()
        shoot(control, "09_pcs_tab.png", (1290, 690))
        control.tabs.setCurrentIndex(control.tabs.indexOf(control.variable_pool) + 1)
        shoot(control, "07_process_manager.png", (1290, 690))

        figure = control.open_plot()
        figure.resize(1500, 815)
        figure.show()
        app.processEvents()
        figure.refresh()
        shoot(figure, "07_figure_app.png", (1500, 815))

    shoot(_process_templates(), "10_process_templates.png", (720, 420))

    return written


def _process_templates():
    """The load dialog with two templates of the Pichia model.

    Built on a copy of the shipped template in a directory of its own: the
    dialog needs stored templates, and render() may have been given somebody's
    real database, which a screenshot must not write to.
    """
    import tempfile

    from ..db import load_phases, save_process_template
    from .dialogs.process_templates import LoadTemplateDialog

    folder = Path(tempfile.mkdtemp(prefix="biofermentation-shot-"))
    db_path = folder / "templates.db"
    shutil.copy(TEMPLATE_DB, db_path)
    setup = load_phases(db_path, 519)
    model = setup.info.modelID
    save_process_template(
        db_path,
        model,
        "Pichia standard",
        "Glycerol batch, fed-batch on reservoir 1, methanol pulses on reservoir 2 "
        "and a closed-loop methanol phase.",
        setup.phases,
        author="Lab course",
    )
    save_process_template(
        db_path, model, "Short test", "Batch and one pulse.", [setup.phases[0], setup.phases[2]]
    )
    types = {row["process_typeID"]: row["type"] for row in setup.lookups.process_type}
    return LoadTemplateDialog(db_path, model, types, model_name=setup.info.model_name or "")


def _pcs_elements():
    """Every building block of the PCS tab, in the states that matter."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QWidget

    from .pcs_specs import SYMBOLS
    from .widgets.pcs_elements import (
        TankGauge,
        ValveButton,
        VesselWidget,
        draw_pipe,
    )

    class PipeDemo(QWidget):
        """A live and an idle pipe of the same medium, one above the other."""

        def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
            from PySide6.QtGui import QPainter

            painter = QPainter(self)
            width = self.width()
            draw_pipe(painter, [(10, 40), (width - 40, 40), (width - 40, 90)], "feed", True)
            draw_pipe(painter, [(10, 140), (width - 10, 140)], "feed", False)

    sheet = QWidget()
    row = QHBoxLayout(sheet)

    # One row per symbol: stopped, running, locked by a controller, in alarm.
    grid = QGridLayout()
    for column, state in enumerate(("off", "on", "auto", "alarm")):
        grid.addWidget(QLabel(state), 0, column + 1)
    for line, symbol in enumerate(SYMBOLS, start=1):
        grid.addWidget(QLabel(symbol), line, 0)
        for column, state in enumerate(("off", "on", "auto", "alarm")):
            element = ValveButton(symbol, symbol=symbol)
            # No focus ring in a picture of states.
            element.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            element.set_state_now(state != "off")
            if state == "auto":
                element.set_locked("a controller")
            if state == "alarm":
                element.set_alarm("alarm")
            grid.addWidget(element, line, column + 1)
    row.addLayout(grid)

    reservoir = TankGauge("Reservoir 1")
    reservoir.set_volume(3.2, 5.0)
    antifoam = TankGauge("Antifoam")
    antifoam.set_alarm("warning")
    reactor = VesselWidget()
    reactor.set_volume(10.0, 11.0, 5.0)  # VL0, VLmax, VLmin of project 716
    reactor.set_stirring(True)
    for element in (reservoir, antifoam, reactor):
        row.addWidget(element)
    row.addWidget(PipeDemo(), stretch=1)
    return sheet


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
