"""Plot templates and the multi-axis plot (plan section 6).

plot_templateTab and plot_variableTab are taken over unchanged, so the tests
run against the shipped template rather than a fixture — if the data changes,
the tests say so.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest

from biofermentation.db.plots import (
    PlotTemplate,
    PlotVariable,
    auto_limits,
    list_plot_templates,
    load_plot_template,
    save_plot_template,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


# ------------------------------------------------------------ templates --


def test_both_shipped_templates_load(db_copy):
    templates = list_plot_templates(db_copy)
    assert {row["name"] for row in templates} == {"Default", "Oxygen"}


def test_a_template_carries_every_variable_not_only_the_drawn_ones(db_copy):
    template = load_plot_template(db_copy, 1)
    assert len(template.variables) > len(template.selected())
    assert {v.name for v in template.selected()} == {
        "cXL",
        "cS1L",
        "qXpX",
        "pO2",
        "NSt",
        "thetaL",
    }


def test_the_axes_are_ordered_by_their_range(db_copy):
    """sortVariables: the widest scale outermost, so they do not cross."""
    selected = load_plot_template(db_copy, 1).selected()
    limits = [variable.ymax for variable in selected]
    assert limits == sorted(limits)


def test_limit_type_one_means_automatic(db_copy):
    """The field name says nothing; the window labels the checkbox "Auto"."""
    template = load_plot_template(db_copy, 1)
    po2 = next(v for v in template.variables if v.name == "pO2")
    assert po2.limit_type == 0 and po2.auto_limits is False
    cxl = next(v for v in template.variables if v.name == "cXL")
    assert cxl.limit_type == 1 and cxl.auto_limits is True


def test_colours_arrive_as_bytes(db_copy):
    """plot_colorTab stores 0..1 floats; Qt wants 0..255."""
    template = load_plot_template(db_copy, 1)
    black = next(v for v in template.variables if v.name == "cXL")
    assert black.color == (0, 0, 0)
    assert all(0 <= channel <= 255 for v in template.variables for channel in v.color)


def test_the_decimal_symbol_formats_a_value(db_copy):
    template = load_plot_template(db_copy, 1)
    growth = next(v for v in template.variables if v.name == "qXpX")
    assert growth.format(3.14159) == "3.142"


def test_an_unknown_template_is_refused(db_copy):
    with pytest.raises(LookupError, match="999"):
        load_plot_template(db_copy, 999)


def test_a_template_survives_a_save_and_reload(db_copy):
    template = load_plot_template(db_copy, 1)
    target = next(v for v in template.variables if v.name == "cS2L")
    target.selected = True
    target.ymax = 42.0
    target.limit_type = 0
    template.tend = 12.0

    save_plot_template(db_copy, template)
    again = load_plot_template(db_copy, 1)

    reloaded = next(v for v in again.variables if v.name == "cS2L")
    assert reloaded.selected is True
    assert reloaded.ymax == 42.0
    assert reloaded.auto_limits is False
    assert again.tend == 12.0


# ---------------------------------------------------------- auto limits --


@pytest.mark.parametrize(
    ("values", "current", "expected"),
    [
        # Rounds up to the next 2, 5 or 10 times a power of ten.
        ([0, 3.2, 7.9], (0, 100), (0.0, 20)),
        # Below a tenth of the current maximum the value is stretched by half
        # first, so 1.4 becomes 2.1 and rounds up to 5, not to 2.
        ([0, 1.4], (0, 100), (0.0, 5)),
        ([0, 4.0], (0, 4), (0.0, 5)),
        # Below a tenth of the current maximum it shrinks, with room to spare.
        ([0, 0.9], (0, 100), (0.0, 2)),
        # A negative minimum keeps the scale of the maximum.
        ([-2.5, 8.0], (0, 10), (-10, 10)),
        # Very small numbers have a floor.
        ([0, 1e-9], (0, 10), (0.0, 0.0001)),
    ],
)
def test_automatic_limits_follow_calculate_y_limits(values, current, expected):
    assert auto_limits(values, *current) == expected


def test_automatic_limits_ignore_nan_and_empty_data():
    assert auto_limits([np.nan, np.nan], 0, 10) == (0, 10)
    assert auto_limits([], 0, 10) == (0, 10)


# ------------------------------------------------------------- the plot --


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _template(*names: str) -> PlotTemplate:
    return PlotTemplate(
        templateID=0,
        tstart=0.0,
        tend=2.0,
        variables=[
            PlotVariable(
                variableID=index,
                name=name,
                shorttex=name,
                tex_unit="gl^{-1}",
                selected=True,
                limit_type=0,
                ymin=0.0,
                ymax=10.0 * (index + 1),
                color=(0, 0, 0),
            )
            for index, name in enumerate(names)
        ],
    )


def test_the_plot_builds_one_axis_per_variable(qapp):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a", "b", "c"))
    assert len(plot._views) == 3
    assert len(plot._curves) == 3
    # One extra axis per variable past the first; the first uses the plot's.
    assert len(plot._placeholders) == 2


def test_rebuilding_the_plot_does_not_pile_up_axes(qapp):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a", "b", "c"))
    plot.set_template(_template("a", "b"))
    assert len(plot._views) == 2
    assert len(plot._placeholders) == 1


def test_the_curves_receive_the_data(qapp):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a", "b"))
    t = np.linspace(0, 2, 100)
    plot.update_data(t, {"a": t * 2, "b": t * 3})

    for position, factor in enumerate((2, 3)):
        x, y = plot._curves[position].getData()
        assert len(x) == 100
        assert y[-1] == pytest.approx(2 * factor)


def test_every_pen_is_cosmetic(qapp):
    """A non-cosmetic pen is scaled by the ViewBox transform.

    A 1.5 pt line then comes out as a 50 px band and every curve looks like a
    filled area. pg.mkPen sets this; a QPen built by hand does not.
    """
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a", "b"))
    for curve in plot._curves:
        assert curve.opts["pen"].isCosmetic() is True


def test_automatic_limits_move_the_axis(qapp):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    template = _template("a")
    template.variables[0].limit_type = 1  # auto
    template.variables[0].ymax = 100.0

    plot = MultiAxisPlot()
    plot.set_template(template)
    t = np.linspace(0, 2, 50)
    plot.update_data(t, {"a": np.full_like(t, 3.0)})

    assert template.variables[0].ymax == 5
    assert plot._views[0].viewRange()[1] == [0.0, 5.0]


def test_manual_limits_stay_put(qapp):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    template = _template("a")  # limit_type 0
    plot = MultiAxisPlot()
    plot.set_template(template)
    plot.update_data(np.linspace(0, 2, 50), {"a": np.full(50, 3.0)})
    assert template.variables[0].ymax == 10.0


def test_a_curve_carries_its_name_at_the_end(qapp):
    """plotFlags: six scales are unreadable without it."""
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a"))
    assert plot._labels[0].isVisible() is False

    t = np.linspace(0, 2, 20)
    plot.update_data(t, {"a": t})
    assert plot._labels[0].isVisible() is True
    assert plot._labels[0].pos().y() == pytest.approx(2.0)


def test_a_template_without_a_selection_draws_nothing(qapp):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    template = _template("a")
    template.variables[0].selected = False
    plot = MultiAxisPlot()
    plot.set_template(template)
    assert plot._views == []
    plot.update_data(np.array([0.0, 1.0]), {"a": np.array([1.0, 2.0])})


# ------------------------------------------------------- the window --


@pytest.fixture
def figure(qapp, db_copy):
    from biofermentation.core.runner import load_project_state
    from biofermentation.core.simulation_runner import SimulationRunner
    from biofermentation.gui.windows import FigureWindow
    from biofermentation.organisms import discover_organisms

    discover_organisms()
    state, organism = load_project_state(db_copy, 716)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    runner = SimulationRunner(organism, state, interval_ms=1)
    for _ in range(30):
        runner._on_tick()
    return FigureWindow(load_plot_template(db_copy, 1), runner, db_copy)


def test_the_window_offers_every_variable(figure):
    assert len(figure.checkboxes) == len(figure.template.variables)
    assert figure.checkboxes["cXL"].isChecked() is True
    assert figure.checkboxes["cS2L"].isChecked() is False


def test_the_limit_rows_match_the_drawn_axes(figure):
    assert set(figure.limit_rows) == {v.name for v in figure.template.selected()}


def test_a_manual_axis_has_editable_fields(figure):
    lower, _, auto = figure.limit_rows["pO2"]
    assert auto.isChecked() is False
    assert lower.isEnabled() is True

    lower, _, auto = figure.limit_rows["cXL"]
    assert auto.isChecked() is True
    assert lower.isEnabled() is False


def test_ticking_a_variable_adds_an_axis(figure):
    before = len(figure.template.selected())
    figure.checkboxes["cS2L"].setChecked(True)
    assert len(figure.template.selected()) == before + 1
    assert "cS2L" in figure.limit_rows


def test_turning_auto_off_frees_the_fields(figure):
    _, _, auto = figure.limit_rows["cXL"]
    auto.setChecked(False)
    lower, _, _ = figure.limit_rows["cXL"]
    assert lower.isEnabled() is True
    assert next(v for v in figure.template.variables if v.name == "cXL").limit_type == 0


def test_the_time_range_reaches_the_plot(figure):
    figure.tend_box.setValue(8.0)
    assert figure.template.tend == 8.0
    assert figure.plot.plot_item.viewRange()[0][1] == pytest.approx(8.0)


def test_auto_update_can_be_switched_off(figure):
    figure.auto_button.setChecked(False)
    assert figure.auto_update is False
    figure._on_block()  # a block arrives and is ignored


def test_saving_the_template_writes_the_selection(figure, db_copy):
    figure.checkboxes["cS2L"].setChecked(True)
    figure.save_template()
    again = load_plot_template(db_copy, figure.template.templateID)
    assert next(v for v in again.variables if v.name == "cS2L").selected is True
