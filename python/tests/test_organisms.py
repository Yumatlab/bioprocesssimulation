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

from biofermentation.core.runner import (
    build_state,
    load_project_state,
    run_simulation,
    run_steps,
)
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
ECOLI_REFERENCE = REFERENCE_DIR / "ecoli_reference.csv.gz"
PICHIA_REFERENCE = REFERENCE_DIR / "pichia_reference.csv.gz"

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


def test_a_resumed_run_is_not_inoculated_a_second_time(registry, tmp_path):
    """Reopening an inoculated project must not throw the culture away.

    `a` is not persisted and `init_variables` only runs for a fresh state, so
    a resumed run came back with `inoc_occ` = 0 while `f_Inoc` was still 1 —
    the pair the model reads as "inoculate now". The next step replaced the
    grown cXL with cXL0 and moved the time of inoculation, which the antifoam
    timer counts from, to the moment the project was reopened. Nothing said
    so; the lamp went on and the biomass went back.
    """
    from biofermentation.db import save_project
    from biofermentation.db.models import VariableSeries

    db = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, db)

    state = run_simulation("escherichia_coli", _growing(ECOLI_PROJECT), 20)
    grown = float(state.v.cXL[state.idx])
    assert grown > float(state.p.cXL0), "the fixture did not grow, so nothing is at stake"
    save_project(
        db,
        ECOLI_PROJECT,
        p=dict(state.p),
        series=VariableSeries(
            t=state.trimmed()["t"], v=state.trimmed(), real_t=[""] * (state.idx + 1)
        ),
    )

    resumed, model = load_project_state(db, ECOLI_PROJECT)
    assert resumed.p.f_Inoc == 1
    assert resumed.a.inoc_occ == 1, "the stored biomass says it has happened"

    model.calculate_step(resumed)
    assert float(resumed.v.cXL[resumed.idx]) > grown, "the culture kept growing"


def test_a_resumed_run_recovers_when_the_culture_went_in(registry, tmp_path):
    """Inoculation during the run, not at the start: ToI is the time of it."""
    from biofermentation.db import save_project
    from biofermentation.db.models import VariableSeries

    db = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, db)

    organism = get_organism("escherichia_coli")
    state = build_state(_parameters(ECOLI_PROJECT, f_Inoc=0.0, f_InocStart=0.0), organism)
    run_steps(state, organism, 5)
    state.p.f_Inoc = 1.0  # the Inoculate button, pressed mid-run
    inoculated_after = float(state.v.t[state.idx])
    run_steps(state, organism, 5)
    assert state.a.ToI == pytest.approx(inoculated_after)

    save_project(
        db,
        ECOLI_PROJECT,
        p=dict(state.p),
        series=VariableSeries(
            t=state.trimmed()["t"], v=state.trimmed(), real_t=[""] * (state.idx + 1)
        ),
    )

    resumed, _ = load_project_state(db, ECOLI_PROJECT)
    assert resumed.a.inoc_occ == 1
    assert resumed.a.ToI == pytest.approx(inoculated_after)


def test_a_resumed_run_that_was_never_inoculated_still_can_be(registry, tmp_path):
    from biofermentation.db import save_project
    from biofermentation.db.models import VariableSeries

    db = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, db)

    organism = get_organism("escherichia_coli")
    state = build_state(_parameters(ECOLI_PROJECT, f_Inoc=0.0, f_InocStart=0.0), organism)
    run_steps(state, organism, 10)
    save_project(
        db,
        ECOLI_PROJECT,
        p=dict(state.p),
        series=VariableSeries(
            t=state.trimmed()["t"], v=state.trimmed(), real_t=[""] * (state.idx + 1)
        ),
    )

    resumed, model = load_project_state(db, ECOLI_PROJECT)
    assert resumed.a.inoc_occ == 0
    resumed.p.f_Inoc = 1.0
    model.calculate_step(resumed)
    assert float(resumed.v.cXL[resumed.idx]) == pytest.approx(float(resumed.p.cXL0))


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
#
# The plan asks for one tolerance over the whole run. That cannot work for
# this system, and the reason is worth writing down.
#
# The E. coli reference is a batch that turns into a fed batch at step 403,
# driven by a phase of a project that no longer exists. The phase is
# reconstructed — see reference_data/extract.py — so the comparison covers the
# feed as well and reaches step 903.
#
# It cannot reach further. The pH controller has a hard
# dead band, |pHw - pHL| < 0.1, and the process sits almost exactly on it: in
# 19 % of all steps MATLAB is within 1e-3 of the switching threshold. At step
# 785 a pH difference of 1.0e-04 puts MATLAB inside the band and this model
# outside, the alkali pump runs in one and not in the other, and 1016 of 2983
# steps end up deciding differently. With the feed phase in place the first
# divergence moves to step 904 and the deciding pH difference is 1.4e-05 —
# smaller, not larger, which is what amplification at a discontinuity looks
# like. Bit-exact agreement over a long horizon
# is impossible here in principle, not merely hard — no tolerance can be both
# meaningful and passable across a discontinuous switch.
#
# Tolerances below are measured, not guessed. Over steps 0..903 the state
# variables agree to 1.5e-06 or better and the measured values to 1e-11; the
# fast oxygen loop (pO2, kLa, OTR, RQ) is looser because those quantities pass
# through zero, which makes a relative bound meaningless — they get an
# absolute one. Every bound has at least a factor of two of margin.

