"""The measuring bench for the Pichia controllers.

    python tools/tune_pichia.py feed      the methanol feed on reservoir 2
    python tools/tune_pichia.py po2       whether the pO2 loop can control at all
    python tools/tune_pichia.py lag       why neither of them can, yet
    python tools/tune_pichia.py all

The counterpart of `tune_po2.py`, which does the same for E. coli. It exists
for the same reason: a gain that is changed without a measurement beside it is
an opinion, and the numbers in CLAUDE.md have to be reproducible by whoever
reads them next.

**The scenario is the late-stage model**, not project 519. Pichia's second
model ("Pichia model (late stage)") starts where the glycerol batch ends —
8 litres, 20 g/l biomass, glycerol down to 1 g/l and `R_feed` on reservoir 2 —
which is the only configuration in this database where the methanol feed
controller has anything to do.
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biofermentation.core.runner import build_state, run_steps
from biofermentation.db import create_project, load_phases
from biofermentation.organisms import discover_organisms, get_organism
from biofermentation.resources import resource_root

#: modelTab row of "Pichia model (late stage)".
LATE_STAGE_MODEL = 2

TRACKED = ("t", "pO2", "NSt", "cXL", "cS2L", "cS2Lm", "FR2", "OUR", "OTR", "kLa")


def parameters() -> dict:
    """The parameter set of a project created from the late-stage model."""
    database = Path(tempfile.mkdtemp()) / "tuning.db"
    shutil.copy(resource_root() / "SimulationAppDB_template.db", database)
    project = create_project(database, "Tuning", LATE_STAGE_MODEL)
    return dict(load_phases(database, project).p)


def run(extra: dict, steps: int = 3600, dt: float = 2 / 3600) -> dict:
    """One run of the late-stage model with `extra` written over its parameters."""
    p = parameters() | {"f_Inoc": 1.0, "f_InocStart": 1.0} | extra
    model = get_organism("pichia_pastoris")
    state = build_state(p, model, dt=dt)
    run_steps(state, model, steps)
    stop = state.idx + 1
    result = {name: np.asarray(state.v[name][:stop], float) for name in TRACKED}
    result["p"] = p
    return result


def feed_score(result: dict) -> dict:
    """How well the methanol concentration is held, and what it cost.

    Measured from the second step: the first carries the initial value, which
    no controller can be held responsible for.
    """
    p = result["p"]
    setpoint = float(p["cS2Lw"])
    measured = result["cS2L"][1:]
    pump = result["FR2"][1:]
    maximum = float(p["FR2max"])
    return {
        "rms": float(np.sqrt(np.mean((measured - setpoint) ** 2))),
        "end": float(measured[-1]),
        "max": float(measured.max()),
        # How much of the run the pump spends at one of its stops. A loop that
        # is always at a stop is not controlling, whatever its RMS says.
        "at_stop": float(np.mean((pump <= 1e-12) | (pump >= maximum - 1e-12)) * 100),
        "travel": float(np.abs(np.diff(pump)).sum()),
        "cXL": float(result["cXL"][-1]),
    }


def po2_score(result: dict) -> dict:
    """The same for the pO2 loop, with the saturation that matters there."""
    p = result["p"]
    setpoint = float(p["pO2w"])
    pO2 = result["pO2"][1:]
    stirrer = result["NSt"][1:]
    low, high = 0.3 * float(p["NStmax"]), float(p["NStmax"])
    return {
        "rms": float(np.sqrt(np.mean((pO2 - setpoint) ** 2))),
        "end": float(pO2[-1]),
        "min": float(pO2.min()),
        "at_stop": float(np.mean((stirrer <= low + 0.5) | (stirrer >= high - 0.5)) * 100),
        "supply": float(np.mean(result["OTR"][1:] / np.maximum(result["OUR"][1:], 1e-12))),
    }


def tune_feed() -> None:
    """Find gains that hold the methanol concentration at its setpoint.

    The shipped gains for reservoir 2 are `KP_feedR2` = -2, `KI_feedR2` = -15,
    `KD_feedR2` = -0.009 — exactly the values of `KP_feedpO2`, `KI_feedpO2`
    and `KD_feedpO2`. Negative gains are right for that loop, where a pO2
    above the setpoint means the culture has oxygen to spare and may be fed
    more. On a substrate loop, where the error is `cS2Lw - cS2L`, they invert
    the controller: too little methanol gives a positive error, a negative
    output and a pump that stays shut.
    """
    shipped = {"f_feed": 1.0, "Mode_feed": 1.0, "Mode_pO2": 1.0}
    rows = []
    print("The shipped gains (a copy of the pO2 feed controller's):")
    base = run(shipped)
    rows.append(("shipped  -2 / -15 / -0.009", feed_score(base)))

    # The sign turned round first, then the magnitude. The error is
    # normalised by cS2R2 * 0.2 - 0.01, which is 158 g/l for this reservoir —
    # two orders of magnitude more than the setpoint, so the gains have to be
    # correspondingly larger than E. coli's on reservoir 1.
    grid = [
        (2.0, 15.0, 0.009),      # the sign turned round, magnitude untouched
        (1.0, 5.0, 0.005),
        (0.6, 2.0, 0.002),
        (0.5, 2.0, 0.002),       # the best of the sweep
        (0.4, 2.0, 0.002),
        (0.2, 1.0, 0.001),
        (15.0, 500.0, 0.02),     # E. coli's reservoir 1, for scale
    ]
    for kp, ki, kd in grid:
        result = run(shipped | {"KP_feedR2": kp, "KI_feedR2": ki, "KD_feedR2": kd})
        rows.append((f"{kp:g} / {ki:g} / {kd:g}", feed_score(result)))

    print(f"\n{'gains':28s} {'RMS':>8s} {'end':>8s} {'max':>8s} {'at stop':>8s} {'travel':>9s}"
          f" {'cXL':>7s}")
    for label, score in rows:
        print(f"{label:28s} {score['rms']:8.3f} {score['end']:8.3f} {score['max']:8.3f}"
              f" {score['at_stop']:7.1f}% {score['travel']:9.3f} {score['cXL']:7.2f}")
    print(f"\nSetpoint cS2Lw = {base['p']['cS2Lw']} g/l, FR2max = {base['p']['FR2max']} l/h")


def tune_po2() -> None:
    """Whether the pO2 loop has anything to tune. It has not — measured.

    Gains are only worth searching for once the manipulated variable is off
    its stops. Here it is not: the vessel delivers more oxygen at the stirrer's
    floor than the culture takes up, so pO2 sits above its setpoint whatever
    the gains are.
    """
    rows = []
    for label, extra in (
        ("as configured", {"Mode_pO2": 1.0}),
        ("anti-windup on", {"Mode_pO2": 1.0, "f_awpO2": 1.0}),
        ("gains x10", {"Mode_pO2": 1.0, "f_awpO2": 1.0, "KP_agi": 100.0, "KI_agi": 10000.0}),
        ("gains /10", {"Mode_pO2": 1.0, "f_awpO2": 1.0, "KP_agi": 1.0, "KI_agi": 100.0}),
        ("no pure oxygen", {"Mode_pO2": 1.0, "f_awpO2": 1.0, "f_O2": 0.0}),
        ("half the air", {"Mode_pO2": 1.0, "f_awpO2": 1.0, "f_O2": 0.0, "FnAIRw": 4.0}),
    ):
        rows.append((label, po2_score(run(extra))))

    print(f"{'scenario':18s} {'RMS':>8s} {'end':>8s} {'min':>8s} {'at stop':>8s} {'OTR/OUR':>8s}")
    for label, score in rows:
        print(f"{label:18s} {score['rms']:8.2f} {score['end']:8.2f} {score['min']:8.2f}"
              f" {score['at_stop']:7.1f}% {score['supply']:8.2f}")


def measured_lag() -> None:
    """Why the feed loop cannot hold anything, whatever its gains are.

    Pichia's closed-loop feed controls `cS2Lm`, the *measured* concentration,
    where E. coli controls the true one. And the measurement never moves:
    `meas_transfer_function` computes `T = dt / 3600` on a dt that is already
    in hours, so a step advances the lag by dt/3600/tau = 2.6e-09 of the gap.

    That is MATLAB's own arithmetic, faithfully ported and **verified**: the
    E. coli reference run agrees on `pHLm`, `thetaLm`, `pO2m` and `cS1Lm` to
    1e-12, so the original produces the same frozen signals. E. coli never
    notices because its feed controller reads the true concentration.

    Printed here rather than fixed, because correcting it would change what
    the verified comparison compares.
    """
    import biofermentation.organisms.pichia_pastoris.model as model

    def one_conversion(current, previous, tau, dt):
        """tau in seconds, dt in hours — converted once instead of twice."""
        return previous + (dt / (tau / 3600.0)) * (current - previous)

    gains = {"KP_feedR2": 0.5, "KI_feedR2": 2.0, "KD_feedR2": 0.002}
    shipped = {"f_feed": 1.0, "Mode_feed": 1.0, "Mode_pO2": 1.0}

    print("As ported — the measurement stands still:")
    result = run(shipped | gains)
    print(f"   cS2L  {result['cS2L'][-1]:8.4f}   cS2Lm {result['cS2Lm'][-1]:10.6f}")

    original = model.meas_transfer_function
    model.meas_transfer_function = one_conversion
    try:
        result = run(shipped | gains)
    finally:
        model.meas_transfer_function = original
    print("With the conversion applied once — the loop closes:")
    print(f"   cS2L  {result['cS2L'][-1]:8.4f}   cS2Lm {result['cS2Lm'][-1]:10.6f}")
    print(f"   setpoint {result['p']['cS2Lw']}, pump {result['FR2'][-1]:.4f} l/h")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("what", choices=("feed", "po2", "lag", "all"), nargs="?", default="all")
    args = parser.parse_args()
    discover_organisms()
    if args.what in ("feed", "all"):
        tune_feed()
    if args.what in ("po2", "all"):
        print()
        tune_po2()
    if args.what in ("lag", "all"):
        print()
        measured_lag()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
