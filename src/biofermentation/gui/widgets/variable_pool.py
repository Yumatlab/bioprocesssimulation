"""The Variable Pool tab (point 6 of the review).

Three things, as the original's VariablePoolTab has them:

  * **Pump Rates** — the six flows the actuators produce, read-only.
  * **Liquid Volume** — the working volume and what has been added to it.
  * **Trend** — a checkable list of every displayable variable and a table
    with the current value, the unit and an arrow for the direction it is
    moving in.

MATLAB fits a cubic spline through the last ten samples and looks at the sign
of its derivative at the end. A spline through ten points only to read off a
sign is more machinery than the answer needs, so the trend here is a least
squares slope over the same ten samples — same window, same question, and it
does not overshoot on noisy data the way a spline can.
"""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .tex import tex_label, tex_to_html

#: How many samples the trend looks back over, as in the original.
TREND_WINDOW = 10
#: How many variables start out ticked.
DEFAULT_CHECKED = 10

RISING, FALLING, FLAT = "⬈", "⬊", "➞"

#: Pump rates panel: variable, label. Reservoirs beyond the project's are
#: dropped when the panel is built.
# FT1 is the acid pump and FT2 the base pump (variableTab.description). The
# original swaps them in this panel — the field captioned F_T1 reads v.FT2 —
# so what is shown here differs from MATLAB on purpose.
PUMP_RATES = [
    ("FT1", "F_{T1} (acid) [lh^{-1}]"),
    ("FT2", "F_{T2} (base) [lh^{-1}]"),
    ("FH", "F_{H} [lh^{-1}]"),
    ("FR1", "F_{R1} [lh^{-1}]"),
    ("FR2", "F_{R2} [lh^{-1}]"),
    ("FR3", "F_{R3} [lh^{-1}]"),
]

LIQUID_VOLUME = [
    ("VL", "V_{L} [l]"),
    ("Vacid", "added acid [l]"),
    ("Vbase", "added base [l]"),
    ("AAF", "added AF [l]"),
    ("VR1in", "added feed R1 [l]"),
    ("VR2in", "added feed R2 [l]"),
    ("VR3in", "added feed R3 [l]"),
]

#: Which entries only make sense with that many reservoirs.
_RESERVOIR_OF = {
    "FR1": 1,
    "FR2": 2,
    "FR3": 3,
    "VR1in": 1,
    "VR2in": 2,
    "VR3in": 3,
}


def trend_arrow(time: np.ndarray, data: np.ndarray) -> str:
    """Up, down or flat over the last TREND_WINDOW samples."""
    n = min(TREND_WINDOW, time.size, data.size)
    if n < 2:
        return FLAT
    x, y = time[-n:], data[-n:]
    finite = np.isfinite(x) & np.isfinite(y)
    if finite.sum() < 2:
        return FLAT
    x, y = x[finite], y[finite]
    span = x[-1] - x[0]
    if span <= 0:
        return FLAT
    slope = float(np.polyfit(x, y, 1)[0])
    # Relative to the size of the signal, so a large variable creeping along
    # does not read as a trend and a small one moving does.
    scale = max(abs(float(np.nanmean(y))), 1e-9)
    if slope / scale > 1e-6:
        return RISING
    if slope / scale < -1e-6:
        return FALLING
    return FLAT


class VariablePool(QWidget):
    """Pump rates, liquid volume and the trend table of the running process."""

    def __init__(self, variables: list[dict], reservoirs: int = 1, parent=None):
        super().__init__(parent)
        self.variables = {row["name"]: row for row in variables}
        self.reservoirs = max(1, int(reservoirs or 1))

        layout = QHBoxLayout(self)
        layout.addWidget(self._build_readouts(), 0)
        layout.addWidget(self._build_tree(), 0)
        layout.addWidget(self._build_table(), 1)
        # Connected last: ticking a box clears the table, which does not
        # exist yet while the tree is being filled.
        self.tree.itemChanged.connect(self._selection_changed)

    # ------------------------------------------------------------ build --

    def _build_readouts(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(250)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)

        self.readouts: dict[str, QLineEdit] = {}
        for title, entries in (
            ("Pump Rates", PUMP_RATES),
            ("Liquid Volume", LIQUID_VOLUME),
        ):
            box = QGroupBox(title)
            form = QFormLayout(box)
            for name, label in entries:
                if _RESERVOIR_OF.get(name, 0) > self.reservoirs:
                    continue
                field = QLineEdit("—")
                field.setReadOnly(True)
                field.setAlignment(Qt.AlignmentFlag.AlignRight)
                field.setMaximumWidth(110)
                self.readouts[name] = field
                caption = QLabel(tex_to_html(label) + ":")
                caption.setTextFormat(Qt.TextFormat.RichText)
                form.addRow(caption, field)
            layout.addWidget(box)
        layout.addStretch()
        return column

    def _build_tree(self) -> QWidget:
        box = QGroupBox("Displayable Variables")
        box.setFixedWidth(230)
        grid = QGridLayout(box)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        grid.addWidget(self.tree, 0, 0)

        self.items: dict[str, QTreeWidgetItem] = {}
        for position, (name, row) in enumerate(self.variables.items()):
            item = QTreeWidgetItem(self.tree, [f"{name} [{row.get('unit') or '-'}]"])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = Qt.CheckState.Checked if position < DEFAULT_CHECKED else Qt.CheckState.Unchecked
            item.setCheckState(0, state)
            self.items[name] = item
        return box

    def _build_table(self) -> QWidget:
        box = QGroupBox("Trend")
        layout = QVBoxLayout(box)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Variable Name", "Current Value", "Unit", "Trend"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)
        return box

    # ------------------------------------------------------------ state --

    def checked(self) -> list[str]:
        return [
            name for name, item in self.items.items() if item.checkState(0) == Qt.CheckState.Checked
        ]

    def refresh(self, state) -> None:
        """Read the step just computed. Nothing is calculated here but the trend."""
        v, index = state.v, state.idx
        rho = float(state.p.get("rhoL", 1.0) or 1.0)

        for name, field in self.readouts.items():
            series = v.get(name)
            if series is None or index >= series.size:
                field.setText("—")
                continue
            field.setText(f"{float(series[index]):.4g}")

        names = self.checked()
        time = v.get("t")
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            series = v.get(name)
            meta = self.variables.get(name, {})
            if series is None or index >= series.size:
                cells = (name, "—", meta.get("unit") or "", FLAT)
            else:
                data = np.asarray(series[: index + 1], dtype=float)
                unit = meta.get("unit") or ""
                if name == "VL":
                    # The original shows the liquid as a mass, as the scale does.
                    data = data * rho
                    unit = "kg"
                arrow = (
                    trend_arrow(np.asarray(time[: index + 1], dtype=float), data)
                    if time is not None
                    else FLAT
                )
                cells = (name, f"{float(data[-1]):.6g}", unit, arrow)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

    def label_for(self, name: str) -> str:
        row = self.variables.get(name, {})
        return tex_label(row.get("shorttex") or name, row.get("tex_unit"))

    def _selection_changed(self, *_) -> None:
        self.table.setRowCount(0)
