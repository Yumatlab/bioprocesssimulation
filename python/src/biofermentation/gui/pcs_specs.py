"""What the PCS tab shows and what each element is wired to.

The PCS tab draws the plant as a flow sheet: the reactor in the middle,
reservoirs, valves and supplies around it. This module says *what* is on the
sheet and which parameter or series each element belongs to. *Where* it sits
is taste and lives in resources/layouts/pcs.yaml (see gui/pcs_layout.py).

Wiring decides the outcome of a run, so it is code and it is tested against
the models: every valve writes a flag a model reads, every lock names a mode
in which the model does not read that flag, every flow names a series a model
writes. See tests/test_pcs_specs.py and the section "Der PCS-Tab" in
CLAUDE.md, which lists the model line behind every row.

No Qt in here. The specification is data; it is tested without a window, and
the widgets of the tab are built from it.

Sources are written "p:name", "v:name" or "a:name" — parameter, stored series
or auxiliary value — so that a reader can see at a glance which of the three
containers of SimulationState a value comes from.
"""

from dataclasses import dataclass

#: The element the sheet is built around. Its widget differs from a tank's.
REACTOR = "reactor"

#: How an operable element is drawn, after the R&I scheme in matlab/RI.drawio
#: (symbols of DIN EN ISO 10628-2). Which one an element gets is not taste:
#: the model meters acid, alkali, feed, antifoam and harvest as pump rates
#: (FT1max is "Pump rate acid"), and the gases through mass flow controllers.
#: The harvest is the exception: it leaves through a valve in the bottom of
#: the reactor (decision of 16.11.2026), not through the pump of the scheme.
SYMBOLS = ("pump", "valve", "control_valve", "motor")

#: What a pipe carries. The tab colours a live pipe by its medium.
MEDIA = ("feed", "acid", "base", "antifoam", "harvest", "gas", "coolant", "heating")

#: Element ids a layout file may name for reservoirs the current organism does
#: not have. A layout written for Pichia (two reservoirs) must not break E. coli.
MAX_RESERVOIRS = 3


def read(source: str, p, a) -> float | None:
    """The value behind a "p:", "a:" source. None if it is not there.

    A missing auxiliary counts as 0: `a.switch_exp` only exists once a phase
    has set it, and the model reads it with `a.get("switch_exp", False)`.
    """
    container, _, name = source.partition(":")
    if container == "p":
        return p.get(name)
    if container == "a":
        return float(a.get(name, 0.0))
    raise ValueError(f"a condition reads p or a, not {source!r}")


@dataclass(frozen=True)
class Condition:
    """Holds while the value at `source` is one of `values`."""

    source: str  # "p:Mode_pO2" or "a:switch_exp"
    values: tuple[int, ...]

    def holds(self, p, a) -> bool:
        return read(self.source, p, a) in self.values


@dataclass(frozen=True)
class Lock(Condition):
    """The operator owns the valve only while this condition holds.

    Outside it a controller or a phase drives the flow and the model does not
    read the flag. The valve is then disabled, its symbol follows the flow,
    and its tooltip names `owner`.
    """

    owner: str = ""
    #: True: outside the condition the model ignores the flag entirely, and
    #: the tests check exactly that. False: the lock is a decision of the tab,
    #: not a fact about the model — see the aeration valve.
    complete: bool = True


@dataclass(frozen=True)
class ValveSpec:
    """One operable element: a flag in p, written 0 or 1.

    Called a valve because most of them switch a line; `symbol` says what it
    is on the sheet — a pump, a block valve, a control valve or a motor.
    """

    element: str
    parameter: str
    label: str
    #: The series that shows what the valve does. A locked valve draws itself
    #: from this, not from its flag. None: there is no such series.
    feedback: str | None
    locks: tuple[Lock, ...] = ()
    symbol: str = "valve"

    def locked_by(self, p, a) -> str | None:
        """Who drives this valve right now, or None if the operator does."""
        for lock in self.locks:
            if not lock.holds(p, a):
                return lock.owner
        return None


