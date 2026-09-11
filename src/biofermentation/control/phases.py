"""The phase automaton (plan section 3).

Translated from ControlApp.mlapp: conditionCheck, evaluateCondition,
checkStartCondition, checkEndCondition, processPhaseActions,
applyPhaseParameters, handlePulseFeed and handleExponentialFeed.

MATLAB builds the comparison as a string and hands it to eval(). Python needs
neither: the variable is looked up by name in the state and the operator maps
to a function. Same behaviour, no code assembled at runtime.

The Phase and Condition containers are the ones the database layer already
returns — see db/models.py. A phase read from processTab, run through the
automaton and written back by save_project is the same object throughout.
"""

import operator
from collections.abc import Callable
from enum import IntEnum

from ..core.state import SimulationState
from ..db.models import Phase
from .batch_end import BatchEndDetector


class PhaseStatus(IntEnum):
    """processTab.process_statusID, as process_statusTab defines it."""

    UPCOMING = 1
    PENDING = 2
    ACTIVE = 3
    COMPLETED = 4


class PhaseType(IntEnum):
    """processTab.process_typeID, as process_typeTab defines it."""

    MANUAL = 1  # "Batch" in the editor; does nothing on its own
    STOP = 2
    PARAMETER_UPDATE = 3
    PULSE_FEED = 4
    EXPONENTIAL_FEED = 5


#: What a phase of this type works from, `{n}` standing for its reservoir.
#: Kept next to the handlers that read them so the two cannot drift: the
#: exponential feed computes FRj from the first four and is then limited by
#: FRmax, the pulse feed multiplies the two it names. A parameter update
#: takes anything, and the other types take nothing.
#:
#: Not in it: t{n}j, cXL{n}j and FR{n}j. Those are results — the phase writes
#: them when it starts, and offering them for editing would be offering to
#: overwrite its own record.
PHASE_PARAMETERS: dict[int, tuple[str, ...]] = {
    PhaseType.EXPONENTIAL_FEED: ("qXpX{n}w", "qS{n}pXm", "yXpS{n}gr", "cS{n}R{n}", "FR{n}max"),
    PhaseType.PULSE_FEED: ("kR{n}", "FR{n}max"),
}


class StartCondition(IntEnum):
    """process_conditiontypeTab rows with start_end = 1."""

    VARIABLE = 1
    PREVIOUS_ENDED = 2
    BATCH_END = 3


class EndCondition(IntEnum):
    """process_conditiontypeTab rows with start_end = 2."""

    NEXT_PHASE_STARTS = 5
    VARIABLE = 6
    TIMER = 7


# process_operatorTab stores the operator column as >=, <=, >, < and =.
# MATLAB's switch tests for "==" and "~=" and therefore never matches the "="
# the database actually holds — an equality condition silently never fired.
# Both spellings are accepted here.
OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "≥": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "≤": operator.le,
    "=": operator.eq,
    "==": operator.eq,
    "!=": operator.ne,
    "~=": operator.ne,
    "≠": operator.ne,
}


