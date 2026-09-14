"""Bioreactors as portable definitions (points 3 and 4 of the review).

The counterpart of db/definitions.py for the vessel. A project's parameter
set is the union of what its organism defines and what its bioreactor does —
`VLmax`, `NStmax`, the heat transfer areas, the pump limits — so a project
cannot be moved between installations unless its vessel can be too.

Names, not ids, are the identity, for the same reason as everywhere else in
this layer: ids differ between installations.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .connection import get_connection


@dataclass
class BioreactorDefinition:
    """One row of bioreactorTab with the parameter values that belong to it."""

    name: str
    manufacturer: str | None = None
    description: str | None = None
    #: parameter name -> value, from default_bioreactorTab.
    parameters: dict[str, float] = field(default_factory=dict)
    #: parameter name -> description, where the row carries one.
    descriptions: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        problems = []
        if not self.name:
            problems.append("a bioreactor needs a name")
        if not self.parameters:
            problems.append(f"bioreactor {self.name!r} has no parameters")
        return problems


def list_bioreactors(db_path: Path | str) -> list[dict]:
    with get_connection(db_path, readonly=True) as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT bioreactorID, name, manufacturer, description FROM bioreactorTab "
                "ORDER BY bioreactorID"
            )
        ]


def export_bioreactor(db_path: Path | str, name: str) -> BioreactorDefinition:
    """Read a bioreactor out of the database as a definition."""
    with get_connection(db_path, readonly=True) as conn:
        row = conn.execute("SELECT * FROM bioreactorTab WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise LookupError(f"no bioreactor named {name!r} in the database")

        values, descriptions = {}, {}
        for entry in conn.execute(
            """
            SELECT p.name, d.value, d.description
              FROM default_bioreactorTab d
              JOIN parameterTab p ON p.parameterID = d.parameterID
             WHERE d.bioreactorID = ?
             ORDER BY p.internal_order, p.parameterID
            """,
            (row["bioreactorID"],),
        ):
            values[entry["name"]] = entry["value"]
            if entry["description"]:
                descriptions[entry["name"]] = entry["description"]

    return BioreactorDefinition(
        name=row["name"],
        manufacturer=row["manufacturer"],
        description=row["description"],
        parameters=values,
        descriptions=descriptions,
    )


def import_bioreactor(
    db_path: Path | str, definition: BioreactorDefinition, *, replace: bool = False
) -> dict[str, int]:
    """Create or update a bioreactor from a definition. One transaction.

    Parameters are matched by name against parameterTab and never created
    there: a vessel that names a parameter this installation does not know is
    reported rather than invented, because a parameter without a category and
    a unit would be unusable in every editor.
    """
    problems = definition.validate()
    if problems:
        listing = "\n  ".join(problems)
        raise ValueError(f"bioreactor {definition.name!r} is not usable:\n  {listing}")

    counts = {"parameters": 0, "unknown_parameters": 0}
    unknown: list[str] = []

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT bioreactorID FROM bioreactorTab WHERE name = ?", (definition.name,)
        ).fetchone()
        if existing is not None and not replace:
            raise ValueError(
                f"bioreactor {definition.name!r} already exists; "
                "pass replace=True to overwrite its values"
            )

        if existing is None:
            bioreactor_id = conn.execute(
                "INSERT INTO bioreactorTab (name, manufacturer, description) VALUES (?, ?, ?)",
                (definition.name, definition.manufacturer, definition.description),
            ).lastrowid
        else:
            bioreactor_id = existing["bioreactorID"]
            conn.execute(
                "UPDATE bioreactorTab SET manufacturer = ?, description = ? WHERE bioreactorID = ?",
                (definition.manufacturer, definition.description, bioreactor_id),
            )

        known = {
            row["name"]: row["parameterID"]
            for row in conn.execute("SELECT parameterID, name FROM parameterTab")
        }
        unknown = sorted(set(definition.parameters) - set(known))

        conn.execute("DELETE FROM default_bioreactorTab WHERE bioreactorID = ?", (bioreactor_id,))
        payload = [
            (bioreactor_id, known[name], value, definition.descriptions.get(name))
            for name, value in definition.parameters.items()
            if name in known
        ]
        conn.executemany(
            "INSERT INTO default_bioreactorTab "
            "(bioreactorID, parameterID, value, description) VALUES (?, ?, ?, ?)",
            payload,
        )
        counts["parameters"] = len(payload)
        counts["unknown_parameters"] = len(unknown)
        counts["bioreactorID"] = bioreactor_id

    if unknown:
        counts["unknown"] = unknown
    return counts


def bioreactor_parameters(db_path: Path | str, name: str) -> list[dict]:
    """The vessel's parameters with what an editor needs to show them.

    `export_bioreactor` is the transfer contract and carries values only; a
    form needs the symbol, the unit and the category as well. Ordered the way
    the other parameter dialogs order things: by section, category and the
    order the parameter carries itself.
    """
    with get_connection(db_path, readonly=True) as conn:
        row = conn.execute(
            "SELECT bioreactorID FROM bioreactorTab WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no bioreactor named {name!r} in the database")
        return [
            dict(entry)
            for entry in conn.execute(
                """
                SELECT p.name AS parametername, p.tex, p.unit, p.type,
                       c.name AS categoryname, c.section AS categorysection,
                       d.value, d.description
                  FROM default_bioreactorTab d
                  JOIN parameterTab p ON p.parameterID = d.parameterID
                  JOIN categoryTab c ON c.categoryID = p.categoryID
                 WHERE d.bioreactorID = ?
                 ORDER BY c.section, c.name, p.internal_order, p.parameterID
                """,
                (row["bioreactorID"],),
            )
        ]


def bioreactor_usage(db_path: Path | str, name: str) -> dict[str, int]:
    """How many models and projects stand on this vessel.

    Asked before deleting one: a project keeps its own copy of the parameter
    values, but its row still points here, and a dangling reference is not
    something to find out about later.
    """
    with get_connection(db_path, readonly=True) as conn:
        row = conn.execute(
            "SELECT bioreactorID FROM bioreactorTab WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no bioreactor named {name!r} in the database")
        bioreactor_id = row["bioreactorID"]
        return {
            "models": conn.execute(
                "SELECT COUNT(*) FROM modelTab WHERE bioreactorID = ?", (bioreactor_id,)
            ).fetchone()[0],
            "projects": conn.execute(
                "SELECT COUNT(*) FROM projectTab WHERE bioreactorID = ?", (bioreactor_id,)
            ).fetchone()[0],
        }


def delete_bioreactor(db_path: Path | str, name: str) -> dict[str, int]:
    """Remove a vessel and its parameter values. One transaction.

    Refuses while anything stands on it. The alternative — letting the cascade
    take the models and their parameter sets with it — is how the MATLAB
    version lost projects, and it is not on offer here.
    """
    usage = bioreactor_usage(db_path, name)
    if usage["models"] or usage["projects"]:
        raise ValueError(
            f"bioreactor {name!r} is still used by {usage['models']} model(s) and "
            f"{usage['projects']} project(s); delete those first"
        )

    with get_connection(db_path) as conn:
        bioreactor_id = conn.execute(
            "SELECT bioreactorID FROM bioreactorTab WHERE name = ?", (name,)
        ).fetchone()["bioreactorID"]
        values = conn.execute(
            "DELETE FROM default_bioreactorTab WHERE bioreactorID = ?", (bioreactor_id,)
        ).rowcount
        conn.execute("DELETE FROM bioreactorTab WHERE bioreactorID = ?", (bioreactor_id,))
    return {"parameters": values}


def free_bioreactor_name(db_path: Path | str, name: str) -> str:
    """`name`, or the first "name (2)" that is not taken."""
    taken = {row["name"] for row in list_bioreactors(db_path)}
    if name not in taken:
        return name
    number = 2
    while f"{name} ({number})" in taken:
        number += 1
    return f"{name} ({number})"


def write_bioreactor(definition: BioreactorDefinition, path: Path | str) -> Path:
    path = Path(path)
    payload = {k: v for k, v in asdict(definition).items() if v not in (None, {}, [])}
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return path


def load_bioreactor(path: Path | str) -> BioreactorDefinition:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    definition = BioreactorDefinition(
        name=raw.get("name", ""),
        manufacturer=raw.get("manufacturer"),
        description=raw.get("description"),
        parameters={str(k): float(v) for k, v in (raw.get("parameters") or {}).items()},
        descriptions={str(k): str(v) for k, v in (raw.get("descriptions") or {}).items()},
    )
    problems = definition.validate()
    if problems:
        listing = "\n  ".join(problems)
        raise ValueError(f"{path.name} is not a usable bioreactor definition:\n  {listing}")
    return definition