# Balance equations and slow states. A translation error shows here first.
PRIMARY_COLUMNS = ["cXL", "cS1L", "pHL", "thetaL", "VL"]
# Fast oxygen transfer loop and the controllers driving it.
SECONDARY_COLUMNS = ["pO2", "cOL", "OUR", "OTR", "kLa", "NSt", "xOG", "RQ"]


def _reference(prefix: str):
    """Load a reference run: series, the parameters MATLAB ran with, metadata."""
    pd = pytest.importorskip("pandas")
    series = pd.read_csv(REFERENCE_DIR / f"{prefix}_reference.csv.gz")
    parameters = pd.read_csv(REFERENCE_DIR / f"{prefix}_reference_p.csv")
    meta = pd.read_csv(REFERENCE_DIR / f"{prefix}_reference_meta.csv").set_index("key")["value"]
    p = dict(zip(parameters["name"], parameters["value"].astype(float), strict=True))
    return series, p, meta


@pytest.mark.reference
@pytest.mark.skipif(not ECOLI_REFERENCE.is_file(), reason="no E. coli reference run yet")
def test_ecoli_matches_matlab_reference(registry):
    """Against MyProject_11.txt, an export the application wrote itself.

    The export carries no parameter set. Project 716 supplies it: every
    starting value of the run matches that project exactly, down to
    pG = pGcal + deltapGw * 1e5 and the agitation controller's lower clamp of
    0.3 * NStmax. Agreement to 1e-09 in the first steps confirms the choice.

    The project itself is deleted, so its feed phase is reconstructed from the
    run — see reference_data/extract.py for the derivation. With the phase in
    place the comparison reaches step 903 instead of 402 and covers the
    exponential feed; without it, this model simply stops feeding at 403 and
    the two runs are no longer the same experiment.
    """
    from biofermentation.control import (
        EndCondition,
        PhaseAutomaton,
        PhaseStatus,
        PhaseType,
        StartCondition,
    )
    from biofermentation.db.models import Condition, Phase

    reference, p, meta = _reference("ecoli")
    dt = float(meta["deltat"])
    inoculation_step = int(float(meta["inoculation_step"]))
    feed_step = int(float(meta["feed_phase_start_step"]))
    end = int(float(meta["comparison_end_step"]))

    # cXL is 0 for the first two rows and 3.0 in the third: inoculation was
    # switched on during the run, not before it.
    p = dict(p) | {"f_InocStart": 0.0, "f_Inoc": 0.0, "deltatsec": 2.0}
    model = get_organism("escherichia_coli")
    state = build_state(p, model, dt=dt)

    # variableID 61 is "t"; operatorID 1 is ">=".
    phase = Phase(
        processID=1,
        projectID=int(float(meta["projectID"])),
        statusID=PhaseStatus.UPCOMING,
        typeID=PhaseType(int(float(meta["feed_phase_type"]))),
        name="Fed Batch",
        reservoirID=int(float(meta["feed_phase_reservoir"])),
        start=Condition(
            typeID=StartCondition.VARIABLE,
            variableID=61,
            operatorID=1,
            value=float(reference["t"][feed_step]),
        ),
        end=Condition(typeID=EndCondition.TIMER, value=99.0),
    )
    automaton = PhaseAutomaton([phase], variable_names={61: "t"}, operator_symbols={1: ">="})

    for step in range(end):
        if step == inoculation_step:
            state.p.f_Inoc = 1.0
        automaton.check_start(state)
        model.calculate_step(state)
        automaton.check_end(state)

    # The reconstructed feed has to land on the run's own value. The residual
    # is 3.7e-09, which is the solver noise already present in cXL and VL —
    # handleExponentialFeed computes FRj from both.
    assert state.v.FR1[feed_step + 1] == pytest.approx(reference["FR1"][feed_step + 1], abs=1e-8)

    for column in PRIMARY_COLUMNS:
        np.testing.assert_allclose(
            state.v[column][: end + 1],
            reference[column].to_numpy()[: end + 1],
            rtol=1e-5,
            atol=1e-8,
            err_msg=f"deviation in {column}",
        )
    for column in SECONDARY_COLUMNS:
        np.testing.assert_allclose(
            state.v[column][: end + 1],
            reference[column].to_numpy()[: end + 1],
            rtol=5e-3,
            atol=1e-3,
            err_msg=f"deviation in {column}",
        )


