"""The multi-axis live plot (plan section 6.1).

pyqtgraph draws one PlotItem with its own ViewBox. Everything past the first
curve needs a ViewBox of its own, linked to the same x-axis and given an
AxisItem placed further to the left — that is the direct counterpart to the
stacked y-axes of the MATLAB FigureApp.

Two things the original does that are easy to lose:

  * The axes are ordered by their upper limit, so the scales do not cross.
    PlotTemplate.selected() does that sorting.
  * Every curve carries its name at its right end, drawn in the curve's own
    colour. Without it a plot with six scales is unreadable.
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QWidget

from ...db.plots import PlotTemplate, PlotVariable, auto_limits
from .tex import tex_to_html

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")


class MultiAxisPlot(pg.GraphicsLayoutWidget):
    """One x-axis, one y-axis per variable, all sharing the same time base."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.template: PlotTemplate | None = None
        self.plot_item: pg.PlotItem | None = None

        # ViewBox, AxisItem, curve and end label, one set per variable.
        self._views: list[pg.ViewBox] = []
        self._axes: list[pg.AxisItem] = []
        self._curves: list[pg.PlotDataItem] = []
        self._labels: list[pg.TextItem] = []
        self._variables: list[PlotVariable] = []
        self._placeholders: list[pg.AxisItem] = []

    # ------------------------------------------------------------ build --

    def set_template(self, template: PlotTemplate) -> None:
        """Rebuild for a template. Like the phase grid: throw away, build again.

        The number of extra axes decides the layout, so the whole thing is
        built here rather than patched. PlotItem keeps its own axis in column
        0 and its ViewBox in column 1; an extra axis cannot go there, and
        QGraphicsGridLayout cannot insert a column in front. So the axes are
        placed in this widget's own layout instead, outermost first, and the
        plot takes the last column.
        """
        self.template = template
        self._clear()

        variables = template.selected()
        self._variables = variables
        extra = max(0, len(variables) - 1)

        # Outermost axis at column 0; variable[0] keeps the plot's own axis.
        placeholders = [pg.AxisItem("left") for _ in range(extra)]
        for column, axis in enumerate(placeholders):
            self.addItem(axis, row=0, col=column)

        self.plot_item = self.addPlot(row=0, col=extra)
        self.plot_item.showGrid(x=True, y=True, alpha=0.25)
        self.plot_item.setMenuEnabled(False)
        self.plot_item.vb.sigResized.connect(self._resize_views)
        self._placeholders = placeholders

        if not variables:
            return

        # plot_templateTab.axisxunit stores the brackets ("[h]"), so they are
        # stripped before being put back — otherwise the label reads [[h]].
        unit = template.axisxunit.strip("[] ")
        self.plot_item.getAxis("bottom").setLabel(
            f"{template.axisxlabel} [{unit}]" if unit else template.axisxlabel
        )
        if template.show_title and template.plottitle:
            self.plot_item.setTitle(template.plottitle, size=f"{template.graphtitlefontsize:.0f}pt")
        self.plot_item.setXRange(template.tstart, template.tend, padding=0)

        for position, variable in enumerate(variables):
            self._add_variable(position, variable)
        self._resize_views()

    def _add_variable(self, position: int, variable: PlotVariable) -> None:
        color = QColor(*variable.color)
        pen = QPen(color)
        pen.setWidthF(self.template.graphlinewidth if self.template else 1.5)
        # Cosmetic, or the width is taken in data units and scaled by the
        # ViewBox transform — a 1.5 pt line then comes out as a 50 px band and
        # every curve looks like a filled area. pg.mkPen sets this; a QPen
        # built by hand does not.
        pen.setCosmetic(True)
        if variable.dash_pattern:
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([float(x) for x in variable.dash_pattern])

        if position == 0:
            # The first variable owns the plot's own ViewBox and axis, so it
            # sits closest to the plot area — the innermost scale.
            view = self.plot_item.vb
            axis = self.plot_item.getAxis("left")
            curve = self.plot_item.plot([], [], pen=pen)
        else:
            view = pg.ViewBox()
            # Ascending ymax means later variables belong further out.
            axis = self._placeholders[len(self._placeholders) - position]
            self.plot_item.scene().addItem(view)
            axis.linkToView(view)
            view.setXLink(self.plot_item.vb)
            curve = pg.PlotDataItem([], [], pen=pen)
            view.addItem(curve)

        axis.setPen(QPen(color))
        axis.setTextPen(QPen(color))
        unit = tex_to_html(variable.tex_unit) if variable.tex_unit else ""
        caption = tex_to_html(variable.label())
        axis.setLabel(f"{caption} [{unit}]" if unit else caption)
        view.setYRange(variable.ymin, variable.ymax, padding=0)
        view.enableAutoRange(axis="y", enable=False)

        # The end label carries the curve's colour, so six scales stay
        # readable — plotFlags of the original.
        caption_html = f'<span style="color:{color.name()}">{caption}</span>'
        label = pg.TextItem(html=caption_html, anchor=(0, 0.5))
        font = QFont()
        font.setPointSizeF(self.template.flagfontsize * 0.6 if self.template else 10)
        label.setFont(font)
        view.addItem(label)
        label.hide()

        self._views.append(view)
        self._axes.append(axis)
        self._curves.append(curve)
        self._labels.append(label)

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
        self._placeholders = []
        # clear() takes the plot and every axis out of the layout at once.
        self.clear()
        self.plot_item = None

    # ------------------------------------------------------------- data --

    def update_data(self, t: np.ndarray, series: dict[str, np.ndarray]) -> None:
        """Redraw from the trimmed time series of the simulation state."""
        if not self._variables or t.size == 0 or self.plot_item is None:
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
                    self._views[position].setYRange(lower, upper, padding=0)

            self._place_label(position, x, y)

        if self.template is not None and t[-1] > self.template.tend:
            # The window follows the run rather than cutting it off.
            self.plot_item.setXRange(self.template.tstart, float(t[-1]), padding=0.02)

    def _place_label(self, position: int, x: np.ndarray, y: np.ndarray) -> None:
        """The curve's name at its right end — plotFlags of the original."""
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
        if self.plot_item is not None:
            self.plot_item.setXRange(start, end, padding=0)

    def set_y_range(self, name: str, lower: float, upper: float) -> None:
        for position, variable in enumerate(self._variables):
            if variable.name == name:
                variable.ymin, variable.ymax = lower, upper
                self._views[position].setYRange(lower, upper, padding=0)
                return

    # ---------------------------------------------------------- layout --

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """sigResized alone is not enough.

        An extra ViewBox is not in the layout — it only lives in the scene —
        so nothing moves it when the widget changes size. Without this the
        curves are drawn through a stale transform and come out as filled
        shapes rather than lines.
        """
        super().resizeEvent(event)
        self._resize_views()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._resize_views()

    def _resize_views(self) -> None:
        """Extra ViewBoxes do not follow the plot on their own.

        getattr, not self.plot_item: pyqtgraph's GraphicsView calls
        resizeEvent from inside its own __init__, before this class has set
        any attribute at all.
        """
        if getattr(self, "plot_item", None) is None:
            return
        geometry = self.plot_item.vb.sceneBoundingRect()
        for view in self._views[1:]:
            view.setGeometry(geometry)
            view.linkedViewChanged(self.plot_item.vb, view.XAxis)
