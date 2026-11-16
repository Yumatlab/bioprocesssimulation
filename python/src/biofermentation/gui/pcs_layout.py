"""Where the elements of the PCS tab sit — a text file, like the panel layout.

What is on the flow sheet and what it is wired to is code (gui/pcs_specs.py).
Where it is drawn is taste, so it is a file: the bundled default is
resources/layouts/pcs.yaml and a pcs.yaml next to the database replaces it.

    elements:
      reactor: [0.55, 0.50]
      acid:    [0.06, 0.68]
    pipes:
      acid_line: [[0.42, 0.68]]

Positions are fractions of the sheet, 0 to 1, so the sheet scales with the
window and asks for no width of its own. A pipe runs from the centre of its
source through its bends to the centre of its target; the widgets cover the
ends. A pipe without bends is a straight line.

Same deal as gui/panel_layout.py: never raises, a broken file falls back to an
arrangement that needs no file, and the reason goes to the log.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..resources import LAYOUTS_DIR, default_database
from .pcs_specs import MAX_RESERVOIRS, REACTOR, PcsSpec, pcs_spec

BUNDLED_PCS_LAYOUT = LAYOUTS_DIR / "pcs.yaml"
USER_PCS_LAYOUT_NAME = "pcs.yaml"

Point = tuple[float, float]


@dataclass(frozen=True)
class PcsLayout:
    """Where every element sits and how every pipe bends."""

    positions: dict[str, Point]
    bends: dict[str, tuple[Point, ...]] = field(default_factory=dict)

    def route(self, spec: PcsSpec, pipe: str) -> list[Point]:
        """The points a pipe is drawn through, ends included."""
        for candidate in spec.pipes:
            if candidate.element == pipe:
                start = self.positions[candidate.source]
                end = self.positions[candidate.target]
                return [start, *self.bends.get(pipe, ()), end]
        raise KeyError(pipe)


class PcsLayoutError(ValueError):
    """The file says something that cannot be drawn."""


def user_pcs_layout_path() -> Path:
    """Where a user's own arrangement goes: next to their database."""
    return default_database(create=False).parent / USER_PCS_LAYOUT_NAME


def _ids_of_any_organism() -> tuple[set[str], set[str]]:
    """Element and pipe ids a file may name without being wrong.

    A layout written for two reservoirs places reservoir2; for E. coli that
    entry is surplus, not a typo.
    """
    spec = pcs_spec(MAX_RESERVOIRS)
    return set(spec.elements()), {pipe.element for pipe in spec.pipes}


def parse_point(value, where: str) -> Point:
    """One [x, y] pair, both between 0 and 1."""
    if not isinstance(value, list) or len(value) != 2:
        raise PcsLayoutError(f"{where}: a position is [x, y], got {value!r}")
    point = []
    for number in value:
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise PcsLayoutError(f"{where}: {number!r} is not a number")
        if not 0 <= number <= 1:
            raise PcsLayoutError(f"{where}: {number} is outside 0 to 1")
        point.append(float(number))
    return point[0], point[1]


def parse_positions(elements, spec: PcsSpec) -> dict[str, Point]:
    """The `elements` mapping, checked against the specification."""
    if not isinstance(elements, dict):
        raise PcsLayoutError("elements must map each element to [x, y]")

    known, _ = _ids_of_any_organism()
    positions: dict[str, Point] = {}
    for name, value in elements.items():
        if name not in known:
            raise PcsLayoutError(
                f"unknown element {name!r} — the elements are: {', '.join(spec.elements())}"
            )
        positions[name] = parse_point(value, f"element {name}")

    missing = [name for name in spec.elements() if name not in positions]
    if missing:
        raise PcsLayoutError(f"not placed anywhere: {', '.join(missing)}")
    return {name: positions[name] for name in spec.elements()}


def parse_bends(pipes, spec: PcsSpec) -> dict[str, tuple[Point, ...]]:
    """The optional `pipes` mapping. A pipe left out is drawn straight."""
    if pipes is None:
        return {}
    if not isinstance(pipes, dict):
        raise PcsLayoutError("pipes must map each pipe to a list of [x, y] bends")

    _, known = _ids_of_any_organism()
    present = {pipe.element for pipe in spec.pipes}
    bends: dict[str, tuple[Point, ...]] = {}
    for name, points in pipes.items():
        if name not in known:
            raise PcsLayoutError(
                f"unknown pipe {name!r} — the pipes are: {', '.join(sorted(present))}"
            )
        if points is None:
            points = []
        if not isinstance(points, list):
            raise PcsLayoutError(f"pipe {name}: bends are a list of [x, y]")
        if name in present:
            bends[name] = tuple(parse_point(point, f"pipe {name}") for point in points)
    return bends


def load_pcs_layout(spec: PcsSpec, path: Path | None = None) -> tuple[PcsLayout, str]:
    """The layout to draw, and what went wrong on the way to it.

    Never raises: a broken file falls back and returns the reason. A typo in
    a layout file must not empty the tab.
    """
    candidates = [path] if path is not None else [user_pcs_layout_path(), BUNDLED_PCS_LAYOUT]
    problem = ""
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        try:
            document = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if not isinstance(document, dict):
                raise PcsLayoutError("the file must be a mapping with elements and pipes")
            layout = PcsLayout(
                parse_positions(document.get("elements"), spec),
                parse_bends(document.get("pipes"), spec),
            )
            return layout, problem
        except (PcsLayoutError, yaml.YAMLError, OSError) as error:
            problem = f"{candidate.name}: {error}"
            continue

    if not problem:
        problem = "no PCS layout file found"
    return fallback(spec), problem


def fallback(spec: PcsSpec) -> PcsLayout:
    """The reactor in the middle, everything else on a circle around it.

    Not pretty, and not meant to be: it runs when even the bundled file could
    not be read, and something that needs no file is the only thing worth
    falling back to. Every element is visible, pipes are straight.
    """
    others = [name for name in spec.elements() if name != REACTOR]
    positions: dict[str, Point] = {REACTOR: (0.5, 0.5)}
    for index, name in enumerate(others):
        angle = 2 * math.pi * index / len(others)
        positions[name] = (0.5 + 0.42 * math.cos(angle), 0.5 + 0.42 * math.sin(angle))
    return PcsLayout(positions)


def write_user_pcs_layout() -> Path:
    """Put the bundled arrangement next to the database for editing.

    An existing file is left alone — it is the user's.
    """
    target = user_pcs_layout_path()
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(BUNDLED_PCS_LAYOUT.read_text(encoding="utf-8"), encoding="utf-8")
    return target
