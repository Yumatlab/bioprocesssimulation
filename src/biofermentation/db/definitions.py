"""Organism definitions against the database (plan section 2.3).

export_definition() turns what is already in the database into a YAML
definition; import_definition() is the other direction and is the point of the
whole layer: a new organism becomes a file somebody can write without knowing
Python, and this fills categoryTab, parameterTab, variableTab,
variable_handlingTab, default_modelTab and organismTab from it.

Names, not ids, are the identity. Ids differ between installations, and a
definition that carried them would only be importable into the database it
came from.
"""

import sqlite3
from pathlib import Path

from ..organisms.definition import (
    CategoryDefinition,
    ModelDefinition,
    OrganismDefinition,
    ParameterDefinition,
    VariableDefinition,
)
from .connection import get_connection


def export_definition(db_path: Path | str, organism_name: str) -> OrganismDefinition:
    """Read an organism out of the database as a definition."""
    with get_connection(db_path, readonly=True) as conn:
        organism = conn.execute(
            "SELECT * FROM organismTab WHERE name = ?", (organism_name,)
        ).fetchone()
        if organism is None:
            raise LookupError(f"no organism named {organism_name!r} in the database")
        organism_id = organism["organismID"]

        categories = [
            CategoryDefinition(
                name=row["name"], section=row["section"], reading_rate=row["reading_rate"]
            )
            for row in conn.execute("SELECT * FROM categoryTab ORDER BY categoryID")
        ]

        parameters = [
            ParameterDefinition(
                name=row["name"],
                category=row["categoryname"],
                default=row["value"],
                tex=row["tex"],
                unit=row["unit"],
                tex_unit=row["tex_unit"],
                type=row["type"],
                internal_order=row["internal_order"],
                external_order=row["external_order"],
                description=row["description"],
            )
            for row in conn.execute(
                """
                SELECT p.name, c.name AS categoryname, d.value, p.tex, p.unit, p.tex_unit,
                       p.type, p.internal_order, p.external_order, d.description
                  FROM default_modelTab d
                  JOIN parameterTab p ON p.parameterID = d.parameterID
                  JOIN categoryTab c ON c.categoryID = p.categoryID
                 WHERE d.organismID = ?
                 ORDER BY p.parameterID
                """,
                (organism_id,),
            )
        ]

        process_variables = {
            row[0]
            for row in conn.execute(
                "SELECT variableID FROM process_variableTab WHERE organismID = ?", (organism_id,)
            )
        }

        variables = [
            VariableDefinition(
                name=row["name"],
                shorttex=row["shorttex"],
                longtex=row["longtex"],
                unit=row["unit"],
                tex_unit=row["tex_unit"],
                description=row["description"],
                visible=bool(row["visible"]),
                upload_rate=row["upload_rate"],
                initial_assignment=row["initial_assignment"],
                process_variable=row["variableID"] in process_variables,
            )
            for row in conn.execute(
                """
                SELECT v.variableID, v.name, v.shorttex, v.longtex, v.unit, v.tex_unit,
                       v.description, h.visible, h.upload_rate, h.initial_assignment
                  FROM variable_handlingTab h
                  JOIN variableTab v ON v.variableID = h.variableID
                 WHERE h.organismID = ?
                 ORDER BY v.variableID
                """,
                (organism_id,),
            )
        ]

        models = [
            ModelDefinition(
                name=row["name"],
                description=row["description"],
                parameters={
                    entry["name"]: entry["value"]
                    for entry in conn.execute(
                        """
                        SELECT p.name, mp.value
                          FROM model_parameterTab mp
                          JOIN parameterTab p ON p.parameterID = mp.parameterID
                         WHERE mp.modelID = ?
                        """,
                        (row["modelID"],),
                    )
                },
            )
            for row in conn.execute(
                "SELECT modelID, name, description FROM modelTab WHERE organismID = ? "
                "ORDER BY modelID",
                (organism_id,),
            )
        ]

    duplicates = sorted(
        {p.name for p in parameters if [q.name for q in parameters].count(p.name) > 1}
    )
    if duplicates:
        raise ValueError(
            f"default_modelTab holds more than one row per parameter for "
            f"{organism_name!r}: {', '.join(duplicates)}. A definition cannot say "
            "which value counts, so none is written. See CLAUDE.md, known defects."
        )

    return OrganismDefinition(
        name=organism["function_file"] or organism_name,
        display_name=organism_name,
        n_reservoirs=organism["reservoirs"],
        texname=organism["texname"],
        description=organism["description"],
        function_file=organism["function_file"],
        initialization_file=organism["initialization_file"],
        categories=categories,
        parameters=parameters,
        variables=variables,
        models=models,
    )


