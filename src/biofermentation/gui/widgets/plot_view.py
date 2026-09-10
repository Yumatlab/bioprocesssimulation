"""The multi-axis live plot (plan section 6.1).

The layout is built by hand rather than taken from pyqtgraph's PlotItem, and
that is the whole point of this module.

PlotItem keeps its own left axis in column 0 of an internal grid and its
ViewBox in column 1, and QGraphicsGridLayout cannot insert a column in front
of an existing one. Extra axes therefore have to go somewhere else — and if
they go into a row of the outer layout, that row also spans the PlotItem's
title and x-axis, so every extra axis ends up taller than the plot area and
sits a few pixels off. The original stacks its axes flush with the plot area,
so the layout here is explicit:

    row 0   title, spanning everything
    row 1   caption[n-1] … caption[1] caption[0]
    row 2   axis[n-1]    … axis[1]    axis[0]    | ViewBox
    row 3                                        | bottom axis

Every y-axis shares row 1 with the ViewBox and is therefore exactly as tall
as the plot area. The bottom axis sits under the ViewBox alone.

Each y-axis carries its caption above itself rather than rotated alongside,
in the colour of the axis, the way the figures of the thesis do it. Row 1
exists only for those captions.

The tick spacing is forced to the template's axisytick on every axis, so the
divisions of all scales line up horizontally — the way they do in the MATLAB
figure. Without that each axis picks its own spacing and the gridlines of one
scale fall between those of the next.
"""

from typing import ClassVar

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QWidget

from ...db.plots import PlotTemplate, PlotVariable, auto_limits
from .tex import tex_to_html

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

# Positive length points away from the plot area — ticks on the outside.
TICK_LENGTH = 7

#: Tick numbers are drawn smaller than the axis caption above them, and set
#: away from the axis line. Both let the scales stand closer together without
#: the numbers of one touching the line of the next.
TICK_FONT_SCALE = 0.78
TICK_TEXT_OFFSET = 6

#: The caption above an axis, relative to the template's axislabelfontsize.
#: It is the caption, not the tick numbers, that sets how wide an axis column
#: is — measured with six scales, the captions are 56 to 81 px wide and the
#: axes themselves 26 to 48. Shrinking the numbers alone moves the stack by
#: four pixels; this brings the scales about fifty pixels closer together.
CAPTION_FONT_SCALE = 0.85


