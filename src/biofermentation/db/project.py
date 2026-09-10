"""The two database accesses of a session (plan section 1.2).

load_phases() at session start, save_project() at session end, and
load_project_variables() when a project is resumed. Nothing in between — the
simulation loop and every editor work off the objects these return. That was
the central architectural decision of the MATLAB version 2 and it is kept.

Three places where this deviates from the MATLAB original, all deliberate:

  * dataTab rows for NaN values are not written at all. MATLAB wrote 0
    instead, which turns "not measured" into a measured zero and silently
    corrupts any later comparison.
  * load_project_variables() returns every variable of the organism, not just
    those with variable_handlingTab.visible = 1. MATLAB saved all and read
    back only the visible ones, so a resumed session quietly lost the rest.
    Visibility is a question for the plot, not for persistence.
  * Parameters, time series, phases and the log are written through one
    connection inside one transaction. MATLAB opened three, and the log
    section used a connection that had already been closed.
"""

import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np

from .connection import get_connection
from .models import (
    Condition,
    Lookups,
    Phase,
    ProjectInfo,
    ProjectSetup,
    VariableSeries,
)


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params)]


def _number(value: object) -> float | None:
    """SQLite gives back strings where MATLAB once wrote them. NULL stays None."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return None if isinstance(value, float) and math.isnan(value) else float(value)
    try:
        parsed = float(str(value))
    except ValueError:
        return None
    return None if math.isnan(parsed) else parsed


def _int_or_none(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


# --------------------------------------------------------------- loading --


def load_project_info(db_path: Path | str, project_id: int) -> ProjectInfo:
    """projectTab joined with organism, bioreactor and model."""
    with get_connection(db_path, readonly=True) as conn:
        row = conn.execute(
            """
            SELECT p.projectID, p.name, p.description, p.author, p.created_on,
                   p.recent_use, p.organismID, p.bioreactorID, p.modelID,
                   o.name AS organism_name, o.function_file, o.initialization_file,
                   o.reservoirs, b.name AS bioreactor_name
              FROM projectTab p
              LEFT JOIN organismTab o ON o.organismID = p.organismID
              LEFT JOIN bioreactorTab b ON b.bioreactorID = p.bioreactorID
             WHERE p.projectID = ?
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"no project with projectID {project_id}")
    return ProjectInfo(
        projectID=row["projectID"],
        name=row["name"],
        description=row["description"],
        author=row["author"],
        created_on=row["created_on"],
        recent_use=row["recent_use"],
        organismID=row["organismID"],
        organism_name=row["organism_name"],
        function_file=row["function_file"],
        initialization_file=row["initialization_file"],
        reservoirs=row["reservoirs"],
        bioreactorID=row["bioreactorID"],
        bioreactor_name=row["bioreactor_name"],
        modelID=row["modelID"],
    )


