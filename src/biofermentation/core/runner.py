"""Driving a simulation without any user interface (plan section 2).

Phase 2 has to stand on its own: the numerical core must be runnable, and
therefore verifiable, before a single Qt widget exists. Everything the GUI
adds later — a timer, a guard flag, live plots — sits on top of run_steps()
and changes none of the numbers.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..organisms.base import OrganismModel
from ..organisms.registry import discover_organisms, get_organism
from .state import Namespace, SimulationState

# Step width in hours. MATLAB's app.a.deltat; 0.005 h is 18 seconds.
DEFAULT_DT = 0.005


def build_state(
    p: dict[str, float], organism: OrganismModel, *, dt: float = DEFAULT_DT
) -> SimulationState:
    """A state ready for step one, with the organism's own starting values."""
    state = SimulationState(p=Namespace(dict(p)), dt=dt)
    organism.initialize(state)
    return state


def run_steps(
    state: SimulationState,
    organism: OrganismModel,
    n_steps: int,
    *,
    phases=None,
    steps_per_check: int = 1,
    on_step: Callable[[SimulationState], None] | None = None,
    stop_when: Callable[[SimulationState], bool] | None = None,
) -> SimulationState:
    """Advance the state by n_steps.

    With a PhaseAutomaton in phases the loop mirrors MATLAB's calculationFcn:
    the start condition is checked before a block of steps and the end
    condition after it. steps_per_check is app.p.speedfactor, the number of
    simulation steps one timer tick performs; the checks do not happen in
    between, and a phase can therefore overrun its condition by up to that
    many steps. Faithful, and worth knowing when reading a phase's end time.

    on_step is called after every step — that is where the GUI will hang its
    plot refresh. stop_when ends the run early.
    """
    done = 0
    while done < n_steps:
        if phases is not None:
            phases.check_start(state)

        for _ in range(min(steps_per_check, n_steps - done)):
            organism.calculate_step(state)
            done += 1
            if on_step is not None:
                on_step(state)
            if stop_when is not None and stop_when(state):
                return state

        if phases is not None:
            phases.check_end(state)
            if phases.stop_requested:
                return state
    return state


def run_simulation(
    organism_name: str,
    p: dict[str, float],
    n_steps: int,
    *,
    dt: float = DEFAULT_DT,
    **kwargs,
) -> SimulationState:
    """Build a state and run it. The entry point the reference tests use."""
    discover_organisms()
    organism = get_organism(organism_name)
    state = build_state(p, organism, dt=dt)
    return run_steps(state, organism, n_steps, **kwargs)


def load_project_state(
    db_path: Path | str, project_id: int, *, dt: float = DEFAULT_DT
) -> tuple[SimulationState, OrganismModel]:
    """Everything a session needs, from the one read at start.

    Resumes where a stored run left off: if the project already has time
    series, they replace the organism's starting values and the index points
    at the last stored step. The import is local because core/ has no business
    depending on the database when a caller only wants run_simulation().
    """
    from ..db.project import load_phases, load_project_variables

    setup = load_phases(db_path, project_id)
    discover_organisms()

    organism_name = _organism_key(setup.info.organism_name, setup.info.function_file)
    organism = get_organism(organism_name)

    state = SimulationState(p=Namespace(dict(setup.p)), dt=dt)
    organism.initialize(state)

    stored = load_project_variables(db_path, project_id)
    if stored.n > 0:
        state.a.skipped_variables = _adopt(state, stored.t, stored.v)
        organism.initialize(state)  # rebuild a, keep v
        state.a.restarted_variables = _restart_unstored(state)

    return state, organism


def _restart_unstored(state: SimulationState) -> list[str]:
    """Give series that were never persisted their starting value back.

    A resumed state has to be complete: one NaN in it and the next ODE call
    refuses the whole vector. Some series never reach the database because
    variable_handlingTab does not assign them to the organism — among them
    xO2 and xCO2, which are ODE states. Those restart from t = 0 instead of
    continuing, which is wrong but recoverable; a NaN is neither.

    The names are returned so a caller can say so out loud rather than let a
    run continue on quietly reset states.
    """
    restarted = []
    for name, values in state.v.items():
        if not isinstance(values, np.ndarray):
            continue
        if np.isnan(values[state.idx]) and np.isfinite(values[0]):
            values[state.idx] = values[0]
            restarted.append(name)
    return sorted(restarted)


def _organism_key(display_name: str | None, function_file: str | None) -> str:
    """Map what the database calls an organism onto a registry key.

    organismTab.function_file already holds the MATLAB module name, which is
    the folder name too — "Escherichia_coli" against "escherichia_coli". The
    display name is the fallback for a row that has no function file.
    """
    for candidate in (function_file, display_name):
        if candidate:
            key = candidate.strip().replace(" ", "_").lower()
            if key:
                return key
    raise LookupError("project names no organism")


def _adopt(state: SimulationState, t: np.ndarray, v: dict[str, np.ndarray]) -> list[str]:
    """Put stored series into the state and point the index at their end.

    load_project_variables() returns every variable variable_handlingTab
    assigns to the organism, and that table is wider than the models are:
    E. coli is credited with cP1X, VR2, VR3, FR2, FR3 and the whole Pichia AOX
    set, none of which its balance equations produce. Those columns come back
    empty. Adopting them would put an all-NaN series into the state and the
    next ODE call would refuse it.

    So a stored series is taken when the model declared it, or when it carries
    at least one real value — data from an older model version is not thrown
    away. Everything else is reported and skipped.
    """
    n = int(t.size)
    known = set(state.v)
    adopt, skipped = {}, []
    for name, values in v.items():
        if name in known or np.any(np.isfinite(values)):
            adopt[name] = values
        else:
            skipped.append(name)

    for name in ("t", *adopt):
        state.series(name)
    state.ensure_capacity(n - 1)

    state.v.t[:n] = t
    for name, values in adopt.items():
        state.v[name][:n] = values
    state.idx = n - 1
    return sorted(skipped)
