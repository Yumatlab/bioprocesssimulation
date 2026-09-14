"""Importing and exporting organisms, bioreactors and whole projects.

Three windows' worth of file dialogs in one place, because they share one
question: which name, and what happens when the target installation does not
have it. Everything here is keyed by name — an id means nothing outside the
database it came from.
"""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from ...db import (
    export_bioreactor,
    import_bioreactor,
    import_package,
    list_bioreactors,
    load_bioreactor,
    read_package,
    write_bioreactor,
)
from ...db.definitions import export_definition, import_definition
from ...db.transfer import MissingPrerequisiteError
from ...organisms.definition import load_definition, write_definition

ORGANISM_FILTER = "Organism definition (*.yaml *.yml)"
BIOREACTOR_FILTER = "Bioreactor definition (*.yaml *.yml)"


def _organism_names(db_path) -> list[str]:
    from ...db.connection import get_connection

    with get_connection(db_path, readonly=True) as conn:
        return [row["name"] for row in conn.execute("SELECT name FROM organismTab ORDER BY name")]


# ---------------------------------------------------------- organisms --


def export_organism_file(parent, db_path: Path) -> Path | None:
    """Write one organism to a YAML file, models included."""
    names = _organism_names(db_path)
    if not names:
        QMessageBox.information(parent, "Export organism", "This database has no organisms.")
        return None
    name, chosen = QInputDialog.getItem(parent, "Export organism", "Organism:", names, 0, False)
    if not chosen:
        return None

    target, _ = QFileDialog.getSaveFileName(
        parent, "Export organism", str(Path.home() / f"{_slug(name)}.yaml"), ORGANISM_FILTER
    )
    if not target:
        return None
    try:
        path = write_definition(export_definition(db_path, name), target)
    except Exception as error:
        QMessageBox.warning(parent, "Export failed", str(error))
        return None
    QMessageBox.information(parent, "Export organism", f"{name} written to {path}")
    return path


def import_organism_file(parent, db_path: Path, path: Path | None = None) -> str | None:
    """Read a YAML organism into the database. Returns the name it got."""
    if path is None:
        selected, _ = QFileDialog.getOpenFileName(
            parent, "Import organism", str(Path.home()), ORGANISM_FILTER
        )
        if not selected:
            return None
        path = Path(selected)

    try:
        definition = load_definition(path)
    except Exception as error:
        QMessageBox.warning(parent, "Import failed", str(error))
        return None

    replace = False
    if definition.display_name in _organism_names(db_path):
        answer = QMessageBox.question(
            parent,
            "Import organism",
            f"{definition.display_name!r} already exists.\n\n"
            "Overwrite its defaults, models and variable assignment?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        replace = True

    try:
        counts = import_definition(db_path, definition, replace=replace)
    except Exception as error:
        QMessageBox.warning(parent, "Import failed", str(error))
        return None

    QMessageBox.information(
        parent,
        "Import organism",
        f"{definition.display_name}: {counts['parameters']} new parameters, "
        f"{counts['defaults']} defaults, {counts['models']} model(s) with "
        f"{counts['model_parameters']} parameters.",
    )
    return definition.display_name


# -------------------------------------------------------- bioreactors --


def export_bioreactor_file(parent, db_path: Path) -> Path | None:
    names = [row["name"] for row in list_bioreactors(db_path)]
    if not names:
        QMessageBox.information(parent, "Export bioreactor", "This database has no bioreactors.")
        return None
    name, chosen = QInputDialog.getItem(parent, "Export bioreactor", "Bioreactor:", names, 0, False)
    if not chosen:
        return None

    target, _ = QFileDialog.getSaveFileName(
        parent, "Export bioreactor", str(Path.home() / f"{_slug(name)}.yaml"), BIOREACTOR_FILTER
    )
    if not target:
        return None
    try:
        path = write_bioreactor(export_bioreactor(db_path, name), target)
    except Exception as error:
        QMessageBox.warning(parent, "Export failed", str(error))
        return None
    QMessageBox.information(parent, "Export bioreactor", f"{name} written to {path}")
    return path


def import_bioreactor_file(parent, db_path: Path, path: Path | None = None) -> str | None:
    if path is None:
        selected, _ = QFileDialog.getOpenFileName(
            parent, "Import bioreactor", str(Path.home()), BIOREACTOR_FILTER
        )
        if not selected:
            return None
        path = Path(selected)

    try:
        definition = load_bioreactor(path)
    except Exception as error:
        QMessageBox.warning(parent, "Import failed", str(error))
        return None

    replace = False
    if definition.name in [row["name"] for row in list_bioreactors(db_path)]:
        answer = QMessageBox.question(
            parent,
            "Import bioreactor",
            f"{definition.name!r} already exists.\n\nOverwrite its values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        replace = True

    try:
        counts = import_bioreactor(db_path, definition, replace=replace)
    except Exception as error:
        QMessageBox.warning(parent, "Import failed", str(error))
        return None

    message = f"{definition.name}: {counts['parameters']} parameters."
    if counts.get("unknown"):
        message += "\n\nNot known to this installation and therefore skipped:\n" + ", ".join(
            counts["unknown"]
        )
    QMessageBox.information(parent, "Import bioreactor", message)
    return definition.name


# ----------------------------------------------------------- projects --


def import_project_folder(parent, db_path: Path) -> int | None:
    """Read an export back in, asking for what the database is missing.

    The organism and the bioreactor cannot be reconstructed from an export —
    a project's parameter set is the union of what those two define. When one
    is absent the import offers to read its package first and then carries on,
    which is the whole point of keeping them as separate files.
    """
    folder = QFileDialog.getExistingDirectory(
        parent, "Import project — pick the exported folder", str(Path.home())
    )
    if not folder:
        return None
    folder = Path(folder)

    try:
        package = read_package(folder)
    except Exception as error:
        QMessageBox.warning(parent, "Import failed", str(error))
        return None

    # Up to two rounds: the organism, then the bioreactor.
    for _ in range(3):
        try:
            result = import_package(db_path, folder)
        except MissingPrerequisiteError as missing:
            if not _offer_prerequisite(parent, db_path, missing):
                return None
            continue
        except Exception as error:
            QMessageBox.warning(parent, "Import failed", str(error))
            return None

        QMessageBox.information(
            parent,
            "Import project",
            f"{result['name']} imported: {result['parameters']} parameters, "
            f"{result['times']} time points, {result['phases']} phases.",
        )
        return result["projectID"]

    QMessageBox.warning(parent, "Import failed", f"{package.name} still cannot be imported.")
    return None


def _offer_prerequisite(parent, db_path: Path, missing: MissingPrerequisiteError) -> bool:
    """Ask for the organism or bioreactor package the export needs."""
    answer = QMessageBox.question(
        parent,
        "Import project",
        f"{missing}\n\nPick the {missing.kind} definition now?",
        QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
    )
    if answer != QMessageBox.StandardButton.Open:
        return False
    if missing.kind == "organism":
        return import_organism_file(parent, db_path) is not None
    return import_bioreactor_file(parent, db_path) is not None


def _slug(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in text).strip("_")
    return cleaned or "definition"