def load_phases(db_path: Path | str, project_id: int) -> ProjectSetup:
    """The single read at session start: lookups, parameters and phases."""
    info = load_project_info(db_path, project_id)

    with get_connection(db_path, readonly=True) as conn:
        lookups = Lookups(
            process_status=_rows(conn, "SELECT * FROM process_statusTab"),
            process_type=_rows(conn, "SELECT * FROM process_typeTab"),
            process_variable=_rows(
                conn,
                """
                SELECT pv.process_variableID, pv.variableID, v.name, v.shorttex, v.tex_unit
                  FROM process_variableTab pv
                  JOIN variableTab v ON v.variableID = pv.variableID
                """,
            ),
            variable=_rows(
                conn,
                """
                SELECT v.variableID, v.name, v.shorttex, v.longtex, v.unit,
                       v.tex_unit, v.description, h.upload_rate
                  FROM variableTab v
                  JOIN variable_handlingTab h ON h.variableID = v.variableID
                 WHERE h.organismID = ? AND h.visible = 1
                 ORDER BY v.variableID
                """,
                (info.organismID,),
            ),
            process_operator=_rows(conn, "SELECT * FROM process_operatorTab"),
            start_conditiontype=_rows(
                conn, "SELECT * FROM process_conditiontypeTab WHERE start_end = 1"
            ),
            end_conditiontype=_rows(
                conn, "SELECT * FROM process_conditiontypeTab WHERE start_end = 2"
            ),
        )

        p_meta = _rows(
            conn,
            """
            SELECT prop.parameterID, prop.name AS parametername, prop.tex,
                   ppara.value, prop.type, prop.unit, ppara.description,
                   c.name AS categoryname, c.section AS categorysection,
                   c.reading_rate
              FROM project_parameterTab ppara
              JOIN parameterTab prop ON prop.parameterID = ppara.parameterID
              JOIN categoryTab c ON c.categoryID = prop.categoryID
             WHERE ppara.projectID = ?
             ORDER BY c.section, c.name, prop.internal_order
            """,
            (project_id,),
        )
        p = {row["parametername"]: _number(row["value"]) for row in p_meta}
        p_meta_cyclic = [row for row in p_meta if row["reading_rate"] == "cyclic"]

        p_modes = _rows(
            conn,
            """
            SELECT p.name AS parametername, cm.value, cm.mode
              FROM parameter_controlmodesTab cm
              JOIN parameterTab p ON p.parameterID = cm.parameterID
            """,
        )

        phase_rows = _rows(
            conn,
            "SELECT * FROM processTab WHERE projectID = ? ORDER BY processID",
            (project_id,),
        )
        phase_params = _rows(
            conn,
            """
            SELECT pp.processID, p.name, pp.value
              FROM process_parameterTab pp
              JOIN parameterTab p ON p.parameterID = pp.parameterID
             WHERE pp.processID IN (SELECT processID FROM processTab WHERE projectID = ?)
            """,
            (project_id,),
        )

    by_process: dict[int, dict[str, float]] = {}
    for row in phase_params:
        by_process.setdefault(row["processID"], {})[row["name"]] = _number(row["value"])

    phases = [
        Phase(
            processID=row["processID"],
            projectID=row["projectID"],
            statusID=_int_or_none(row["process_statusID"]),
            typeID=_int_or_none(row["process_typeID"]),
            name=row["name"],
            reservoirID=_int_or_none(row["reservoirID"]),
            start=Condition(
                typeID=_int_or_none(row["start_typeID"]),
                variableID=_int_or_none(row["start_variableID"]),
                operatorID=_int_or_none(row["start_operatorID"]),
                value=_number(row["start_value"]),
                time=_number(row["start_time"]),
            ),
            end=Condition(
                typeID=_int_or_none(row["end_typeID"]),
                variableID=_int_or_none(row["end_variableID"]),
                operatorID=_int_or_none(row["end_operatorID"]),
                value=_number(row["end_value"]),
                time=_number(row["end_time"]),
            ),
            parameters=by_process.get(row["processID"], {}),
        )
        for row in phase_rows
    ]

    next_process_id = max((ph.processID for ph in phases), default=0) + 1

    return ProjectSetup(
        info=info,
        p=p,
        p_meta=p_meta,
        p_meta_cyclic=p_meta_cyclic,
        p_modes=p_modes,
        phases=phases,
        lookups=lookups,
        next_process_id=next_process_id,
    )


#: How the event type was smuggled into the message before logTab had a
#: column for it: "[Phase Event] the message".
_LOG_PREFIX = re.compile(r"^\s*\[([^\]]{1,40})\]\s*(.*)$", re.S)


def load_project_log(db_path: Path | str, project_id: int) -> list[dict]:
    """Every log entry of a project, oldest first.

    Rows written before logTab had an event_type column carry it as a
    "[...]" prefix on the message; it is read back out here rather than
    rewritten in the database, so a schema migration never touches stored
    text. Rows that have neither get the event type "Log".
    """
    with get_connection(db_path, readonly=True) as conn:
        rows = _rows(
            conn,
            """
            SELECT logID, datetime, event_type, message, process_time
              FROM logTab
             WHERE projectID = ?
             ORDER BY logID
            """,
            (project_id,),
        )

    entries = []
    for row in rows:
        event_type = row["event_type"]
        message = row["message"] or ""
        if not event_type:
            match = _LOG_PREFIX.match(message)
            event_type, message = match.groups() if match else ("Log", message)
        entries.append(
            {
                "logID": row["logID"],
                "datetime": row["datetime"],
                "event_type": event_type,
                "message": message,
                "process_time": _number(row["process_time"]) or 0.0,
            }
        )
    return entries


