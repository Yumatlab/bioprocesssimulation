"""How much data a project may hold, and how close a run is to it.

**There is no hard limit worth the name.** SQLite stops at max_page_count
times the page size: 4 294 967 294 pages of 4 KiB, about 17.6 TB (SQLite
3.45.1, measured here). Long before that, the cost is what limits a run —
and the cost grows with the number of *stored* values, one row of dataTab
each.

Measured on project 716 (E. coli, 58 stored values per step), saving and
reopening in separate processes, on the development Mac (17.11.2026):

    process time     values     save           reopen               file
    8 h              835 258    2.2 s, +97 MB  0.8 s, peak 326 MB    56 MB
    24 h           2 505 658    6.9 s, +287 MB 2.3 s, peak 831 MB   168 MB
    per value                   2.8 µs, 115 B  0.9 µs, ~300 B        67 B

Pichia (project 519, 74 values per step) costs the same per value. The series
in memory are small beside this (10 MB after 8 h); the computation is not
what fills up.

**The binding cost is reopening**: about 300 bytes per value at its peak,
because the rows of dataTab are fetched before they are pivoted into series.
The limit is set so that reopening stays under about 1.5 GB, a margin a
student laptop with 8 GB can be expected to give, and saving stays at about
a quarter of a minute here (slower on Windows, not measured):

    5 000 000 values  ->  reopen ~1.5 GB, save ~14 s, file ~335 MB

That is 48 h of E. coli at Δt = 2 s with every step stored, 37 h of Pichia,
and ten times that with one step in ten stored. **The budget is a choice
made on these measurements, not a property of SQLite.** Should the reopening
be rewritten to stream rows, the peak falls and this number may rise.
"""

#: The most values a project may store (rows of dataTab), see above.
MAX_STORED_VALUES = 5_000_000

#: At this share the run pauses and asks; up to the next it may go on.
WARN_SHARE = 0.90
#: At this share the run stops and does not start again.
STOP_SHARE = 0.99


def stored_values(steps_at_open: int, steps_now: int, every: int, series: int) -> int:
    """How many values the project will hold once this run is saved.

    `steps_at_open` steps were in memory when the project was opened and are
    counted whole: they are stored already, or (index 0 of a fresh project)
    will be. Of the steps computed since, a save keeps those whose index is
    a multiple of `every` and always the last one — the rule of
    `_save_series`, counted the same way. `series` is the number of stored
    variables.

    NaN values are not stored, so a series with gaps holds fewer values than
    this says. Each further save in the same session keeps its own last step
    as well, one step more per save that this does not count.
    """
    every = max(1, int(every))
    first, last = max(0, steps_at_open), steps_now - 1
    kept = steps_at_open
    if last >= first:
        # Multiples of `every` in [first, last]; floor division handles 0.
        kept += last // every - (first - 1) // every
        if last % every:
            kept += 1
    return kept * max(0, series)


def share_of_limit(values: int, limit: int = MAX_STORED_VALUES) -> float:
    return values / limit if limit > 0 else 0.0


__all__ = [
    "MAX_STORED_VALUES",
    "STOP_SHARE",
    "WARN_SHARE",
    "share_of_limit",
    "stored_values",
]
