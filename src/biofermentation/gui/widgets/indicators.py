"""Small widgets the control surface repeats (plan section 5.1).

A status lamp and an off/on switch. MATLAB has uilamp and a rocker switch
built in; Qt does not, so they are drawn here — small enough to keep, and
having them as widgets means the panels stay readable.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget

from .tex import tex_to_html


def select_data(box, value) -> bool:
    """Select the item carrying value. Returns whether it was found.

    int() is the point of the function. QComboBox.findData compares through a
    QVariant, and a QVariant holding a plain int does not match an IntEnum —
    findData(EndCondition.TIMER) returns -1 where findData(7) returns 0. Every
    id in this application comes from a lookup table and has an IntEnum next
    to it, so the trap is one line away everywhere.
    """
    if value is None:
        return False
    index = box.findData(int(value))
    if index < 0:
        return False
    box.setCurrentIndex(index)
    return True


# The four colours of MATLAB's phase status lamp, in status order.
STATUS_COLORS = {
    1: QColor(128, 128, 128),  # upcoming
    2: QColor(255, 179, 26),  # pending
    3: QColor(0, 170, 0),  # active
    4: QColor(220, 0, 0),  # completed
}

GREEN = QColor(0, 190, 0)
RED = QColor(220, 40, 40)
GREY = QColor(150, 150, 150)


class StatusLamp(QWidget):
    """A filled circle. Qt has no uilamp."""

    def __init__(self, color: QColor = GREY, diameter: int = 14, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = color
        self._diameter = diameter
        self.setFixedSize(QSize(diameter + 2, diameter + 2))

    def color(self) -> QColor:
        return self._color

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def set_on(self, on: bool) -> None:
        self.set_color(GREEN if on else RED)

    def set_status(self, status_id: int) -> None:
        self.set_color(STATUS_COLORS.get(int(status_id), GREY))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(QColor(90, 90, 90))
        painter.drawEllipse(1, 1, self._diameter, self._diameter)


class ToggleSwitch(QWidget):
    """Off — [switch] — On, the rocker of the original.

    A styled QCheckBox carries the state, so keyboard handling, focus and the
    accessibility tree come from Qt rather than from a repaint.
    """

    toggled = Signal(bool)

    def __init__(
        self,
        label: str = "",
        *,
        lamp: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.label = QLabel(label)
        font = self.label.font()
        font.setBold(True)
        self.label.setFont(font)
        if label:
            layout.addWidget(self.label)
        layout.addStretch()

        self.off_label = QLabel("Off")
        self.checkbox = QCheckBox()
        self.on_label = QLabel("On")
        layout.addWidget(self.off_label)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.on_label)

        self.lamp = StatusLamp(RED, diameter=11) if lamp else None
        if self.lamp is not None:
            layout.addWidget(self.lamp)

        self.checkbox.toggled.connect(self._on_toggled)
        self._update_labels(False)

    def _on_toggled(self, checked: bool) -> None:
        self._update_labels(checked)
        self.toggled.emit(checked)

    def _update_labels(self, checked: bool) -> None:
        for widget, active in ((self.off_label, not checked), (self.on_label, checked)):
            font = widget.font()
            font.setBold(active)
            widget.setFont(font)
        if self.lamp is not None:
            self.lamp.set_on(checked)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.checkbox.setChecked(bool(checked))

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt API
        super().setEnabled(enabled)
        self.checkbox.setEnabled(enabled)


class ValueRow(QWidget):
    """A setpoint next to its measured value, the way every panel shows one.

    The setpoint is editable, the actual value never is — it comes out of the
    simulation. MATLAB greys the actual field; here it is read-only, which
    says the same thing and cannot be typed into by accident.
    """

    setpoint_changed = Signal(float)

    def __init__(
        self,
        setpoint_label: str,
        actual_label: str = "",
        *,
        decimals: int = 2,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout, QLineEdit

        self.decimals = decimals
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        left = QLabel(tex_to_html(setpoint_label))
        left.setTextFormat(Qt.TextFormat.RichText)
        left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(left, 0, 0)

        self.setpoint = QDoubleSpinBox()
        self.setpoint.setDecimals(decimals)
        self.setpoint.setRange(-1e9, 1e9)
        self.setpoint.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setpoint.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setpoint.valueChanged.connect(self.setpoint_changed.emit)
        layout.addWidget(self.setpoint, 1, 0)

        self.actual: QLineEdit | None = None
        if actual_label:
            right = QLabel(tex_to_html(actual_label))
            right.setTextFormat(Qt.TextFormat.RichText)
            right.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(right, 0, 1)

            self.actual = QLineEdit()
            self.actual.setReadOnly(True)
            self.actual.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(self.actual, 1, 1)

    def set_actual(self, value: float) -> None:
        if self.actual is not None:
            self.actual.setText(f"{value:.{self.decimals}f}")