@pytest.mark.reference
@pytest.mark.skipif(not ECOLI_REFERENCE.is_file(), reason="no E. coli reference run yet")
def test_ecoli_agrees_to_nine_digits_at_the_start(registry):
    """Before any controller switch, the two implementations are the same code.

    This is the sharpest statement the reference supports and the one that
    would break first on an index slip or a sign error. Measured over the
    first twelve steps: cXL 4.8e-09, cS1L 2.8e-09, pHL 1.3e-10, VL 4.6e-15.

    thetaL is left out on purpose — it sits at 2.7e-07, which is excellent but
    a decimal short of the rest. The temperature balance is the stiffest part
    of the system and shows MATLAB's own solver tolerance first.
    """
    reference, p, meta = _reference("ecoli")
    dt = float(meta["deltat"])
    p = dict(p) | {"f_InocStart": 0.0, "f_Inoc": 0.0}
    model = get_organism("escherichia_coli")
    state = build_state(p, model, dt=dt)
    for step in range(12):
        if step == int(float(meta["inoculation_step"])):
            state.p.f_Inoc = 1.0
        model.calculate_step(state)

    for column in ("cXL", "cS1L", "VL", "pHL"):
        np.testing.assert_allclose(
            state.v[column][:13],
            reference[column].to_numpy()[:13],
            rtol=1e-8,
            atol=1e-10,
            err_msg=f"deviation in {column}",
        )


@pytest.mark.reference
@pytest.mark.skip(
    reason="the only Pichia run predates the model it would verify: "
    "Thesis_SimulationAppDB.db is from 2 March 2025, Pichia_pastoris.m from "
    "22 April 2026. The kLa of the run does not follow the current formula, "
    "so a mismatch would say nothing about the translation."
)
def test_pichia_matches_matlab_reference(registry):
    """Kept as a fixture rather than deleted — see reference_data/README.md.

    The run itself is excellent: 14799 steps, 51 variables, the full AOX
    induction and expression chain, both reservoirs and seven phases. It is
    the natural test for the phase automaton of plan section 3, provided a
    Pichia run from the current source ever becomes available to separate a
    model change from a translation error.
    """
    reference, p, meta = _reference("pichia")
    dt = float(meta["deltat"])
    end = int(float(meta["batch_end_step"]))
    p = dict(p) | {"f_InocStart": 0.0, "f_Inoc": 0.0}
    model = get_organism("pichia_pastoris")
    state = build_state(p, model, dt=dt)
    for step in range(end):
        if step == 2:
            state.p.f_Inoc = 1.0
        model.calculate_step(state)
    for column in PRIMARY_COLUMNS:
        np.testing.assert_allclose(
            state.v[column][: end + 1],
            reference[column].to_numpy()[: end + 1],
            rtol=1e-5,
            atol=1e-8,
            err_msg=f"deviation in {column}",
        )


@pytest.mark.reference
@pytest.mark.skipif(not ECOLI_REFERENCE.is_file(), reason="no E. coli reference run yet")
def test_the_reference_run_covers_more_than_a_bare_batch():
    """A run with nothing switched on would verify very little."""
    reference, _, _ = _reference("ecoli")
    assert reference["FT1"].abs().max() > 0, "acid pump never ran"
    assert reference["FT2"].abs().max() > 0, "alkali pump never ran"
    assert reference["cS3L"].abs().max() > 0, "no acetate was formed"
    assert reference["NSt"].max() > reference["NSt"].min(), "agitation never moved"


