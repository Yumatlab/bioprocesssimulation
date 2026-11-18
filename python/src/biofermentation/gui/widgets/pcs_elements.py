"""Building blocks of the PCS tab — PCS plan, phase 1.

A pump or valve, a reservoir, the reactor and a pipe. Each one on its own,
without a window and without a simulation; the tab that puts them together on
a sheet is gui/widgets/pcs_view.py (phase 3), what they are wired to is
gui/pcs_specs.py, where they sit is resources/layouts/pcs.yaml.

The symbols follow the project's R&I scheme (matlab/RI.drawio, symbols of
DIN EN ISO 10628-2): pumps for everything the model meters as a pump rate,
control valves on the gases, bottles with a level mark for the reservoirs, a
vessel with a dished bottom, stirrer and sparger for the reactor.

The colours follow the idea of ISA-101 (decision of 16.11.2026, variant b):
equipment is grey, its state is its shape — filled is running or open,
hollow is stopped or closed — and saturated colour is kept for alarms. A live
pipe gets a muted colour for its medium; an idle one stays grey.

Same rules as the other drawn controls (indicators.py):

- The state of anything operable lives in a Qt button. A ValveButton is a
  QAbstractButton, so focus, keyboard, click() and the accessibility tree
  come from Qt and only the drawing is ours.
- Colour is never the only sign: fill, width, arrow, frame and letter carry
  the same information.
- No element asks for a width of its own. Text that does not fit is elided.
"""

import math
from itertools import pairwise

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QWidget

from ..pcs_specs import MEDIA, SYMBOLS
from .indicators import ACCENT, ALARM_COLORS, MUTED, TEXT

ALARM_LEVELS = (None, "warning", "alarm")

#: Equipment: outline, and the fill of anything running or open.
EQUIPMENT = QColor(0x4A, 0x4A, 0x4A)
#: Equipment a controller drives: the same shapes, paler.
EQUIPMENT_LOCKED = MUTED
WHITE = QColor(0xFF, 0xFF, 0xFF)
LIQUID = QColor(0xC3, 0xCF, 0xDA)
#: A dense culture, and a broth full of a green product (GFP).
BROTH_DENSE = QColor(0xD9, 0xC6, 0x9C)
BROTH_PRODUCT = QColor(0xA9, 0xD4, 0x7C)

#: How fast the impeller is drawn turning, in turns per second. A symbol,
#: not the speed: 400 rpm drawn truly would be a blur.
IMPELLER_TURNS = 0.8

#: How far a turning stirrer swirls the bubbles sideways, as a share of the
#: width of the gas ring.
BUBBLE_SWIRL = 0.45

#: The bubbles above the sparger: three kinds, so that the gas does not march
#: in step. Per kind: where across the ring it rises (share of its width),
#: how fast (rises per second), its radius, how far it sways, how many.
BUBBLE_STREAMS = (
    (-0.32, 0.55, 1.6, 1.5, 4),  # small and quick, nearly straight
    (0.02, 0.35, 2.4, 4.0, 3),  # medium, swaying
    (0.34, 0.22, 3.2, 2.5, 2),  # large and slow
)

#: The colour of a live pipe, by what it carries — muted, so that no medium
#: can be mistaken for an alarm (a test keeps the saturation low). One per
#: medium in pcs_specs.MEDIA.
MEDIUM_COLORS = {
    "feed": QColor(0x8C, 0x7E, 0x5C),
    "acid": QColor(0x8A, 0x6E, 0x86),
    "base": QColor(0x5E, 0x7A, 0x9C),
    "antifoam": QColor(0x6A, 0x94, 0x8E),
    "harvest": QColor(0x7D, 0x6E, 0x60),
    "gas": QColor(0x7C, 0x9F, 0xBA),
    "coolant": QColor(0x4E, 0x6D, 0x8C),
    "heating": QColor(0x9A, 0x7A, 0x6A),
}

PIPE_LIVE_WIDTH = 4.0
PIPE_IDLE_WIDTH = 1.5
PIPE_IDLE = QColor(0xB8, 0xBB, 0xBF)
ARROW_SIZE = 7.0

#: The drawn size of each symbol, without the margin around it.
SYMBOL_SIZES = {
    "pump": QSize(26, 26),
    "valve": QSize(28, 18),
    "control_valve": QSize(28, 30),
    "motor": QSize(28, 28),  # a little larger than the pump: it carries a letter
}

#: Height of the valve part of a control valve; stem and actuator sit above.
CONTROL_VALVE_BODY = 18

#: Room around a symbol for the alarm badge and the automatic tag.
MARGIN = 5
#: Share of the reactor kept free above VLmax, so that the max mark is a line
#: on the vessel and not its lid.
HEADSPACE = 0.12


# ------------------------------------------------------------ alarms --


