"""E. coli balance equations.

Translated from Escherichia_ODE_Volume.m and Escherichia_ODE_Luttmann.m. The
state order of each vector is the one MATLAB passes to ode15s and is what the
model relies on when it reads the result back — do not reorder.
"""

from dataclasses import dataclass

import numpy as np

# Volume state vector, in MATLAB's order.
VOLUME_STATES = ("VL", "VR1", "VT2", "VT1")

# Concentration state vector, in MATLAB's order.
CONCENTRATION_STATES = (
    "cXL",
    "cS1L",
    "cS2L",
    "cP1L",
    "cOL",
    "pO2",
    "CB1Ltot",
    "CB2Ltot",
    "CAcLtot",
    "CAlLtot",
    "CCLtot",
    "pH",
    "xO2",
    "xCO2",
    "hF",
    "AAF",
    "thetaD",
    "thetaL",
)


def ode_volume(
    t: float, y: np.ndarray, FR1: float, FH: float, FT1: float, FT2: float
) -> np.ndarray:
    """Liquid and reservoir volumes [l/h]. Harvest is not fed back yet."""
    return np.array(
        [
            FR1 + FT1 + FT2 - FH,  # liquid volume
            -FR1,  # substrate reservoir
            -FT2,  # pH base reservoir
            -FT1,  # pH acid reservoir
        ]
    )


@dataclass
class LuttmannTerms:
    """Everything the concentration balance needs that is constant over a step.

    MATLAB passes these as 54 positional arguments to Escherichia_ODE_Luttmann.
    Naming them costs nothing at runtime and makes the call site checkable.
    """

    qXpX: float
    Din: float
    cS1R1: float
    qS1pX: float
    cS2R1: float
    qS2pX: float
    cP1R1: float
    qP1pX: float
    MP1: float
    cOT1: float
    cOT2: float
    cOR1: float
    OTR: float
    OUR: float
    cOL100: float
    TMpO2: float
    DT1: float
    CAcT1tot: float
    qAcpX: float
    MAc: float
    DT2: float
    CAlT2tot: float
    qAlpX: float
    AlTR: float
    MAl: float
    DR1: float
    CCR1tot: float
    CCT1tot: float
    CCT2tot: float
    CTR: float
    CER: float
    MCO2: float
    pHL: float
    TMpH: float
    TMxO2: float
    xOG: float
    TMxCO2: float
    xCG: float
    lamdaF: float
    qhpX: float
    lamdaAF: float
    AAFin: float
    tauD: float
    DD: float
    thetaTc: float
    tauDL: float
    thetaU: float
    tauDU: float
    tauL: float
    tauLD: float
    tauLU: float
    QdotM: float
    QdotSt: float
    CL: float


def ode_luttmann(t: float, y: np.ndarray, c: LuttmannTerms) -> np.ndarray:
    """The eighteen concentration, gas, foam and temperature balances."""
    dy = np.empty(18)

    dy[0] = (c.qXpX - c.Din) * y[0]  # cell concentration
    dy[1] = c.DR1 * c.cS1R1 - c.Din * y[1] - c.qS1pX * y[0]  # glucose
    dy[2] = c.DR1 * c.cS2R1 - c.Din * y[2] - c.qS2pX * y[0]  # glycerol
    dy[3] = c.DR1 * c.cP1R1 - c.Din * y[3] + c.qP1pX * y[0]  # product
    dy[4] = (  # dissolved O2
        c.DR1 * c.cOR1 + c.DT1 * c.cOT1 + c.DT2 * c.cOT2 - c.Din * y[4] + c.OTR - c.OUR
    )
    dy[5] = ((y[4] / c.cOL100) * 100 - y[5]) / c.TMpO2  # pO2 reading
    dy[6] = -c.Din * y[6]  # buffer acid [mol/(l*h)]
    dy[7] = -c.Din * y[7]  # buffer base [mol/(l*h)]
    dy[8] = c.DT1 * c.CAcT1tot - c.Din * y[8] - c.qAcpX * y[0] / c.MAc  # titration acid
    dy[9] = (  # ammonia
        c.DT2 * c.CAlT2tot - c.Din * y[9] - (c.qAlpX * y[0] + c.AlTR) / c.MAl
    )
    dy[10] = (  # dissolved CO2
        c.DR1 * c.CCR1tot
        + c.DT1 * c.CCT1tot
        + c.DT2 * c.CCT2tot
        - c.Din * y[10]
        + (c.CTR + c.CER) / c.MCO2
    )
    dy[11] = (c.pHL - y[11]) / c.TMpH  # pH with measurement dynamics
    dy[12] = (c.xOG * 100 - y[12]) / c.TMxO2  # O2 in offgas
    dy[13] = (c.xCG * 100 - y[13]) / c.TMxCO2  # CO2 in offgas
    dy[14] = c.lamdaF * y[14] + c.qhpX * y[0]  # relative foam height
    dy[15] = c.lamdaAF * y[15] + c.AAFin  # anti foam activity
    dy[16] = (  # double jacket temperature [°C/h]
        -y[16] / c.tauD + c.DD * c.thetaTc + y[17] / c.tauDL + c.thetaU / c.tauDU
    )
    dy[17] = (  # liquid phase temperature [°C/h]
        -y[17] / c.tauL + y[16] / c.tauLD + c.thetaU / c.tauLU + (c.QdotM + c.QdotSt) / c.CL
    )
    return dy
