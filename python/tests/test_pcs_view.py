"""The PCS tab in the control window — PCS plan, phases 3 and 4.

Built on real projects: 716 (E. coli, one reservoir) and 519 (Pichia, two).
A short run is computed on the window's own state, then the tab is asked
what it shows, and that is held against v — the same numbers the Variable
Pool reads.
"""

import math
import shutil
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from biofermentation.control import PhaseAutomaton
from biofermentation.core.runner import load_project_state, run_steps
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import load_phases
from biofermentation.gui.pcs_specs import REACTOR
from biofermentation.gui.widgets.pcs_elements import ValveButton, arrow_anchor
from biofermentation.gui.widgets.pcs_view import FLOW_EPSILON, read_value
from biofermentation.gui.windows import ControlWindow
from biofermentation.organisms import discover_organisms

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
ECOLI_PROJECT = 716
PICHIA_PROJECT = 519


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


def _window(db_copy: Path, project: int, **parameters) -> ControlWindow:
    discover_organisms()
    setup = load_phases(db_copy, project)
    state, organism = load_project_state(db_copy, project)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    for name, value in parameters.items():
        state.p[name] = value
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    return ControlWindow(setup, runner, db_copy)


def _run(window: ControlWindow, steps: int = 30) -> None:
    """Compute on the window's state, then show the PCS tab and refresh it."""
    state = window.runner.state
    run_steps(state, window.runner.organism, steps)
    window.tabs.setCurrentWidget(window.pcs_view)
    window.load_panels()
    window.refresh()


@pytest.fixture
def coli(qapp, db_copy):
    return _window(db_copy, ECOLI_PROJECT, f_feed=1.0, Mode_feed=0.0)


# --------------------------------------------------------- the tab --


def test_the_pcs_tab_sits_right_after_control_options(coli):
    assert coli.tabs.tabText(0) == "Control Options"
    assert coli.tabs.tabText(1) == "PCS"
    assert coli.pages["PCS"] is coli.pcs_view


def test_the_pcs_tab_is_built_even_when_hidden(qapp, db_copy, monkeypatch):
    from biofermentation.gui.settings import Settings
    from biofermentation.gui.windows import control_app

    monkeypatch.setattr(control_app, "load_settings", lambda: (Settings(hidden_tabs={"PCS"}), ""))
    window = _window(db_copy, ECOLI_PROJECT)
    titles = {window.tabs.tabText(index) for index in range(window.tabs.count())}
    assert "PCS" not in titles
    assert window.pages["PCS"] is window.pcs_view
    window.load_panels()  # reads into the hidden sheet without trouble


def test_only_the_visible_pcs_tab_is_refreshed(coli, monkeypatch):
    calls = []
    monkeypatch.setattr(coli.pcs_view, "refresh", lambda *args, **kw: calls.append(1))

    coli.tabs.setCurrentWidget(coli.variable_pool)
    calls.clear()
    coli.refresh()
    assert calls == []

    coli.tabs.setCurrentWidget(coli.pcs_view)
    calls.clear()
    coli.refresh()
    assert calls == [1]


def test_the_pcs_tab_does_not_widen_the_window(coli):
    """The existing width test measures every tab; this names the new one."""
    assert coli.pcs_view.minimumSizeHint().width() <= 1440
    assert coli.minimumSizeHint().width() <= 1440


# ------------------------------------------------------- operating --


def test_an_element_is_operable_exactly_when_the_operator_owns_it(coli):
    _run(coli)
    view = coli.pcs_view
    for valve in view.spec.valves:
        button = view.element(valve.element)
        assert button.isEnabled() == (view.owners[valve.element] is None), valve.element
    assert view.element("feed1_pump").isEnabled()  # Mode_pO2 = 1, no feed phase
    assert not view.element("acid_pump").isEnabled()  # pH control is automatic


def test_a_valve_click_goes_through_the_guard(coli, monkeypatch):
    """The sheet has no way into p of its own."""
    _run(coli)
    seen = []
    original = coli.runner.editing

    def watched():
        seen.append("guarded")
        return original()

    monkeypatch.setattr(coli.runner, "editing", watched)
    assert coli.runner.state.p["f_feed"] == 1
    coli.pcs_view.element("feed1_pump").click()

    assert seen == ["guarded"]
    assert coli.runner.state.p["f_feed"] == 0


def test_a_valve_click_is_logged_as_a_parameter_change(coli):
    from biofermentation.gui.widgets.log_view import PARAMETER_EVENT

    _run(coli)
    before = len(coli.log_view.entries)
    coli.pcs_view.element("feed1_pump").click()

    written = coli.log_view.entries[before:]
    assert len(written) == 1
    assert written[0].event_type == PARAMETER_EVENT
    assert "f_feed" in written[0].message


def test_a_valve_and_its_panel_switch_never_disagree(coli):
    """Both directions: sheet to panel, panel to sheet."""
    _run(coli)
    pump = coli.pcs_view.element("feed1_pump")
    switch = coli.panels["Feed Control"].switches["f_feed"]
    assert pump.isChecked() and switch.is_checked()

    pump.click()
    assert not pump.isChecked()
    assert not switch.is_checked()

    switch.switch.click()
    assert switch.is_checked()
    assert pump.isChecked()
    assert coli.runner.state.p["f_feed"] == 1


