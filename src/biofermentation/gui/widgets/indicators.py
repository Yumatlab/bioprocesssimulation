"""Small widgets the control surface repeats (plan section 5.1).

A status lamp, a sliding off/on switch and a segmented selector. MATLAB has
uilamp, a rocker switch and a dropdown built in; Qt has none of the first two
and its dropdown hides its own options, so they are drawn here. Small enough
to keep, and having them as widgets means the panels stay readable.

The state always lives in a Qt button, never in a repaint: focus, keyboard
and the accessibility tree come from Qt, and only the drawing is ours.
"""

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

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

#: The switch and the selector share these, so on means the same green
#: everywhere and a selection the same blue as the rest of the surface.
SWITCH_ON = QColor(0x2A, 0xA8, 0x4A)
SWITCH_OFF = QColor(0xC4, 0xC7, 0xCB)
SWITCH_OFF_DISABLED = QColor(0xE4, 0xE4, 0xE4)
SWITCH_ON_DISABLED = QColor(0xC9, 0xDE, 0xCD)
ACCENT = QColor(0x2F, 0x7F, 0xD1)
TEXT = QColor(0x4A, 0x4A, 0x4A)
MUTED = QColor(0x9A, 0x9A, 0x9A)


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


class SlideSwitch(QAbstractButton):
    """A sliding off/on switch: the knob travels, the track turns green.

    One state, one colour, one movement — readable across a room, which a
    tick box in a list of six is not. The travel is a property so Qt can
    animate it; the state itself is the button's, not the animation's.
    """

    TRACK_W = 46
    TRACK_H = 24
    KNOB = 20
    DURATION_MS = 140

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(QSize(self.TRACK_W, self.TRACK_H))
        self._travel = 0.0
        self._animation = QPropertyAnimation(self, b"travel", self)
        self._animation.setDuration(self.DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.toggled.connect(self._animate)

    # The knob position, 0 at Off and 1 at On. A Property so QPropertyAnimation
    # can drive it; nothing else should write it.
    def _get_travel(self) -> float:
        return self._travel

    def _set_travel(self, value: float) -> None:
        self._travel = value
        self.update()

    travel = Property(float, _get_travel, _set_travel)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._travel)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def set_state_now(self, checked: bool) -> None:
        """Take the state without animating and without reporting it.

        For loading a parameter set: a switch that slides over on its own
        while a project opens looks like somebody threw it.
        """
        self.blockSignals(True)
        self.setChecked(bool(checked))
        self.blockSignals(False)
        self._animation.stop()
        self._set_travel(1.0 if checked else 0.0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        live = self.isEnabled()

        off = SWITCH_OFF if live else SWITCH_OFF_DISABLED
        on = SWITCH_ON if live else SWITCH_ON_DISABLED
        track = QColor(
            round(off.red() + (on.red() - off.red()) * self._travel),
            round(off.green() + (on.green() - off.green()) * self._travel),
            round(off.blue() + (on.blue() - off.blue()) * self._travel),
        )
        rect = QRectF(0.5, 0.5, self.TRACK_W - 1, self.TRACK_H - 1)
        painter.setPen(QPen(track.darker(120), 1))
        painter.setBrush(track)
        painter.drawRoundedRect(rect, self.TRACK_H / 2, self.TRACK_H / 2)

        if self.hasFocus():
            painter.setPen(QPen(ACCENT, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), 13, 13)

        travel = self.TRACK_W - self.KNOB - 4
        knob = QRectF(2 + travel * self._travel, 2, self.KNOB, self.KNOB)
        gradient = QLinearGradient(knob.topLeft(), knob.bottomLeft())
        gradient.setColorAt(0.0, QColor(0xFF, 0xFF, 0xFF))
        gradient.setColorAt(1.0, QColor(0xEC, 0xEC, 0xEC) if live else QColor(0xF4, 0xF4, 0xF4))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawEllipse(knob)


class ToggleSwitch(QWidget):
    """A labelled slide switch, the way a controller panel shows a flag.

    Label on the left, switch on the right, optionally a lamp for a state the
    switch does not carry itself — the feed switch says what the operator
    asked for, the lamp whether the reservoir is actually feeding.
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

        self.switch = SlideSwitch()
        layout.addWidget(self.switch)

        self.lamp = StatusLamp(RED, diameter=11) if lamp else None
        if self.lamp is not None:
            layout.addWidget(self.lamp)

        self.switch.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        if self.lamp is not None:
            self.lamp.set_on(checked)
        self.toggled.emit(checked)

    def is_checked(self) -> bool:
        return self.switch.isChecked()

    def set_checked(self, checked: bool) -> None:
        """Set the state without animating and without emitting `toggled`.

        Every caller of this is a load, and a load must not look like the
        operator moved something.
        """
        self.switch.set_state_now(checked)
        if self.lamp is not None:
            self.lamp.set_on(bool(checked))


class SegmentedControl(QWidget):
    """Joined keys, one lit — a dropdown that does not hide its options.

    Carries the same (text, value) pairs a QComboBox would, and answers to
    the same four calls, so `select_data` and the panels do not care which of
    the two they are holding.
    """

    #: Emitted on a change, with the new index — the QComboBox signal name,
    #: because the panels connect to it without knowing what they have.
    currentIndexChanged = Signal(int)

    PADDING = 14
    HEIGHT = 28

    def __init__(self, parent: QWidget | None = None, *, accent: QColor = ACCENT):
        super().__init__(parent)
        self._items: list[tuple[str, object]] = []
        self._index = -1
        self._hover = -1
        self.accent = accent
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # ------------------------------------------------ the QComboBox part --

    def addItem(self, text: str, value=None) -> None:  # noqa: N802 - Qt API
        self._items.append((text, value))
        if self._index < 0:
            self._index = 0
        self.updateGeometry()
        self.update()

    def count(self) -> int:
        return len(self._items)

    def itemText(self, index: int) -> str:  # noqa: N802 - Qt API
        return self._items[index][0]

    def findData(self, value) -> int:  # noqa: N802 - Qt API
        for index, (_, data) in enumerate(self._items):
            if data == value:
                return index
        return -1

    def currentIndex(self) -> int:  # noqa: N802 - Qt API
        return self._index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt API
        if not self._items or index == self._index:
            return
        self._index = max(0, min(index, len(self._items) - 1))
        self.update()
        self.currentIndexChanged.emit(self._index)

    def currentData(self):  # noqa: N802 - Qt API
        return self._items[self._index][1] if 0 <= self._index < len(self._items) else None

    def currentText(self) -> str:  # noqa: N802 - Qt API
        return self._items[self._index][0] if 0 <= self._index < len(self._items) else ""

    # ------------------------------------------------------------ layout --

    def _widths(self) -> list[float]:
        """Segment widths: each as wide as its text, the rest shared out."""
        metrics = self.fontMetrics()
        natural = [metrics.horizontalAdvance(text) + 2 * self.PADDING for text, _ in self._items]
        if not natural:
            return []
        spare = (self.width() - sum(natural)) / len(natural)
        return [width + spare for width in natural]

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        metrics = self.fontMetrics()
        width = sum(metrics.horizontalAdvance(text) + 2 * self.PADDING for text, _ in self._items)
        return QSize(max(width, 60), self.HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    def _segment_at(self, x: float) -> int:
        left = 0.0
        for index, width in enumerate(self._widths()):
            if x < left + width:
                return index
            left += width
        return len(self._items) - 1

    # ------------------------------------------------------------- input --

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._items:
            self.setCurrentIndex(self._segment_at(event.position().x()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        hover = self._segment_at(event.position().x()) if self._items else -1
        if hover != self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._hover = -1
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.setCurrentIndex(self._index - 1)
        elif event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.setCurrentIndex(self._index + 1)
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------ paint --

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        live = self.isEnabled()

        outer = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setBrush(QColor(0xF4, 0xF4, 0xF4) if live else QColor(0xF8, 0xF8, 0xF8))
        painter.setPen(QPen(QColor(0xAD, 0xAD, 0xAD) if live else QColor(0xD8, 0xD8, 0xD8), 1))
        painter.drawRoundedRect(outer, 4, 4)

        widths = self._widths()
        last = len(self._items) - 1
        left = 0.0
        for index, (text, _) in enumerate(self._items):
            cell = QRectF(left, 0, widths[index], self.height())
            left += widths[index]

            if index == self._index:
                path = QPainterPath()
                path.addRoundedRect(
                    cell.adjusted(
                        2 if index == 0 else 1.5,
                        2,
                        -2 if index == last else -1.5,
                        -2,
                    ),
                    3,
                    3,
                )
                painter.setBrush(self.accent if live else QColor(0xDD, 0xDD, 0xDD))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(path)
            elif index == self._hover and live:
                path = QPainterPath()
                path.addRoundedRect(cell.adjusted(2, 2, -2, -2), 3, 3)
                painter.setBrush(QColor(0xE3, 0xEF, 0xFF))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(path)
            elif index and index - 1 != self._index:
                # A hairline between two unlit keys, so they read as separate.
                painter.setPen(QPen(QColor(0xCB, 0xCB, 0xCB), 1))
                top = cell.top() + cell.height() * 0.22
                painter.drawLine(
                    QRectF(cell.left(), top, 0, cell.height() * 0.56).topLeft(),
                    QRectF(cell.left(), top, 0, cell.height() * 0.56).bottomLeft(),
                )

            font = QFont(self.font())
            font.setBold(index == self._index)
            painter.setFont(font)
            if not live:
                painter.setPen(MUTED)
            elif index == self._index:
                painter.setPen(QColor(0xFF, 0xFF, 0xFF))
            else:
                painter.setPen(TEXT)
            painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, text)

        if self.hasFocus() and live:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ACCENT, 1.5))
            painter.drawRoundedRect(outer.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)


#: How narrow a value field may become before it stops being readable.
FIELD_MIN_WIDTH = 72


def _take_what_you_get(widget) -> None:
    """Let a field have whatever width the panel can spare.

    A QDoubleSpinBox sizes itself to the widest text its range allows, and
    these accept plus or minus a billion — two of them side by side asked for
    264 px, five panels of them for a 1600 px window. Ignored means the layout
    goes by the minimum below instead of by that hint.
    """
    from PySide6.QtWidgets import QSizePolicy

    widget.setMinimumWidth(FIELD_MIN_WIDTH)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)


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
        _take_what_you_get(self.setpoint)
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
            _take_what_you_get(self.actual)
            layout.addWidget(self.actual, 1, 1)

    def set_actual(self, value: float) -> None:
        if self.actual is not None:
            self.actual.setText(f"{value:.{self.decimals}f}")
