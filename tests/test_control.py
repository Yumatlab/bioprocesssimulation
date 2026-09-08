"""Phase state machine tests - phase 3.

A phase sequence is simulated without any GUI and the transitions are checked
against the MATLAB semantics documented in the MATLAB CLAUDE.md:
status 1 = upcoming, 2 = pending, 3 = active, 4 = ended.
"""

import pytest


def test_phase_transitions():
    pytest.skip("phase 3 - state machine not implemented yet")
