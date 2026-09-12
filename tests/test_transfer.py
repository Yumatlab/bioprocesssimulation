"""Moving organisms, bioreactors and projects between installations.

Every identity here is a name. Ids differ between databases, so a package
that carried them could only be read back into the one it came from — the
tests import into a database whose ids were deliberately moved.
"""

import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from biofermentation.db import (
    create_project,
    export_bioreactor,
    import_bioreactor,
    import_package,
    list_bioreactors,
    load_bioreactor,
    load_phases,
    read_package,
    write_bioreactor,
    write_manifest,
)
from biofermentation.db.definitions import export_definition, import_definition
from biofermentation.db.transfer import MANIFEST, MissingPrerequisiteError
from biofermentation.organisms.definition import load_definition, write_definition

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
ECOLI_PROJECT = 716
PICHIA_PROJECT = 519


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


# -------------------------------------------------------- bioreactors --


def test_a_bioreactor_round_trips_through_yaml(db, tmp_path):
    definition = export_bioreactor(db, "BIOSTAT ED")
    assert definition.manufacturer == "B. Braun Stedim"
    assert len(definition.parameters) > 50
    assert definition.parameters["VLmax"] == 11.0

    path = write_bioreactor(definition, tmp_path / "ed.yaml")
    again = load_bioreactor(path)
    assert again.parameters == definition.parameters
    assert again.manufacturer == definition.manufacturer


def test_an_organism_reports_what_its_parameters_mean(db):
    from biofermentation.db.definitions import organism_parameters

    rows = organism_parameters(db, "Escherichia coli")
    assert len(rows) > 100
    assert {"parametername", "tex", "unit", "categoryname", "reading_rate", "value"} <= set(rows[0])
    sections = [row["categorysection"] for row in rows]
    assert sections == sorted(sections)


def test_an_organism_says_what_stands_on_it(db):
    from biofermentation.db.definitions import organism_usage

    assert organism_usage(db, "Escherichia coli")["projects"] > 0
    with pytest.raises(LookupError, match="Nonsense"):
        organism_usage(db, "Nonsense")


def test_saving_default_values_touches_nothing_else(db):
    """An editor that changes four numbers should not rewrite the categories,
    the variables and the models on its way out."""
    from biofermentation.db.definitions import organism_parameters, save_organism_parameters

    before = export_definition(db, "Escherichia coli")
    name = organism_parameters(db, "Escherichia coli")[0]["parametername"]

    result = save_organism_parameters(db, "Escherichia coli", {name: 0.25, "nonsense": 1.0})
    assert result == {"parameters": 1, "unknown_parameters": 1}

    after = export_definition(db, "Escherichia coli")
    assert [c.name for c in after.categories] == [c.name for c in before.categories]
    assert [v.name for v in after.variables] == [v.name for v in before.variables]
    assert [m.name for m in after.models] == [m.name for m in before.models]
    assert next(p.default for p in after.parameters if p.name == name) == pytest.approx(0.25)


def test_a_rename_moves_the_organism_rather_than_copying_it(db):
    """Everything references organismID, so a rename is one UPDATE. Going
    through import_definition would key on the name and leave two."""
    from biofermentation.db.definitions import list_organisms, organism_usage, update_organism

    before = organism_usage(db, "Escherichia coli")
    update_organism(db, "Escherichia coli", new_name="E. coli K-12", description="a strain")

    names = {row["name"] for row in list_organisms(db)}
    assert "E. coli K-12" in names
    assert "Escherichia coli" not in names
    assert len(names) == 2
    # The models and projects came with it — they never held the name.
    assert organism_usage(db, "E. coli K-12") == before

    with pytest.raises(ValueError, match="already exists"):
        update_organism(db, "E. coli K-12", new_name="Pichia pastoris")


def test_an_organism_in_use_cannot_be_deleted(db):
    from biofermentation.db.definitions import delete_organism

    with pytest.raises(ValueError, match="still used"):
        delete_organism(db, "Escherichia coli")


def test_a_copied_organism_can_be_deleted_again(db):
    """default_modelTab is the one reference the schema gives no cascade."""
    import sqlite3

    from biofermentation.db.definitions import delete_organism, import_definition

    copy = export_definition(db, "Escherichia coli")
    copy.display_name, copy.name, copy.models = "E. coli K-12", "ecoli_k12", []
    import_definition(db, copy)

    assert delete_organism(db, "E. coli K-12")["defaults"] > 100
    with sqlite3.connect(db) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM default_modelTab WHERE organismID NOT IN "
            "(SELECT organismID FROM organismTab)"
        ).fetchone()[0]
    assert orphans == 0


