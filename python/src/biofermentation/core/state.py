"""Simulation state and preallocation (plan section 2, phase 4 of the plan).

The three containers of the MATLAB model are kept, including their names:

    p   parameters — scalars, read mostly, written by the phase automaton
    v   variables  — one time series per name, persisted to the database
    a   auxiliary  — controller states and derived constants, never persisted

app.p.NStw becomes p.NStw and app.v.cXL(idx) becomes v.cXL[idx], so a line of
MATLAB and its translation stay readable side by side. See CLAUDE.md,
"Namensgebung".

Indexing is zero-based here while MATLAB counts from one. Only the absolute
numbers differ; every relation in the model is between idx and idx - 1 and
survives the shift unchanged.
"""

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Starting size of a series, and the smallest amount it ever grows by.
#
# Preallocation matters more here than it did in MATLAB, not less: a numpy
# array has no spare capacity, so np.append allocates a new array and copies
# the old one every single time. Growing one element per step is O(n^2) and
# costs 7.3 s over 20000 steps across the ~64 series of this model.
#
# MATLAB's preallocationFcn adds a fixed block of 20. That is still O(n^2),
# only divided by 20 — measurably so: 438 ms at 20000 steps and 1.7 s at
# 50000. Growing geometrically instead makes it amortised O(1) and brings the
# same run to 62 ms and 151 ms. The MATLAB principle is kept, its block size
# is not.
BLOCK = 32


class Namespace(MutableMapping):
    """A dict that also answers to attribute access.

    p["NStw"] and p.NStw are the same slot. The attribute form is what makes
    the translated model readable; the mapping form is what the database layer
    and the tests want.
    """

    def __init__(self, values: dict[str, Any] | None = None):
        object.__setattr__(self, "_values", dict(values or {}))

    def __getattr__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, "_values")[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        self._values[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, name: str) -> Any:
        return self._values[name]

    def __setitem__(self, name: str, value: Any) -> None:
        self._values[name] = value

    def __delitem__(self, name: str) -> None:
        del self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Namespace({sorted(self._values)})"


@dataclass
class SimulationState:
    """Everything one simulation run needs, and nothing a GUI needs.

    idx is MATLAB's app.nxtidx: the index of the step that has been computed
    last. dt is app.a.deltat, the step width in hours.
    """

    p: Namespace = field(default_factory=Namespace)
    v: Namespace = field(default_factory=Namespace)
    a: Namespace = field(default_factory=Namespace)
    idx: int = 0
    dt: float = 0.005

    # Slots every series currently has room for. Tracked so the common case —
    # a step that needs no growth at all — costs one integer comparison
    # instead of a walk over all 150-odd series.
    _capacity: int = 0

    def series(self, name: str, initial: float = np.nan) -> np.ndarray:
        """Declare a variable series and return it, creating it if needed."""
        existing = self.v.get(name)
        if existing is None:
            size = max(BLOCK, self._capacity)
            existing = np.full(size, np.nan)
            existing[0] = initial
            self.v[name] = existing
            self._capacity = max(self._capacity, size)
        return existing

    def aux_series(self, name: str, initial: float = 0.0) -> np.ndarray:
        """Same for a controller signal in a — read at idx - 1, written at idx.

        These are the app.a fields MATLAB indexes (ce_agi, cI_Part, ce_LW and
        friends). They are time series like any other, they are simply not
        worth persisting.
        """
        existing = self.a.get(name)
        if existing is None:
            size = max(BLOCK, self._capacity)
            existing = np.zeros(size)
            existing[0] = initial
            self.a[name] = existing
            self._capacity = max(self._capacity, size)
        return existing

    def ensure_capacity(self, index: int) -> None:
        """Make room for writing at index, doubling when the room runs out.

        Every series in v and a is extended together, so no field can fall
        behind and produce an index error halfway through a step. The cost is
        up to twice the memory a run strictly needs — 25 MB of series become
        at most 51 MB — in exchange for dropping the quadratic term.
        """
        capacity = index + 1
        if capacity <= self._capacity:
            return

        target = max(capacity, self._capacity * 2, BLOCK)
        for store, fill in ((self.v, np.nan), (self.a, 0.0)):
            for name, value in list(store.items()):
                if not isinstance(value, np.ndarray) or value.size >= target:
                    continue
                store[name] = np.concatenate([value, np.full(target - value.size, fill)])
        self._capacity = target

    def carry_forward(self, index: int) -> tuple[str, ...]:
        """Hold every series that this step did not write at its last value.

        Some variables are constants kept as series (the pO2 setpoint, the CO2
        inlet fraction) and some are simply never recomputed by a given
        organism. MATLAB left them as NaN in memory and then wrote 0 for them
        on upload, which turned a gap into a measured zero. Carrying the
        previous value forward states what is actually true — the quantity did
        not change — and it keeps a resumed run from feeding NaN into the ODE.

        Returns the names it touched so a caller can see which variables its
        model never computes.
        """
        if index == 0:
            return ()
        carried = []
        for name, values in self.v.items():
            if not isinstance(values, np.ndarray):
                continue
            if np.isnan(values[index]) and not np.isnan(values[index - 1]):
                values[index] = values[index - 1]
                carried.append(name)
        return tuple(carried)

    def trimmed(self) -> dict[str, np.ndarray]:
        """The variable series without their preallocation slots.

        What goes to the database. Anything past idx is padding, not data.
        """
        end = self.idx + 1
        return {
            name: values[:end].copy()
            for name, values in self.v.items()
            if isinstance(values, np.ndarray)
        }
