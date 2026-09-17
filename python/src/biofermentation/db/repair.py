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


#: Parameters the database defines and nothing reads.
#:
#: `tmax` ("Time limit for cultivation") is one: no organism model touches it,
#: neither here nor in the MATLAB sources, and its category is `invisible`, so
#: no dialog ever showed it either. It sat in parameterTab, in both organisms'
#: defaults, in three models and in five projects, carrying a number that
#: decided nothing. The two occurrences in FigureApp.mlapp are a local
#: variable for the x-range of the plot and a tooltip about it — a different
#: thing with the same name.
#:
#: Nothing else in this list yet. A parameter belongs here only once it has
#: been shown to be unread, not because it looks unused.
DEAD_PARAMETERS = ("tmax",)


def find_dead_parameters(
    db_path: Path | str, names: tuple[str, ...] = DEAD_PARAMETERS
) -> list[dict]:
    """Where each of `names` still sits, with the rows it occupies."""
    found = []
    with get_connection(db_path, readonly=True) as conn:
        for name in names:
            row = conn.execute(
                "SELECT parameterID FROM parameterTab WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                continue
            parameter_id = row["parameterID"]
            counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE parameterID = ?",
                    (parameter_id,),
                ).fetchone()[0]
                for table in (
                    "default_modelTab",
                    "model_parameterTab",
                    "project_parameterTab",
                    "default_bioreactorTab",
                    "process_parameterTab",
                    "parameter_controlmodesTab",
                )
            }
            found.append({"name": name, "parameterID": parameter_id, **counts})
    return found


def remove_dead_parameters(
    db_path: Path | str, names: tuple[str, ...] = DEAD_PARAMETERS, *, dry_run: bool = True
) -> dict:
    """Drop a parameter and every value of it. One transaction.

    Separate from `repair()` on purpose: that function fixes what is wrong,
    this one removes what is merely pointless, and the two should not be one
    switch. Idempotent — a parameter that is already gone is not an error.
    """
    found = find_dead_parameters(db_path, names)
    report = {"parameters": found, "applied": not dry_run, "rows": 0}
    if dry_run or not found:
        return report

    with get_connection(db_path) as conn:
        for entry in found:
            for table in (
                "default_modelTab",
                "model_parameterTab",
                "project_parameterTab",
                "default_bioreactorTab",
                "process_parameterTab",
                "parameter_controlmodesTab",
            ):
                report["rows"] += conn.execute(
                    f"DELETE FROM {table} WHERE parameterID = ?",
                    (entry["parameterID"],),
                ).rowcount
            report["rows"] += conn.execute(
                "DELETE FROM parameterTab WHERE parameterID = ?", (entry["parameterID"],)
            ).rowcount
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"removing dead parameters left foreign key violations: {violations}")
    return report


#: The anti-windup switches, one per controller that has an integrator whose
#: output is limited. The pH controller has none — it is a P controller with
#: a dead band — so it has no switch either.
ANTI_WINDUP_PARAMETERS = (
    {"name": "f_awpO2", "tex": "aw_{pO_2}", "order": 20},
    {"name": "f_awtemp", "tex": "aw_{\\vartheta}", "order": 21},
    {"name": "f_awLW", "tex": "aw_{LW}", "order": 22},
    {"name": "f_awfeed", "tex": "aw_{feed}", "order": 23},
)

#: Where a flag belongs: categoryTab row 'Flags', section 'Parameters',
#: reading_rate 'cyclic' — changeable while the simulation runs, which is the
#: whole point of a switch a student is meant to try out mid-run.
FLAG_CATEGORY = "Flags"


