"""Process templates: a phase list saved under a name, for one model.

Projektplan_Prozessvorlagen.md, phase 1. A template is bound to the model the
process was designed on (decision E1): within one model the parameter names,
the process variables of the organism and the reservoirs all exist, so a
saved phase means the same thing when it is loaded again.

**This module breaks the rule of two database accesses per session, on
purpose.** A template has to be stored the moment it is saved — whatever
becomes of the project afterwards — and the list of templates is read when
the dialog opens. Every function here is one short transaction of its own
through get_connection, touches only the three template tables (and, to
resolve names, parameterTab), and is called from a dialog, never from the
timer. It cannot meet the project's own save halfway.

What is stored of a phase: its type, name, reservoir, the start and end
condition without their times, and its parameters by name — **except the
results a feed phase writes for itself** (t{n}j, cXL{n}j, FR{n}j, see
`_exponential_feed`). Those describe a run that happened, not a plan; in the
shipped projects they are the only parameters a fed-batch phase carries
(Phase 0 finding P0-2).
"""

import math
import re
from datetime import datetime
from pathlib import Path

from .connection import get_connection
from .models import Condition, Phase, ProcessTemplate

#: What a feed phase records about its own start. Results, never settings:
#: control.phases.PHASE_PARAMETERS leaves them out of the editor for the same
#: reason. Matches exactly t1j..t3j, cXL1j..cXL3j and FR1j..FR3j in the
#: shipped parameterTab, and no other parameter.
RESULT_PARAMETER = re.compile(r"(t|cXL|FR)\d+j")

#: Same format as projectTab.created_on.
STAMP_FORMAT = "%d.%m.%Y %H:%M:%S.%f"


class TemplateExistsError(ValueError):
    """A template of this name already exists for this model."""


def is_result_parameter(name: str) -> bool:
    return RESULT_PARAMETER.fullmatch(name) is not None


def _stamp() -> str:
    return datetime.now().strftime(STAMP_FORMAT)[:-3]


