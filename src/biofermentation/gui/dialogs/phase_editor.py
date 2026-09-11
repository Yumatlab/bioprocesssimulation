"""Editing a phase (plan section 5.3).

A QDialog opened with exec() is the direct equivalent of MATLAB's
waitfor(dialog): the caller blocks, the phase is edited in place, and the
grid is rebuilt afterwards.

The dialog works on a copy and only writes back on accept, so Cancel really
cancels — the MATLAB editors write straight into app.Phases and a cancel
leaves whatever was typed.
"""

from copy import deepcopy

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...control import EndCondition, PhaseType, StartCondition
from ...db.models import Condition, Phase
from ..widgets.indicators import select_data
from ..widgets.tex import tex_to_html

#: The only two phase types that draw from a reservoir.
FEED_TYPES = (PhaseType.PULSE_FEED, PhaseType.EXPONENTIAL_FEED)


def plain_tex(text: str | None) -> str:
    """A TeX fragment as plain text, for places that cannot render markup."""
    return (text or "").replace("{", "").replace("}", "")


class ConditionEditor(QGroupBox):
    """Start or end of a phase: the type, and whatever that type needs."""

    def __init__(
        self,
        title: str,
        which: str,
        types: dict[int, str],
        variables: list[dict],
        operators: list[dict],
        parent: QWidget | None = None,
    ):
        super().__init__(title, parent)
        self.which = which
        layout = QFormLayout(self)

        self.type_box = QComboBox()
        for type_id, text in types.items():
            self.type_box.addItem(text, type_id)
        self.type_box.currentIndexChanged.connect(self._update_visibility)
        layout.addRow("Condition:", self.type_box)

        self.variable_box = QComboBox()
        for row in variables:
            # A combo box entry is plain text, so the TeX braces are dropped
            # rather than rendered. Name and unit are enough — repeating the
            # symbol next to the name only makes the list harder to scan.
            unit = plain_tex(row.get("tex_unit"))
            name = row["name"]
            self.variable_box.addItem(f"{name} [{unit}]" if unit else name, row["variableID"])
        self.variable_label = QLabel("Variable:")
        layout.addRow(self.variable_label, self.variable_box)

        self.operator_box = QComboBox()
        for row in operators:
            self.operator_box.addItem(row["condition"], row["process_operatorID"])
        self.operator_label = QLabel("Operator:")
        layout.addRow(self.operator_label, self.operator_box)

        self.value_box = QDoubleSpinBox()
        self.value_box.setDecimals(4)
        self.value_box.setRange(-1e9, 1e9)
        self.value_label = QLabel("Value:")
        layout.addRow(self.value_label, self.value_box)

    def load(self, condition) -> None:
        select_data(self.type_box, condition.typeID)
        select_data(self.variable_box, condition.variableID)
        select_data(self.operator_box, condition.operatorID)
        self.value_box.setValue(float(condition.value or 0.0))
        self._update_visibility()

    def apply_to(self, condition) -> None:
        condition.typeID = self.type_box.currentData()
        if self._needs_variable():
            condition.variableID = self.variable_box.currentData()
            condition.operatorID = self.operator_box.currentData()
        condition.value = self.value_box.value()

    def _needs_variable(self) -> bool:
        type_id = self.type_box.currentData()
        if self.which == "start":
            return type_id == StartCondition.VARIABLE
        return type_id == EndCondition.VARIABLE

    def _needs_value(self) -> bool:
        if self._needs_variable():
            return True
        return self.which == "end" and self.type_box.currentData() == EndCondition.TIMER

    def _update_visibility(self) -> None:
        """Grey out what the condition type does not use, never hide it.

        Hiding was the first attempt and it reads as a bug: four of the five
        phases of a real project start on "end of previous phase", so the
        editor came up with a single row and the variable picker nowhere to
        be seen. Greying is what the controller panels already do, and it
        shows that the setting exists and why it is not available.
        """
        needs_variable = self._needs_variable()
        for widget in (
            self.variable_label,
            self.variable_box,
            self.operator_label,
            self.operator_box,
        ):
            widget.setEnabled(needs_variable)
        needs_value = self._needs_value()
        self.value_label.setEnabled(needs_value)
        self.value_box.setEnabled(needs_value)
        # A timer takes a duration, a variable condition a threshold.
        if self.which == "end" and self.type_box.currentData() == EndCondition.TIMER:
            self.value_label.setText("Duration [h]:")
        else:
            self.value_label.setText("Value:")