def test_a_panel_change_does_not_reload_the_panels(coli, monkeypatch):
    """A panel loaded after its own change would lose what is being typed."""
    _run(coli)
    calls = []
    monkeypatch.setattr(coli, "load_panels", lambda: calls.append(1))
    coli.panels["Feed Control"].switches["f_feed"].switch.click()
    assert calls == []


def test_a_mode_change_in_a_panel_hands_the_valves_over(coli):
    """pH to manual in the panel: acid and alkali become the operator's."""
    _run(coli)
    acid = coli.pcs_view.element("acid_pump")
    assert not acid.isEnabled()

    coli.runner.state.p["f_acid"] = 0.0
    coli._panel_changed("Mode_pH", 0.0)
    assert acid.isEnabled()
    assert coli.pcs_view.owners["acid_pump"] is None
    assert not acid.isChecked()  # shows its flag again, not the flow

    acid.click()
    assert coli.runner.state.p["f_acid"] == 1
    assert coli.panels["pH-Control"].switches["f_acid"].is_checked()


def test_a_phase_that_changes_a_mode_regreys_the_valves(coli):
    _run(coli)
    cooling = coli.pcs_view.element("cooling_valve")
    assert not cooling.isEnabled()  # temperature control is automatic in 716

    coli.runner.state.p["Mode_temp"] = 0.0  # what a parameter phase would do
    coli._phase_changed(0)
    assert cooling.isEnabled()

    coli.runner.state.p["Mode_temp"] = 1.0
    coli._phase_changed(0)
    assert not cooling.isEnabled()
    assert "Temperature-Control" in cooling.toolTip()


def test_a_feed_phase_takes_the_feed_pump(coli):
    """Exponential feed is set in a, not in p: load reads both."""
    _run(coli)
    pump = coli.pcs_view.element("feed1_pump")
    assert pump.isEnabled()
    coli.runner.state.a.switch_exp = True
    coli._phase_changed(0)
    assert not pump.isEnabled()
    assert "exponential feed" in pump.toolTip()


def test_a_locked_element_cannot_write(coli):
    _run(coli)
    before = dict(coli.runner.state.p)
    coli.pcs_view.element("acid_pump").click()
    assert dict(coli.runner.state.p) == before


def test_loading_reports_nothing(coli):
    _run(coli)
    seen = []
    coli.pcs_view.parameter_changed.connect(lambda *args: seen.append(args))
    coli.runner.state.p["f_feed"] = 0.0
    coli.load_panels()
    coli.refresh()
    assert seen == []
    assert not coli.pcs_view.element("feed1_pump").isChecked()


def test_the_tab_computes_nothing(coli):
    """Loading, refreshing and drawing leave p and v exactly as they were —
    which is why the reference run cannot depend on the tab."""
    _run(coli)
    state = coli.runner.state
    p_before = dict(state.p)
    v_before = {name: values.copy() for name, values in state.trimmed().items()}

    coli.load_panels()
    coli.refresh()
    coli.pcs_view.grab()

    assert dict(state.p) == p_before
    v_after = state.trimmed()
    assert v_after.keys() == v_before.keys()
    for name, values in v_before.items():
        assert np.array_equal(values, v_after[name], equal_nan=True), name


def test_a_click_changes_the_run_only_through_its_flag(qapp, db_copy):
    """Feed switched off on the sheet gives, bit for bit, the run of a state
    in which f_feed was set to 0 by hand at the same step."""
    clicked = _window(db_copy, ECOLI_PROJECT, f_feed=1.0, Mode_feed=0.0)
    _run(clicked, 20)
    clicked.pcs_view.element("feed1_pump").click()
    run_steps(clicked.runner.state, clicked.runner.organism, 20)

    by_hand = _window(db_copy, ECOLI_PROJECT, f_feed=1.0, Mode_feed=0.0)
    run_steps(by_hand.runner.state, by_hand.runner.organism, 20)
    by_hand.runner.state.p["f_feed"] = 0.0
    run_steps(by_hand.runner.state, by_hand.runner.organism, 20)

    first, second = clicked.runner.state.trimmed(), by_hand.runner.state.trimmed()
    assert first.keys() == second.keys()
    for name in first:
        assert np.array_equal(first[name], second[name], equal_nan=True), name


# ------------------------------------------------------ what it shows --


def test_a_pipe_is_live_exactly_when_its_flow_is(coli):
    """Feed on: the feed line flows and says so; feed off: it does not."""
    _run(coli)
    view = coli.pcs_view
    assert view.canvas.live["feed1_line"]
    assert view.canvas.flows["feed1_line"] == pytest.approx(coli.runner.state.p["FR1w"])

    coli.runner.state.p["f_feed"] = 0.0
    _run(coli)
    assert not view.canvas.live["feed1_line"]


@pytest.mark.parametrize("project", [ECOLI_PROJECT, PICHIA_PROJECT])
def test_every_pipe_follows_its_series(qapp, db_copy, project):
    window = _window(db_copy, project, f_feed=1.0, Mode_feed=0.0)
    _run(window)
    state = window.runner.state
    view = window.pcs_view
    for pipe in view.spec.pipes:
        value = read_value(pipe.flow, state)
        expected = value is not None and value > FLOW_EPSILON
        if pipe.counts_when is not None and not pipe.counts_when.holds(state.p, state.a):
            expected = False
        assert view.canvas.live[pipe.element] == expected, pipe.element


