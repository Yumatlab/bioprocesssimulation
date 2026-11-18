"""Things the model gained after the databases were made.

A user's database is a copy of the template taken when they first ran the
program, so it does not know a parameter or a variable that was introduced
later. The functions here add them — the way `repair.add_flags` added the
anti-windup switches: one transaction, idempotent, a dry run by default.

The antifoam reservoir (16.11.2026)
-----------------------------------
The original model has no volume for antifoam: `AAF` is an activity that
decays, the dosing has no pump rate, and the vessel on the flow sheet could
show no level. Two parameters and two series give it one, named after the
acid and alkali vessels (T1, T2):

    VT30    volume of the antifoam reservoir at t = 0      [l]
    FT3max  rate of the antifoam pump                      [l/h]
    VT3     volume left in the reservoir                   [l]
    FT3     flow of the antifoam pump                      [l/h]

A database without them still runs: the models read both parameters with a
default of 0, which means no pump and no level.
"""

import sqlite3
from pathlib import Path

from .connection import get_connection
from .repair import find_broken_projects

#: Category of the reservoir volumes and pump rates of the vessel.
INSTRUMENTATION = "Instrumentation"

ANTIFOAM_PARAMETERS = (
    {
        "name": "VT30",
        "tex": "V_{T30}",
        "unit": "l",
        "tex_unit": "l",
        "value": 0.5,
        "description": "Antifoam reservoir volume at t = 0 h",
    },
    {
        "name": "FT3max",
        "tex": "F_{T3max}",
        "unit": "l/h",
        "tex_unit": "lh^{-1}",
        "value": 0.1,
        "description": "Pump rate of the antifoam pump",
    },
)

ANTIFOAM_VARIABLES = (
    {
        "name": "VT3",
        "tex": "V_{T3}",
        "unit": "l",
        "tex_unit": "l",
        "description": "Antifoam reservoir volume",
        "initial": "app.p.VT30",
    },
    {
        "name": "FT3",
        "tex": "F_{T3}",
        "unit": "l/h",
        "tex_unit": "lh^{-1}",
        "description": "Pump rate antifoam",
        "initial": "0",
    },
)


def _missing(conn: sqlite3.Connection, table: str, entries: tuple[dict, ...]) -> list[dict]:
    """The entries whose name the table does not hold yet."""
    return [
        entry
        for entry in entries
        if conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE name = ?", (entry["name"],)
        ).fetchone()[0]
        == 0
    ]


def add_antifoam_reservoir(db_path: Path | str, *, dry_run: bool = True) -> dict:
    """Add the antifoam reservoir's parameters and series to a database.

    Every bioreactor, every model and every whole project gets the two
    parameters with their default values; every organism gets the two series.
    Half-created projects are left alone, for the reason `add_flags` gives.
    Running it again changes nothing.
    """
    report = {"parameters": [], "variables": [], "rows": 0, "applied": not dry_run}
    with get_connection(db_path, readonly=True) as conn:
        parameters = _missing(conn, "parameterTab", ANTIFOAM_PARAMETERS)
        variables = _missing(conn, "variableTab", ANTIFOAM_VARIABLES)
        category = conn.execute(
            "SELECT categoryID FROM categoryTab WHERE name = ?", (INSTRUMENTATION,)
        ).fetchone()
        if category is None:
            raise LookupError(f"the database has no {INSTRUMENTATION!r} category")
        category_id = category["categoryID"]
    report["parameters"] = [entry["name"] for entry in parameters]
    report["variables"] = [entry["name"] for entry in variables]
    if dry_run or not (parameters or variables):
        return report

    broken = {row["projectID"] for row in find_broken_projects(db_path)}
    with get_connection(db_path) as conn:
        bioreactors = [
            r["bioreactorID"] for r in conn.execute("SELECT bioreactorID FROM bioreactorTab")
        ]
        models = [r["modelID"] for r in conn.execute("SELECT modelID FROM modelTab")]
        organisms = [r["organismID"] for r in conn.execute("SELECT organismID FROM organismTab")]
        projects = [
            r["projectID"]
            for r in conn.execute("SELECT projectID FROM projectTab")
            if r["projectID"] not in broken
        ]

        next_id = (conn.execute("SELECT MAX(parameterID) FROM parameterTab").fetchone()[0] or 0) + 1
        order = (
            conn.execute(
                "SELECT MAX(internal_order) FROM parameterTab WHERE categoryID = ?", (category_id,)
            ).fetchone()[0]
            or 0
        )
        for entry in parameters:
            order += 1
            conn.execute(
                "INSERT INTO parameterTab (parameterID, categoryID, name, tex, unit,"
                " tex_unit, type, internal_order, external_order)"
                " VALUES (?, ?, ?, ?, ?, ?, 'editfield', ?, ?)",
                (
                    next_id,
                    category_id,
                    entry["name"],
                    entry["tex"],
                    entry["unit"],
                    entry["tex_unit"],
                    order,
                    category_id * 100 + order,
                ),
            )
            report["rows"] += 1
            values = (next_id, entry["value"], entry["description"])
            for table, column, owners in (
                ("default_bioreactorTab", "bioreactorID", bioreactors),
                ("model_parameterTab", "modelID", models),
                ("project_parameterTab", "projectID", projects),
            ):
                for owner in owners:
                    conn.execute(
                        f"INSERT INTO {table} ({column}, parameterID, value, description)"
                        " VALUES (?, ?, ?, ?)",
                        (owner, *values),
                    )
                    report["rows"] += 1
            next_id += 1

        next_id = (conn.execute("SELECT MAX(variableID) FROM variableTab").fetchone()[0] or 0) + 1
        for entry in variables:
            conn.execute(
                "INSERT INTO variableTab (variableID, name, shorttex, longtex, unit,"
                " tex_unit, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    next_id,
                    entry["name"],
                    entry["tex"],
                    entry["tex"],
                    entry["unit"],
                    entry["tex_unit"],
                    entry["description"],
                ),
            )
            report["rows"] += 1
            for organism in organisms:
                conn.execute(
                    "INSERT INTO variable_handlingTab (organismID, variableID, visible,"
                    " upload_rate, initial_assignment) VALUES (?, ?, 1, 'cyclic', ?)",
                    (organism, next_id, entry["initial"]),
                )
                report["rows"] += 1
            next_id += 1

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"adding the antifoam reservoir left foreign key violations: {violations}"
        )
    return report
