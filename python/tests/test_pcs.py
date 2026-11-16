"""Building blocks of the PCS tab — PCS plan, phase 1.

Each element on its own, headless: what a valve reports and when, what a gauge
shows for which volume, how a pipe differs live and idle. The wiring and the
layout file are tests/test_pcs_specs.py.
"""

import math

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from biofermentation.gui.pcs_specs import MEDIA, SYMBOLS
from biofermentation.gui.widgets.indicators import ALARM_COLORS
from biofermentation.gui.widgets.pcs_elements import (
    ALARM_LEVELS,
    MEDIUM_COLORS,
    TankGauge,
    ValveButton,
    VesselWidget,
    arrow_anchor,
    fill_fraction,
    pipe_style,
)


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


def _reports(valve: ValveButton) -> list[bool]:
    seen: list[bool] = []
    valve.toggled.connect(seen.append)
    return seen


# ------------------------------------------------------------ valves --


def test_a_loaded_valve_neither_moves_nor_reports(qapp):
    valve = ValveButton("Acid")
    seen = _reports(valve)
    valve.set_state_now(True)
    assert valve.isChecked()
    valve.set_state_now(False)
    assert not valve.isChecked()
    assert seen == []


def test_clicking_a_valve_reports_it_once(qapp):
    valve = ValveButton("Acid")
    seen = _reports(valve)
    valve.click()
    assert seen == [True]
    valve.click()
    assert seen == [True, False]


def test_a_disabled_valve_does_not_report(qapp):
    valve = ValveButton("Acid")
    seen = _reports(valve)
    valve.set_locked("pH-Control")
    valve.click()
    assert seen == []
    assert not valve.isChecked()


def test_a_locked_valve_names_its_owner_and_shows_the_flow(qapp):
    """Locked, the symbol follows the flow: loading still works."""
    valve = ValveButton("Acid", symbol="pump")
    valve.set_locked("pH-Control")
    assert not valve.isEnabled()
    assert "pH-Control" in valve.toolTip()
    valve.set_state_now(True)
    assert valve.isChecked()

    valve.set_locked(None)
    assert valve.isEnabled()
    assert valve.toolTip() == "Acid"
    assert valve.owner() is None


def test_every_symbol_of_the_specification_can_be_drawn(qapp):
    for symbol in SYMBOLS:
        assert ValveButton("Element", symbol=symbol).symbol == symbol
    with pytest.raises(ValueError):
        ValveButton("Tap", symbol="tap")


def test_a_locked_element_says_so_in_more_than_colour(qapp):
    """Paler, and tagged "A" — the tag is drawn whenever there is an owner."""
    valve = ValveButton("Air", symbol="control_valve")
    valve.set_locked("pO2-Control")
    assert valve.owner() == "pO2-Control"
    valve.resize(valve.sizeHint())
    assert not valve.grab().isNull()


# ------------------------------------------------------------ levels --


def test_a_gauge_clamps_its_level_between_empty_and_full(qapp):
    gauge = TankGauge("Reservoir 1")
    gauge.set_volume(2.5, 5.0)
    assert gauge.level() == 0.5
    gauge.set_volume(7.5, 5.0)
    assert gauge.level() == 1.0
    assert "150 %" in gauge.text()  # the numbers stay true
    gauge.set_volume(-1.0, 5.0)
    assert gauge.level() == 0.0


def test_a_gauge_without_a_maximum_shows_no_level(qapp):
    gauge = TankGauge("Antifoam")
    for volume, maximum in [(None, None), (2.0, None), (2.0, 0.0), (math.nan, 5.0)]:
        gauge.set_volume(volume, maximum)
        assert gauge.level() is None, (volume, maximum)
        assert gauge.text() == ""


def test_the_vessel_marks_its_minimum_against_its_maximum(qapp):
    vessel = VesselWidget()
    vessel.set_volume(1.0, 2.0, 0.5)
    assert vessel.level() == 0.5
    assert vessel.minimum_mark() == 0.25
    vessel.set_volume(1.0, 2.0)
    assert vessel.minimum_mark() is None


def test_the_harvest_outlet_sits_under_the_lowest_point(qapp):
    """The sheet starts the harvest pipe here: under the lowest point of the
    dish, so that the vessel drains completely."""
    vessel = VesselWidget()
    vessel.resize(160, 230)
    outlet = vessel.outlet()
    assert outlet.y() == vessel.rect().bottom()
    assert outlet.x() == pytest.approx(vessel.width() / 2)