# ----------------------------------------------- the inlet gas mixture --
#
# The gas mixing and aeration branches write FnAIR, FnO2 and their total, and
# the oxygen balance divides by that total. The originals mix a current
# setpoint with a previous flow there, which produces mixtures that cannot
# exist. Corrected in both models; these tests hold the correction.
#
# The verified E. coli window is untouched by it: the reference run is
# Mode_pO2 = 1, where no branch below is reached. See docs/ and CLAUDE.md.


def _gas_run(organism: str, project: int, mode: float, steps: int = 1500):
    model = get_organism(organism)
    p = _parameters(project, f_Inoc=1.0, f_InocStart=1.0, deltatsec=2.0, Mode_pO2=mode)
    state = build_state(p, model, dt=2 / 3600)
    run_steps(state, model, steps)
    return state, p


PO2_MODES = [
    (organism, project, mode)
    for organism, project in (
        ("escherichia_coli", ECOLI_PROJECT),
        ("pichia_pastoris", PICHIA_PROJECT),
    )
    for mode in (0.0, 1.0, 2.0, 3.0)
]


@pytest.mark.parametrize(("organism", "project", "mode"), PO2_MODES)
def test_the_inlet_gas_is_a_mixture_that_could_exist(registry, organism, project, mode):
    """Air and oxygen only, so the oxygen fraction cannot leave [xOAIR, 1].

    Before the correction it reached -0.48: the oxygen flow was computed as
    FnGw minus the *previous* step's air flow.
    """
    state, p = _gas_run(organism, project, mode)
    stop = state.idx + 1
    fraction = np.asarray(state.v.xOGin[:stop], dtype=float)

    assert np.isfinite(fraction).all()
    assert fraction.min() >= p["xOAIR"] - 1e-9, f"{fraction.min()} is below air"
    assert fraction.max() <= 1.0 + 1e-9


@pytest.mark.parametrize(("organism", "project", "mode"), PO2_MODES)
def test_no_flow_of_gas_is_ever_negative(registry, organism, project, mode):
    state, _ = _gas_run(organism, project, mode)
    stop = state.idx + 1
    for name in ("FnAIR", "FnO2", "FnN2", "FnCO2", "FnG"):
        values = np.asarray(state.v[name][:stop], dtype=float)
        assert values.min() >= -1e-9, f"{name} goes to {values.min()}"


@pytest.mark.parametrize(("organism", "project", "mode"), PO2_MODES)
def test_the_reactor_is_never_left_without_gas(registry, organism, project, mode):
    """FnG = 0 divided the oxygen balance by zero — 27 steps in a measured run,
    and every one of them at the moment of highest oxygen demand."""
    state, _ = _gas_run(organism, project, mode)
    total = np.asarray(state.v.FnG[: state.idx + 1], dtype=float)
    assert (total > 0).all(), f"{int((total <= 0).sum())} steps without gas"


@pytest.mark.parametrize("organism", ["escherichia_coli", "pichia_pastoris"])
def test_asking_for_pure_oxygen_delivers_gas(registry, organism):
    """The regression in one line.

    At a setpoint of 100 % oxygen the air flow correctly goes to zero. The
    original then computed FnO2 = FnGw - FnAIR(previdx), which is
    FnGw - FnGw = 0 while the previous step was still on air: full demand
    turned the gas off.
    """
    project = ECOLI_PROJECT if organism == "escherichia_coli" else PICHIA_PROJECT
    model = get_organism(organism)
    # The gain is turned up so the controller pins at its upper limit at once.
    # What is under test is the mixer's arithmetic, not the tuning.
    p = _parameters(
        project,
        f_Inoc=1.0,
        f_InocStart=1.0,
        deltatsec=2.0,
        Mode_pO2=3.0,
        pO2w=100.0,
        KP_gasmix=50.0,
    )
    state = build_state(p, model, dt=2 / 3600)
    run_steps(state, model, 300)
    stop = state.idx + 1

    air = np.asarray(state.v.FnAIR[:stop], dtype=float)
    oxygen = np.asarray(state.v.FnO2[:stop], dtype=float)
    total = np.asarray(state.v.FnG[:stop], dtype=float)

    pure = np.flatnonzero(air < 1e-9)
    assert pure.size, "the controller never asked for pure oxygen"
    assert (oxygen[pure] > 0).all(), "pure oxygen was asked for and none was fed"
    assert np.allclose(total[pure], p["FnGw"])