def load_model_defaults(db_path: Path | str, organism_id: int | None) -> dict[str, float]:
    """default_modelTab of one organism, keyed by parameter name.

    Used to put a parameter back where it started. Where the table has more
    than one row for a name — it does for three Pichia parameters, see
    CLAUDE.md — the last one wins, as MATLAB's loadPhases loop does.
    """
    if organism_id is None:
        return {}
    with get_connection(db_path, readonly=True) as conn:
        rows = _rows(
            conn,
            """
            SELECT p.name, d.value
              FROM default_modelTab d
              JOIN parameterTab p ON p.parameterID = d.parameterID
             WHERE d.organismID = ?
             ORDER BY d.default_modelparameterID
            """,
            (organism_id,),
        )
    return {row["name"]: _number(row["value"]) for row in rows if _number(row["value"]) is not None}


def load_project_variables(db_path: Path | str, project_id: int) -> VariableSeries:
    """The stored time series, pivoted from the long format of dataTab."""
    with get_connection(db_path, readonly=True) as conn:
        variables = _rows(
            conn,
            """
            SELECT vh.variableID, v.name
              FROM variableTab v
              JOIN variable_handlingTab vh ON vh.variableID = v.variableID
              JOIN projectTab p ON p.organismID = vh.organismID
             WHERE p.projectID = ?
             ORDER BY vh.variableID
            """,
            (project_id,),
        )
        times = _rows(
            conn,
            """
            SELECT timeID, process_time, datetime
              FROM timeTab
             WHERE projectID = ?
             ORDER BY process_time, timeID
            """,
            (project_id,),
        )
        data = _rows(
            conn,
            """
            SELECT d.timeID, d.variableID, d.value
              FROM dataTab d
              JOIN timeTab t ON t.timeID = d.timeID
             WHERE t.projectID = ?
            """,
            (project_id,),
        )

    names = [row["name"] for row in variables]
    if not times:
        return VariableSeries(t=np.empty(0), v={name: np.empty(0) for name in names}, real_t=[])

    time_index = {row["timeID"]: i for i, row in enumerate(times)}
    var_index = {row["variableID"]: i for i, row in enumerate(variables)}

    # Missing entries stay NaN. A zero here would be indistinguishable from a
    # measured zero.
    matrix = np.full((len(times), len(names)), np.nan)
    for row in data:
        i = time_index.get(row["timeID"])
        j = var_index.get(row["variableID"])
        if i is not None and j is not None:
            value = _number(row["value"])
            matrix[i, j] = np.nan if value is None else value

    return VariableSeries(
        t=np.array([_number(row["process_time"]) for row in times], dtype=float),
        v={name: matrix[:, j].copy() for j, name in enumerate(names)},
        real_t=[row["datetime"] if row["datetime"] is not None else "" for row in times],
    )


# --------------------------------------------------------------- saving --


def save_project(
    db_path: Path | str,
    project_id: int,
    *,
    p: dict[str, float] | None = None,
    series: VariableSeries | None = None,
    phases: list[Phase] | None = None,
    log: list[dict] | None = None,
) -> dict[str, int | list[str]]:
    """The single write at session end. One connection, one transaction.

    Returns what was written, plus 'unknown_parameters' for names in p that
    parameterTab does not know — those are skipped rather than raised over, so
    a typo cannot cost a whole session's results.
    """
    result: dict[str, int | list[str]] = {
        "parameters": 0,
        "times": 0,
        "values": 0,
        "phases": 0,
        "phase_parameters": 0,
        "log": 0,
        "unknown_parameters": [],
        "skipped_parameters": [],
    }

    with get_connection(db_path) as conn:
        if p:
            _save_parameters(conn, project_id, p, result)
        if series is not None:
            _save_series(conn, project_id, series, result)
        if phases is not None:
            _save_phases(conn, project_id, phases, result)
        if log:
            _save_log(conn, project_id, log, result)

    return result


