"""Plot templates and the multi-axis plot (plan section 6).

plot_templateTab and plot_variableTab are taken over unchanged, so the tests
run against the shipped template rather than a fixture — if the data changes,
the tests say so.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QColor

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
    assert len(plot._axes) == 3


def test_rebuilding_the_plot_does_not_pile_up_axes(qapp):
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a", "b", "c"))
    plot.set_template(_template("a", "b"))
    assert len(plot._views) == 2
    assert len(plot._axes) == 2


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
    # At the end of the flag stub, which starts at the last data point.
    assert plot._labels[0].pos().y() >= 2.0


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
    assert figure.plot.main_view.viewRange()[0][1] == pytest.approx(8.0)


def test_auto_update_can_be_switched_off(figure):
    figure.auto_button.setChecked(False)
    assert figure.auto_update is False
    figure._on_block()  # a block arrives and is ignored


def test_saving_the_template_writes_the_selection(figure, db_copy):
    figure.checkboxes["cS2L"].setChecked(True)
    figure.save_template()
    again = load_plot_template(db_copy, figure.template.templateID)
    assert next(v for v in again.variables if v.name == "cS2L").selected is True


def test_every_y_axis_is_flush_with_the_plot_area(qapp):
    """The axes have to share their row with the ViewBox, not the x-axis.

    Putting them in a row of their own makes each of them as tall as the
    whole plot including its bottom axis, and every scale then sits a few
    pixels off the one next to it.
    """
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a", "b", "c"))
    plot.resize(800, 400)
    plot.show()
    qapp.processEvents()

    # geometry(), not sceneBoundingRect(): an AxisItem's bounding rect
    # includes the overhang of its tick labels and says nothing about where
    # the layout put it.
    plot_area = plot.main_view.geometry()
    for axis in plot._axes:
        cell = axis.geometry()
        assert cell.top() == pytest.approx(plot_area.top(), abs=0.5)
        assert cell.height() == pytest.approx(plot_area.height(), abs=0.5)

    # The bottom axis sits under the plot area alone, not under the scales.
    assert plot.bottom_axis.geometry().top() > plot_area.bottom() - 1
    assert plot.bottom_axis.geometry().left() == pytest.approx(plot_area.left(), abs=0.5)


def test_every_axis_has_the_same_number_of_divisions(qapp):
    """axisytick of the template, so the ticks of all scales line up."""
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    template = _template("a", "b", "c")
    template.axisytick = 5.0
    plot = MultiAxisPlot()
    plot.set_template(template)
    plot.resize(800, 400)
    plot.show()
    qapp.processEvents()

    for position, axis in enumerate(plot._axes):
        variable = plot._variables[position]
        expected = (variable.ymax - variable.ymin) / template.axisytick
        assert axis._tickSpacing[0][0] == pytest.approx(expected)


def test_the_plot_has_no_grid(qapp):
    """A checkered background is not wanted."""
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    plot.set_template(_template("a", "b"))
    for axis in [*plot._axes, plot.bottom_axis]:
        assert axis.grid is False


# ------------------------------------------ axes: outward ticks, alignment --


def _probe_plot(qapp, count: int = 3):
    """A plot with straight lines and known limits, for pixel measurements."""
    from biofermentation.db.plots import PlotTemplate, PlotVariable
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    template = PlotTemplate(templateID=0, tstart=0, tend=10, plottitle="", titlebool=0)
    template.variables = [
        PlotVariable(
            variableID=index,
            name=name,
            shorttex=name,
            tex_unit="-",
            selected=True,
            limit_type=0,
            ymin=0,
            ymax=maximum,
            color=color,
        )
        for index, (name, maximum, color) in enumerate(
            [("a", 10, (255, 0, 0)), ("b", 100, (0, 0, 255)), ("c", 1000, (0, 160, 0))][:count],
            start=1,
        )
    ]
    plot = MultiAxisPlot()
    plot.resize(900, 500)
    plot.set_template(template)
    plot.show()
    qapp.processEvents()
    t = np.linspace(0, 10, 200)
    plot.update_data(t, {"a": t, "b": t * 10, "c": t * 100})
    qapp.processEvents()
    return plot


def test_every_stacked_view_sits_on_the_main_one(qapp):
    """The curves of the second and further axes were a few pixels right.

    They live in the scene rather than in the layout, so nothing moves them
    when the layout runs again after the axis labels are measured.
    """
    plot = _probe_plot(qapp)
    main = plot.main_view.sceneBoundingRect()
    for index, view in enumerate(plot._views[1:], start=1):
        rect = view.sceneBoundingRect()
        assert abs(rect.x() - main.x()) < 1.0, f"view {index} is off in x"
        assert abs(rect.width() - main.width()) < 1.0, f"view {index} is off in width"


def test_a_late_resize_still_lines_the_views_up(qapp):
    plot = _probe_plot(qapp)
    plot.resize(1200, 600)
    qapp.processEvents()
    main = plot.main_view.sceneBoundingRect()
    for view in plot._views[1:]:
        assert abs(view.sceneBoundingRect().x() - main.x()) < 1.0


def test_a_tick_starts_on_the_axis_line_not_past_it(qapp, monkeypatch):
    """Point 5. pyqtgraph draws the axis line one pixel towards the plot.

    The tick starts where the axis *item* ends, so it always crossed that line
    and poked into the plot; with the minor ticks two pixels long the whole
    row read as pointing inwards. OutwardAxis moves the inner end onto the
    line. The shift is checked against the offsets generateDrawSpecs applies.
    """
    import pyqtgraph as pg

    from biofermentation.gui.widgets.plot_view import OutwardAxis

    raw = (
        ("axis", pg.Point(0, 0), pg.Point(0, 100)),
        [("pen", pg.Point(50.0, 10.0), pg.Point(44.0, 10.0))],
        [],
    )
    monkeypatch.setattr(pg.AxisItem, "generateDrawSpecs", lambda self, p: raw)

    left = OutwardAxis("left").generateDrawSpecs(None)
    _, ticks, _ = left
    # The plot is to the right of a left axis, so the start moves left.
    assert ticks[0][1].x() == 49.0
    assert ticks[0][2].x() == 44.0, "the outer end must not move"

    bottom = OutwardAxis("bottom").generateDrawSpecs(None)
    _, ticks, _ = bottom
    # The plot is above a bottom axis, so the start moves down.
    assert ticks[0][1].y() == 11.0
    assert ticks[0][2].y() == 10.0


def test_the_axis_override_passes_a_missing_spec_through(qapp, monkeypatch):
    import pyqtgraph as pg

    from biofermentation.gui.widgets.plot_view import OutwardAxis

    monkeypatch.setattr(pg.AxisItem, "generateDrawSpecs", lambda self, p: None)
    assert OutwardAxis("left").generateDrawSpecs(None) is None


def test_the_ticks_of_a_built_plot_point_away_from_the_data(qapp):
    plot = _probe_plot(qapp, count=1)
    main = plot.main_view.sceneBoundingRect()

    axis = plot._axes[0]
    right = axis.sceneBoundingRect().right()
    assert right <= main.left(), "the y-axis overlaps the plot area"

    bottom = plot.bottom_axis.sceneBoundingRect()
    assert bottom.top() >= main.bottom() - 1.0, "the x-axis overlaps the plot area"


def test_the_innermost_axis_is_flush_with_the_plot(qapp):
    """Point 11: a gap with nothing in it between the last y-axis and the x-axis.

    The caption above an axis is wider than the axis and therefore sets the
    width of the column. Centred, half of that surplus lands to the right of
    the axis line — for the innermost axis, right where the plot begins.
    """
    plot = _probe_plot(qapp)
    left = plot.main_view.sceneBoundingRect().left()
    assert abs(plot._axes[0].sceneBoundingRect().right() - left) < 1.0


def test_the_curves_are_drawn_over_the_axes(qapp):
    """A curve running along x = 0 lies on the innermost axis."""
    plot = _probe_plot(qapp)
    for axis, view in zip(plot._axes, plot._views, strict=True):
        assert view.zValue() > axis.zValue()


def test_each_axis_caption_carries_the_colour_of_its_axis(qapp):
    """Point 13: the captions were in the foreground colour, not the curve's."""
    plot = _probe_plot(qapp)
    assert len(plot._captions) == len(plot._variables)
    for caption, variable in zip(plot._captions, plot._variables, strict=True):
        expected = QColor(*variable.color).name()
        assert caption.opts["color"] == expected, f"{variable.name}: {caption.opts}"