def test_the_numbers_are_the_variable_pool_numbers(coli):
    """Phase 3 is done when the sheet and the Variable Pool agree."""
    _run(coli)
    coli.variable_pool.refresh(coli.runner.state)
    readouts = coli.variable_pool.readouts
    compared = 0
    for pipe in coli.pcs_view.spec.pipes:
        name = (pipe.flow or "").partition(":")[2]
        if pipe.flow and pipe.flow.startswith("v:") and name in readouts:
            assert coli.pcs_view.canvas.value_text(pipe.element) == readouts[name].text(), name
            compared += 1
    assert compared >= 5


def test_levels_follow_the_volumes(coli):
    _run(coli)
    state = coli.runner.state
    v, p, index = state.v, state.p, state.idx
    widgets = coli.pcs_view.canvas.widgets

    def share(volume, maximum):
        return min(max(volume / maximum, 0.0), 1.0)

    assert widgets[REACTOR].level() == pytest.approx(share(v.VL[index], p["VLmax"]))
    assert widgets[REACTOR].minimum_mark() == pytest.approx(p["VLmin"] / p["VLmax"])
    assert widgets["reservoir1"].level() == pytest.approx(share(v.VR1[index], p["VR10"]))
    assert widgets["acid"].level() == pytest.approx(share(v.VT1[index], p["VT10"]))
    assert widgets["alkali"].level() == pytest.approx(share(v.VT2[index], p["VT20"]))
    assert widgets["antifoam"].level() == pytest.approx(share(v.VT3[index], p["VT30"]))
    assert widgets["harvest"].level() is None


def test_the_stirrer_turns_when_the_speed_says_so(coli):
    _run(coli)
    speed = float(coli.runner.state.v.NSt[coli.runner.state.idx])
    assert coli.pcs_view.canvas.widgets[REACTOR].stirring() == (speed > FLOW_EPSILON)


def test_pichia_shows_two_reservoirs_and_coli_one(qapp, db_copy):
    pichia = _window(db_copy, PICHIA_PROJECT)
    assert {"reservoir1", "reservoir2", "feed2_pump"} <= set(pichia.pcs_view.canvas.widgets)
    coli = _window(db_copy, ECOLI_PROJECT)
    assert "reservoir2" not in coli.pcs_view.canvas.widgets
    assert "reservoir1" in coli.pcs_view.canvas.widgets


def test_a_controller_owned_element_shows_the_flow_not_the_flag(coli):
    """pH control is automatic in 716: the acid pump says who owns it and
    whether acid flows, whatever f_acid says."""
    assert coli.runner.state.p["Mode_pH"] == 1
    coli.runner.state.p["f_acid"] = 1.0
    _run(coli)
    pump = coli.pcs_view.element("acid_pump")
    assert coli.pcs_view.owners["acid_pump"] == "pH-Control"
    assert "pH-Control" in pump.toolTip()
    flowing = float(coli.runner.state.v.FT1[coli.runner.state.idx]) > FLOW_EPSILON
    assert pump.isChecked() == flowing


def test_an_operator_element_shows_its_flag(coli):
    """Feed is the operator's in 716 (Mode_pO2 = 1, no feed phase)."""
    _run(coli)
    assert coli.pcs_view.owners["feed1_pump"] is None
    assert coli.pcs_view.element("feed1_pump").isChecked()


def test_the_harvest_pipe_starts_at_the_outlet(coli):
    coli.resize(1280, 720)
    coli.tabs.setCurrentWidget(coli.pcs_view)
    coli.show()
    QApplication.processEvents()
    canvas = coli.pcs_view.canvas
    pipe = next(pipe for pipe in canvas.spec.pipes if pipe.element == "harvest_line")
    route = canvas.route(pipe)
    vessel = canvas.widgets[REACTOR]
    outlet = vessel.mapTo(canvas, vessel.outlet().toPoint())
    assert route[0] == (float(outlet.x()), float(outlet.y()))
    assert route[1][0] == route[0][0]  # straight down first
    coli.close()


def test_a_line_from_a_named_element_does_not_name_its_valve_again(coli):
    canvas = coli.pcs_view.canvas
    shown = {valve.element: canvas.shows_label(valve) for valve in canvas.spec.valves}
    assert not shown["air_valve"]  # "Air" stands at the supply already
    assert not shown["acid_pump"]  # and "Acid" under the vessel
    assert shown["aeration_valve"]  # the manifold has no name
    assert shown["stirrer"]  # on no line at all


def test_the_arrow_sits_where_the_line_enters_its_target(coli):
    """R&I style: just outside the vessel, not half way on the valve."""
    coli.resize(1280, 720)
    coli.tabs.setCurrentWidget(coli.pcs_view)
    coli.show()
    QApplication.processEvents()
    canvas = coli.pcs_view.canvas
    vessel = canvas.widgets[REACTOR].geometry()
    for name in ("acid_line", "heating_line"):
        pipe = next(pipe for pipe in canvas.spec.pipes if pipe.element == name)
        points = canvas.route(pipe)
        (x, y), _ = arrow_anchor(points, canvas.arrow_share(pipe, points))
        assert not vessel.contains(round(x), round(y)), name
        gap = min(abs(x - vessel.left()), abs(x - vessel.right()))
        assert gap < 40, (name, gap)
    coli.close()


def _distance_to_route(point, route) -> float:
    """Shortest distance from a point to a polyline, in pixels."""
    px, py = point
    best = math.inf
    for (ax, ay), (bx, by) in pairwise(route):
        length = (bx - ax) ** 2 + (by - ay) ** 2
        share = 0.0
        if length > 0:
            share = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length))
        best = min(best, math.dist((px, py), (ax + share * (bx - ax), ay + share * (by - ay))))
    return best


