"""The phase panels of the Process Manager (plan section 5.2).

Translated from createPhasePanel, updatePhasePanels, createArrowButton and
arrowButtonPushed.

rebuild_grid() carries over the one rule that made the MATLAB version work:
the whole grid is rebuilt rather than individual columns kept in step. Panel i
goes in column 2i, the arrow after it in column 2i+1, and the add button last.
Trying to patch a grid in place was where the original kept going wrong.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...control import EndCondition, PhaseStatus, StartCondition
from ...db.models import Phase
from ..values import format_number
from .indicators import StatusLamp
from .tex import tex_to_html

PANEL_WIDTH = 210
ARROW_WIDTH = 75


def condition_text(
    condition,
    which: str,
    variables: dict[int, dict],
    operators: dict[int, str],
    status_id: int | None = None,
) -> str:
    """The one-line summary a panel shows for a start or end condition."""
    type_id = condition.typeID
    if which == "start":
        if type_id == StartCondition.VARIABLE:
            return _variable_text(condition, variables, operators)
        if type_id == StartCondition.PREVIOUS_ENDED:
            return "End of previous phase"
        if type_id == StartCondition.BATCH_END:
            return "Batch end (pO2 slope)"
        return "-"

    if type_id == EndCondition.NEXT_PHASE_STARTS:
        return "Next phase condition"
    if type_id == EndCondition.VARIABLE:
        return _variable_text(condition, variables, operators)
    if type_id == EndCondition.TIMER:
        value = condition.value or 0.0
        if status_id in (PhaseStatus.ACTIVE, PhaseStatus.COMPLETED) and condition.time is not None:
            # The timer is a number somebody typed and keeps every place it
            # has; the time the phase actually ended is a measurement, and
            # its tail is the arithmetic of the accumulation, not a decimal
            # anyone set — 8.502222222223 h is 8.502 h with noise after it.
            return f"t = {format_number(condition.time, cap=3)} h ({format_number(value)} h timer)"
        return f"Timer ({format_number(value)} h)"
    return "-"


def _variable_text(condition, variables: dict[int, dict], operators: dict[int, str]) -> str:
    variable = variables.get(condition.variableID)
    symbol = operators.get(condition.operatorID)
    if variable is None or symbol is None:
        return "-"
    unit = variable.get("tex_unit") or ""
    name = variable.get("shorttex") or variable.get("name") or "?"
    return f"{name} {symbol} {format_number(condition.value)} {unit}".strip()


class PhasePanel(QGroupBox):
    """One phase: name, type, both conditions, a status lamp and two buttons."""

    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, index: int, parent: QWidget | None = None):
        super().__init__(f"Phase {index + 1}", parent)
        self.index = index
        self.setObjectName("phasePanel")
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(PANEL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.name_label = QLabel("Empty Phase")
        font = self.name_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 3)
        self.name_label.setFont(font)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label)

        self.type_label = QLabel("Blank")
        self.type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.type_label)
        layout.addStretch()

        conditions = QGridLayout()
        conditions.setHorizontalSpacing(6)
        conditions.addWidget(QLabel("Start:"), 0, 0)
        conditions.addWidget(QLabel("End:"), 1, 0)
        self.start_label = QLabel("-")
        self.end_label = QLabel("-")
        for label in (self.start_label, self.end_label):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
        conditions.addWidget(self.start_label, 0, 1)
        conditions.addWidget(self.end_label, 1, 1)
        conditions.setColumnStretch(1, 1)
        layout.addLayout(conditions)
        layout.addStretch()

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self.index))
        layout.addWidget(self.edit_button)

        lamp_row = QHBoxLayout()
        lamp_row.addStretch()
        self.lamp = StatusLamp()
        lamp_row.addWidget(self.lamp)
        lamp_row.addStretch()
        layout.addLayout(lamp_row)

        delete_row = QHBoxLayout()
        delete_row.addStretch()
        self.delete_button = QPushButton("x")
        self.delete_button.setFixedWidth(28)
        self.delete_button.setToolTip("Delete this phase")
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.index))
        delete_row.addWidget(self.delete_button)
        delete_row.addStretch()
        layout.addLayout(delete_row)

    def update_from(
        self,
        phase: Phase,
        types: dict[int, str],
        statuses: dict[int, str],
        variables: dict[int, dict],
        operators: dict[int, str],
    ) -> None:
        self.name_label.setText(phase.name or "Empty Phase")
        self.type_label.setText(types.get(phase.typeID, "-"))
        self.start_label.setText(
            tex_to_html(condition_text(phase.start, "start", variables, operators))
        )
        self.end_label.setText(
            tex_to_html(condition_text(phase.end, "end", variables, operators, phase.statusID))
        )
        self.lamp.set_status(phase.statusID or 1)
        self.lamp.setToolTip(statuses.get(phase.statusID, ""))

        # A phase that has run, or is running, is part of the record. Editing
        # or deleting it would leave a process history that never happened —
        # the automaton has already read its conditions and applied its
        # parameters, so a change now would be rewriting what was done.
        self._finished = phase.statusID in (PhaseStatus.ACTIVE, PhaseStatus.COMPLETED)
        self.apply_editable()

        if phase.statusID == PhaseStatus.PENDING and phase.start.time is not None:
            self.setToolTip(f"Start: t = {format_number(phase.start.time, cap=3)} h")
        elif phase.statusID == PhaseStatus.ACTIVE and phase.end.time is not None:
            self.setToolTip(f"End: t = {format_number(phase.end.time, cap=3)} h")
        else:
            self.setToolTip("")

    def set_editable(self, editable: bool) -> None:
        """Whether the process is standing still and may be re-planned."""
        self._editable = editable
        self.apply_editable()

    def apply_editable(self) -> None:
        """Two reasons a button may be dead, and they say different things."""
        editable = getattr(self, "_editable", True)
        finished = getattr(self, "_finished", False)

        self.edit_button.setEnabled(editable and not finished)
        if not editable:
            self.edit_button.setToolTip("Pause the process to edit a phase")
        elif finished:
            self.edit_button.setToolTip("A running or completed phase cannot be edited")
        else:
            self.edit_button.setToolTip("Edit this phase")

        self.delete_button.setEnabled(editable and not finished)
        if not editable:
            self.delete_button.setToolTip("Pause the process to delete a phase")
        elif finished:
            self.delete_button.setToolTip("A running or completed phase cannot be deleted")
        else:
            self.delete_button.setToolTip("Delete this phase")


class ArrowButton(QPushButton):
    """Forces the next phase to start. Disabled until the one before is active.

    arrowList[i] is the arrow between phase i and phase i+1, so there is
    always one fewer arrow than panels — the off-by-one the MATLAB loops kept
    tripping over.
    """

    def __init__(self, index: int, parent: QWidget | None = None):
        super().__init__("→", parent)
        self.index = index  # the phase this arrow starts
        self.setFixedWidth(ARROW_WIDTH)
        self.setEnabled(False)


class PhaseGrid(QWidget):
    """The row of panels with arrows between them, rebuilt as a whole."""

    edit_requested = Signal(int)
    delete_requested = Signal(int)
    add_requested = Signal()
    force_start_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self.panels: list[PhasePanel] = []
        self.arrows: list[ArrowButton] = []
        self._editable = True
        self.add_button = QPushButton("+")
        self.add_button.setFixedWidth(100)
        self.add_button.setToolTip("Add a phase")
        self.add_button.clicked.connect(self.add_requested.emit)

    def rebuild(
        self,
        phases: list[Phase],
        types: dict[int, str],
        statuses: dict[int, str],
        variables: dict[int, dict],
        operators: dict[int, str],
    ) -> None:
        """Throw the grid away and build it again. rebuildGridColumns."""
        self._clear()

        for index, phase in enumerate(phases):
            panel = PhasePanel(index)
            panel.edit_requested.connect(self.edit_requested.emit)
            panel.delete_requested.connect(self.delete_requested.emit)
            panel.update_from(phase, types, statuses, variables, operators)
            panel.set_editable(self._editable)
            self._layout.addWidget(panel)
            self.panels.append(panel)

            if index < len(phases) - 1:
                arrow = ArrowButton(index + 1)
                arrow.clicked.connect(
                    lambda _=False, i=index + 1: self.force_start_requested.emit(i)
                )
                # Only the arrow after the active phase may be pressed.
                if phase.statusID == PhaseStatus.ACTIVE:
                    arrow.setEnabled(True)
                    arrow.setToolTip("Force start next phase")
                self._layout.addWidget(arrow)
                self.arrows.append(arrow)

        self._layout.addWidget(self.add_button)
        self._layout.addStretch()
        self.set_editable(self._editable)

    def set_editable(self, editable: bool) -> None:
        """Phases are planned on a standing process (point 10 of the review).

        Adding, editing or deleting a phase while the automaton is stepping
        would take effect halfway through a block. The guard flag protects a
        single write, not a change of plan.
        """
        self._editable = bool(editable)
        self.add_button.setEnabled(self._editable)
        self.add_button.setToolTip(
            "Add a phase" if self._editable else "Pause the process to add a phase"
        )
        for panel in self.panels:
            panel.set_editable(self._editable)

    def _clear(self) -> None:
        for panel in self.panels:
            panel.setParent(None)
        for arrow in self.arrows:
            arrow.setParent(None)
        self.panels.clear()
        self.arrows.clear()
        self._layout.removeWidget(self.add_button)
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.add_button:
                widget.setParent(None)
