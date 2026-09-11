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
