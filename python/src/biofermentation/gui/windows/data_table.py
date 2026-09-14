"""The Data Table window (point 18 of the review).

A translation of DataTable.mlapp: pick variables on the left, see every time
point of them on the right, export what is on screen. The original refreshes
it from the control app's timer; here the window listens to the runner, so it
stays correct even when it is opened while the simulation is already running.

Only what is selected is materialised. A finished E. coli run is a few
thousand rows across forty-three variables, and building all of that on every
block would make the table the slowest thing in the application.
"""

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..dialogs.export import write_table

#: What DataTable.mlapp ticks on opening.
DEFAULT_VARIABLES = ("t", "cXL", "cS1L", "pO2", "NSt", "thetaL", "pHL", "VL")


class DataTableWindow(QMainWindow):
    """Every stored value of the selected variables, and an export of it."""

    closed = Signal()

    def __init__(self, setup, runner, parent: QWidget | None = None):
        super().__init__(parent)
        self.setup = setup
        self.runner = runner
        self.auto_update = True

        self.setWindowTitle(f"Data Table - {setup.info.name}")
        self.resize(1000, 640)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.addWidget(self._build_selection(), 0)
        layout.addWidget(self._build_table(), 1)

        if runner is not None:
            runner.block_completed.connect(self._on_block)
        self.refresh()

    # ------------------------------------------------------------ build --

    def _build_selection(self) -> QWidget:
        box = QGroupBox("Variable Selection")
        box.setFixedWidth(230)
        layout = QVBoxLayout(box)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.items: dict[str, QTreeWidgetItem] = {}
        for row in self.setup.lookups.variable:
            name = row["name"]
            item = QTreeWidgetItem(self.tree, [f"{name} [{row.get('unit') or '-'}]"])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Checked if name in DEFAULT_VARIABLES else Qt.CheckState.Unchecked,
            )
            self.items[name] = item
        self.tree.itemChanged.connect(lambda *_: self.refresh())
        layout.addWidget(self.tree, 1)

        digits = QHBoxLayout()
        digits.addWidget(QLabel("Significant figures:"))
        self.digits_box = QSpinBox()
        self.digits_box.setRange(1, 15)
        self.digits_box.setValue(6)
        self.digits_box.valueChanged.connect(lambda _: self.refresh())
        digits.addWidget(self.digits_box)
        layout.addLayout(digits)

        self.auto_checkbox = QCheckBox("Auto update")
        self.auto_checkbox.setChecked(True)
        self.auto_checkbox.toggled.connect(self._auto_changed)
        layout.addWidget(self.auto_checkbox)

        self.entries_label = QLabel("0 entries")
        layout.addWidget(self.entries_label)

        for text, slot in (
            ("Refresh", self.refresh),
            ("Export table…", self.export),
            ("Close", self.close),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            layout.addWidget(button)
        return box

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        return self.table

    # ------------------------------------------------------------ state --

    def selected(self) -> list[str]:
        return [
            name for name, item in self.items.items() if item.checkState(0) == Qt.CheckState.Checked
        ]

    def columns(self) -> tuple[list[str], list[np.ndarray]]:
        """Time first, then the ticked variables — the shape of the export."""
        state = self.runner.state
        stop = state.idx + 1
        names, data = ["t"], [np.asarray(state.v.t[:stop], dtype=float)]
        for name in self.selected():
            if name == "t":
                continue
            series = state.v.get(name)
            if series is None:
                continue
            names.append(name)
            data.append(np.asarray(series[:stop], dtype=float))
        return names, data

    def refresh(self) -> None:
        names, data = self.columns()
        rows = len(data[0]) if data else 0
        digits = self.digits_box.value()

        self.table.setColumnCount(len(names))
        self.table.setHorizontalHeaderLabels([f"{name} [{self._unit(name)}]" for name in names])
        self.table.setRowCount(rows)
        for column, series in enumerate(data):
            for row in range(rows):
                item = QTableWidgetItem(f"{series[row]:.{digits}g}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
                self.table.setItem(row, column, item)
        self.entries_label.setText(f"{rows} entries")

    def _unit(self, name: str) -> str:
        if name == "t":
            return "h"
        for row in self.setup.lookups.variable:
            if row["name"] == name:
                return row.get("unit") or ""
        return ""

    # ---------------------------------------------------------- actions --

    def _on_block(self, *_) -> None:
        if self.auto_update:
            self.refresh()

    def _auto_changed(self, checked: bool) -> None:
        self.auto_update = checked
        if checked:
            self.refresh()

    def export(self) -> None:
        """Exactly the view on screen, as the original's Export table does."""
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Export table",
            str(Path.home() / f"{self.setup.info.name or 'project'}_table.csv"),
            "CSV (*.csv);;Text (*.txt);;Excel (*.xlsx)",
        )
        if not target:
            return
        names, data = self.columns()
        try:
            written = write_table(Path(target), names, data, digits=self.digits_box.value())
        except Exception as error:
            QMessageBox.warning(self, "Export failed", str(error))
            return
        QMessageBox.information(self, "Export", f"Written to {written}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closed.emit()
        super().closeEvent(event)