def test_the_gas_lance_comes_in_through_the_lid(qapp):
    """Left of the shaft, at the top edge, where the aeration pipe ends."""
    vessel = VesselWidget()
    vessel.resize(160, 230)
    inlet = vessel.gas_inlet()
    assert inlet.y() == vessel.rect().top()
    assert 0 < inlet.x() < vessel.width() / 2
    assert not vessel.grab().isNull()


def test_the_stirrer_follows_what_it_is_told(qapp):
    vessel = VesselWidget()
    assert not vessel.stirring()
    vessel.set_stirring(True)
    assert vessel.stirring()


def test_level_text_fits_under_a_narrow_bottle():
    from biofermentation.gui.widgets.pcs_elements import level_text

    assert level_text(0.787, 1.0, "l") == "0.79 l · 79 %"
    assert level_text(5.0, 5.0, "l") == "5 l · 100 %"
    assert level_text(10.25, 11.0, "l") == "10.2 l · 93 %"
    assert level_text(None, 5.0, "l") == ""


def test_fill_fraction_needs_a_positive_finite_maximum():
    assert fill_fraction(1.0, 4.0) == 0.25
    assert fill_fraction(1.0, -4.0) is None
    assert fill_fraction(1.0, math.inf) is None


# ------------------------------------------------------------ alarms --


def _elements():
    symbols = [ValveButton(symbol, symbol=symbol) for symbol in SYMBOLS]
    return [*symbols, TankGauge("Acid"), VesselWidget()]


def test_the_motor_is_not_smaller_than_the_pump(qapp):
    motor = ValveButton("Stirrer", symbol="motor")
    pump = ValveButton("Acid", symbol="pump")
    assert motor.width() >= pump.width()


def test_every_element_takes_an_alarm_level_and_refuses_others(qapp):
    for element in _elements():
        for level in ALARM_LEVELS:
            element.set_alarm(level)
            assert element.alarm() == level
        with pytest.raises(ValueError):
            element.set_alarm("fire")


# ------------------------------------------------------------- pipes --


def test_every_medium_has_a_colour():
    assert set(MEDIUM_COLORS) == set(MEDIA)


def test_no_medium_can_be_mistaken_for_an_alarm():
    """Saturated colour belongs to alarms (ISA-101); a medium is muted."""
    for medium, color in MEDIUM_COLORS.items():
        assert color.hsvSaturationF() <= 0.45, medium
    for level, color in ALARM_COLORS.items():
        # A clear gap to the media, not a particular red: ALARM_ALARM is 0.78.
        assert color.hsvSaturationF() >= 0.7, level


def test_a_live_pipe_differs_from_an_idle_one_in_more_than_colour():
    for medium in MEDIA:
        _, live_width, live_arrow = pipe_style(medium, True)
        _, idle_width, idle_arrow = pipe_style(medium, False)
        assert live_width > idle_width
        assert live_arrow and not idle_arrow
    with pytest.raises(ValueError):
        pipe_style("beer", True)


def test_the_arrow_sits_half_way_along_the_pipe():
    (x, y), angle = arrow_anchor([(0, 0), (30, 0), (30, 10)])
    assert (x, y) == (20, 0)
    assert angle == 0

    (x, y), angle = arrow_anchor([(0, 0), (0, 0), (0, 10)])
    assert (x, y) == (0, 5)
    assert angle == pytest.approx(math.pi / 2)

    assert arrow_anchor([(3, 3), (3, 3)]) is None

    (x, y), _ = arrow_anchor([(0, 0), (40, 0)], share=0.75)
    assert (x, y) == (30, 0)


# ----------------------------------------------------------- drawing --


@pytest.mark.parametrize("level", ALARM_LEVELS)
def test_every_element_draws_in_every_state(qapp, level):
    """Nothing to compare pixels against yet — this catches a paintEvent that raises."""
    for element in _elements():
        element.set_alarm(level)
        if isinstance(element, ValveButton):
            element.set_state_now(True)
        else:
            element.set_volume(1.0, 2.0)
        element.resize(element.sizeHint())
        assert not element.grab().isNull()


def test_no_element_asks_for_a_wide_window(qapp):
    """The sheet scales with the window; no element may push it wider."""
    for element in _elements():
        assert element.minimumSizeHint().width() <= 120
        assert element.minimumWidth() <= 120
