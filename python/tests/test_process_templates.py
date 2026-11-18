"""Process templates in the database — Projektplan_Prozessvorlagen.md, phase 1.

Built on the real process of project 519 (Pichia): a batch, a fed-batch that
has run and carries its results, pulse feeds on two reservoirs and a
parameter update, with stamped timer ends. A copy of the shipped template
database each time, never a mock.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from biofermentation.db import (
    TemplateExistsError,
    delete_model,
    delete_process_template,
    duplicate_model,
    ensure_template_tables,
    get_connection,
    list_process_templates,
    load_phases,
    load_process_template,
    model_usage,
    rename_process_template,
    save_process_template,
    template_count,
)
from biofermentation.db.migrate import TEMPLATE_TABLES, apply_migration
from biofermentation.db.process_templates import is_result_parameter

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
PROJECT = 519


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


@pytest.fixture
def setup(db):
    return load_phases(db, PROJECT)


def _save(db, setup, name="Pichia standard", **kwargs) -> int:
    return save_process_template(
        db, setup.info.modelID, name, "Batch, fed-batch, pulses", setup.phases, **kwargs
    )


def _rows(db, table: str) -> int:
    with get_connection(db, readonly=True) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ------------------------------------------------------- the round trip --


def test_saving_and_loading_gives_back_the_same_phases(db, setup):
    template = load_process_template(db, _save(db, setup))
    assert template.name == "Pichia standard"
    assert template.description == "Batch, fed-batch, pulses"
    assert template.modelID == setup.info.modelID
    assert len(template.phases) == len(setup.phases) == 5
    for saved, original in zip(template.phases, setup.phases, strict=True):
        assert saved.typeID == original.typeID
        assert saved.name == original.name
        assert saved.reservoirID == original.reservoirID
        for which in ("start", "end"):
            got, want = getattr(saved, which), getattr(original, which)
            assert (got.typeID, got.variableID, got.operatorID, got.value) == (
                want.typeID,
                want.variableID,
                want.operatorID,
                want.value,
            ), (original.name, which)
        expected = {k: v for k, v in original.parameters.items() if not is_result_parameter(k)}
        assert saved.parameters == expected, original.name


def test_a_template_is_a_plan_without_status_ids_or_times(db, setup):
    # The shipped run has completed, active and upcoming phases, times stamped.
    assert {phase.statusID for phase in setup.phases} == {1, 3, 4}
    template = load_process_template(db, _save(db, setup))
    for phase in template.phases:
        assert phase.statusID is None
        assert phase.processID == 0 and phase.projectID == 0
        assert phase.start.time is None and phase.end.time is None


def test_a_timer_keeps_its_duration_not_its_time(db, setup):
    fed_batch = setup.phases[1]
    assert fed_batch.end.typeID == 7  # timer
    assert fed_batch.end.value == 5.0
    assert fed_batch.end.time is not None  # it ran: start + 5 h is stamped
    template = load_process_template(db, _save(db, setup))
    assert template.phases[1].end.value == 5.0
    assert template.phases[1].end.time is None


def test_the_results_of_a_feed_are_not_saved(db, setup):
    """P0-2: t1j, cXL1j, FR1j describe a run that happened, not a plan."""
    assert set(setup.phases[1].parameters) == {"t1j", "cXL1j", "FR1j"}
    template = load_process_template(db, _save(db, setup))
    assert template.phases[1].parameters == {}
    # The settings of the other phases do travel.
    assert template.phases[2].parameters == {"kR2": 1.0}
    assert template.phases[3].parameters == {"cS2Lw": 2.0, "Mode_feed": 1.0, "R_feed": 2.0}


def test_the_order_is_kept(db, setup):
    reordered = list(reversed(setup.phases))
    template_id = save_process_template(db, setup.info.modelID, "Reversed", None, reordered)
    names = [phase.name for phase in load_process_template(db, template_id).phases]
    assert names == [phase.name for phase in reordered]


def test_saving_does_not_touch_the_project(db, setup):
    with get_connection(db, readonly=True) as conn:
        before = conn.execute("SELECT * FROM processTab ORDER BY processID").fetchall()
        params = conn.execute("SELECT * FROM process_parameterTab ORDER BY 1").fetchall()
    _save(db, setup)
    with get_connection(db, readonly=True) as conn:
        assert conn.execute("SELECT * FROM processTab ORDER BY processID").fetchall() == before
        assert conn.execute("SELECT * FROM process_parameterTab ORDER BY 1").fetchall() == params


# ---------------------------------------------------------------- names --


def test_a_name_is_unique_per_model_not_per_database(db, setup):
    _save(db, setup, name="Standard")
    with pytest.raises(TemplateExistsError):
        _save(db, setup, name="Standard")
    # The same name in another model is fine.
    other = duplicate_model(db, setup.info.modelID, "Pichia copy")
    with get_connection(db) as conn:
        conn.execute("DELETE FROM process_templateTab WHERE modelID = ?", (other,))
    save_process_template(db, other, "Standard", None, setup.phases)
    assert template_count(db, other) == 1


def test_overwriting_replaces_the_whole_template(db, setup):
    first = _save(db, setup, name="Standard")
    second = save_process_template(
        db, setup.info.modelID, "Standard", "only two", setup.phases[:2], replace=True
    )
    assert second != first
    templates = list_process_templates(db, setup.info.modelID)
    assert [(row["name"], row["phases"], row["description"]) for row in templates] == [
        ("Standard", 2, "only two")
    ]
    # Nothing of the first one is left behind.
    assert _rows(db, "process_template_phaseTab") == 2
    with pytest.raises(LookupError):
        load_process_template(db, first)


def test_an_interrupted_save_leaves_the_old_template_whole(db, setup):
    """Replacing writes delete and insert in one transaction."""
    _save(db, setup, name="Standard")
    phases_before = _rows(db, "process_template_phaseTab")
    broken = [*setup.phases[:2], setup.phases[2]]
    broken[2] = type(broken[2])(**{**broken[2].__dict__, "typeID": 999})  # no such type
    with pytest.raises(sqlite3.IntegrityError):
        save_process_template(db, setup.info.modelID, "Standard", "new", broken, replace=True)
    template = load_process_template(
        db, list_process_templates(db, setup.info.modelID)[0]["templateID"]
    )
    assert len(template.phases) == 5
    assert template.description == "Batch, fed-batch, pulses"
    assert _rows(db, "process_template_phaseTab") == phases_before


def test_an_empty_name_or_no_phase_is_refused(db, setup):
    with pytest.raises(ValueError, match="name"):
        save_process_template(db, setup.info.modelID, "  ", None, setup.phases)
    with pytest.raises(ValueError, match="phase"):
        save_process_template(db, setup.info.modelID, "Empty", None, [])
    assert _rows(db, "process_templateTab") == 0


def test_an_unknown_parameter_is_refused_with_its_name(db, setup):
    phases = list(setup.phases)
    phases[3].parameters["noSuchThing"] = 1.0
    with pytest.raises(LookupError, match="noSuchThing"):
        _save(db, setup)
    assert _rows(db, "process_templateTab") == 0


def test_renaming_keeps_names_unique(db, setup):
    first = _save(db, setup, name="A")
    _save(db, setup, name="B")
    with pytest.raises(TemplateExistsError):
        rename_process_template(db, first, "B")
    rename_process_template(db, first, "C", "renamed")
    template = load_process_template(db, first)
    assert (template.name, template.description) == ("C", "renamed")


def test_the_list_is_sorted_by_name_and_counts_the_phases(db, setup):
    _save(db, setup, name="beta")
    save_process_template(db, setup.info.modelID, "Alpha", None, setup.phases[:1])
    rows = list_process_templates(db, setup.info.modelID)
    assert [(row["name"], row["phases"]) for row in rows] == [("Alpha", 1), ("beta", 5)]
    assert list_process_templates(db, 99999) == []


def test_deleting_a_template_takes_its_phases_and_parameters(db, setup):
    template_id = _save(db, setup)
    assert delete_process_template(db, template_id) == 5
    for table in TEMPLATE_TABLES:
        assert _rows(db, table) == 0, table
    with pytest.raises(LookupError):
        delete_process_template(db, template_id)


# ---------------------------------------------------------- the model --


def test_the_usage_of_a_model_counts_its_templates(db, setup):
    assert model_usage(db, setup.info.modelID)["templates"] == 0
    _save(db, setup)
    assert model_usage(db, setup.info.modelID)["templates"] == 1


def test_deleting_a_model_takes_its_templates(db, setup):
    """E7. The shipped models are used by projects, so a duplicate is deleted."""
    copy = duplicate_model(db, setup.info.modelID, "Pichia copy")
    save_process_template(db, copy, "Mine", None, setup.phases)
    with get_connection(db, readonly=True) as conn:
        own = conn.execute(
            "SELECT COUNT(*) FROM process_templateTab WHERE modelID = ?", (copy,)
        ).fetchone()[0]
    assert delete_model(db, copy)["templates"] == own
    assert template_count(db, copy) == 0
    with get_connection(db, readonly=True) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_duplicating_a_model_copies_its_templates(db, setup):
    """E8: a variant of a model is a variant of the same process."""
    _save(db, setup)
    copy = duplicate_model(db, setup.info.modelID, "Pichia copy")
    [row] = list_process_templates(db, copy)
    original = load_process_template(
        db, list_process_templates(db, setup.info.modelID)[0]["templateID"]
    )
    duplicate = load_process_template(db, row["templateID"])
    assert duplicate.templateID != original.templateID
    assert [
        (phase.name, phase.typeID, phase.end.value, phase.parameters) for phase in duplicate.phases
    ] == [
        (phase.name, phase.typeID, phase.end.value, phase.parameters) for phase in original.phases
    ]
    # Independent copies: deleting one leaves the other.
    delete_process_template(db, original.templateID)
    assert len(load_process_template(db, duplicate.templateID).phases) == 5


# ---------------------------------------------------------- the schema --


def test_the_shipped_database_has_the_tables_and_no_template(db):
    with get_connection(db, readonly=True) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert set(TEMPLATE_TABLES) <= names
    assert _rows(db, "process_templateTab") == 0
    assert ensure_template_tables(db) == []


def test_a_database_from_before_gets_the_tables_and_keeps_everything_else(db, setup):
    with get_connection(db) as conn:
        for table in reversed(list(TEMPLATE_TABLES)):
            conn.execute(f"DROP TABLE {table}")
    # The model functions do not trip over the missing tables ...
    assert model_usage(db, setup.info.modelID)["templates"] == 0
    copy = duplicate_model(db, setup.info.modelID, "Pichia copy")
    assert copy
    # ... and the start adds them, once.
    assert ensure_template_tables(db) == list(TEMPLATE_TABLES)
    assert ensure_template_tables(db) == []
    _save(db, setup)
    with get_connection(db, readonly=True) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_full_migration_creates_them_too_and_stays_idempotent(db, setup):
    _save(db, setup)
    apply_migration(db, backup=False)
    apply_migration(db, backup=False)
    with get_connection(db, readonly=True) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # A template survives the rebuild.
    assert len(list_process_templates(db, setup.info.modelID)) == 1


def test_a_template_points_at_a_real_operator_table(db):
    """Not the fault of processTab.start_operatorID (CLAUDE.md, Offen aus Phase 1)."""
    with get_connection(db, readonly=True) as conn:
        keys = conn.execute("PRAGMA foreign_key_list(process_template_phaseTab)").fetchall()
    targets = {row["from"]: row["table"] for row in keys}
    assert targets["start_operatorID"] == "process_operatorTab"
    assert targets["end_operatorID"] == "process_operatorTab"
    assert targets["start_typeID"] == "process_conditiontypeTab"


def test_load_defaults_refuses_while_templates_exist(db, setup):
    """Templates are user data: the CSV rebuild would cascade into them."""
    from biofermentation.db.seed import load_defaults

    with get_connection(db) as conn:
        conn.execute("DELETE FROM projectTab")
    _save(db, setup)
    with pytest.raises(RuntimeError, match="process templates"):
        load_defaults(db)
    assert _rows(db, "process_templateTab") == 1