def test_a_caption_sits_above_its_own_axis(qapp):
    plot = _probe_plot(qapp)
    # geometry(), not sceneBoundingRect(): an AxisItem's bounding rect reaches
    # past its cell to make room for the tick text.
    for caption, axis in zip(plot._captions, plot._axes, strict=True):
        assert caption.geometry().bottom() <= axis.geometry().top() + 1
        # Right edges line up: both are pinned to the right of their column.
        assert abs(caption.geometry().right() - axis.geometry().right()) < 2.0


def test_the_time_axis_prints_both_ends_of_its_range(qapp):
    """A window from 0 to 5 h was labelled 0.5 … 4.5 and nothing at the ends.

    pyqtgraph picks round numbers, and it drops any tick text whose rectangle
    is not fully inside the axis item — a label centred on the first pixel is
    half outside by construction.
    """
    from PySide6.QtGui import QPainter, QPixmap

    plot = _probe_plot(qapp, count=1)
    pixmap = QPixmap(10, 10)
    painter = QPainter(pixmap)
    try:
        specs = plot.bottom_axis.generateDrawSpecs(painter)
    finally:
        painter.end()
    labels = {text for _, _, text in specs[2]}
    assert {"0", "5"} <= labels, labels


def test_an_end_label_stays_inside_the_axis(qapp):
    from PySide6.QtGui import QPainter, QPixmap

    plot = _probe_plot(qapp, count=1)
    axis = plot.bottom_axis
    pixmap = QPixmap(10, 10)
    painter = QPainter(pixmap)
    try:
        specs = axis.generateDrawSpecs(painter)
    finally:
        painter.end()
    bounds = axis.boundingRect()
    for rect, _, _ in specs[2]:
        assert bounds.left() - 0.5 <= rect.left()
        assert rect.right() <= bounds.right() + 0.5