@pytest.mark.parametrize("organism", ["escherichia_coli", "pichia_pastoris"])
def test_the_gas_total_is_summed_from_the_step_it_belongs_to(registry, organism):
    """xOGin divides by this total using the current component flows.

    The Pichia source sums the previous ones at all three places where it
    totals the gas, the E. coli source the current ones at all three. Both
    read the current ones now.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "biofermentation"
        / "organisms"
        / organism
        / "model.py"
    ).read_text(encoding="utf-8")
    assert "v.FnG[i] = v.FnAIR[prev]" not in source
    assert source.count("v.FnG[i] = v.FnAIR[i] + v.FnO2[i] + v.FnN2[i] + v.FnCO2[i]") == 3


@pytest.mark.parametrize("organism", ["escherichia_coli", "pichia_pastoris"])
def test_the_guard_tests_the_total_it_divides_by(registry, organism):
    """The E. coli source guards on FnG(previdx) and divides by FnG(idx)."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "biofermentation"
        / "organisms"
        / organism
        / "model.py"
    ).read_text(encoding="utf-8")
    assert "if v.FnG[i] > 0:" in source
    assert "if v.FnG[prev] > 0:" not in source


@pytest.mark.parametrize(("organism", "project", "mode"), PO2_MODES)
def test_the_probe_never_reads_above_its_own_equilibrium(registry, organism, project, mode):
    """pO2 over 100 % is not by itself wrong — a probe calibrated on air at
    pGcal reads above 100 when the gas is enriched or the pressure is higher.
    What it must not do is read above the equilibrium of the gas it is in.

    The first seconds are exempt: the vessel starts at 2 bar and settles to
    1.5, so the liquid really does hold more oxygen than the new equilibrium
    and degasses through the probe's nine-second lag.
    """
    state, p = _gas_run(organism, project, mode)
    stop = state.idx + 1
    settled = slice(int(0.02 / (2 / 3600)), stop)  # after the first 0.02 h

    pO2 = np.asarray(state.v.pO2[:stop], dtype=float)[settled]
    ceiling = (
        np.asarray(state.v.pG[:stop], dtype=float)[settled]
        * np.asarray(state.v.xOGin[:stop], dtype=float)[settled]
        / (p["pGcal"] * p["xOGcal"])
        * 100
    )
    assert (pO2 <= ceiling + 1e-6).all(), f"worst excess {float((pO2 - ceiling).max()):.2f} points"


@pytest.mark.parametrize(("organism", "project", "mode"), PO2_MODES)
def test_the_gas_total_matches_its_components(registry, organism, project, mode):
    """The strongest guard over this corner, and the one that would have found
    both defects: a total that no component feeds is not a total.

    E. coli left FnO2 unwritten when pure oxygen was switched off, so the sum
    became NaN and carry_forward froze the total at its starting value —
    7.5 l/min next to FnAIR = 0 and FnO2 = 0.
    """
    state, _ = _gas_run(organism, project, mode)
    stop = state.idx + 1
    parts = [
        np.asarray(state.v[name][:stop], dtype=float) for name in ("FnAIR", "FnO2", "FnN2", "FnCO2")
    ]
    total = np.asarray(state.v.FnG[:stop], dtype=float)
    assert np.allclose(total, sum(parts), rtol=0, atol=1e-9)


@pytest.mark.parametrize("organism", ["escherichia_coli", "pichia_pastoris"])
def test_switching_the_oxygen_off_leaves_the_air_alone(registry, organism):
    """The one-line regression.

    The E. coli source has two blocks of the same shape for the two gases, and
    the second carries the variable of the first:

        if app.p.f_O2 == 1
            app.v.FnO2(idx) = app.p.FnO2w;
        else
            app.v.FnAIR(idx) = 0;      % should be FnO2

    so f_O2 = 0 switched the air off instead. Measured before the correction,
    pO2 went to zero and the culture suffocated while the window still
    reported 7.5 l/min of gas.
    """
    project = ECOLI_PROJECT if organism == "escherichia_coli" else PICHIA_PROJECT
    model = get_organism(organism)
    shared = {"f_Inoc": 1.0, "f_InocStart": 1.0, "deltatsec": 2.0, "Mode_pO2": 1.0}

    def last(**flags):
        p = _parameters(project, **(shared | flags))
        state = build_state(p, model, dt=2 / 3600)
        run_steps(state, model, 300)
        v, i = state.v, state.idx
        return float(v.FnAIR[i]), float(v.FnO2[i]), float(v.FnG[i]), float(v.xOGin[i])

    air_on = last(f_air=1.0, f_O2=1.0, FnAIRw=7.5, FnO2w=0.0)
    oxygen_off = last(f_air=1.0, f_O2=0.0, FnAIRw=7.5, FnO2w=0.0)
    assert oxygen_off == pytest.approx(air_on), "f_O2 = 0 changed the air flow"
    assert oxygen_off[0] == pytest.approx(7.5), "the air was switched off"

    # And the other way round: air off, pure oxygen on.
    air_off = last(f_air=0.0, f_O2=1.0, FnAIRw=7.5, FnO2w=2.0)
    assert air_off[0] == 0.0
    assert air_off[1] == pytest.approx(2.0)
    assert air_off[2] == pytest.approx(2.0)
    assert air_off[3] == pytest.approx(1.0), "pure oxygen is a mole fraction of one"