def _save_parameters(
    conn: sqlite3.Connection, project_id: int, p: dict[str, float], result: dict
) -> None:
    known = {
        row["name"]: row["parameterID"]
        for row in conn.execute("SELECT parameterID, name FROM parameterTab")
    }
    payload = []
    for name, value in p.items():
        parameter_id = known.get(name)
        if parameter_id is None:
            result["unknown_parameters"].append(name)
            continue
        number = _number(value)
        if number is None:
            # sqlite3 binds NaN as NULL, which would erase the stored value.
            result["skipped_parameters"].append(name)
            continue
        payload.append((project_id, parameter_id, number))

    # UNIQUE (projectID, parameterID) from plan 1.1 is what makes this upsert
    # possible; without it the conflict target would not exist.
    conn.executemany(
        """
        INSERT INTO project_parameterTab (projectID, parameterID, value)
        VALUES (?, ?, ?)
        ON CONFLICT (projectID, parameterID) DO UPDATE SET value = excluded.value
        """,
        payload,
    )
    result["parameters"] = len(payload)


def _save_series(
    conn: sqlite3.Connection, project_id: int, series: VariableSeries, result: dict
) -> None:
    """Append the time steps that are not in the database yet.

    COUNT(*) rather than MAX(): on an empty table MAX() returns NULL, which
    was a recurring crash in the MATLAB version.
    """
    saved = conn.execute(
        "SELECT COUNT(*) FROM timeTab WHERE projectID = ?", (project_id,)
    ).fetchone()[0]
    if series.n <= saved:
        return

    variables = {
        row["name"]: row["variableID"]
        for row in conn.execute(
            """
            SELECT vh.variableID, v.name
              FROM variableTab v
              JOIN variable_handlingTab vh ON vh.variableID = v.variableID
              JOIN projectTab p ON p.organismID = vh.organismID
             WHERE p.projectID = ?
            """,
            (project_id,),
        )
    }
    fallback = datetime.now().strftime("%d.%m.%Y %H:%M:%S.%f")[:-3]

    values: list[tuple] = []
    for i in range(saved, series.n):
        # Drop the NaN preallocation slots at the end of every series.
        process_time = _number(series.t[i])
        if process_time is None:
            continue
        stamp = series.real_t[i] if i < len(series.real_t) and series.real_t[i] else fallback
        cursor = conn.execute(
            "INSERT INTO timeTab (projectID, datetime, process_time) VALUES (?, ?, ?)",
            (project_id, stamp, process_time),
        )
        time_id = cursor.lastrowid
        result["times"] += 1

        for name, variable_id in variables.items():
            column = series.v.get(name)
            if column is None or i >= column.size:
                continue
            value = _number(column[i])
            if value is None:
                continue
            values.append((variable_id, time_id, value))

    conn.executemany("INSERT INTO dataTab (variableID, timeID, value) VALUES (?, ?, ?)", values)
    result["values"] = len(values)