class EndLabelledAxis(pg.AxisItem):
    """An axis that always prints the two ends of its range.

    pyqtgraph picks round numbers, and the first and last of them rarely fall
    on the limits themselves — a time axis from 0 to 5 h ends up labelled
    0.5 … 4.5 with nothing at either end, so the window the plot actually
    shows cannot be read off it.

    Two things are needed. tickValues puts the limits into the tick list, and
    generateDrawSpecs puts their labels back: pyqtgraph drops any tick text
    whose rectangle is not fully inside the axis item, and a label centred on
    the very first pixel is half outside by construction. The two end labels
    are pulled inside instead of being dropped.
    """

    def tickValues(self, minVal, maxVal, size):  # noqa: N802 - pyqtgraph API
        levels = super().tickValues(minVal, maxVal, size)
        if not levels:
            return levels
        spacing, values = levels[0]
        lower, upper = min(minVal, maxVal), max(minVal, maxVal)
        # Close to an end, a chosen tick would collide with the end label.
        margin = 0.3 * abs(spacing) if spacing else 0.0
        kept = [v for v in values if lower + margin < v < upper - margin]
        return [(spacing, sorted({lower, upper, *kept})), *levels[1:]]

    def generateDrawSpecs(self, p):  # noqa: N802 - pyqtgraph API
        specs = super().generateDrawSpecs(p)
        if specs is None or self.orientation not in ("bottom", "top"):
            return specs
        axis_spec, tick_specs, text_specs = specs
        if not tick_specs:
            return specs

        bounds = self.boundingRect()
        positions = [start.x() for _, start, _ in tick_specs]
        offset = max(0, self.style["tickLength"]) + self.style["tickTextOffset"][0]
        spacing = self.tickValues(*sorted(self.range), bounds.width())[0][0]

        added = list(text_specs)
        for value, x in zip(sorted(self.range), (min(positions), max(positions)), strict=True):
            if any(abs(rect.center().x() - x) < 1.0 for rect, _, _ in text_specs):
                continue  # pyqtgraph found room for it after all
            text = self.tickStrings([value], self.scale, spacing)[0]
            if text is None:
                continue
            size = p.boundingRect(QRectF(0, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, text)
            top = (
                bounds.top() + offset
                if self.orientation == "bottom"
                else bounds.bottom() - offset - size.height()
            )
            left = min(max(x - size.width() / 2, bounds.left()), bounds.right() - size.width())
            added.append(
                (
                    QRectF(left, top, size.width(), size.height()),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextDontClip,
                    text,
                )
            )
        return axis_spec, tick_specs, added


class OutwardAxis(pg.AxisItem):
    """An axis whose ticks lie strictly outside the plot area.

    pyqtgraph already draws a positive tickLength away from the plot, but it
    offsets the axis *line* by one pixel towards the plot relative to where
    the ticks start (`left_offset`/`bottom_offset` in generateDrawSpecs).
    Every tick therefore pokes one pixel across the line into the plot, and
    with the minor ticks only two pixels long the whole row reads as pointing
    inwards. Moving each tick's inner end onto the axis line removes the
    overhang; nothing else about the drawing changes.
    """

    #: The offset generateDrawSpecs applies to the axis line, per orientation.
    _LINE_OFFSET: ClassVar[dict[str, tuple[int, int]]] = {
        "left": (-1, 0),
        "right": (1, 0),
        "top": (0, -1),
        "bottom": (0, 1),
    }

    def generateDrawSpecs(self, p):  # noqa: N802 - pyqtgraph API
        specs = super().generateDrawSpecs(p)
        if specs is None:
            return specs
        axis_spec, tick_specs, text_specs = specs
        dx, dy = self._LINE_OFFSET.get(self.orientation, (0, 0))
        if dx or dy:
            tick_specs = [
                (pen, pg.Point(start.x() + dx, start.y() + dy), stop)
                for pen, start, stop in tick_specs
            ]
        return axis_spec, tick_specs, text_specs


class OutwardTimeAxis(EndLabelledAxis, OutwardAxis):
    """The x-axis: ticks outside, and the ends of the range labelled."""


def _tick_font(base: float) -> QFont:
    font = QFont()
    font.setPointSizeF(max(6.0, base * TICK_FONT_SCALE))
    return font


class MultiAxisPlot(pg.GraphicsLayoutWidget):
    """One x-axis, one y-axis per variable, all sharing the same time base."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # Explicitly, not only through pg.setConfigOption: the config option
        # is read when a widget is built, and a plot built before this module
        # is imported would take the platform background — grey, in dark mode.
        self.setBackground("w")
        self.template: PlotTemplate | None = None
        self.main_view: pg.ViewBox | None = None
        self.bottom_axis: pg.AxisItem | None = None
        self.title_item: pg.LabelItem | None = None

        self._views: list[pg.ViewBox] = []
        self._axes: list[pg.AxisItem] = []
        self._captions: list[pg.LabelItem] = []
        self._curves: list[pg.PlotDataItem] = []
        self._labels: list[pg.TextItem] = []
        self._variables: list[PlotVariable] = []

    # ------------------------------------------------------------ build --

    def set_template(self, template: PlotTemplate) -> None:
        """Rebuild for a template. Throw the layout away and build it again."""
        self.template = template
        self._clear()

        variables = template.selected()
        self._variables = variables
        if not variables:
            return

        count = len(variables)

        if template.show_title and template.plottitle:
            self.title_item = self.addLabel(
                template.plottitle,
                row=0,
                col=0,
                colspan=count + 1,
                size=f"{template.graphtitlefontsize:.0f}pt",
            )

        # The ViewBox every curve shares an x-axis with.
        self.main_view = pg.ViewBox()
        self.main_view.setMouseEnabled(x=True, y=False)
        # The x range is the template's, not whatever the data happens to
        # span. Left on, autoRange also takes the end labels into account and
        # drags the axis far past the run.
        self.main_view.enableAutoRange(axis="x", enable=False)
        # The extra ViewBoxes are not in the layout and only follow when this
        # fires. resizeEvent alone is not enough: the layout runs again after
        # the axis labels are known, without the widget being resized, and the
        # stacked views would keep the geometry from the pass before — the
        # curves then sit a few pixels to the right of their axes.
        self.main_view.sigResized.connect(self._resize_views)
        self.addItem(self.main_view, row=2, col=count)
        self.ci.layout.setColumnStretchFactor(count, 1)
        # No spacing between the axis columns and the plot area: the gap left
        # the innermost y-axis standing away from the x-axis, with nothing in
        # between.
        self.ci.layout.setHorizontalSpacing(0)
        self.ci.layout.setVerticalSpacing(0)

        unit = template.axisxunit.strip("[] ")
        self.bottom_axis = OutwardTimeAxis("bottom")
        self.bottom_axis.linkToView(self.main_view)
        self.bottom_axis.enableAutoSIPrefix(False)
        self.bottom_axis.setStyle(tickLength=TICK_LENGTH)
        bottom_pen = QPen(QColor("k"))
        bottom_pen.setWidthF(template.axislinewidth)
        bottom_pen.setCosmetic(True)
        self.bottom_axis.setPen(bottom_pen)
        self.bottom_axis.setTickFont(_tick_font(template.graphfontsize))
        self.bottom_axis.setStyle(tickLength=TICK_LENGTH, tickTextOffset=TICK_TEXT_OFFSET)
        self.bottom_axis.setLabel(
            f"{template.axisxlabel} [{unit}]" if unit else template.axisxlabel,
            **{"font-size": f"{template.axislabelfontsize:.0f}pt"},
        )
        self.addItem(self.bottom_axis, row=3, col=count)

        # Column 0 is the outermost axis, so the innermost variable — the one
        # with the smallest range — ends up next to the plot area.
        for position, variable in enumerate(variables):
            self._add_variable(position, count - 1 - position, variable)

        self.set_x_range(template.tstart, template.tend)
        self._resize_views()

    def _add_variable(self, position: int, column: int, variable: PlotVariable) -> None:
        color = QColor(*variable.color)
        caption = tex_to_html(variable.label())
        rendered_unit = tex_to_html(variable.tex_unit) if variable.tex_unit else ""
        heading = f"{caption} [{rendered_unit}]" if rendered_unit else caption

        pen = QPen(color)
        pen.setWidthF(self.template.graphlinewidth if self.template else 1.5)
        # Cosmetic, or the width is taken in data units and scaled by the
        # ViewBox transform — a 1.5 pt line then comes out as a 50 px band and
        # every curve looks like a filled area. pg.mkPen sets this; a QPen
        # built by hand does not.
        pen.setCosmetic(True)
        if variable.dash_pattern:
            pen.setStyle(pg.QtCore.Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([float(step) for step in variable.dash_pattern])

        if position == 0:
            view = self.main_view
        else:
            # Only the first ViewBox is in the layout; the rest live in the
            # scene and are moved onto it in _resize_views.
            view = pg.ViewBox()
            view.setMouseEnabled(x=False, y=False)
            self.scene().addItem(view)
            view.setXLink(self.main_view)

        axis = OutwardAxis("left")
        axis.linkToView(view)
        axis_pen = QPen(color)
        axis_pen.setWidthF(self.template.axislinewidth if self.template else 1.75)
        axis_pen.setCosmetic(True)
        axis.setPen(axis_pen)
        axis.setTextPen(QPen(color))
        axis.setTickFont(_tick_font(self.template.graphfontsize if self.template else 12.0))
        # No "(x0.001)" over the axis; the original prints the numbers as
        # they are, and the unit is already in the caption.
        axis.enableAutoSIPrefix(False)
        # Ticks outside the plot area, as in the original. pyqtgraph counts a
        # positive length towards the labels, which for a left axis is out.
        axis.setStyle(tickLength=TICK_LENGTH, tickTextOffset=TICK_TEXT_OFFSET)
        # The caption sits above the axis, in the colour of the axis, as the
        # figures of the thesis have it. setLabel would rotate it alongside
        # and draw it in the foreground colour instead.
        base = self.template.axislabelfontsize if self.template else 12.0
        size = f"{max(6.0, base * CAPTION_FONT_SCALE):.1f}pt"
        label = self.addLabel(heading, row=1, col=column, color=color.name(), size=size, bold=True)
        self._captions.append(label)
        self.addItem(axis, row=2, col=column)

        # The caption is wider than the axis and therefore sets the width of
        # the column. Centred, half of that surplus ends up to the right of
        # the axis — and for the innermost axis that is the gap between it
        # and the plot area, with nothing in it. Both are pinned to the right
        # edge of their column instead, so every axis line sits under the
        # right edge of its own caption and the innermost one is flush with
        # the plot.
        right = Qt.AlignmentFlag.AlignRight
        self.ci.layout.setAlignment(axis, right | Qt.AlignmentFlag.AlignVCenter)
        self.ci.layout.setAlignment(label, right | Qt.AlignmentFlag.AlignBottom)

        # Data over decoration: a curve running along x = 0 lies on the
        # innermost axis, and behind it there is no telling which one it is.
        axis.setZValue(0)
        view.setZValue(1)

        curve = pg.PlotDataItem([], [], pen=pen)
        view.addItem(curve)

        # The curve's name at its right end, in its own colour — plotFlags of
        # the original. With six scales the plot is unreadable without it.
        flag = pg.TextItem(
            html=f'<span style="color:{color.name()}">{caption}</span>', anchor=(0, 0.5)
        )
        font = QFont()
        font.setPointSizeF(self.template.flagfontsize * 0.6 if self.template else 10)
        flag.setFont(font)
        # ignoreBounds: the label sits past the last data point, and letting
        # it count towards the range would stretch the axis every step.
        view.addItem(flag, ignoreBounds=True)
        flag.hide()

        self._views.append(view)
        self._axes.append(axis)
        self._curves.append(curve)
        self._labels.append(flag)
        self._apply_range(position, variable.ymin, variable.ymax)

    def _apply_range(self, position: int, lower: float, upper: float) -> None:
        """Set an axis range and pin its divisions to the template's count.

        Every scale gets the same number of intervals, so their ticks sit at
        the same heights and the scales can be read across.
        """
        self._views[position].setYRange(lower, upper, padding=0)
        self._views[position].enableAutoRange(axis="y", enable=False)
        divisions = int(self.template.axisytick) if self.template else 5
        if divisions > 0 and upper > lower:
            step = (upper - lower) / divisions
            self._axes[position].setTickSpacing(major=step, minor=step)

    def _clear(self) -> None:
        for position, view in enumerate(self._views):
            if position == 0:
                continue
            scene = view.scene()
            if scene is not None:
                scene.removeItem(view)
        self._views.clear()
        self._axes.clear()
        self._captions.clear()
        self._curves.clear()
        self._labels.clear()
        self._variables.clear()
        self.main_view = None
        self.bottom_axis = None
        self.title_item = None
        self.clear()

    # ------------------------------------------------------------- data --

    def update_data(self, t: np.ndarray, series: dict[str, np.ndarray]) -> None:
        """Redraw from the trimmed time series of the simulation state."""
        if not self._variables or t.size == 0 or self.main_view is None:
            return

        for position, variable in enumerate(self._variables):
            values = series.get(variable.name)
            if values is None:
                continue
            length = min(t.size, values.size)
            x, y = t[:length], values[:length]
            self._curves[position].setData(x, y)

            if variable.auto_limits:
                lower, upper = auto_limits(y, variable.ymin, variable.ymax)
                if (lower, upper) != (variable.ymin, variable.ymax):
                    variable.ymin, variable.ymax = lower, upper
                    self._apply_range(position, lower, upper)

            self._place_label(position, x, y)

        if self.template is not None and t[-1] > self.template.tend:
            # The window follows the run rather than cutting it off.
            self.set_x_range(self.template.tstart, float(t[-1]))

    def _place_label(self, position: int, x: np.ndarray, y: np.ndarray) -> None:
        finite = np.isfinite(y)
        if not finite.any():
            self._labels[position].hide()
            return
        last = int(np.flatnonzero(finite)[-1])
        offset = 0.0
        if self.template is not None:
            span = max(float(x[-1]) - float(x[0]), 1e-9)
            offset = span * self.template.flaglength
        self._labels[position].setPos(float(x[last]) + offset, float(y[last]))
        self._labels[position].show()

    def set_x_range(self, start: float, end: float) -> None:
        """The time axis picks its own ticks.

        The y-axes get a fixed number of divisions because their limits are
        the user's and the scales have to be readable across. The time axis
        grows with the run, and forcing axisxtick divisions onto a range of
        0 to 18 h gives ticks at 3.6 h — pyqtgraph's own choice of round
        numbers is better here.
        """
        if self.main_view is None:
            return
        self.main_view.setXRange(start, end, padding=0)

    def set_y_range(self, name: str, lower: float, upper: float) -> None:
        for position, variable in enumerate(self._variables):
            if variable.name == name:
                variable.ymin, variable.ymax = lower, upper
                self._apply_range(position, lower, upper)
                return

    # ---------------------------------------------------------- layout --

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """sigResized alone is not enough.

        An extra ViewBox is not in the layout — it only lives in the scene —
        so nothing moves it when the widget changes size. Without this the
        curves are drawn through a stale transform.
        """
        super().resizeEvent(event)
        self._resize_views()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Last chance before anything is drawn with a stale transform."""
        self._resize_views()
        super().paintEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._resize_views()

    def _resize_views(self) -> None:
        """Put every extra ViewBox exactly on top of the main one.

        getattr, not self.main_view: pyqtgraph's GraphicsView calls
        resizeEvent from inside its own __init__, before this class has set
        any attribute at all.
        """
        main = getattr(self, "main_view", None)
        if main is None:
            return
        geometry = main.sceneBoundingRect()
        for view in self._views[1:]:
            view.setGeometry(geometry)
            view.linkedViewChanged(main, view.XAxis)