def import_definition(
    db_path: Path | str, definition: OrganismDefinition, *, replace: bool = False
) -> dict[str, int]:
    """Create or update an organism from a definition. One transaction.

    Rows shared with other organisms — categories, parameters, variables — are
    matched by name and reused, never duplicated. Only the per-organism rows
    (default_modelTab, variable_handlingTab, process_variableTab) belong to
    this organism alone and are rewritten.

    replace=True allows overwriting an organism that already exists. Without
    it an existing name is refused, so an import cannot quietly change the
    defaults of a running project.
    """
    problems = definition.validate()
    if problems:
        listing = "\n  ".join(problems)
        raise ValueError(f"definition {definition.name!r} is not usable:\n  {listing}")

    counts = dict.fromkeys(
        (
            "categories",
            "parameters",
            "variables",
            "defaults",
            "handling",
            "process_variables",
            "models",
            "model_parameters",
            "unknown_parameters",
        ),
        0,
    )

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT organismID FROM organismTab WHERE name = ?", (definition.display_name,)
        ).fetchone()
        if existing is not None and not replace:
            raise ValueError(
                f"organism {definition.display_name!r} already exists; "
                "pass replace=True to overwrite its defaults"
            )

        category_ids = _upsert_categories(conn, definition, counts)
        parameter_ids = _upsert_parameters(conn, definition, category_ids, counts)
        variable_ids = _upsert_variables(conn, definition, counts)
        organism_id = _upsert_organism(conn, definition, existing)

        # Per-organism rows are replaced wholesale — the definition is the
        # complete statement of what this organism has.
        conn.execute("DELETE FROM default_modelTab WHERE organismID = ?", (organism_id,))
        conn.executemany(
            """
            INSERT INTO default_modelTab (organismID, parameterID, value, description)
            VALUES (?, ?, ?, ?)
            """,
            [
                (organism_id, parameter_ids[p.name], p.default, p.description)
                for p in definition.parameters
            ],
        )
        counts["defaults"] = len(definition.parameters)

        conn.execute("DELETE FROM variable_handlingTab WHERE organismID = ?", (organism_id,))
        conn.executemany(
            """
            INSERT INTO variable_handlingTab
                (organismID, variableID, visible, upload_rate, initial_assignment)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    organism_id,
                    variable_ids[v.name],
                    int(v.visible),
                    v.upload_rate,
                    v.initial_assignment,
                )
                for v in definition.variables
            ],
        )
        counts["handling"] = len(definition.variables)

        conn.execute("DELETE FROM process_variableTab WHERE organismID = ?", (organism_id,))
        selected = [v for v in definition.variables if v.process_variable]
        next_id = (
            conn.execute(
                "SELECT COALESCE(MAX(process_variableID), 0) FROM process_variableTab"
            ).fetchone()[0]
            + 1
        )
        conn.executemany(
            "INSERT INTO process_variableTab (process_variableID, organismID, variableID) "
            "VALUES (?, ?, ?)",
            [
                (next_id + offset, organism_id, variable_ids[v.name])
                for offset, v in enumerate(selected)
            ],
        )
        counts["process_variables"] = len(selected)
        _upsert_models(conn, definition, organism_id, parameter_ids, counts)

    return counts


def _free_model_name(conn: sqlite3.Connection, name: str, organism: str) -> str:
    """A model name no other organism has already taken.

    modelTab.name is UNIQUE across the whole table, not per organism, so
    importing an organism next to one it was copied from collides on the
    model. The organism is put in brackets behind it, and a counter after
    that if even the pair is taken.
    """
    taken = {row[0] for row in conn.execute("SELECT name FROM modelTab")}
    if name not in taken:
        return name
    candidate = f"{name} ({organism})"
    suffix = 2
    while candidate in taken:
        candidate = f"{name} ({organism}) {suffix}"
        suffix += 1
    return candidate


def _upsert_models(
    conn: sqlite3.Connection,
    definition: OrganismDefinition,
    organism_id: int,
    parameter_ids: dict[str, int],
    counts: dict,
) -> None:
    """The models of this organism, replaced wholesale like its other rows.

    A project is created from a model, not from an organism: create_project
    reads model_parameterTab. An organism imported without one looks fine and
    then refuses the first project made from it.

    Names are resolved against the whole of parameterTab, not only against
    what this organism defines: a model's parameter set is the union of the
    organism's and the bioreactor's, and dropping the latter would leave every
    project made from it short of its vessel.
    """
    known = {
        row["name"]: row["parameterID"]
        for row in conn.execute("SELECT parameterID, name FROM parameterTab")
    } | parameter_ids
    existing = {
        row["name"]: row["modelID"]
        for row in conn.execute(
            "SELECT modelID, name FROM modelTab WHERE organismID = ?", (organism_id,)
        )
    }
    for model in definition.models:
        model_id = existing.get(model.name)
        if model_id is None:
            name = _free_model_name(conn, model.name, definition.display_name)
            model_id = conn.execute(
                "INSERT INTO modelTab (organismID, name, description) VALUES (?, ?, ?)",
                (organism_id, name, model.description),
            ).lastrowid
        else:
            conn.execute(
                "UPDATE modelTab SET description = ? WHERE modelID = ?",
                (model.description, model_id),
            )
        counts["models"] += 1

        conn.execute("DELETE FROM model_parameterTab WHERE modelID = ?", (model_id,))
        payload = [
            (model_id, known[name], value, None)
            for name, value in model.parameters.items()
            if name in known
        ]
        counts["unknown_parameters"] += len(model.parameters) - len(payload)
        conn.executemany(
            "INSERT INTO model_parameterTab (modelID, parameterID, value, description) "
            "VALUES (?, ?, ?, ?)",
            payload,
        )
        counts["model_parameters"] += len(payload)


def _upsert_categories(
    conn: sqlite3.Connection, definition: OrganismDefinition, counts: dict
) -> dict[str, int]:
    ids = {row["name"]: row["categoryID"] for row in conn.execute("SELECT * FROM categoryTab")}
    for category in definition.categories:
        if category.name in ids:
            continue
        cursor = conn.execute(
            "INSERT INTO categoryTab (name, section, reading_rate) VALUES (?, ?, ?)",
            (category.name, category.section, category.reading_rate),
        )
        ids[category.name] = cursor.lastrowid
        counts["categories"] += 1
    return ids


def _upsert_parameters(
    conn: sqlite3.Connection,
    definition: OrganismDefinition,
    category_ids: dict[str, int],
    counts: dict,
) -> dict[str, int]:
    ids = {row["name"]: row["parameterID"] for row in conn.execute("SELECT * FROM parameterTab")}
    # parameterTab.parameterID is not AUTOINCREMENT, so ids are assigned here.
    next_id = conn.execute("SELECT COALESCE(MAX(parameterID), 0) FROM parameterTab").fetchone()[0]
    for parameter in definition.parameters:
        if parameter.name in ids:
            continue
        next_id += 1
        conn.execute(
            """
            INSERT INTO parameterTab
                (parameterID, categoryID, name, tex, unit, tex_unit, type,
                 internal_order, external_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_id,
                category_ids[parameter.category],
                parameter.name,
                parameter.tex,
                parameter.unit,
                parameter.tex_unit,
                parameter.type,
                parameter.internal_order,
                parameter.external_order,
            ),
        )
        ids[parameter.name] = next_id
        counts["parameters"] += 1
    return ids


