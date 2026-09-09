"""Plot templates (plan section 6.2).

plot_templateTab and plot_variableTab are taken over unchanged — they are
configuration, with nothing MATLAB-specific in them. This module reads a
template into objects and writes it back.

limit_type is the one field whose meaning is not obvious from its name:
1 means automatic, and the axis limits grow when data leaves the plot area;
0 means the ymin and ymax stored next to it are used as they are. The
checkbox in the window is labelled "Auto" and is ticked for 1.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path

from .connection import get_connection

# plot_linestyleTab stores MATLAB's symbols; Qt wants a dash pattern.
LINE_STYLES = {
    "-": None,  # solid
    "--": (6, 4),
    "-.-": (6, 3, 2, 3),
    ":": (2, 3),
}


@dataclass
class PlotVariable:
    """One row of plot_variableTab, joined with what it needs to be drawn."""

    variableID: int
    name: str
    shorttex: str | None = None
    longtex: str | None = None
    tex_unit: str | None = None
    selected: bool = False
    limit_type: int = 1
    ymin: float = 0.0
    ymax: float = 10.0
    decimal: str = "%.2f"
    colorID: int = 1
    color: tuple[int, int, int] = (0, 0, 0)
    linestyleID: int = 1
    linestyle: str = "-"
    plot_variableID: int | None = None

    @property
    def auto_limits(self) -> bool:
        return self.limit_type == 1

    @property
    def dash_pattern(self) -> tuple[int, ...] | None:
        return LINE_STYLES.get(self.linestyle)

    def label(self) -> str:
        """Name and unit, as the axis caption shows them."""
        return self.shorttex or self.name

    def format(self, value: float) -> str:
        try:
            return self.decimal % value
        except (TypeError, ValueError):
            return f"{value:g}"


@dataclass
class PlotTemplate:
    """A row of plot_templateTab with its variables."""

    templateID: int
    name: str = "PlotProfile"
    description: str = ""
    plottitle: str = ""
    titlebool: float = 1.0
    graphlinewidth: float = 1.5
    graphvlinewidth: float = 2.0
    graphfontsize: float = 12.0
    graphtitlefontsize: float = 18.0
    axisxlabel: str = "Process time"
    axisxunit: str = "h"
    axisxtick: float = 6.0
    axisytick: float = 5.0
    axisyoffset: float = 50.0
    axislabelfontsize: float = 12.0
    axislinewidth: float = 1.75
    flaglength: float = 0.04
    flagangle: float = 45.0
    flaglinewidth: float = 1.25
    flagfontsize: float = 16.0
    refreshrate: float = 2.0
    tstart: float = 0.0
    tend: float = 5.0
    variables: list[PlotVariable] = field(default_factory=list)

    @property
    def show_title(self) -> bool:
        return bool(self.titlebool)

    def selected(self) -> list[PlotVariable]:
        """The drawn variables, innermost axis first.

        sortVariables of the original orders them by ymax, so the axis with
        the largest range ends up outermost and the scales do not cross.
        """
        return sorted(
            (variable for variable in self.variables if variable.selected),
            key=lambda variable: variable.ymax,
        )


def list_plot_templates(db_path: Path | str) -> list[dict]:
    with get_connection(db_path, readonly=True) as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT templateID, name, description, last_changed FROM plot_templateTab "
                "ORDER BY templateID"
            )
        ]


def load_plot_template(db_path: Path | str, template_id: int) -> PlotTemplate:
    """One template and every variable it knows about, selected or not."""
    with get_connection(db_path, readonly=True) as conn:
        row = conn.execute(
            "SELECT * FROM plot_templateTab WHERE templateID = ?", (template_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no plot template with templateID {template_id}")

        # sqlite3.Row has no membership test of its own, so the column names
        # are taken out once and intersected with the dataclass fields.
        known = {key for key in PlotTemplate.__dataclass_fields__ if key != "variables"}
        columns = set(row.keys())
        template = PlotTemplate(**{key: row[key] for key in known & columns})

        template.variables = [
            PlotVariable(
                variableID=item["variableID"],
                name=item["name"],
                shorttex=item["shorttex"],
                longtex=item["longtex"],
                tex_unit=item["tex_unit"],
                selected=bool(item["selected_axis"]),
                limit_type=item["limit_type"],
                ymin=item["ymin"],
                ymax=item["ymax"],
                decimal=item["decimal_symbol"] or "%.2f",
                colorID=item["colorID"],
                color=_rgb(item["R"], item["G"], item["B"]),
                linestyleID=item["linestyleID"],
                linestyle=item["linestyle_symbol"] or "-",
                plot_variableID=item["plot_variableID"],
            )
            for item in conn.execute(
                """
                SELECT pv.plot_variableID, pv.variableID, pv.selected_axis, pv.limit_type,
                       pv.ymin, pv.ymax, pv.colorID, pv.linestyleID,
                       v.name, v.shorttex, v.longtex, v.tex_unit,
                       d.decimal_symbol, c.R, c.G, c.B, l.linestyle_symbol
                  FROM plot_variableTab pv
                  JOIN variableTab v ON v.variableID = pv.variableID
                  LEFT JOIN plot_decimalTab d ON d.decimalID = pv.decimalID
                  LEFT JOIN plot_colorTab c ON c.colorID = pv.colorID
                  LEFT JOIN plot_linestyleTab l ON l.linestyleID = pv.linestyleID
                 WHERE pv.templateID = ?
                 ORDER BY pv.variableID
                """,
                (template_id,),
            )
        ]
    return template


def save_plot_template(db_path: Path | str, template: PlotTemplate) -> int:
    """Write the template and its variables back. One transaction."""
    from datetime import datetime

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE plot_templateTab
               SET name = ?, description = ?, plottitle = ?, titlebool = ?,
                   graphlinewidth = ?, graphfontsize = ?, axisxlabel = ?, axisxunit = ?,
                   axisxtick = ?, axisytick = ?, axislabelfontsize = ?,
                   flaglength = ?, flagangle = ?, flagfontsize = ?,
                   refreshrate = ?, tstart = ?, tend = ?, last_changed = ?
             WHERE templateID = ?
            """,
            (
                template.name,
                template.description,
                template.plottitle,
                template.titlebool,
                template.graphlinewidth,
                template.graphfontsize,
                template.axisxlabel,
                template.axisxunit,
                template.axisxtick,
                template.axisytick,
                template.axislabelfontsize,
                template.flaglength,
                template.flagangle,
                template.flagfontsize,
                template.refreshrate,
                template.tstart,
                template.tend,
                datetime.now().strftime("%Y.%m.%d %H:%M:%S"),
                template.templateID,
            ),
        )
        conn.executemany(
            """
            UPDATE plot_variableTab
               SET selected_axis = ?, limit_type = ?, ymin = ?, ymax = ?,
                   colorID = ?, linestyleID = ?
             WHERE plot_variableID = ?
            """,
            [
                (
                    int(variable.selected),
                    variable.limit_type,
                    variable.ymin,
                    variable.ymax,
                    variable.colorID,
                    variable.linestyleID,
                    variable.plot_variableID,
                )
                for variable in template.variables
                if variable.plot_variableID is not None
            ],
        )
    return template.templateID


