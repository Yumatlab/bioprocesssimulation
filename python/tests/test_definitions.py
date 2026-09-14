"""Declarative organism definitions (plan section 2.3).

The point of the layer is that somebody who does not write Python can add an
organism. So the tests import one that does not exist yet, from a file, and
check what the database looks like afterwards.
"""

import shutil
from pathlib import Path

import pytest

from biofermentation.db.definitions import export_definition, import_definition
from biofermentation.organisms.definition import (
    CategoryDefinition,
    OrganismDefinition,
    ParameterDefinition,
    VariableDefinition,
    definition_path,
    load_definition,
    write_definition,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
# Pichia ships no definition yet: default_modelTab holds two rows each for
# yXpOgr, yCpO and qOpXm, so there is no single value to write down. See
# test_pichia_defaults_are_duplicated below.
ORGANISMS = ("escherichia_coli",)


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


def _new_organism() -> OrganismDefinition:
    return OrganismDefinition(
        name="bacillus_subtilis",
        display_name="Bacillus subtilis",
        n_reservoirs=1,
        texname=r"\textit{Bacillus subtilis}",
        categories=[
            CategoryDefinition("Cell growth", "Organism", "once"),
            CategoryDefinition("Brand new category", "Organism", "once"),
        ],
        parameters=[
            # my1opt exists already and must be reused, kSbrandnew must not.
            ParameterDefinition("my1opt", "Cell growth", 0.55, unit="1/h"),
            ParameterDefinition("kSbrandnew", "Brand new category", 0.07, unit="g/l"),
        ],
        variables=[
            VariableDefinition("cXL", unit="g/l", initial_assignment="app.p.cXL0"),
            VariableDefinition("cBrandnewL", unit="g/l", visible=False),
        ],
    )


# ------------------------------------------------------------- the file --


@pytest.mark.parametrize("organism", ORGANISMS)
def test_every_plugin_ships_a_definition(organism):
    assert definition_path(organism).is_file()


@pytest.mark.parametrize("organism", ORGANISMS)
def test_shipped_definitions_load_and_validate(organism):
    definition = load_definition(definition_path(organism))
    assert definition.name == organism
    assert definition.parameters and definition.variables
    assert definition.validate() == []


def test_a_definition_survives_a_yaml_round_trip(tmp_path):
    original = _new_organism()
    path = write_definition(original, tmp_path / "definition.yaml")
    again = load_definition(path)
    assert again == original


def test_a_parameter_in_an_undeclared_category_is_refused(tmp_path):
    broken = _new_organism()
    broken.parameters.append(ParameterDefinition("kX", "Category that is missing", 1.0))
    path = write_definition(broken, tmp_path / "definition.yaml")
    with pytest.raises(ValueError, match="which is not defined"):
        load_definition(path)


def test_duplicates_are_refused(tmp_path):
    broken = _new_organism()
    broken.parameters.append(ParameterDefinition("my1opt", "Cell growth", 0.9))
    path = write_definition(broken, tmp_path / "definition.yaml")
    with pytest.raises(ValueError, match="duplicate parameters: my1opt"):
        load_definition(path)


# ---------------------------------------------------------- the import --


def test_a_new_organism_arrives_from_a_file(db_copy, tmp_path):
    path = write_definition(_new_organism(), tmp_path / "definition.yaml")
    counts = import_definition(db_copy, load_definition(path))

    assert counts["categories"] == 1, "only the unknown category is created"
    assert counts["parameters"] == 1, "my1opt already exists and is reused"
    assert counts["variables"] == 1, "cXL already exists and is reused"
    assert counts["defaults"] == 2
    assert counts["handling"] == 2

    exported = export_definition(db_copy, "Bacillus subtilis")
    assert exported.n_reservoirs == 1
    assert {p.name for p in exported.parameters} == {"my1opt", "kSbrandnew"}
    assert {v.name for v in exported.variables} == {"cXL", "cBrandnewL"}


def test_shared_rows_are_reused_never_duplicated(db_copy, tmp_path):
    """A new organism must not fork parameterTab."""
    import sqlite3

    def count(table):
        with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    before = count("parameterTab"), count("variableTab")
    import_definition(db_copy, _new_organism())
    after = count("parameterTab"), count("variableTab")
    assert after == (before[0] + 1, before[1] + 1)


def test_an_existing_organism_is_not_overwritten_by_accident(db_copy):
    definition = load_definition(definition_path("escherichia_coli"))
    with pytest.raises(ValueError, match="already exists"):
        import_definition(db_copy, definition)


def test_replace_updates_the_defaults_in_place(db_copy):
    definition = load_definition(definition_path("escherichia_coli"))
    target = next(p for p in definition.parameters if p.name == "my1opt")
    target.default = 0.9

    import_definition(db_copy, definition, replace=True)

    again = export_definition(db_copy, "Escherichia coli")
    assert next(p for p in again.parameters if p.name == "my1opt").default == 0.9


@pytest.mark.parametrize("organism", ORGANISMS)
def test_reimporting_a_shipped_definition_changes_nothing(db_copy, organism):
    definition = load_definition(definition_path(organism))
    import_definition(db_copy, definition, replace=True)
    again = export_definition(db_copy, definition.display_name)

    assert {(p.name, p.default) for p in again.parameters} == {
        (p.name, p.default) for p in definition.parameters
    }
    assert {(v.name, v.visible) for v in again.variables} == {
        (v.name, v.visible) for v in definition.variables
    }


def test_pichia_defaults_are_not_duplicated():
    """The 206/207/208 against 309/310/311 duplicate from the MATLAB notes.

    It was known to block the creation of Pichia projects. What went unnoticed
    is that the stray values reached project_parameterTab as well, so every
    Pichia project ran with an oxygen growth yield of 40 instead of 1.773.

    Repaired with db/repair.py; this test held it as a strict xfail until then
    and now guards the repair.
    """
    definition = export_definition(TEMPLATE_DB, "Pichia pastoris")
    values = {p.name: p.default for p in definition.parameters}
    assert values["yXpOgr"] == pytest.approx(1.773)
    assert values["yCpO"] == pytest.approx(1.375)
    assert values["qOpXm"] == pytest.approx(0.0117)
    # The numbers that were sitting on them belong to these three.
    assert values["kS2tox"] == pytest.approx(40.0)
    assert values["kappatox"] == pytest.approx(15.0)
    assert values["qXpXtox"] == pytest.approx(0.5)


def test_an_import_leaves_no_foreign_key_violations(db_copy):
    import sqlite3

    import_definition(db_copy, _new_organism())
    with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_a_broken_definition_is_refused_before_it_touches_the_database(db_copy):
    import sqlite3

    broken = _new_organism()
    broken.n_reservoirs = 0
    with pytest.raises(ValueError, match="n_reservoirs"):
        import_definition(db_copy, broken)

    with sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM organismTab WHERE name = 'Bacillus subtilis'"
            ).fetchone()[0]
            == 0
        )
