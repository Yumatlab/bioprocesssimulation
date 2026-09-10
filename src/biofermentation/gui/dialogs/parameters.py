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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..widgets.tex import tex_label, tex_to_html

#: reading_rate values that stay editable once the simulation has started.
CYCLIC = "cyclic"
#: reading_rate value of parameters no editor should show at all.
INVISIBLE = "invisible"


def _spin(value: float, decimals: int = 4) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
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

    def accept(self) -> None:
        """Only what actually moved. An untouched field is not a change."""
        self.changes = {
            name: box.value()
            for name, box in self._boxes.items()
            if box.isEnabled() and abs(box.value() - self._original[name]) > 1e-15
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
        row = QHBoxLayout()
        row.addWidget(QLabel("Search:"))
        row.addWidget(self.search, 1)
        layout.addLayout(row)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self._inner_layout = QVBoxLayout(inner)
        area.setWidget(inner)
        layout.addWidget(area, 1)

        self._rows: list[tuple[QWidget, str]] = []
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
                self._rows.append((widget, f"{name} {category} {section}".lower()))
                # A form row hides as a pair, so the label has to follow.
                self._rows.append((label, f"{name} {category} {section}".lower()))
            if form.rowCount():
                self._inner_layout.addWidget(group)
                self._groups.append(group)

        self._inner_layout.addStretch()
        if started:
            layout.addWidget(_locked_hint(partial=True))
        layout.addWidget(self._button_box())

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for widget, haystack in self._rows:
            widget.setVisible(not needle or needle in haystack)
        for group in self._groups:
            visible = any(
                widget.isVisibleTo(group) for widget, _ in self._rows if widget.parent() is group
            )
            group.setVisible(visible)


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
    """Group the metadata rows, keeping the order load_phases sorted them in."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for meta in p_meta:
        if meta.get("reading_rate") == INVISIBLE:
            continue
        section = meta.get("categorysection") or "Other"
        if sections is not None and section not in sections:
            continue
        grouped.setdefault((section, meta.get("categoryname") or "Other"), []).append(meta)
    return grouped
