"""The time axis holds at t max unless it may follow the run.

Until 18.11.2026 the plot widened its time axis by itself as soon as the
process time passed the template's tend, and the Max field of the figure
window meant nothing once a run was long enough. Now tend is the upper limit,
and "Extend t max with the run" is the one way past it — with Max locked and
unchanged while ticked, so that unticking returns to exactly that limit.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from biofermentation.db.plots import PlotTemplate, PlotVariable, load_plot_template

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _plot(tend: float = 2.0):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    template = PlotTemplate(
        templateID=0,
        tstart=0.0,
        tend=tend,
        variables=[
            PlotVariable(
                variableID=0,
                name="a",
                shorttex="a",
                tex_unit="",
                selected=True,
                limit_type=0,
                ymin=0.0,
                ymax=10.0,
                color=(0, 0, 0),
            )
        ],
    )
    plot = MultiAxisPlot()
    plot.set_template(template)
    return plot


def _run_to(plot, hours: float) -> None:
    t = np.linspace(0.0, hours, 200)
    plot.update_data(t, {"a": t})


def _x_max(plot) -> float:
    return plot.main_view.viewRange()[0][1]


def test_the_time_axis_stays_at_t_max_when_the_run_passes_it(qapp):
    plot = _plot(tend=2.0)
    _run_to(plot, 5.0)
    assert _x_max(plot) == pytest.approx(2.0)
    assert plot.template.tend == 2.0


def test_ticked_it_grows_with_the_run_and_t_max_stays_as_set(qapp):
    plot = _plot(tend=2.0)
    plot.set_follow_time(True)
    _run_to(plot, 5.0)
    assert _x_max(plot) == pytest.approx(5.0)
    _run_to(plot, 6.5)
    assert _x_max(plot) == pytest.approx(6.5)
    assert plot.template.tend == 2.0


def test_unticking_puts_the_axis_back_at_t_max(qapp):
    plot = _plot(tend=2.0)
    plot.set_follow_time(True)
    _run_to(plot, 5.0)
    plot.set_follow_time(False)
    assert _x_max(plot) == pytest.approx(2.0)
    _run_to(plot, 7.0)
    assert _x_max(plot) == pytest.approx(2.0)


def test_ticking_after_the_run_has_passed_widens_at_once(qapp):
    plot = _plot(tend=2.0)
    _run_to(plot, 5.0)
    plot.set_follow_time(True)
    assert _x_max(plot) == pytest.approx(5.0)


def test_below_t_max_following_changes_nothing(qapp):
    plot = _plot(tend=2.0)
    plot.set_follow_time(True)
    _run_to(plot, 1.0)
    assert _x_max(plot) == pytest.approx(2.0)


def test_a_new_template_keeps_the_switch(qapp):
    plot = _plot(tend=2.0)
    plot.set_follow_time(True)
    _run_to(plot, 5.0)
    plot.set_template(plot.template)
    assert _x_max(plot) == pytest.approx(5.0)


# ----------------------------------------------------- the figure window --


@pytest.fixture
def figure(qapp, tmp_path):
    from biofermentation.core.runner import load_project_state
    from biofermentation.core.simulation_runner import SimulationRunner
    from biofermentation.gui.windows import FigureWindow
    from biofermentation.organisms import discover_organisms

    db = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, db)
    discover_organisms()
    state, organism = load_project_state(db, 716)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    runner = SimulationRunner(organism, state, interval_ms=1)
    for _ in range(30):
        runner._on_tick()
    window = FigureWindow(load_plot_template(db, 1), runner, db)
    yield window
    window.close()


def test_the_box_is_unticked_and_max_editable_at_first(figure):
    assert not figure.follow_box.isChecked()
    assert figure.tend_box.isEnabled()
    assert figure.plot.follow_time is False


def test_ticked_max_is_locked_and_keeps_its_value(figure):
    figure.tend_box.setValue(0.5)
    figure.follow_box.setChecked(True)
    assert not figure.tend_box.isEnabled()
    assert figure.tend_box.value() == 0.5
    assert figure.template.tend == 0.5
    assert figure.plot.follow_time is True
    assert "Locked" in figure.tend_box.toolTip()


def test_the_window_holds_max_and_follows_only_when_ticked(figure):
    """A run past Max: held at Max, widened when ticked, back when unticked."""
    figure.tend_box.setValue(0.01)
    figure.refresh()
    t_last = float(figure.runner.state.v.t[figure.runner.state.idx])
    assert t_last > 0.01
    assert _x_max(figure.plot) == pytest.approx(0.01)

    figure.follow_box.setChecked(True)
    figure.refresh()
    assert _x_max(figure.plot) == pytest.approx(t_last)

    figure.follow_box.setChecked(False)
    assert figure.tend_box.isEnabled()
    assert _x_max(figure.plot) == pytest.approx(0.01)
