"""The controller panels of the Control Options tab (plan section 5.1).

Five panels that differ only in their fields — pH, temperature, pO2, liquid
weight and feed. They are described as data rather than laid out five times,
because which fields are live depends on the mode, and a table of that is
easier to check against the original than five near-identical constructors.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .indicators import SegmentedControl, StatusLamp, ToggleSwitch, ValueRow, select_data


@dataclass
class FieldSpec:
    """One editable setpoint, and the parameter behind it.

    `parameter`, `label` and `actual` may carry `{n}`: the feed panel works on
    one reservoir at a time, and FR1w, FR2w and FR3w are the same field with a
    different number in it. The panel fills it in from its reservoir selector.
    """

    parameter: str
    label: str
    actual: str = ""  # the variable shown next to it, if any
    actual_label: str = ""
    decimals: int = 2
    # Modes in which the field is live. Empty means always.
    modes: tuple[int, ...] = ()
    #: Shown but not typed into — a value this panel reports rather than sets.
    read_only: bool = False


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
    #: The parameter holding the reservoir this panel works on (R_feed). Set
    #: it and the panel gets a reservoir selector and fills in every `{n}`.
    reservoir_parameter: str | None = None
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

    def __init__(
        self, spec: PanelSpec, parent: QWidget | None = None, *, reservoirs: int = 1
    ):
        super().__init__(spec.title, parent)
        self.spec = spec
        # Keyed by the *template* name — "FR{n}w", not "FR1w" — so the keys
        # stay put when the reservoir changes.
        self.rows: dict[str, ValueRow] = {}
        self.switches: dict[str, ToggleSwitch] = {}
        self.reservoirs = max(1, int(reservoirs or 1))
        self.reservoir = 1
        #: The parameter set the panel was last filled from, so a reservoir
        #: change can refill without asking the window for it.
        self._p: dict | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.mode_selector: SegmentedControl | None = None
        self.lamp: StatusLamp | None = None
        if spec.mode_parameter:
            row = QHBoxLayout()
            row.addWidget(QLabel("Mode:"))
            # Keys instead of a dropdown: the operator sees what there is to
            # choose without opening anything, and the choice is one click
            # rather than two.
            self.mode_selector = SegmentedControl()
            for value, text in spec.modes.items():
                self.mode_selector.addItem(text, value)
            self.mode_selector.currentIndexChanged.connect(self._mode_changed)
            row.addWidget(self.mode_selector, 1)
            self.lamp = StatusLamp()
            row.addWidget(self.lamp)
            layout.addLayout(row)

        self.reservoir_selector: SegmentedControl | None = None
        if spec.reservoir_parameter and self.reservoirs > 1:
            # Only worth the row when there is a choice. With one reservoir
            # the panel simply works on R1, as the original does.
            row = QHBoxLayout()
            row.addWidget(QLabel("Reservoir:"))
            self.reservoir_selector = SegmentedControl()
            for number in range(1, self.reservoirs + 1):
                self.reservoir_selector.addItem(f"R{number}", number)
            self.reservoir_selector.currentIndexChanged.connect(self._reservoir_changed)
            row.addWidget(self.reservoir_selector, 1)
            layout.addLayout(row)

        for spec_field in spec.fields:
            widget = ValueRow(
                self._resolve(spec_field.label),
                self._resolve(spec_field.actual_label),
                decimals=spec_field.decimals,
            )
            if spec_field.read_only:
                # Set elsewhere — by the feed dialog or by a phase — and shown
                # here so the operator can see what the loop is working with.
                widget.setpoint.setReadOnly(True)
            else:
                widget.setpoint_changed.connect(
                    lambda value, template=spec_field.parameter: self.parameter_changed.emit(
                        self._resolve(template), value
                    )
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

    def _resolve(self, text: str) -> str:
        """Fill in the reservoir number: FR{n}w becomes FR1w."""
        return text.replace("{n}", str(self.reservoir)) if text else text

    def set_reservoir(self, number: int) -> None:
        """Work on another reservoir: new labels, new values, same widgets."""
        number = max(1, min(int(number), self.reservoirs))
        if number == self.reservoir:
            return
        self.reservoir = number
        if self.reservoir_selector is not None:
            self.reservoir_selector.blockSignals(True)
            select_data(self.reservoir_selector, number)
            self.reservoir_selector.blockSignals(False)
        for spec_field in self.spec.fields:
            row = self.rows[spec_field.parameter]
            row.set_labels(
                self._resolve(spec_field.label), self._resolve(spec_field.actual_label)
            )
        if self._p is not None:
            self.load(self._p)

    def _reservoir_changed(self) -> None:
        selector = self.reservoir_selector
        if selector is None:
            return
        self.set_reservoir(int(selector.currentData()))
        if self.spec.reservoir_parameter:
            self.parameter_changed.emit(
                self.spec.reservoir_parameter, float(self.reservoir)
            )

    def content_width(self) -> int:
        """How wide this panel has to be for nothing in it to be cut off.

        The minimum, not the wish: a QDoubleSpinBox asks for the widest number
        its range allows, and the mode keys ask to stand side by side. Neither
        has to be granted — the fields have a readable floor of their own and
        the keys wrap onto a second row.
        """
        width = self.minimumSizeHint().width()
        if self.mode_selector is not None:
            # One key, plus the "Mode:" caption, the lamp and the margins.
            width = max(width, self.mode_selector.minimumSizeHint().width() + 90)
        return width

    def current_mode(self) -> int | None:
        return self.mode_selector.currentData() if self.mode_selector else None

    def load(self, p) -> None:
        """Fill every widget from the parameter set, without emitting."""
        self._p = p
        if self.spec.reservoir_parameter and self.spec.reservoir_parameter in p:
            # A phase can switch the reservoir under the panel; the selector
            # follows the parameter, never the other way round.
            self.set_reservoir(int(p[self.spec.reservoir_parameter] or 1))
        if self.mode_selector is not None and self.spec.mode_parameter in p:
            self.mode_selector.blockSignals(True)
            select_data(self.mode_selector, p[self.spec.mode_parameter])
            self.mode_selector.blockSignals(False)

        for spec_field in self.spec.fields:
            row = self.rows[spec_field.parameter]
            name = self._resolve(spec_field.parameter)
            if name in p:
                row.setpoint.blockSignals(True)
                row.setpoint.setValue(float(p[name]))
                row.setpoint.blockSignals(False)

        for switch_spec in self.spec.switches:
            switch = self.switches[switch_spec.parameter]
            if switch_spec.parameter in p:
                # set_checked neither animates nor emits; see ToggleSwitch.
                switch.set_checked(bool(p[switch_spec.parameter]))

        self.apply_mode()

    def update_actuals(self, v, index: int) -> None:
        """Show the measured values of the step just computed."""
        for spec_field in self.spec.fields:
            if not spec_field.actual:
                continue
            series = v.get(self._resolve(spec_field.actual))
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
        if self.spec.mode_parameter and self.mode_selector is not None:
            self.parameter_changed.emit(
                self.spec.mode_parameter, float(self.mode_selector.currentData())
            )
