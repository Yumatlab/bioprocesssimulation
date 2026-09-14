"""What every organism shares (plan section 2.1).

Translated from <Organism>_Initialization.m. Those two files are identical
apart from indentation, the number of reservoirs, acetate for E. coli and the
AOX variables for Pichia — which is exactly the seam the plan draws: controller
states and bioreactor physics here, kinetics and starting values in the model.

The controller signals that MATLAB indexes (app.a.ce_agi(idx) and friends) are
declared as series here, the rest as scalars.
"""

import numpy as np

from ..core.state import SimulationState
from .base import ControlLoop

# Controller signals read at idx - 1 and written at idx. In MATLAB these start
# out as scalars and silently become vectors on the first indexed assignment.
CONTROLLER_SERIES = (
    "ce",  # temperature master
    "cI_Part",
    "ce_agi",  # pO2 via agitation
    "ce_aeration",  # pO2 via aeration
    "ce_gasmix",  # pO2 via gas mixing
    "cI_gasmix",
    "ce_feedpO2",  # pO2 via feed
    "ce_LW",  # liquid weight
    "cI_LW",
    "ce_feedR1",  # substrate controllers, one per reservoir
    "ce_feedR2",
    "ce_feedR3",
)

# Scalar controller states and flags.
CONTROLLER_SCALARS = (
    "cE",
    "cEpH",
    "cP_Part",
    "cE_agi",
    "cP_agi",
    "cI_agi",
    "cD_agi",
    "cE_feedpO2",
    "cP_feedpO2",
    "cI_feedpO2",
    "cD_feedpO2",
    "yfeedpO2",
    "cE_aeration",
    "cP_aeration",
    "cI_aeration",
    "cD_aeration",
    "cE_gasmix",
    "cP_gasmix",
    "cD_gasmix",
    "cE_LW",
    "cE_feedR1",
    "cP_feedR1",
    "cI_feedR1",
    "cD_feedR1",
    "cE_feedR2",
    "cP_feedR2",
    "cI_feedR2",
    "cD_feedR2",
    "cE_feedR3",
    "cP_feedR3",
    "cI_feedR3",
    "cD_feedR3",
)


def init_controller_states(state: SimulationState) -> None:
    """PID states, flags and the inoculation marker."""
    for name in CONTROLLER_SCALARS:
        state.a[name] = 0.0
    for name in CONTROLLER_SERIES:
        state.aux_series(name, 0.0)

    # Cooling and steam mass flux. MATLAB parks these in app.p, but they are
    # controller outputs recomputed every step and are in no database table,
    # so they belong in a.
    state.a.mdotC = 0.0
    state.a.mdotH = 0.0

    state.a.ToI = 0.0  # time of inoculation [h]
    state.a.VLflag = 0  # set once the VLmax warning has been shown
    state.a.VolumeFlag = 0  # VLmax reached
    state.a.inoc_occ = 0  # inoculation has happened
    state.a.pH_negative = False  # the pH iteration ran into xpH < 0
    # May a controller hold its integrator at all? The project decides per
    # controller; this is the installation's veto over all of them, set by the
    # control window out of settings.yaml. True here so that a headless run —
    # a reference run, a test — is never quietly restricted.
    state.a.antiwindup_allowed = True