@pytest.mark.parametrize("size", [(1280, 720), (1000, 600)])
def test_every_valve_sits_on_its_pipe(coli, size):
    """The point the pipe runs through — for a control valve the valve, not
    its actuator — lies on the pipe, give or take the rounding to pixels."""
    coli.resize(*size)
    coli.tabs.setCurrentWidget(coli.pcs_view)
    coli.show()
    QApplication.processEvents()
    canvas = coli.pcs_view.canvas
    for pipe in canvas.spec.pipes:
        if pipe.valve is None:
            continue
        button = canvas.widgets[pipe.valve]
        through = button.mapTo(canvas, button.line_point().toPoint())
        gap = _distance_to_route((through.x(), through.y()), canvas.route(pipe))
        assert gap <= 1.5, (pipe.valve, gap)
    coli.close()


def test_a_control_valve_runs_its_line_below_its_actuator(qapp):
    valve = ValveButton("Air", symbol="control_valve")
    assert valve.line_point().y() > valve.rect().center().y()
    pump = ValveButton("Acid", symbol="pump")
    assert pump.line_point() == QRectF(pump.rect()).center()


def _shown(window, size=(1280, 720)):
    window.resize(*size)
    window.tabs.setCurrentWidget(window.pcs_view)
    window.show()
    QApplication.processEvents()
    return window.pcs_view.canvas


def test_the_aeration_pipe_ends_on_the_gas_lance(coli):
    canvas = _shown(coli)
    pipe = next(pipe for pipe in canvas.spec.pipes if pipe.element == "aeration_line")
    route = canvas.route(pipe)
    vessel = canvas.widgets[REACTOR]
    inlet = vessel.mapTo(canvas, vessel.gas_inlet().toPoint())
    assert route[-1] == (float(inlet.x()), float(inlet.y()))
    assert route[-2][0] == route[-1][0]  # straight down onto it
    assert route[-2][1] < route[-1][1]  # from above the vessel
    coli.close()


def test_the_motor_sits_exactly_on_the_shaft(coli):
    canvas = _shown(coli)
    motor = canvas.widgets["stirrer"]
    vessel = canvas.widgets[REACTOR]
    assert vessel.width() % 2 == 0
    assert motor.x() + motor.width() // 2 == vessel.x() + vessel.width() // 2
    coli.close()


def test_two_live_gases_do_not_share_the_spot_of_their_reading(coli):
    canvas = _shown(coli)
    anchors = []
    for name in ("air_line", "o2_line"):
        pipe = next(pipe for pipe in canvas.spec.pipes if pipe.element == name)
        points = canvas.route(pipe)
        (_, y), angle = arrow_anchor(points, canvas.arrow_share(pipe, points))
        assert abs(math.sin(angle)) < 0.1, name  # on its own level part
        anchors.append(y)
    assert anchors[0] != anchors[1]
    coli.close()


@pytest.mark.parametrize("size", [(1280, 720), (1000, 600), (1600, 900)])
def test_no_reading_covers_an_element_a_name_or_another_reading(qapp, db_copy, size):
    """Every gas on, feed on: as many live pipes as the sheet can have."""
    window = _window(
        db_copy,
        ECOLI_PROJECT,
        f_feed=1.0,
        Mode_feed=0.0,
        f_O2=1.0,
        f_N2=1.0,
        f_CO2=1.0,
        FnO2w=1.0,
        FnN2w=1.0,
        FnCO2w=0.5,
        Mode_pO2=0.0,
    )
    _run(window)
    canvas = _shown(window, size)
    window.pcs_view.refresh(window.runner.state)
    boxes = [placed[0] for placed in canvas.value_boxes().values()]
    assert len(boxes) >= 6
    elements = {name: QRectF(widget.geometry()) for name, widget in canvas.widgets.items()}
    for number, label in enumerate(canvas.label_boxes()):
        elements[f"label {number}"] = label
    for index, box in enumerate(boxes):
        for name, area in elements.items():
            assert not box.intersects(area), name
        for other in boxes[index + 1 :]:
            assert not box.intersects(other)
    window.close()


@pytest.mark.parametrize("size", [(1280, 720), (1000, 600), (1600, 900)])
def test_a_gas_reading_stands_between_its_valve_and_the_collector(qapp, db_copy, size):
    """Clear of everything is not enough: a reading belongs beside its arrow.

    With the collector at x = 0.26 the test above passed at 1280 px because
    each gas reading had walked back past its valve to above the name of the
    supply — on nothing, and nowhere near the arrow it belongs to.
    """
    window = _window(
        db_copy,
        ECOLI_PROJECT,
        f_O2=1.0,
        f_N2=1.0,
        f_CO2=1.0,
        FnO2w=1.0,
        FnN2w=1.0,
        FnCO2w=0.5,
        Mode_pO2=0.0,
    )
    _run(window)
    canvas = _shown(window, size)
    window.pcs_view.refresh(window.runner.state)
    boxes = canvas.value_boxes()
    collector = canvas.point("gas_manifold")[0]
    for gas in ("air", "o2", "n2", "co2"):
        box = boxes[f"{gas}_line"][0]
        valve = canvas.widgets[f"{gas}_valve"].geometry()
        assert valve.right() <= box.left(), gas
        assert box.right() <= collector, gas
        # Just above its own line, not lifted towards the next gas.
        assert abs(box.bottom() - canvas.point(f"{gas}_valve")[1]) <= 8, gas


