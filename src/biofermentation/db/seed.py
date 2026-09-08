"""Export and reload of the reference data ("defaults") as CSV.

Everything the application needs in order to run but that is not tied to a
single project: parameter and variable definitions, the lookup tables, and
the default values per bioreactor, per organism and per model. Project data
(projectTab, processTab, timeTab, dataTab, logTab and their child tables) is
deliberately not covered — it is user data, not defaults.

The CSV set is the rebuild path for an emptied database. It is also plain
text, so a change to a default value shows up in a diff.

File format, one file per table:
  - header row with the column names of the table
  - one row per record, fields in header order
  - NULL is written as \\N; an empty field means the empty string
  - UTF-8, LF line endings, minimal quoting

The \\N convention (borrowed from PostgreSQL's COPY) is needed because CSV
cannot otherwise tell NULL from '' — and both occur, for example in
parameterTab.unit, where a dimensionless parameter carries ''.
"""

import csv
import sqlite3
from pathlib import Path

NULL = r"\N"

DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "resources" / "defaults"

# Insert order. Every table comes after the tables it references, so the set
# can be loaded into an empty database with foreign keys enabled. Deleting
# happens in reverse.
DEFAULT_TABLES: tuple[str, ...] = (
    "categoryTab",
    "parameterTab",
    "variableTab",
    "organismTab",
    "bioreactorTab",
    "modelTab",
    "process_typeTab",
    "process_conditiontypeTab",
    "process_operatorTab",
    "process_statusTab",
    "plot_colorTab",
    "plot_decimalTab",
    "plot_linestyleTab",
    "plot_templateTab",
    "default_bioreactorTab",
    "default_modelTab",
    "model_parameterTab",
    "default_plot_variableTab",
    "plot_variableTab",
    "variable_handlingTab",
    "process_variableTab",
    "parameter_controlmodesTab",
    "systemTab",
)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _blob_affinity(conn: sqlite3.Connection, table: str) -> set[str]:
    """Columns SQLite will not convert for us.

    A column declared INTEGER, REAL, NUMERIC or TEXT applies its affinity to
    the string coming out of the CSV and ends up with the type it had before.
    A column declared BLOB, or declared without a type at all, has no affinity
    and would keep the string — default_plot_variableTab.selected_variable and
    systemTab.godmode hold integers and would silently turn into text.
    """
    return {
        row[1]
        for row in conn.execute(f'PRAGMA table_info("{table}")')
        if row[2].upper() in ("", "BLOB")
    }


def _encode(value: object) -> str:
    if value is None:
        return NULL
    if isinstance(value, bytes):
        raise TypeError("binary columns are not part of the default data")
    return str(value)


def _decode(field: str, *, numeric: bool = False) -> str | int | float | None:
    if field == NULL:
        return None
    if numeric:
        try:
            return int(field)
        except ValueError:
            try:
                return float(field)
            except ValueError:
                return field
    return field


def export_defaults(db_path: Path | str, target_dir: Path | str = DEFAULTS_DIR) -> list[Path]:
    """Write one CSV per reference table. Returns the files written."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    written = []

    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        for table in DEFAULT_TABLES:
            cols = _columns(conn, table)
            # A stable sort keeps the diff of a changed default value small.
            order = ", ".join(f'"{c}"' for c in cols[:1])
            rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}')
            path = target_dir / f"{table}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh, lineterminator="\n")
                writer.writerow(cols)
                writer.writerows([_encode(v) for v in row] for row in rows)
            written.append(path)
    finally:
        conn.close()
    return written


def load_defaults(
    db_path: Path | str,
    source_dir: Path | str = DEFAULTS_DIR,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Replace the reference tables from the CSV set. Returns rows per table.

    Refuses to run while projects exist, unless force is set: the reference
    tables are the parents of the project tables, so clearing them cascades
    into project data and would delete it.
    """
    source_dir = Path(source_dir)
    conn = sqlite3.connect(Path(db_path), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        projects = conn.execute("SELECT COUNT(*) FROM projectTab").fetchone()[0]
        if projects and not force:
            raise RuntimeError(
                f"{projects} projects in the database; loading defaults would cascade "
                "into them. Pass force=True if that is intended."
            )

        counts = {}
        conn.execute("BEGIN")
        try:
            for table in reversed(DEFAULT_TABLES):
                conn.execute(f'DELETE FROM "{table}"')
            for table in DEFAULT_TABLES:
                path = source_dir / f"{table}.csv"
                typeless = _blob_affinity(conn, table)
                with path.open(newline="", encoding="utf-8") as fh:
                    reader = csv.reader(fh)
                    cols = next(reader)
                    numeric = [c in typeless for c in cols]
                    placeholders = ", ".join("?" * len(cols))
                    columns = ", ".join(f'"{c}"' for c in cols)
                    data = [
                        [_decode(f, numeric=n) for f, n in zip(row, numeric, strict=True)]
                        for row in reader
                        if row
                    ]
                conn.executemany(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})', data)
                counts[table] = len(data)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"defaults left foreign key violations: {violations}")
    finally:
        conn.close()
    return counts