def _number(value) -> float | None:
    """A finite float, or None. NaN is never written (CLAUDE.md)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_or_none(value) -> int | None:
    return None if value is None else int(value)


# ------------------------------------------------------------- reading --


def list_process_templates(db_path: Path | str, model_id: int) -> list[dict]:
    """The templates of one model, by name, with the number of their phases."""
    with get_connection(db_path, readonly=True) as conn:
        rows = conn.execute(
            """
            SELECT t.templateID, t.modelID, t.name, t.description, t.author, t.created_on,
                   (SELECT COUNT(*) FROM process_template_phaseTab p
                     WHERE p.templateID = t.templateID) AS phases
              FROM process_templateTab t
             WHERE t.modelID = ?
             ORDER BY t.name COLLATE NOCASE
            """,
            (model_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def template_count(db_path: Path | str, model_id: int) -> int:
    with get_connection(db_path, readonly=True) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM process_templateTab WHERE modelID = ?", (model_id,)
        ).fetchone()[0]


def load_process_template(db_path: Path | str, template_id: int) -> ProcessTemplate:
    """One template with its phases in their saved order."""
    with get_connection(db_path, readonly=True) as conn:
        head = conn.execute(
            "SELECT * FROM process_templateTab WHERE templateID = ?", (template_id,)
        ).fetchone()
        if head is None:
            raise LookupError(f"no process template with templateID {template_id}")
        phase_rows = conn.execute(
            "SELECT * FROM process_template_phaseTab WHERE templateID = ? ORDER BY position",
            (template_id,),
        ).fetchall()
        parameter_rows = conn.execute(
            """
            SELECT tp.template_phaseID, p.name, tp.value
              FROM process_template_parameterTab tp
              JOIN parameterTab p ON p.parameterID = tp.parameterID
              JOIN process_template_phaseTab ph ON ph.template_phaseID = tp.template_phaseID
             WHERE ph.templateID = ?
             ORDER BY tp.template_parameterID
            """,
            (template_id,),
        ).fetchall()

    by_phase: dict[int, dict[str, float]] = {}
    for row in parameter_rows:
        by_phase.setdefault(row["template_phaseID"], {})[row["name"]] = row["value"]

    phases = [
        Phase(
            processID=0,
            projectID=0,
            statusID=None,
            typeID=row["process_typeID"],
            name=row["name"],
            reservoirID=_int_or_none(row["reservoirID"]),
            start=Condition(
                typeID=_int_or_none(row["start_typeID"]),
                variableID=_int_or_none(row["start_variableID"]),
                operatorID=_int_or_none(row["start_operatorID"]),
                value=_number(row["start_value"]),
            ),
            end=Condition(
                typeID=_int_or_none(row["end_typeID"]),
                variableID=_int_or_none(row["end_variableID"]),
                operatorID=_int_or_none(row["end_operatorID"]),
                value=_number(row["end_value"]),
            ),
            parameters=by_phase.get(row["template_phaseID"], {}),
        )
        for row in phase_rows
    ]
    return ProcessTemplate(
        templateID=head["templateID"],
        modelID=head["modelID"],
        name=head["name"],
        description=head["description"],
        author=head["author"],
        created_on=head["created_on"],
        phases=phases,
    )


# ------------------------------------------------------------- writing --


def save_process_template(
    db_path: Path | str,
    model_id: int,
    name: str,
    description: str | None,
    phases: list[Phase],
    *,
    author: str | None = None,
    replace: bool = False,
) -> int:
    """Store the phases as a template of this model. Returns its templateID.

    One transaction. A template of the same name in the same model raises
    TemplateExistsError unless `replace` is set (decision E3); with it, the
    old one is deleted and the new one written in the same transaction, so
    an interrupted save leaves the old template, not half of either.

    A parameter name the database does not know is refused with its name —
    the template could not hold it, and dropping it silently would make the
    loaded process differ from the saved one without anybody seeing it.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("a process template needs a name")
    if not phases:
        raise ValueError("a process template needs at least one phase")

    with get_connection(db_path) as conn:
        if (
            conn.execute("SELECT COUNT(*) FROM modelTab WHERE modelID = ?", (model_id,)).fetchone()[
                0
            ]
            == 0
        ):
            raise LookupError(f"no model with modelID {model_id}")
        known = {
            row["name"]: row["parameterID"]
            for row in conn.execute("SELECT parameterID, name FROM parameterTab")
        }
        unknown = sorted(
            {
                parameter
                for phase in phases
                for parameter in phase.parameters
                if parameter not in known and not is_result_parameter(parameter)
            }
        )
        if unknown:
            raise LookupError(f"unknown parameter(s): {', '.join(unknown)}")

        existing = conn.execute(
            "SELECT templateID FROM process_templateTab WHERE modelID = ? AND name = ?",
            (model_id, name),
        ).fetchone()
        if existing is not None:
            if not replace:
                raise TemplateExistsError(f"a process template named {name!r} already exists")
            conn.execute(
                "DELETE FROM process_templateTab WHERE templateID = ?", (existing["templateID"],)
            )

        template_id = conn.execute(
            "INSERT INTO process_templateTab (modelID, name, description, author, created_on)"
            " VALUES (?, ?, ?, ?, ?)",
            (model_id, name, (description or "").strip() or None, author, _stamp()),
        ).lastrowid

        for position, phase in enumerate(phases, start=1):
            phase_id = conn.execute(
                """
                INSERT INTO process_template_phaseTab
                    (templateID, position, process_typeID, name, reservoirID,
                     start_typeID, start_variableID, start_operatorID, start_value,
                     end_typeID, end_variableID, end_operatorID, end_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    position,
                    phase.typeID,
                    phase.name,
                    phase.reservoirID,
                    phase.start.typeID,
                    phase.start.variableID,
                    phase.start.operatorID,
                    _number(phase.start.value),
                    phase.end.typeID,
                    phase.end.variableID,
                    phase.end.operatorID,
                    _number(phase.end.value),
                ),
            ).lastrowid
            conn.executemany(
                "INSERT INTO process_template_parameterTab (template_phaseID, parameterID, value)"
                " VALUES (?, ?, ?)",
                [
                    (phase_id, known[parameter], _number(value))
                    for parameter, value in phase.parameters.items()
                    if not is_result_parameter(parameter) and _number(value) is not None
                ],
            )
    return template_id


def rename_process_template(
    db_path: Path | str, template_id: int, name: str, description: str | None = None
) -> None:
    """New name (and description, if given). Names stay unique per model."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a process template needs a name")
    with get_connection(db_path) as conn:
        head = conn.execute(
            "SELECT modelID FROM process_templateTab WHERE templateID = ?", (template_id,)
        ).fetchone()
        if head is None:
            raise LookupError(f"no process template with templateID {template_id}")
        clash = conn.execute(
            "SELECT COUNT(*) FROM process_templateTab"
            " WHERE modelID = ? AND name = ? AND templateID != ?",
            (head["modelID"], name, template_id),
        ).fetchone()[0]
        if clash:
            raise TemplateExistsError(f"a process template named {name!r} already exists")
        if description is None:
            conn.execute(
                "UPDATE process_templateTab SET name = ? WHERE templateID = ?",
                (name, template_id),
            )
        else:
            conn.execute(
                "UPDATE process_templateTab SET name = ?, description = ? WHERE templateID = ?",
                (name, description.strip() or None, template_id),
            )