def test_cooling_and_heating_are_shown_in_grams_per_hour(coli):
    """The model computes kg/h; the sheet shows g/h, the operator's wish."""
    state = coli.runner.state
    state.p["Mode_temp"] = 0.0
    state.p["f_cooling"] = 1.0
    _run(coli, 5)
    pipes = {pipe.element: pipe for pipe in coli.pcs_view.spec.pipes}
    assert pipes["cooling_line"].unit == pipes["heating_line"].unit == "g/h"

    expected = float(state.a["mdotC"]) * 1000
    assert expected > 0
    assert coli.pcs_view.canvas.flows["cooling_line"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (7.512, "7.512"),
        (0.01294, "0.01294"),
        (9999.0, "9999"),
        (68127.93, "68\u2009128"),
        (1_500_000.0, "1\u2009500\u2009000"),
    ],
)
def test_a_large_reading_is_written_whole_not_with_an_exponent(coli, value, text):
    coli.pcs_view.canvas.flows["cooling_line"] = value
    assert coli.pcs_view.canvas.value_text("cooling_line") == text


def test_the_cooling_reading_keeps_its_place_from_none_to_full(coli):
    """From a trickle to the pump at its maximum by hand: one box."""
    state = coli.runner.state
    state.p["Mode_temp"] = 0.0
    state.p["f_cooling"] = 1.0
    _run(coli, 5)
    canvas = _shown(coli)
    coli.pcs_view.refresh(state)
    boxes = []
    for value in (12.0, 68127.93, 1_500_000.0):
        canvas.flows["cooling_line"] = value
        boxes.append(canvas.value_boxes()["cooling_line"][0])
    assert boxes[0] == boxes[1] == boxes[2]
    metrics = canvas.fontMetrics()
    widest = metrics.horizontalAdvance(f"{canvas.value_text('cooling_line')} g h⁻¹")
    assert boxes[2].width() >= widest
    coli.close()


def test_heating_water_is_shown_in_grams_per_hour(coli):
    """Automatic temperature control in 716: the heater runs on a.mdotH."""
    _run(coli, 30)
    state = coli.runner.state
    assert state.p["Mode_temp"] == 1
    flow = coli.pcs_view.canvas.flows["heating_line"]
    assert flow == pytest.approx(float(state.a["mdotH"]) * 1000)


def test_units_are_written_with_exponents():
    from biofermentation.gui.pcs_specs import pretty_unit

    assert pretty_unit("l/min") == "l min⁻¹"
    assert pretty_unit("l/h") == "l h⁻¹"
    assert pretty_unit("rpm") == "rpm"
    assert pretty_unit("") == ""


def test_a_reading_does_not_move_when_a_digit_comes_or_goes(coli):
    _run(coli)
    canvas = _shown(coli)
    coli.pcs_view.refresh(coli.runner.state)
    assert canvas.live["air_line"]

    canvas.flows["air_line"] = 7.5
    short = canvas.value_boxes()["air_line"]
    canvas.flows["air_line"] = 7.512
    long = canvas.value_boxes()["air_line"]
    assert short[0] == long[0]
    assert short[2] == long[2]
    assert short[1] != long[1]
    coli.close()


def test_no_pipe_is_drawn_inside_a_symbol(coli):
    canvas = _shown(coli)
    outside = canvas._outside_symbols()
    for name in ("alkali_pump", "air_valve", "heating_valve", "stirrer"):
        button = canvas.widgets[name]
        through = button.mapTo(canvas, button.line_point().toPoint())
        assert not outside.contains(QPointF(through)), name
    assert outside.contains(QPointF(2, 2))
    coli.close()


def test_the_stirrer_shows_its_speed(coli):
    _run(coli)
    state = coli.runner.state
    canvas = coli.pcs_view.canvas
    speed = float(state.v.NSt[state.idx])
    assert canvas.stirrer_reading == f"{speed:.4g} rpm"
    stirrer = coli.pcs_view.spec.valve("stirrer")
    assert canvas.label_text(stirrer).startswith("Stirrer · ")


def test_bubbles_rise_only_while_gas_flows(coli):
    _run(coli)
    vessel = coli.pcs_view.canvas.widgets[REACTOR]
    assert coli.pcs_view.canvas.live["aeration_line"]
    assert vessel.gassing()

    coli.runner.state.p["f_aeration"] = 0.0
    _run(coli, 5)
    assert not coli.pcs_view.canvas.live["aeration_line"]
    assert not vessel.gassing()


def test_bubbles_move_only_while_the_process_runs(coli):
    _run(coli)
    view = coli.pcs_view
    vessel = view.canvas.widgets[REACTOR]
    before = vessel.bubbles(100, 200, 40, 50)
    assert len(before) == 9  # three kinds of bubble

    view.set_running(False)
    view._animate()
    assert vessel.bubbles(100, 200, 40, 50) == before

    view.set_running(True)
    view._animate()
    assert vessel.bubbles(100, 200, 40, 50) != before


