"""How a value is written down — a number, or the name of a mode.

Two questions the windows kept answering differently, and both of them are
about reading rather than about computing:

**A number needs as many decimals as it has, not as many as fit.** A phase
panel with two of them showed a 0.005 h timer as "0.00 h", and a log line with
`%g` turned 1e-05 into "1e-05" in one place and 0 in another. `format_number`
gives at least three and then as many as the value actually carries, which is
found by asking whether rounding changes it.

**A mode is a name, not a number.** `Mode_pO2 = 3` says nothing; the database
has said "pO2-Gasmix" all along, in `parameter_controlmodesTab`. The panels
have shown the names since the beginning — only the parameter dialogs and the
log still printed the raw number, which meant the log recorded what nobody
could read back.
"""

import math

#: Where the control modes come from, as `load_phases` hands them over:
#: one row per (parameter, value) pair with the name of that mode.
ModeTable = dict[str, dict[int, str]]


def decimals_for(value: float, floor: int = 4, cap: int = 12) -> int:
    """Enough places to show this value, at least `floor`.

    A box with four decimals holds 1e-05 as 0.0000 and hands that back on the
    next read: KD_gasmix appeared as "1e-05 → 0" in every phase, untouched,
    because the field could not represent what was put into it.
    """
    if not value or not math.isfinite(value):
        return floor
    magnitude = math.floor(math.log10(abs(value)))
    return min(cap, max(floor, 3 - magnitude))


def format_number(value: float, floor: int = 3, cap: int = 12) -> str:
    """`floor` decimals, and more where the value has more.

    Not significant digits: 1234.5678 keeps its four decimals, and 2.5 is
    written 2.500 rather than 2.5 so that a column of them lines up. The
    number of places is measured, not guessed — the first one at which
    rounding no longer changes the value is the one it has.
    """
    number = float(value)
    if not math.isfinite(number):
        return str(number)
    digits = max(0, floor)
    while digits < cap and round(number, digits) != number:
        digits += 1
    return f"{number:.{digits}f}"


def mode_table(p_modes) -> ModeTable:
    """Group `parameter_controlmodesTab` by parameter name."""
    table: ModeTable = {}
    for row in p_modes or ():
        name = row["parametername"]
        table.setdefault(name, {})[int(row["value"])] = row["mode"]
    return table


def modes_of(name: str, modes: ModeTable | None) -> dict[int, str]:
    """The modes of this parameter, or nothing if it has none."""
    return (modes or {}).get(name) or {}


def format_value(name: str, value, modes: ModeTable | None = None, *, floor: int = 3) -> str:
    """What a parameter's value is called.

    The name of the mode where the parameter has modes, the number otherwise.
    A value no mode carries — a database that grew a fifth mode without a row
    for it — is written as the number rather than as a guess.
    """
    if value is None:
        return "—"
    labels = modes_of(name, modes)
    if labels:
        return labels.get(round(float(value)), format_number(value, floor=0))
    return format_number(value, floor=floor)


__all__ = [
    "ModeTable",
    "decimals_for",
    "format_number",
    "format_value",
    "mode_table",
    "modes_of",
]
