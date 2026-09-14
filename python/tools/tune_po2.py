"""Bench for the pO2 controllers of the E. coli model.

Reproduces the numbers behind the default gains in default_modelTab and
model_parameterTab. Run it after a change to the model or to the gains:

    python tools/tune_po2.py            compare current with the proposal
    python tools/tune_po2.py --sweep    search the grid again

Scored over the growth phase only. After the substrate runs out the oxygen
uptake collapses and pO2 climbs back towards saturation whatever the
controller does; including that would measure the batch end, not the loop.
"""

import argparse
import itertools
import warnings
from pathlib import Path

import numpy as np

from biofermentation.core.runner import build_state, run_steps
from biofermentation.db import load_phases
from biofermentation.organisms import discover_organisms, get_organism

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
ECOLI_PROJECT = 716

#: mode -> (actuator variable, gain names, the values this bench arrived at)
CONTROLLERS = {
    1: ("NSt", ("KP_agi", "KI_agi", "KD_agi"), (1.0, 60.0, 0.002)),
    2: ("FnAIR", ("KP_aeration", "KI_aeration", "KD_aeration"), (5.0, 500.0, 0.005)),
    3: ("FnG", ("KP_gasmix", "KI_gasmix", "KD_gasmix"), (0.012, 1.0, 1e-5)),
}

#: The grids the proposal came out of.
GRIDS = {
    1: ([0.5, 1.0, 1.5, 2.0, 3.0], [15, 25, 40, 60], [0.0, 0.002, 0.005, 0.01]),
    2: ([0.5, 1.0, 2.0, 5.0], [50, 200, 500, 1000, 2000], [0.0, 0.005, 0.0188]),
    3: ([0.003, 0.005, 0.008, 0.012], [0.5, 1.0, 2.0, 5.0], [0.0, 5e-6, 1e-5, 5e-5]),
}

TRACKED = ("t", "pO2", "NSt", "FnAIR", "FnG", "OUR", "cXL")


def run(mode: int, gains: dict | None = None, steps: int = 5400, dt: float = 2 / 3600, **extra):
    """One batch with one set of gains."""
    p = (
        dict(load_phases(TEMPLATE, ECOLI_PROJECT).p)
        | {"f_Inoc": 1.0, "f_InocStart": 1.0, "deltatsec": round(dt * 3600, 6)}
        | {"Mode_pO2": float(mode)}
        | (gains or {})
        | extra
    )
    model = get_organism("escherichia_coli")
    state = build_state(p, model, dt=dt)
    run_steps(state, model, steps)
    stop = state.idx + 1
    return {name: np.asarray(state.v[name][:stop], float) for name in TRACKED}, p


def growth_window(result: dict, floor: float = 0.2) -> slice:
    """The samples while the culture is still respiring."""
    our = result["OUR"]
    live = our > floor * np.nanmax(our)
    if not live.any():
        return slice(0, len(our))
    start = int(np.argmax(live))
    stop = len(live) - int(np.argmax(live[::-1]))
    return slice(start + max(1, (stop - start) // 20), stop)


def score(result: dict, p: dict, actuator: str) -> dict:
    window = growth_window(result)
    error = result["pO2"][window] - p["pO2w"]
    u = result[actuator][window]
    step = np.abs(np.diff(u))
    return {
        "rms": float(np.sqrt(np.mean(error**2))),
        "max_err": float(np.max(np.abs(error))),
        "travel": float(np.sum(step) / max(1e-9, np.mean(np.abs(u)))),
    }


def cost(s: dict) -> float:
    """Tracking first, then how hard the actuator has to work for it."""
    return s["rms"] + 0.02 * s["travel"]


def compare() -> None:
    for mode, (actuator, names, proposal) in CONTROLLERS.items():
        before, p = run(mode)
        after, _ = run(mode, dict(zip(names, proposal, strict=True)))
        old, new = score(before, p, actuator), score(after, p, actuator)
        print(f"mode {mode} ({actuator}), gains {dict(zip(names, proposal, strict=True))}")
        for key in ("rms", "max_err", "travel"):
            print(f"    {key:8s} {old[key]:9.3f} -> {new[key]:8.3f}")


def sweep(mode: int) -> None:
    actuator, names, _ = CONTROLLERS[mode]
    rows = []
    for combo in itertools.product(*GRIDS[mode]):
        gains = dict(zip(names, combo, strict=True))
        try:
            result, p = run(mode, gains, steps=1800)
            s = score(result, p, actuator)
        except Exception:  # a set of gains that makes the model diverge
            continue
        if np.isfinite(s["rms"]):
            rows.append((cost(s), gains, s))
    rows.sort(key=lambda row: row[0])
    for value, gains, s in rows[:8]:
        print(f"  {value:8.3f}  {gains}  rms {s['rms']:7.3f}  travel {s['travel']:8.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", action="store_true", help="search the grid again")
    parser.add_argument("--mode", type=int, choices=sorted(CONTROLLERS), help="one mode only")
    args = parser.parse_args()

    warnings.filterwarnings("ignore")
    discover_organisms()
    modes = [args.mode] if args.mode else sorted(CONTROLLERS)
    for mode in modes:
        if args.sweep:
            print(f"=== mode {mode}")
            sweep(mode)
        else:
            pass
    if not args.sweep:
        compare()


if __name__ == "__main__":
    main()