def test_a_vessel_reports_what_its_parameters_mean(db):
    """The transfer package carries values; a form needs the labels too."""
    from biofermentation.db import bioreactor_parameters

    rows = bioreactor_parameters(db, "BIOSTAT ED")
    assert len(rows) == 60
    first = rows[0]
    assert {"parametername", "tex", "unit", "categoryname", "categorysection", "value"} <= set(
        first
    )
    # Grouped the way the dialogs group things, and every row belongs to the
    # vessel rather than the organism.
    sections = [row["categorysection"] for row in rows]
    assert sections == sorted(sections)


def test_a_vessel_says_what_stands_on_it(db):
    from biofermentation.db import bioreactor_usage

    assert bioreactor_usage(db, "BIOSTAT ED") == {"models": 3, "projects": 14}
    assert bioreactor_usage(db, "BIOSTAT B") == {"models": 0, "projects": 0}
    with pytest.raises(LookupError, match="Nonsense"):
        bioreactor_usage(db, "Nonsense")


def test_a_vessel_in_use_cannot_be_deleted(db):
    """Letting the cascade take the models with it is how the MATLAB version
    lost projects. It is not on offer."""
    from biofermentation.db import delete_bioreactor

    with pytest.raises(ValueError, match="still used"):
        delete_bioreactor(db, "BIOSTAT ED")
    assert "BIOSTAT ED" in {row["name"] for row in list_bioreactors(db)}


def test_an_unused_vessel_goes_with_its_values(db):
    from biofermentation.db import delete_bioreactor

    result = delete_bioreactor(db, "BIOSTAT B")
    assert result["parameters"] == 60
    assert "BIOSTAT B" not in {row["name"] for row in list_bioreactors(db)}
    with sqlite3.connect(db) as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM default_bioreactorTab WHERE bioreactorID NOT IN "
            "(SELECT bioreactorID FROM bioreactorTab)"
        ).fetchone()[0]
    assert left == 0, "parameter values without a vessel"


def test_a_free_name_is_offered_rather_than_a_collision(db):
    from biofermentation.db import free_bioreactor_name

    assert free_bioreactor_name(db, "Wubbelbrew") == "Wubbelbrew"
    assert free_bioreactor_name(db, "BIOSTAT B") == "BIOSTAT B (2)"


def test_importing_a_bioreactor_under_a_new_name_adds_one(db, tmp_path):
    definition = export_bioreactor(db, "BIOSTAT ED")
    definition.name = "BIOSTAT ED (lab 2)"
    counts = import_bioreactor(db, definition)

    assert counts["parameters"] == len(definition.parameters)
    assert counts["unknown_parameters"] == 0
    names = [row["name"] for row in list_bioreactors(db)]
    assert names == ["BIOSTAT ED", "BIOSTAT B", "BIOSTAT ED (lab 2)"]


def test_an_existing_bioreactor_is_not_overwritten_by_accident(db):
    definition = export_bioreactor(db, "BIOSTAT ED")
    with pytest.raises(ValueError, match="already exists"):
        import_bioreactor(db, definition)

    definition.parameters["VLmax"] = 99.0
    import_bioreactor(db, definition, replace=True)
    assert export_bioreactor(db, "BIOSTAT ED").parameters["VLmax"] == 99.0


def test_a_parameter_this_installation_does_not_know_is_reported(db, tmp_path):
    definition = export_bioreactor(db, "BIOSTAT ED")
    definition.name = "Imaginary vessel"
    definition.parameters["not_a_parameter"] = 1.0

    counts = import_bioreactor(db, definition)
    assert counts["unknown_parameters"] == 1
    assert counts["unknown"] == ["not_a_parameter"]
    # And nothing was invented in parameterTab for it.
    with sqlite3.connect(db) as conn:
        assert not conn.execute(
            "SELECT COUNT(*) FROM parameterTab WHERE name = 'not_a_parameter'"
        ).fetchone()[0]


# ----------------------------------------------------------- organisms --


def test_an_organism_carries_its_models(db, tmp_path):
    """Without one, create_project has nothing to build a parameter set from."""
    definition = export_definition(db, "Escherichia coli")
    assert [model.name for model in definition.models] == ["Escherichia model"]
    assert len(definition.models[0].parameters) == 250

    path = write_definition(definition, tmp_path / "ecoli.yaml")
    again = load_definition(path)
    assert again.models[0].parameters == definition.models[0].parameters


