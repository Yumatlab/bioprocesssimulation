"""Parameter editors (points 3 and 4 of the review).

Two dialogs, one rule between them.

`ControllerParametersDialog` is what the "Parameters" button of a controller
panel opens. The original has one .mlapp per controller — DialogBox2 for pH,
DialogBox3 for temperature, DialogBox4 for pO2, DialogBox5 for the liquid
weight and DialogBox6 per feed reservoir. They differ only in caption and
parameter list, so `panel_specs` carries that as data and this one dialog
draws all of them.

`ParameterDialog` is the full parameter set, grouped by category. It is the
counterpart of MATLAB's "Edit Starting Variables" (DialogBox1), widened from
six fields to everything the project has.

The rule: what may be changed while the simulation runs is not decided here.
`categoryTab.reading_rate` already says it — `cyclic` for setpoints, modes,
flags, controller gains and feed control, `once` for everything that is read
at the first step and never again (initial values such as cS1L0, vessel
geometry, growth kinetics), `invisible` for internal settings. Before the
first step everything visible is editable; afterwards only the cyclic ones.
That is why no new column was added to the database.
"""

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...control import PHASE_PARAMETERS, PhaseType
from ..widgets.tex import tex_label, tex_to_html

#: reading_rate values that stay editable once the simulation has started.
CYCLIC = "cyclic"
#: reading_rate value of parameters no editor should show at all.
INVISIBLE = "invisible"

#: The order the sections of categoryTab are shown in. The database sorts by
#: id, which puts "General" — calibration constants and switches nobody opens
#: this dialog for — above the setpoints. This is the order they are looked
#: for in: what is being run, then what it is run with, then the vessel, then
#: the rest. A section not named here follows, in database order.
SECTION_ORDER = ("Parameters", "Organism", "Bioreactor", "General")


def decimals_for(value: float, floor: int = 4, cap: int = 12) -> int:
    """Enough places to show this value, at least `floor`.

    A box with four decimals holds 1e-05 as 0.0000 and hands that back on the
    next read: KD_gasmix appeared as "1e-05 → 0" in every phase, untouched,
    because the field could not represent what was put into it.
    """
    if not value or not math.isfinite(value):
        return floor
    magnitude = math.floor(math.log10(abs(value)))
    return min(cap, max(floor, 3 - magnitude))


def _spin(value: float, decimals: int | None = None) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals_for(float(value)) if decimals is None else decimals)
    box.setRange(-1e12, 1e12)
    box.setValue(float(value))
    box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    box.setMinimumWidth(110)
    box.setMaximumWidth(150)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    return box


