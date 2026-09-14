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
    QGroupBox,
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

        layout.addWidget(
            _note("Takes effect the next time a project is opened, not in a window already open.")
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> Settings:
        """What the boxes currently say."""
        return Settings(
            hidden_tabs={name for name, box in self.boxes.items() if not box.isChecked()},
            student_view=self.student_box.isChecked(),
        )

    def accept(self) -> None:
        save_settings(self.settings(), self._path)
        super().accept()


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6a6a6a;")
    return label
