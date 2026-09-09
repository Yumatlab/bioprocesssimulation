"""Repairing the damage the MATLAB create and delete paths left behind.

This is data repair, not schema repair — migrate_schema.sql handles the
schema. Both run on a copy first; neither touches a database in place without
being asked to.

What is repaired, and why it is safe:

  * Half-created and half-deleted projects. CreateProject wrote the project
    row and its 250 parameter rows without a transaction, and
    ClosingScreen.deleteProject removed a project's data with foreign keys
    switched off and the project row last, again without a transaction. Both
    leave a project that cannot be opened: the row exists, its parameters do
    not. Such a project is unusable by definition, so removing it loses
    nothing that was not already lost.

  * Duplicate rows in default_modelTab. Pichia has two rows each for yXpOgr,
    yCpO and qOpXm. The second of each carries the value and the description
    of a methanol toxicity parameter — kS2tox, kappatox, qXpXtox — which
    exists separately and correctly with exactly that value. The stray is
    identifiable without a judgement call: its description belongs to another
    parameter that already holds the same number.
"""

import sqlite3
from pathlib import Path

from .connection import get_connection

# Rows whose description names a different parameter that already holds the
# same value. Kept explicit rather than derived, so a repair never guesses.
STRAY_MODEL_DEFAULTS = (
    ("yXpOgr", "Methanol toxicity concentration [5%v/v]", "kS2tox"),
    ("yCpO", "Slope of toxicity turn on function", "kappatox"),
    ("qOpXm", "Methanol death rate", "qXpXtox"),
)


def find_broken_projects(db_path: Path | str) -> list[dict]:
    """Projects that cannot be opened because their parameters are missing.

    A complete project carries one project_parameterTab row per parameter of
    its model. Anything short of that is the residue of an interrupted create
    or delete.
    """
    with get_connection(db_path, readonly=True) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.projectID, p.name, p.created_on, p.recent_use,
                       COUNT(pp.project_parameterID) AS parameters,
                       (SELECT COUNT(*) FROM model_parameterTab mp
                         WHERE mp.modelID = p.modelID) AS expected
                  FROM projectTab p
                  LEFT JOIN project_parameterTab pp ON pp.projectID = p.projectID
                 GROUP BY p.projectID
                HAVING parameters < expected
                 ORDER BY p.projectID
                """
            )
        ]


def find_duplicate_model_defaults(db_path: Path | str) -> list[dict]:
    """default_modelTab rows that describe a parameter other than their own."""
    with get_connection(db_path, readonly=True) as conn:
        found = []
        for name, description, belongs_to in STRAY_MODEL_DEFAULTS:
            for row in conn.execute(
                """
                SELECT d.default_modelparameterID, d.organismID, p.name, d.value,
                       d.description
                  FROM default_modelTab d
                  JOIN parameterTab p ON p.parameterID = d.parameterID
                 WHERE p.name = ? AND d.description = ?
                """,
                (name, description),
            ):
                found.append(dict(row) | {"belongs_to": belongs_to})
        return found


def find_corrupted_project_parameters(db_path: Path | str) -> list[dict]:
    """Projects that inherited a stray value into project_parameterTab.

    The three parameters the strays sit on are restored from
    model_parameterTab, which is where CreateProject reads its defaults and
    which holds the correct numbers — 1.773, 1.375 and 0.0117 — next to the
    toxicity parameters that hold 40, 15 and 0.5 in their own right.

    Only these three names are considered. Every other difference between a
    project and its model is an operator's setting and none of this code's
    business.
    """
    names = tuple(name for name, _, _ in STRAY_MODEL_DEFAULTS)
    placeholders = ", ".join("?" * len(names))
    with get_connection(db_path, readonly=True) as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT pp.projectID, p.name, pp.value AS stored, m.value AS correct,
                       pp.parameterID
                  FROM project_parameterTab pp
                  JOIN parameterTab p ON p.parameterID = pp.parameterID
                  JOIN projectTab pr ON pr.projectID = pp.projectID
                  JOIN model_parameterTab m
                    ON m.parameterID = pp.parameterID AND m.modelID = pr.modelID
                 WHERE p.name IN ({placeholders})
                   AND ABS(COALESCE(pp.value, 0) - COALESCE(m.value, 0)) > 1e-12
                 ORDER BY pp.projectID, p.name
                """,
                names,
            )
        ]


def repair(db_path: Path | str, *, dry_run: bool = True) -> dict:
    """Report what is broken, and with dry_run=False repair it.

    Everything happens in the one transaction get_connection holds, with
    foreign keys on — the deletion of a project cascades the way SQLite
    intends rather than being taken apart by hand.
    """
    broken = find_broken_projects(db_path)
    strays = find_duplicate_model_defaults(db_path)
    corrupted = find_corrupted_project_parameters(db_path)
    report = {
        "broken_projects": broken,
        "stray_defaults": strays,
        "corrupted_parameters": corrupted,
        "applied": not dry_run,
    }
    if dry_run:
        return report

    with get_connection(db_path) as conn:
        conn.executemany(
            "DELETE FROM projectTab WHERE projectID = ?",
            [(row["projectID"],) for row in broken],
        )
        conn.executemany(
            "DELETE FROM default_modelTab WHERE default_modelparameterID = ?",
            [(row["default_modelparameterID"],) for row in strays],
        )
        conn.executemany(
            "UPDATE project_parameterTab SET value = ? "
            " WHERE projectID = ? AND parameterID = ?",
            [(row["correct"], row["projectID"], row["parameterID"]) for row in corrupted],
        )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"repair left foreign key violations: {violations}")

    # VACUUM cannot run inside a transaction, so it gets its own connection.
    # The database is 98.9 % free pages before this.
    conn = sqlite3.connect(Path(db_path), isolation_level=None)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    return report
