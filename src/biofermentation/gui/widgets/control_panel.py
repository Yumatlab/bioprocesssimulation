"""The controller panels of the Control Options tab (plan section 5.1).

Five panels that differ only in their fields — pH, temperature, pO2, liquid
weight and feed. They are described as data rather than laid out five times,
because which fields are live depends on the mode, and a table of that is
easier to check against the original than five near-identical constructors.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .indicators import StatusLamp, ToggleSwitch, ValueRow, select_data


@dataclass
class FieldSpec:
    """One editable setpoint, and the parameter behind it."""

    parameter: str
    label: str
    actual: str = ""  # the variable shown next to it, if any
    actual_label: str = ""
    decimals: int = 2
    # Modes in which the field is live. Empty means always.
    modes: tuple[int, ...] = ()


@dataclass
class SwitchSpec:
    parameter: str
    label: str
    modes: tuple[int, ...] = ()
    lamp: bool = False


@dataclass
class ParameterGroup:
    """One captioned block inside a controller's parameter dialog.

    The original spreads these over DialogBox2 to DialogBox6, one .mlapp per
    controller. They differ only in caption and parameter list, so here they
    are data and one dialog draws all of them.
    """

    title: str
    parameters: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class PanelSpec:
    """A controller panel, as the Control Options tab shows it."""

    title: str
    mode_parameter: str | None
    modes: dict[int, str] = field(default_factory=dict)
    fields: list[FieldSpec] = field(default_factory=list)
    switches: list[SwitchSpec] = field(default_factory=list)
    has_parameters_button: bool = True
    #: Contents of the "Parameters" dialog. Empty means the button is dead.
    parameter_groups: list[ParameterGroup] = field(default_factory=list)
    #: Per reservoir instead of once, as the feed gains are.
    parameter_groups_per_reservoir: list[ParameterGroup] = field(default_factory=list)


class ControlPanel(QGroupBox):
    """One panel. Emits parameter changes; it never writes to the state itself.

    Keeping the write out of the widget is what lets the control window put it
    inside the runner's guard — the timer must not step while a setpoint is
    half applied.
    """

    parameter_changed = Signal(str, float)
    parameters_requested = Signal(str)

    def __init__(self, spec: PanelSpec, parent: QWidget | None = None):
        super().__init__(spec.title, parent)
        self.spec = spec
        self.rows: dict[str, ValueRow] = {}
        self.switches: dict[str, ToggleSwitch] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.mode_box: QComboBox | None = None
        self.lamp: StatusLamp | None = None
        if spec.mode_parameter:
            row = QHBoxLayout()
            row.addWidget(QLabel("Mode:"))
            self.mode_box = QComboBox()
            # Sized by its longest entry, so no mode is cut off and every
            # panel can be given the same width without one of them
            # overflowing.
            self.mode_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            # Its size hint is the longest entry, so nothing is cut off, and
            # it grows into whatever the panel has left over. Without this the
            # box stops halfway and leaves a gap before the lamp.
            self.mode_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            for value, text in spec.modes.items():
                self.mode_box.addItem(text, value)
            self.mode_box.currentIndexChanged.connect(self._mode_changed)
            row.addWidget(self.mode_box, 1)
            self.lamp = StatusLamp()
            row.addWidget(self.lamp)
            layout.addLayout(row)

        for spec_field in spec.fields:
            widget = ValueRow(
                spec_field.label,
                spec_field.actual_label,
                decimals=spec_field.decimals,
            )
            widget.setpoint_changed.connect(
                lambda value, name=spec_field.parameter: self.parameter_changed.emit(name, value)
            )
            self.rows[spec_field.parameter] = widget
            layout.addWidget(widget)

        layout.addStretch()

        for switch_spec in spec.switches:
            switch = ToggleSwitch(switch_spec.label, lamp=switch_spec.lamp)
            switch.toggled.connect(
                lambda checked, name=switch_spec.parameter: self.parameter_changed.emit(
                    name, float(checked)
                )
            )
            self.switches[switch_spec.parameter] = switch
            layout.addWidget(switch)

        if spec.has_parameters_button:
            self.parameters_button = QPushButton("Parameters")
            self.parameters_button.clicked.connect(
                lambda: self.parameters_requested.emit(spec.title)
            )
            layout.addWidget(self.parameters_button)

    # ------------------------------------------------------------ state --

    def content_width(self) -> int:
        """How wide this panel has to be for nothing in it to be cut off."""
        width = self.sizeHint().width()
        if self.mode_box is not None:
            metrics = self.mode_box.fontMetrics()
            longest = max(
                (metrics.horizontalAdvance(text) for text in self.spec.modes.values()),
                default=0,
            )
            # Dropdown arrow, frame, the "Mode:" caption and the layout margins.
            width = max(width, longest + 130)
        return width

    def current_mode(self) -> int | None:
        return self.mode_box.currentData() if self.mode_box else None

    def load(self, p) -> None:
        """Fill every widget from the parameter set, without emitting."""
        if self.mode_box is not None and self.spec.mode_parameter in p:
            self.mode_box.blockSignals(True)
            select_data(self.mode_box, p[self.spec.mode_parameter])
            self.mode_box.blockSignals(False)

        for spec_field in self.spec.fields:
            row = self.rows[spec_field.parameter]
            if spec_field.parameter in p:
                row.setpoint.blockSignals(True)
                row.setpoint.setValue(float(p[spec_field.parameter]))
                row.setpoint.blockSignals(False)

        for switch_spec in self.spec.switches:
            switch = self.switches[switch_spec.parameter]
            if switch_spec.parameter in p:
                switch.checkbox.blockSignals(True)
                switch.set_checked(bool(p[switch_spec.parameter]))
                switch.checkbox.blockSignals(False)

        self.apply_mode()

    def update_actuals(self, v, index: int) -> None:
        """Show the measured values of the step just computed."""
        for spec_field in self.spec.fields:
            if not spec_field.actual:
                continue
            series = v.get(spec_field.actual)
            if series is not None and index < series.size:
                self.rows[spec_field.parameter].set_actual(float(series[index]))

    def apply_mode(self) -> None:
        """Grey out what the current mode does not use, as the original does."""
        mode = self.current_mode()
        for spec_field in self.spec.fields:
            live = not spec_field.modes or mode in spec_field.modes
            self.rows[spec_field.parameter].setEnabled(live)
        for switch_spec in self.spec.switches:
            live = not switch_spec.modes or mode in switch_spec.modes
            self.switches[switch_spec.parameter].setEnabled(live)
        if self.lamp is not None:
            # Green once the panel is doing something automatic, as in MATLAB.
            self.lamp.set_on(bool(mode))

    def _mode_changed(self) -> None:
        self.apply_mode()
        if self.spec.mode_parameter and self.mode_box is not None:
            self.parameter_changed.emit(
                self.spec.mode_parameter, float(self.mode_box.currentData())
            )
