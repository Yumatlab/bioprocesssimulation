"""The settings dialog of the starting screen.

Four things, and none of them changes a number the simulation computes: which
tabs of the control window exist, whether the run controls can be touched, how
often the screen is redrawn, and how much of a run is written down.

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
    QSpinBox,
    QVBoxLayout,
)

from ..settings import HIDEABLE_TABS, Settings, load_settings, save_settings

#: The step width the explanation counts with. Δt belongs to a project, and
#: this dialog is opened from the starting screen, where none is open — so the
#: sentence names it as an example instead of pretending to know it. 2 s is
#: what the projects of this application are configured with.
EXAMPLE_DT = 2.0


class SettingsDialog(QDialog):
    """What this installation shows, and how much of it can be changed."""

    def __init__(self, parent=None, *, path: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        # Wide enough for the explanations, which are what this dialog is
        # mostly made of: at 440 px every note wrapped into four or five lines
        # and the group they belong to was taller than the setting itself.
        # 680 puts each of them on two.
        self.setMinimumWidth(680)
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

        store = QGroupBox("Stored resolution")
        store_layout = QVBoxLayout(store)
        store_row = QHBoxLayout()
        self.storage_box = QSpinBox()
        self.storage_box.setRange(1, 3600)
        self.storage_box.setValue(settings.storage_interval)
        self.storage_box.setMaximumWidth(120)
        store_row.addWidget(QLabel("Store one point per"))
        store_row.addWidget(self.storage_box)
        store_row.addStretch()
        store_layout.addLayout(store_row)

        self.storage_note = _note("")
        store_layout.addWidget(self.storage_note)

        self.ask_box = QCheckBox("Offer this again in the closing dialog")
        self.ask_box.setChecked(settings.ask_storage_on_save)
        self.ask_box.setToolTip(
            "Unticked, saving uses the value above without asking — one "
            "decision for a whole course instead of one per student."
        )
        store_layout.addWidget(self.ask_box)
        store_layout.addWidget(
            _note(
                "Δt is what the controllers are tuned for and is not the place "
                "to save room — this is. The run itself is unchanged: every "
                "step is computed and plotted, only fewer are written to the "
                "file. What a reopened project can show is what was stored."
            )
        )
        self.storage_box.valueChanged.connect(self._describe_storage)
        self._describe_storage(self.storage_box.value())
        layout.addWidget(store)

        # The slack goes here, so the closing note keeps its place above the
        # buttons instead of drifting into the middle of the dialog.
        layout.addStretch()
        layout.addWidget(
            _note("Takes effect the next time a project is opened, not in a window already open.")
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Opened at what it asks for, at the width it is given. A word-wrapped
        # note reports its height without knowing how wide it will be, so the
        # hint is generous — 795 px where the layout would fit in 615 — and
        # the stretch above puts that slack at the bottom. Taking
        # `heightForWidth` instead clipped the last note by two lines: it is
        # the group boxes that report it too tightly, and a dialog that hides
        # the end of a sentence is worse than one with room to spare.
        self.resize(max(self.minimumWidth(), self.sizeHint().width()), self.sizeHint().height())

    def _follow_coupling(self, coupled: bool) -> None:
        """A field that changes nothing belongs greyed out."""
        self.refresh_box.setEnabled(not coupled)
        self.refresh_label.setEnabled(not coupled)
        self.refresh_box.setToolTip(
            "Follows Δt — the box above unties them" if coupled else ""
        )

    def _describe_storage(self, interval: int) -> None:
        """Say what the number means in points, not in factors.

        The dialog belongs to the starting screen and has no project, so there
        is no Δt to read; EXAMPLE_DT stands in for one and is named as an
        example rather than presented as the setting.
        """
        # "per 1 step", "per 5 steps" — a spin box has one suffix, so it is
        # set with the value rather than once.
        self.storage_box.setSuffix(" step" if interval == 1 else " steps")
        per_hour = 3600 / (EXAMPLE_DT * interval)
        if interval == 1:
            self.storage_note.setText(
                f"Every computed step is stored. At Δt = {EXAMPLE_DT:g} s that is "
                f"{per_hour:,.0f} points per hour and variable."
            )
        else:
            # "one step in 5" rather than "every 5th step": the number comes
            # from a spin box, and English ordinals do not.
            self.storage_note.setText(
                f"One step in {interval} is stored. At Δt = {EXAMPLE_DT:g} s that is one "
                f"point every {EXAMPLE_DT * interval:g} s, {per_hour:,.0f} per hour and "
                f"variable — one row in every {interval}."
            )

    def settings(self) -> Settings:
        """What the boxes currently say."""
        return Settings(
            hidden_tabs={name for name, box in self.boxes.items() if not box.isChecked()},
            student_view=self.student_box.isChecked(),
            couple_refresh_to_dt=self.couple_box.isChecked(),
            refresh_seconds=self.refresh_box.value(),
            storage_interval=self.storage_box.value(),
            ask_storage_on_save=self.ask_box.isChecked(),
        )

    def accept(self) -> None:
        save_settings(self.settings(), self._path)
        super().accept()


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6a6a6a;")
    return label