def add_flags(
    db_path: Path | str,
    parameters: tuple[dict, ...] = ANTI_WINDUP_PARAMETERS,
    *,
    dry_run: bool = True,
) -> dict:
    """Add switch parameters and give every model and project a value of 0.

    The counterpart of `remove_dead_parameters`, and built the same way: one
    transaction, idempotent, a dry run by default.

    A parameter that exists in `parameterTab` but nowhere else is invisible —
    the dialogs read a project's own set. So each new flag is written into
    `default_modelTab` for every organism, `model_parameterTab` for every
    model and `project_parameterTab` for every project, always as 0. Nothing
    changes behaviour by being added; the switch has to be thrown.
    """
    report = {"added": [], "rows": 0, "applied": not dry_run}
    with get_connection(db_path, readonly=True) as conn:
        category = conn.execute(
            "SELECT categoryID FROM categoryTab WHERE name = ?", (FLAG_CATEGORY,)
        ).fetchone()
        if category is None:
            raise LookupError(f"the database has no {FLAG_CATEGORY!r} category")
        category_id = category["categoryID"]
        missing = [
            entry
            for entry in parameters
            if conn.execute(
                "SELECT COUNT(*) FROM parameterTab WHERE name = ?", (entry["name"],)
            ).fetchone()[0]
            == 0
        ]
        report["added"] = [entry["name"] for entry in missing]
    if dry_run or not missing:
        return report

    with get_connection(db_path) as conn:
        next_id = (conn.execute("SELECT MAX(parameterID) FROM parameterTab").fetchone()[0] or 0) + 1
        organisms = [r["organismID"] for r in conn.execute("SELECT organismID FROM organismTab")]
        models = [r["modelID"] for r in conn.execute("SELECT modelID FROM modelTab")]
        # Whole projects only. Nine projects in the productive database were
        # left half-created by the MATLAB path — 732 has 42 contiguous rows
        # ending exactly on the highest id ever assigned, and that contiguity
        # *is* the evidence of an interrupted write. Appending four rows with
        # high ids would break it and erase the only remaining record of what
        # that path did. A project nobody can open does not need a switch.
        broken = {row["projectID"] for row in find_broken_projects(db_path)}
        projects = [
            r["projectID"]
            for r in conn.execute("SELECT projectID FROM projectTab")
            if r["projectID"] not in broken
        ]
        for entry in missing:
            conn.execute(
                "INSERT INTO parameterTab (parameterID, categoryID, name, tex, unit,"
                " tex_unit, type, internal_order, external_order)"
                " VALUES (?, ?, ?, ?, '', '', 'switch', ?, ?)",
                (next_id, category_id, entry["name"], entry["tex"], entry["order"],
                 800 + entry["order"]),
            )
            report["rows"] += 1
            for organism_id in organisms:
                conn.execute(
                    "INSERT INTO default_modelTab (organismID, parameterID, value)"
                    " VALUES (?, ?, 0)",
                    (organism_id, next_id),
                )
                report["rows"] += 1
            for model_id in models:
                conn.execute(
                    "INSERT INTO model_parameterTab (modelID, parameterID, value) VALUES (?, ?, 0)",
                    (model_id, next_id),
                )
                report["rows"] += 1
            for project_id in projects:
                conn.execute(
                    "INSERT INTO project_parameterTab (projectID, parameterID, value)"
                    " VALUES (?, ?, 0)",
                    (project_id, next_id),
                )
                report["rows"] += 1
            next_id += 1
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"adding flags left foreign key violations: {violations}")
    return report


#: The gains of Pichia's closed-loop feed on reservoir 2, as shipped and as
#: measured. The three stored values are, digit for digit, `KP_feedpO2`,
#: `KI_feedpO2` and `KD_feedpO2` — a copy of the pO2 feed controller, where a
#: negative sign is right because a high pO2 means the culture can take more
#: substrate. On a substrate loop, whose error is `cS2Lw - cS2L`, the same
#: sign inverts the controller: too little methanol gives a positive error, a
#: negative output, and a pump that stays shut for the whole run.
#:
#: The replacements are measured, not guessed. `tools/tune_pichia.py` is the
#: bench; over eight hours of the late-stage model they hold cS2L at 1.38 g/l
#: against a setpoint of 1.5 with the pump never once at a stop, and they hold
#: across setpoints from 1.0 to 3.0 g/l, step widths of 2, 5 and 10 s and half
#: the reservoir concentration.
PICHIA_FEED_GAINS = {
    "KP_feedR2": (-2.0, 1.0),
    "KI_feedR2": (-15.0, 5.0),
    "KD_feedR2": (-0.009, 0.005),
}


