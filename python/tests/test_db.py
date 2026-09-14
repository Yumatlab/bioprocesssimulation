"""Database layer tests.

Covers the bundled template database, the schema migration of plan section
1.1 and the access layer of plan sections 1.2 and 1.3. Everything runs
against a copy of the real database, never against mocks — the defects worth
catching here live in the data, not in an idealised model of it.
"""

import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from biofermentation.db import (
    Phase,
    VariableSeries,
    get_connection,
    load_phases,
    load_project_info,
    load_project_log,
    load_project_variables,
    save_project,
    save_project_with_backup,
)
from biofermentation.db.migrate import MIGRATION_SQL, apply_migration

# Two projects in the template carry phases and parameters; the rest are
# empty shells. 519 is a Pichia run with five phases, 520 has seven.
PROJECT_WITH_PHASES = 519

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"

# Tables the MATLAB application relies on; see CLAUDE.md of the MATLAB project.
EXPECTED_TABLES = {
    "projectTab",
    "project_parameterTab",
    "processTab",
    "process_parameterTab",
    "organismTab",
    "modelTab",
    "model_parameterTab",
    "variableTab",
    "variable_handlingTab",
    "parameterTab",
    "categoryTab",
    "timeTab",
    "dataTab",
    "plot_templateTab",
    "plot_variableTab",
    "logTab",
}


def _readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _schema(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    """A writable copy of the template database. Never test on the original."""
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


# --------------------------------------------------------------- template --


def test_template_database_is_bundled():
    assert TEMPLATE_DB.is_file(), f"template database missing at {TEMPLATE_DB}"


def test_template_database_passes_integrity_check():
    with _readonly(TEMPLATE_DB) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_template_database_has_expected_tables():
    with _readonly(TEMPLATE_DB) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        present = {row[0] for row in rows}
    assert present >= EXPECTED_TABLES, f"missing tables: {sorted(EXPECTED_TABLES - present)}"


def test_template_database_knows_both_organisms():
    with _readonly(TEMPLATE_DB) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM organismTab")}
    assert names == {"Escherichia coli", "Pichia pastoris"}


# ------------------------------------------------- migration, plan 1.1 --
# Until the migration was applied, end_typeID referenced process_typeTab while
# holding process_conditiontypeTab ids, which produced twelve violations. The
# template ships migrated, so this is now a plain assertion.


def test_template_database_has_no_foreign_key_violations():
    with _readonly(TEMPLATE_DB) as conn:
        violations = list(conn.execute("PRAGMA foreign_key_check"))
    assert violations == [], violations


def test_no_foreign_key_carries_match_simple():
    with _readonly(TEMPLATE_DB) as conn:
        offenders = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE sql LIKE '%MATCH SIMPLE%'"
            )
        ]
    assert offenders == [], offenders


def test_process_start_and_end_type_reference_condition_types():
    with _readonly(TEMPLATE_DB) as conn:
        targets = {row[3]: row[2] for row in conn.execute("PRAGMA foreign_key_list(processTab)")}
    assert targets["start_typeID"] == "process_conditiontypeTab"
    assert targets["end_typeID"] == "process_conditiontypeTab"


def test_stored_condition_types_exist_in_condition_type_table():
    with _readonly(TEMPLATE_DB) as conn:
        starts = {row[0] for row in conn.execute("SELECT DISTINCT start_typeID FROM processTab")}
        ends = {row[0] for row in conn.execute("SELECT DISTINCT end_typeID FROM processTab")}
        known = {
            row[0]
            for row in conn.execute("SELECT process_conditiontypeID FROM process_conditiontypeTab")
        }
    assert starts <= known and ends <= known
    # The values that made the old foreign key wrong: 6 and 7 are end
    # conditions, and process_typeTab only reaches id 5.
    assert ends == {6, 7}


def test_project_parameter_pair_is_unique(db_copy: Path):
    with sqlite3.connect(db_copy) as conn:
        projectID, parameterID = conn.execute(
            "SELECT projectID, parameterID FROM project_parameterTab LIMIT 1"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO project_parameterTab (projectID, parameterID, value) VALUES (?, ?, ?)",
                (projectID, parameterID, 1.0),
            )