def _upsert_variables(
    conn: sqlite3.Connection, definition: OrganismDefinition, counts: dict
) -> dict[str, int]:
    ids = {row["name"]: row["variableID"] for row in conn.execute("SELECT * FROM variableTab")}
    for variable in definition.variables:
        if variable.name in ids:
            continue
        cursor = conn.execute(
            """
            INSERT INTO variableTab (name, shorttex, longtex, unit, tex_unit, description)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                variable.name,
                variable.shorttex,
                variable.longtex,
                variable.unit,
                variable.tex_unit,
                variable.description,
            ),
        )
        ids[variable.name] = cursor.lastrowid
        counts["variables"] += 1
    return ids


def _upsert_organism(
    conn: sqlite3.Connection, definition: OrganismDefinition, existing: sqlite3.Row | None
) -> int:
    if existing is not None:
        conn.execute(
            """
            UPDATE organismTab
               SET texname = ?, description = ?, function_file = ?,
                   initialization_file = ?, reservoirs = ?
             WHERE organismID = ?
            """,
            (
                definition.texname,
                definition.description,
                definition.function_file or definition.name,
                definition.initialization_file,
                definition.n_reservoirs,
                existing["organismID"],
            ),
        )
        return existing["organismID"]

    cursor = conn.execute(
        """
        INSERT INTO organismTab
            (name, texname, description, function_file, initialization_file, reservoirs)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            definition.display_name,
            definition.texname,
            definition.description,
            definition.function_file or definition.name,
            definition.initialization_file,
            definition.n_reservoirs,
        ),
    )
    return cursor.lastrowid
