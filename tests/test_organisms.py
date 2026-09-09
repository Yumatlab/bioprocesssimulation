"""Organism model tests (plan sections 2.1 to 2.4).

The decisive test is the comparison against a MATLAB reference run. Until
tests/reference_data/ecoli_reference.csv exists it skips rather than silently
passing — a port verified against nothing is not verified. Everything else
here checks structure and plausibility, which catches a broken translation
but never proves a correct one.

See tests/reference_data/README.md for the export format.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest

from biofermentation.core.runner import build_state, load_project_state, run_simulation
from biofermentation.db import load_phases
from biofermentation.organisms import (
    OrganismMetadata,
    OrganismModel,
    available_organisms,
    discover_organisms,
    get_organism,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
REFERENCE_DIR = Path(__file__).resolve().parent / "reference_data"
ECOLI_REFERENCE = REFERENCE_DIR / "ecoli_reference.csv"
PICHIA_REFERENCE = REFERENCE_DIR / "pichia_reference.csv"

# Variables compared first; a deviation here points at the balance equations
# rather than at a controller detail.
CORE_COLUMNS = ["cXL", "cS1L", "pO2", "pHL", "thetaL", "VL"]

# Projects in the template that carry a full parameter set.
ECOLI_PROJECT = 716
PICHIA_PROJECT = 519


@pytest.fixture(scope="module")
def registry():
    return discover_organisms()


def _parameters(project_id: int, **overrides) -> dict[str, float]:
    p = dict(load_phases(TEMPLATE_DB, project_id).p)
    p.update(overrides)
    return p


def _growing(project_id: int) -> dict[str, float]:
    """A parameter set with cells in the reactor, so the kinetics do work."""
    return _parameters(project_id, f_Inoc=1.0, f_InocStart=1.0)


# ------------------------------------------------- registry, plan 2.2 --


def test_registry_discovers_both_organisms(registry):
    assert set(registry) == {"escherichia_coli", "pichia_pastoris"}


def test_discovery_is_idempotent(registry):
    assert discover_organisms() == registry == available_organisms()


def test_get_organism_returns_a_fresh_instance(registry):
    first, second = get_organism("escherichia_coli"), get_organism("escherichia_coli")
    assert first is not second
    assert isinstance(first, OrganismModel)


def test_unknown_organism_names_the_ones_it_knows():
    with pytest.raises(LookupError, match="escherichia_coli"):
        get_organism("saccharomyces_cerevisiae")


def test_metadata_matches_the_database(registry):
    """organismTab.reservoirs and the plugin must not drift apart."""
    with __import__("sqlite3").connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        rows = dict(conn.execute("SELECT function_file, reservoirs FROM organismTab"))
    by_key = {key.lower(): value for key, value in rows.items()}
    for name, cls in registry.items():
        assert by_key[name] == cls.metadata.n_reservoirs, name


def test_a_second_model_cannot_claim_a_taken_name(registry):
    from biofermentation.organisms.registry import register

    class Impostor(OrganismModel):
        metadata = OrganismMetadata(
            name="escherichia_coli", display_name="Impostor", n_reservoirs=1
        )

        def init_controller_states(self, state): ...
        def init_physical_constants(self, state): ...
        def init_kinetics(self, state): ...
        def init_variables(self, state): ...
        def calculate_step(self, state): ...

    with pytest.raises(ValueError, match="claim the name"):
        register(Impostor)


def test_the_abstract_base_cannot_be_instantiated():
    with pytest.raises(TypeError):
        OrganismModel()


# --------------------------------------------- initialisation, plan 2.1 --


@pytest.mark.parametrize(
    ("organism", "project"),
    [("escherichia_coli", ECOLI_PROJECT), ("pichia_pastoris", PICHIA_PROJECT)],
)
def test_initialisation_fills_all_three_containers(registry, organism, project):
    state = build_state(_parameters(project), get_organism(organism))
    assert len(state.v) > 60, "variable series"
    assert len(state.a) > 60, "controller states and derived constants"
    assert state.idx == 0
    # Derived constants of the bioreactor physics
    for name in ("cOL100", "cOLmax", "tauD", "ApH", "pGw"):
        assert np.isfinite(state.a[name]), name


@pytest.mark.parametrize(
    ("organism", "project"),
    [("escherichia_coli", ECOLI_PROJECT), ("pichia_pastoris", PICHIA_PROJECT)],
)
def test_every_starting_value_is_finite(registry, organism, project):
    state = build_state(_parameters(project), get_organism(organism))
    bad = sorted(n for n, s in state.v.items() if not np.isfinite(s[0]))
    assert bad == [], f"NaN at t=0 in {bad}"


def test_inoculation_flag_decides_the_starting_biomass(registry):
    without = build_state(
        _parameters(ECOLI_PROJECT, f_InocStart=0.0), get_organism("escherichia_coli")
    )
    with_cells = build_state(_growing(ECOLI_PROJECT), get_organism("escherichia_coli"))
    assert without.v.cXL[0] == 0.0
    assert with_cells.v.cXL[0] == with_cells.p.cXL0 > 0


def test_pichia_has_the_second_reservoir_and_e_coli_does_not(registry):
    pichia = build_state(_parameters(PICHIA_PROJECT), get_organism("pichia_pastoris"))
    ecoli = build_state(_parameters(ECOLI_PROJECT), get_organism("escherichia_coli"))
    assert "FR2" in pichia.v and "VR2" in pichia.v
    assert "FR2" not in ecoli.v
    # Acetate is E. coli's third substrate; Pichia has none.
    assert "cS3L" in ecoli.v and "cS3L" not in pichia.v
    # The AOX machinery is Pichia's alone.
    assert "qS2pXact" in pichia.v and "qS2pXact" not in ecoli.v


# ------------------------------------------------------ steps, plan 2.4 --


@pytest.mark.parametrize(
    ("organism", "project"),
    [("escherichia_coli", ECOLI_PROJECT), ("pichia_pastoris", PICHIA_PROJECT)],
)
def test_a_step_advances_time_by_exactly_dt(registry, organism, project):
    model = get_organism(organism)
    state = build_state(_growing(project), model, dt=0.005)
    model.calculate_step(state)
    assert state.idx == 1
    assert state.v.t[1] == pytest.approx(0.005)


@pytest.mark.parametrize(
    ("organism", "project"),
    [("escherichia_coli", ECOLI_PROJECT), ("pichia_pastoris", PICHIA_PROJECT)],
)
def test_a_run_stays_finite_and_non_negative(registry, organism, project):
    state = run_simulation(organism, _growing(project), 200)
    end = state.idx + 1
    # Concentrations the ODE clamps at zero must never come back negative.
    for name in ("cXL", "cS1L", "cOL", "VL", "kLa"):
        values = state.v[name][:end]
        assert np.all(np.isfinite(values)), f"{name} went non-finite"
        assert np.all(values >= 0), f"{name} went negative"


def test_ecoli_consumes_glucose_and_grows(registry):
    """Plausibility, not verification: a batch has to look like a batch."""
    state = run_simulation("escherichia_coli", _growing(ECOLI_PROJECT), 600)
    end = state.idx
    assert state.v.cXL[end] > state.v.cXL[0], "no growth"
    assert state.v.cS1L[end] < state.v.cS1L[0], "glucose not consumed"
    # Acetate is the product and is fed back as the third substrate.
    assert state.v.cP1L[end] > 0


def test_pichia_expresses_only_once_glycerol_is_gone(registry):
    """VS1rep represses the AOX promoter while glycerol is present."""
    p = _growing(PICHIA_PROJECT)
    state = run_simulation("pichia_pastoris", p, 200)
    end = state.idx
    assert state.v.cS1L[end] > 0, "glycerol still present in this window"
    assert state.v.qP1pX[end] < 1e-10, "expression must stay repressed"


def test_preallocation_slots_do_not_leak_into_the_result(registry):
    state = run_simulation("escherichia_coli", _growing(ECOLI_PROJECT), 50)
    trimmed = state.trimmed()
    assert len(trimmed["cXL"]) == 51
    assert not np.isnan(trimmed["cXL"]).any()


def test_the_model_keeps_no_state_of_its_own(registry):
    """Two runs of one instance must not influence each other."""
    model = get_organism("escherichia_coli")
    first = build_state(_growing(ECOLI_PROJECT), model)
    second = build_state(_growing(ECOLI_PROJECT), model)
    for _ in range(20):
        model.calculate_step(first)
    for _ in range(20):
        model.calculate_step(second)
    assert first.v.cXL[20] == second.v.cXL[20]


def test_a_run_is_reproducible(registry):
    a = run_simulation("escherichia_coli", _growing(ECOLI_PROJECT), 100)
    b = run_simulation("escherichia_coli", _growing(ECOLI_PROJECT), 100)
    assert np.array_equal(a.trimmed()["cXL"], b.trimmed()["cXL"])


def test_run_steps_can_be_stopped_early(registry):
    state = run_simulation(
        "escherichia_coli", _growing(ECOLI_PROJECT), 500, stop_when=lambda s: s.v.t[s.idx] >= 0.05
    )
    assert state.idx < 500
    assert state.v.t[state.idx] >= 0.05


def test_on_step_sees_every_step(registry):
    seen = []
    run_simulation(
        "escherichia_coli", _growing(ECOLI_PROJECT), 10, on_step=lambda s: seen.append(s.idx)
    )
    assert seen == list(range(1, 11))


# ------------------------------------------------------- resuming a run --


def test_a_stored_run_is_resumed_where_it_stopped(registry, tmp_path):
    """The state comes back from the database, not from the starting values."""
    from biofermentation.db import save_project
    from biofermentation.db.models import VariableSeries

    db = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, db)

    state = run_simulation("escherichia_coli", _growing(ECOLI_PROJECT), 20)
    series = VariableSeries(
        t=state.trimmed()["t"], v=state.trimmed(), real_t=[""] * (state.idx + 1)
    )
    save_project(db, ECOLI_PROJECT, series=series)

    resumed, model = load_project_state(db, ECOLI_PROJECT)
    assert resumed.idx == state.idx
    assert resumed.v.cXL[resumed.idx] == pytest.approx(state.v.cXL[state.idx])

    # A resumed state must be complete, or the next ODE call refuses it.
    gaps = sorted(n for n, s in resumed.v.items() if np.isnan(s[resumed.idx]))
    assert gaps == [], f"a resumed state must be complete, missing {gaps}"

    # The series the database does not store for this organism restart from
    # t = 0, and the state says which ones rather than hiding it.
    assert "xO2" in resumed.a.restarted_variables
    assert "cXL" not in resumed.a.restarted_variables

    model.calculate_step(resumed)
    assert resumed.idx == state.idx + 1


@pytest.mark.xfail(
    reason="variable_handlingTab assigns neither organism the offgas fractions, "
    "OTRmax, OURmax or the setpoint series; see docs and CLAUDE.md",
    strict=True,
)
def test_the_database_knows_every_variable_the_models_compute(registry):
    """variable_handlingTab is out of step with both models, in both directions.

    Seven E. coli series and six Pichia series are computed but assigned to no
    organism, so save_project never writes them and a resumed run silently
    restarts them from their starting values. Two of them, xO2 and xCO2, are
    ODE states — the offgas fractions — which makes this a correctness problem,
    not a reporting one. The other direction is harmless by comparison:
    E. coli is credited with 19 Pichia variables it has no balance for.

    Marked strict so it turns into a failure the moment the assignment is
    corrected, the same way the phase 1.1 foreign key defect was held.
    """
    import sqlite3

    with sqlite3.connect(f"file:{TEMPLATE_DB}?mode=ro", uri=True) as conn:
        assigned = {
            organism: {
                row[0]
                for row in conn.execute(
                    "SELECT v.name FROM variable_handlingTab h "
                    "JOIN variableTab v USING (variableID) WHERE h.organismID = ?",
                    (organism,),
                )
            }
            for organism in (1, 2)
        }

    unsaved = {}
    for organism, (name, project) in {
        1: ("escherichia_coli", ECOLI_PROJECT),
        2: ("pichia_pastoris", PICHIA_PROJECT),
    }.items():
        state = run_simulation(name, _growing(project), 3)
        unsaved[name] = sorted(set(state.v) - assigned[organism] - {"t"})

    assert unsaved == {"escherichia_coli": [], "pichia_pastoris": []}, (
        f"these series are computed but never persisted: {unsaved}"
    )


# ----------------------------------------- MATLAB reference, plan 2.4 --


def _load_reference(prefix: str):
    pd = pytest.importorskip("pandas")
    series = pd.read_csv(REFERENCE_DIR / f"{prefix}_reference.csv")
    parameters = pd.read_csv(REFERENCE_DIR / f"{prefix}_reference_p.csv")
    meta = pd.read_csv(REFERENCE_DIR / f"{prefix}_reference_meta.csv").set_index("key")["value"]
    p = dict(zip(parameters["name"], parameters["value"].astype(float), strict=True))
    return series, p, float(meta["deltat"]), int(float(meta["steps"]))


def _compare(organism: str, prefix: str) -> None:
    reference, p, dt, steps = _load_reference(prefix)
    state = run_simulation(organism, p, steps - 1, dt=dt)
    result = state.trimmed()

    missing = [c for c in CORE_COLUMNS if c not in reference.columns]
    assert missing == [], f"reference run lacks {missing}"

    for column in CORE_COLUMNS:
        np.testing.assert_allclose(
            result[column][: len(reference)],
            reference[column].to_numpy(),
            rtol=1e-4,
            atol=1e-6,
            err_msg=f"deviation in {column}",
        )


@pytest.mark.reference
@pytest.mark.skipif(not ECOLI_REFERENCE.is_file(), reason="no E. coli reference run yet")
def test_ecoli_matches_matlab_reference():
    _compare("escherichia_coli", "ecoli")


@pytest.mark.reference
@pytest.mark.skipif(not PICHIA_REFERENCE.is_file(), reason="no Pichia reference run yet")
def test_pichia_matches_matlab_reference():
    _compare("pichia_pastoris", "pichia")
