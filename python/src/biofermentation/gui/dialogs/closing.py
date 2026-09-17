"""The closing dialog, after ClosingScreen.mlapp.

Leaving a project is a decision, not a side effect of clicking the window's
close box. The original asks four questions in one window — keep the name,
author and description; save; delete; save and export — and this is that
window, with two changes:

  * **Discard** is offered next to Delete. The original only had "delete the
    whole project", and an operator who wanted to drop the last twenty
    minutes had no way to say so.
  * The three text fields are written **with the save**, not the moment they
    are typed. In MATLAB each one fires its own UPDATE, so a name edited on
    the way to "Delete Project" was written to a row that was about to be
    deleted.
  * **The stored resolution is asked here**, defaulting to the setting. The
    moment of saving is the only one at which somebody knows how long the run
    turned out to be, and it is the last one at which the decision can still
    be made — 14 h at Δt = 2 s are 1 443 624 values, and every fifth step is
    a fifth of that and the same simulation.

The dialog decides nothing by itself: it reports a choice and the control
window carries it out.
"""

from enum import Enum

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class Choice(Enum):
    """What the operator decided. CANCEL means the window stays open."""

    CANCEL = "cancel"
    SAVE = "save"
    DISCARD = "discard"
    DELETE = "delete"


class ClosingDialog(QDialog):
    """Save, discard or delete — and export on the way out."""

    #: The Export button. The export needs the state and the log, which this
    #: dialog has not got, so it asks whoever opened it and stays open: the
    #: operator still has a decision to make afterwards.
    export_requested = Signal()

    def __init__(
        self,
        info,
        *,
        running: bool = False,
        storage_interval: int = 1,
        dt_seconds: float = 0.0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Close Project")
        self.setMinimumWidth(420)
        self.choice = Choice.CANCEL

        layout = QVBoxLayout(self)

        heading = QLabel(f"<b>{info.name}</b>")
        layout.addWidget(heading)
        if running:
            note = QLabel("The process is still running. Leaving pauses it.")
            note.setStyleSheet("color: #8a6d1a;")
            layout.addWidget(note)

        form = QFormLayout()
        self.name_field = QLineEdit(info.name or "")
        self.author_field = QLineEdit(info.author or "")
        self.description_field = QTextEdit(info.description or "")
        self.description_field.setFixedHeight(70)
        form.addRow("Project name:", self.name_field)
        form.addRow("Author:", self.author_field)
        form.addRow("Description:", self.description_field)

        self._dt_seconds = float(dt_seconds or 0)
        self.storage_box = QSpinBox()
        self.storage_box.setRange(1, 3600)
        self.storage_box.setValue(max(1, int(storage_interval)))
        self.storage_box.setMaximumWidth(140)
        self.storage_note = QLabel()
        self.storage_note.setStyleSheet("color: #6a6a6a;")
        storage_row = QHBoxLayout()
        storage_row.addWidget(self.storage_box)
        storage_row.addWidget(self.storage_note, 1)
        form.addRow("Store one point per:", storage_row)
        self.storage_box.valueChanged.connect(self._describe_storage)
        self._describe_storage(self.storage_box.value())

        layout.addLayout(form)

        buttons = QDialogButtonBox()
        self.save_button = QPushButton("Save and close")
        self.save_button.setDefault(True)
        self.discard_button = QPushButton("Discard changes")
        self.delete_button = QPushButton("Delete project…")
        self.export_button = QPushButton("Export…")
        self.cancel_button = QPushButton("Cancel")

        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.discard_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton(self.export_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        self.save_button.clicked.connect(lambda: self._choose(Choice.SAVE))
        self.discard_button.clicked.connect(lambda: self._choose(Choice.DISCARD))
        self.delete_button.clicked.connect(lambda: self._choose(Choice.DELETE))
        self.cancel_button.clicked.connect(self.reject)
        # Export does not close the dialog: exporting is not a decision about
        # the project, and the operator still has to make one.
        self.export_button.clicked.connect(lambda: self.export_requested.emit())

    # ------------------------------------------------------------ state --

    def info_fields(self) -> dict[str, str]:
        """The three editable fields, for save_project(info=…)."""
        return {
            "name": self.name_field.text().strip(),
            "author": self.author_field.text().strip(),
            "description": self.description_field.toPlainText().strip(),
        }

    def storage_interval(self) -> int:
        """Every n-th step, for save_project(storage_interval=…)."""
        return self.storage_box.value()

    def _describe_storage(self, interval: int) -> None:
        """What the number costs, in the step width of this project.

        Here Δt is known — it belongs to the project being closed — so the
        sentence says seconds instead of an example.
        """
        self.storage_box.setSuffix(" step" if interval == 1 else " steps")
        if self._dt_seconds <= 0:
            self.storage_note.setText("" if interval == 1 else f"one step in {interval}")
            return
        stored = self._dt_seconds * interval
        if interval == 1:
            self.storage_note.setText(f"everything — one point every {stored:g} s")
        else:
            self.storage_note.setText(
                f"one point every {stored:g} s — one row in every {interval}"
            )

    def _choose(self, choice: Choice) -> None:
        self.choice = choice
        self.accept()
