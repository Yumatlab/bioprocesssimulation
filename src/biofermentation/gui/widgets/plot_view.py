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
    row 1   axis[n-1] … axis[1] axis[0] | ViewBox
    row 2                               | bottom axis

Every y-axis shares row 1 with the ViewBox and is therefore exactly as tall
as the plot area. The bottom axis sits under the ViewBox alone.

The tick spacing is forced to the template's axisytick on every axis, so the
divisions of all scales line up horizontally — the way they do in the MATLAB
figure. Without that each axis picks its own spacing and the gridlines of one
scale fall between those of the next.
"""

from typing import ClassVar

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QWidget

from ...db.plots import PlotTemplate, PlotVariable, auto_limits
from .tex import tex_to_html

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

# Positive length points away from the plot area — ticks on the outside.
TICK_LENGTH = 7


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


class MultiAxisPlot(pg.GraphicsLayoutWidget):
    """One x-axis, one y-axis per variable, all sharing the same time base."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.template: PlotTemplate | None = None
        self.main_view: pg.ViewBox | None = None
        self.bottom_axis: pg.AxisItem | None = None
        self.title_item: pg.LabelItem | None = None

        self._views: list[pg.ViewBox] = []
        self._axes: list[pg.AxisItem] = []
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
        self.addItem(self.main_view, row=1, col=count)
        self.ci.layout.setColumnStretchFactor(count, 1)

        unit = template.axisxunit.strip("[] ")
        self.bottom_axis = OutwardAxis("bottom")
        self.bottom_axis.linkToView(self.main_view)
        self.bottom_axis.enableAutoSIPrefix(False)
        self.bottom_axis.setStyle(tickLength=TICK_LENGTH)
        bottom_pen = QPen(QColor("k"))
        bottom_pen.setWidthF(template.axislinewidth)
        bottom_pen.setCosmetic(True)
        self.bottom_axis.setPen(bottom_pen)
        bottom_font = QFont()
        bottom_font.setPointSizeF(template.graphfontsize)
        self.bottom_axis.setTickFont(bottom_font)
        self.bottom_axis.setLabel(
            f"{template.axisxlabel} [{unit}]" if unit else template.axisxlabel,
            **{"font-size": f"{template.axislabelfontsize:.0f}pt"},
        )
        self.addItem(self.bottom_axis, row=2, col=count)

        # Column 0 is the outermost axis, so the innermost variable — the one
        # with the smallest range — ends up next to the plot area.
        for position, variable in enumerate(variables):
            self._add_variable(position, count - 1 - position, variable)

        self.set_x_range(template.tstart, template.tend)
        self._resize_views()

    def _add_variable(self, position: int, column: int, variable: PlotVariable) -> None:
        color = QColor(*variable.color)
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
        tick_font = QFont()
        tick_font.setPointSizeF(self.template.graphfontsize if self.template else 12.0)
        axis.setTickFont(tick_font)
        # No "(x0.001)" over the axis; the original prints the numbers as
        # they are, and the unit is already in the caption.
        axis.enableAutoSIPrefix(False)
        # Ticks outside the plot area, as in the original. pyqtgraph counts a
        # positive length towards the labels, which for a left axis is out.
        axis.setStyle(tickLength=TICK_LENGTH)
        caption = tex_to_html(variable.label())
        rendered_unit = tex_to_html(variable.tex_unit) if variable.tex_unit else ""
        size = f"{self.template.axislabelfontsize:.0f}pt" if self.template else "12pt"
        axis.setLabel(
            f"{caption} [{rendered_unit}]" if rendered_unit else caption,
            **{"font-size": size},
        )
        self.addItem(axis, row=1, col=column)

        curve = pg.PlotDataItem([], [], pen=pen)
        view.addItem(curve)

        # The curve's name at its right end, in its own colour — plotFlags of
        # the original. With six scales the plot is unreadable without it.
        label = pg.TextItem(
            html=f'<span style="color:{color.name()}">{caption}</span>', anchor=(0, 0.5)
        )
        font = QFont()
        font.setPointSizeF(self.template.flagfontsize * 0.6 if self.template else 10)
        label.setFont(font)
        # ignoreBounds: the label sits past the last data point, and letting
        # it count towards the range would stretch the axis every step.
        view.addItem(label, ignoreBounds=True)
        label.hide()

        self._views.append(view)
        self._axes.append(axis)
        self._curves.append(curve)
        self._labels.append(label)
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
