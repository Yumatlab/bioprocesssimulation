"""The PCS tab: the plant as a flow sheet — PCS plan, phase 3.

What is on the sheet comes from gui/pcs_specs.py, where it sits from
resources/layouts/pcs.yaml (gui/pcs_layout.py), and how each piece looks from
gui/widgets/pcs_elements.py. This module puts them together:

- `PcsCanvas` positions the elements from fractions of its own size, so the
  sheet scales with the window and asks for no width of its own, and draws
  the pipes, supplies and labels underneath them.
- `PcsView` is the tab: a row reserved for the alarm banner (phase 6, empty
  and hidden until then) above the canvas.

Two ways in, as for the controller panels:

- `load(state)` reads p (and the feed phase flags in a): which valve is
  commanded open and who owns it. After a dialog, a phase change, a write.
- `refresh(state)` reads v and a at the current index: flows, levels, the
  stirrer. After every block, and only while the tab is visible.

Command and feedback are kept apart. An element the operator owns shows its
flag; one a controller owns shows whether its line flows. A pipe shows only
the flow, never the flag.

Operating (phase 4): a click on an element the operator owns reports
`parameter_changed(name, value)` and nothing else. The view never writes into
p itself — the window does, through its one guarded, logged write path, and
then loads the panels and this view again. An element a controller owns is
disabled and cannot report.
"""

import math
from itertools import pairwise

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..pcs_layout import load_pcs_layout
from ..pcs_specs import (
    REACTOR,
    VESSEL_READINGS,
    broth_spec,
    harvested_volume,
    pcs_spec,
    pretty_unit,
)
from .indicators import MUTED, TEXT
from .pcs_elements import (
    ARROW_SIZE,
    EQUIPMENT,
    FLOW_DASH_SPEED,
    TankGauge,
    ValveButton,
    VesselWidget,
    arrow_anchor,
    draw_pipe,
)

#: A flow counts as flowing above this. Not `> 0`: controller outputs carry
#: noise, and a pipe that flickers live at 1e-12 l/h says nothing.
FLOW_EPSILON = 1e-6

#: Sizes of the vessels as shares of the canvas, with floors and ceilings in
#: pixels. Pumps and valves have a fixed size of their own.
REACTOR_SHARE = (0.22, 0.50)
REACTOR_LIMITS = ((90, 220), (130, 330))

#: Bubbles and the dashes on live pipes move this often, and only while the
#: sheet is visible and the process runs (bubbles: and gas flows).
BUBBLE_INTERVAL_MS = 80

#: Every reading reserves the room of this many characters before its unit,
#: so that it does not move when a digit comes or goes.
READING_TEMPLATE = "0.0000"

#: What runs through the reactor's double jacket rather than into the broth.
JACKET_MEDIA = ("coolant", "heating")

#: Groups the thousands of a large reading: "68 128", not "6.813e+04".
THIN_SPACE = "\u2009"
TANK_SHARE = (0.075, 0.17)
TANK_LIMITS = ((48, 90), (70, 120))


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _until(points, area: QRectF, step: float = 1.0) -> list[tuple[float, float]]:
    """The polyline from its start up to the last point before it enters `area`."""
    kept = [points[0]]
    for begin, end in pairwise(points):
        count = max(1, int(math.dist(begin, end) / step))
        last = begin
        for number in range(1, count + 1):
            share = number / count
            point = (begin[0] + (end[0] - begin[0]) * share, begin[1] + (end[1] - begin[1]) * share)
            if area.contains(QPointF(*point)):
                if last != kept[-1]:
                    kept.append(last)
                return kept
            last = point
        kept.append(end)
    return kept


def read_value(source: str | None, state) -> float | None:
    """The number behind "v:name", "a:name" or "p:name" at the current index.

    None if there is no such value or it is not a finite number: a pipe
    without a reading is idle, a tank without one shows no level.
    """
    if source is None:
        return None
    container, _, name = source.partition(":")
    if container == "v":
        series = state.v.get(name)
        if series is None:
            return None
        value = series[state.idx]
    elif container == "a":
        value = state.a.get(name)
    elif container == "p":
        value = state.p.get(name)
    else:
        raise ValueError(f"a source reads v, a or p, not {source!r}")
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return value


