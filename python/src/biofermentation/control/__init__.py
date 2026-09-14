"""Phase automaton and controllers — phase 3."""

from .batch_end import BatchEndDetector, sliding_median, theil_sen_slope
from .phases import (
    OPERATORS,
    PHASE_PARAMETERS,
    EndCondition,
    PhaseAutomaton,
    PhaseStatus,
    PhaseType,
    StartCondition,
)

__all__ = [
    "OPERATORS",
    "PHASE_PARAMETERS",
    "BatchEndDetector",
    "EndCondition",
    "PhaseAutomaton",
    "PhaseStatus",
    "PhaseType",
    "StartCondition",
    "sliding_median",
    "theil_sen_slope",
]