def test_cascade_delete_reaches_project_parameters(db_copy: Path):
    """The symptom defect 1 was blamed for: deleting a project must clear its rows."""
    with sqlite3.connect(db_copy) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        projectID = conn.execute(
            "SELECT projectID FROM project_parameterTab GROUP BY projectID "
            "ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()[0]
        before = conn.execute(
            "SELECT COUNT(*) FROM project_parameterTab WHERE projectID = ?", (projectID,)
        ).fetchone()[0]
        assert before > 0
        conn.execute("DELETE FROM projectTab WHERE projectID = ?", (projectID,))
        after = conn.execute(
            "SELECT COUNT(*) FROM project_parameterTab WHERE projectID = ?", (projectID,)
        ).fetchone()[0]
    assert after == 0


def test_migration_script_is_shipped():
    assert MIGRATION_SQL.is_file(), f"migration script missing at {MIGRATION_SQL}"


def test_migration_is_idempotent(db_copy: Path):
    """Rerunning it on an already migrated database must change nothing."""
    with _readonly(db_copy) as conn:
        before_schema = _schema(conn)
        before_counts = _row_counts(conn)
        before_seq = conn.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name").fetchall()

    apply_migration(db_copy, backup=False)

    with _readonly(db_copy) as conn:
        assert _schema(conn) == before_schema
        assert _row_counts(conn) == before_counts
        after_seq = conn.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name")
        assert after_seq.fetchall() == before_seq
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_migration_writes_a_backup_by_default(db_copy: Path):
    backup_path = apply_migration(db_copy)
    assert backup_path is not None
    assert backup_path.is_file()
    assert backup_path != db_copy


def test_migration_preserves_autoincrement_counters(db_copy: Path):
    """The counters run far ahead of MAX(id); rebuilding must not reset them."""
    with _readonly(db_copy) as conn:
        seq = dict(conn.execute("SELECT name, seq FROM sqlite_sequence"))
    assert seq["dataTab"] > 1_000_000, "expected the template's runaway dataTab counter"

    apply_migration(db_copy, backup=False)

    with _readonly(db_copy) as conn:
        assert dict(conn.execute("SELECT name, seq FROM sqlite_sequence")) == seq


def test_migration_collapses_duplicate_project_parameters(db_copy: Path):
    """Rebuild the pre-migration table, plant a duplicate, migrate, check the winner."""
    with sqlite3.connect(db_copy, isolation_level=None) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            PRAGMA legacy_alter_table = ON;
            CREATE TABLE _legacy (
                project_parameterID INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE NOT NULL,
                projectID INTEGER NOT NULL REFERENCES projectTab (projectID)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                parameterID INTEGER REFERENCES parameterTab (parameterID),
                value REAL,
                description TEXT);
            INSERT INTO _legacy SELECT * FROM project_parameterTab;
            DROP TABLE project_parameterTab;
            ALTER TABLE _legacy RENAME TO project_parameterTab;
            """
        )
        projectID, parameterID = conn.execute(
            "SELECT projectID, parameterID FROM project_parameterTab LIMIT 1"
        ).fetchone()
        newest_id = (
            conn.execute("SELECT MAX(project_parameterID) FROM project_parameterTab").fetchone()[0]
            + 1
        )
        conn.execute(
            "INSERT INTO project_parameterTab (project_parameterID, projectID, parameterID, value)"
            " VALUES (?, ?, ?, ?)",
            (newest_id, projectID, parameterID, 42.0),
        )
        total_before = conn.execute("SELECT COUNT(*) FROM project_parameterTab").fetchone()[0]

    apply_migration(db_copy, backup=False)

    with _readonly(db_copy) as conn:
        rows = conn.execute(
            "SELECT project_parameterID, value FROM project_parameterTab"
            " WHERE projectID = ? AND parameterID = ?",
            (projectID, parameterID),
        ).fetchall()
        total_after = conn.execute("SELECT COUNT(*) FROM project_parameterTab").fetchone()[0]
    assert rows == [(newest_id, 42.0)], "the most recently written row must win"
    assert total_after == total_before - 1


def test_biostat_b_has_its_own_instrumentation_values():
    """Defect 4: the BIOSTAT B used to carry the BIOSTAT ED's figures.

    Values from the spreadsheet, sheet 'bioreactors', column BBI_ED. This is
    the one place where the spreadsheet outranks the database.
    """
    expected = {
        "FnAIRmax": 10.0,
        "FnGmax": 17.0,
        "FT1max": 1.0,
        "FT2max": 1.0,
        "mdotCmax": 150.0,
        "mdotHmax": 6.0,
        "PHmax": 2000.0,
    }
    with _readonly(TEMPLATE_DB) as conn:
        actual = dict(
            conn.execute(
                "SELECT p.name, d.value FROM default_bioreactorTab d "
                "JOIN parameterTab p USING (parameterID) "
                "WHERE d.bioreactorID = 2 AND p.name IN "
                "('FnAIRmax','FnGmax','FT1max','FT2max','mdotCmax','mdotHmax','PHmax')"
            )
        )
    assert actual == expected


def test_both_bioreactors_are_fully_populated():
    """Eight rows were missing for the BIOSTAT B; both must now be complete."""
    with _readonly(TEMPLATE_DB) as conn:
        counts = dict(
            conn.execute(
                "SELECT bioreactorID, COUNT(*) FROM default_bioreactorTab GROUP BY bioreactorID"
            )
        )
        missing = conn.execute(
            "SELECT COUNT(*) FROM default_bioreactorTab a "
            " WHERE a.bioreactorID = 1 AND NOT EXISTS ("
            "   SELECT 1 FROM default_bioreactorTab b"
            "    WHERE b.bioreactorID = 2 AND b.parameterID = a.parameterID)"
        ).fetchone()[0]
    assert counts == {1: 60, 2: 60}
    assert missing == 0


# ------------------------------------------- access layer, plan 1.2 / 1.3 --


def _series(t, **columns) -> VariableSeries:
    return VariableSeries(
        t=np.array(t, dtype=float),
        v={name: np.array(values, dtype=float) for name, values in columns.items()},
        real_t=["01.01.2026 10:00:00.000"] * len(t),
    )


def test_get_connection_enables_foreign_keys_and_wal(db_copy: Path):
    with get_connection(db_copy) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_get_connection_rolls_back_on_error(db_copy: Path):
    before = _count(db_copy, "SELECT COUNT(*) FROM logTab")
    with pytest.raises(ZeroDivisionError), get_connection(db_copy) as conn:
        conn.execute(
            "INSERT INTO logTab (projectID, datetime, message) VALUES (?, ?, ?)",
            (PROJECT_WITH_PHASES, "01.01.2026", "should not survive"),
        )
        raise ZeroDivisionError
    assert _count(db_copy, "SELECT COUNT(*) FROM logTab") == before


def test_get_connection_commits_on_clean_exit(db_copy: Path):
    before = _count(db_copy, "SELECT COUNT(*) FROM logTab")
    with get_connection(db_copy) as conn:
        conn.execute(
            "INSERT INTO logTab (projectID, datetime, message) VALUES (?, ?, ?)",
            (PROJECT_WITH_PHASES, "01.01.2026", "kept"),
        )
    assert _count(db_copy, "SELECT COUNT(*) FROM logTab") == before + 1


def test_readonly_connection_refuses_to_write(db_copy: Path):
    with (
        pytest.raises(sqlite3.OperationalError, match="readonly"),
        get_connection(db_copy, readonly=True) as conn,
    ):
        conn.execute("DELETE FROM logTab")


def _count(db_path: Path, sql: str) -> int:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        return conn.execute(sql).fetchone()[0]


def test_load_project_info_resolves_organism_and_bioreactor(db_copy: Path):
    info = load_project_info(db_copy, PROJECT_WITH_PHASES)
    assert info.organism_name == "Pichia pastoris"
    assert info.bioreactor_name == "BIOSTAT ED"
    assert info.reservoirs == 2
    assert info.function_file == "Pichia_pastoris"


def test_load_project_info_rejects_unknown_project(db_copy: Path):
    with pytest.raises(LookupError, match="99999"):
        load_project_info(db_copy, 99999)


def test_load_phases_reads_everything_in_one_go(db_copy: Path):
    setup = load_phases(db_copy, PROJECT_WITH_PHASES)
    # 279 since tmax was dropped; it was 280 while the database carried it.
    assert len(setup.p) == 279
    assert setup.p["NStw"] == 1000.0
    assert len(setup.phases) == 5
    # Free table-wide, not only inside the project — processID is the
    # primary key of processTab.
    assert setup.next_process_id == _count(db_copy, "SELECT MAX(processID) FROM processTab") + 1
    # Lookups are split by start_end so the editors get the right dropdown.
    assert {row["start_end"] for row in setup.lookups.start_conditiontype} == {1}
    assert {row["start_end"] for row in setup.lookups.end_conditiontype} == {2}


def test_cyclic_parameters_are_a_subset_of_the_metadata(db_copy: Path):
    setup = load_phases(db_copy, PROJECT_WITH_PHASES)
    assert 0 < len(setup.p_meta_cyclic) < len(setup.p_meta)
    assert all(row["reading_rate"] == "cyclic" for row in setup.p_meta_cyclic)


def test_phase_conditions_are_split_into_start_and_end(db_copy: Path):
    setup = load_phases(db_copy, PROJECT_WITH_PHASES)
    batch = next(ph for ph in setup.phases if ph.name == "Batch Phase")
    assert batch.statusID == 4
    assert batch.start.typeID == 1
    assert batch.end.typeID == 6
    assert batch.end.value == 0.1
    fed_batch = next(ph for ph in setup.phases if ph.name == "Fed Batch")
    assert fed_batch.parameters, "phase parameters must come along"


def test_phases_survive_a_save_and_reload(db_copy: Path):
    before = load_phases(db_copy, PROJECT_WITH_PHASES)
    save_project(db_copy, PROJECT_WITH_PHASES, p=before.p, phases=before.phases)
    after = load_phases(db_copy, PROJECT_WITH_PHASES)
    assert after.phases == before.phases
    assert after.p == before.p


def test_series_survives_a_save_and_reload(db_copy: Path):
    series = _series([0.0, 0.1, 0.2], cXL=[0.5, 0.8, 1.3], pO2=[100.0, 88.0, 71.0])
    save_project(db_copy, PROJECT_WITH_PHASES, series=series)

    back = load_project_variables(db_copy, PROJECT_WITH_PHASES)
    assert back.n == 3
    assert np.array_equal(back.t, series.t)
    assert np.array_equal(back.v["cXL"], series.v["cXL"])
    assert np.array_equal(back.v["pO2"], series.v["pO2"])


def test_nan_preallocation_slots_are_not_written(db_copy: Path):
    """preallocationFcn leaves NaN at the end of every series; they are not data."""
    series = _series([0.0, 0.1, np.nan, np.nan], cXL=[0.5, 0.8, np.nan, np.nan])
    result = save_project(db_copy, PROJECT_WITH_PHASES, series=series)
    assert result["times"] == 2
    assert load_project_variables(db_copy, PROJECT_WITH_PHASES).n == 2


def test_missing_values_come_back_as_nan_not_zero(db_copy: Path):
    """MATLAB wrote 0 for a NaN, turning 'not measured' into a measured zero."""
    series = _series([0.0, 0.1, 0.2], cXL=[0.5, np.nan, 1.3])
    save_project(db_copy, PROJECT_WITH_PHASES, series=series)

    back = load_project_variables(db_copy, PROJECT_WITH_PHASES)
    assert back.v["cXL"][0] == 0.5
    assert np.isnan(back.v["cXL"][1])
    assert back.v["cXL"][2] == 1.3


def test_second_save_appends_instead_of_duplicating(db_copy: Path):
    save_project(db_copy, PROJECT_WITH_PHASES, series=_series([0.0, 0.1], cXL=[0.5, 0.8]))
    save_project(
        db_copy,
        PROJECT_WITH_PHASES,
        series=_series([0.0, 0.1, 0.2, 0.3], cXL=[0.5, 0.8, 1.3, 1.9]),
    )
    back = load_project_variables(db_copy, PROJECT_WITH_PHASES)
    assert back.n == 4
    assert np.array_equal(back.v["cXL"], np.array([0.5, 0.8, 1.3, 1.9]))


def test_saving_an_already_saved_series_changes_nothing(db_copy: Path):
    series = _series([0.0, 0.1], cXL=[0.5, 0.8])
    save_project(db_copy, PROJECT_WITH_PHASES, series=series)
    result = save_project(db_copy, PROJECT_WITH_PHASES, series=series)
    assert result["times"] == 0
    assert load_project_variables(db_copy, PROJECT_WITH_PHASES).n == 2


def test_parameter_values_are_updated_in_place(db_copy: Path):
    setup = load_phases(db_copy, PROJECT_WITH_PHASES)
    rows_before = _count(
        db_copy,
        f"SELECT COUNT(*) FROM project_parameterTab WHERE projectID = {PROJECT_WITH_PHASES}",
    )
    changed = dict(setup.p)
    changed["NStw"] = 1234.0
    save_project(db_copy, PROJECT_WITH_PHASES, p=changed)

    after = load_phases(db_copy, PROJECT_WITH_PHASES)
    assert after.p["NStw"] == 1234.0
    # The upsert must not add a second row for the same pair — that is exactly
    # what UNIQUE (projectID, parameterID) from plan 1.1 prevents.
    assert (
        _count(
            db_copy,
            f"SELECT COUNT(*) FROM project_parameterTab WHERE projectID = {PROJECT_WITH_PHASES}",
        )
        == rows_before
    )


def test_unknown_parameter_names_are_reported_not_raised(db_copy: Path):
    """A typo must not cost a whole session's results."""
    result = save_project(
        db_copy, PROJECT_WITH_PHASES, p={"NStw": 900.0, "definitely_not_a_parameter": 1.0}
    )
    assert result["unknown_parameters"] == ["definitely_not_a_parameter"]
    assert result["parameters"] == 1


def test_nan_parameters_are_skipped_rather_than_nulled(db_copy: Path):
    """sqlite3 binds NaN as NULL, which would erase the stored value."""
    before = load_phases(db_copy, PROJECT_WITH_PHASES).p["NStw"]
    result = save_project(db_copy, PROJECT_WITH_PHASES, p={"NStw": float("nan")})
    assert result["skipped_parameters"] == ["NStw"]
    assert load_phases(db_copy, PROJECT_WITH_PHASES).p["NStw"] == before


def test_replacing_phases_cascades_into_phase_parameters(db_copy: Path):
    """ON DELETE CASCADE only fires because get_connection turns it on."""
    setup = load_phases(db_copy, PROJECT_WITH_PHASES)
    assert (
        _count(
            db_copy,
            "SELECT COUNT(*) FROM process_parameterTab WHERE processID IN "
            f"(SELECT processID FROM processTab WHERE projectID = {PROJECT_WITH_PHASES})",
        )
        > 0
    )

    save_project(db_copy, PROJECT_WITH_PHASES, phases=[])
    assert load_phases(db_copy, PROJECT_WITH_PHASES).phases == []
    assert (
        _count(
            db_copy,
            "SELECT COUNT(*) FROM process_parameterTab WHERE processID IN "
            f"(SELECT processID FROM processTab WHERE projectID = {PROJECT_WITH_PHASES})",
        )
        == 0
    )
    assert setup.phases, "fixture must actually have had phases"


def test_two_projects_do_not_fight_over_a_phase_number(db_copy: Path):
    """processID is the key of the whole table, not of one project.

    Both projects numbered their phases from 1, and the second one to be saved
    took the whole session down with it: UNIQUE constraint failed, and with it
    the parameters, the series and the log of that save.
    """
    other = 733  # a project of the template without phases of its own
    setup = load_phases(db_copy, other)
    phase = Phase(processID=setup.next_process_id, projectID=other, name="Batch")

    result = save_project(db_copy, other, phases=[phase])
    assert result["phases"] == 1
    assert result["renumbered_phases"] == 0
    assert load_phases(db_copy, other).phases[0].name == "Batch"


def test_a_phase_that_lands_on_a_foreign_number_takes_a_free_one(db_copy: Path):
    """The cure for a session that was numbered before the rule was known."""
    other = 733
    foreign = _count(db_copy, "SELECT MIN(processID) FROM processTab")
    phase = Phase(processID=foreign, projectID=other, name="Batch")

    result = save_project(db_copy, other, phases=[phase])
    assert result["renumbered_phases"] == 1
    assert phase.processID != foreign, "the new id must reach the caller"
    assert load_phases(db_copy, other).phases[0].processID == phase.processID
    # And the project that owned the number keeps its phase.
    assert _count(db_copy, f"SELECT COUNT(*) FROM processTab WHERE processID = {foreign}") == 1


def test_a_failing_save_leaves_the_database_untouched(db_copy: Path):
    """One transaction for parameters, series, phases and log together.

    Parameters and the series are written before the phases; the duplicate
    processID below makes the phase insert fail, and nothing may survive.
    """
    setup = load_phases(db_copy, PROJECT_WITH_PHASES)
    duplicate = [
        Phase(processID=1, projectID=PROJECT_WITH_PHASES),
        Phase(processID=1, projectID=PROJECT_WITH_PHASES),
    ]

    with pytest.raises(sqlite3.IntegrityError):
        save_project(
            db_copy,
            PROJECT_WITH_PHASES,
            p={"NStw": 4242.0},
            series=_series([0.0, 0.1], cXL=[0.5, 0.8]),
            phases=duplicate,
        )

    after = load_phases(db_copy, PROJECT_WITH_PHASES)
    assert after.p["NStw"] == setup.p["NStw"]
    assert len(after.phases) == len(setup.phases)
    assert (
        _count(db_copy, f"SELECT COUNT(*) FROM timeTab WHERE projectID = {PROJECT_WITH_PHASES}")
        == 0
    )


def test_backup_is_written_and_is_a_usable_database(db_copy: Path):
    result, backup = save_project_with_backup(
        db_copy, PROJECT_WITH_PHASES, series=_series([0.0], cXL=[0.5])
    )
    assert result["times"] == 1
    assert backup.is_file() and backup != db_copy
    with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert list(conn.execute("PRAGMA foreign_key_check")) == []
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM timeTab WHERE projectID = ?", (PROJECT_WITH_PHASES,)
            ).fetchone()[0]
            == 1
        )