class PhaseEditor(QDialog):
    """Name, type, reservoir and both conditions of one phase."""

    def __init__(
        self,
        phase: Phase,
        lookups,
        reservoirs: int = 1,
        parent: QWidget | None = None,
        p_meta=None,
        p=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {phase.name or 'Phase'}")
        self.setModal(True)
        self._phase = phase
        self._draft = deepcopy(phase)
        #: What the parameter dialog needs; without them its button stays off.
        self._p_meta = p_meta
        self._p = p

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(phase.name or "")
        form.addRow("Name:", self.name_edit)

        self.type_box = QComboBox()
        for row in lookups.process_type:
            self.type_box.addItem(row["type"], row["process_typeID"])
        form.addRow("Type:", self.type_box)

        self.reservoir_box = QComboBox()
        for number in range(1, max(1, reservoirs) + 1):
            self.reservoir_box.addItem(f"R{number}", number)
        self.reservoir_label = QLabel("Reservoir:")
        form.addRow(self.reservoir_label, self.reservoir_box)
        layout.addLayout(form)

        starts = {
            row["process_conditiontypeID"]: row["conditiontype"]
            for row in lookups.start_conditiontype
        }
        ends = {
            row["process_conditiontypeID"]: row["conditiontype"]
            for row in lookups.end_conditiontype
        }
        self.start_editor = ConditionEditor(
            "Start", "start", starts, lookups.process_variable, lookups.process_operator
        )
        self.end_editor = ConditionEditor(
            "End", "end", ends, lookups.process_variable, lookups.process_operator
        )
        layout.addWidget(self.start_editor)
        layout.addWidget(self.end_editor)

        self.parameters_button = QPushButton("Parameters…")
        self.parameters_button.setToolTip("The values this phase applies when it starts")
        self.parameters_button.clicked.connect(self._edit_parameters)
        form.addRow("", self.parameters_button)

        self.type_box.currentIndexChanged.connect(self._update_for_type)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()

    def _load(self) -> None:
        select_data(self.type_box, self._draft.typeID)
        select_data(self.reservoir_box, self._draft.reservoirID or 1)
        self.start_editor.load(self._draft.start)
        self.end_editor.load(self._draft.end)
        self._update_for_type()

    def _update_for_type(self) -> None:
        """What the phase type does and does not need.

        A reservoir only means something for the two feed types, and a stop
        phase has no end condition at all — the process is standing, so any
        condition on it could never be met.
        """
        phase_type = self.type_box.currentData()
        needs_reservoir = phase_type in FEED_TYPES
        self.reservoir_label.setVisible(needs_reservoir)
        self.reservoir_box.setVisible(needs_reservoir)

        is_stop = phase_type == PhaseType.STOP
        self.end_editor.setVisible(not is_stop)

        # Every phase type but Stop can carry a parameter set; an update phase
        # is the one whose whole purpose it is.
        self.parameters_button.setEnabled(not is_stop and self._p_meta is not None)
        count = len(self._draft.parameters)
        self.parameters_button.setText(f"Parameters… ({count})" if count else "Parameters…")

    def _edit_parameters(self) -> None:
        """The values this phase applies when it starts.

        Edited on the draft, like everything else here: cancelling the phase
        editor has to drop them too.
        """
        from .parameters import PhaseParameterDialog

        if self._p_meta is None or self._p is None:
            return
        dialog = PhaseParameterDialog(self._draft, self._p_meta, self._p, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_for_type()

    def accept(self) -> None:
        """Write the draft back. Only here, and only on Ok."""
        self._phase.parameters = dict(self._draft.parameters)
        self._phase.name = self.name_edit.text().strip() or self._phase.name
        self._phase.typeID = self.type_box.currentData()
        # Asking the widget would be wrong: a hidden parent makes every child
        # report invisible, so the type is the only reliable source here.
        self._phase.reservoirID = (
            self.reservoir_box.currentData() if self._phase.typeID in FEED_TYPES else None
        )
        self.start_editor.apply_to(self._phase.start)
        if self._phase.typeID == PhaseType.STOP:
            # No end condition on a phase that stops the process.
            self._phase.end = Condition()
        else:
            self.end_editor.apply_to(self._phase.end)
        super().accept()

    def summary(self) -> str:
        """What the phase now says, for the log."""
        return tex_to_html(
            f"{self._phase.name}: {PhaseType(self._phase.typeID).name.lower().replace('_', ' ')}"
        )
