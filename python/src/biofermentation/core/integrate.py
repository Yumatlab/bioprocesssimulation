"""One-step ODE integration (plan section 2.4).

MATLAB integrates every step with ode15s, a solver for stiff systems, and the
obvious counterpart in scipy is BDF. Measuring says otherwise (plan section
2.5): over a single step of 0.005 h the system is not stiff, and BDF spends
around 84 internal steps on something an Adams method settles in a handful.

Against a BDF run at rtol 1e-12, per simulation step of the E. coli model:

    BDF   rtol 1e-10   4.77 ms   deviation 1.7e-07
    BDF   rtol 1e-08   3.07 ms   deviation 5.7e-06
    BDF   rtol 1e-03   1.18 ms   deviation 2.8e-01   <- MATLAB's default
    RK45  rtol 1e-08   0.94 ms   deviation 8.7e-07
    LSODA rtol 1e-08   0.71 ms   deviation 9.7e-07

LSODA is the choice: as fast as the explicit method while it can be, and it
switches to BDF on its own if a phase does turn stiff — which a pH transient
or a saturating controller may well do. RK45 would only get slower or fail.

The tolerance stays far tighter than MATLAB's own defaults. At rtol 1e-3 the
trajectory moves by 28 %, which says the MATLAB reference run carries solver
error of its own; ours should not add to it.
"""

from collections.abc import Callable

import numpy as np
from scipy.integrate import solve_ivp

METHOD = "LSODA"
RTOL = 1e-8
ATOL = 1e-10


def solve_step(
    fun: Callable[..., np.ndarray],
    dt: float,
    y0: np.ndarray,
    args: tuple = (),
    *,
    method: str = METHOD,
    rtol: float = RTOL,
    atol: float = ATOL,
) -> np.ndarray:
    """Integrate from 0 to dt and return the end state.

    Mirrors MATLAB's ode15s(f, [0 deltat], y0) followed by y(end, :).
    """
    solution = solve_ivp(
        fun,
        (0.0, dt),
        np.asarray(y0, dtype=float),
        method=method,
        args=args,
        rtol=rtol,
        atol=atol,
        dense_output=False,
    )
    if not solution.success:
        raise RuntimeError(f"integration failed: {solution.message}")
    return solution.y[:, -1]


def solve_step_linear(dy: np.ndarray, dt: float, y0: np.ndarray) -> np.ndarray:
    """Exact solution for a balance whose derivative is constant over the step.

    The volume balance is of that kind: FR1, FH, FT1 and FT2 are held fixed
    for the duration of a step, so y(dt) = y0 + dy * dt is the analytic
    result, not an approximation. MATLAB calls ode15s here as well; the
    numbers agree to solver tolerance and this avoids the solver entirely.
    """
    return np.asarray(y0, dtype=float) + np.asarray(dy, dtype=float) * dt