def test_the_broth_turns_beige_with_the_cells(coli):
    from biofermentation.gui.widgets.pcs_elements import BROTH_DENSE, LIQUID, broth_color

    assert broth_color(0.0, 0.0) == LIQUID
    assert broth_color(1.0, 0.0) == BROTH_DENSE
    assert broth_color(5.0, 0.0) == BROTH_DENSE  # held at full

    _run(coli)
    state = coli.runner.state
    share = float(state.v.cXL[state.idx]) / coli.pcs_view.broth.biomass_full
    vessel = coli.pcs_view.canvas.widgets[REACTOR]
    assert vessel.broth() == broth_color(share, 0.0)
    assert coli.pcs_view.broth.product is None  # no coloured product in E. coli


def test_pichia_broth_turns_green_with_the_product(qapp, db_copy):
    from biofermentation.gui.widgets.pcs_elements import broth_color

    pichia = _window(db_copy, PICHIA_PROJECT)
    assert pichia.pcs_view.broth.product == "v:cP1L"
    plain, green = broth_color(0.3, 0.0), broth_color(0.3, 1.0)
    assert green.green() - green.red() > plain.green() - plain.red()


def test_the_sheet_shows_the_organisms_reservoirs_not_the_projects(qapp, db_copy):
    """A Pichia project saved with one reservoir still computes FR2 and VR2."""
    pichia = _window(db_copy, PICHIA_PROJECT)
    wanted = pichia.runner.organism.metadata.n_reservoirs
    assert wanted == 2
    shown = [tank for tank in pichia.pcs_view.spec.tanks if tank.element.startswith("reservoir")]
    assert len(shown) == wanted


def test_the_sheet_draws_at_any_size(coli):
    """A paintEvent that raises would only show when the tab is opened."""
    _run(coli)
    for size in [(480, 360), (900, 600), (1400, 900)]:
        coli.pcs_view.resize(*size)
        assert not coli.pcs_view.grab().isNull()


def test_read_value_reads_all_three_containers(coli):
    state = coli.runner.state
    assert read_value("p:VLmax", state) == state.p["VLmax"]
    assert read_value("v:VL", state) == float(state.v.VL[state.idx])
    assert read_value(None, state) is None
    assert read_value("a:does_not_exist", state) is None
    state.p["nan_here"] = math.nan
    assert read_value("p:nan_here", state) is None


# ---------------------------------------------------- phase 5: polish --


def test_the_vessel_shows_ph_po2_and_temperature_as_the_panels_do(coli):
    """The same numbers, to the digit, as the actual fields of the panels."""
    _run(coli)
    coli.pcs_view.refresh(coli.runner.state)
    shown = coli.pcs_view.canvas.vessel_readings
    actuals = {
        spec_field.actual: panel.rows[spec_field.parameter].actual.text()
        for panel in coli.panels.values()
        for spec_field in panel.spec.fields
        if spec_field.actual in ("pHL", "pO2", "thetaL")
    }
    assert len(actuals) == 3
    assert shown[0] == f"pH {actuals['pHL']}"
    assert shown[1] == f"pO₂ {actuals['pO2']} %"
    assert shown[2] == f"ϑ {actuals['thetaL']} °C"


@pytest.mark.parametrize("size", [(1280, 720), (1000, 600), (1600, 900), (700, 500)])
def test_the_vessel_readings_stand_between_motor_and_lid_on_nothing(coli, size):
    _run(coli)
    canvas = _shown(coli, size)
    coli.pcs_view.refresh(coli.runner.state)
    boxes = [box for box, _ in canvas.vessel_reading_boxes()]
    assert len(boxes) == 3
    lid = canvas.widgets[REACTOR].geometry().top()
    for box in boxes:
        assert box.bottom() <= lid, size
        for name, widget in canvas.widgets.items():
            assert not box.intersects(QRectF(widget.geometry())), name
    flows = [placed[0] for placed in canvas.value_boxes().values()]
    assert not any(box.intersects(flow) for box in boxes for flow in flows)
    coli.close()


def test_the_dashes_run_only_while_the_process_runs(coli):
    _run(coli)
    view = coli.pcs_view
    view.set_running(False)
    view._animate()
    assert view.canvas.flow_travel == 0.0
    view.set_running(True)
    view._animate()
    view._animate()
    assert view.canvas.flow_travel > 0.0


def test_the_animation_runs_only_while_the_sheet_is_seen(coli):
    _shown(coli)
    timer = coli.pcs_view.animation_timer
    assert timer.isActive()
    coli.tabs.setCurrentWidget(coli.variable_pool)
    assert not timer.isActive()
    # Out in a window of its own it is seen again, whatever is in front.
    coli.tabs.detach("PCS")
    QApplication.processEvents()
    assert timer.isActive()
    coli.tabs.attach_all()
    coli.close()


def test_moving_dashes_change_only_the_pixels_of_live_pipes(coli):
    """The dashes sit on the line: an idle pipe looks the same at every frame."""
    _run(coli)
    canvas = _shown(coli)
    coli.pcs_view.refresh(coli.runner.state)
    canvas.flow_travel = 0.0
    first = canvas.grab().toImage()
    canvas.flow_travel = 6.0
    second = canvas.grab().toImage()
    assert first != second
    idle = next(pipe for pipe in canvas.spec.pipes if not canvas.live[pipe.element])
    for x, y in canvas.route(idle)[:1]:
        point = (int(x), int(y))
        assert first.pixel(*point) == second.pixel(*point), idle.element
    coli.close()


# ------------------------------------------- harvest, lance, stirrer --


