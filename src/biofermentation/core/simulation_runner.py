"""Driving the simulation from a Qt timer (plan section 4.3).

The architectural heart of the running application, and the one piece where a
mistake shows up as an intermittent fault rather than a wrong number. It is
therefore built and tested before any larger window exists.

Importing this module pulls in PySide6. Nothing else in core/ does — a
headless run goes through core/runner.py and needs no Qt at all.

The guard flag is carried over from the MATLAB version. A timer tick and a UI
callback both write to the same state: the tick advances the simulation, the
callback changes a setpoint or a mode. In MATLAB that produced a parameter
read half-updated, and the fix was a flag the tick checks before it touches
anything. Here the flag is a context manager, so it cannot be left set by an
exception in the callback.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QObject, QTimer, Signal

from ..organisms.base import OrganismModel
from .state import SimulationState


class SimulationRunner(QObject):
    """Advances a SimulationState on a timer, in the GUI thread.

    One tick performs speedfactor steps, which is what app.p.speedfactor did:
    the display refreshes at a comfortable rate while the simulation runs
    faster than real time. The phase automaton is checked once before and once
    after the block, exactly as MATLAB's calculationFcn does it.
    """

    step_completed = Signal(int)  # index of the step just written
    block_completed = Signal(int)  # end of a tick, for the plot refresh
    phase_started = Signal(int)
    phase_ended = Signal(int)
    stopped = Signal(str)  # reason
    failed = Signal(str)  # message of an exception in a step

    def __init__(
        self,
        organism: OrganismModel,
        state: SimulationState,
        *,
        phases=None,
        speedfactor: int = 1,
        interval_ms: int = 100,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.organism = organism
        self.state = state
        self.phases = phases
        self.speedfactor = max(1, int(speedfactor))

        self._busy = False  # a UI callback is editing the state
        self._ticking = False  # re-entrancy guard for the tick itself

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------ state --

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    @property
    def interval_ms(self) -> int:
        return self._timer.interval()

    def set_interval(self, interval_ms: int) -> None:
        self._timer.setInterval(interval_ms)

    def set_speedfactor(self, speedfactor: int) -> None:
        self.speedfactor = max(1, int(speedfactor))

    # ----------------------------------------------------------- control --

    def start(self) -> None:
        self._timer.start()

    def pause(self) -> None:
        self._timer.stop()

    def stop(self, reason: str = "stopped") -> None:
        self._timer.stop()
        self.stopped.emit(reason)

    @contextmanager
    def editing(self) -> Iterator[SimulationState]:
        """Hold the state still while a UI callback changes it.

        A tick that fires inside this block does nothing and comes back on the
        next interval. Losing a tick is invisible; a half-written parameter
        set is not.
        """
        self._busy = True
        try:
            yield self.state
        finally:
            self._busy = False

    # -------------------------------------------------------------- tick --

    def _on_tick(self) -> None:
        if self._busy or self._ticking:
            return
        self._ticking = True
        try:
            self._run_block()
        finally:
            self._ticking = False

    def _run_block(self) -> None:
        if self.phases is not None:
            started = self.phases.check_start(self.state)
            if started is not None:
                self.phase_started.emit(started)
            if self.phases.stop_requested:
                self.stop("stop phase")
                return

        for _ in range(self.speedfactor):
            try:
                self.organism.calculate_step(self.state)
            # Reported through the failed signal rather than swallowed: a
            # simulation that dies must not take the window with it.
            except Exception as error:
                self.pause()
                self.failed.emit(f"{type(error).__name__}: {error}")
                return
            self.step_completed.emit(self.state.idx)

        if self.phases is not None:
            ended = self.phases.check_end(self.state)
            if ended is not None:
                self.phase_ended.emit(ended)

        self.block_completed.emit(self.state.idx)

        if self.phases is not None and self.phases.stop_requested:
            self.stop("stop phase")