@dataclass(frozen=True)
class TankSpec:
    """A vessel with a level. Without `volume` it is drawn empty."""

    element: str
    label: str
    volume: str | None = None  # series, e.g. "v:VR1"
    maximum: str | None = None  # parameter that counts as 100 %, e.g. "p:VR10"
    minimum: str | None = None  # optional mark, e.g. "p:VLmin"


@dataclass(frozen=True)
class NodeSpec:
    """A place a pipe starts, ends or meets others: a supply or a junction."""

    element: str
    label: str = ""


@dataclass(frozen=True)
class PipeSpec:
    """A line between two elements, live while its flow is."""

    element: str
    source: str
    target: str
    medium: str
    flow: str | None  # None: no series says whether it flows
    valve: str | None = None
    #: The flow counts only while this holds. Heating water flows only in
    #: automatic mode; in manual the heater is electric and a.mdotH keeps
    #: whatever the controller last wrote.
    counts_when: Condition | None = None


@dataclass(frozen=True)
class PcsSpec:
    """Everything on the sheet for one organism."""

    tanks: tuple[TankSpec, ...]
    nodes: tuple[NodeSpec, ...]
    valves: tuple[ValveSpec, ...]
    pipes: tuple[PipeSpec, ...]

    def elements(self) -> list[str]:
        """Every element id that needs a place on the sheet, in drawing order."""
        ids = [tank.element for tank in self.tanks]
        ids += [node.element for node in self.nodes]
        ids += [valve.element for valve in self.valves]
        return ids

    def valve(self, element: str) -> ValveSpec:
        for valve in self.valves:
            if valve.element == element:
                return valve
        raise KeyError(element)


# ------------------------------------------------------------ locks --
#
# The panel switches of Control Options carry the same conditions for the six
# flags they offer (gui/widgets/panel_specs.py). They are written out again
# here because the panels are Qt widgets and this module is not; a test holds
# the two together.

PH_MANUAL = Lock("p:Mode_pH", (0,), owner="pH-Control")
TEMP_MANUAL = Lock("p:Mode_temp", (0,), owner="Temperature-Control")
HARVEST_MANUAL = Lock("p:Mode_harvest", (0,), owner="Liquid Weight")

#: Air and oxygen: the pO2 controller sets both in Aeration and Gasmix.
GAS_BY_HAND = Lock("p:Mode_pO2", (0, 1, 4), owner="pO2-Control")

#: The main gas valve. In Aeration and Gasmix the model still reads it for N2
#: and CO2, so this lock is a decision, not a fact (decision 7): a closed main
#: valve there leaves FnG[i] NaN and xOGin at 0. See CLAUDE.md.
AERATION_BY_HAND = Lock("p:Mode_pO2", (0, 1, 4), owner="pO2-Control", complete=False)

#: The stirrer: pO2 control by agitation sets the speed itself.
STIRRER_BY_HAND = Lock("p:Mode_pO2", (0, 2, 3, 4), owner="pO2-Control")

#: Feed: phases and pO2-controlled feed take the pumps without reading f_feed.
FEED_LOCKS = (
    Lock("a:switch_exp", (0,), owner="exponential feed phase"),
    Lock("a:switch_pulse", (0,), owner="pulse feed phase"),
    Lock("p:Mode_pO2", (0, 1, 2, 3), owner="pO2-Control (Feed)"),
)


# ------------------------------------------------------------ sheet --


def _feed_line(n: int) -> tuple[TankSpec, ValveSpec, PipeSpec]:
    """Reservoir n, its valve and its pipe.

    The reservoir is chosen in the Feed Control panel (decision 3). The valve
    of a reservoir that is not chosen is therefore locked: f_feed would open
    the other one.
    """
    tank = TankSpec(f"reservoir{n}", f"Reservoir {n}", f"v:VR{n}", f"p:VR{n}0")
    chosen = Lock("p:R_feed", (n,), owner="Feed Control (other reservoir selected)")
    valve = ValveSpec(
        f"feed{n}_pump", "f_feed", f"Feed {n}", f"v:FR{n}", (*FEED_LOCKS, chosen), "pump"
    )
    pipe = PipeSpec(f"feed{n}_line", f"reservoir{n}", REACTOR, "feed", f"v:FR{n}", valve.element)
    return tank, valve, pipe


