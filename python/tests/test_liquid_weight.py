"""The liquid weight controller — reworked on 16.11.2026.

Manual: the harvest pump runs at FHrelw while f_harvest is set. Automatic:
the controller holds the weight at LWw and lets liquid out only while the
weight is above it. The second half is a deliberate deviation from MATLAB,
where the integral part kept draining below the setpoint.
"""

from pathlib import Path

import pytest

from biofermentation.core.runner import build_state, run_steps
from biofermentation.db import load_phases
from biofermentation.organisms import discover_organisms, get_organism

TEMPLATE_DB = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "biofermentation"
    / "resources"
    / "SimulationAppDB_template.db"
)
ORGANISMS = [("escherichia_coli", 716), ("pichia_pastoris", 519)]


@pytest.fixture(autouse=True, scope="module")
def _registry():
    discover_organisms()


def _state(organism: str, project: int, **parameters):
    model = get_organism(organism)
    p = dict(load_phases(TEMPLATE_DB, project).p)
    p.update(f_Inoc=1.0, f_InocStart=1.0)
    p.update(parameters)
    return build_state(p, model, dt=2 / 3600), model


def _weight(state, index: int) -> float:
    return float(state.v.VL[index]) * state.p["rhoL"]


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_nothing_leaves_at_or_below_the_setpoint(organism, project):
    """Even with an integral part left over from being above it."""
    state, model = _state(organism, project, VL0=10.0, Mode_harvest=1.0, LWw=9.8, KI_LW=50.0)
    run_steps(state, model, 600)

    below = [
        index for index in range(2, state.idx + 1) if _weight(state, index - 1) <= state.p["LWw"]
    ]
    assert below, "the run never came down to the setpoint"
    for index in below:
        assert state.v.FH[index] == 0.0, index


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_it_drains_while_the_weight_is_above_the_setpoint(organism, project):
    state, model = _state(organism, project, VL0=10.0, Mode_harvest=1.0, LWw=9.0)
    assert _weight(state, 0) > 9.0
    run_steps(state, model, 5)
    assert state.v.FH[state.idx] > 0.0


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_it_holds_the_weight_against_a_running_feed(organism, project):
    """Feed in, controller on: the weight settles at the setpoint, not below."""
    state, model = _state(
        organism,
        project,
        VL0=9.0,
        Mode_harvest=1.0,
        LWw=9.5,
        f_feed=1.0,
        Mode_feed=0.0,
        R_feed=1.0,
        FR1w=1.0,
    )
    run_steps(state, model, 3000)
    setpoint = state.p["LWw"]
    tail = [_weight(state, index) for index in range(state.idx - 300, state.idx + 1)]
    assert min(tail) > setpoint - 0.05
    assert max(tail) < setpoint + 0.2


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_manual_mode_is_the_pump_at_its_relative_rate(organism, project):
    state, model = _state(organism, project, Mode_harvest=0.0, f_harvest=1.0, FHrelw=20.0)
    run_steps(state, model, 3)
    assert state.v.FH[state.idx] == pytest.approx(0.2 * state.p["FHmax"])

    state.p["f_harvest"] = 0.0
    run_steps(state, model, 2)
    assert state.v.FH[state.idx] == 0.0
