"""Organism model tests.

The decisive test is the comparison against a MATLAB reference run. Until
tests/reference_data/ecoli_reference.csv exists, that test skips rather than
silently passing - a port verified against nothing is not verified.
See tests/reference_data/README.md for the export format.
"""

from pathlib import Path

import pytest

REFERENCE_DIR = Path(__file__).resolve().parent / "reference_data"
ECOLI_REFERENCE = REFERENCE_DIR / "ecoli_reference.csv"
PICHIA_REFERENCE = REFERENCE_DIR / "pichia_reference.csv"

# Variables compared first; a deviation here points at the balance equations
# rather than at a controller detail.
CORE_COLUMNS = ["cXL", "cS1L", "pO2", "pHL", "thetaL", "VL"]


@pytest.mark.reference
@pytest.mark.skipif(not ECOLI_REFERENCE.is_file(), reason="no E. coli reference run yet")
def test_ecoli_matches_matlab_reference():
    pytest.skip("phase 2.4 - model not ported yet")


@pytest.mark.reference
@pytest.mark.skipif(not PICHIA_REFERENCE.is_file(), reason="no Pichia reference run yet")
def test_pichia_matches_matlab_reference():
    pytest.skip("phase 2.4 - model not ported yet")


def test_registry_discovers_no_organism_yet():
    """Placeholder for phase 2.2: discover_organisms() must find both models."""
    pytest.skip("phase 2.2 - plugin registry not implemented yet")