def test_an_imported_organism_can_carry_a_project(db):
    definition = export_definition(db, "Escherichia coli")
    definition.display_name = "E. coli (lab strain)"
    counts = import_definition(db, definition)
    assert counts["models"] == 1
    assert counts["model_parameters"] == 250

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        model = conn.execute(
            "SELECT m.modelID, m.name FROM modelTab m JOIN organismTab o "
            "ON o.organismID = m.organismID WHERE o.name = ?",
            ("E. coli (lab strain)",),
        ).fetchone()
    # modelTab.name is unique across the table, not per organism.
    assert model["name"] != "Escherichia model"
    assert "E. coli (lab strain)" in model["name"]

    project_id = create_project(db, "From the import", model["modelID"])
    setup = load_phases(db, project_id)
    assert setup.info.organism_name == "E. coli (lab strain)"
    assert len(setup.p) == 250


def test_a_model_may_set_parameters_the_organism_does_not_define(db):
    """The vessel contributes its own; a project's set is the union."""
    definition = export_definition(db, "Escherichia coli")
    organism_parameters = {p.name for p in definition.parameters}
    model_parameters = set(definition.models[0].parameters)
    assert model_parameters - organism_parameters, "the fixture proves nothing otherwise"
    assert definition.validate() == []


# ------------------------------------------------------------ projects --


def _export(db, project_id, folder: Path, name: str = "package") -> Path:
    """What the export dialog writes, without the dialog."""
    from biofermentation.core.runner import DEFAULT_DT, load_project_state

    setup = load_phases(db, project_id)
    state, _ = load_project_state(db, project_id, dt=DEFAULT_DT)
    target = folder / name
    target.mkdir(parents=True, exist_ok=True)

    stop = state.idx + 1
    names = ["t", *sorted(n for n in state.v if n != "t" and hasattr(state.v[n], "size"))]
    with (target / "variables.csv").open("w", encoding="utf-8") as handle:
        handle.write(",".join(f"{n} [-]" for n in names) + "\n")
        for row in range(stop):
            handle.write(",".join(f"{float(state.v[n][row]):.10g}" for n in names) + "\n")

    write_manifest(target, setup, state, files={"variables": "variables.csv"})
    return target


def test_a_project_package_names_everything_it_needs(db, tmp_path):
    folder = _export(db, PICHIA_PROJECT, tmp_path)
    package = read_package(folder)

    assert package.organism == "Pichia pastoris"
    assert package.bioreactor == "BIOSTAT ED"
    assert package.model == "Pichia pastoris"
    assert package.parameters["cS1L0"] == pytest.approx(load_phases(db, PICHIA_PROJECT).p["cS1L0"])
    assert len(package.phases) == 5


def test_a_project_survives_an_export_and_an_import(db, tmp_path):
    before = load_phases(db, PICHIA_PROJECT)
    folder = _export(db, PICHIA_PROJECT, tmp_path)

    result = import_package(db, folder)
    after = load_phases(db, result["projectID"])

    assert after.info.organism_name == before.info.organism_name
    assert after.info.bioreactor_name == before.info.bioreactor_name
    # Every value the export carried is back. The new project may hold more:
    # it is created from the model first, and a parameter the export does not
    # mention keeps the model default rather than ending up empty. Project 519
    # predates four of its model's parameters.
    assert set(before.p) <= set(after.p)
    for name, value in before.p.items():
        assert after.p[name] == pytest.approx(value), name

    assert len(after.phases) == len(before.phases)
    for old, new in zip(before.phases, after.phases, strict=True):
        assert (new.name, new.typeID, new.statusID) == (old.name, old.typeID, old.statusID)
        assert new.start.typeID == old.start.typeID
        assert new.end.value == pytest.approx(old.end.value)
        assert new.parameters == pytest.approx(old.parameters)


def test_an_import_does_not_take_the_name_of_the_project_it_came_from(db, tmp_path):
    folder = _export(db, PICHIA_PROJECT, tmp_path)
    first = import_package(db, folder)
    second = import_package(db, folder)
    assert first["name"] != second["name"]
    assert first["projectID"] != second["projectID"]