def init_physical_constants(state: SimulationState) -> None:
    """Bioreactor physics: heat transfer, pressure, pH dissociation, Henry.

    Everything here depends on the bioreactor and the calibration, not on the
    organism.
    """
    p, a = state.p, state.a

    # Temperature system
    a.kCT = 1 / (1 / p.alphaC + p.deltaCT / p.lambdaCT + 1 / p.alphaT)
    a.tauCTc = p.mC * p.cH2O / (a.kCT * p.ACT)
    a.RT = 1 / (p.mdotT * p.cH2O)
    a.DTc = p.mdotT / p.mTc
    a.tauTcC = p.mTc * p.cH2O / (a.kCT * p.ACT)
    a.phiTcC = a.DTc * a.tauTcC
    a.DD = p.mdotT / p.mD
    a.CD = p.mD * p.cH2O + p.mWD * p.cW
    a.kDU = 1 / (1 / p.alphaD + p.deltaDU / p.lambdaDU + 1 / p.alphaU)
    a.tauDU = a.CD / (a.kDU * p.ADU)
    a.kDL = 1 / (1 / p.alphaD + p.deltaDL / p.lambdaDL + 1 / p.alphaL)
    a.tauDL = a.CD / (a.kDL * p.ADL)
    a.tauD = 1 / (a.DD + 1 / a.tauDU + 1 / a.tauDL)
    a.kLU = 1 / (1 / p.alphaL + p.deltaLU / p.lambdaLU + 1 / p.alphaU)
    a.mHmax = p.VH * p.rhoH2O
    a.CHmax = a.mHmax * p.cH2O
    a.kHTh = 1 / (1 / p.alphaH + p.deltaHTh / p.lambdaHTh + 1 / p.alphaTh)
    a.Qny = p.deltahv * a.mHmax
    a.thetaDJ = p.thetaDJ_WP

    # Absolute pressure setpoint [N/m^2]
    a.pGw = p.deltapGw * 1e5 + p.pnG

    # pH system
    a.cCLmax0 = p.pGcal / p.HCO20

    # Dimensionless dissociation constants
    a.ApH = p.KB1 / p.CH0
    a.BpH = a.ApH * p.KB2 / p.CH0
    a.CpH = a.BpH * p.KB3 / p.CH0
    a.DpH = p.KC1 / p.CH0
    a.EpH = a.DpH * p.KC2 / p.CH0
    a.FpH = p.KP1 / p.CH0
    a.GpH = p.KAl / p.CH0
    a.HpH = p.KAc1 / p.CH0
    a.IpH = a.HpH * p.KAc2 / p.CH0

    # Henry constant of O2 at the starting temperature [Nm/kg]
    a.HO2 = henry_o2(p, p.thetaL0)

    # O2 concentration at a pO2 reading of 100 % [g/l]
    a.cOL100 = p.pGcal * p.xOGcal / a.HO2

    # Highest O2 concentration the liquid can reach [g/l]
    a.cOLmax = (p.pGcal + p.deltapGw * 1e5) / a.HO2

    a.xCGin = p.xCGcal


def henry_o2(p, thetaL: float) -> float:
    """O2 Henry constant at a liquid temperature [Nm/kg]."""
    return p.HnO2 / (
        1 + p.K1HO2 * thetaL + p.K2HO2 * thetaL**2 + p.K3HO2 * thetaL**3 + p.K4HO2 * thetaL**4
    )


def henry_co2(p, thetaL: float) -> float:
    """CO2 Henry constant at a liquid temperature [Nm/kg]."""
    return p.HnCO2 / (
        1 + p.K1HCO2 * thetaL + p.K2HCO2 * thetaL**2 + p.K3HCO2 * thetaL**3 + p.K4HCO2 * thetaL**4
    )


def init_common_kinetics(state: SimulationState) -> None:
    """The maintenance and maximum rates both organisms derive the same way."""
    p, a = state.p, state.a
    a.mySm = p.yXpS1gr * p.qS1pXm  # substrate maintenance growth rate [1/h]
    a.myOm = p.yXpOgr * p.qOpXm + a.mySm  # oxygen maintenance growth rate [1/h]
    a.qS1pXmax = (p.my1opt + a.mySm) / p.yXpS1gr
    a.qS2pXmax = (p.my2opt + a.mySm) / p.yXpS2gr
    # MATLAB notes here that my1max is not defined yet and my1opt stands in.
    a.qOpXmax = (p.my1opt + a.mySm) / p.yXpOgr + p.qOpXm