def test_empty_project_loads_without_data(db_copy: Path):
    """Most projects in the template have no phases and no series at all."""
    setup = load_phases(db_copy, 733)
    assert setup.phases == []
    assert setup.p == {}
    # Not 1: the phases of other projects hold the low numbers, and a new
    # project that starts counting at 1 collides with them on the first save.
    assert setup.next_process_id > _count(db_copy, "SELECT MAX(processID) FROM processTab")
    series = load_project_variables(db_copy, 733)
    assert series.n == 0


# ------------------------------------------------------------- the log --


def test_the_log_table_carries_the_event_type_and_the_process_time(db_copy):
    """Two thirds of a log entry had nowhere to go before this."""
    with _readonly(db_copy) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(logTab)")}
    assert {"event_type", "process_time"} <= columns


def test_adding_the_log_columns_twice_keeps_what_was_written(tmp_path):
    """ALTER TABLE ADD COLUMN has no IF NOT EXISTS, and a rebuild would drop
    the columns again on the next run — with everything written since."""
    target = tmp_path / "twice.db"
    shutil.copy(TEMPLATE_DB, target)
    apply_migration(target, backup=False)

    with sqlite3.connect(target) as conn:
        conn.execute(
            "UPDATE logTab SET event_type = 'Phase Event', process_time = 1.25 "
            "WHERE logID = (SELECT MIN(logID) FROM logTab)"
        )

    apply_migration(target, backup=False)
    with sqlite3.connect(target) as conn:
        row = conn.execute(
            "SELECT event_type, process_time FROM logTab ORDER BY logID LIMIT 1"
        ).fetchone()
    assert row == ("Phase Event", 1.25)


