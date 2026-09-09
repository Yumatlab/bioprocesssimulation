"""Render the windows to PNG without a display (plan section 4).

Useful for a look at the layout while the application has no run loop yet,
and for the handbook of phase 8. Runs offscreen, so it works over SSH and in
CI.

    python -m biofermentation.gui.screenshots --out shots/
"""

import argparse
import os
import shutil
from pathlib import Path

# Has to be set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ..organisms import discover_organisms
from ..resources import TEMPLATE_DB
from .windows import CreateProjectWindow, SelectProjectWindow, StartingScreen


def render(out_dir: Path, db_path: Path | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if db_path is None:
        db_path = out_dir / "screenshot.db"
        shutil.copy(TEMPLATE_DB, db_path)

    app = QApplication.instance() or QApplication([])
    discover_organisms()
    written = []

    def shoot(widget, name: str, size: tuple[int, int]) -> None:
        widget.resize(*size)
        widget.show()
        app.processEvents()
        path = out_dir / name
        widget.grab().save(str(path))
        written.append(path)

    shoot(StartingScreen(), "01_starting_screen.png", (430, 560))

    select = SelectProjectWindow(db_path)
    select.table.resizeColumnsToContents()
    if select.model.rowCount():
        select.table.selectRow(0)
    shoot(select, "02_load_project.png", (1000, 460))

    create = CreateProjectWindow(db_path)
    create.title_edit.setText("MyProject")
    if create.model.rowCount():
        create.table.selectRow(0)
    shoot(create, "03_create_project.png", (600, 620))

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("screenshots"))
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    for path in render(args.out, args.db):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