def delete_process_template(db_path: Path | str, template_id: int) -> int:
    """Remove a template; its phases and parameters cascade. Returns the phases."""
    with get_connection(db_path) as conn:
        phases = conn.execute(
            "SELECT COUNT(*) FROM process_template_phaseTab WHERE templateID = ?",
            (template_id,),
        ).fetchone()[0]
        deleted = conn.execute(
            "DELETE FROM process_templateTab WHERE templateID = ?", (template_id,)
        ).rowcount
    if not deleted:
        raise LookupError(f"no process template with templateID {template_id}")
    return phases


def copy_process_templates(conn, source_model_id: int, target_model_id: int) -> int:
    """Copy every template of one model to another, inside the caller's transaction.

    For duplicate_model (decision E8): a duplicated model is a variant of the
    same process. Returns the number of templates copied.
    """
    templates = conn.execute(
        "SELECT * FROM process_templateTab WHERE modelID = ? ORDER BY templateID",
        (source_model_id,),
    ).fetchall()
    for template in templates:
        new_template = conn.execute(
            "INSERT INTO process_templateTab (modelID, name, description, author, created_on)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                target_model_id,
                template["name"],
                template["description"],
                template["author"],
                template["created_on"],
            ),
        ).lastrowid
        for phase in conn.execute(
            "SELECT * FROM process_template_phaseTab WHERE templateID = ? ORDER BY position",
            (template["templateID"],),
        ).fetchall():
            new_phase = conn.execute(
                """
                INSERT INTO process_template_phaseTab
                    (templateID, position, process_typeID, name, reservoirID,
                     start_typeID, start_variableID, start_operatorID, start_value,
                     end_typeID, end_variableID, end_operatorID, end_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_template,
                    phase["position"],
                    phase["process_typeID"],
                    phase["name"],
                    phase["reservoirID"],
                    phase["start_typeID"],
                    phase["start_variableID"],
                    phase["start_operatorID"],
                    phase["start_value"],
                    phase["end_typeID"],
                    phase["end_variableID"],
                    phase["end_operatorID"],
                    phase["end_value"],
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO process_template_parameterTab (template_phaseID, parameterID, value)"
                " SELECT ?, parameterID, value FROM process_template_parameterTab"
                " WHERE template_phaseID = ?",
                (new_phase, phase["template_phaseID"]),
            )
    return len(templates)


__all__ = [
    "RESULT_PARAMETER",
    "TemplateExistsError",
    "copy_process_templates",
    "delete_process_template",
    "is_result_parameter",
    "list_process_templates",
    "load_process_template",
    "rename_process_template",
    "save_process_template",
    "template_count",
]