def test_a_log_round_trips(db_copy):
    entries = [
        {
            "datetime": "10.09.2026 12:00:00.000",
            "event_type": "Process",
            "message": "Process started",
            "process_time": 0.0,
        },
        {
            "datetime": "10.09.2026 12:00:02.000",
            "event_type": "Phase Event",
            "message": "Batch Phase [Phase 1] started",
            "process_time": 0.002,
        },
    ]
    result = save_project(db_copy, PROJECT_WITH_PHASES, log=entries)
    assert result["log"] == 2
    assert all(entry["logID"] is not None for entry in entries)

    loaded = load_project_log(db_copy, PROJECT_WITH_PHASES)
    assert [entry["event_type"] for entry in loaded[-2:]] == ["Process", "Phase Event"]
    assert loaded[-1]["message"] == "Batch Phase [Phase 1] started"
    assert loaded[-1]["process_time"] == pytest.approx(0.002)


def test_saving_the_same_log_twice_writes_it_once(db_copy):
    """Counting the rows already there broke as soon as a log was reloaded."""
    entries = [
        {
            "datetime": "10.09.2026 12:00:00.000",
            "event_type": "Process",
            "message": "Process started",
            "process_time": 0.0,
        }
    ]
    before = len(load_project_log(db_copy, PROJECT_WITH_PHASES))

    assert save_project(db_copy, PROJECT_WITH_PHASES, log=entries)["log"] == 1
    assert save_project(db_copy, PROJECT_WITH_PHASES, log=entries)["log"] == 0

    entries.append(
        {
            "datetime": "10.09.2026 12:00:04.000",
            "event_type": "Process",
            "message": "Process paused",
            "process_time": 0.004,
        }
    )
    assert save_project(db_copy, PROJECT_WITH_PHASES, log=entries)["log"] == 1
    assert len(load_project_log(db_copy, PROJECT_WITH_PHASES)) == before + 2