def init_common_variables(state: SimulationState) -> None:
    """Starting values every organism sets the same way.

    Reservoirs, acetate and the induction variables are left to the model.
    """
    p, v, a = state.p, state.v, state.a

    def start(name: str, value: float) -> None:
        state.series(name, float(value))

    start("t", 0.0)

    start("xO2", p.xOAIR * 100)
    start("xCO2", p.xCAIR * 100)

    start("VL", p.VL0)
    start("VT1", p.VT10)
    start("VT2", p.VT20)
    start("Vacid", 0.0)
    start("Vbase", 0.0)
    start("FT1", 0.0)
    start("FT2", 0.0)

    # Inoculation may already have happened before the run starts.
    if p.f_InocStart == 1:
        a.inoc_occ = 1
        start("cXL", p.cXL0)
    else:
        a.inoc_occ = 0
        start("cXL", 0.0)

    start("cS1L", p.cS1L0)
    start("cS2L", p.cS2L0)

    start("thetaL", p.thetaL0)
    start("thetaD", p.thetaD0)
    start("pG", p.pGcal + p.deltapGw * 1e5)

    start("pO2", p.pO20)
    start("cOL", (p.pO20 / 100) * a.cOL100)
    start("pO2w", p.pO2w)
    start("xOL", a.cOL100 / a.cOLmax)

    start("xOG", p.xOGcal)
    start("xOGin", p.xOGcal)
    start("xCG", p.xCGcal)
    start("xCGin", p.xCGcal)

    # cP1X, the intracellular product, is a Pichia state; E. coli has no
    # balance for it and sets only the extracellular one.
    start("cP1L", 0.0)

    start("CB1Ltot", p.CB1Ltot0)
    start("CB2Ltot", p.CB2Ltot0)
    start("CAlLtot", p.CAlLtot0)
    start("CAcLtot", p.CAcLtot0)

    start("hF", 0.0)
    start("AAF", 0.0)

    start("pHL", p.pH0)
    start("pH", p.pH0)

    start("RQ", 0.1)

    start(
        "CCLtot",
        (1 + p.KC1 * 10**p.pH0 + p.KC1 * p.KC2 * 10 ** (2 * p.pH0)) * p.xCAIR * a.cCLmax0 / p.MCO2,
    )

    start("NSt", p.NStw if p.f_motor == 1 else 0.0)

    if p.f_aeration == 1:
        start("FnAIR", p.FnAIRw if p.f_air == 1 else 0.0)
        start("FnO2", p.FnO2w if p.f_O2 == 1 else 0.0)
        start("FnN2", p.FnN2w if p.f_N2 == 1 else 0.0)
        start("FnCO2", p.FnCO2w if p.f_CO2 == 1 else 0.0)
        start("FnG", v.FnAIR[0] + v.FnO2[0] + v.FnN2[0] + v.FnCO2[0])
    else:
        start("FnAIR", 0.0)
        start("FnO2", 0.0)
        start("FnN2", 0.0)
        start("FnCO2", 0.0)
        start("FnG", 0.0)

    start("FH", p.FHrelw / 100 * p.FHmax if p.f_harvest == 1 else 0.0)

    start("OURm", 0.0)
    start("OURmax", 0.0)
    start("QO2max", v.FnG[0] * 60 * p.MO2 / (v.VL[0] * p.VnM))
    start("QCO2max", v.QO2max[0] * p.MCO2 / p.MO2)

    kLa0 = p.kLamin + p.kLamax * ((p.FnGw / p.FnGmax) ** p.beta) * (
        (p.NStw / p.NStmax) ** (3 * p.alpha)
    ) / ((p.VL0 / p.VLmin) ** p.alpha)
    start("kLa", kLa0)
    start("OTRmax", kLa0 * a.cOLmax)
    start("OUR", 0.0)
    start("OTR", v.OTRmax[0] * (p.xOAIR - v.cOL[0] / a.cOLmax))
    start("CTR", 0.0)
    start("qXpX", 0.0)

    # Measured variables, each behind its own first-order lag
    start("pHLm", p.pH0)
    start("thetaLm", p.thetaL0)
    start("pO2m", p.pO20)
    start("cS1Lm", p.cS1L0)
    start("cS2Lm", p.cS2L0)


def meas_transfer_function(
    current_value: float, previous_value: float, tau: float, dt: float
) -> float:
    """First-order lag of a measurement (Additional_functions/meas_transfer_function.m).

    MATLAB divides the sample time by 3600 to go from seconds to hours. dt is
    already in hours here — app.a.deltat is passed in as T — so the conversion
    is carried over unchanged to keep the same numbers.
    """
    K = 1.0
    T = dt / 3600
    return previous_value + (T / tau) * (K * current_value - previous_value)


def integrate(
    previous: float,
    increment: float,
    output: float,
    low: float,
    high: float,
    *,
    active: bool,
) -> float:
    """The integrator's next value, frozen while it would push past a limit.

    Conditional integration, the plainest form of anti-windup: when the
    controller's output already sits outside its range and the new increment
    points further out, the integral keeps the value it had. It resumes the
    moment the error turns round, so the controller reacts at once instead of
    first unwinding.

    `output` is the unclamped sum computed with `previous + increment` — the
    integral has to be part of it, or the test would ask whether the output
    was saturated before this step rather than whether it is now.

    **`active=False` is the MATLAB structure and stays the default.** That
    integrator runs on while the output is stuck at its limit, and the
    verified E. coli run was recorded with it; switching this on changes
    numbers. Which controller does it is a parameter of the project
    (`f_awpO2`, `f_awtemp`, `f_awLW`, `f_awfeed`), and a missing parameter
    means off — an older project computes exactly what it did before.
    """
    if not active:
        return previous + increment
    if output > high and increment > 0:
        return previous
    if output < low and increment < 0:
        return previous
    return previous + increment


def anti_windup(p, a, flag: str) -> bool:
    """Whether this controller may hold its integrator.

    Two switches, and the second can only take away. The project says per
    controller (`p[flag]`); the installation may forbid it for all of them at
    once, and that answer lives in `a` rather than in `p` because it belongs
    to the session, not to the project — written into `p` it would be saved
    and would overwrite the flags the project actually carries.
    """
    return bool(p.get(flag, 0)) and bool(a.get("antiwindup_allowed", True))


