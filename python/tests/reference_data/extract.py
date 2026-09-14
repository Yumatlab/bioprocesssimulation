"""Build the MATLAB reference fixtures (plan sections 0.3 and 2.4).

Two runs, from two sources, because no MATLAB licence was available to
produce fresh ones:

  E. coli  from MyProject_11.txt, an export the application itself wrote.
           43 variables, 2983 steps at dt = 2 s. The export carries no
           parameter set; every starting value matches project 716 of the
           shipped database exactly, down to pG = pGcal + deltapGw * 1e5 and
           the agitation controller's lower clamp of 0.3 * NStmax, so that
           project's parameters are used.

  Pichia   from Thesis_SimulationAppDB.db, the database as it was at thesis
           submission. Project 520 holds 14799 time points over 8.2 h with
           51 variables and seven phases, taken straight out of dataTab.

The parameter sets are written the way MATLAB's loadPhases builds app.p:
looping over the rows and letting a later one overwrite an earlier one. That
matters here — project_parameterTab in the thesis database has duplicate rows
for yXpOgr, yCpO and qOpXm, the correct value first and a stray second, so
MATLAB ran with 40.0, 15.0 and 0.5. Reproducing the run means reproducing
that, not correcting it.

Run this only to rebuild the fixtures; the CSVs are checked in.
"""

import argparse
import csv
import gzip
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
MATLAB_DIR = Path.home() / "Documents" / "Biofermentation Simulation Version 2.2"
THESIS_DB = HERE.parents[1] / "additional_files" / "Thesis_SimulationAppDB.db"
TEMPLATE_DB = (
    HERE.parents[1] / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
)


def _write_rows(path: Path, header: list[str], rows) -> Path:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _parameters(db_path: Path, project_id: int) -> dict[str, float]:
    """app.p as loadPhases builds it — later rows overwrite earlier ones."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT prop.name, ppara.value
              FROM project_parameterTab ppara
              JOIN parameterTab prop ON ppara.parameterID = prop.parameterID
              JOIN categoryTab c ON c.categoryID = prop.categoryID
             WHERE ppara.projectID = ?
             ORDER BY c.section, c.name, prop.internal_order, ppara.project_parameterID
            """,
            (project_id,),
        ).fetchall()
    finally:
        conn.close()
    return {name: value for name, value in rows}


def _write_meta(prefix: str, **values) -> Path:
    return _write_rows(
        HERE / f"{prefix}_reference_meta.csv", ["key", "value"], sorted(values.items())
    )


def _write_parameters(prefix: str, parameters: dict[str, float]) -> Path:
    return _write_rows(
        HERE / f"{prefix}_reference_p.csv",
        ["name", "value"],
        [(name, repr(float(value))) for name, value in sorted(parameters.items())],
    )


def build_ecoli() -> None:
    source = MATLAB_DIR / "MyProject_11.txt"
    if not source.is_file():
        raise SystemExit(f"missing {source}")

    with source.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = [column.split(" in ")[0].strip() for column in next(reader)]
        header[0] = "t"  # the export calls it "time in h"
        rows = list(reader)

    _write_rows(HERE / "ecoli_reference.csv.gz", header, rows)
    _write_parameters("ecoli", _parameters(TEMPLATE_DB, 716))

    dt = float(rows[1][0]) - float(rows[0][0])
    _write_meta(
        "ecoli",
        organism="escherichia_coli",
        deltat=repr(dt),
        steps=len(rows),
        projectID=716,
        source="MyProject_11.txt",
        # cXL is 0 at index 0 and 1 and 3.0 at index 2: inoculation was
        # switched on during the second step, not before the run.
        inoculation_step=1,
        # The project this run belonged to is deleted, but its feed phase can
        # be reconstructed. FR1 becomes non-zero at step 403, and the value
        # 0.03899203 l/h is exactly what handleExponentialFeed computes from
        # the state at step 402 — to eight decimals. The feed then grows at
        # 0.100000 1/h, which is qXpX1w. Reservoir 1, since E. coli has one.
        feed_phase_start_step=402,
        feed_phase_type=5,
        feed_phase_reservoir=1,
        # Where the comparison has to stop: at this step a pH difference of
        # 1.4e-05 puts the two runs on opposite sides of the controller's dead
        # band and the pump schedules part company.
        comparison_end_step=903,
    )
    print(f"E. coli: {len(rows)} Schritte, {len(header)} Spalten, dt = {dt}")


def build_pichia(project_id: int = 520) -> None:
    if not THESIS_DB.is_file():
        raise SystemExit(f"missing {THESIS_DB}")

    conn = sqlite3.connect(f"file:{THESIS_DB}?mode=ro", uri=True)
    try:
        times = conn.execute(
            "SELECT timeID, process_time FROM timeTab WHERE projectID = ? "
            "ORDER BY process_time, timeID",
            (project_id,),
        ).fetchall()
        names = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT v.name
                  FROM dataTab d
                  JOIN timeTab t ON t.timeID = d.timeID
                  JOIN variableTab v ON v.variableID = d.variableID
                 WHERE t.projectID = ?
                 ORDER BY v.variableID
                """,
                (project_id,),
            )
        ]
        index = {name: position for position, name in enumerate(names)}
        by_time = {time_id: position for position, (time_id, _) in enumerate(times)}

        table = [["" for _ in names] for _ in times]
        for time_id, name, value in conn.execute(
            """
            SELECT d.timeID, v.name, d.value
              FROM dataTab d
              JOIN timeTab t ON t.timeID = d.timeID
              JOIN variableTab v ON v.variableID = d.variableID
             WHERE t.projectID = ?
            """,
            (project_id,),
        ):
            table[by_time[time_id]][index[name]] = repr(value) if value is not None else ""
    finally:
        conn.close()

    rows = [
        [repr(process_time), *values]
        for (_, process_time), values in zip(times, table, strict=True)
    ]
    _write_rows(HERE / "pichia_reference.csv.gz", ["t", *names], rows)
    _write_parameters("pichia", _parameters(THESIS_DB, project_id))

    dt = times[1][1] - times[0][1]
    _write_meta(
        "pichia",
        organism="pichia_pastoris",
        deltat=repr(dt),
        steps=len(times),
        projectID=project_id,
        source="Thesis_SimulationAppDB.db",
        # The batch phase runs alone until the first feed starts; up to there
        # the run needs no phase automaton.
        batch_end_step=round(3.5 / dt),
    )
    print(f"Pichia: {len(times)} Schritte, {len(names)} Variablen, dt = {dt}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("which", nargs="?", default="both", choices=["ecoli", "pichia", "both"])
    args = parser.parse_args()
    if args.which in ("ecoli", "both"):
        build_ecoli()
    if args.which in ("pichia", "both"):
        build_pichia()