@pytest.mark.parametrize("project", [ECOLI_PROJECT, PICHIA_PROJECT])
def test_the_harvested_volume_is_what_the_harvest_pump_took_out(qapp, db_copy, project):
    """The balance on the sheet against FH summed step by step."""
    from biofermentation.gui.pcs_specs import harvested_volume

    window = _window(
        db_copy, project, f_feed=1.0, Mode_feed=0.0, Mode_harvest=0.0, f_harvest=1.0, FHrelw=20.0
    )
    _run(window, 300)
    state = window.runner.state
    v = state.v
    # Euler on the volumes: the step into i drains FH[i - 1] for dt.
    pumped = float(np.nansum(v.FH[: state.idx]) * state.dt)
    assert pumped > 0.05
    shown = harvested_volume(window.pcs_view.spec, lambda source: read_value(source, state))
    assert shown == pytest.approx(pumped, rel=1e-9)
    gauge = window.pcs_view.element("harvest")
    assert gauge.text() == f"{round(shown, 2):.3g} l"
    assert gauge.level() is None  # no capacity, no level
    window.close()


def test_nothing_harvested_reads_zero(coli):
    _run(coli, 5)
    assert coli.pcs_view.element("harvest").text() == "0 l"


def test_a_large_harvest_has_no_exponent():
    from biofermentation.gui.widgets.pcs_elements import volume_text

    assert volume_text(0.0) == "0"
    assert volume_text(3.14159) == "3.14"
    assert volume_text(1234.5) == "1234"


