"""Containers the data layer hands out and takes back (plan section 1.2).

Field names follow the MATLAB model on purpose — p, v, phases, statusID,
reservoirID — so a value can be traced from the reference implementation to
here without a translation table. See CLAUDE.md, "Namensgebung".
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Condition:
    """Start or end condition of a phase.

    typeID points at process_conditiontypeTab — start conditions carry
    start_end = 1 (1 variable condition, 2 previous phase ended, 3 batch end
    detection), end conditions start_end = 2 (5 next phase starts, 6 variable
    condition, 7 timer). Until the schema migration of plan 1.1 the foreign
    key claimed process_typeTab instead.

    time is None as long as the phase has not started or ended yet.
    """

    typeID: int | None = None
    variableID: int | None = None
    operatorID: int | None = None
    value: float | None = None
    time: float | None = None


@dataclass
class Phase:
    """One row of processTab plus its process_parameterTab rows.

    statusID: 1 upcoming, 2 pending, 3 active, 4 completed.
    typeID:   1 manual, 2 stop, 3 update parameter set, 4 pulse feed,
              5 exponential feed.
    """

    processID: int
    projectID: int
    statusID: int | None = None
    typeID: int | None = None
    name: str | None = None
    reservoirID: int | None = None
    start: Condition = field(default_factory=Condition)
    end: Condition = field(default_factory=Condition)
    parameters: dict[str, float] = field(default_factory=dict)


@dataclass
class ProjectInfo:
    """projectTab joined with the organism, bioreactor and model it names."""

    projectID: int
    name: str | None
    description: str | None
    author: str | None
    created_on: str | None
    recent_use: str | None
    organismID: int | None
    organism_name: str | None
    function_file: str | None
    initialization_file: str | None
    reservoirs: int | None
    bioreactorID: int | None
    bioreactor_name: str | None
    modelID: int | None


@dataclass
class Lookups:
    """The reference tables the phase editors need in memory.

    Read once at session start together with everything else, because no
    editor is allowed to touch the database while a simulation runs.
    """

    process_status: list[dict]
    process_type: list[dict]
    process_variable: list[dict]
    process_operator: list[dict]
    start_conditiontype: list[dict]
    end_conditiontype: list[dict]


@dataclass
class ProjectSetup:
    """What load_phases() returns — the whole session in one read.

    p              parameter values, keyed by parameter name
    p_meta         one entry per parameter with tex, unit, type, category
    p_meta_cyclic  the subset with reading_rate = 'cyclic'
    p_modes        parameter_controlmodesTab, for the dropdowns
    """

    info: ProjectInfo
    p: dict[str, float]
    p_meta: list[dict]
    p_meta_cyclic: list[dict]
    p_modes: list[dict]
    phases: list[Phase]
    lookups: Lookups
    next_process_id: int


@dataclass
class VariableSeries:
    """The stored time series of a project, as loaded for a resumed session.

    v holds one array per variable name, t the process time in hours, and
    real_t the wall-clock timestamps. All arrays have length n; missing
    values are NaN, never 0.
    """

    t: np.ndarray
    v: dict[str, np.ndarray]
    real_t: list[str]

    @property
    def n(self) -> int:
        return int(self.t.size)
