"""The Controllers tab: what each loop is doing, and why.

The application computes every share of every controller at every step and,
until this tab, displayed none of them. A student saw pO2 oscillate without
seeing the integral wind up — which is the one thing that explains it.

One panel per loop: setpoint, measurement, error, the P, I and D shares as
signed bars against a common scale, the gain behind each, and what the loop
moves. Nothing here is computed; every number is read out of the state the
step just produced. What a loop is called and which signals it taps comes
from the organism (`OrganismModel.control_loops`), not from this file.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .indicators import GREEN, GREY, StatusLamp
from .tex import tex_to_html

#: One colour per share, used for the bar and the letter in front of it.
SHARE_COLORS = {
    "P": QColor(0x2F, 0x7F, 0xD1),
    "I": QColor(0xE0, 0x8A, 0x1E),
    "D": QColor(0x7B, 0x5C, 0xC4),
}
#: How many loop panels stand side by side.
COLUMNS = 2


class ShareBar(QWidget):
    """One signed bar from a centre line. Left is negative, right positive.

    The three bars of a loop share one scale, so their lengths can be compared
    — that is the whole point of drawing them: which share is carrying the
    output right now, and which one is running away.
    """

    HEIGHT = 14

    def __init__(self, color: QColor, parent: QWidget | None = None):
        super().__init__(parent)
        self.color = color
        self._value = 0.0
        self._scale = 1.0
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float, scale: float) -> None:
        self._value = float(value)
        self._scale = float(scale) or 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        middle = self.width() / 2
        painter.fillRect(self.rect(), QColor(0xF2, 0xF2, 0xF2))
        painter.setPen(QColor(0xC8, 0xC8, 0xC8))
        painter.drawLine(int(middle), 0, int(middle), self.HEIGHT)

        if not self.isEnabled() or not self._value:
            return
        fraction = max(-1.0, min(1.0, self._value / self._scale))
        length = fraction * (middle - 1)
        bar = QRectF(middle, 2, length, self.HEIGHT - 4).normalized()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawRect(bar)


class LoopPanel(QGroupBox):
    """One control loop, read out of the state after every block."""

    def __init__(self, loop, parent: QWidget | None = None):
        super().__init__(loop.name, parent)
        self.setObjectName("controlPanel")
        self.loop = loop
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        head = QHBoxLayout()
        self.state_label = QLabel("off")
        self.lamp = StatusLamp(GREY, diameter=11)
        head.addWidget(self.state_label)
        head.addStretch()
        head.addWidget(self.lamp)
        layout.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        self.values: dict[str, QLabel] = {}
        for column, (key, caption) in enumerate(
            (("setpoint", "Setpoint"), ("measurement", "Measured"), ("error", "Error"))
        ):
            caption_label = QLabel(caption)
            caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = QFont(value.font())
            font.setBold(True)
            value.setFont(font)
            grid.addWidget(caption_label, 0, column)
            grid.addWidget(value, 1, column)
            self.values[key] = value
        layout.addLayout(grid)

        shares = QGridLayout()
        shares.setHorizontalSpacing(8)
        shares.setVerticalSpacing(3)
        self.bars: dict[str, ShareBar] = {}
        self.share_values: dict[str, QLabel] = {}
        self.gain_labels: dict[str, QLabel] = {}
        for row, letter in enumerate("PID"):
            name = QLabel(letter)
            name.setStyleSheet(f"color: {SHARE_COLORS[letter].name()}; font-weight: bold;")
            bar = ShareBar(SHARE_COLORS[letter])
            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setMinimumWidth(76)
            gain = QLabel("")
            gain.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            gain.setMinimumWidth(96)
            gain.setStyleSheet("color: #6a6a6a;")
            shares.addWidget(name, row, 0)
            shares.addWidget(bar, row, 1)
            shares.addWidget(value, row, 2)
            shares.addWidget(gain, row, 3)
            shares.setColumnStretch(1, 1)
            self.bars[letter] = bar
            self.share_values[letter] = value
            self.gain_labels[letter] = gain
        layout.addLayout(shares)

        self.output_label = QLabel("—")
        self.output_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output:"))
        output_row.addStretch()
        output_row.addWidget(self.output_label)
        layout.addLayout(output_row)

    # ------------------------------------------------------------ state --

    def refresh(self, state) -> None:
        """Read the step that was just computed. Nothing is calculated here."""
        loop, p, v, a = self.loop, state.p, state.v, state.a
        mode = p.get(loop.mode_parameter)
        active = mode is not None and int(mode) == loop.mode_value
        self.lamp.set_color(GREEN if active else GREY)
        self.state_label.setText("controlling" if active else "off")
        for widget in (*self.bars.values(), *self.share_values.values()):
            widget.setEnabled(active)

        for position, letter in enumerate("PID"):
            # A loop has as many gains as it has shares: the pH master is a
            # pure P controller and names one.
            gain = loop.gains[position] if position < len(loop.gains) else ""
            label = self.gain_labels[letter]
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setText(
                f"{tex_to_html(_gain_label(gain))} = {p[gain]:.4g}" if gain and gain in p else ""
            )

        if not active:
            for key in self.values:
                self.values[key].setText("—")
            for letter in "PID":
                self.share_values[letter].setText("—")
                self.bars[letter].set_value(0.0, 1.0)
            self.output_label.setText("—")
            return

        setpoint = p.get(loop.setpoint)
        measured = _series_value(v, loop.measurement, state.idx)
        self.values["setpoint"].setText(_number(setpoint, loop.unit))
        self.values["measurement"].setText(_number(measured, loop.unit))
        # Both numbers: the difference the operator sees, and the normalised
        # one the controller multiplies by K_P. Without the second, "P = e·K_P"
        # does not add up on screen.
        error = _auxiliary(a, loop.error, state.idx)
        raw = None if setpoint is None or measured is None else setpoint - measured
        self.values["error"].setText(
            f"{_number(raw, loop.unit)}"
            + (f"  <span style='color:#6a6a6a'>({error:+.4g})</span>" if error is not None else "")
        )
        self.values["error"].setTextFormat(Qt.TextFormat.RichText)

        shares = {
            letter: _auxiliary(a, key, state.idx)
            for letter, key in zip("PID", (loop.p_share, loop.i_share, loop.d_share), strict=True)
        }
        scale = max((abs(value) for value in shares.values() if value is not None), default=0.0)
        for letter, value in shares.items():
            self.share_values[letter].setText("—" if value is None else f"{value:+.4g}")
            self.bars[letter].set_value(value or 0.0, scale or 1.0)

        readings = []
        for name in loop.outputs:
            value = _series_value(v, name, state.idx)
            if value is None:
                value = _auxiliary(a, name, state.idx)
            readings.append(f"{name} = {_number(value, loop.output_unit)}")
        self.output_label.setText("   ".join(readings) or "—")


class ControllerView(QWidget):
    """Every loop the organism declares, in a scrolling grid of panels."""

    def __init__(self, loops, reservoirs: int = 1, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        heading = QLabel(
            "What each loop is doing right now. The bars are the three shares "
            "of the controller output against a common scale — a long integral "
            "bar next to a short proportional one is an integral winding up."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(8)
        area.setWidget(inner)
        layout.addWidget(area, 1)

        self.panels: list[LoopPanel] = []
        for loop in _expand(loops, reservoirs):
            panel = LoopPanel(loop)
            grid.addWidget(panel, len(self.panels) // COLUMNS, len(self.panels) % COLUMNS)
            self.panels.append(panel)
        for column in range(COLUMNS):
            grid.setColumnStretch(column, 1)
        grid.setRowStretch(grid.rowCount(), 1)

        if not self.panels:
            empty = QLabel("This organism does not describe its control loops.")
            layout.addWidget(empty, 0, Qt.AlignmentFlag.AlignTop)

    def refresh(self, state) -> None:
        for panel in self.panels:
            panel.refresh(state)


# ----------------------------------------------------------------- bits --


def _expand(loops, reservoirs: int) -> list:
    """One panel per loop — and one per reservoir where a loop has `{n}`."""
    expanded = []
    for loop in loops:
        if "{n}" in loop.name:
            expanded.extend(loop.resolve(number) for number in range(1, max(1, reservoirs) + 1))
        else:
            expanded.append(loop)
    return expanded


def _series_value(v, name: str, index: int):
    series = v.get(name) if name else None
    if series is None or index >= getattr(series, "size", 0):
        return None
    return float(series[index])


def _auxiliary(a, name: str, index: int):
    """A controller signal — some are scalars, some are series over the run.

    Told apart by `ndim`, not by `size`: a numpy float64 is a 0-dimensional
    array and answers `size == 1`, so every scalar share looked like a series
    of one element and read as empty at any index past the first.
    """
    if not name:
        return None
    value = a.get(name)
    if value is None:
        return None
    if getattr(value, "ndim", 0) > 0:
        return _series_value(a, name, index)
    return float(value)


def _number(value, unit: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.4g} {unit}".strip()


def _gain_label(name: str) -> str:
    """KP_agi becomes K_{P}. The suffix is the loop, and that is the title."""
    letter = name[1:2]
    return f"K_{{{letter}}}"

