"""Phase automaton and controllers — phase 3."""

from .batch_end import BatchEndDetector, sliding_median, theil_sen_slope
from .phases import (
    OPERATORS,
    EndCondition,
    PhaseAutomaton,
    PhaseStatus,
    PhaseType,
    StartCondition,
)

__all__ = [
    "OPERATORS",
    "BatchEndDetector",
    "EndCondition",
    "PhaseAutomaton",
    "PhaseStatus",
    "PhaseType",
    "StartCondition",
    "sliding_median",
    "theil_sen_slope",
]
