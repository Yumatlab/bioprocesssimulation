"""Moving a whole project between installations (point 3 of the review).

An export is written for a person to read: the phase table says
"Exponential Feed" and "Variable condition: cS1L [g/l] <= 0.1", not the ids
the database joins on. Reading that back would mean parsing prose, so the
export carries a manifest next to it — the same content in the shape the
importer needs, keyed by name throughout.

The two files are not redundant. The CSVs are the record; the manifest is the
machine's copy of it, and `MANIFEST` is the only file the importer reads.

What an import needs from the target installation is the organism and the
bioreactor: a project's parameter set is the union of what those two define,
and neither can be invented from the export. When one is missing the import
stops with `MissingPrerequisiteError`, which names what to import first — see
db/definitions.py and db/bioreactors.py for those two packages.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from .connection import get_connection
from .models import Condition, Phase, VariableSeries
from .project import create_project, save_project, unique_project_name

#: The manifest, next to the human-readable tables.
MANIFEST = "project.yaml"
#: What this module writes and what it refuses to read.
FORMAT = "biofermentation-project/1"


class MissingPrerequisiteError(LookupError):
    """The target installation lacks the organism or the bioreactor.

    `kind` is "organism" or "bioreactor" and `name` is what the export asked
    for, so a window can offer to import that package and try again.
    """

    def __init__(self, kind: str, name: str):
        super().__init__(
            f"this database has no {kind} named {name!r}. Import the {kind} first, "
            f"then the project."
        )
        self.kind = kind
        self.name = name


@dataclass
class ProjectPackage:
    """What an export says about the project it came from."""

    name: str
    organism: str
    bioreactor: str | None = None
    model: str | None = None
    description: str = ""
    author: str = ""
    exported: str = ""
    parameters: dict[str, float] = field(default_factory=dict)
    phases: list[dict] = field(default_factory=list)
    #: Name of the CSV holding the time series, relative to the folder.
    variables_file: str | None = None
    log_file: str | None = None


# ------------------------------------------------------------- writing --


def write_manifest(folder: Path | str, setup, state, *, files: dict[str, str]) -> Path:
    """The machine-readable half of an export.

    `files` names the tables that were written, so an importer can find the
    time series whatever format the user chose.
    """
    folder = Path(folder)
    info = setup.info
    payload = {
        "format": FORMAT,
        "exported": datetime.now().isoformat(timespec="seconds"),
        "project": {
            "name": info.name,
            "description": info.description or "",
            "author": info.author or "",
            "organism": info.organism_name,
            "bioreactor": info.bioreactor_name,
            "model": _model_name(setup),
            "reservoirs": info.reservoirs,
        },
        "files": files,
        "parameters": {name: _plain(value) for name, value in state.p.items()},
        "phases": [_phase_payload(phase) for phase in setup.phases],
    }
    path = folder / MANIFEST
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return path


def _model_name(setup) -> str | None:
    return setup.info.model_name


def _plain(value):
    """numpy scalars do not survive safe_dump."""
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, (int, float, str)) or value is None:
        return value
    return float(value)


def _phase_payload(phase: Phase) -> dict:
    return {
        "name": phase.name,
        "typeID": phase.typeID,
        "statusID": phase.statusID,
        "reservoirID": phase.reservoirID,
        "start": _condition_payload(phase.start),
        "end": _condition_payload(phase.end),
        "parameters": {name: _plain(value) for name, value in phase.parameters.items()},
    }


def _condition_payload(condition: Condition) -> dict:
    return {
        "typeID": condition.typeID,
        "variableID": condition.variableID,
        "operatorID": condition.operatorID,
        "value": _plain(condition.value),
        "time": _plain(condition.time),
    }


# ------------------------------------------------------------- reading --


def read_package(folder: Path | str) -> ProjectPackage:
    """Read the manifest of an export. Raises if it is not one."""
    folder = Path(folder)
    path = folder / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(
            f"{folder} is not a project export: no {MANIFEST}. Exports written "
            "before this format was introduced cannot be imported."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    declared = raw.get("format")
    if declared != FORMAT:
        raise ValueError(f"{path.name} says format {declared!r}; this reads {FORMAT!r}")

    project = raw.get("project") or {}
    files = raw.get("files") or {}
    return ProjectPackage(
        name=project.get("name") or folder.name,
        organism=project.get("organism") or "",
        bioreactor=project.get("bioreactor"),
        model=project.get("model"),
        description=project.get("description") or "",
        author=project.get("author") or "",
        exported=raw.get("exported") or "",
        parameters={str(k): v for k, v in (raw.get("parameters") or {}).items()},
        phases=list(raw.get("phases") or []),
        variables_file=files.get("variables"),
        log_file=files.get("log"),
    )


def check_prerequisites(db_path: Path | str, package: ProjectPackage) -> None:
    """Raise MissingPrerequisiteError for whatever the target lacks."""
    with get_connection(db_path, readonly=True) as conn:
        if not conn.execute(
            "SELECT COUNT(*) FROM organismTab WHERE name = ?", (package.organism,)
        ).fetchone()[0]:
            raise MissingPrerequisiteError("organism", package.organism)
        if (
            package.bioreactor
            and not conn.execute(
                "SELECT COUNT(*) FROM bioreactorTab WHERE name = ?", (package.bioreactor,)
            ).fetchone()[0]
        ):
            raise MissingPrerequisiteError("bioreactor", package.bioreactor)


def import_package(db_path: Path | str, folder: Path | str, *, name: str | None = None) -> dict:
    """Create a project from an export and put its history back.

    Returns the new projectID together with what was written. The project is
    created through create_project — one transaction, the parameter set from
    the model — and the export's own values are then written over it, so a
    parameter the export does not mention keeps the model default rather than
    ending up empty.
    """
    folder = Path(folder)
    package = read_package(folder)
    check_prerequisites(db_path, package)

    model_id, bioreactor_id = _resolve(db_path, package)
    title = unique_project_name(db_path, name or package.name)
    project_id = create_project(
        db_path,
        title,
        model_id,
        author=package.author,
        description=package.description,
    )

    if bioreactor_id is not None:
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE projectTab SET bioreactorID = ? WHERE projectID = ?",
                (bioreactor_id, project_id),
            )

    series = _read_series(folder, package)
    phases = _phases(db_path, project_id, package)
    result = save_project(
        db_path,
        project_id,
        p=package.parameters or None,
        series=series,
        phases=phases or None,
    )
    result["projectID"] = project_id
    result["name"] = title
    return result


def _resolve(db_path: Path | str, package: ProjectPackage) -> tuple[int, int | None]:
    """The model to build from and the vessel to record, as local ids."""
    with get_connection(db_path, readonly=True) as conn:
        organism_id = conn.execute(
            "SELECT organismID FROM organismTab WHERE name = ?", (package.organism,)
        ).fetchone()["organismID"]

        model = None
        if package.model:
            model = conn.execute(
                "SELECT modelID FROM modelTab WHERE organismID = ? AND name = ?",
                (organism_id, package.model),
            ).fetchone()
        if model is None:
            model = conn.execute(
                "SELECT modelID FROM modelTab WHERE organismID = ? ORDER BY modelID",
                (organism_id,),
            ).fetchone()
        if model is None:
            raise MissingPrerequisiteError("model for organism", package.organism)

        bioreactor = None
        if package.bioreactor:
            bioreactor = conn.execute(
                "SELECT bioreactorID FROM bioreactorTab WHERE name = ?",
                (package.bioreactor,),
            ).fetchone()
    return model["modelID"], bioreactor["bioreactorID"] if bioreactor else None


def _phases(db_path: Path | str, project_id: int, package: ProjectPackage) -> list[Phase]:
    """The exported phases as rows of this database."""
    phases = []
    for offset, entry in enumerate(package.phases, start=1):
        phases.append(
            Phase(
                processID=offset,
                projectID=project_id,
                statusID=entry.get("statusID"),
                typeID=entry.get("typeID"),
                name=entry.get("name"),
                reservoirID=entry.get("reservoirID"),
                start=_condition(entry.get("start")),
                end=_condition(entry.get("end")),
                parameters={str(k): v for k, v in (entry.get("parameters") or {}).items()},
            )
        )
    # processTab.processID is unique across the table, not per project.
    with get_connection(db_path, readonly=True) as conn:
        base = conn.execute("SELECT COALESCE(MAX(processID), 0) FROM processTab").fetchone()[0]
    for phase in phases:
        phase.processID += base
    return phases


def _condition(raw) -> Condition:
    raw = raw or {}
    return Condition(
        typeID=raw.get("typeID"),
        variableID=raw.get("variableID"),
        operatorID=raw.get("operatorID"),
        value=raw.get("value"),
        time=raw.get("time"),
    )


def _read_series(folder: Path, package: ProjectPackage) -> VariableSeries | None:
    """The time series, from whichever table the export wrote.

    Column headers carry their unit — "cXL [g/l]" — because the file is meant
    to be read; the unit is dropped again here.
    """
    if not package.variables_file:
        return None
    path = folder / package.variables_file
    if not path.is_file():
        return None

    separator = "\t" if path.suffix.lower() == ".txt" else ","
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        return None

    names = [_column_name(part) for part in lines[0].split(separator)]
    rows = [
        [float(cell) if cell not in ("", "nan") else float("nan") for cell in line.split(separator)]
        for line in lines[1:]
        if line.strip()
    ]
    if not rows:
        return None

    columns = np.asarray(rows, dtype=float)
    values = {name: columns[:, index] for index, name in enumerate(names)}
    time = values.get("t")
    if time is None:
        return None
    return VariableSeries(t=time, v=values, real_t=[""] * len(time))


def _column_name(header: str) -> str:
    return header.split("[")[0].strip()