def _save_phases(
    conn: sqlite3.Connection, project_id: int, phases: list[Phase], result: dict
) -> None:
    """Replace the project's phases wholesale.

    ON DELETE CASCADE clears process_parameterTab along with them — which it
    only does because get_connection() switches foreign keys on.
    """
    conn.execute("DELETE FROM processTab WHERE projectID = ?", (project_id,))

    known = {
        row["name"]: row["parameterID"]
        for row in conn.execute("SELECT parameterID, name FROM parameterTab")
    }

    for phase in phases:
        conn.execute(
            """
            INSERT INTO processTab
                (processID, projectID, process_statusID, process_typeID, name,
                 start_typeID, start_variableID, start_operatorID, start_value, start_time,
                 end_typeID, end_variableID, end_operatorID, end_value, end_time, reservoirID)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                phase.processID,
                project_id,
                phase.statusID,
                phase.typeID,
                phase.name,
                phase.start.typeID,
                phase.start.variableID,
                phase.start.operatorID,
                _number(phase.start.value),
                _number(phase.start.time),
                phase.end.typeID,
                phase.end.variableID,
                phase.end.operatorID,
                _number(phase.end.value),
                _number(phase.end.time),
                phase.reservoirID,
            ),
        )
        result["phases"] += 1

        payload = [
            (phase.processID, known[name], _number(value))
            for name, value in phase.parameters.items()
            if name in known and _number(value) is not None
        ]
        conn.executemany(
            "INSERT INTO process_parameterTab (processID, parameterID, value) VALUES (?, ?, ?)",
            payload,
        )
        result["phase_parameters"] += len(payload)


def _save_log(conn: sqlite3.Connection, project_id: int, log: list[dict], result: dict) -> None:
    """Append the entries that are not in logTab yet.

    An entry knows whether it is stored: logID is None until it is written,
    and this function fills it in. Counting the rows already there — what
    this did before — only works while a session neither loads a log nor
    saves twice, and silently duplicates or swallows entries as soon as it
    does either.
    """
    written = 0
    for entry in log:
        if entry.get("logID") is not None:
            continue
        cursor = conn.execute(
            """
            INSERT INTO logTab
                (projectID, datetime, event_type, message, process_time,
                 parameterID, old_value, new_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                entry.get("datetime") or datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                entry.get("event_type"),
                entry.get("message"),
                _number(entry.get("process_time")),
                entry.get("parameterID"),
                entry.get("old_value"),
                entry.get("new_value"),
            ),
        )
        # Back into the caller's dict, so the next save skips this one.
        entry["logID"] = cursor.lastrowid
        written += 1
    result["log"] = written


# --------------------------------------------------------------- backup --


def save_project_with_backup(db_path: Path | str, project_id: int, **state) -> tuple[dict, Path]:
    """save_project() plus a copy of the database (plan section 1.3).

    Never implemented in MATLAB; the database was lost to corruption twice.
    The copy is taken after a successful write, so it always holds a database
    that at least committed cleanly.
    """
    result = save_project(db_path, project_id, **state)

    db_path = Path(db_path)
    backup_path = db_path.with_suffix(".backup.db")
    # sqlite3's own backup API rather than a file copy: it goes through SQLite,
    # so the WAL is included and the copy is consistent even while the database
    # is open elsewhere. VACUUM INTO would do as well but cannot run inside the
    # transaction get_connection() holds.
    backup_path.unlink(missing_ok=True)
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return result, backup_path


# ------------------------------------------------- projects, plan 5 --
#
# The two paths that destroyed the production database. See CLAUDE.md,
# "Anforderung an Phase 5". Both are one transaction here, both leave the
# cascading to SQLite, and neither ever switches foreign keys off.


def list_projects(db_path: Path | str) -> list[dict]:
    """Projects with their organism, bioreactor and how complete they are.

    parameters against expected is what tells a usable project from the
    residue of an interrupted create or delete.
    """
    with get_connection(db_path, readonly=True) as conn:
        return _rows(
            conn,
            """
            SELECT p.projectID, p.name, p.description, p.author, p.created_on,
                   p.recent_use, p.organismID, p.bioreactorID, p.modelID,
                   o.name AS organism_name, b.name AS bioreactor_name,
                   (SELECT COUNT(*) FROM project_parameterTab pp
                     WHERE pp.projectID = p.projectID) AS parameters,
                   (SELECT COUNT(*) FROM model_parameterTab mp
                     WHERE mp.modelID = p.modelID) AS expected
              FROM projectTab p
              LEFT JOIN organismTab o ON o.organismID = p.organismID
              LEFT JOIN bioreactorTab b ON b.bioreactorID = p.bioreactorID
             ORDER BY p.recent_use DESC, p.projectID DESC
            """,
        )