def _rich(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


class _EditorBase(QDialog):
    """Collects edits and hands them back only on Ok.

    The caller writes them into the state inside the runner's guard; the
    dialog itself never touches the simulation. Same split as the phase
    editor, and for the same reason — a timer tick must not see half an edit.
    """

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._boxes: dict[str, QDoubleSpinBox] = {}
        self._original: dict[str, float] = {}
        self.changes: dict[str, float] = {}

    def _button_box(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Confirm")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        return buttons

    def _differs(self, name: str) -> bool:
        """Whether the field was moved — measured in what the field can show.

        A box rounds to its own decimals and hands the rounded number back.
        Comparing that against the unrounded original made every parameter too
        small for its field look like a change nobody made.
        """
        box = self._boxes[name]
        return abs(box.value() - self._original[name]) > 0.5 * 10 ** -box.decimals()

    def accept(self) -> None:
        """Only what actually moved. An untouched field is not a change."""
        self.changes = {
            name: box.value()
            for name, box in self._boxes.items()
            if box.isEnabled() and self._differs(name)
        }
        super().accept()


class ControllerParametersDialog(_EditorBase):
    """The gains of one controller, as DialogBox2 to DialogBox6 show them."""

    def __init__(self, spec, p, *, reservoirs: int = 1, editable: bool = True, parent=None):
        super().__init__(f"{spec.title} Parameters", parent)
        layout = QVBoxLayout(self)

        heading = QLabel(f"Parameters of the {spec.title}")
        font = heading.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        heading.setFont(font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        groups = list(spec.parameter_groups)
        for number in range(1, max(1, reservoirs) + 1):
            for template in spec.parameter_groups_per_reservoir:
                groups.append(
                    type(template)(
                        template.title.format(n=number),
                        # Only the parameter name carries the number; the
                        # label is TeX and its braces are not format fields.
                        [(name.format(n=number), label) for name, label in template.parameters],
                    )
                )

        shown = 0
        for group in groups:
            box = QGroupBox(group.title)
            form = QFormLayout(box)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
            for name, label in group.parameters:
                if name not in p:
                    continue  # a reservoir the project does not have
                widget = _spin(p[name])
                widget.setEnabled(editable)
                self._boxes[name] = widget
                self._original[name] = float(p[name])
                form.addRow(_rich(tex_to_html(label) + ":"), widget)
                shown += 1
            if form.rowCount():
                layout.addWidget(box)

        if not shown:
            layout.addWidget(QLabel("This controller has no adjustable parameters."))
        if not editable:
            layout.addWidget(_locked_hint())

        layout.addStretch()
        layout.addWidget(self._button_box())


class ParameterDialog(_EditorBase):
    """Every parameter of the project, grouped by category.

    Before the first step all visible parameters are editable. Once the
    simulation has advanced, only the cyclic ones are — an initial value read
    at step 0 cannot be changed retroactively without invalidating the run.
    """

    def __init__(self, p_meta, p, *, started: bool, sections=None, parent=None):
        super().__init__("Parameters", parent)
        self.resize(560, 720)
        layout = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name or category…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.editable_only = QCheckBox("Only editable")
        self.editable_only.setToolTip(
            "Hide the parameters that are read once at the first step and "
            "cannot be changed while the simulation runs."
        )
        self.editable_only.toggled.connect(self._filter)

        row = QHBoxLayout()
        row.addWidget(QLabel("Search:"))
        row.addWidget(self.search, 1)
        row.addWidget(self.editable_only)
        layout.addLayout(row)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self._inner_layout = QVBoxLayout(inner)
        area.setWidget(inner)
        layout.addWidget(area, 1)

        #: (widget, haystack, editable) — the filter needs all three.
        self._rows: list[tuple[QWidget, str, bool]] = []
        self._groups: list[QGroupBox] = []

        for (section, category), entries in _by_category(p_meta, sections).items():
            group = QGroupBox(f"{section} — {category}")
            form = QFormLayout(group)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
            for meta in entries:
                name = meta["parametername"]
                if name not in p:
                    continue
                widget = _spin(p[name])
                cyclic = meta.get("reading_rate") == CYCLIC
                widget.setEnabled(cyclic or not started)
                if started and not cyclic:
                    widget.setToolTip(
                        "Read once at the first step — changing it now would not reach the model."
                    )
                self._boxes[name] = widget
                self._original[name] = float(p[name])
                label = _rich(tex_label(meta.get("tex") or name, meta.get("unit")) + ":")
                label.setToolTip(f"{name}\n{meta.get('description') or ''}".strip())
                form.addRow(label, widget)
                haystack = f"{name} {category} {section}".lower()
                editable = widget.isEnabled()
                # A form row hides as a pair, so the label has to follow.
                self._rows.append((widget, haystack, editable))
                self._rows.append((label, haystack, editable))
            if form.rowCount():
                self._inner_layout.addWidget(group)
                self._groups.append(group)

        self._inner_layout.addStretch()
        if started:
            layout.addWidget(_locked_hint(partial=True))
        layout.addWidget(self._button_box())

    def _filter(self, *_) -> None:
        """Search text and the editable-only tick, together."""
        needle = self.search.text().strip().lower()
        only_editable = self.editable_only.isChecked()
        for widget, haystack, editable in self._rows:
            matches = not needle or needle in haystack
            widget.setVisible(matches and (editable or not only_editable))
        for group in self._groups:
            group.setVisible(
                any(
                    widget.isVisibleTo(group)
                    for widget, _, _ in self._rows
                    if widget.parent() is group
                )
            )


def offered_parameters(phase, p_meta: list[dict]) -> list[dict]:
    """Which parameters a phase of this type may set, in display order.

    An **Update Parameter Set** phase exists to change parameters, so it gets
    all of them — the `cyclic` ones, which are the ones a running process can
    take. The two feed phases get the handful their own handler reads, for
    their own reservoir and no other, from `PHASE_PARAMETERS`. Every other
    type gets nothing: a manual phase does not apply parameters, and a list of
    fields that do nothing is worse than no list.
    """
    type_id = phase.typeID
    if type_id == PhaseType.PARAMETER_UPDATE:
        return [meta for meta in p_meta if meta.get("reading_rate") == CYCLIC]

    templates = PHASE_PARAMETERS.get(type_id, ())
    if not templates:
        return []
    # The feed parameters belong to one reservoir. reading_rate does not come
    # into it: these are read by the phase handler when the phase starts, not
    # at the first step of the run.
    wanted = [template.replace("{n}", str(phase.reservoirID or 1)) for template in templates]
    by_name = {meta["parametername"]: meta for meta in p_meta}
    return [by_name[name] for name in wanted if name in by_name]


class PhaseParameterDialog(_EditorBase):
    """The parameters a phase applies when it starts.

    PhaseParameterEditor.mlapp: the parameters with a field each, a reset
    button next to every one that has been changed, and a running list of what
    the phase will do. Which parameters are offered depends on the phase type;
    see `offered_parameters`.

    What the phase stores is the *difference* from the project value. An
    untouched field means "leave it as it is", which is not the same as
    writing the current value back: the operator may have moved it since.
    """

    def __init__(self, phase, p_meta, p, *, parent=None):
        super().__init__(f"Parameters of {phase.name or 'the phase'}", parent)
        self.resize(620, 720)
        self._phase = phase
        layout = QVBoxLayout(self)

        offered = offered_parameters(phase, p_meta)
        reservoir = phase.reservoirID or 1
        note = (
            "These values are applied when the phase starts. Everything not "
            "touched here keeps whatever the process has at that moment."
        )
        if phase.typeID in PHASE_PARAMETERS:
            note = (
                f"The feed of reservoir R{reservoir} is computed from these when "
                "the phase starts. Everything else the phase leaves alone."
            )
        heading = QLabel(note)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name or category…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        row = QHBoxLayout()
        row.addWidget(QLabel("Search:"))
        row.addWidget(self.search, 1)
        layout.addLayout(row)
        # Five fields need no search box; two hundred do.
        self.search.setVisible(len(offered) > 12)
        row.itemAt(0).widget().setVisible(len(offered) > 12)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self._inner_layout = QVBoxLayout(inner)
        area.setWidget(inner)
        layout.addWidget(area, 1)

        self._rows: list[tuple[QWidget, str]] = []
        self._groups: list[QGroupBox] = []
        self._resets: dict[str, QPushButton] = {}

        for (section, category), entries in _by_category(offered).items():
            group = QGroupBox(f"{section} — {category}")
            form = QFormLayout(group)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
            for meta in entries:
                name = meta["parametername"]
                if name not in p:
                    continue
                self._add_row(form, meta, name, float(p[name]))
            if form.rowCount():
                self._inner_layout.addWidget(group)
                self._groups.append(group)
        self._inner_layout.addStretch()

        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setFixedHeight(96)
        layout.addWidget(QLabel("Changes made:"))
        layout.addWidget(self.summary)
        layout.addWidget(self._button_box())
        self._update_summary()

    def _add_row(self, form: QFormLayout, meta: dict, name: str, project_value: float) -> None:
        stored = self._phase.parameters.get(name)
        widget = _spin(stored if stored is not None else project_value)
        widget.valueChanged.connect(lambda _=0.0, key=name: self._changed(key))
        self._boxes[name] = widget
        #: The value to fall back to — the project's, not the phase's.
        self._original[name] = project_value

        reset = QPushButton("↺ Drop")
        # Sized to its own text: a fixed 28 px left the stylesheet's 10 px of
        # padding on either side and clipped what was between them.
        reset.setFixedWidth(reset.sizeHint().width())
        reset.setToolTip("Drop this parameter from the phase — it keeps the project value")
        reset.clicked.connect(lambda _=False, key=name: self._reset(key))
        self._resets[name] = reset

        field = QWidget()
        row = QHBoxLayout(field)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(widget)
        row.addWidget(reset)

        label = _rich(tex_label(meta.get("tex") or name, meta.get("unit")) + ":")
        label.setToolTip(f"{name}\n{meta.get('description') or ''}".strip())
        form.addRow(label, field)

        haystack = f"{name} {meta.get('categoryname') or ''} {meta.get('categorysection') or ''}"
        self._rows.append((label, haystack.lower()))
        self._rows.append((field, haystack.lower()))
        self._mark(name)

    # ---------------------------------------------------------- changes --

    def _changed(self, name: str) -> None:
        self._mark(name)
        self._update_summary()

    def _reset(self, name: str) -> None:
        box = self._boxes[name]
        box.blockSignals(True)
        box.setValue(self._original[name])
        box.blockSignals(False)
        self._mark(name)
        self._update_summary()

    def _mark(self, name: str) -> None:
        """A changed field looks changed, and only then can be reset."""
        changed = self._differs(name)
        self._resets[name].setVisible(changed)
        self._boxes[name].setStyleSheet(
            "background: #e3f5e3; border-color: #4a9a4a;" if changed else ""
        )

    def _update_summary(self) -> None:
        lines = [
            f"{name}: {self._original[name]:g} → {self._boxes[name].value():g}"
            for name in sorted(self._boxes)
            if self._differs(name)
        ]
        self.summary.setPlainText(
            "\n".join(lines) if lines else "Nothing — the phase leaves every parameter alone."
        )

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for widget, haystack in self._rows:
            widget.setVisible(not needle or needle in haystack)
        for group in self._groups:
            group.setVisible(
                any(
                    widget.isVisibleTo(group)
                    for widget, _ in self._rows
                    if widget.parent() is group
                )
            )

    def accept(self) -> None:
        """Write the differences into the phase. Nothing else is stored."""
        super().accept()
        self._phase.parameters = dict(self.changes)


def _locked_hint(*, partial: bool = False) -> QLabel:
    text = (
        "Greyed-out parameters are read once at the first step and cannot be "
        "changed during a running simulation."
        if partial
        else "The simulation has started — these parameters are read only."
    )
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6a6a6a;")
    return label


def _by_category(p_meta, sections=None) -> dict[tuple[str, str], list[dict]]:
    """Group the metadata rows, sections in reading order.

    Within a section the order is the one `load_phases` sorted the rows in.
    The sections themselves are put in the order someone looks for them:
    what the run does first, then what it runs on. A section the database
    grew that SECTION_ORDER does not know comes last rather than nowhere.
    """
    grouped: dict[tuple[str, str], list[dict]] = {}
    for meta in p_meta:
        if meta.get("reading_rate") == INVISIBLE:
            continue
        section = meta.get("categorysection") or "Other"
        if sections is not None and section not in sections:
            continue
        grouped.setdefault((section, meta.get("categoryname") or "Other"), []).append(meta)

    def rank(key: tuple[str, str]) -> int:
        section = key[0]
        return SECTION_ORDER.index(section) if section in SECTION_ORDER else len(SECTION_ORDER)

    return {key: grouped[key] for key in sorted(grouped, key=rank)}
