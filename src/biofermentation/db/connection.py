"""The single way into the database (plan section 1.2).

Every access goes through get_connection(). No module-level connection, no
sqlite3.connect() anywhere else. In the MATLAB version connections were opened
ad hoc and closed in only one branch of a try/catch, which leaked them, and
transactions were nested until a rollback stopped rolling anything back. One
block, one connection, one transaction.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def get_connection(db_path: Path | str, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the database for the duration of the block.

    Commits on a clean exit, rolls back on any exception, closes either way.
    Rows come back as sqlite3.Row, so they can be read by column name.

    readonly opens the file in SQLite's read-only mode, which is what the
    loaders use: a reader cannot corrupt anything, and it makes the intent of
    a block obvious at the call site.
    """
    db_path = Path(db_path)
    if readonly:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, isolation_level=None)
    else:
        conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row

    # Both pragmas have to run outside a transaction: foreign_keys is a no-op
    # inside one, and journal_mode cannot switch. WAL is a property of the
    # file and survives, so a reader must not try to set it.
    conn.execute("PRAGMA foreign_keys = ON")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")

    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
        raise
    else:
        # A block that committed on its own leaves nothing to commit here.
        if conn.in_transaction:
            conn.execute("COMMIT")
        conn.close()