def check_alarm_level(level):
    """The level, if it is one the elements know."""
    if level not in ALARM_LEVELS:
        raise ValueError(f"an alarm level is None, 'warning' or 'alarm', not {level!r}")
    return level


def draw_alarm(painter: QPainter, rect: QRectF, level) -> None:
    """Frame and badge for an element in alarm. Nothing for None.

    A warning gets a dashed frame, an alarm a solid one, and both a small
    triangle with an exclamation mark in the top right corner.
    """
    if level is None:
        return
    color = ALARM_COLORS[level]
    painter.save()

    frame = QPen(color, 2.0)
    if level == "warning":
        frame.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(frame)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)

    size = 10.0
    right = rect.right()
    top = rect.top()
    middle = right - size / 2
    triangle = QPolygonF(
        [
            QPointF(middle, top),
            QPointF(right, top + size),
            QPointF(right - size, top + size),
        ]
    )
    painter.setPen(QPen(color.darker(130), 1))
    painter.setBrush(color)
    painter.drawPolygon(triangle)
    painter.setPen(QPen(WHITE, 1.4))
    painter.drawLine(QPointF(middle, top + 3.5), QPointF(middle, top + size - 3.5))
    painter.drawPoint(QPointF(middle, top + size - 1.8))

    painter.restore()


# ------------------------------------------------------------ levels --


def fill_fraction(volume, maximum) -> float | None:
    """Volume as a share of its maximum, held between 0 and 1.

    None when there is nothing to divide by: no maximum, a maximum of zero,
    or a value that is not a number. An empty gauge would claim the vessel is
    empty; no level claims nothing.
    """
    if volume is None or maximum is None:
        return None
    if not math.isfinite(volume) or not math.isfinite(maximum) or maximum <= 0:
        return None
    return min(max(volume / maximum, 0.0), 1.0)


def level_text(volume, maximum, unit: str) -> str:
    """Volume and share, e.g. "3.2 l · 64 %". The share is the true one.

    Three significant digits and at most two decimals: under a narrow
    bottle "5.00 l · 100 %" and "0.787 l · 79 %" were cut off. The exact
    volume is in the Variable Pool.
    """
    if fill_fraction(volume, maximum) is None:
        return ""
    share = volume / maximum * 100
    return f"{round(volume, 2):.3g} {unit} · {share:.0f} %"


def volume_text(volume: float) -> str:
    """A volume as the level text writes it: three digits, two decimals at most.

    Without an exponent: 1234.5 l is "1235", not "1.23e+03".
    """
    text = f"{round(volume, 2):.3g}"
    if "e" in text:
        text = f"{volume:.0f}"
    return text


def _elided(widget: QWidget, text: str, width: float) -> str:
    return widget.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(width))


def _paint_caption(widget: QWidget, painter: QPainter, area: QRectF, lines: list[str]) -> None:
    """Name and numbers under a vessel, one line each, elided to fit."""
    height = widget.fontMetrics().height()
    for index, (text, color) in enumerate(zip(lines, (TEXT, MUTED), strict=False)):
        row = QRectF(area.left(), area.top() + index * height, area.width(), height)
        painter.setPen(color)
        painter.drawText(row, Qt.AlignmentFlag.AlignCenter, _elided(widget, text, area.width()))