def _rgb(r, g, b) -> tuple[int, int, int]:
    """plot_colorTab stores 0..1 floats; Qt wants 0..255."""
    return tuple(
        max(0, min(255, round((component or 0.0) * 255))) for component in (r, g, b)
    )


def auto_limits(values, ymin: float, ymax: float) -> tuple[float, float]:
    """The automatic axis limits of calculateYLimits, one to one.

    Rounds up to the next 2, 5 or 10 times a power of ten, and only shrinks
    once the data has dropped below a tenth of the current maximum — so an
    axis does not twitch on every step.
    """
    import numpy as np

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return ymin, ymax

    lowest = float(finite.min())
    highest = float(finite.max())

    # Only stretch by half once the data has dropped below a tenth of the
    # current maximum, so the axis does not twitch on every step.
    upper = (
        _round_to_nearest(highest * 1.5)
        if highest < 0.1 * ymax
        else _round_to_nearest(highest)
    )

    if lowest >= 0:
        lower = 0.0
    else:
        scale = 10 ** math.floor(math.log10(upper)) if upper > 0 else 1.0
        lower = -math.ceil(abs(lowest) / scale) * scale

    return lower, upper


def _round_to_nearest(value: float) -> float:
    if value <= 0.0001:
        return 0.0001
    scale = 10 ** math.floor(math.log10(value))
    scaled = value / scale
    if scaled <= 2:
        return 2 * scale
    if scaled <= 5:
        return 5 * scale
    return 10 * scale
