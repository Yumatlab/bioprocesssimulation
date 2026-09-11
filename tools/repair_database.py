"""Repair the data damage the MATLAB create and delete paths left behind.

    python tools/repair_database.py --dry-run     show what is wrong
    python tools/repair_database.py               repair the parameters
    python tools/repair_database.py --remove-broken-projects

Two repairs are safe by construction and are applied by default:

  * A stray row in default_modelTab — one that carries another parameter's
    description next to that parameter's own value. Pichia has three, and
    they made every Pichia project run with an oxygen growth yield of 40
    instead of 1.773.
  * A project value that inherited one of those strays. It is restored from
    model_parameterTab, which holds the right number. Only those three names
    are touched; every other difference between a project and its model is an
    operator's setting.

Deleting a half-created project is not in that class — it is unopenable, but
it is also the only remaining record of what the MATLAB create path did. It
happens only with --remove-broken-projects, and is listed either way.
"""

import argparse
from pathlib import Path

from biofermentation.db.repair import repair
from biofermentation.resources import default_database


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        help="the database to repair; the application's own by default",
    )
    parser.add_argument("--dry-run", action="store_true", help="only report")
    parser.add_argument(
        "--remove-broken-projects",
        action="store_true",
        help="also delete projects whose parameters were never written",
    )
    args = parser.parse_args()

    target = args.database or default_database(create=False)
    if not target.is_file():
        print(f"no database at {target}")
        return 1

    report = repair(
        target,
        dry_run=args.dry_run,
        remove_broken_projects=args.remove_broken_projects,
    )
    print(target)
    for row in report["stray_defaults"]:
        print(
            f"  stray default     {row['name']:10s} = {row['value']!r:8} "
            f"({row['description']}) — belongs to {row['belongs_to']}"
        )
    for row in report["corrupted_parameters"]:
        print(
            f"  project {row['projectID']:<6} {row['name']:10s} "
            f"{row['stored']!r:8} -> {row['correct']!r}"
        )
    for row in report["broken_projects"]:
        state = "deleted" if report["removed_projects"] else "left alone"
        print(
            f"  broken project    {row['projectID']:<6} {row['name']:20s} "
            f"{row['parameters']}/{row['expected']} parameters — {state}"
        )
    verb = "would be" if args.dry_run else "were"
    print(
        f"  {len(report['stray_defaults'])} stray default(s) and "
        f"{len(report['corrupted_parameters'])} project value(s) {verb} repaired"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