def clamp(value: float, low: float, high: float) -> float:
    """The 'if y < a; y = a; elseif y > b; y = b; end' that repeats everywhere."""
    return low if value < low else high if value > high else value


def pt1_filter(error: float, previous: float, dt: float, T: float = 0.001) -> float:
    """The PT1 the controllers put in front of every error signal.

    (e + T/dt * e_prev) / (T/dt + 1), with T = 0.001 h throughout.
    """
    ratio = T / dt
    return (error + ratio * previous) / (ratio + 1)


def positive(values: np.ndarray) -> np.ndarray:
    """Clip an ODE result at zero — no concentration may go negative."""
    return np.where(values < 0, 0.0, values)


#: The control loops both organisms run, in the order the panels stand in.
#:
#: The names are the same in both models — Pichia is a later revision with a
#: different D term and anti-windup, but it taps the same signals. A model
#: whose internals differ declares its own; this is a default, not a rule.
CONTROL_LOOPS = (
    ControlLoop(
        name="pH",
        mode_parameter="Mode_pH",
        mode_value=1,
        setpoint="pHw",
        measurement="pHL",
        error="ce_pH",
        p_share="cP_pH",
        outputs=("FT1", "FT2"),
        output_unit="l/h",
        gains=("KP_pH",),
    ),
    ControlLoop(
        name="Temperature",
        mode_parameter="Mode_temp",
        mode_value=1,
        setpoint="thetaLw",
        measurement="thetaL",
        unit="°C",
        error="ce",
        p_share="cP_Part",
        i_share="cI_Part",
        outputs=("thetaDJ",),
        output_unit="°C",
        gains=("KP_temp1", "KI_temp1"),
    ),
    ControlLoop(
        name="pO2 — agitation",
        mode_parameter="Mode_pO2",
        mode_value=1,
        setpoint="pO2w",
        measurement="pO2",
        unit="%",
        error="ce_agi",
        p_share="cP_agi",
        i_share="cI_agi",
        d_share="cD_agi",
        outputs=("NSt",),
        output_unit="rpm",
        gains=("KP_agi", "KI_agi", "KD_agi"),
    ),
    ControlLoop(
        name="pO2 — aeration",
        mode_parameter="Mode_pO2",
        mode_value=2,
        setpoint="pO2w",
        measurement="pO2",
        unit="%",
        error="ce_aeration",
        p_share="cP_aeration",
        i_share="cI_aeration",
        d_share="cD_aeration",
        outputs=("FnAIR", "FnO2"),
        output_unit="l/min",
        gains=("KP_aeration", "KI_aeration", "KD_aeration"),
    ),
    ControlLoop(
        name="pO2 — gas mixing",
        mode_parameter="Mode_pO2",
        mode_value=3,
        setpoint="pO2w",
        measurement="pO2",
        unit="%",
        error="ce_gasmix",
        p_share="cP_gasmix",
        i_share="cI_gasmix",
        d_share="cD_gasmix",
        outputs=("FnAIR", "FnO2", "xOGin"),
        output_unit="",
        gains=("KP_gasmix", "KI_gasmix", "KD_gasmix"),
    ),
    ControlLoop(
        name="pO2 — feed",
        mode_parameter="Mode_pO2",
        mode_value=4,
        setpoint="pO2w",
        measurement="pO2",
        unit="%",
        error="ce_feedpO2",
        p_share="cP_feedpO2",
        i_share="cI_feedpO2",
        d_share="cD_feedpO2",
        outputs=("FR1",),
        output_unit="l/h",
        gains=("KP_feedpO2", "KI_feedpO2", "KD_feedpO2"),
    ),
    ControlLoop(
        name="Liquid weight",
        mode_parameter="Mode_harvest",
        mode_value=1,
        setpoint="LWw",
        measurement="VL",
        unit="kg",
        error="ce_LW",
        p_share="cP_LW",
        i_share="cI_LW",
        d_share="cD_LW",
        outputs=("FH",),
        output_unit="l/h",
        gains=("KP_LW", "KI_LW", "KD_LW"),
    ),
    ControlLoop(
        name="Feed R{n}",
        mode_parameter="Mode_feed",
        mode_value=1,
        setpoint="cS{n}Lw",
        measurement="cS{n}L",
        unit="g/l",
        error="ce_feedR{n}",
        p_share="cP_feedR{n}",
        i_share="cI_feedR{n}",
        d_share="cD_feedR{n}",
        outputs=("FR{n}",),
        output_unit="l/h",
        gains=("KP_feedR{n}", "KI_feedR{n}", "KD_feedR{n}"),
    ),
)
