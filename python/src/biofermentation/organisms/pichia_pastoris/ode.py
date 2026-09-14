"""Pichia pastoris balance equations.

Translated from Pichia_ODE_Volume.m, Pichia_ODE_Luttmann.m,
Pichia_Induction_Cornelissen.m and Pichia_Expression_Cornelissen.m.

Two reservoirs (R1 glycerol, R2 methanol) make the volume vector five states
long, and the product appears twice — inside the cell and in the liquid — so
the concentration vector has nineteen states rather than E. coli's eighteen.
"""

from dataclasses import dataclass

import numpy as np

VOLUME_STATES = ("VL", "VR1", "VR2", "VT2", "VT1")

CONCENTRATION_STATES = (
    "cXL",
    "cS1L",
    "cS2L",
    "cP1X",
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

INDUCTION_STATES = ("qS2pXscript", "qS2pXtrans", "qS2pXact")
EXPRESSION_STATES = ("qP1pXscript", "qP1pXtrans", "qP1pXact")


def ode_volume(
    t: float, y: np.ndarray, FR1: float, FR2: float, FH: float, FT1: float, FT2: float
) -> np.ndarray:
    """Liquid volume and the four reservoirs [l/h]."""
    return np.array(
        [
            FR1 + FR2 + FT1 + FT2 - FH,  # liquid volume
            -FR1,  # glycerol reservoir
            -FR2,  # methanol reservoir
            -FT2,  # pH base reservoir
            -FT1,  # pH acid reservoir
        ]
    )


@dataclass
class LuttmannTerms:
    """Constants of one step for the concentration balance."""

    qXpX: float
    Din: float
    cS1R1: float
    qS1pX: float
    cS2R1: float
    qS2pX: float
    cS1R2: float
    cS2R2: float
    cP1R1: float
    cP1R2: float
    qP1pX: float
    kP1alpha: float
    cOT1: float
    cOT2: float
    cOR1: float
    cOR2: float
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
    DR2: float
    CCRtot: float
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
    """The nineteen concentration, gas, foam and temperature balances."""
    dy = np.empty(19)

    dy[0] = (c.qXpX - c.Din) * y[0]  # cells
    dy[1] = c.DR1 * c.cS1R1 + c.DR2 * c.cS1R2 - c.Din * y[1] - c.qS1pX * y[0]  # glycerol
    dy[2] = c.DR1 * c.cS2R1 + c.DR2 * c.cS2R2 - c.Din * y[2] - c.qS2pX * y[0]  # methanol
    dy[3] = c.qP1pX * y[0] - c.Din * y[3] - c.kP1alpha * y[3]  # product in the cell
    dy[4] = (  # product in the liquid
        c.DR1 * c.cP1R1 + c.DR2 * c.cP1R2 + c.kP1alpha * y[3] - c.Din * y[4]
    )
    dy[5] = (  # dissolved O2
        c.DR1 * c.cOR1
        + c.DR2 * c.cOR2
        + c.DT1 * c.cOT1
        + c.DT2 * c.cOT2
        - c.Din * y[5]
        + c.OTR
        - c.OUR
    )
    dy[6] = ((y[5] / c.cOL100) * 100 - y[6]) / c.TMpO2  # pO2 reading
    dy[7] = -c.Din * y[7]  # buffer acid
    dy[8] = -c.Din * y[8]  # buffer base
    dy[9] = c.DT1 * c.CAcT1tot - c.Din * y[9] - c.qAcpX * y[0] / c.MAc  # titration acid
    dy[10] = c.DT2 * c.CAlT2tot - c.Din * y[10] - (c.qAlpX * y[0] + c.AlTR) / c.MAl  # ammonia
    dy[11] = (  # dissolved CO2. The original notes that CCR1tot and CCR2tot
        # should be told apart here; it passes one reservoir's value for both.
        c.DR1 * c.CCRtot
        + c.DT1 * c.CCT1tot
        + c.DT2 * c.CCT2tot
        - c.Din * y[11]
        + (c.CTR + c.CER) / c.MCO2
    )
    dy[12] = (c.pHL - y[12]) / c.TMpH  # pH with measurement dynamics
    dy[13] = (c.xOG * 100 - y[13]) / c.TMxO2  # O2 in offgas
    dy[14] = (c.xCG * 100 - y[14]) / c.TMxCO2  # CO2 in offgas
    dy[15] = c.lamdaF * y[15] + c.qhpX * y[0]  # foam height
    dy[16] = c.lamdaAF * y[16] + c.AAFin  # anti foam activity
    dy[17] = -y[17] / c.tauD + c.DD * c.thetaTc + y[18] / c.tauDL + c.thetaU / c.tauDU
    dy[18] = -y[18] / c.tauL + y[17] / c.tauLD + c.thetaU / c.tauLU + (c.QdotM + c.QdotSt) / c.CL
    return dy


def ode_induction(
    t: float,
    y: np.ndarray,
    qXpX: float,
    qS2pXind: float,
    aS2script: float,
    aS2trans: float,
    aS2act: float,
    bS2script: float,
    bS2trans: float,
    bS2act: float,
) -> np.ndarray:
    """AOX induction after Cornelissen: transcription, translation, activity."""
    return np.array(
        [
            -(aS2script + qXpX) * y[0] + bS2script * qS2pXind,
            -(aS2trans + qXpX) * y[1] + bS2trans * y[0],
            -(aS2act + qXpX) * y[2] + bS2act * y[1],
        ]
    )


def ode_expression(
    t: float,
    y: np.ndarray,
    qXpX: float,
    qP1pXind: float,
    qP1pXback: float,
    aP1script: float,
    aP1trans: float,
    kP1alpha: float,
    bP1script: float,
    bP1trans: float,
    bP1act: float,
) -> np.ndarray:
    """Target protein expression after Cornelissen.

    qP1pXback is the output of the PI controller on the transcription rate and
    is held constant over the step; the model computes it before integrating.
    """
    return np.array(
        [
            -(aP1script + qXpX) * y[0] + bP1script * (qP1pXind + qP1pXback),
            -(aP1trans + qXpX) * y[1] + bP1trans * y[0],
            -(kP1alpha + qXpX) * y[2] + bP1act * y[1],
        ]
    )