def test_the_time_series_comes_back(db, tmp_path):
    from biofermentation.core.runner import DEFAULT_DT, load_project_state, run_steps
    from biofermentation.organisms import discover_organisms

    discover_organisms()
    setup = load_phases(db, ECOLI_PROJECT)
    state, organism = load_project_state(db, ECOLI_PROJECT, dt=DEFAULT_DT)
    state.p["f_Inoc"] = 1.0
    state.p["f_InocStart"] = 1.0
    run_steps(state, organism, 40)

    folder = tmp_path / "run"
    folder.mkdir()
    stop = state.idx + 1
    names = ["t", "cXL", "pO2"]
    with (folder / "variables.csv").open("w", encoding="utf-8") as handle:
        handle.write("t [h],cXL [g/l],pO2 [%]\n")
        for row in range(stop):
            handle.write(",".join(f"{float(state.v[n][row]):.10g}" for n in names) + "\n")
    write_manifest(folder, setup, state, files={"variables": "variables.csv"})

    result = import_package(db, folder)
    assert result["times"] == stop

    from biofermentation.db import load_project_variables

    series = load_project_variables(db, result["projectID"])
    assert series.n == stop
    assert series.v["cXL"][-1] == pytest.approx(float(state.v.cXL[state.idx]))


def test_a_missing_organism_says_which_one(db, tmp_path):
    folder = _export(db, PICHIA_PROJECT, tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM organismTab WHERE name = 'Pichia pastoris'")

    with pytest.raises(MissingPrerequisiteError) as raised:
        import_package(db, folder)
    assert raised.value.kind == "organism"
    assert raised.value.name == "Pichia pastoris"
    assert "Import the organism first" in str(raised.value)


def test_a_missing_bioreactor_says_which_one(db, tmp_path):
    folder = _export(db, PICHIA_PROJECT, tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM bioreactorTab WHERE name = 'BIOSTAT ED'")

    with pytest.raises(MissingPrerequisiteError) as raised:
        import_package(db, folder)
    assert raised.value.kind == "bioreactor"
    assert raised.value.name == "BIOSTAT ED"


def test_importing_after_supplying_the_organism_works(db, tmp_path):
    """The path the window walks: refuse, take the package, try again."""
    definition = export_definition(db, "Escherichia coli")
    yaml_path = write_definition(definition, tmp_path / "ecoli.yaml")
    folder = _export(db, ECOLI_PROJECT, tmp_path)

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM organismTab WHERE name = 'Escherichia coli'")
        conn.execute("DELETE FROM modelTab WHERE name = 'Escherichia model'")

    with pytest.raises(MissingPrerequisiteError):
        import_package(db, folder)

    import_definition(db, load_definition(yaml_path))
    result = import_package(db, folder)
    assert load_phases(db, result["projectID"]).info.organism_name == "Escherichia coli"


def test_pichia_can_be_exported_as_an_organism(db, tmp_path):
    """Held as a strict xfail until the duplicates in default_modelTab were
    repaired: without the export there is no moving a Pichia project to an
    installation that does not already have the organism."""
    definition = export_definition(db, "Pichia pastoris")
    assert [model.name for model in definition.models] == [
        "Pichia model (late stage)",
        "Pichia pastoris",
    ]

    definition.display_name = "P. pastoris (lab strain)"
    write_definition(definition, tmp_path / "pichia.yaml")
    counts = import_definition(db, load_definition(tmp_path / "pichia.yaml"))
    assert counts["models"] == 2


def test_a_pichia_project_can_be_moved_to_an_empty_installation(db, tmp_path):
    yaml_path = write_definition(export_definition(db, "Pichia pastoris"), tmp_path / "p.yaml")
    folder = _export(db, PICHIA_PROJECT, tmp_path)

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM organismTab WHERE name = 'Pichia pastoris'")
        conn.execute(
            "DELETE FROM modelTab WHERE organismID NOT IN (SELECT organismID FROM organismTab)"
        )

    with pytest.raises(MissingPrerequisiteError):
        import_package(db, folder)

    import_definition(db, load_definition(yaml_path))
    result = import_package(db, folder)
    assert load_phases(db, result["projectID"]).info.organism_name == "Pichia pastoris"


def test_a_folder_that_is_not_an_export_says_so(db, tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match=MANIFEST):
        read_package(empty)


def test_a_manifest_of_another_format_is_refused(db, tmp_path):
    folder = _export(db, PICHIA_PROJECT, tmp_path)
    path = folder / MANIFEST
    path.write_text(path.read_text().replace("biofermentation-project/1", "something/9"))
    with pytest.raises(ValueError, match="something/9"):
        read_package(folder)


def test_the_manifest_holds_no_numpy_scalars(db, tmp_path):
    """safe_dump refuses them, and a failed export is worse than a slow one."""
    import yaml

    folder = _export(db, ECOLI_PROJECT, tmp_path)
    raw = yaml.safe_load((folder / MANIFEST).read_text())
    for name, value in raw["parameters"].items():
        assert not isinstance(value, np.generic), name
