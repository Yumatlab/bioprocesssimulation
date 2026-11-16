"""The PCS tab in the control window — PCS plan, phase 3 (read only).

Built on real projects: 716 (E. coli, one reservoir) and 519 (Pichia, two).
A short run is computed on the window's own state, then the tab is asked
what it shows, and that is held against v — the same numbers the Variable
Pool reads.
"""

import math
import shutil
from itertools import pairwise
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF
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


def test_every_element_is_read_only_in_phase_3(coli):
    _run(coli)
    for element, widget in coli.pcs_view.canvas.widgets.items():
        if isinstance(widget, ValveButton):
            assert not widget.isEnabled(), element


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
    assert widgets["antifoam"].level() is None
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
    boxes = [box for box, _ in canvas.value_boxes().values()]
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


def test_jacket_flows_carry_their_unit(coli):
    pipes = {pipe.element: pipe for pipe in coli.pcs_view.spec.pipes}
    assert pipes["cooling_line"].unit == "kg/h"
    assert pipes["heating_line"].unit == "kg/h"


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