def _gas_line(gas: str, label: str, flag: str, flow: str, locks=()):
    """One gas supply, its valve, and its pipe into the manifold."""
    node = NodeSpec(f"{gas}_supply", label)
    valve = ValveSpec(f"{gas}_valve", flag, label, flow, locks, "control_valve")
    pipe = PipeSpec(f"{gas}_line", node.element, "gas_manifold", "gas", flow, valve.element)
    return node, valve, pipe


def pcs_spec(n_reservoirs: int) -> PcsSpec:
    """The sheet for an organism with this many substrate reservoirs."""
    tanks = [
        TankSpec(REACTOR, "Reactor", "v:VL", "p:VLmax", "p:VLmin"),
        TankSpec("acid", "Acid", "v:VT1", "p:VT10"),
        TankSpec("alkali", "Alkali", "v:VT2", "p:VT20"),
        # No volume series for either (decision 4).
        TankSpec("antifoam", "Antifoam"),
        TankSpec("harvest", "Harvest"),
    ]
    nodes = [
        NodeSpec("gas_manifold"),
        NodeSpec("cooling_supply", "Cooling water"),
        NodeSpec("heating_supply", "Heating water"),
    ]
    valves = [
        ValveSpec("acid_pump", "f_acid", "Acid", "v:FT1", (PH_MANUAL,), "pump"),
        ValveSpec("alkali_pump", "f_alkali", "Alkali", "v:FT2", (PH_MANUAL,), "pump"),
        # The model reads f_antifoam only after inoculation (a.ToI != 0). That
        # is not a controller taking over, so no lock; nothing flows before.
        ValveSpec("antifoam_pump", "f_antifoam", "Antifoam", None, symbol="pump"),
        ValveSpec("harvest_valve", "f_harvest", "Harvest", "v:FH", (HARVEST_MANUAL,), "valve"),
        ValveSpec("aeration_valve", "f_aeration", "Aeration", "v:FnG", (AERATION_BY_HAND,)),
        ValveSpec("stirrer", "f_motor", "Stirrer", "v:NSt", (STIRRER_BY_HAND,), "motor"),
        ValveSpec("cooling_valve", "f_cooling", "Cooling", "a:mdotC", (TEMP_MANUAL,)),
        ValveSpec("heating_valve", "f_heating", "Heating", "a:mdotH", (TEMP_MANUAL,)),
    ]
    pipes = [
        PipeSpec("acid_line", "acid", REACTOR, "acid", "v:FT1", "acid_pump"),
        PipeSpec("alkali_line", "alkali", REACTOR, "base", "v:FT2", "alkali_pump"),
        PipeSpec("antifoam_line", "antifoam", REACTOR, "antifoam", None, "antifoam_pump"),
        PipeSpec("harvest_line", REACTOR, "harvest", "harvest", "v:FH", "harvest_valve"),
        PipeSpec("aeration_line", "gas_manifold", REACTOR, "gas", "v:FnG", "aeration_valve"),
        PipeSpec("cooling_line", "cooling_supply", REACTOR, "coolant", "a:mdotC", "cooling_valve"),
        PipeSpec(
            "heating_line",
            "heating_supply",
            REACTOR,
            "heating",
            "a:mdotH",
            "heating_valve",
            counts_when=Condition("p:Mode_temp", (1,)),
        ),
    ]

    gases = (
        _gas_line("air", "Air", "f_air", "v:FnAIR", (GAS_BY_HAND,)),
        _gas_line("o2", "O2", "f_O2", "v:FnO2", (GAS_BY_HAND,)),
        _gas_line("n2", "N2", "f_N2", "v:FnN2"),
        _gas_line("co2", "CO2", "f_CO2", "v:FnCO2"),
    )
    for node, valve, pipe in gases:
        nodes.append(node)
        valves.append(valve)
        pipes.append(pipe)

    for n in range(1, n_reservoirs + 1):
        tank, valve, pipe = _feed_line(n)
        tanks.append(tank)
        valves.append(valve)
        pipes.append(pipe)

    return PcsSpec(tuple(tanks), tuple(nodes), tuple(valves), tuple(pipes))