def test_the_tick_numbers_are_smaller_than_the_caption(qapp):
    """Point 1 of the third round: smaller numbers, further from the line."""
    from biofermentation.gui.widgets.plot_view import (
        CAPTION_FONT_SCALE,
        TICK_FONT_SCALE,
        TICK_TEXT_OFFSET,
    )

    assert TICK_FONT_SCALE < CAPTION_FONT_SCALE <= 1.0
    assert TICK_TEXT_OFFSET > 2

    plot = _probe_plot(qapp)
    template = plot.template
    # tickTextOffset is a pair; pyqtgraph puts a scalar into the entry that
    # belongs to the orientation — 0 horizontal, 1 vertical.
    for axis, index in [(a, 0) for a in plot._axes] + [(plot.bottom_axis, 1)]:
        assert axis.style["tickFont"].pointSizeF() < template.axislabelfontsize
        assert axis.style["tickTextOffset"][index] == TICK_TEXT_OFFSET


def test_narrower_captions_bring_the_scales_closer(qapp):
    """The caption sets the column width, not the tick numbers."""
    import biofermentation.gui.widgets.plot_view as plot_view

    def stack_width(caption_scale):
        original = plot_view.CAPTION_FONT_SCALE
        plot_view.CAPTION_FONT_SCALE = caption_scale
        try:
            plot = _probe_plot(qapp)
            left = min(axis.geometry().left() for axis in plot._axes)
            return plot.main_view.sceneBoundingRect().left() - left
        finally:
            plot_view.CAPTION_FONT_SCALE = original

    assert stack_width(0.85) < stack_width(1.0)