def test_an_old_entry_gives_up_its_event_type_prefix(db_copy):
    """Rows written before the column existed carry it as "[...]" in the text.

    They are read, not rewritten — a schema migration must not touch stored
    data.
    """
    with sqlite3.connect(db_copy) as conn:
        conn.execute(
            "INSERT INTO logTab (projectID, datetime, message) VALUES (?, ?, ?)",
            (PROJECT_WITH_PHASES, "01.01.2025 08:00:00.000", "[Phase Event] Batch ended"),
        )
        conn.execute(
            "INSERT INTO logTab (projectID, datetime, message) VALUES (?, ?, ?)",
            (PROJECT_WITH_PHASES, "01.01.2025 08:00:01.000", "no prefix at all"),
        )

    loaded = load_project_log(db_copy, PROJECT_WITH_PHASES)
    prefixed, plain = loaded[-2], loaded[-1]
    assert (prefixed["event_type"], prefixed["message"]) == ("Phase Event", "Batch ended")
    assert (plain["event_type"], plain["message"]) == ("Log", "no prefix at all")

    with sqlite3.connect(db_copy) as conn:
        stored = conn.execute(
            "SELECT message FROM logTab WHERE logID = ?", (prefixed["logID"],)
        ).fetchone()[0]
    assert stored == "[Phase Event] Batch ended", "the stored text was rewritten"
