"""How a value is written down — decimals, and the names of the modes.

Pure functions, no Qt: `gui/values.py` is what the phase panels, the parameter
dialogs and the log all read a number through, and it should be checkable
without building a window.
"""

import math

import pytest

from biofermentation.gui.values import (
    decimals_for,
    format_number,
    format_value,
    mode_table,
    modes_of,
)

MODES = [
    {"parametername": "Mode_pO2", "value": 0, "mode": "Manual"},
    {"parametername": "Mode_pO2", "value": 1, "mode": "pO2-Agitation"},
    {"parametername": "Mode_pO2", "value": 3, "mode": "pO2-Gasmix"},
    {"parametername": "Mode_pH", "value": 0, "mode": "Manual"},
    {"parametername": "Mode_pH", "value": 1, "mode": "Auto"},
]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2.5, "2.500"),
        (14.0, "14.000"),
        (0.0, "0.000"),
        (-1.5, "-1.500"),
        # More than three where the number has more: a 0.005 h timer read as
        # "0.00 h" at two decimals, which is a condition that never fires.
        (0.005, "0.005"),
        (0.0625, "0.0625"),
        (1e-05, "0.00001"),
        # Not significant digits — the places after the point are what count.
        (1234.5678, "1234.5678"),
    ],
)
def test_a_number_keeps_the_decimals_it_has(value, expected):
    assert format_number(value) == expected


def test_the_floor_is_three_and_the_cap_holds():
    assert format_number(1.0, floor=0) == "1"
    assert format_number(1 / 3).count("3") <= 12, "the cap stops an endless expansion"
    assert format_number(float("nan")) == "nan"
    assert math.isfinite(float(format_number(2.5)))


def test_decimals_for_still_answers_in_places_not_digits():
    """The spin boxes are built on this one; 1e-05 needs eight."""
    assert decimals_for(1e-05) == 8
    assert decimals_for(1.0) == 4
    assert decimals_for(0.0) == 4


def test_the_mode_table_groups_by_parameter():
    table = mode_table(MODES)
    assert table["Mode_pO2"] == {0: "Manual", 1: "pO2-Agitation", 3: "pO2-Gasmix"}
    assert modes_of("Mode_pH", table) == {0: "Manual", 1: "Auto"}
    assert modes_of("pHw", table) == {}
    assert mode_table(None) == {}


def test_a_mode_is_written_by_name_and_everything_else_by_number():
    table = mode_table(MODES)
    assert format_value("Mode_pO2", 3, table) == "pO2-Gasmix"
    assert format_value("Mode_pO2", 3.0, table) == "pO2-Gasmix"
    assert format_value("Mode_pH", 0, table) == "Manual"
    assert format_value("pHw", 6.8, table) == "6.800"
    assert format_value("pHw", None, table) == "—"


def test_a_mode_number_the_database_does_not_name_stays_a_number():
    """A guess would be worse than the raw value: it would read as a fact."""
    assert format_value("Mode_pO2", 4, mode_table(MODES)) == "4"