@pytest.mark.parametrize("organism", ["escherichia_coli", "pichia_pastoris"])
def test_each_gas_flag_writes_its_own_flow(registry, organism):
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "biofermentation"
        / "organisms"
        / organism
        / "model.py"
    ).read_text(encoding="utf-8")
    assert "v.FnO2[i] = p.FnO2w if p.f_O2 == 1 else 0.0" in source
    assert "v.FnAIR[i] = p.FnAIRw if p.f_air == 1 else 0.0" in source


# ----------------------------------------------------------- anti-windup --
#
# A switch nobody could reach until the controller dialogs grew one, and a
# behaviour nothing measured until now.


def test_the_integrator_only_freezes_when_it_would_push_further_out():
    """Conditional integration: hold at the limit, resume the moment it turns.

    The three cases that matter are the limit reached with the increment
    pointing further out (freeze), the same limit with the increment pointing
    back (carry on), and inside the range (carry on regardless).
    """
    from biofermentation.organisms.shared import integrate

    # At the upper limit, still pushing up: the integral keeps what it had.
    assert integrate(5.0, 2.0, output=120.0, low=0.0, high=100.0, active=True) == 5.0
    # At the same limit, but the deviation has turned round.
    assert integrate(5.0, -2.0, output=120.0, low=0.0, high=100.0, active=True) == 3.0
    # Below the lower limit, pushing further down.
    assert integrate(-5.0, -2.0, output=-20.0, low=0.0, high=100.0, active=True) == -5.0
    # Inside the range nothing is held.
    assert integrate(5.0, 2.0, output=50.0, low=0.0, high=100.0, active=True) == 7.0


def test_without_the_switch_the_integrator_runs_on_as_matlab_does():
    """Off is the default and the structure the reference run was recorded with."""
    from biofermentation.organisms.shared import anti_windup, integrate

    assert integrate(5.0, 2.0, output=120.0, low=0.0, high=100.0, active=False) == 7.0
    # A project that has never heard of the parameter reads as off.
    assert anti_windup({}, {}, "f_awpO2") is False
    assert anti_windup({"f_awpO2": 0.0}, {}, "f_awpO2") is False
    assert anti_windup({"f_awpO2": 1.0}, {}, "f_awpO2") is True


def test_the_installation_can_forbid_what_the_project_allows():
    """Two switches, and the second can only take away."""
    from biofermentation.organisms.shared import anti_windup

    p = {"f_awfeed": 1.0}
    assert anti_windup(p, {"antiwindup_allowed": True}, "f_awfeed") is True
    assert anti_windup(p, {"antiwindup_allowed": False}, "f_awfeed") is False
    # And it cannot give: a project with the flag off stays off.
    assert anti_windup({"f_awfeed": 0.0}, {"antiwindup_allowed": True}, "f_awfeed") is False


def test_every_flag_the_model_reads_has_a_switch_in_a_dialog():
    """The panels offer exactly the flags the E. coli model asks for.

    Read out of the source rather than listed twice: a renamed flag would
    otherwise leave a switch that writes a parameter nothing reads, and that
    is invisible — the run simply goes on computing the old way.
    """
    import re

    from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS

    source = (
        Path(__file__).resolve().parents[1]
        / "src/biofermentation/organisms/escherichia_coli/model.py"
    ).read_text(encoding="utf-8")
    read = set(re.findall(r'anti_windup\(p, a, "([^"]+)"\)', source))
    offered = {spec.anti_windup for spec in CONTROL_PANELS if spec.anti_windup}
    assert read == offered, (
        f"read but not offered: {read - offered}; offered but unread: {offered - read}"
    )