class PcsCanvas(QWidget):
    """The flow sheet: elements as child widgets, pipes painted beneath them."""

    def __init__(self, spec, layout, units: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self.spec = spec
        self.layout_file = layout
        self.units = units
        # Small on purpose: the window must fit a 1440 px screen with every
        # tab, and the sheet scales rather than demanding room.
        self.setMinimumSize(QSize(480, 360))

        self.widgets: dict[str, QWidget] = {}
        for tank in spec.tanks:
            if tank.element == REACTOR:
                widget = VesselWidget(tank.label, parent=self)
            else:
                widget = TankGauge(tank.label, parent=self)
            self.widgets[tank.element] = widget
        for valve in spec.valves:
            button = ValveButton(valve.label, valve.symbol, parent=self)
            button.setEnabled(False)  # nobody owns it before the first load
            self.widgets[valve.element] = button

        #: Per pipe: the reading at the current index, and whether it flows.
        self.flows: dict[str, float | None] = {pipe.element: None for pipe in spec.pipes}
        self.live: dict[str, bool] = {pipe.element: False for pipe in spec.pipes}
        #: The stirrer speed with its unit, written next to the motor's name.
        self.stirrer_reading = ""
        #: pH, pO2 and temperature as text, written beside the reactor.
        self.vessel_readings: list[str] = []
        #: How far the dashes on live pipes have travelled, in pixels.
        self.flow_travel = 0.0
        #: The unit each pipe's reading is in right now, where it is not the
        #: pipe's own (a Substitute in force).
        self.reading_units: dict[str, str] = {}

    # ----------------------------------------------------------- layout --

    def _size_for(self, element: str, widget: QWidget) -> QSize:
        if isinstance(widget, ValveButton):
            return widget.size()
        if element == REACTOR:
            share, limits = REACTOR_SHARE, REACTOR_LIMITS
        else:
            share, limits = TANK_SHARE, TANK_LIMITS
        width = _clamp(self.width() * share[0], *limits[0])
        height = _clamp(self.height() * share[1], *limits[1])
        # An even width puts the centre on a whole pixel, and with it the
        # shaft that the motor above must meet without a kink.
        return QSize(2 * round(width / 2), round(height))

    def _place(self) -> None:
        """Put every element on its position, kept inside the canvas.

        A vessel is centred on it. A pump or valve puts the point where its
        pipe runs through it there, which for a control valve is not its
        centre — otherwise the valve hangs below its line.
        """
        for element, widget in self.widgets.items():
            size = self._size_for(element, widget)
            widget.resize(size)
            x, y = self.point(element)
            anchor_x, anchor_y = size.width() / 2, size.height() / 2
            if isinstance(widget, ValveButton):
                anchor = widget.line_point()
                anchor_x, anchor_y = anchor.x(), anchor.y()
            left = _clamp(x - anchor_x, 0, max(0, self.width() - size.width()))
            top = _clamp(y - anchor_y, 0, max(0, self.height() - size.height()))
            widget.move(round(left), round(top))
        self._align_motor()

    def _align_motor(self) -> None:
        """Put the stirrer's motor exactly over the reactor's shaft.

        Placed on their own, both are rounded to whole pixels, and the two
        roundings left the shaft with a half-pixel kink at the lid.
        """
        motor = self.widgets.get("stirrer")
        vessel = self.widgets.get(REACTOR)
        if motor is None or vessel is None:
            return
        shaft = vessel.x() + vessel.width() // 2
        motor.move(shaft - motor.width() // 2, motor.y())

    def point(self, element: str) -> tuple[float, float]:
        """The position of an element in pixels of this canvas."""
        x, y = self.layout_file.positions[element]
        return x * self.width(), y * self.height()

    def route(self, pipe) -> list[tuple[float, float]]:
        """The points a pipe runs through, in pixels.

        A pipe that leaves an element with an outlet (the reactor's harvest
        nozzle) starts at the outlet and drops straight down to the height of
        its first bend, rather than starting at the element's centre.
        """
        width, height = self.width(), self.height()
        points = [
            (x * width, y * height) for x, y in self.layout_file.route(self.spec, pipe.element)
        ]
        source = self.widgets.get(pipe.source)
        if isinstance(source, VesselWidget):
            outlet = source.mapTo(self, source.outlet().toPoint())
            start = (float(outlet.x()), float(outlet.y()))
            drop = (start[0], points[1][1])
            points = [start, drop, *points[1:]]
        target = self.widgets.get(pipe.target)
        if isinstance(target, VesselWidget) and pipe.medium == "gas":
            # Gas goes in through the lance in the lid: level from the last
            # bend, then straight down onto the lance.
            inlet = target.mapTo(self, target.gas_inlet().toPoint())
            end = (float(inlet.x()), float(inlet.y()))
            last = points[-2]
            points = [*points[:-1], (end[0], last[1]), end]
        return points

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._place()

    # ---------------------------------------------------------- drawing --

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._paint_shaft(painter)

        # No pipe inside a symbol: a thick live line showed through the waist
        # of a valve and behind a hollow pump.
        painter.save()
        painter.setClipPath(self._outside_symbols())
        # Idle pipes first, so that a live one is never hidden where two
        # share a stretch (the gases behind their manifold).
        for wanted in (False, True):
            for pipe in self.spec.pipes:
                if self.live[pipe.element] != wanted:
                    continue
                points = self.route(pipe)
                share = self.arrow_share(pipe, points)
                draw_pipe(painter, points, pipe.medium, wanted, share, self.flow_travel)
        for pipe, points, travel in self.standing_stretches():
            draw_pipe(painter, points, pipe.medium, True, travel=travel, head=False)
        painter.restore()

        painter.setPen(TEXT)
        for box, text, alignment in self.value_boxes().values():
            painter.drawText(box, alignment | Qt.AlignmentFlag.AlignVCenter, text)
        for box, text in self.vessel_reading_boxes():
            painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        for node in self.spec.nodes:
            self._paint_node(painter, node)
        for valve in self.spec.valves:
            if self.shows_label(valve):
                self._paint_valve_label(painter, valve)

    def arrow_share(self, pipe, points) -> float:
        """Where along the pipe its arrow goes: just before it enters its target.

        As in the R&I scheme, the arrow says where the medium goes in. Half
        way sat on the valve of the line, and the reading with it. A target
        without a widget (the gas manifold, a point) gets the arrow just
        before the point.
        """
        target = self.widgets.get(pipe.target)
        total = sum(math.dist(a, b) for a, b in pairwise(points))
        if total <= 0:
            return 0.5
        if target is None:
            # Into a point (the gas manifold): at the end of the pipe's own
            # part, before it joins the collector the others share, so that
            # two live gases do not put their readings on the same spot.
            own = total - math.dist(points[-2], points[-1]) if len(points) > 2 else total
            return max(own - ARROW_SIZE - 6, 0.0) / total
        box = QRectF(target.geometry())
        step = 4.0
        distance = 0.0
        while distance <= total:
            anchor = arrow_anchor(points, distance / total)
            if anchor is not None and box.contains(QPointF(*anchor[0])):
                back = max(distance - 2 * ARROW_SIZE - 4, 0.0)
                return back / total
            distance += step
        # The pipe ends on the target's edge (the gas lance at the top edge of
        # the reactor), which the 4 px steps can step over: just before the end.
        return max(total - 2 * ARROW_SIZE - 4, 0.0) / total

    def _outside_symbols(self) -> QPainterPath:
        """The canvas with a hole where each pump, valve or motor is drawn."""
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        for widget in self.widgets.values():
            if isinstance(widget, ValveButton):
                path.addRect(widget.symbol_rect().translated(widget.x(), widget.y()))
        return path

    def value_boxes(self) -> dict[str, tuple[QRectF, str, Qt.AlignmentFlag]]:
        """Where each live pipe's reading goes, and what it says.

        Placed one after the other, each clear of every element, every name
        on the sheet and the readings placed before it.
        """
        obstacles = [QRectF(widget.geometry()) for widget in self.widgets.values()]
        obstacles += self.label_boxes()
        boxes: dict[str, tuple[QRectF, str, Qt.AlignmentFlag]] = {}
        for pipe in self.spec.pipes:
            if not self.live[pipe.element]:
                continue
            placed = self._value_box(pipe, obstacles)
            if placed is None:
                continue
            boxes[pipe.element] = placed
            obstacles.append(placed[0])
        return boxes

    def _value_box(self, pipe, obstacles) -> tuple[QRectF, str, Qt.AlignmentFlag] | None:
        """The reading of one live pipe, as the Variable Pool writes it.

        It starts beside the arrow, on its upstream side — above a level
        line, beside an upright one — and walks back up the line, 8 px at a
        time, until it covers no element and no other reading; if the line
        has no such gap, it steps away from the line and walks again. A fixed offset
        always sat on something somewhere: a valve, the pump above, the
        reading of the next gas, the name of a supply.

        The box is as wide as the widest reading can get and the text is
        aligned to the side of the arrow, so a digit more or less does not
        move the reading.
        """
        points = self.route(pipe)
        anchor = arrow_anchor(points, self.arrow_share(pipe, points))
        if anchor is None:
            return None
        (x, y), angle = anchor
        name = (pipe.flow or "").partition(":")[2]
        unit = pretty_unit(
            self.reading_units.get(pipe.element) or pipe.unit or self.units.get(name, "")
        )
        text = f"{self.value_text(pipe.element)} {unit}".strip()
        metrics = self.fontMetrics()
        widest = f"{pipe.widest or READING_TEMPLATE} {unit}".strip()
        width = max(metrics.horizontalAdvance(text), metrics.horizontalAdvance(widest)) + 4
        height = metrics.height()

        upright = abs(math.cos(angle)) < 0.5
        # Upstream of the arrow: left of it when the flow goes right.
        left = x + ARROW_SIZE + 6
        alignment = Qt.AlignmentFlag.AlignLeft
        if math.cos(angle) >= 0 or upright:
            left = x - ARROW_SIZE - 6 - width
            alignment = Qt.AlignmentFlag.AlignRight
        top = y - height - 4
        if upright:
            top = y - height / 2
        start = QRectF(left, top, width, height)

        canvas = QRectF(self.rect())
        back_x, back_y = -math.cos(angle) * 8, -math.sin(angle) * 8
        # Away from the line: up from a level one, aside from an upright one.
        away_x, away_y = (-1.0, 0.0) if upright else (0.0, -1.0)
        # Where a narrow window leaves no gap along the line (between the
        # reactor, the heating valve and "Heating water" at 1000 px), the
        # reading moves away from the line a step at a time and walks again.
        for lift in range(0, 40, 6):
            lifted = start.translated(away_x * lift, away_y * lift)
            for step in range(80):
                box = lifted.translated(back_x * step, back_y * step)
                if not canvas.contains(box):
                    break
                if not any(box.intersects(other) for other in obstacles):
                    return box, text, alignment
        return start, text, alignment

    #: Where gas standing in front of a closed valve stops, in pixels before
    #: the valve's symbol.
    STANDING_GAP = 6.0

    def standing_stretches(self) -> list[tuple]:
        """Gas that reaches a closed valve: the stretch up to just before it.

        With the aeration valve shut the gases still run into the manifold,
        and the line on from there to the valve is full of gas too. Drawn live
        up to STANDING_GAP before the valve — without arrow and reading, the
        valve stops it. Only lines that start at a junction (the manifold),
        not at a vessel: the harvest line behind its shut valve stays idle.

        Returns (pipe, points, travel) with the dashes carried on from the
        line that feeds it.
        """
        junctions = {node.element for node in self.spec.nodes}
        stretches = []
        for pipe in self.spec.pipes:
            if self.live[pipe.element] or pipe.valve is None or pipe.source not in junctions:
                continue
            feeders = [
                other
                for other in self.spec.pipes
                if other.target == pipe.source and self.live[other.element]
            ]
            valve = self.widgets.get(pipe.valve)
            if not feeders or not isinstance(valve, ValveButton):
                continue
            symbol = valve.symbol_rect().translated(valve.x(), valve.y())
            stop = symbol.adjusted(
                -self.STANDING_GAP, -self.STANDING_GAP, self.STANDING_GAP, self.STANDING_GAP
            )
            points = _until(self.route(pipe), stop)
            if len(points) < 2:
                continue
            fed = sum(math.dist(a, b) for a, b in pairwise(self.route(feeders[0])))
            stretches.append((pipe, points, self.flow_travel - fed))
        return stretches

    def lance_travel(self) -> float:
        """The dashes' travel as the lance sees it: less the aeration pipe.

        The lance in the reactor carries on where the aeration pipe ends, so
        its pattern starts the pipe's length further on.
        """
        for pipe in self.spec.pipes:
            if pipe.target == REACTOR and pipe.medium == "gas":
                length = sum(math.dist(a, b) for a, b in pairwise(self.route(pipe)))
                return self.flow_travel - length
        return self.flow_travel

    def _paint_shaft(self, painter: QPainter) -> None:
        """The stirrer's motor drives the reactor's shaft: draw the link."""
        motor = self.widgets.get("stirrer")
        vessel = self.widgets.get(REACTOR)
        if motor is None or vessel is None:
            return
        x = vessel.x() + vessel.width() // 2
        painter.setPen(QPen(EQUIPMENT, 2.0))
        painter.drawLine(
            QPointF(x, motor.geometry().bottom() - 4), QPointF(x, vessel.geometry().top())
        )

    def value_text(self, pipe: str) -> str:
        """The reading of a pipe as text — in the Variable Pool's format.

        Four significant digits, as the Variable Pool writes them, as long as
        that needs no exponent. Cooling water in g/h reaches 68 128 in two
        hours of project 716 and 1 500 000 by hand; ".4g" makes that
        "6.813e+04", which nobody reads at a glance on a flow sheet. A reading
        of 10 000 or more is therefore written whole, its thousands grouped.
        Only the jacket pipes get there: every series the Variable Pool also
        shows stays far below.
        """
        value = self.flows[pipe]
        if value is None:
            return "—"
        text = f"{value:.4g}"
        if "e" in text and abs(value) >= 1:
            text = f"{value:,.0f}".replace(",", THIN_SPACE)
        return text

    def _paint_node(self, painter: QPainter, node) -> None:
        """A supply is an open circle with its name; a junction is a dot."""
        x, y = self.point(node.element)
        painter.setPen(QPen(EQUIPMENT, 1.2))
        if not node.label:
            painter.setBrush(EQUIPMENT)
            painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
        painter.setPen(TEXT)
        painter.drawText(self._node_label_box(node), Qt.AlignmentFlag.AlignCenter, node.label)

    def _node_label_box(self, node) -> QRectF:
        """Where a supply's name stands: centred above its circle."""
        x, y = self.point(node.element)
        metrics = self.fontMetrics()
        width = metrics.horizontalAdvance(node.label) + 4
        left = _clamp(x - width / 2, 0, max(0, self.width() - width))
        return QRectF(left, y - metrics.height() - 6, width, metrics.height())

    def label_boxes(self) -> list[QRectF]:
        """Every name painted on the sheet, for the readings to keep clear of."""
        boxes = [self._node_label_box(node) for node in self.spec.nodes if node.label]
        boxes += [
            self._valve_label_box(valve) for valve in self.spec.valves if self.shows_label(valve)
        ]
        boxes += [box for box, _ in self.vessel_reading_boxes()]
        return boxes

    def vessel_reading_boxes(self) -> list[tuple[QRectF, str]]:
        """pH, pO2 and temperature: one line each, under the stirrer's name.

        Right of the shaft, between the motor and the lid — the one stretch
        of the sheet no pipe crosses. Left-aligned with the stirrer's name, so
        the four values about the broth read as one block.
        """
        motor = self.widgets.get("stirrer")
        if motor is None or not self.vessel_readings:
            return []
        name = self._valve_label_box(self.spec.valve("stirrer"))
        metrics = self.fontMetrics()
        height = metrics.height()
        boxes = []
        for number, text in enumerate(self.vessel_readings):
            width = metrics.horizontalAdvance(text) + 4
            top = name.bottom() + 2 + number * height
            boxes.append((QRectF(name.left(), top, width, height), text))
        return boxes

    def shows_label(self, valve) -> bool:
        """Whether an element is named on the sheet.

        An element on a line from a named supply or vessel is named by it:
        "Air" over the air supply and again under its valve says it twice,
        and on a dense sheet the second one sits on the next row's symbol.
        The element keeps its name in its tooltip either way.
        """
        named = {tank.element for tank in self.spec.tanks}
        named |= {node.element for node in self.spec.nodes if node.label}
        for pipe in self.spec.pipes:
            if pipe.valve == valve.element and pipe.source in named:
                return False
        return True

    def _paint_valve_label(self, painter: QPainter, valve) -> None:
        """The element's name under its symbol, small and grey.

        The stirrer's name stands to its right: below it runs the shaft.
        """
        painter.setPen(MUTED)
        painter.drawText(
            self._valve_label_box(valve), Qt.AlignmentFlag.AlignCenter, self.label_text(valve)
        )

    def label_text(self, valve) -> str:
        """The name on the sheet; the stirrer's carries its speed."""
        if valve.element == "stirrer" and self.stirrer_reading:
            return f"{valve.label} · {self.stirrer_reading}"
        return valve.label

    def _valve_label_box(self, valve) -> QRectF:
        geometry = self.widgets[valve.element].geometry()
        metrics = self.fontMetrics()
        if valve.element == "stirrer":
            return QRectF(
                geometry.right() + 4,
                geometry.center().y() - metrics.height() / 2,
                metrics.horizontalAdvance(self.label_text(valve)) + 4,
                metrics.height(),
            )
        width = max(geometry.width(), metrics.horizontalAdvance(valve.label) + 4)
        left = _clamp(geometry.center().x() - width / 2, 0, max(0, self.width() - width))
        return QRectF(left, geometry.bottom() + 1, width, metrics.height())


class PcsView(QWidget):
    """The PCS tab: a reserved banner row above the flow sheet."""

    #: An operator's click: the flag to write and its new value, 0.0 or 1.0.
    #: Same signature as ControlPanel.parameter_changed, on purpose.
    parameter_changed = Signal(str, float)

    def __init__(
        self,
        n_reservoirs: int,
        variables=(),
        layout_path=None,
        organism: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.spec = pcs_spec(int(n_reservoirs))
        self.broth = broth_spec(organism)
        self.running = False
        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(BUBBLE_INTERVAL_MS)
        self.animation_timer.timeout.connect(self._animate)
        layout, self.layout_problem = load_pcs_layout(self.spec, layout_path)
        units = {row["name"]: row.get("unit") or "" for row in variables}

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        # Reserved for the alarm banner of phase 6: present, hidden, no height.
        self.banner = QLabel()
        self.banner.setVisible(False)
        column.addWidget(self.banner)
        self.canvas = PcsCanvas(self.spec, layout, units)
        column.addWidget(self.canvas, 1)

        #: Who owns each element right now, from the last load: None is the
        #: operator.
        self.owners: dict[str, str | None] = {valve.element: None for valve in self.spec.valves}

        for valve in self.spec.valves:
            # toggled, not clicked: it carries the new state, and set_state_now
            # blocks it, so loading never reports.
            self.canvas.widgets[valve.element].toggled.connect(
                lambda checked, name=valve.parameter: self.parameter_changed.emit(
                    name, float(checked)
                )
            )

    def element(self, element: str) -> QWidget:
        return self.canvas.widgets[element]

    # ------------------------------------------------------- animation --

    def set_running(self, running: bool) -> None:
        """Whether the process computes. Nothing moves while it pauses."""
        self.running = bool(running)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.animation_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().hideEvent(event)
        self.animation_timer.stop()

    def _animate(self) -> None:
        """One frame: dashes run along live pipes and on down the lance, the
        impeller turns while it stirs, bubbles rise while gas flows.

        Only while the process runs. A paused process with moving lines would
        say that something flows that the model is not computing.
        """
        if not self.running:
            return
        seconds = BUBBLE_INTERVAL_MS / 1000
        self.canvas.flow_travel += FLOW_DASH_SPEED * seconds
        vessel = self.canvas.widgets[REACTOR]
        if vessel.gassing():
            vessel.advance_bubbles(seconds)
        if vessel.stirring():
            vessel.advance_stirrer(seconds)
        vessel.set_flow_travel(self.canvas.lance_travel())
        self.canvas.update()

    def load(self, state) -> None:
        """Commands and ownership from p (and the feed phase flags in a)."""
        for valve in self.spec.valves:
            owner = valve.locked_by(state.p, state.a)
            self.owners[valve.element] = owner
            button = self.canvas.widgets[valve.element]
            # Enables the element for the operator, disables it for a controller.
            button.set_locked(owner)
            if owner is None:
                button.set_state_now(state.p.get(valve.parameter) == 1)
        self.refresh(state)

    def refresh(self, state, alarms=()) -> None:
        """Flows, levels and the stirrer at the current index.

        `alarms` is taken already (pairs of element id and level) so that
        phase 6 has nothing to rebuild; nobody passes any yet.
        """
        for pipe in self.spec.pipes:
            self.canvas.reading_units.pop(pipe.element, None)
            instead = pipe.instead
            if instead is not None and all(c.holds(state.p, state.a) for c in instead.when):
                value = read_value(instead.flow, state)
                self.canvas.reading_units[pipe.element] = instead.unit
                live = value is not None and value > FLOW_EPSILON
            else:
                value = read_value(pipe.flow, state)
                live = value is not None and value > FLOW_EPSILON
                if pipe.counts_when is not None and not pipe.counts_when.holds(state.p, state.a):
                    live = False
                if value is not None:
                    value *= pipe.factor
            self.canvas.flows[pipe.element] = value
            self.canvas.live[pipe.element] = live

        # A controller's element shows what flows, not what was commanded.
        for valve in self.spec.valves:
            if self.owners[valve.element] is None:
                continue
            value = read_value(valve.feedback, state)
            running = value is not None and value > FLOW_EPSILON
            self.canvas.widgets[valve.element].set_state_now(running)

        for tank in self.spec.tanks:
            widget = self.canvas.widgets[tank.element]
            volume = read_value(tank.volume, state)
            maximum = read_value(tank.maximum, state)
            if tank.element == "harvest":
                widget.set_collected(
                    harvested_volume(self.spec, lambda source: read_value(source, state))
                )
            elif isinstance(widget, VesselWidget):
                widget.set_volume(volume, maximum, read_value(tank.minimum, state))
                speed = read_value("v:NSt", state)
                widget.set_stirring(speed is not None and speed > FLOW_EPSILON)
                self.canvas.stirrer_reading = ""
                if speed is not None:
                    unit = pretty_unit(self.canvas.units.get("NSt", ""))
                    self.canvas.stirrer_reading = f"{speed:.4g} {unit}".strip()
                self._show_reactor_state(widget, state)
                widget.set_flow_travel(self.canvas.lance_travel())
            else:
                widget.set_volume(volume, maximum)

        self.canvas.vessel_readings = []
        for reading in VESSEL_READINGS:
            value = read_value(reading.source, state)
            if value is None:
                continue
            text = f"{reading.label} {value:.{reading.decimals}f} {reading.unit}"
            self.canvas.vessel_readings.append(text.strip())

        levels = dict(alarms)
        for element, widget in self.canvas.widgets.items():
            widget.set_alarm(levels.get(element))

        self.canvas.update()

    def _show_reactor_state(self, vessel: VesselWidget, state) -> None:
        """Gas in, harvest out and the colour of the broth."""
        live = self.canvas.live
        vessel.set_gassing(
            any(
                live[pipe.element]
                for pipe in self.spec.pipes
                if pipe.target == REACTOR and pipe.medium == "gas"
            )
        )
        vessel.set_draining(
            any(live[pipe.element] for pipe in self.spec.pipes if pipe.source == REACTOR)
        )
        vessel.set_jacket(
            pipe.medium
            for pipe in self.spec.pipes
            if pipe.target == REACTOR and pipe.medium in JACKET_MEDIA and live[pipe.element]
        )
        biomass = read_value(self.broth.biomass, state) or 0.0
        product = read_value(self.broth.product, state) or 0.0
        vessel.set_broth(biomass / self.broth.biomass_full, product / self.broth.product_full)