class PhaseAutomaton:
    """Drives a list of phases against a running simulation.

    One instance per simulation. It owns what MATLAB kept on the app object:
    which phase is active, the two feed switches the organism models read out
    of state.a, and the hysteresis counter of the batch end detector.
    """

    def __init__(
        self,
        phases: list[Phase],
        *,
        variable_names: dict[int, str] | None = None,
        operator_symbols: dict[int, str] | None = None,
        detector: BatchEndDetector | None = None,
    ):
        self.phases = phases
        self.current: int | None = None
        self.stop_requested = False
        self.log: list[str] = []
        self._drained = 0
        self.detector = detector or BatchEndDetector()

        # variableID -> name and operatorID -> symbol, from the lookup tables
        # load_phases reads once at session start.
        self.variable_names = variable_names or {}
        self.operator_symbols = operator_symbols or {}

    # ----------------------------------------------------------- lookups --

    @classmethod
    def from_setup(cls, setup, **kwargs) -> "PhaseAutomaton":
        """Build from what load_phases() returned, resuming where it stopped."""
        automaton = cls(
            setup.phases,
            variable_names={
                row["variableID"]: row["name"] for row in setup.lookups.process_variable
            },
            operator_symbols={
                row["process_operatorID"]: row["operator"] for row in setup.lookups.process_operator
            },
            **kwargs,
        )
        automaton.adopt_active_phase()
        return automaton

    def adopt_active_phase(self) -> int | None:
        """Pick up a phase that was running when the project was last saved.

        processTab stores the status of every phase, so a reloaded project
        knows which one was active. Without this the automaton starts blank,
        finds no PENDING phase, and puts the *next* one to PENDING instead —
        the running phase is silently restarted, its start time overwritten
        and its actions applied a second time.
        """
        self.current = next(
            (
                index
                for index, phase in enumerate(self.phases)
                if phase.statusID == PhaseStatus.ACTIVE
            ),
            None,
        )
        return self.current

    # -------------------------------------------------------- conditions --

    def evaluate_condition(self, state: SimulationState, variableID, operatorID, threshold) -> bool:
        """Compare one variable against a threshold. MATLAB's evaluateCondition."""
        if variableID is None or operatorID is None or threshold is None:
            return False

        name = self.variable_names.get(variableID)
        if name is None:
            self._note(f"variableID {variableID} is not a process variable")
            return False

        series = state.v.get(name)
        if series is None:
            self._note(f"variable {name!r} is not in the simulation state")
            return False

        symbol = self.operator_symbols.get(operatorID)
        compare = OPERATORS.get(symbol)
        if compare is None:
            self._note(f"operatorID {operatorID} maps to unknown operator {symbol!r}")
            return False

        return bool(compare(series[state.idx], threshold))

    def condition_check(self, state: SimulationState, which: str, index: int) -> bool:
        """MATLAB's conditionCheck, for the start or the end of a phase."""
        phase = self.phases[index]

        if which == "start":
            match phase.start.typeID:
                case StartCondition.VARIABLE:
                    return self.evaluate_condition(
                        state, phase.start.variableID, phase.start.operatorID, phase.start.value
                    )
                case StartCondition.PREVIOUS_ENDED:
                    return True
                case StartCondition.BATCH_END:
                    return self.detector.detect(state)
                case _:
                    self._note(f"unknown start condition type {phase.start.typeID}")
                    return False

        match phase.end.typeID:
            case EndCondition.NEXT_PHASE_STARTS:
                # Recurses into the next phase's start condition.
                if index + 1 < len(self.phases):
                    return self.condition_check(state, "start", index + 1)
                return False
            case EndCondition.VARIABLE:
                return self.evaluate_condition(
                    state, phase.end.variableID, phase.end.operatorID, phase.end.value
                )
            case EndCondition.TIMER:
                # bool(): the comparison of a numpy scalar yields np.bool_,
                # which is not `is True`. Callers should not have to know.
                return phase.end.time is not None and bool(state.v.t[state.idx] >= phase.end.time)
            case _:
                self._note(f"unknown end condition type {phase.end.typeID}")
                return False

    # ------------------------------------------------------ transitions --

    def check_start(self, state: SimulationState) -> int | None:
        """Start the next phase if its condition is met. Returns its index."""
        if self.current is not None or not self.phases:
            return None

        statuses = [phase.statusID for phase in self.phases]
        if all(status == PhaseStatus.COMPLETED for status in statuses):
            return None

        index = next(
            (i for i, status in enumerate(statuses) if status == PhaseStatus.PENDING), None
        )
        if index is None:
            ended = [i for i, status in enumerate(statuses) if status == PhaseStatus.COMPLETED]
            if ended:
                if ended[-1] == len(self.phases) - 1:
                    return None
                index = ended[-1] + 1
            else:
                index = 0
            self.phases[index].statusID = PhaseStatus.PENDING

        if not self.condition_check(state, "start", index):
            return None

        phase = self.phases[index]
        phase.statusID = PhaseStatus.ACTIVE
        phase.start.time = float(state.v.t[state.idx])

        # A timer phase gets its end stamped from its start.
        if phase.end.typeID == EndCondition.TIMER:
            phase.end.time = phase.start.time + (phase.end.value or 0.0)

        self._note(f"{phase.name} [Phase {index + 1}] started at t = {phase.start.time:.3f} h")
        self._process_actions(state, index)
        self.current = index
        return index

    def check_end(self, state: SimulationState) -> int | None:
        """End the active phase if its condition is met. Returns its index."""
        if self.current is None:
            return None

        index = self.current
        phase = self.phases[index]

        # A phase whose status was forced to COMPLETED ends regardless.
        if (
            not self.condition_check(state, "end", index)
            and phase.statusID != PhaseStatus.COMPLETED
        ):
            return None

        phase.statusID = PhaseStatus.COMPLETED
        phase.end.time = float(state.v.t[state.idx])
        self._note(f"{phase.name} [Phase {index + 1}] ended at t = {phase.end.time:.3f} h")

        if index + 1 < len(self.phases):
            self.phases[index + 1].statusID = PhaseStatus.PENDING

        self.current = None
        state.a.switch_exp = False
        state.a.switch_pulse = False
        return index

    def release_stop(self, state: SimulationState) -> int | None:
        """Finish the stop phase the process is standing on. Returns its index.

        A stop phase has no end condition — the process is halted, so no
        condition on it could ever be met (see the phase editor). It is
        therefore ended from the outside, when the operator presses Run again.
        The next phase goes to PENDING and starts when *its* start condition
        is met, exactly like any other transition.
        """
        self.stop_requested = False
        index = self.current
        if index is None:
            return None

        phase = self.phases[index]
        phase.statusID = PhaseStatus.COMPLETED
        phase.end.time = float(state.v.t[state.idx])
        self._note(f"{phase.name} [Phase {index + 1}] released at t = {phase.end.time:.3f} h")

        if index + 1 < len(self.phases):
            self.phases[index + 1].statusID = PhaseStatus.PENDING

        self.current = None
        state.a.switch_exp = False
        state.a.switch_pulse = False
        return index

    # ---------------------------------------------------------- actions --

    def _process_actions(self, state: SimulationState, index: int) -> None:
        match self.phases[index].typeID:
            case PhaseType.MANUAL:
                return
            case PhaseType.STOP:
                self.stop_requested = True
            case PhaseType.PARAMETER_UPDATE:
                self._apply_parameters(state, index)
            case PhaseType.PULSE_FEED:
                self._pulse_feed(state, index)
            case PhaseType.EXPONENTIAL_FEED:
                self._exponential_feed(state, index)
            case _:
                self._note(f"unknown phase type {self.phases[index].typeID}")

    def _apply_parameters(self, state: SimulationState, index: int) -> None:
        """Copy the phase's parameters into p. Only names p already knows."""
        for name, value in self.phases[index].parameters.items():
            if name in state.p:
                old = state.p[name]
                state.p[name] = value
                self._note(f"parameter {name} changed from {old} to {value}")

    def _reservoir(self, state: SimulationState, index: int) -> int:
        reservoir = self.phases[index].reservoirID or 1
        return min(int(reservoir), int(state.a.numReservoir))

    def _pulse_feed(self, state: SimulationState, index: int) -> None:
        self._apply_parameters(state, index)
        state.a.switch_pulse = True
        state.p.R_feed = self._reservoir(state, index)
        n = int(state.p.R_feed)
        rate = state.p[f"kR{n}"] * state.p[f"FR{n}max"]
        # MATLAB logs f_feed as going from 1 to 0 here but never assigns it;
        # ParameterChangedFcn only writes to the log. Reproduced.
        self._note(f"pulse feed R{n}: FR = {rate:.3f} l/h")

    def _exponential_feed(self, state: SimulationState, index: int) -> None:
        """Open loop feed. Freezes the starting point into p and the phase."""
        self._apply_parameters(state, index)
        state.a.switch_exp = True
        state.p.R_feed = self._reservoir(state, index)
        n = int(state.p.R_feed)

        t_start = float(state.v.t[state.idx])
        cXL_start = float(state.v.cXL[state.idx])
        state.p[f"t{n}j"] = t_start
        state.p[f"cXL{n}j"] = cXL_start

        qXpXw = state.p[f"qXpX{n}w"]
        qSpXm = state.p[f"qS{n}pXm"]
        yXpSgr = state.p[f"yXpS{n}gr"]
        cSR = state.p[f"cS{n}R{n}"]
        FRj = ((qXpXw + qSpXm * yXpSgr) * state.v.VL[state.idx] * cXL_start) / (yXpSgr * cSR)
        state.p[f"FR{n}j"] = FRj

        # savePhases writes these back, so the phase carries its own history.
        self.phases[index].parameters[f"t{n}j"] = t_start
        self.phases[index].parameters[f"cXL{n}j"] = cXL_start
        self.phases[index].parameters[f"FR{n}j"] = FRj

        # The whole parameter set the open loop rests on, as the MATLAB
        # version writes it: without it there is no telling afterwards what
        # the feed profile was computed from.
        self._note(
            "\n".join(
                (
                    f"Open loop feed R{n}",
                    f"  qXpX{n}w  = {qXpXw:.4g} 1/h     (growth rate setpoint)",
                    f"  qS{n}pXm  = {qSpXm:.4g} 1/h     (maintenance)",
                    f"  yXpS{n}gr = {yXpSgr:.4g}         (yield)",
                    f"  cS{n}R{n}   = {cSR:.4g} g/l     (reservoir)",
                    f"  VLj      = {float(state.v.VL[state.idx]):.4g} l",
                    f"  cXLj     = {cXL_start:.4g} g/l",
                    f"  t{n}j      = {t_start:.4g} h",
                    f"  FR{n}j     = {FRj:.4g} l/h      (initial feed rate)",
                )
            )
        )

    def drain_log(self) -> list[str]:
        """The notes written since the last call.

        The automaton knows things the window cannot reconstruct — which
        reservoir a feed drew from, what the open loop was parameterised
        with. It cannot emit a Qt signal, so it collects and the window
        collects from it after every block.
        """
        fresh = self.log[self._drained :]
        self._drained = len(self.log)
        return fresh

    def _note(self, message: str) -> None:
        self.log.append(message)