def test_only_the_loops_that_can_wind_up_have_a_switch():
    """Two panels have none, for two different reasons.

    pH is a P controller with a dead band — there is no integrator. The
    temperature master has one, but its output never reaches the stops of the
    split range: measured [-2.3, +3.2] over a two-hour batch against a
    setpoint 12 K away, on a loop whose stops sit at -10 and +10000. A switch
    that provably changes nothing is worse than none.
    """
    from biofermentation.gui.widgets.panel_specs import PH_PANEL, TEMPERATURE_PANEL

    assert PH_PANEL.anti_windup is None
    assert not any(
        "KI_pH" in name for group in PH_PANEL.parameter_groups for name, _ in group.parameters
    )
    assert TEMPERATURE_PANEL.anti_windup is None
    # It does have an integral gain — the reason is the limit, not the term.
    assert any(
        "KI_temp" in name
        for group in TEMPERATURE_PANEL.parameter_groups
        for name, _ in group.parameters
    )


def test_the_temperature_master_stays_away_from_its_stops(registry):
    """The measurement the missing switch rests on, so it cannot rot.

    If somebody re-tunes the cascade until this master does saturate, this
    test fails and the switch has to be wired after all.
    """
    import numpy as np

    from biofermentation.core.runner import build_state, run_steps
    from biofermentation.db import load_phases
    from biofermentation.organisms import get_organism

    p = dict(load_phases(TEMPLATE_DB, 716).p) | {
        "f_Inoc": 1.0,
        "f_InocStart": 1.0,
        "thetaLw": 20.0,  # 12 K below the start, so the loop pushes hard
    }
    model = get_organism("escherichia_coli")
    state = build_state(p, model, dt=2 / 3600)
    run_steps(state, model, 600)

    a = state.a
    integral = np.asarray(a.cI_Part)[1 : state.idx + 1]
    offsets = float(a.cP_Part) + integral + p["thetaDJ_WP"] - float(a.thetaDJ)
    cooling_stop = -100.0 / p["KP_temp2c"]
    heating_stop = 100.0 / p["KP_temp2h"]
    assert offsets.min() > cooling_stop, "the cooling stop is reached — wire f_awtemp"
    assert offsets.max() < heating_stop


def test_pichia_reads_the_same_three_flags(registry):
    """The switch reaches both organisms, or it reaches neither honestly."""
    import re

    from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS

    source = (
        Path(__file__).resolve().parents[1]
        / "src/biofermentation/organisms/pichia_pastoris/model.py"
    ).read_text(encoding="utf-8")
    read = set(re.findall(r'anti_windup\(p, a, "([^"]+)"\)', source))
    offered = {spec.anti_windup for spec in CONTROL_PANELS if spec.anti_windup}
    assert read == offered


def test_the_pichia_stirrer_integral_can_only_fall_with_the_switch_on(registry):
    """The original clamps the integral in the wrong unit; the switch replaces it.

    `clamp(cI_agi, 0, NStmax)` is anti-windup applied to a normalised term with
    a limit in rpm: the upper bound of 1500 cannot bind, the lower bound of 0
    always can, and once the stirrer has been driven up the integral can never
    come back down. Measured on the shipped Pichia parameters, Mode_pO2 = 1:
    pO2 ends at 108.7 % with the switch off and at 78.3 % with it on.
    """
    import numpy as np

    from biofermentation.core.runner import build_state, run_steps
    from biofermentation.db import load_phases
    from biofermentation.organisms import get_organism

    def run(extra):
        p = dict(load_phases(TEMPLATE_DB, 519).p) | {
            "f_Inoc": 1.0,
            "f_InocStart": 1.0,
            "Mode_pO2": 1.0,
        } | extra
        model = get_organism("pichia_pastoris")
        state = build_state(p, model, dt=2 / 3600)
        run_steps(state, model, 1800)
        return state, float(np.asarray(state.v.pO2)[state.idx])

    off_state, off_pO2 = run({})
    on_state, on_pO2 = run({"f_awpO2": 1.0})

    assert off_state.a.cI_agi >= 0.0, "the original's clamp keeps the integral positive"
    assert on_state.a.cI_agi < off_state.a.cI_agi, "released, it can fall again"
    # The setpoint is 20 %; neither run reaches it (see tools/tune_pichia.py),
    # but the released integrator gets measurably closer.
    assert on_pO2 < off_pO2 - 20.0, f"off {off_pO2:.1f} %, on {on_pO2:.1f} %"