def list_models(db_path: Path | str) -> list[dict]:
    """Selectable models, as the project creator lists them."""
    with get_connection(db_path, readonly=True) as conn:
        return _rows(
            conn,
            """
            SELECT m.modelID, m.name, m.description, m.display_rank,
                   m.organismID, m.bioreactorID,
                   o.name AS organism_name, o.function_file, o.reservoirs,
                   b.name AS bioreactor_name,
                   (SELECT COUNT(*) FROM model_parameterTab mp
                     WHERE mp.modelID = m.modelID) AS parameters
              FROM modelTab m
              LEFT JOIN organismTab o ON o.organismID = m.organismID
              LEFT JOIN bioreactorTab b ON b.bioreactorID = m.bioreactorID
             ORDER BY m.display_rank, m.modelID
            """,
        )


def unique_project_name(db_path: Path | str, name: str) -> str:
    """A free name, appending _1, _2 … the way uniqueProjectname does."""
    with get_connection(db_path, readonly=True) as conn:
        taken = {row[0] for row in conn.execute("SELECT name FROM projectTab")}
    if name not in taken:
        return name
    suffix = 1
    while f"{name}_{suffix}" in taken:
        suffix += 1
    return f"{name}_{suffix}"


def create_project(
    db_path: Path | str,
    name: str,
    model_id: int,
    *,
    author: str = "",
    description: str = "",
) -> int:
    """Create a project and its parameter set. One transaction.

    MATLAB inserts the project row and then bulk-writes 250 parameter rows
    without a transaction. An interruption in between leaves a project that
    cannot be opened — project 732 of the production database has 42 of its
    250 rows, ending exactly on the highest id ever assigned. Here the row and
    its parameters are one unit: either both or neither.
    """
    if not name.strip():
        raise ValueError("a project needs a name")

    with get_connection(db_path) as conn:
        model = conn.execute(
            "SELECT modelID, organismID, bioreactorID FROM modelTab WHERE modelID = ?",
            (model_id,),
        ).fetchone()
        if model is None:
            raise LookupError(f"no model with modelID {model_id}")

        defaults = conn.execute(
            "SELECT parameterID, value, description FROM model_parameterTab WHERE modelID = ?",
            (model_id,),
        ).fetchall()
        if not defaults:
            raise ValueError(f"model {model_id} has no parameters; a project from it is unusable")

        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S.%f")[:-3]
        cursor = conn.execute(
            """
            INSERT INTO projectTab
                (name, description, author, created_on, recent_use,
                 organismID, bioreactorID, modelID)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                description,
                author,
                timestamp,
                timestamp,
                model["organismID"],
                model["bioreactorID"],
                model_id,
            ),
        )
        project_id = cursor.lastrowid

        conn.executemany(
            """
            INSERT INTO project_parameterTab (projectID, parameterID, value, description)
            VALUES (?, ?, ?, ?)
            """,
            [
                (project_id, row["parameterID"], row["value"], row["description"])
                for row in defaults
            ],
        )

    return project_id


def delete_project(db_path: Path | str, project_id: int) -> dict[str, int]:
    """Delete a project and everything hanging off it. One transaction.

    MATLAB's ClosingScreen.deleteProject switches foreign keys off, deletes
    from dataTab, timeTab and project_parameterTab by hand, switches them back
    on and deletes the project row last — five statements, each committing on
    its own. An interruption leaves the data gone and the project row standing.
    Three projects of the production database are in exactly that state.

    Here one DELETE removes the row and SQLite cascades the rest, inside the
    transaction get_connection holds and with foreign keys on throughout.
    """
    with get_connection(db_path) as conn:
        if (
            conn.execute(
                "SELECT COUNT(*) FROM projectTab WHERE projectID = ?", (project_id,)
            ).fetchone()[0]
            == 0
        ):
            raise LookupError(f"no project with projectID {project_id}")

        before = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE projectID = ?", (project_id,)
            ).fetchone()[0]
            for table in ("project_parameterTab", "processTab", "timeTab", "logTab")
        }
        before["dataTab"] = conn.execute(
            "SELECT COUNT(*) FROM dataTab WHERE timeID IN "
            "(SELECT timeID FROM timeTab WHERE projectID = ?)",
            (project_id,),
        ).fetchone()[0]

        conn.execute("DELETE FROM projectTab WHERE projectID = ?", (project_id,))

    return before
