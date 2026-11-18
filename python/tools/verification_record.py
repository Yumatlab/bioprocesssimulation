"""Measure how far the E. coli model is from the MATLAB reference run.

Runs exactly what `test_ecoli_matches_matlab_reference` runs — the exported
MATLAB run MyProject_11, inoculation and the reconstructed fed-batch phase at
the same steps — and prints, per quantity, the largest relative and absolute
deviation over the comparison window and over the first twelve steps.

The output is a Markdown table for docs/verification_escherichia_coli.md, so
that the record of a version is measured, not copied from an older one:

    python tools/verification_record.py

Needs pandas (development dependency) and the files in
tests/reference_data/.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biofermentation import __version__  # noqa: E402
from biofermentation.control import (  # noqa: E402
    EndCondition,
    PhaseAutomaton,
    PhaseStatus,
    PhaseType,
    StartCondition,
)
from biofermentation.core.runner import build_state  # noqa: E402
from biofermentation.db.models import Condition, Phase  # noqa: E402
from biofermentation.organisms import discover_organisms, get_organism  # noqa: E402

REFERENCE_DIR = ROOT / "tests" / "reference_data"

#: The groups of docs/verification_escherichia_coli.md.
GROUPS = {
    "State variables and balances": ["cXL", "cS1L", "cS3L", "pHL", "thetaL", "VL"],
    "Measured quantities (first-order lags)": ["pHLm", "thetaLm", "pO2m", "cS1Lm"],
    "The fast oxygen loop": ["pO2", "cOL", "OUR", "OTR", "kLa", "NSt", "xOG", "RQ", "CTR"],
    "Identical in both": ["pG", "FnG", "FT1", "FT2", "QO2max", "FR1"],
}
FIRST_STEPS = 12


def run():
    """The reference run as the test runs it. Returns (state, reference, end)."""
    series = pd.read_csv(REFERENCE_DIR / "ecoli_reference.csv.gz")
    parameters = pd.read_csv(REFERENCE_DIR / "ecoli_reference_p.csv")
    meta = pd.read_csv(REFERENCE_DIR / "ecoli_reference_meta.csv").set_index("key")["value"]
    p = dict(zip(parameters["name"], parameters["value"].astype(float), strict=True))

    dt = float(meta["deltat"])
    inoculation = int(float(meta["inoculation_step"]))
    feed = int(float(meta["feed_phase_start_step"]))
    end = int(float(meta["comparison_end_step"]))

    discover_organisms()
    p = dict(p) | {"f_InocStart": 0.0, "f_Inoc": 0.0, "deltatsec": 2.0}
    model = get_organism("escherichia_coli")
    state = build_state(p, model, dt=dt)
    phase = Phase(
        processID=1,
        projectID=int(float(meta["projectID"])),
        statusID=PhaseStatus.UPCOMING,
        typeID=PhaseType(int(float(meta["feed_phase_type"]))),
        name="Fed Batch",
        reservoirID=int(float(meta["feed_phase_reservoir"])),
        start=Condition(
            typeID=StartCondition.VARIABLE,
            variableID=61,
            operatorID=1,
            value=float(series["t"][feed]),
        ),
        end=Condition(typeID=EndCondition.TIMER, value=99.0),
    )
    automaton = PhaseAutomaton([phase], variable_names={61: "t"}, operator_symbols={1: ">="})
    for step in range(end):
        if step == inoculation:
            state.p.f_Inoc = 1.0
        automaton.check_start(state)
        model.calculate_step(state)
        automaton.check_end(state)
    return state, series, end


def deviation(ours: np.ndarray, theirs: np.ndarray) -> tuple[float, float]:
    """Largest relative and absolute deviation; relative only where |MATLAB| > 1e-12."""
    absolute = np.abs(ours - theirs)
    scale = np.abs(theirs)
    relative = np.where(scale > 1e-12, absolute / np.where(scale > 1e-12, scale, 1.0), 0.0)
    return float(np.nanmax(relative)), float(np.nanmax(absolute))


def main() -> int:
    state, reference, end = run()
    print(f"Version {__version__}, steps 0 to {end}, first {FIRST_STEPS} steps separately.\n")
    for title, columns in GROUPS.items():
        print(f"#### {title}\n")
        dash = "\u2013"  # the range dash of the tables in the report
        window, early = f"0{dash}{end}", f"0{dash}{FIRST_STEPS}"
        print(f"| Quantity | rel. ({window}) | abs. ({window}) | rel. ({early}) |")
        print("|---|---:|---:|---:|")
        for column in columns:
            if column not in reference or column not in state.v:
                continue
            ours = np.asarray(state.v[column][: end + 1], dtype=float)
            theirs = reference[column].to_numpy(dtype=float)[: end + 1]
            rel, ab = deviation(ours, theirs)
            early, _ = deviation(ours[: FIRST_STEPS + 1], theirs[: FIRST_STEPS + 1])
            print(f"| `{column}` | {rel:.1e} | {ab:.1e} | {early:.1e} |")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