def test_the_two_organisms_measure_differently_and_on_purpose(registry):
    """The fifth deliberate deviation, guarded at its two call sites.

    `meas_transfer_function` divides a dt that is already in hours by 3600 a
    second time, so a step closes 2.6e-09 of the gap and the measured series
    never leave their initial value. That is MATLAB's own arithmetic and the
    E. coli reference run verifies it — `pHLm`, `thetaLm`, `pO2m` and `cS1Lm`
    agree to 1e-12 — so E. coli keeps calling it.

    Pichia does not, because it is the only model that reads a measured series
    back: its closed-loop feed controls `cS2Lm`, and a controller on a
    constant cannot hold anything. It calls `sensor_lag`, which converts once.

    If somebody swaps either call, this test says so.
    """
    root = Path(__file__).resolve().parents[1] / "src/biofermentation/organisms"
    ecoli = (root / "escherichia_coli/model.py").read_text(encoding="utf-8")
    pichia = (root / "pichia_pastoris/model.py").read_text(encoding="utf-8")

    assert ecoli.count("meas_transfer_function(") == 4, "E. coli keeps the verified arithmetic"
    assert "sensor_lag(" not in ecoli
    assert pichia.count("sensor_lag(") == 5
    assert "meas_transfer_function(" not in pichia


def test_the_two_lags_differ_by_the_conversion_squared(registry):
    """dt/3600/tau against dt*3600/tau — the factor is 3600^2, not 3600.

    The original divides where the units ask for a multiplication, so the two
    are two conversions apart, not one: 12 960 000. Written down because the
    obvious guess is wrong, and a wrong factor in a comment is worse than none.
    """
    from biofermentation.organisms.shared import meas_transfer_function, sensor_lag

    dt = 2 / 3600  # hours, as the state carries it
    frozen = meas_transfer_function(current_value=10.0, previous_value=0.0, tau=60.0, dt=dt)
    moving = sensor_lag(current_value=10.0, previous_value=0.0, tau=60.0, dt=dt)

    assert frozen == pytest.approx(10.0 * dt / 3600 / 60, rel=1e-12)
    assert frozen < 1e-7, "the original freezes the measurement"
    # tau = 60 s at dt = 2 s closes a thirtieth of the gap per step.
    assert moving == pytest.approx(10.0 / 30.0, rel=1e-12)
    assert moving / frozen == pytest.approx(3600.0**2, rel=1e-9)


def test_the_pichia_feed_now_holds_its_setpoint(registry):
    """What the deviation and the corrected gains are for, measured.

    The late-stage model is the configuration this loop exists for: the
    glycerol batch is over, `R_feed` is on reservoir 2 and the methanol feed
    holds `cS2L` at 1.5 g/l. With the shipped gains — a copy of the pO2 feed
    controller's, negative — the pump never opened at all.
    """
    import shutil
    import tempfile

    import numpy as np

    from biofermentation.core.runner import build_state, run_steps
    from biofermentation.db import create_project, load_phases
    from biofermentation.organisms import get_organism

    database = Path(tempfile.mkdtemp()) / "sim.db"
    shutil.copy(TEMPLATE_DB, database)
    project = create_project(database, "FeedTest", 2)  # Pichia model (late stage)
    p = dict(load_phases(database, project).p) | {
        "f_Inoc": 1.0,
        "f_InocStart": 1.0,
        "f_feed": 1.0,
        "Mode_feed": 1.0,
    }
    assert p["KP_feedR2"] == 1.0, "the corrected gains ship with the template"
    assert p["R_feed"] == 2.0, "this model feeds methanol"

    model = get_organism("pichia_pastoris")
    state = build_state(p, model, dt=2 / 3600)
    run_steps(state, model, 3600)  # two hours

    stop = state.idx + 1
    measured = np.asarray(state.v.cS2Lm[:stop], float)
    true = np.asarray(state.v.cS2L[:stop], float)
    pump = np.asarray(state.v.FR2[:stop], float)

    assert measured[-1] > 0.5, "the sensor follows the process"
    assert abs(measured[-1] - true[-1]) < 0.2, "and follows it closely"
    assert 0.5 < true[-1] < 3.0, f"held near the setpoint of {p['cS2Lw']}, got {true[-1]:.3f}"
    assert pump[-1] > 0.0, "the pump runs"
    assert pump.max() < float(p["FR2max"]), "and never at its stop"


