"""Batch end detection from the pO2 slope (plan section 3).

Translated from Additional_functions/BatchEndDetection_pO2Slope.m. When the
substrate runs out, respiration stops: pO2 shoots up while the agitation
controller backs off. Detecting both at once is the classical signature.

Two things are deliberately not carried over.

MATLAB keeps the hysteresis counter in a `persistent` variable, which in
MATLAB is shared across the whole session — two projects running one after
the other would inherit each other's count. Here it is instance state.

MATLAB's `random` behaviour with the window is a unit mistake, and that one is
reproduced: the function's own documentation says deltat is in hours, but
ControlApp calls it with app.p.deltatsec, which is seconds. With deltatsec = 2
the window collapses from the intended 3 minutes (90 samples) to the floor of
3 samples, 6 seconds. Set window_in_seconds=False to get the documented
behaviour instead.
"""

from dataclasses import dataclass, field
from statistics import median

import numpy as np


def sliding_median(values: np.ndarray, k: int) -> np.ndarray:
    """Median filter with edge padding, as medfilt1 does by default."""
    if k <= 1:
        return np.asarray(values, dtype=float).copy()
    values = np.asarray(values, dtype=float)
    half = k // 2
    padded = np.concatenate([np.full(half, values[0]), values, np.full(half, values[-1])])
    return np.array([median(padded[i : i + k]) for i in range(values.size)])


def theil_sen_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Median of all pairwise slopes — robust against outliers in a short window."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 2:
        return 0.0
    slopes = [
        (y[j] - y[i]) / (x[j] - x[i])
        for i in range(x.size - 1)
        for j in range(i + 1, x.size)
        if x[j] != x[i]
    ]
    return float(median(slopes)) if slopes else 0.0


@dataclass
class BatchEndDetector:
    """Holds the hysteresis counter across steps.

    Thresholds are the tunable parameters of the MATLAB original, in the same
    units: a normalised pO2 slope above 5 %/min together with an agitation
    slope below -5 rpm/min, both holding for three consecutive steps.
    """

    window_minutes: float = 3.0
    min_confirm: int = 3
    threshold_pO2: float = 5.0
    threshold_NSt: float = -5.0
    window_in_seconds: bool = True
    confirm_count: int = field(default=0, init=False)
    last_slopes: tuple[float, float] = field(default=(0.0, 0.0), init=False)

    def reset(self) -> None:
        self.confirm_count = 0

    def detect(self, state) -> bool:
        """True once both conditions have held for min_confirm steps."""
        # The unit mistake of the original: deltatsec is seconds, the window
        # is hours, and the division collapses to the floor of three samples.
        step = state.p.deltatsec if self.window_in_seconds else state.dt
        n_window = max(3, round((self.window_minutes / 60) / step))

        idx = state.idx
        if idx < n_window:
            self.confirm_count = 0
            return False

        start = idx - n_window
        pO2 = state.v.pO2[start : idx + 1]
        NSt = state.v.NSt[start : idx + 1]
        t = state.v.t[start : idx + 1]

        if np.isnan(pO2).any() or np.isnan(NSt).any() or np.all(NSt == 0):
            self.confirm_count = 0
            return False

        k = min(5, (n_window // 2) * 2 + 1)  # odd kernel, at most 5
        slope_pO2 = theil_sen_slope(t, sliding_median(pO2, k)) / 60
        slope_NSt = theil_sen_slope(t, sliding_median(NSt, k)) / 60
        self.last_slopes = (slope_pO2, slope_NSt)

        if slope_pO2 > self.threshold_pO2 and slope_NSt < self.threshold_NSt:
            self.confirm_count += 1
        else:
            self.confirm_count = 0

        return self.confirm_count >= self.min_confirm
