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
    QPointF,
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

    Label on the left, switch on the right, and nothing else: the switch is
    grey when it is off and green when it is on, so a lamp next to it would
    say a second time what the switch already says. It is as wide as one field
    of the panel grid, not as wide as the panel.
    """

    toggled = Signal(bool)

    def __init__(
        self,
        label: str = "",
        *,
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
        self.switch.toggled.connect(self.toggled.emit)

    def is_checked(self) -> bool:
        return self.switch.isChecked()

    def set_checked(self, checked: bool) -> None:
        """Set the state without animating and without emitting `toggled`.

        Every caller of this is a load, and a load must not look like the
        operator moved something.
        """
        self.switch.set_state_now(checked)


class SegmentedControl(QWidget):
    """Joined keys, one lit — a dropdown that does not hide its options.

    Carries the same (text, value) pairs a QComboBox would, and answers to
    the same four calls, so `select_data` and the panels do not care which of
    the two they are holding.

    What it does that a dropdown cannot: when the keys do not fit side by
    side it puts them on a second row instead of hiding them. pO2 has five
    modes and a panel a third of the window wide; a control that showed all
    of them only in a wide window would be no better than the dropdown.
    """

    #: Emitted on a change, with the new index — the QComboBox signal name,
    #: because the panels connect to it without knowing what they have.
    currentIndexChanged = Signal(int)

    PADDING = 12
    HEIGHT = 28
    #: Between two rows of keys, when they do not fit on one.
    ROW_GAP = 4

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
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

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

    def _natural(self) -> list[float]:
        """How wide each key would like to be."""
        metrics = self.fontMetrics()
        return [metrics.horizontalAdvance(text) + 2 * self.PADDING for text, _ in self._items]

    def _rows(self, width: float | None = None) -> list[list[int]]:
        """The keys, grouped into the rows they fit on."""
        if not self._items:
            return []
        width = self.width() if width is None else width
        natural = self._natural()
        rows: list[list[int]] = [[]]
        used = 0.0
        for index, own in enumerate(natural):
            if rows[-1] and used + own > width:
                rows.append([])
                used = 0.0
            rows[-1].append(index)
            used += own
        return rows

    def _cells(self, width: float | None = None) -> dict[int, QRectF]:
        """Where every key sits. One pass, used by both painting and hit test."""
        width = self.width() if width is None else width
        natural = self._natural()
        cells: dict[int, QRectF] = {}
        for row, indices in enumerate(self._rows(width)):
            spare = (width - sum(natural[i] for i in indices)) / len(indices)
            left = 0.0
            top = row * (self.HEIGHT + self.ROW_GAP)
            for index in indices:
                own = natural[index] + spare
                cells[index] = QRectF(left, top, own, self.HEIGHT)
                left += own
        return cells

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(max(sum(self._natural()), 60), self.heightForWidth(self.width()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        # One key wide. Below that there is nothing left to wrap.
        return QSize(int(max(self._natural(), default=60)), self.HEIGHT)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API
        rows = max(1, len(self._rows(width)))
        return rows * self.HEIGHT + (rows - 1) * self.ROW_GAP

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # heightForWidth is not honoured inside a QHBoxLayout, and a second
        # row of keys drawn outside the widget is a row nobody can press. So
        # the height is set from the width, here, where the width is known.
        wanted = self.heightForWidth(self.width())
        if self.height() != wanted:
            self.setFixedHeight(wanted)

    def _segment_at(self, x: float, y: float) -> int:
        for index, cell in self._cells().items():
            if cell.contains(x, y):
                return index
        # Past the end of a row: the nearest key on that row.
        row = int(y // (self.HEIGHT + self.ROW_GAP))
        rows = self._rows()
        if 0 <= row < len(rows):
            return rows[row][-1] if x > 0 else rows[row][0]
        return self._index

    # ------------------------------------------------------------- input --

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._items:
            position = event.position()
            self.setCurrentIndex(self._segment_at(position.x(), position.y()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        position = event.position()
        hover = self._segment_at(position.x(), position.y()) if self._items else -1
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
        ground = QColor(0xF4, 0xF4, 0xF4) if live else QColor(0xF8, 0xF8, 0xF8)
        border = QPen(QColor(0xAD, 0xAD, 0xAD) if live else QColor(0xD8, 0xD8, 0xD8), 1)

        cells = self._cells()
        for row, indices in enumerate(self._rows()):
            top = row * (self.HEIGHT + self.ROW_GAP)
            outer = QRectF(0.5, top + 0.5, self.width() - 1, self.HEIGHT - 1)
            painter.setBrush(ground)
            painter.setPen(border)
            painter.drawRoundedRect(outer, 4, 4)

            last = indices[-1]
            for index in indices:
                cell = cells[index]
                text = self._items[index][0]
                if index == self._index:
                    path = QPainterPath()
                    path.addRoundedRect(
                        cell.adjusted(
                            2 if index == indices[0] else 1.5,
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
                elif index != indices[0] and index - 1 != self._index:
                    # A hairline between two unlit keys, so they read as separate.
                    painter.setPen(QPen(QColor(0xCB, 0xCB, 0xCB), 1))
                    edge = cell.height() * 0.22
                    painter.drawLine(
                        QPointF(cell.left(), cell.top() + edge),
                        QPointF(cell.left(), cell.bottom() - edge),
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
        # Two columns, always — the setpoint keeps the width of the left one
        # whether or not there is a measured value beside it. Without this a
        # lone setpoint took the whole panel and the fields of one panel came
        # out in two different widths.
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

        self.setpoint_caption = QLabel(tex_to_html(setpoint_label))
        self.setpoint_caption.setTextFormat(Qt.TextFormat.RichText)
        self.setpoint_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.setpoint_caption, 0, 0)

        self.setpoint = QDoubleSpinBox()
        self.setpoint.setDecimals(decimals)
        self.setpoint.setRange(-1e9, 1e9)
        self.setpoint.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setpoint.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setpoint.valueChanged.connect(self.setpoint_changed.emit)
        _take_what_you_get(self.setpoint)
        layout.addWidget(self.setpoint, 1, 0)

        self.actual: QLineEdit | None = None
        self.actual_caption: QLabel | None = None
        if actual_label:
            self.actual_caption = QLabel(tex_to_html(actual_label))
            self.actual_caption.setTextFormat(Qt.TextFormat.RichText)
            self.actual_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.actual_caption, 0, 1)

            self.actual = QLineEdit()
            self.actual.setReadOnly(True)
            self.actual.setAlignment(Qt.AlignmentFlag.AlignRight)
            _take_what_you_get(self.actual)
            layout.addWidget(self.actual, 1, 1)

    def set_labels(self, setpoint_label: str, actual_label: str = "") -> None:
        """Rename the row. The feed panel does this when the reservoir changes."""
        self.setpoint_caption.setText(tex_to_html(setpoint_label))
        if self.actual_caption is not None:
            self.actual_caption.setText(tex_to_html(actual_label))

    def set_actual(self, value: float) -> None:
        if self.actual is not None:
            self.actual.setText(f"{value:.{self.decimals}f}")
