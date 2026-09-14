"""Export (point 18 of the review).

ExportProject.mlapp writes a folder per project: one file with the variable
time series, one with the parameters, one with the phases and a text file
with the project information. Same here, and the same three formats — .csv,
.txt and .xlsx.

xlsx needs a library MATLAB has built in and Python does not. Rather than
add openpyxl as a hard dependency for one optional format, the writer falls
back to .csv and says so; when openpyxl happens to be installed it is used.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from ...control import EndCondition, StartCondition
from ...db.transfer import write_manifest

FORMATS = (".xlsx", ".csv", ".txt")
#: The column separator each format uses.
SEPARATORS = {".csv": ",", ".txt": "\t"}


def write_table(
    target: Path, names: list[str], columns: list[np.ndarray], *, digits: int = 6
) -> Path:
    """Write one table. Returns the file actually written.

    The suffix decides the format. An .xlsx target falls back to .csv when
    openpyxl is missing — silently losing the export would be worse than
    handing back a file the user did not ask for by name.
    """
    target = Path(target)
    if target.suffix.lower() == ".xlsx":
        try:
            return _write_xlsx(target, names, columns)
        except ImportError:
            target = target.with_suffix(".csv")

    separator = SEPARATORS.get(target.suffix.lower(), ",")
    rows = len(columns[0]) if columns else 0
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(separator.join(names) + "\n")
        for row in range(rows):
            handle.write(separator.join(f"{column[row]:.{digits}g}" for column in columns) + "\n")
    return target


def _write_xlsx(target: Path, names: list[str], columns: list[np.ndarray]) -> Path:
    from openpyxl import Workbook  # optional; ImportError is handled above

    book = Workbook()
    sheet = book.active
    sheet.append(names)
    for row in range(len(columns[0]) if columns else 0):
        sheet.append([float(column[row]) for column in columns])
    book.save(target)
    return target


def write_text_table(target: Path, header: list[str], rows: list[list[str]]) -> Path:
    """A table of strings — parameters, phases — in the same three formats."""
    target = Path(target)
    if target.suffix.lower() == ".xlsx":
        try:
            from openpyxl import Workbook

            book = Workbook()
            sheet = book.active
            sheet.append(header)
            for row in rows:
                sheet.append(row)
            book.save(target)
            return target
        except ImportError:
            target = target.with_suffix(".csv")

    separator = SEPARATORS.get(target.suffix.lower(), ",")
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(separator.join(header) + "\n")
        for row in rows:
            handle.write(separator.join(str(cell).replace(separator, " ") for cell in row) + "\n")
    return target


class ExportDialog(QDialog):
    """Which parts of the project to write, in which format, and where."""

    def __init__(self, setup, state, log_lines: list[str], parent=None):
        super().__init__(parent)
        self.setup = setup
        self.state = state
        self.log_lines = log_lines
        self.written: list[Path] = []
        self.target: Path | None = None

        self.setWindowTitle("Export project")
        self.resize(460, 380)
        layout = QVBoxLayout(self)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(Path.home()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(QLabel("Folder:"))
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        name_row = QHBoxLayout()
        self.name_edit = QLineEdit(_slug(setup.info.name or "project"))
        name_row.addWidget(QLabel("Name:"))
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        contents = QGroupBox("Contents")
        contents_layout = QVBoxLayout(contents)
        self.checkboxes = {}
        for key, text in (
            ("variables", "Variable data"),
            ("parameters", "Parameters"),
            ("phases", "Phases"),
            ("log", "Log"),
            ("information", "Project information"),
        ):
            box = QCheckBox(text)
            box.setChecked(True)
            self.checkboxes[key] = box
            contents_layout.addWidget(box)
        layout.addWidget(contents)

        formats = QGroupBox("Variable data file type")
        formats_layout = QHBoxLayout(formats)
        self.format_group = QButtonGroup(self)
        for suffix in FORMATS:
            button = QRadioButton(f"*{suffix}")
            button.setChecked(suffix == ".csv")
            self.format_group.addButton(button)
            button.setProperty("suffix", suffix)
            formats_layout.addWidget(button)
        layout.addWidget(formats)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #6a6a6a;")
        layout.addWidget(self.status)
        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------------------------------------------------------- helpers --

    def suffix(self) -> str:
        button = self.format_group.checkedButton()
        return button.property("suffix") if button else ".csv"

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def accept(self) -> None:
        try:
            self.written = self._export()
        except OSError as error:
            self.status.setText(f"Export failed: {error}")
            return
        super().accept()

    def _export(self) -> list[Path]:
        base = Path(self.folder_edit.text()) / _slug(self.name_edit.text() or "project")
        base.mkdir(parents=True, exist_ok=True)
        self.target = base
        suffix = self.suffix()
        written: list[Path] = []

        if self.checkboxes["variables"].isChecked():
            stop = self.state.idx + 1
            names = [
                "t",
                *sorted(
                    name
                    for name, series in self.state.v.items()
                    if name != "t" and hasattr(series, "size")
                ),
            ]
            columns = [np.asarray(self.state.v[name][:stop], dtype=float) for name in names]
            units = dict(self.setup.lookups.variable_units)
            units.setdefault("t", "h")
            headers = [f"{name} [{units.get(name) or '-'}]" for name in names]
            written.append(write_table(base / f"variables{suffix}", headers, columns))

        if self.checkboxes["parameters"].isChecked():
            rows = [
                [
                    meta["parametername"],
                    f"{self.state.p.get(meta['parametername'], float('nan')):.10g}",
                    meta.get("unit") or "",
                    meta.get("categorysection") or "",
                    meta.get("categoryname") or "",
                    meta.get("description") or "",
                ]
                for meta in self.setup.p_meta
            ]
            written.append(
                write_text_table(
                    base / f"parameters{suffix}",
                    ["name", "value", "unit", "section", "category", "description"],
                    rows,
                )
            )

        if self.checkboxes["phases"].isChecked():
            names = _Names(self.setup.lookups)
            rows = [
                [
                    str(phase.processID),
                    phase.name or "",
                    names.phase_type(phase.typeID),
                    names.status(phase.statusID),
                    f"R{phase.reservoirID}" if phase.reservoirID else "",
                    names.condition(phase.start, "start"),
                    _time(phase.start.time),
                    names.condition(phase.end, "end"),
                    _time(phase.end.time),
                ]
                for phase in self.setup.phases
            ]
            written.append(
                write_text_table(
                    base / f"phases{suffix}",
                    [
                        "processID",
                        "name",
                        "type",
                        "status",
                        "reservoir",
                        "start condition",
                        "start time [h]",
                        "end condition",
                        "end time [h]",
                    ],
                    rows,
                )
            )

        if self.checkboxes["log"].isChecked():
            path = base / "log.txt"
            path.write_text("\n".join(self.log_lines) + "\n", encoding="utf-8")
            written.append(path)

        if self.checkboxes["information"].isChecked():
            written.append(self._write_information(base))

        # The machine-readable copy, so the export can be imported again.
        # Written unconditionally: without it the folder is a record, not a
        # package, and there is no way to tell afterwards which it was.
        written.append(
            write_manifest(base, self.setup, self.state, files=self._files(written, base))
        )
        return written

    def _files(self, written: list[Path], base: Path) -> dict[str, str]:
        """Which table went into which file, for the importer to find."""
        return {
            key: path.name
            for key, path in (
                ("variables", next((p for p in written if p.stem == "variables"), None)),
                ("parameters", next((p for p in written if p.stem == "parameters"), None)),
                ("phases", next((p for p in written if p.stem == "phases"), None)),
                ("log", next((p for p in written if p.name == "log.txt"), None)),
            )
            if path is not None
        }

    def _write_information(self, base: Path) -> Path:
        info = self.setup.info
        lines = [
            "Project Information",
            "=" * 40,
            f"Exported:      {datetime.now():%d.%m.%Y %H:%M:%S}",
            f"Name:          {info.name}",
            f"Description:   {info.description or '-'}",
            f"Author:        {info.author or '-'}",
            f"Created on:    {info.created_on or '-'}",
            f"Last used:     {info.recent_use or '-'}",
            f"Organism:      {info.organism_name or '-'}",
            f"Bioreactor:    {info.bioreactor_name or '-'}",
            f"Reservoirs:    {info.reservoirs or 0}",
            f"Time points:   {self.state.idx + 1}",
            f"Process time:  {float(self.state.v.t[self.state.idx]):.3f} h",
            f"Phases:        {len(self.setup.phases)}",
        ]
        path = base / "Project_Information.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


class _Names:
    """The lookup tables, keyed for reading.

    An export used to carry "typeID 5" and "6 var 1 op 1 = 5" — the numbers
    the database joins on, which say nothing to whoever opens the file. Every
    one of them has a description one join away.
    """

    def __init__(self, lookups):
        self.types = {row["process_typeID"]: row["type"] for row in lookups.process_type}
        self.statuses = {row["process_statusID"]: row["status"] for row in lookups.process_status}
        self.operators = {
            row["process_operatorID"]: row["operator"] for row in lookups.process_operator
        }
        self.conditions = {
            row["process_conditiontypeID"]: row["conditiontype"]
            for row in (*lookups.start_conditiontype, *lookups.end_conditiontype)
        }
        self.variables = {row["variableID"]: row for row in lookups.process_variable}
        self.units = {row["variableID"]: row for row in lookups.variable}

    def phase_type(self, type_id) -> str:
        return self.types.get(type_id, "" if type_id is None else f"type {type_id}")

    def status(self, status_id) -> str:
        return self.statuses.get(status_id, "" if status_id is None else f"status {status_id}")

    def variable(self, variable_id) -> str:
        row = self.variables.get(variable_id) or self.units.get(variable_id)
        if row is None:
            return "" if variable_id is None else f"variable {variable_id}"
        unit = (self.units.get(variable_id) or {}).get("unit") or ""
        return f"{row['name']} [{unit}]" if unit else str(row["name"])

    def condition(self, condition, kind: str) -> str:
        """One condition as a sentence: what it waits for, and for what value.

        Only what the type actually uses. A phase that starts when the one
        before it ended still carries a variableID and an operator in
        processTab — left over from an earlier edit, read by nothing — and
        printing them would invent a condition that is not there.
        """
        if condition.typeID is None:
            return "none" if kind == "end" else ""
        text = self.conditions.get(condition.typeID, f"condition {condition.typeID}")

        if condition.typeID in (StartCondition.VARIABLE, EndCondition.VARIABLE):
            return " ".join(
                (
                    text + ":",
                    self.variable(condition.variableID),
                    self.operators.get(condition.operatorID, "?"),
                    f"{condition.value:g}" if condition.value is not None else "?",
                )
            )
        if condition.typeID == EndCondition.TIMER:
            return f"{text}: {condition.value:g} h" if condition.value is not None else text
        return text


def _time(value) -> str:
    return "" if value is None else f"{value:.4f}"


def _slug(text: str) -> str:
    keep = "-_ "
    cleaned = "".join(c for c in text if c.isalnum() or c in keep).strip()
    return cleaned.replace(" ", "_") or "project"


__all__ = ["ExportDialog", "write_table", "write_text_table"]