def _paint_surface_mark(painter: QPainter, x: float, y: float) -> None:
    """The ▽ that marks a liquid surface in an R&I scheme, tip on the surface."""
    half = 4.0
    mark = QPolygonF([QPointF(x - half, y - 7), QPointF(x + half, y - 7), QPointF(x, y)])
    painter.setPen(QPen(EQUIPMENT, 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(mark)


def broth_color(biomass: float, product: float) -> QColor:
    """The colour of the broth: beige with the cells, green with the product.

    Both arguments are shares between 0 and 1. Clear medium is LIQUID; a
    dense culture is BROTH_DENSE; a coloured product (GFP) shifts either
    towards BROTH_PRODUCT. All three are muted — saturated colour stays with
    the alarms.
    """
    biomass = min(max(biomass, 0.0), 1.0)
    product = min(max(product, 0.0), 1.0)

    def mix(first: QColor, second: QColor, share: float) -> QColor:
        return QColor(
            round(first.red() + (second.red() - first.red()) * share),
            round(first.green() + (second.green() - first.green()) * share),
            round(first.blue() + (second.blue() - first.blue()) * share),
        )

    return mix(mix(LIQUID, BROTH_DENSE, biomass), BROTH_PRODUCT, product * 0.7)


def _fill(
    painter: QPainter, vessel: QPainterPath, area: QRectF, level: float, color: QColor | None = None
) -> float:
    """Liquid from the bottom of `area` up to `level`, inside the vessel.

    Returns the height of the surface in pixels, for the level mark.
    """
    if color is None:
        color = LIQUID
    surface = area.bottom() - area.height() * level
    liquid = QRectF(area.left(), surface, area.width(), area.bottom() - surface)
    painter.save()
    painter.setClipPath(vessel)
    painter.fillRect(liquid, color)
    painter.restore()
    return surface


# ------------------------------------------------- pumps and valves --


class ValveButton(QAbstractButton):
    """An operable element on the sheet. Checked is open or running: flag 1.

    Drawn as one of pcs_specs.SYMBOLS: a pump (circle with a triangle towards
    its outlet), a block valve (two triangles), a control valve (a block
    valve with a diaphragm actuator) or a motor (circle with an M). Running
    or open is filled dark, stopped or closed is hollow.

    A controller can take it (`set_locked(owner)`): it is then disabled,
    paler, tagged "A" for automatic, and its tooltip names the owner.
    Whoever loads a locked element shows the flow, not the flag, through
    `set_state_now`.
    """

    def __init__(self, label: str, symbol: str = "valve", parent: QWidget | None = None):
        super().__init__(parent)
        if symbol not in SYMBOLS:
            raise ValueError(f"unknown symbol {symbol!r} — the symbols are: {', '.join(SYMBOLS)}")
        self.label = label
        self.symbol = symbol
        self._owner = None
        self._alarm = None
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(label)
        self.setToolTip(label)
        inner = SYMBOL_SIZES[symbol]
        self.setFixedSize(QSize(inner.width() + 2 * MARGIN, inner.height() + 2 * MARGIN))

    def line_point(self) -> QPointF:
        """Where the pipe runs through the symbol, in widget pixels.

        The middle of the widget for most symbols. A control valve carries its
        stem and actuator above the valve, so its line runs through the lower
        part — the sheet puts this point, not the widget's centre, on the pipe.
        """
        rect = QRectF(self.rect())
        if self.symbol == "control_valve":
            return QPointF(rect.center().x(), rect.bottom() - MARGIN - CONTROL_VALVE_BODY / 2)
        return rect.center()

    def symbol_rect(self) -> QRectF:
        """The part of the widget the symbol itself covers, in widget pixels.

        The sheet leaves the pipe out here: a thick live line showed through
        the waist of a valve and behind a hollow pump.
        """
        body = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        if self.symbol == "control_valve":
            return QRectF(
                body.left(), body.bottom() - CONTROL_VALVE_BODY, body.width(), CONTROL_VALVE_BODY
            )
        return body

    def set_state_now(self, checked: bool) -> None:
        """Take the state without reporting it — for loading, not for clicks."""
        self.blockSignals(True)
        self.setChecked(bool(checked))
        self.blockSignals(False)
        self.update()

    def set_locked(self, owner: str | None) -> None:
        """Hand the element to a controller, or back to the operator with None."""
        self._owner = owner
        self.setEnabled(owner is None)
        if owner is None:
            self.setToolTip(self.label)
        else:
            self.setToolTip(f"{self.label} — controlled by {owner}")

    def owner(self) -> str | None:
        return self._owner

    def set_alarm(self, level) -> None:
        self._alarm = check_alarm_level(level)
        self.update()

    def alarm(self):
        return self._alarm

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        body = rect.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

        line = EQUIPMENT if self.isEnabled() else EQUIPMENT_LOCKED
        fill = WHITE
        if self.isChecked():
            fill = line
        painter.setPen(QPen(line, 1.5))
        painter.setBrush(fill)

        if self.symbol == "pump":
            self._paint_pump(painter, body, fill, line)
        elif self.symbol == "motor":
            self._paint_motor(painter, body, fill, line)
        elif self.symbol == "control_valve":
            self._paint_control_valve(painter, body)
        else:
            self._paint_valve(painter, body)

        if self.hasFocus():
            painter.setPen(QPen(ACCENT, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
        if self._owner is not None:
            self._paint_automatic_tag(painter, rect)
        draw_alarm(painter, rect, self._alarm)

    @staticmethod
    def _contrast(fill: QColor, line: QColor) -> QColor:
        """What to draw on top of the body: white on a filled one."""
        if fill == WHITE:
            return line
        return WHITE

    def _paint_pump(self, painter: QPainter, body: QRectF, fill: QColor, line: QColor) -> None:
        painter.drawEllipse(body)
        # The triangle points to the outlet, which is to the right.
        centre = body.center()
        radius = body.width() / 2
        corners = [
            QPointF(
                centre.x() + radius * math.cos(math.radians(angle)),
                centre.y() - radius * math.sin(math.radians(angle)),
            )
            for angle in (0, 120, 240)
        ]
        painter.setPen(QPen(self._contrast(fill, line), 1.3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF(corners))

    def _paint_motor(self, painter: QPainter, body: QRectF, fill: QColor, line: QColor) -> None:
        painter.drawEllipse(body)
        # The letter as a shape, moved so that the middle of its outline sits
        # on the middle of the circle. Centring text by its font metrics left
        # it visibly off: they leave room for accents and descenders, and
        # differ between platforms.
        font = painter.font()
        font.setPixelSize(round(body.height() * 0.55))
        font.setBold(True)
        letter = QPainterPath()
        letter.addText(0, 0, font, "M")
        centre = body.center()
        middle = letter.boundingRect().center()
        letter.translate(centre.x() - middle.x(), centre.y() - middle.y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._contrast(fill, line))
        painter.drawPath(letter)

    @staticmethod
    def _bow_tie(painter: QPainter, body: QRectF) -> None:
        centre = body.center()
        painter.drawPolygon(QPolygonF([body.topLeft(), centre, body.bottomLeft()]))
        painter.drawPolygon(QPolygonF([body.topRight(), centre, body.bottomRight()]))

    def _paint_valve(self, painter: QPainter, body: QRectF) -> None:
        self._bow_tie(painter, body)

    def _paint_control_valve(self, painter: QPainter, body: QRectF) -> None:
        # Lower part: the valve. Upper part: stem and diaphragm actuator.
        valve = QRectF(
            body.left(), body.bottom() - CONTROL_VALVE_BODY, body.width(), CONTROL_VALVE_BODY
        )
        self._bow_tie(painter, valve)
        x = valve.center().x()
        dome_top = body.top()
        dome_bottom = body.top() + 7
        painter.drawLine(QPointF(x, valve.center().y()), QPointF(x, dome_bottom))
        dome = QPainterPath()
        dome.moveTo(x - 7, dome_bottom)
        dome.arcTo(QRectF(x - 7, dome_top, 14, 14), 180, -180)
        dome.closeSubpath()
        painter.drawPath(dome)

    def _paint_automatic_tag(self, painter: QPainter, rect: QRectF) -> None:
        """A small "A" in the bottom left corner: a controller has this one."""
        tag = QRectF(rect.left(), rect.bottom() - 11, 11, 11)
        painter.setPen(QPen(EQUIPMENT_LOCKED, 1))
        painter.setBrush(WHITE)
        painter.drawRoundedRect(tag, 2, 2)
        font = painter.font()
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(EQUIPMENT)
        painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, "A")


# ------------------------------------------------------------- tanks --


class TankGauge(QWidget):
    """A reservoir: a bottle filled to its level, ▽ on the surface, name and
    numbers below.

    Without a maximum there is no level: the bottle stays empty and the
    second line blank — for the antifoam and harvest vessels, which have no
    volume series (decision 4).
    """

    def __init__(self, label: str, unit: str = "l", parent: QWidget | None = None):
        super().__init__(parent)
        self.label = label
        self.unit = unit
        self._level = None
        self._text = ""
        self._alarm = None
        self.setMinimumSize(QSize(56, 80))
        self.setToolTip(label)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(84, 120)

    def set_volume(self, volume, maximum) -> None:
        self._level = fill_fraction(volume, maximum)
        self._text = level_text(volume, maximum, self.unit)
        if self._level is None:
            self.setToolTip(self.label)
        else:
            self.setToolTip(f"{self.label}: {volume:.3f} of {maximum:.3f} {self.unit}")
        self.update()

    def set_collected(self, volume) -> None:
        """A vessel that collects without a capacity: the volume, no level.

        The harvest vessel. Its size is in no table, so a level would be a
        guess; what has gone into it is known exactly.
        """
        self._level = None
        self._text = "" if volume is None else f"{volume_text(volume)} {self.unit}"
        tip = self.label
        if volume is not None:
            tip = f"{self.label}: {volume:.3f} {self.unit} collected in total"
        self.setToolTip(tip)
        self.update()

    def level(self) -> float | None:
        return self._level

    def text(self) -> str:
        return self._text

    def set_alarm(self, level) -> None:
        self._alarm = check_alarm_level(level)
        self.update()

    def alarm(self):
        return self._alarm

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        caption_height = 2 * self.fontMetrics().height()
        caption = QRectF(rect.left(), rect.bottom() - caption_height, rect.width(), caption_height)
        body = QRectF(
            rect.left() + 10,
            rect.top() + 6,
            rect.width() - 20,
            caption.top() - rect.top() - 10,
        )

        # A bottle: walls, shoulders, neck.
        shoulder = body.top() + body.height() * 0.2
        neck = body.width() * 0.25
        centre = body.center().x()
        bottle = QPainterPath()
        bottle.moveTo(body.left(), body.bottom())
        bottle.lineTo(body.left(), shoulder)
        bottle.lineTo(centre - neck, body.top())
        bottle.lineTo(centre + neck, body.top())
        bottle.lineTo(body.right(), shoulder)
        bottle.lineTo(body.right(), body.bottom())
        bottle.closeSubpath()

        painter.setPen(QPen(EQUIPMENT, 1.5))
        painter.setBrush(WHITE)
        painter.drawPath(bottle)
        if self._level is not None:
            # Full is the shoulder, as drawn in the R&I scheme.
            working = QRectF(body.left(), shoulder, body.width(), body.bottom() - shoulder)
            surface = _fill(painter, bottle, working, self._level)
            painter.setPen(QPen(EQUIPMENT, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(bottle)
            _paint_surface_mark(painter, body.right() - 9, surface)

        _paint_caption(self, painter, caption, [self.label, self._text])
        draw_alarm(painter, rect, self._alarm)


class VesselWidget(QWidget):
    """The reactor: dished bottom, level against VLmax with marks for VLmin
    and VLmax, ▽ on the surface, stirrer and sparger near the bottom, and the
    outlet for the harvest at the lowest point of the dish, so that the
    vessel drains completely.

    The shaft runs up to the top edge of the widget, where the layout puts
    the motor (a ValveButton). The nozzle runs down to the bottom edge;
    `outlet()` says where, so that the sheet can start the harvest pipe
    there. Name and numbers sit either side of the nozzle. The impeller is
    filled while the stirrer turns.

    The min mark sits where VLmin / VLmax puts it — 5 of 11 l in the
    template projects, a little under half the height. It is data, not
    layout: it moves when VLmin is changed.
    """

    def __init__(self, label: str = "Reactor", unit: str = "l", parent: QWidget | None = None):
        super().__init__(parent)
        self.label = label
        self.unit = unit
        self._level = None
        self._minimum = None
        self._text = ""
        self._stirring = False
        self._gassing = False
        self._draining = False
        #: Where the dashes of the gas flow stand on the lance (draw_pipe's
        #: `travel`), None for none.
        self._flow_travel: float | None = None
        #: How far the impeller has turned, in turns.
        self._turn = 0.0
        #: The media flowing through the jacket right now ("coolant",
        #: "heating"); empty: the jacket stands.
        self._jacket: tuple[str, ...] = ()
        self._broth = LIQUID
        self._bubble_time = 0.0
        self._alarm = None
        self.setMinimumSize(QSize(90, 130))
        self.setToolTip(label)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(180, 230)

    def set_volume(self, volume, maximum, minimum=None) -> None:
        self._level = fill_fraction(volume, maximum)
        self._minimum = fill_fraction(minimum, maximum)
        self._text = level_text(volume, maximum, self.unit)
        self.update()

    def level(self) -> float | None:
        return self._level

    def minimum_mark(self) -> float | None:
        return self._minimum

    def text(self) -> str:
        return self._text

    def set_stirring(self, running: bool) -> None:
        self._stirring = bool(running)
        self.update()

    def stirring(self) -> bool:
        return self._stirring

    def set_gassing(self, flowing: bool) -> None:
        """Gas flows in: the lance is drawn live and bubbles rise."""
        self._gassing = bool(flowing)
        self.update()

    def gassing(self) -> bool:
        return self._gassing

    def set_draining(self, flowing: bool) -> None:
        """Harvest flows out: the outlet nozzle is drawn live."""
        self._draining = bool(flowing)
        self.update()

    def draining(self) -> bool:
        return self._draining

    def set_broth(self, biomass: float, product: float = 0.0) -> None:
        """Colour the liquid by cell density and product, both as shares 0 to 1."""
        self._broth = broth_color(biomass, product)
        self.update()

    def broth(self) -> QColor:
        return self._broth

    def advance_bubbles(self, seconds: float) -> None:
        """Move the bubbles on. Called by the sheet's timer while gas flows."""
        self._bubble_time += seconds
        self.update()

    def advance_stirrer(self, seconds: float) -> None:
        """Turn the impeller on. Called by the sheet's timer while it stirs."""
        self._turn += IMPELLER_TURNS * seconds
        self.update()

    def turn(self) -> float:
        return self._turn

    def set_jacket(self, media) -> None:
        """What flows through the double jacket: coolant, heating, both or nothing."""
        self._jacket = tuple(media)
        self.update()

    def jacket(self) -> tuple[str, ...]:
        return self._jacket

    #: Width of the double jacket on the right wall, in pixels. It lies in the
    #: margin of the widget (10 px), so the cooling and heating pipes, painted
    #: beneath the vessel, end on its outer wall.
    JACKET_WIDTH = 9
    #: Where the jacket runs along the wall, as shares of the vessel's height
    #: from its top: clear of the lid and of the dish. The cooling and heating
    #: pipes of the shipped layout meet the wall at 0.24 to 0.29 and 0.63 to
    #: 0.66 (measured at 700 to 1600 px).
    JACKET_RANGE = (0.16, 0.76)
    #: How much shorter the outer wall is than the inner one at each end, in
    #: pixels: the slanted ends make the jacket a flat trapezoid.
    JACKET_SLANT = 7.0

    def jacket_polygon(self) -> QPolygonF:
        """The jacket in widget pixels: long side on the vessel wall, short outside."""
        body, _, _ = self._geometry()
        top = body.top() + body.height() * self.JACKET_RANGE[0]
        bottom = body.top() + body.height() * self.JACKET_RANGE[1]
        inner, outer = body.right(), body.right() + self.JACKET_WIDTH
        return QPolygonF(
            [
                QPointF(inner, top),
                QPointF(outer, top + self.JACKET_SLANT),
                QPointF(outer, bottom - self.JACKET_SLANT),
                QPointF(inner, bottom),
            ]
        )

    def jacket_span(self) -> QRectF:
        """The straight outer wall of the jacket, where the pipes come in."""
        corners = self.jacket_polygon()
        top, bottom = corners[1].y(), corners[2].y()
        return QRectF(corners[0].x(), top, self.JACKET_WIDTH, bottom - top)

    def _paint_jacket(self, painter: QPainter) -> None:
        """The double jacket on the right: a second wall, filled while it flows.

        Coolant and heating water are drawn lighter than their pipes, as the
        liquid in the reactor is lighter than the lines; both at once (by hand)
        share the colour half and half. The inner side is the vessel wall,
        drawn with the vessel; here only the slanted ends and the outer wall.
        """
        corners = self.jacket_polygon()
        colors = [MEDIUM_COLORS[medium].lighter(150) for medium in self._jacket]
        fill = WHITE
        if len(colors) == 1:
            fill = colors[0]
        elif colors:
            first, second = colors[0], colors[1]
            fill = QColor(
                (first.red() + second.red()) // 2,
                (first.green() + second.green()) // 2,
                (first.blue() + second.blue()) // 2,
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPolygon(corners)
        pen = QPen(EQUIPMENT, 2.0)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF([corners[0], corners[1], corners[2], corners[3]]))

    def set_flow_travel(self, travel: float | None) -> None:
        """Carry the dashes of the aeration pipe on along the lance to the ring.

        `travel` is the pipe's own, less its length: a dash leaving the end of
        the pipe enters the lance at the same moment.
        """
        self._flow_travel = travel
        self.update()

    def bubbles(self, ring_x: float, ring_y: float, ring_width: float, surface: float):
        """Centre and radius of every bubble between the ring and the surface."""
        rise = ring_y - 4 - surface
        if rise <= 8:
            return []
        found = []
        for across, speed, radius, sway, count in BUBBLE_STREAMS:
            for number in range(count):
                share = (self._bubble_time * speed + number / count) % 1.0
                wobble = math.sin(2 * math.pi * (2 * share + 0.37 * number))
                x = ring_x + across * ring_width + sway * wobble
                if self._stirring:
                    # A turning stirrer carries them round with it: a slow
                    # sideways swing that grows as they rise from the ring.
                    swing = math.sin(2 * math.pi * (1.5 * share + self._turn + 0.3 * number))
                    x += BUBBLE_SWIRL * ring_width * share * swing
                y = ring_y - 4 - share * rise
                found.append((x, y, radius * (0.8 + 0.4 * share)))
        return found

    def set_alarm(self, level) -> None:
        self._alarm = check_alarm_level(level)
        self.update()

    def alarm(self):
        return self._alarm

    def _geometry(self) -> tuple[QRectF, float, float]:
        """Vessel body, depth of the dish, top of the caption line."""
        rect = QRectF(self.rect())
        line = self.fontMetrics().height()
        body = QRectF(
            rect.left() + 10,
            rect.top() + 14,
            rect.width() - 20,
            rect.height() - line - 24,
        )
        dish = body.width() * 0.18
        return body, dish, rect.bottom() - line

    def outlet(self) -> QPointF:
        """Where the harvest nozzle meets the bottom edge, in widget pixels."""
        body, _, _ = self._geometry()
        return QPointF(body.center().x(), self.rect().bottom())

    #: Where the gas lance comes through the lid, as a share of the vessel's
    #: width from its left wall: clear of the min/max marks and the shaft.
    LANCE_POSITION = 0.25

    def gas_inlet(self) -> QPointF:
        """Where the gas lance meets the top edge, in widget pixels.

        The sheet ends the aeration pipe here; the vessel draws the lance on
        from here, through the lid, down to the sparger.
        """
        body, _, _ = self._geometry()
        return QPointF(body.left() + body.width() * self.LANCE_POSITION, self.rect().top())

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        body, dish, caption_top = self._geometry()

        # Open top with a lid line, straight walls, dished bottom.
        vessel = QPainterPath()
        vessel.moveTo(body.left(), body.top())
        vessel.lineTo(body.left(), body.bottom() - dish)
        vessel.arcTo(
            QRectF(body.left(), body.bottom() - 2 * dish, body.width(), 2 * dish), 180, 180
        )
        vessel.lineTo(body.right(), body.top())
        vessel.closeSubpath()

        painter.setPen(QPen(EQUIPMENT, 2.0))
        painter.setBrush(WHITE)
        painter.drawPath(vessel)

        # 0 to 100 % of VLmax, from the lowest point of the dish upwards.
        working = body.adjusted(0, body.height() * HEADSPACE, 0, 0)
        surface = None
        if self._level is not None:
            surface = _fill(painter, vessel, working, self._level, self._broth)
            painter.setPen(QPen(EQUIPMENT, 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(vessel)
            _paint_surface_mark(painter, body.right() - 12, surface)

        self._paint_jacket(painter)
        self._paint_mark(painter, working, 1.0, "max")
        if self._minimum is not None:
            self._paint_mark(painter, working, self._minimum, "min")
        self._paint_stirrer(painter, rect, body, dish)
        self._paint_sparger(painter, body, dish, surface)

        # The nozzle, from the lowest point of the dish: equipment, so drawn
        # with the vessel; the pipe that carries on from its end is the
        # sheet's. While harvest flows it is drawn as that pipe is.
        x = body.center().x()
        nozzle = QPen(EQUIPMENT, 2.0)
        if self._draining:
            nozzle = QPen(MEDIUM_COLORS["harvest"], PIPE_LIVE_WIDTH)
        painter.setPen(nozzle)
        painter.drawLine(QPointF(x, body.bottom()), QPointF(x, rect.bottom()))

        # Name left of the nozzle, numbers right of it.
        height = rect.bottom() - caption_top
        name = QRectF(rect.left(), caption_top, x - 6 - rect.left(), height)
        numbers = QRectF(x + 6, caption_top, rect.right() - x - 6, height)
        painter.setPen(TEXT)
        painter.drawText(
            name,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            _elided(self, self.label, name.width()),
        )
        painter.setPen(MUTED)
        painter.drawText(
            numbers,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            _elided(self, self._text, numbers.width()),
        )
        draw_alarm(painter, rect, self._alarm)

    def _paint_mark(self, painter: QPainter, working: QRectF, share: float, name: str) -> None:
        y = working.bottom() - working.height() * share
        pen = QPen(EQUIPMENT, 1.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(working.left() + 2, y), QPointF(working.left() + 14, y))
        painter.setPen(MUTED)
        painter.drawText(QPointF(working.left() + 17, y + 4), name)

    def _paint_stirrer(self, painter: QPainter, rect: QRectF, body: QRectF, dish: float) -> None:
        x = body.center().x()
        # Low in the vessel, just above the dish and the sparger.
        hub = body.bottom() - dish - body.height() * 0.08
        painter.setPen(QPen(EQUIPMENT, 2.0))
        painter.drawLine(QPointF(x, rect.top()), QPointF(x, hub))

        blade = body.width() * 0.16
        painter.setPen(QPen(EQUIPMENT, 1.4))
        if not self._stirring:
            painter.setBrush(WHITE)
            painter.drawRect(QRectF(x - blade - 1, hub - 3, blade, 6))
            painter.drawRect(QRectF(x + 1, hub - 3, blade, 6))
            return
        # Four blades seen from the side while they turn: each is as long as
        # its angle shows it, the ones behind the shaft are drawn first and
        # paler. At turn 0 this is the standing picture, two full blades.
        blades = []
        for number in range(4):
            angle = 2 * math.pi * (self._turn + number / 4)
            blades.append((math.sin(angle), blade * math.cos(angle)))
        for depth, reach in sorted(blades):
            if abs(reach) < 0.5:
                continue
            painter.setBrush(EQUIPMENT if depth >= 0 else MUTED)
            left = x + 1 if reach > 0 else x - 1 + reach
            painter.drawRect(QRectF(left, hub - 3, abs(reach), 6))

    def _paint_sparger(self, painter: QPainter, body: QRectF, dish: float, surface) -> None:
        """The gas ring under the stirrer, fed by the lance from the lid.

        The lance comes down from the top edge (where the aeration pipe ends)
        beside the wall and turns in under the impeller to the ring. While
        gas flows the lance carries the pipe's colour down to the ring, and
        bubbles rise from the ring to the surface; without gas there are none.
        """
        x = body.center().x()
        y = body.bottom() - dish * 0.45  # inside the dish, under the impeller
        width = body.width() * 0.3
        lance = self.gas_inlet().x()
        pen = QPen(EQUIPMENT, 1.5)
        if self._gassing:
            pen = QPen(MEDIUM_COLORS["gas"], PIPE_LIVE_WIDTH - 1)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        lance_line = QPolygonF(
            [
                QPointF(lance, self.rect().top()),
                QPointF(lance, y),
                QPointF(x + width / 2, y),
            ]
        )
        painter.drawPolyline(lance_line)
        if self._gassing and self._flow_travel is not None:
            # The aeration pipe's dashes, carried on down to the ring.
            painter.setPen(flow_dash_pen(pen.widthF(), self._flow_travel))
            painter.drawPolyline(lance_line)
        if not self._gassing or surface is None:
            return
        painter.setPen(QPen(EQUIPMENT, 0.8))
        painter.setBrush(WHITE)
        for bubble_x, bubble_y, radius in self.bubbles(x, y, width, surface):
            painter.drawEllipse(QPointF(bubble_x, bubble_y), radius, radius)


# ------------------------------------------------------------- pipes --


def pipe_style(medium: str, live: bool) -> tuple[QColor, float, bool]:
    """Colour, width and whether there is an arrow. Live and idle differ in all three."""
    if medium not in MEDIUM_COLORS:
        raise ValueError(f"unknown medium {medium!r} — the media are: {', '.join(MEDIA)}")
    if live:
        return MEDIUM_COLORS[medium], PIPE_LIVE_WIDTH, True
    return PIPE_IDLE, PIPE_IDLE_WIDTH, False


def arrow_anchor(points, share: float = 0.5) -> tuple[tuple[float, float], float] | None:
    """Where on a polyline the flow arrow sits, and which way it points.

    `share` of the way along the line, by length: half way by default, since
    both ends lie under the elements the pipe connects. The R&I scheme puts
    the arrow where the line enters its target; the sheet (phase 3) knows
    where that is and passes the share. Returns ((x, y), angle in radians),
    or None for a line without length.
    """
    segments = [(a, b) for a, b in pairwise(points) if math.dist(a, b) > 0]
    if not segments:
        return None

    remaining = sum(math.dist(a, b) for a, b in segments) * share
    for a, b in segments:
        length = math.dist(a, b)
        if remaining <= length:
            part = remaining / length
            x = a[0] + (b[0] - a[0]) * part
            y = a[1] + (b[1] - a[1]) * part
            return (x, y), math.atan2(b[1] - a[1], b[0] - a[0])
        remaining -= length

    # Rounding can leave a hair of length over: then it is the very end.
    a, b = segments[-1]
    return (b[0], b[1]), math.atan2(b[1] - a[1], b[0] - a[0])


#: The moving dashes on a live pipe: dash and gap in pixels, and how far they
#: travel per second. Light enough to read as movement, not as a second line.
FLOW_DASH = (4.0, 8.0)
FLOW_DASH_SPEED = 24.0
FLOW_DASH_COLOR = QColor(0xFF, 0xFF, 0xFF, 110)


def flow_dash_pen(width: float, travel: float) -> QPen:
    """The light dashes on a live line `width` wide, moved on by `travel` px.

    The pattern is the same in pixels on every line, so dashes leaving one
    line and entering the next (the aeration pipe and the lance) line up.
    """
    dashes = QPen(FLOW_DASH_COLOR, max(width - 2.0, 1.0))
    dashes.setCapStyle(Qt.PenCapStyle.FlatCap)
    # A dash pattern is in units of the pen width; the offset moves it
    # backwards along the line, so a growing offset runs downstream.
    unit = dashes.widthF()
    dashes.setDashPattern([FLOW_DASH[0] / unit, FLOW_DASH[1] / unit])
    dashes.setDashOffset(-(travel % sum(FLOW_DASH)) / unit)
    return dashes


def draw_pipe(
    painter: QPainter,
    points,
    medium: str,
    live: bool,
    share: float = 0.5,
    travel: float | None = None,
    head: bool = True,
) -> None:
    """A pipe through `points` (pixels), drawn live or idle.

    `travel` (pixels) moves light dashes along a live pipe in the direction
    of flow; None draws none. The sheet advances it only while the process
    runs, so a paused process shows standing lines.
    """
    color, width, arrow = pipe_style(medium, live)
    if len(points) < 2:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))

    if live and travel is not None:
        painter.setPen(flow_dash_pen(width, travel))
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))

    anchor = arrow_anchor(points, share) if arrow and head else None
    if anchor is not None:
        (x, y), angle = anchor
        dx = math.cos(angle) * ARROW_SIZE
        dy = math.sin(angle) * ARROW_SIZE
        head = QPolygonF(
            [
                QPointF(x + dx, y + dy),  # tip, downstream
                QPointF(x - dx - dy, y - dy + dx),  # back corners, either side
                QPointF(x - dx + dy, y - dy - dx),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(head)

    painter.restore()
