"""Simulation state and preallocation (plan section 2)."""

import numpy as np
import pytest

from biofermentation.core.state import BLOCK, Namespace, SimulationState


def test_namespace_is_dict_and_attributes_at_once():
    ns = Namespace({"NStw": 400.0})
    assert ns.NStw == 400.0
    assert ns["NStw"] == 400.0
    ns.pHw = 6.7
    assert ns["pHw"] == 6.7
    with pytest.raises(AttributeError):
        _ = ns.definitely_missing


def test_series_starts_at_the_block_size():
    state = SimulationState()
    series = state.series("cXL", 3.0)
    assert series.size == BLOCK
    assert series[0] == 3.0
    assert np.isnan(series[1])


def test_capacity_doubles_instead_of_growing_by_a_fixed_block():
    """A fixed block is still O(n^2); doubling makes it amortised O(1).

    numpy arrays have no spare capacity, so every growth copies the whole
    series. MATLAB's preallocationFcn adds 20 slots at a time, which costs
    1.7 s over 50000 steps across this model's series. The block size is the
    one thing not carried over from it.
    """
    state = SimulationState()
    state.series("cXL", 0.0)

    sizes = []
    for i in range(1, 5000):
        before = state.v.cXL.size
        state.ensure_capacity(i)
        if state.v.cXL.size != before:
            sizes.append(state.v.cXL.size)

    assert sizes == [BLOCK * 2**k for k in range(1, len(sizes) + 1)]
    # 5000 steps must not cost 5000/20 = 250 reallocations.
    assert len(sizes) < 10


def test_every_series_grows_together():
    """A field left behind would raise halfway through a step."""
    state = SimulationState()
    state.series("cXL", 0.0)
    state.aux_series("ce_agi", 0.0)
    state.ensure_capacity(500)
    assert state.v.cXL.size >= 501
    assert state.a.ce_agi.size >= 501


def test_a_series_added_late_matches_the_current_capacity():
    state = SimulationState()
    state.series("cXL", 0.0)
    state.ensure_capacity(500)
    late = state.series("cS1L", 1.0)
    assert late.size >= 501, "a series created mid-run must not be short"


def test_variable_series_carry_nan_and_controller_series_carry_zero():
    """NaN marks a slot that was never computed; a controller signal is 0."""
    state = SimulationState()
    state.series("cXL", 0.0)
    state.aux_series("ce_agi", 0.0)
    state.ensure_capacity(100)
    assert np.isnan(state.v.cXL[50])
    assert state.a.ce_agi[50] == 0.0


def test_trimmed_drops_the_preallocation_slots():
    state = SimulationState()
    state.series("cXL", 0.0)
    for i in range(1, 50):
        state.ensure_capacity(i)
        state.v.cXL[i] = i
    state.idx = 49

    trimmed = state.trimmed()
    assert len(trimmed["cXL"]) == 50
    assert state.v.cXL.size > 50, "the padding must still be there in v"
    assert np.array_equal(trimmed["cXL"], np.arange(50, dtype=float))
    assert not np.isnan(trimmed["cXL"]).any()


def test_trimmed_leaves_the_auxiliary_container_alone():
    """a is not persisted, so it has no business in the database payload."""
    state = SimulationState()
    state.series("cXL", 0.0)
    state.aux_series("ce_agi", 0.0)
    state.a.mySm = 0.03
    state.idx = 0
    assert set(state.trimmed()) == {"cXL"}


def test_carry_forward_fills_only_untouched_slots():
    """A variable the model does not recompute holds its value, not a gap."""
    state = SimulationState()
    state.series("cXL", 1.0)
    state.series("pO2w", 20.0)
    state.ensure_capacity(1)
    state.v.cXL[1] = 2.0  # written this step

    carried = state.carry_forward(1)

    assert carried == ("pO2w",)
    assert state.v.cXL[1] == 2.0, "a written value must not be overwritten"
    assert state.v.pO2w[1] == 20.0


def test_carry_forward_does_nothing_at_the_first_step():
    state = SimulationState()
    state.series("cXL", 1.0)
    assert state.carry_forward(0) == ()
