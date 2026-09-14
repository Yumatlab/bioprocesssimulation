"""Bring an existing database's reference values up to the shipped set.

A user's database is a copy of the template taken the day they first ran the
program. New defaults in the code — the pO2 controller gains, say — never
reach it on their own, and there is no rebuild path that does not also delete
the projects in it.

    python tools/update_reference_values.py --dry-run    show what would move
    python tools/update_reference_values.py              move it

Only values in rows that already exist are updated, matched on the primary
key. Nothing is inserted and nothing is deleted, so project data is never
touched. A value you changed on purpose in one of these tables is overwritten,
which is why --dry-run comes first in this docstring.
"""

import argparse
from pathlib import Path

from biofermentation.db import refresh_reference_values
from biofermentation.resources import default_database

TABLES = ("default_modelTab", "model_parameterTab", "plot_templateTab")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        help="the database to update; the application's own by default",
    )
    parser.add_argument("--dry-run", action="store_true", help="only list the differences")
    parser.add_argument("--table", action="append", choices=TABLES, help="restrict to one table")
    args = parser.parse_args()

    target = args.database or default_database(create=False)
    if not target.is_file():
        print(f"no database at {target}")
        return 1

    changes = refresh_reference_values(
        target, tuple(args.table) if args.table else TABLES, dry_run=args.dry_run
    )
    print(f"{target}")
    for table, where, before, after in changes:
        print(f"  {table:20s} {where:32s} {before!r:>12} -> {after!r}")
    verb = "would change" if args.dry_run else "changed"
    print(f"  {len(changes)} value(s) {verb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