def test_the_gas_dashes_run_on_down_the_lance(coli):
    _run(coli)
    canvas = _shown(coli)
    view = coli.pcs_view
    vessel = canvas.widgets[REACTOR]
    assert vessel.gassing()
    view.set_running(True)
    view._animate()
    pipe = next(p for p in canvas.spec.pipes if p.element == "aeration_line")
    length = sum(math.dist(a, b) for a, b in pairwise(canvas.route(pipe)))
    # Carried on from where the pipe ends, not started afresh.
    assert vessel._flow_travel == pytest.approx(canvas.flow_travel - length)
    # And the dashes are drawn there: two frames differ on the lance.
    first = vessel.grab().toImage()
    view._animate()
    second = vessel.grab().toImage()
    inlet = vessel.gas_inlet()
    column = [
        (first.pixel(int(inlet.x()), y), second.pixel(int(inlet.x()), y))
        for y in range(20, vessel.height() // 2)
    ]
    assert any(a != b for a, b in column)
    coli.close()


def test_the_impeller_turns_only_while_it_stirs_and_the_process_runs(coli):
    _run(coli)
    view = coli.pcs_view
    vessel = view.canvas.widgets[REACTOR]
    assert vessel.stirring()
    view.set_running(False)
    view._animate()
    assert vessel.turn() == 0.0
    view.set_running(True)
    view._animate()
    turned = vessel.turn()
    assert turned > 0.0
    vessel.set_stirring(False)
    view._animate()
    assert vessel.turn() == turned


def test_a_turning_impeller_looks_different_from_a_standing_one(coli):
    _run(coli)
    canvas = _shown(coli)
    vessel = canvas.widgets[REACTOR]
    standing = vessel.grab().toImage()
    vessel.advance_stirrer(0.1)
    assert vessel.grab().toImage() != standing
    coli.close()


def test_stirring_swirls_the_bubbles_and_keeps_them_in_the_vessel(qapp):
    from biofermentation.gui.widgets.pcs_elements import VesselWidget

    vessel = VesselWidget()
    vessel.resize(220, 320)
    vessel.set_gassing(True)
    vessel.advance_bubbles(0.7)
    calm = vessel.bubbles(110, 280, 60, 60)
    vessel.set_stirring(True)
    vessel.advance_stirrer(0.3)
    swirled = vessel.bubbles(110, 280, 60, 60)
    assert len(calm) == len(swirled)
    # Sideways only: every bubble keeps its height and its size.
    assert [(y, r) for _, y, r in calm] == [(y, r) for _, y, r in swirled]
    assert any(abs(a[0] - b[0]) > 1 for a, b in zip(calm, swirled, strict=True))
    # Inside the walls: the ring is 60 px wide in a 200 px vessel.
    assert all(10 < x < 210 for x, _, _ in swirled)


@pytest.mark.parametrize("project", [ECOLI_PROJECT, PICHIA_PROJECT])
def test_every_reading_carries_its_unit(qapp, db_copy, project):
    """FH is not in the Variable Pool; its reading still needs its unit."""
    window = _window(db_copy, project)
    canvas = window.pcs_view.canvas
    for pipe in canvas.spec.pipes:
        name = (pipe.flow or "").partition(":")[2]
        unit = pipe.unit or canvas.units.get(name, "")
        assert unit, pipe.element
    window.close()


# ---------------------------- standing gas, double jacket, manual heat --


def _aeration_shut(window) -> None:
    state = window.runner.state
    state.p["f_aeration"] = 0.0
    window.load_panels()
    run_steps(state, window.runner.organism, 5)
    window.refresh()


def test_gas_in_front_of_a_shut_aeration_valve_stops_just_before_it(coli):
    _run(coli)
    canvas = _shown(coli)
    _aeration_shut(coli)
    assert canvas.live["air_line"] and not canvas.live["aeration_line"]
    stretches = canvas.standing_stretches()
    assert [pipe.element for pipe, _, _ in stretches] == ["aeration_line"]
    _, points, _ = stretches[0]
    valve = canvas.widgets["aeration_valve"]
    symbol = valve.symbol_rect().translated(valve.x(), valve.y())
    # Starts at the manifold, ends within a few pixels before the symbol.
    assert points[0] == canvas.route(stretches[0][0])[0]
    end_x = points[-1][0]
    assert symbol.left() - canvas.STANDING_GAP - 2 <= end_x <= symbol.left() - canvas.STANDING_GAP
    coli.close()


def test_with_the_aeration_valve_open_nothing_stands(coli):
    _run(coli)
    _shown(coli)
    assert coli.pcs_view.canvas.live["aeration_line"]
    assert coli.pcs_view.canvas.standing_stretches() == []
    coli.close()


def test_nothing_stands_when_no_gas_comes(coli):
    _run(coli)
    canvas = _shown(coli)
    state = coli.runner.state
    state.p.update(f_air=0.0, f_O2=0.0, f_N2=0.0, f_CO2=0.0, f_aeration=0.0)
    for name in ("FnAIR", "FnO2", "FnN2", "FnCO2"):
        state.v[name][state.idx] = 0.0
    coli.pcs_view.refresh(state)
    assert canvas.standing_stretches() == []
    coli.close()


def test_a_shut_harvest_valve_does_not_fill_its_line(coli):
    """The rule is for junctions; the reactor is a vessel, its outlet stays idle."""
    _run(coli)
    canvas = _shown(coli)
    assert not canvas.live["harvest_line"]
    assert all(pipe.element != "harvest_line" for pipe, _, _ in canvas.standing_stretches())
    coli.close()


@pytest.mark.parametrize("size", [(1280, 720), (1000, 600), (1600, 900)])
def test_cooling_and_heating_run_into_the_double_jacket(coli, size):
    _run(coli)
    canvas = _shown(coli, size)
    vessel = canvas.widgets[REACTOR]
    span = vessel.jacket_span().translated(vessel.x(), vessel.y())
    # On the right wall, inside the widget, where the pipes come in.
    assert span.left() > vessel.x() + vessel.width() / 2
    assert span.right() <= vessel.x() + vessel.width()
    for name in ("cooling_line", "heating_line"):
        pipe = next(p for p in canvas.spec.pipes if p.element == name)
        route = canvas.route(pipe)
        # The last horizontal stretch into the reactor runs at a height the
        # jacket covers.
        y = route[-2][1]
        assert span.top() < y < span.bottom(), (name, size)
    coli.close()


@pytest.mark.parametrize("size", [(1280, 720), (1000, 600), (1600, 900)])
def test_the_jacket_is_a_flat_trapezoid_thicker_than_a_wall_and_not_full_height(coli, size):
    _run(coli)
    canvas = _shown(coli, size)
    vessel = canvas.widgets[REACTOR]
    corners = vessel.jacket_polygon()
    inner = corners[3].y() - corners[0].y()
    outer = corners[2].y() - corners[1].y()
    body, dish, _ = vessel._geometry()
    assert corners[1].x() - corners[0].x() >= 8  # a tick thicker than before (6 px)
    assert inner <= 0.62 * body.height()  # not as high as wall to dish (0.76)
    assert outer < inner  # the outer wall is the short side
    # Clear of the lid and of the dish.
    assert corners[0].y() > body.top()
    assert corners[3].y() < body.bottom() - dish
    # Inside the widget, so nothing is cut off at its edge.
    assert corners[1].x() <= vessel.width()
    coli.close()


def test_the_jacket_fills_with_what_flows(coli):
    _run(coli)
    vessel = coli.pcs_view.canvas.widgets[REACTOR]
    # 716 heats automatically at the start: heating water, no coolant.
    assert coli.pcs_view.canvas.live["heating_line"]
    assert vessel.jacket() == ("heating",)
    standing = vessel.grab().toImage()
    vessel.set_jacket(())
    assert vessel.grab().toImage() != standing


def test_manual_heating_shows_the_electric_power(coli):
    """By hand the model heats with PHmax watts; the line says so and flows."""
    _run(coli)
    coli._panel_changed("Mode_temp", 0.0)
    coli.pcs_view.element("heating_valve").click()
    state = coli.runner.state
    assert state.p["f_heating"] == 1.0
    canvas = coli.pcs_view.canvas
    assert canvas.live["heating_line"]
    assert canvas.flows["heating_line"] == state.p["PHmax"]
    assert canvas.reading_units["heating_line"] == "W"
    assert canvas.value_text("heating_line") == "10\u2009000"
    _shown(coli)
    _, text, _ = canvas.value_boxes()["heating_line"]
    assert text == "10\u2009000 W"

    coli.pcs_view.element("heating_valve").click()  # off again
    assert not canvas.live["heating_line"]
    assert "heating_line" not in canvas.reading_units
    coli.close()


def test_manual_heating_changes_nothing_in_the_run(qapp, db_copy):
    """The power on the line is read from p; the tab still computes nothing."""
    window = _window(db_copy, ECOLI_PROJECT, Mode_temp=0.0, f_heating=1.0)
    state = window.runner.state
    before = {name: np.array(series, copy=True) for name, series in state.v.items()}
    _run(window, 5)
    after_run = {name: np.array(series, copy=True) for name, series in state.v.items()}
    window.pcs_view.refresh(state)
    for name, series in state.v.items():
        assert np.array_equal(series, after_run[name], equal_nan=True), name
    assert before.keys() <= after_run.keys()
    window.close()
