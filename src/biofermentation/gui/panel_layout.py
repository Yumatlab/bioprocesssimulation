"""Where the controller panels sit — a text file, not a Python file.

The arrangement of the Control Options tab went through five rounds in one
afternoon, and every round was a code change. It does not belong in code: it
is a matter of taste, it has no effect on anything the application computes,
and the person whose taste it is should not have to edit Python and restart a
build to try something.

So it is a file, the same way the look is a file: the bundled default is
resources/layouts/control_options.yaml and a control_options.yaml next to the
database replaces it.

The file *is* the arrangement — a grid of names, one line per row of the tab:

    grid:
      - [pO2, pO2, Liquid Weight]
      - [pH, Temperature, Feed]

A name repeated across neighbouring cells makes that panel cover them. What
comes back is one `Placement` per panel, in Qt's addWidget order.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..resources import LAYOUTS_DIR, default_database

BUNDLED_LAYOUT = LAYOUTS_DIR / "control_options.yaml"
USER_LAYOUT_NAME = "control_options.yaml"


@dataclass(frozen=True)
class Placement:
    """One panel's cell, in the order QGridLayout.addWidget wants it."""

    row: int
    column: int
    row_span: int
    column_span: int


class LayoutError(ValueError):
    """The file says something that cannot be drawn."""


def user_layout_path() -> Path:
    """Where a user's own arrangement goes: next to their database."""
    return default_database(create=False).parent / USER_LAYOUT_NAME


def normalise(name: str) -> str:
    """Fold a panel name to its comparable form.

    "pH-Control", "pH control" and "ph" are the same panel. The file is meant
    to be typed by hand, and a layout that breaks over a capital letter would
    be a layout nobody edits twice.
    """
    folded = str(name).strip().lower().replace("_", " ").replace("-", " ")
    for suffix in (" control", " ctrl"):
        if folded.endswith(suffix):
            folded = folded[: -len(suffix)]
    return " ".join(folded.split())


def parse_grid(grid, titles: list[str]) -> dict[str, Placement]:
    """Turn the grid of names into one placement per panel.

    `titles` are the panel titles as the specifications spell them; the return
    is keyed by those, whatever spelling the file used.
    """
    if not isinstance(grid, list) or not grid:
        raise LayoutError("grid must be a list of rows, one per row of the tab")

    rows = []
    for index, row in enumerate(grid):
        if not isinstance(row, list) or not row:
            raise LayoutError(f"row {index + 1} is not a list of cells")
        rows.append(row)

    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise LayoutError("every row needs the same number of cells")

    known = {normalise(title): title for title in titles}
    # Where each name was seen. An empty cell is a tilde or an empty string.
    cells: dict[str, list[tuple[int, int]]] = {}
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell is None or str(cell).strip() in ("", "~"):
                continue
            key = normalise(cell)
            if key not in known:
                raise LayoutError(
                    f"unknown panel {cell!r} at row {r + 1}, column {c + 1} — "
                    f"the names are: {', '.join(titles)}"
                )
            cells.setdefault(known[key], []).append((r, c))

    missing = [title for title in titles if title not in cells]
    if missing:
        raise LayoutError(f"not placed anywhere: {', '.join(missing)}")

    places: dict[str, Placement] = {}
    for title, seen in cells.items():
        top = min(r for r, _ in seen)
        left = min(c for _, c in seen)
        height = max(r for r, _ in seen) - top + 1
        span = max(c for _, c in seen) - left + 1
        if len(seen) != height * span:
            raise LayoutError(
                f"the cells of {title!r} do not form a rectangle — a panel "
                "covers a block of cells, not a scattering of them"
            )
        places[title] = Placement(top, left, height, span)
    return places


def load_layout(titles: list[str], path: Path | None = None) -> tuple[dict[str, Placement], str]:
    """The arrangement to draw, and what went wrong on the way to it.

    Never raises: a broken file falls back to the bundled arrangement and
    returns the reason. Half a tab because of a typo in a layout file is not
    a trade anybody would take.
    """
    candidates = [path] if path is not None else [user_layout_path(), BUNDLED_LAYOUT]
    problem = ""
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        try:
            document = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            return parse_grid(document.get("grid"), titles), problem
        except (LayoutError, yaml.YAMLError, OSError) as error:
            problem = f"{candidate.name}: {error}"
            continue

    if not problem:
        problem = "no layout file found"
    return fallback(titles), problem


def fallback(titles: list[str]) -> dict[str, Placement]:
    """One column per panel, side by side. Every panel is visible, always.

    Deliberately not a copy of the bundled arrangement: this runs when even
    the bundled file could not be read, and something that needs no file is
    the only thing worth falling back to.
    """
    return {title: Placement(0, index, 1, 1) for index, title in enumerate(titles)}


def write_user_layout() -> Path:
    """Put the bundled arrangement next to the database for editing.

    An existing file is left alone — it is the user's, and this is called from
    a menu entry whose job is to open it, not to reset it.
    """
    target = user_layout_path()
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(BUNDLED_LAYOUT.read_text(encoding="utf-8"), encoding="utf-8")
    return target
