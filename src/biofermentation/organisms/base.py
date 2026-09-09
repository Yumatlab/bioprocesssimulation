"""The contract every organism model has to fulfil (plan section 2.1).

Splitting initialisation into four steps is the redesign that came out of the
MATLAB sessions: controller states and bioreactor physics are the same for
every organism and belong in one place, only the kinetics and the starting
values are organism business. In MATLAB that separation was a recommendation
inside a 260-line script; here it is the shape of the class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..core.state import SimulationState


@dataclass(frozen=True)
class OrganismMetadata:
    """What the registry and the GUI need to know without importing the model.

    name is the key in the registry and the folder name; display_name is what
    organismTab.name holds and what a user sees.
    """

    name: str
    display_name: str
    n_reservoirs: int
    description: str = ""
    author: str = ""
    version: str = "1.0"


class OrganismModel(ABC):
    """One organism. Stateless — all state lives in the SimulationState."""

    metadata: OrganismMetadata

    # ------------------------------------------------------------ setup --

    def initialize(self, state: SimulationState) -> None:
        """Run the four initialisation steps in the order they depend on.

        Kinetics need the controller states and the physical constants to be
        there, and the starting values need all three. That order was implicit
        in the MATLAB initialisation file and is fixed here.
        """
        self.init_controller_states(state)
        self.init_physical_constants(state)
        self.init_kinetics(state)
        if state.idx == 0:
            self.init_variables(state)

    @abstractmethod
    def init_controller_states(self, state: SimulationState) -> None:
        """PID states and flags. Usually delegates to shared.py."""

    @abstractmethod
    def init_physical_constants(self, state: SimulationState) -> None:
        """Bioreactor physics — heat transfer, Henry, pH. Usually shared.py."""

    @abstractmethod
    def init_kinetics(self, state: SimulationState) -> None:
        """Growth, uptake and yield constants. Organism business."""

    @abstractmethod
    def init_variables(self, state: SimulationState) -> None:
        """Starting values of v at t = 0. Only called for a fresh run."""

    # ------------------------------------------------------------- step --

    @abstractmethod
    def calculate_step(self, state: SimulationState) -> None:
        """Advance the simulation by one step, writing at state.idx + 1.

        Reads at state.idx, writes at state.idx + 1, and leaves state.idx
        pointing at the step it just wrote.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.metadata.name}>"
