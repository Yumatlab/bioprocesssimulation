"""Zero on a division: scales with a negative part stay in step with the rest.

A deviation from calculateYLimits, display only (db/plots.aligned_limits).
Kept in a file of its own; test_plots.py holds the user's own running work.
"""

import math

import numpy as np
import pytest

from biofermentation.db.plots import ROUND_STEPS, PlotTemplate, PlotVariable, aligned_limits
from biofermentation.db.plots import auto_limits as matlab_limits

CASES = [
    [-0.004, 0.43],  # µ just below zero after inoculation, as in the screenshot
    [-2.5, 8.0],
    [-7.3, 0.08],
    [-0.2, 0.43],
    [-0.0001, 450.0],
    [-30.0, 95.0],
    [-5.0, -1.0],
]


def test_the_screenshot_case_becomes_steps_of_an_eighth():
    """[-0.1, 0.5] had its ticks on 0, 0.12, ... and none at -0.1."""
    assert matlab_limits([-0.004, 0.43], 0, 1) == (-0.1, 0.5)
    assert aligned_limits([-0.004, 0.43], 0, 1, 5) == (-0.125, 0.5)


@pytest.mark.parametrize("values", CASES)
@pytest.mark.parametrize("divisions", [4, 5, 6])
def test_zero_falls_on_a_division_and_nothing_is_cut_off(values, divisions):
    lower, upper = aligned_limits(values, 0, 1, divisions)
    step = (upper - lower) / divisions
    # Zero is a whole number of steps above the lower limit ...
    assert -lower / step == pytest.approx(round(-lower / step), abs=1e-9)
    # ... the step is a round one ...
    mantissa = step / 10 ** math.floor(math.log10(step))
    assert any(mantissa == pytest.approx(r) for r in ROUND_STEPS), step
    # ... the data fits, and the top is never lower than calculateYLimits'.
    assert lower <= min(values)
    assert upper >= matlab_limits(values, 0, 1)[1] - 1e-12


@pytest.mark.parametrize("values", [[0, 3.2], [0.5, 80.0], [np.nan, np.nan], []])
def test_without_a_negative_value_nothing_changes(values):
    assert aligned_limits(values, 0, 10, 5) == matlab_limits(values, 0, 10)


def _template() -> PlotTemplate:
    variables = []
    for index, (name, ymax) in enumerate((("NSt", 500.0), ("mu", 0.5))):
        variables.append(
            PlotVariable(
                variableID=index,
                name=name,
                shorttex=name,
                tex_unit="",
                selected=True,
                limit_type=1,  # automatic
                ymin=0.0,
                ymax=ymax,
                color=(0, 0, 0),
            )
        )
    template = PlotTemplate(templateID=0, tstart=0.0, tend=1.0, variables=variables)
    template.axisytick = 5.0
    return template


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_ticks_of_a_negative_scale_sit_at_the_heights_of_the_others(qapp):
    """What the screenshot showed: µ's ticks 40 px off those of N_St."""
    from biofermentation.gui.widgets.plot_view import MultiAxisPlot

    plot = MultiAxisPlot()
    template = _template()
    plot.set_template(template)
    assert all(variable.auto_limits for variable in plot._variables)
    t = np.linspace(0, 1, 200)
    mu = 0.43 * np.sin(np.pi * t) - 0.004
    plot.update_data(t, {"NSt": 450 + 0 * t, "mu": mu})

    heights = []
    for position, axis in enumerate(plot._axes):
        lower, upper = plot._views[position].viewRange()[1]
        ticks = [value for _, values in axis.tickValues(lower, upper, 400) for value in values]
        heights.append(sorted(round((value - lower) / (upper - lower), 9) for value in ticks))
    mu_position = next(i for i, v in enumerate(plot._variables) if v.name == "mu")
    assert plot._views[mu_position].viewRange()[1] == pytest.approx([-0.125, 0.5])
    assert heights[0] == heights[1] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
