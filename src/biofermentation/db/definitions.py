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
        ("categories", "parameters", "variables", "defaults", "handling", "process_variables"), 0
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

    return counts


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