# --------------------------------------------------------------- flags --


def _flag_vector(plot, position: int = 0) -> tuple[float, float]:
    """The stub of one curve, in pixels."""
    stub = plot._stubs[position]
    x, y = stub.getData()
    pixel_x, pixel_y = plot._views[position].viewPixelSize()
    return (x[1] - x[0]) / pixel_x, (y[1] - y[0]) / pixel_y


def test_a_flag_is_a_stub_with_the_name_at_its_end(qapp):
    """The angle setting drew nothing at all before; MATLAB multiplies it
    straight onto the y span and calls the result an angle."""
    plot = _probe_plot(qapp, count=1)
    stub, label = plot._stubs[0], plot._labels[0]
    assert stub.isVisible()

    x, y = stub.getData()
    assert len(x) == 2
    assert label.pos().x() == pytest.approx(x[1])
    assert label.pos().y() == pytest.approx(y[1])


def test_the_flag_angle_is_an_angle_in_pixels(qapp):
    """Every scale has a different range, so an angle taken in data units
    would come out differently on each of them."""
    import math

    plot = _probe_plot(qapp)
    plot.template.flagangle = 30.0
    plot.template.flaglength = 0.05
    t = np.linspace(0, 10, 200)
    plot.update_data(t, {"a": t, "b": t * 10, "c": t * 100})

    for position in range(len(plot._stubs)):
        dx, dy = _flag_vector(plot, position)
        # viewPixelSize gives the magnitude of a pixel, so dy counts upwards
        # here the way the data does.
        assert math.degrees(math.atan2(dy, dx)) == pytest.approx(30.0, abs=1.0)
        assert math.hypot(dx, dy) == pytest.approx(0.05 * plot._views[position].width(), rel=0.02)


def test_changing_the_flag_settings_shows(qapp):
    plot = _probe_plot(qapp, count=1)
    t = np.linspace(0, 10, 200)

    plot.template.flagangle = 0.0
    plot.template.flaglength = 0.04
    plot.update_data(t, {"a": t})
    flat = _flag_vector(plot)

    plot.template.flagangle = 60.0
    plot.update_data(t, {"a": t})
    steep = _flag_vector(plot)

    assert abs(flat[1]) < 1e-6, "a zero angle has to be horizontal"
    assert steep[1] > flat[1], "a positive angle has to point upwards"
    assert steep[0] < flat[0], "and reach less far sideways"


def test_a_flag_of_zero_length_draws_no_stub(qapp):
    plot = _probe_plot(qapp, count=1)
    plot.template.flaglength = 0.0
    plot.update_data(np.linspace(0, 10, 50), {"a": np.linspace(0, 10, 50)})
    assert plot._stubs[0].isVisible() is False
    assert plot._labels[0].isVisible() is True


def test_the_time_axis_takes_its_divisions_from_the_template(qapp):
    """axisxtick did nothing; the setting has to mean what it says."""
    plot = _probe_plot(qapp, count=1)
    plot.template.axisxtick = 4
    plot.set_x_range(0, 8)
    assert plot.bottom_axis._tickSpacing == [(2.0, 0), (2.0, 0)]


def test_the_caption_does_not_sit_on_the_first_tick(qapp):
    from biofermentation.gui.widgets.plot_view import CAPTION_GAP

    plot = _probe_plot(qapp)
    for caption, axis in zip(plot._captions, plot._axes, strict=True):
        gap = axis.geometry().top() - caption.geometry().bottom()
        assert gap >= CAPTION_GAP - 1