def correct_pichia_feed_gains(db_path: Path | str, *, dry_run: bool = True) -> dict:
    """Turn the inverted feed gains of reservoir 2 into measured ones.

    Only the organism defaults and the models are touched — `default_modelTab`
    and `model_parameterTab`. **A project that already exists keeps its own
    values**, which is the same rule every other change to a default follows
    and the reason a stored run stays reproducible.

    Only a value that still stands at the shipped number is replaced. Anybody
    who has tuned their own is left alone, and a second run changes nothing.
    """
    report = {"changed": {}, "rows": 0, "applied": not dry_run}
    with get_connection(db_path, readonly=True) as conn:
        organism = conn.execute(
            "SELECT organismID FROM organismTab WHERE name LIKE 'Pichia%'"
        ).fetchone()
        if organism is None:
            return report
        organism_id = organism["organismID"]
        models = [
            row["modelID"]
            for row in conn.execute(
                "SELECT modelID FROM modelTab WHERE organismID = ?", (organism_id,)
            )
        ]
        ids = {
            row["name"]: row["parameterID"]
            for row in conn.execute(
                "SELECT name, parameterID FROM parameterTab WHERE name IN "
                f"({', '.join('?' * len(PICHIA_FEED_GAINS))})",
                tuple(PICHIA_FEED_GAINS),
            )
        }
        for name, (shipped, measured) in PICHIA_FEED_GAINS.items():
            if name not in ids:
                continue
            stands = conn.execute(
                "SELECT COUNT(*) FROM default_modelTab WHERE organismID = ? "
                "AND parameterID = ? AND value = ?",
                (organism_id, ids[name], shipped),
            ).fetchone()[0]
            if stands:
                report["changed"][name] = (shipped, measured)

    if dry_run or not report["changed"]:
        return report

    with get_connection(db_path) as conn:
        for name, (shipped, measured) in report["changed"].items():
            report["rows"] += conn.execute(
                "UPDATE default_modelTab SET value = ? WHERE organismID = ? "
                "AND parameterID = ? AND value = ?",
                (measured, organism_id, ids[name], shipped),
            ).rowcount
            for model_id in models:
                report["rows"] += conn.execute(
                    "UPDATE model_parameterTab SET value = ? WHERE modelID = ? "
                    "AND parameterID = ? AND value = ?",
                    (measured, model_id, ids[name], shipped),
                ).rowcount
    return report


def repair(
    db_path: Path | str,
    *,
    dry_run: bool = True,
    remove_broken_projects: bool = False,
) -> dict:
    """Report what is broken, and with dry_run=False repair it.

    Everything happens in the one transaction get_connection holds, with
    foreign keys on — the deletion of a project cascades the way SQLite
    intends rather than being taken apart by hand.

    The two parameter repairs are safe by construction: a stray default is
    identified by carrying another parameter's description next to that
    parameter's own value, and a corrupted project value is restored from
    model_parameterTab, which holds the right number.

    Deleting a half-created project is not in that class. It is unopenable,
    but it is also the only remaining record of what the MATLAB create path
    did, so it goes only when asked for — `remove_broken_projects=True`. The
    report lists them either way.
    """
    broken = find_broken_projects(db_path)
    strays = find_duplicate_model_defaults(db_path)
    corrupted = find_corrupted_project_parameters(db_path)
    report = {
        "broken_projects": broken,
        "stray_defaults": strays,
        "corrupted_parameters": corrupted,
        "applied": not dry_run,
        "removed_projects": bool(not dry_run and remove_broken_projects),
    }
    if dry_run:
        return report

    with get_connection(db_path) as conn:
        if remove_broken_projects:
            conn.executemany(
                "DELETE FROM projectTab WHERE projectID = ?",
                [(row["projectID"],) for row in broken],
            )
        conn.executemany(
            "DELETE FROM default_modelTab WHERE default_modelparameterID = ?",
            [(row["default_modelparameterID"],) for row in strays],
        )
        conn.executemany(
            "UPDATE project_parameterTab SET value = ?  WHERE projectID = ? AND parameterID = ?",
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
