"""The settings dialog of the starting screen.

Two things, and both are about the room rather than about the run: which tabs
of the control window exist, and whether the run controls can be touched.

They are set before a project is opened and read when the control window
builds itself — a window that is already open keeps what it was built with,
which the dialog says rather than pretending otherwise.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from ..settings import HIDEABLE_TABS, Settings, load_settings, save_settings


class SettingsDialog(QDialog):
    """What this installation shows, and how much of it can be changed."""

    def __init__(self, parent=None, *, path: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)
        self._path = path
        settings, problem = load_settings(path)

        layout = QVBoxLayout(self)
        if problem:
            broken = QLabel(f"The settings file could not be read and was ignored: {problem}")
            broken.setWordWrap(True)
            broken.setStyleSheet("color: #8a6d1a;")
            layout.addWidget(broken)

        tabs = QGroupBox("Tabs of the control window")
        tab_layout = QVBoxLayout(tabs)
        tab_layout.addWidget(
            _note(
                "Everything ticked is shown. Control Options and Information "
                "are always there — a window without them is not a control "
                "window."
            )
        )
        self.boxes: dict[str, QCheckBox] = {}
        for name in HIDEABLE_TABS:
            box = QCheckBox(name)
            box.setChecked(settings.shows(name))
            tab_layout.addWidget(box)
            self.boxes[name] = box
        layout.addWidget(tabs)

        view = QGroupBox("Student view")
        view_layout = QVBoxLayout(view)
        self.student_box = QCheckBox("Lock the run controls")
        self.student_box.setChecked(settings.student_view)
        view_layout.addWidget(self.student_box)
        view_layout.addWidget(
            _note(
                "Δt stays visible but cannot be changed, and the speed factor "
                "is not shown at all. A run everybody started with the same "
                "step width is comparable; one where each machine ran at its "
                "own factor is not."
            )
        )
        layout.addWidget(view)

        pace = QGroupBox("Refresh")
        pace_layout = QVBoxLayout(pace)
        self.couple_box = QCheckBox("Tie the refresh rate to Δt")
        self.couple_box.setChecked(settings.couple_refresh_to_dt)
        pace_layout.addWidget(self.couple_box)

        row = QHBoxLayout()
        self.refresh_label = QLabel("Refresh every")
        self.refresh_box = QDoubleSpinBox()
        self.refresh_box.setRange(0.05, 600.0)
        self.refresh_box.setDecimals(2)
        self.refresh_box.setSingleStep(0.5)
        self.refresh_box.setSuffix(" s")
        self.refresh_box.setValue(settings.refresh_seconds)
        self.refresh_box.setMaximumWidth(120)
        row.addSpacing(20)
        row.addWidget(self.refresh_label)
        row.addWidget(self.refresh_box)
        row.addStretch()
        pace_layout.addLayout(row)

        pace_layout.addWidget(
            _note(
                "Tied: one tick per computed step, so a speed factor of 1 "
                "runs at real time. Untied, the field sets the pace — and the "
                "run then goes Δt divided by refresh times faster than the "
                "real process."
            )
        )
        layout.addWidget(pace)

        # The field belongs to the box above it: dead while they are tied.
        self.couple_box.toggled.connect(self._follow_coupling)
        self._follow_coupling(self.couple_box.isChecked())

        layout.addWidget(
            _note("Takes effect the next time a project is opened, not in a window already open.")
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _follow_coupling(self, coupled: bool) -> None:
        """A field that changes nothing belongs greyed out."""
        self.refresh_box.setEnabled(not coupled)
        self.refresh_label.setEnabled(not coupled)
        self.refresh_box.setToolTip(
            "Follows Δt — the box above unties them" if coupled else ""
        )

    def settings(self) -> Settings:
        """What the boxes currently say."""
        return Settings(
            hidden_tabs={name for name, box in self.boxes.items() if not box.isChecked()},
            student_view=self.student_box.isChecked(),
            couple_refresh_to_dt=self.couple_box.isChecked(),
            refresh_seconds=self.refresh_box.value(),
        )

    def accept(self) -> None:
        save_settings(self.settings(), self._path)
        super().accept()


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6a6a6a;")
    return label
