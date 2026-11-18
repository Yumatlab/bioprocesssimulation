"""Errors inherited from MATLAB, fixed in 3.1.0 (FEHLER.md, docs/changes_from_matlab.md).

For every fix two kinds of test: that the error is gone, and that nothing
else moved — the fixed model gives exactly the old numbers wherever the old
code was not wrong. The second kind is what keeps a fix from being a
different model in disguise.
"""

from pathlib import Path

import numpy as np
import pytest

from biofermentation.core.runner import build_state, run_steps
from biofermentation.db import load_phases
from biofermentation.organisms import discover_organisms, get_organism

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
ORGANISMS = [("escherichia_coli", 716), ("pichia_pastoris", 519)]


@pytest.fixture(scope="module", autouse=True)
def _registry():
    discover_organisms()


def _state(organism: str, project: int, model=None, **parameters):
    model = model or get_organism(organism)
    p = dict(load_phases(TEMPLATE_DB, project).p)
    p.update(parameters)
    return build_state(p, model, dt=2 / 3600), model


def _identical(first, second) -> bool:
    a, b = first.trimmed(), second.trimmed()
    return a.keys() == b.keys() and all(
        np.array_equal(a[name], b[name], equal_nan=True) for name in a
    )


# ------------------------------------------------- F-07: antifoam at t = 0 --


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_antifoam_doses_after_an_inoculation_at_the_start(organism, project):
    """MATLAB asked ToI != 0 — the time of inoculation, which is 0 at the start."""
    state, model = _state(
        organism, project, f_Inoc=1.0, f_InocStart=1.0, f_antifoam=1.0, VT30=0.5, FT3max=0.1
    )
    run_steps(state, model, 900)
    assert state.a.ToI == 0.0  # the case the old condition could not see
    assert np.nanmax(state.v.AAF[: state.idx + 1]) > 0.3
    assert state.v.VT3[state.idx] < 0.5


def _with_matlab_antifoam(organism: str):
    """The model with MATLAB's condition, for comparison only."""
    base = type(get_organism(organism))

    class Original(base):
        def _antifoam(self, state, prev):
            p, v, a = state.p, state.v, state.a
            if p.f_antifoam == 1 and a.ToI != 0:
                TON = v.t[prev] - a.ToI
                return p.AAFtast * p.VAF ** (TON / p.Ttast)
            return 0.0

    return Original()


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_an_inoculation_during_the_run_gives_the_old_numbers(organism, project):
    """Inoculated after t = 0, ToI != 0 and inoc_occ are the same question."""
    runs = []
    for model in (get_organism(organism), _with_matlab_antifoam(organism)):
        state, model = _state(
            organism, project, model=model, f_Inoc=0.0, f_InocStart=0.0, f_antifoam=1.0
        )
        run_steps(state, model, 100)
        state.p.f_Inoc = 1.0
        run_steps(state, model, 500)
        assert state.a.ToI > 0
        runs.append(state)
    assert np.nanmax(runs[0].v.AAF[: runs[0].idx + 1]) > 0, "the antifoam did act"
    assert _identical(*runs)


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_without_inoculation_there_is_still_no_antifoam(organism, project):
    state, model = _state(organism, project, f_Inoc=0.0, f_InocStart=0.0, f_antifoam=1.0)
    run_steps(state, model, 200)
    assert np.nanmax(state.v.AAF[: state.idx + 1]) == 0.0


# ------------------------------------------- F-04: crossed pump limits --


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
@pytest.mark.parametrize("direction", ["acid", "alkali"])
def test_each_ph_pump_is_held_by_its_own_limit(organism, project, direction):
    """MATLAB scaled the acid pump with FT2max and the alkali pump with FT1max.

    Two runs with the same limit for the pump at work and a different one for
    the other pump: the pump at work must not notice. With the crossed limits
    it did — its flow followed the other pump's limit.
    """
    flows = []
    for other in (0.2, 0.8):
        state, model = _state(organism, project, f_Inoc=1.0, f_InocStart=1.0, Mode_pH=1.0)
        # A setpoint no culture reaches, so that only one pump ever runs. Not
        # relative to pH0: Pichia's medium settles at 7.4 in the first step
        # from a pH0 of 5.0, so pH0 + 2 would lie below the actual pH.
        state.p.pHw = 3.0 if direction == "acid" else 11.0
        if direction == "acid":
            state.p.FT1max, state.p.FT2max = 0.3, other
        else:
            state.p.FT1max, state.p.FT2max = other, 0.3
        run_steps(state, model, 300)
        working = state.v.FT1 if direction == "acid" else state.v.FT2
        idle = state.v.FT2 if direction == "acid" else state.v.FT1
        series = np.asarray(working[: state.idx + 1])
        assert np.nanmax(series) > 0, "the pump at work did run"
        assert np.nanmax(series) <= 0.3 + 1e-12, "and stayed under its own limit"
        assert np.nanmax(idle[: state.idx + 1]) == 0.0
        flows.append(series)
    assert np.array_equal(flows[0], flows[1], equal_nan=True)
