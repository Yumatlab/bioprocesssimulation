"""Pichia pastoris — two reservoirs, 19 ODE states, AOX induction.

Line-by-line translation of Pichia_pastoris.m.

Pichia is not simply E. coli with a second reservoir. Its MATLAB file is a
later revision of the same code and the controllers differ in substance:

  * the PID terms read the error at idx - 1 and idx - 2 where E. coli reads
    idx and idx - 1, so the whole loop runs one step further behind;
  * the agitation controller takes its derivative from the measurement
    instead of the error, which removes the derivative kick on a setpoint
    change, and clamps its integral term (anti-windup);
  * the closed-loop feed controller uses the measured concentration cS{n}Lm
    rather than the true one;
  * the aeration rates are summed from idx - 1 rather than the values just
    written.

None of that is unified here. Both files are the reference for their own
organism, and reconciling them is a decision for after the reference runs
exist, not a translation detail.
"""

import numpy as np

from ...core.integrate import solve_step, solve_step_linear
from ...core.state import SimulationState
from ..base import OrganismMetadata, OrganismModel
from ..registry import register
from ..shared import (
    clamp,
    henry_co2,
    henry_o2,
    init_common_kinetics,
    init_common_variables,
    init_controller_states,
    init_physical_constants,
    meas_transfer_function,
    pt1_filter,
)
from .ode import LuttmannTerms, ode_expression, ode_induction, ode_luttmann, ode_volume


@register
class PichiaPastoris(OrganismModel):
    metadata = OrganismMetadata(
        name="pichia_pastoris",
        display_name="Pichia pastoris",
        n_reservoirs=2,
        description=(
            "Glycerol and methanol on two reservoirs, AOX induction and product "
            "expression after Cornelissen; 19 ODE states."
        ),
        version="2.2",
    )

    # ------------------------------------------------------------ setup --

    def init_controller_states(self, state: SimulationState) -> None:
        init_controller_states(state)

    def init_physical_constants(self, state: SimulationState) -> None:
        init_physical_constants(state)
        state.a.numReservoir = self.metadata.n_reservoirs

    def init_kinetics(self, state: SimulationState) -> None:
        init_common_kinetics(state)
        p = state.p
        for reservoir in (1, 2):
            for name in (f"t{reservoir}j", f"FR{reservoir}j"):
                p.setdefault(name, 0.0)

    def init_variables(self, state: SimulationState) -> None:
        init_common_variables(state)
        p, v = state.p, state.v

        # Two reservoirs: R1 glycerol, R2 methanol. Both pumps start at their
        # setpoint here, unlike E. coli which starts at zero.
        state.series("VR1", p.VR10)
        state.series("VR1in", 0.0)
        state.series("FR1", p.FR1w)
        state.series("VR2", p.VR20)
        state.series("VR2in", 0.0)
        state.series("FR2", p.FR2w)

        # Product inside the cell — a state E. coli does not have.
        state.series("cP1X", 0.0)

        state.series("QS1in", (v.FR1[0] * p.cS1R1 + v.FR2[0] * p.cS1R2) / v.VL[0])
        state.series("QS2in", (v.FR1[0] * p.cS2R1 + v.FR2[0] * p.cS2R2) / v.VL[0])

        # AOX induction
        for name in ("qS2pXind", "qS2pXscript", "qP1pXscriptw", "qS2pXtrans", "qS2pXact", "qS2pX"):
            state.series(name, 0.0)
        # Product expression
        for name in ("qP1pXind", "qP1pXback", "qP1pXscript", "qP1pXtrans", "qP1pXact", "qP1pX"):
            state.series(name, 0.0)

    # ------------------------------------------------------------- step --

    def calculate_step(self, state: SimulationState) -> None:
        prev = state.idx
        i = prev + 1
        state.ensure_capacity(i)

        p, v, a = state.p, state.v, state.a
        dt = state.dt

        self._feeding(state, prev, i)
        self._po2_control(state, prev, i)
        self._aeration(state, prev, i)
        self._liquid_weight(state, prev, i)

        # Mole fraction at the inlet. Pichia tests FnG at idx, E. coli at
        # idx - 1.
        if v.FnG[i] > 0:
            v.xOGin[i] = (p.xOAIR * v.FnAIR[i] + v.FnO2[i]) / v.FnG[i]
        else:
            v.xOGin[i] = 0.0

        AAFin = self._antifoam(state, prev)
        self._ph_control(state, prev, i)
        PH = self._temperature_control(state, prev, i)

        lamdaF = -v.AAF[prev] / p.tauF0 / (1 + p.KFpX * v.cXL[prev])
        lamdaAF = -v.cXL[prev] / p.KAF

        DR1, DR2, DT1, DT2 = self._volume(state, prev, i)
        Din = DR1 + DR2 + DT1 + DT2

        TL = v.thetaL[prev] + p.TnG
        if v.thetaL[prev] < 100:
            v.pG[i] = a.pGw
        else:
            ExppDL = 10.9 - 2461 / TL - 2.065 * np.log10(v.thetaL[prev] / p.TnG)
            v.pG[i] = 9.8067 * 10**ExppDL
        a.deltapG = (v.pG[prev] - p.pnG) / 1e5

        self._respiration_quotient(state, prev, i)
        CHL = self._ph_iteration(state, prev, i)
        qXpXgr, my2max, qS1pXopt = self._growth(state, prev, i, CHL)

        qS1pX = min(qXpXgr / p.yXpS1gr, qS1pXopt)
        qS2pX = self._induction(state, prev, i, my2max)
        self._expression(state, prev, i, my2max)

        qAlpX = p.yAlpXgr * qXpXgr
        qAcpX = p.yAcpXgr * qXpXgr
        qOpX = qXpXgr / p.yXpOgr + p.qOpXm

        v.OUR[i] = qOpX * v.cXL[prev] if p.f_Inoc == 1 else 0.0
        CER = p.yCpO * v.OUR[prev]
        AlTR = -p.KAlvol * v.FnG[prev] * v.CAlLtot[prev] * p.MAl / v.VL[prev]

        thetaTc, tauL, tauLD, tauLU, QdotM, QdotSt, CL = self._temperature_system(state, prev, PH)

        terms = LuttmannTerms(
            qXpX=v.qXpX[prev],
            Din=Din,
            cS1R1=p.cS1R1,
            qS1pX=qS1pX,
            cS2R1=p.cS2R1,
            qS2pX=qS2pX,
            cS1R2=p.cS1R2,
            cS2R2=p.cS2R2,
            cP1R1=p.cP1R1,
            cP1R2=p.cP1R2,
            qP1pX=v.qP1pX[prev],
            kP1alpha=p.kP1alpha,
            cOT1=p.cOT1,
            cOT2=p.cOT2,
            cOR1=p.cOR1,
            cOR2=p.cOR2,
            OTR=v.OTR[prev],
            OUR=v.OUR[prev],
            cOL100=a.cOL100,
            TMpO2=p.TMpO2,
            DT1=DT1,
            CAcT1tot=p.CAcT1tot,
            qAcpX=qAcpX,
            MAc=p.MAc,
            DT2=DT2,
            CAlT2tot=p.CAlT2tot,
            qAlpX=qAlpX,
            AlTR=AlTR,
            MAl=p.MAl,
            DR1=DR1,
            DR2=DR2,
            CCRtot=p.CCR1tot,
            CCT1tot=p.CCT1tot,
            CCT2tot=p.CCT2tot,
            CTR=v.CTR[prev],
            CER=CER,
            MCO2=p.MCO2,
            pHL=v.pHL[prev],
            TMpH=p.TMpH,
            TMxO2=p.TMxO2,
            xOG=v.xOG[prev],
            TMxCO2=p.TMxCO2,
            xCG=v.xCG[prev],
            lamdaF=lamdaF,
            qhpX=p.qhpX,
            lamdaAF=lamdaAF,
            AAFin=AAFin,
            tauD=a.tauD,
            DD=a.DD,
            thetaTc=thetaTc,
            tauDL=a.tauDL,
            thetaU=p.thetaU,
            tauDU=a.tauDU,
            tauL=tauL,
            tauLD=tauLD,
            tauLU=tauLU,
            QdotM=QdotM,
            QdotSt=QdotSt,
            CL=CL,
        )

        y0 = np.array(
            [
                v.cXL[prev],
                v.cS1L[prev],
                v.cS2L[prev],
                v.cP1X[prev],
                v.cP1L[prev],
                v.cOL[prev],
                v.pO2[prev],
                v.CB1Ltot[prev],
                v.CB2Ltot[prev],
                v.CAcLtot[prev],
                v.CAlLtot[prev],
                v.CCLtot[prev],
                v.pH[prev],
                v.xO2[prev],
                v.xCO2[prev],
                v.hF[prev],
                v.AAF[prev],
                v.thetaD[prev],
                v.thetaL[prev],
            ]
        )
        y = solve_step(ode_luttmann, dt, y0, args=(terms,))
        y = np.where(y < 0, 0.0, y)

        if p.f_Inoc == 1 and a.inoc_occ == 0:
            v.cXL[i] = p.cXL0
            a.ToI = v.t[prev]
            a.inoc_occ = 1
        else:
            v.cXL[i] = y[0]

        v.cS1L[i] = y[1]
        v.cS2L[i] = y[2]
        v.cP1X[i] = y[3]
        v.cP1L[i] = y[4]
        v.cOL[i] = y[5]
        v.pO2[i] = y[6]
        v.CB1Ltot[i] = y[7]
        v.CB2Ltot[i] = y[8]
        v.CAcLtot[i] = y[9]
        v.CAlLtot[i] = y[10]
        v.CCLtot[i] = y[11]
        v.pH[i] = y[12]
        v.xO2[i] = y[13]
        v.xCO2[i] = y[14]
        v.hF[i] = y[15]
        v.AAF[i] = y[16]
        v.thetaD[i] = y[17]
        v.thetaL[i] = y[18]

        if v.thetaL[prev] > 100.0:
            v.thetaL[prev] = 100.0
            a.temperature_exceeded = True

        v.QS1in[i] = (v.FR1[prev] * p.cS1R1 + v.FR2[prev] * p.cS1R2) / v.VL[i]
        v.QS2in[i] = (v.FR1[prev] * p.cS2R1 + v.FR2[prev] * p.cS2R2) / v.VL[i]

        v.pHLm[i] = meas_transfer_function(v.pHL[prev], v.pHLm[prev], p.taupHL, dt)
        v.pO2m[i] = meas_transfer_function(v.pO2[prev], v.pO2m[prev], p.taupO2, dt)
        v.thetaLm[i] = meas_transfer_function(v.thetaL[prev], v.thetaLm[prev], p.tauthetaL, dt)
        v.cS1Lm[i] = meas_transfer_function(v.cS1L[prev], v.cS1Lm[prev], p.taucS1L, dt)
        v.cS2Lm[i] = meas_transfer_function(v.cS2L[prev], v.cS2Lm[prev], p.taucS2L, dt)

        v.t[i] = v.t[prev] + dt

        if v.VL[prev] >= p.VLmax:
            a.VolumeFlag = 1

        # Variables this model never recomputes keep their previous value
        # instead of turning into a gap. See SimulationState.carry_forward.
        a.carried_forward = state.carry_forward(i)

        state.idx = i

    # --------------------------------------------------------- feeding --

    def _feeding(self, state: SimulationState, prev: int, i: int) -> None:
        p, v, a = state.p, state.v, state.a
        dt = state.dt
        back = max(prev - 1, 0)  # MATLAB's end-1

        v.FR1[i] = 0.0
        v.FR2[i] = 0.0

        if a.get("switch_exp", False):
            # The reservoir comes from R_feed here; E. coli hardcodes 1.
            k = int(p.R_feed)
            FR = p[f"FR{k}j"] * np.exp(p[f"qXpX{k}w"] * (v.t[prev] - p[f"t{k}j"]))
            if FR < p[f"FR{k}max"]:  # noqa: SIM300
                v[f"FR{k}"][i] = FR
            else:
                a.switch_exp = False
                a.feed_limit_hit = k
            return

        if a.get("switch_pulse", False):
            k = int(p.R_feed)
            v[f"FR{k}"][i] = p[f"FR{k}max"] * p[f"kR{k}"]
            return

        if p.Mode_pO2 == 4:
            cEfeedpO2 = p.pO2w - v.pO2[prev]
            a.cE_feedpO2 = pt1_filter(cEfeedpO2, a.cE_feedpO2, dt)
            a.ce_feedpO2[i] = a.cE_feedpO2 / (100 - 0)

            # One step further behind than E. coli.
            a.cP_feedpO2 = a.ce_feedpO2[prev] * p.KP_feedpO2
            a.cI_feedpO2 = (
                a.cI_feedpO2 + (a.ce_feedpO2[prev] + a.ce_feedpO2[back]) / 2 * dt * p.KI_feedpO2
            )
            a.cD_feedpO2 = (a.ce_feedpO2[prev] - a.ce_feedpO2[back]) / dt * p.KD_feedpO2

            a.yfeedpO2 = ((a.cP_feedpO2 + a.cI_feedpO2 + a.cD_feedpO2) * 100 + a.yfeedpO2) / 2
            a.yfeedpO2 = clamp(a.yfeedpO2, 0.0, 100.0)
            v.FR1[i] = a.yfeedpO2 / 100 * p.FR1max
            return

        if p.f_feed == 1:
            n = int(p.R_feed)
            if p.Mode_feed == 0:
                v[f"FR{n}"][i] = p[f"FR{n}w"]
            elif p.Mode_feed == 1:
                # The measured concentration is the controlled variable here,
                # not the true one as in E. coli.
                cSLw = p[f"cS{n}Lw"]
                cSL = v[f"cS{n}Lm"][prev]
                cSLwmax = p[f"cS{n}R{n}"] * 0.2
                cSLwmin = 0.01

                cEfeedR = cSLw - cSL
                a[f"cE_feedR{n}"] = pt1_filter(cEfeedR, a[f"cE_feedR{n}"], dt)
                a[f"ce_feedR{n}"][i] = a[f"cE_feedR{n}"] / (cSLwmax - cSLwmin)

                a[f"cP_feedR{n}"] = a[f"ce_feedR{n}"][prev] * p[f"KP_feedR{n}"]
                a[f"cI_feedR{n}"] = (
                    a[f"cI_feedR{n}"]
                    + (a[f"ce_feedR{n}"][prev] + a[f"ce_feedR{n}"][back])
                    / 2
                    * dt
                    * p[f"KI_feedR{n}"]
                )
                a[f"cD_feedR{n}"] = (
                    (a[f"ce_feedR{n}"][prev] - a[f"ce_feedR{n}"][back]) / dt * p[f"KD_feedR{n}"]
                )

                yFR = clamp(a[f"cP_feedR{n}"] + a[f"cI_feedR{n}"] + a[f"cD_feedR{n}"], 0.0, 1.0)
                v[f"FR{n}"][i] = p[f"FR{n}max"] * yFR

    # ----------------------------------------------------- pO2 control --

    def _po2_control(self, state: SimulationState, prev: int, i: int) -> None:
        p, v, a = state.p, state.v, state.a
        dt = state.dt
        back = max(prev - 1, 0)

        if p.f_aeration == 1:
            v.FnN2[i] = p.FnN2w if p.f_N2 == 1 else 0.0
            v.FnCO2[i] = p.FnCO2w if p.f_CO2 == 1 else 0.0

        if p.Mode_pO2 == 1:  # agitation
            cEagi = p.pO2w - v.pO2[prev]
            a.cE_agi = pt1_filter(cEagi, a.cE_agi, dt)
            a.ce_agi[i] = a.cE_agi / (100 - 1)

            a.cP_agi = a.ce_agi[prev] * p.KP_agi
            a.cI_agi = a.cI_agi + (a.ce_agi[prev] + a.ce_agi[back]) / 2 * dt * p.KI_agi
            # Derivative on the measurement, not on the error: a setpoint
            # change no longer produces a derivative kick.
            a.cD_agi = -p.KD_agi * (v.pO2[prev] - v.pO2[back]) / dt

            yNSt = clamp(a.cP_agi + a.cI_agi + a.cD_agi, 0.3, 1.0)
            # Anti-windup with the wrong unit, reproduced from the original:
            # cI_agi is a normalised term that yNSt clamps to [0.3, 1], but
            # the limit here is NStmax in rpm. The upper bound of 1500 can
            # never bind; the lower bound of 0 does, and it stops the integral
            # from ever going negative. With KI_agi = 1000 and dt = 0.005 that
            # lets pO2 overshoot far past 100 %. Whether the MATLAB run shows
            # the same is a question for the reference run.
            a.cI_agi = clamp(a.cI_agi, 0.0, p.NStmax)
            v.NSt[i] = yNSt * p.NStmax

        elif p.Mode_pO2 == 2:  # aeration
            cEaeration = p.pO2w - v.pO2[prev]
            a.cE_aeration = pt1_filter(cEaeration, a.cE_aeration, dt)
            a.ce_aeration[i] = a.cE_aeration / (100 - 1)

            a.cP_aeration = a.ce_aeration[prev] * p.KP_aeration
            a.cI_aeration = (
                a.cI_aeration + (a.ce_aeration[i] + a.ce_aeration[prev]) / 2 * dt * p.KI_aeration
            )
            a.cD_aeration = (a.ce_aeration[i] - a.ce_aeration[prev]) / dt * p.KD_aeration

            yaeration = (a.cP_aeration + a.cI_aeration + a.cD_aeration) * 100
            diff = 0.0
            if yaeration < 30:
                yaeration = 30.0
            elif yaeration > 100:
                diff = min(yaeration - 100, 100.0)
                yaeration = 100.0

            v.FnAIR[i] = yaeration / 100 * p.FnAIRmax
            v.FnO2[i] = diff / 100 * p.FnO2max
            # Corrected: summed from this step, not the one before. See the
            # note in _aeration.
            v.FnG[i] = v.FnAIR[i] + v.FnO2[i] + v.FnN2[i] + v.FnCO2[i]

        elif p.Mode_pO2 == 3:  # gas mixing
            cEgasmix = p.pO2w - v.pO2[prev]
            a.cE_gasmix = pt1_filter(cEgasmix, a.cE_gasmix, dt)
            a.ce_gasmix[i] = a.cE_gasmix / (1 - p.xOAIR)

            a.cP_gasmix = a.ce_gasmix[prev] * p.KP_gasmix
            a.cI_gasmix[i] = (
                a.cI_gasmix[prev] + (a.ce_gasmix[prev] + a.ce_gasmix[back]) / 2 * dt * p.KI_gasmix
            )
            a.cD_gasmix = (a.ce_gasmix[prev] - a.ce_gasmix[back]) / dt * p.KD_gasmix

            ygasmix = (a.cP_gasmix + a.cI_gasmix[prev] + a.cD_gasmix) * 100
            ygasmix = clamp(ygasmix, p.xOAIR * 100, 100.0)
            xOGinw = ygasmix / 100

            v.FnAIR[i] = (p.FnGw * (xOGinw - 1)) / (p.xOAIR - 1)
            # Corrected, not reproduced. The original computes the oxygen
            # flow from the *previous* step's air flow:
            #
            #     app.v.FnO2(idx) = app.p.FnGw - app.v.FnAIR(previdx);
            #       % HIER NOCHMAL CHECKEN
            #
            # — the author's own note sits on that line. Mixing a current
            # setpoint with a previous flow makes the mixture impossible for
            # one step after every change: asked for pure oxygen, FnAIR
            # correctly goes to zero and FnO2 then comes out as
            # FnGw - FnGw = 0, so the gas is switched off at the moment of
            # highest demand — 27 of 2000 steps in a measured run. On the way
            # there the flow goes negative and xOGin leaves [0, 1].
            #
            # The gas mixing branch is outside the verified window: the
            # reference run is Mode_pO2 = 1. See CLAUDE.md.
            v.FnO2[i] = p.FnGw - v.FnAIR[i]
            # And the total from this step, not the one before. See the note
            # in _aeration.
            v.FnG[i] = v.FnAIR[i] + v.FnO2[i] + v.FnN2[i] + v.FnCO2[i]

        if p.Mode_pO2 != 1:
            v.NSt[i] = p.NStw if p.f_motor == 1 else 0.0

    def _aeration(self, state: SimulationState, prev: int, i: int) -> None:
        p, v = state.p, state.v
        if p.Mode_pO2 in (2, 3):
            return
        if p.f_aeration == 1:
            v.FnAIR[i] = p.FnAIRw if p.f_air == 1 else 0.0
            v.FnO2[i] = p.FnO2w if p.f_O2 == 1 else 0.0
            # Corrected: summed from this step, not the one before.
            #
            # The Pichia source writes previdx at all three places where it
            # totals the gas — here and in both pO2 control branches — while
            # the E. coli source, the one the verification rests on, writes
            # idx at all three. xOGin divides this total using the current
            # component flows, so summing the previous ones puts a mixture in
            # the balance that was never fed: measured, xOGin dropped to 0.079
            # where nothing but air and oxygen were flowing and 0.209 is the
            # floor.
            v.FnG[i] = v.FnAIR[i] + v.FnO2[i] + v.FnN2[i] + v.FnCO2[i]
        else:
            v.FnG[i] = 0.0

    def _liquid_weight(self, state: SimulationState, prev: int, i: int) -> None:
        p, v, a = state.p, state.v, state.a
        dt = state.dt

        if p.Mode_harvest == 1:
            cELW = v.VL[prev] * p.rhoL - p.LWw
            a.cE_LW = pt1_filter(cELW, a.cE_LW, dt)
            a.ce_LW[i] = a.cE_LW / (p.VLmax * p.rhoL - p.VLmin * p.rhoL)

            cP_LW = a.ce_LW[i] * p.KP_LW
            a.cI_LW[i] = a.cI_LW[prev] + (a.ce_LW[i] + a.ce_LW[prev]) / 2 * dt * p.KI_LW
            cD_LW = (a.ce_LW[i] - a.ce_LW[prev]) / dt * p.KD_LW

            yLW = clamp((cP_LW + a.cI_LW[i] + cD_LW) * 100, 0.0, 100.0)
            v.FH[i] = yLW / 100 * p.FHmax
        else:
            v.FH[i] = p.FHrelw / 100 * p.FHmax if p.f_harvest == 1 else 0.0

    def _antifoam(self, state: SimulationState, prev: int) -> float:
        p, v, a = state.p, state.v, state.a
        if p.f_antifoam == 1 and a.ToI != 0:
            TON = v.t[prev] - a.ToI
            return p.AAFtast * p.VAF ** (TON / p.Ttast)
        return 0.0

    def _ph_control(self, state: SimulationState, prev: int, i: int) -> None:
        p, v, a = state.p, state.v, state.a
        dt = state.dt

        if p.Mode_pH == 0:
            v.FT2[i] = p.FT2max if p.f_alkali == 1 else 0.0
            v.FT1[i] = p.FT1max if p.f_acid == 1 else 0.0
            return
        if p.Mode_pH != 1:
            return

        if abs(p.pHw - v.pHL[prev]) < 0.1:
            v.FT1[i] = 0.0
            v.FT2[i] = 0.0
            return

        epH = p.pHw - v.pHL[prev]
        a.cEpH = pt1_filter(epH, a.cEpH, dt)
        cepH = a.cEpH / (p.pHLmaxgr - p.pHLmingr)
        ypH = clamp(cepH * p.KP_pH * 100, -100.0, 100.0)

        cEypH = p.ypH_SET - (ypH / 100)
        ceypH = cEypH / (1 - (-1))
        cP_ypH = ceypH * 100

        # Same crossed pump limits as in E. coli: acid scaled with FT2max,
        # alkali with FT1max.
        if cP_ypH > 0:
            yT1 = min(100.0, cP_ypH * p.KP_pH2a)
            v.FT1[i] = yT1 / 100 * p.FT2max
            v.FT2[i] = 0.0
        elif cP_ypH < 0:
            # min, not max: for a negative cP_ypH this keeps the product.
            yT2 = min(100.0, cP_ypH * p.KP_pH2b)
            v.FT1[i] = 0.0
            v.FT2[i] = yT2 / 100 * p.FT1max
        else:
            v.FT1[i] = 0.0
            v.FT2[i] = 0.0

    def _temperature_control(self, state: SimulationState, prev: int, i: int) -> float:
        p, v, a = state.p, state.v, state.a
        dt = state.dt
        PH = 0.0

        if p.Mode_temp == 0:
            a.mdotC = p.mdotCmax if p.f_cooling == 1 else 0.0
            PH = p.PHmax if p.f_heating == 1 else 0.0
            return PH

        if p.Mode_temp == 1:
            e = p.thetaLw - v.thetaL[prev]
            a.cE = pt1_filter(e, a.cE, dt)
            a.ce[i] = a.cE / (p.thetaLmaxgr - p.thetaLmingr)

            a.cP_Part = a.ce[i] * p.KP_temp1
            a.cI_Part[i] = a.cI_Part[prev] + (a.ce[i] + a.ce[prev]) / 2 * dt * p.KI_temp1

            wDJ = a.cP_Part + a.cI_Part[i] + p.thetaDJ_WP
            cDJ = wDJ - a.thetaDJ
            CDJ = cDJ / (100 - 0)
            yDJ = clamp(CDJ * 100, -100.0, 100.0)

            if yDJ > 0:
                yH = min(100.0, yDJ * p.KP_temp2h)
                a.mdotH = (yH / 100) * p.mdotHmax
                a.mdotC = 0.0
            else:
                # min, not max: E. coli clamps at -100 instead.
                yC = min(100.0, -yDJ * p.KP_temp2c)
                a.mdotH = 0.0
                a.mdotC = (yC / 100) * p.mdotCmax * 10
        return PH

    def _temperature_system(self, state: SimulationState, prev: int, PH: float):
        p, v, a = state.p, state.v, state.a
        tauHTh = a.mHmax * p.cH2O / (a.kHTh * p.AHTh)

        if p.Mode_temp == 0:
            a.thetaTh = v.thetaD[prev] + a.RT * PH if p.f_heating == 1 else v.thetaL[prev]
        else:
            DH = a.mdotH / a.mHmax
            phiHTh = DH * tauHTh
            phiHT = a.mdotH / p.mdotT
            a.thetaTh = (
                (1 + phiHTh) * a.CHmax * v.thetaD[prev] + phiHT * (a.CHmax * p.thetaHin + a.Qny)
            ) / (a.CHmax * (1 + phiHTh + phiHT))

        DC = a.mdotC / p.mC
        phiCTc = DC * a.tauCTc
        a.thetaTc = (phiCTc * p.thetaCin + (1 + phiCTc) * a.phiTcC * a.thetaTh) / (
            (1 + a.phiTcC) * (1 + phiCTc) - 1
        )
        a.thetaC = (phiCTc * p.thetaCin + a.thetaTc) / (1 + phiCTc)
        a.thetaDJ = a.thetaTc

        CL = p.rhoL * v.VL[prev] * p.cH2O + p.mWL * p.cW
        tauLD = CL / (a.kDL * p.ADL)
        tauLU = CL / (a.kLU * p.ALU)
        tauL = 1 / (1 / tauLD + 1 / tauLU)

        QdotM = p.KHM * v.VL[prev] * v.OUR[prev]
        QdotSt = p.KHSt * v.VL[prev] * v.NSt[prev] ** 3
        return a.thetaTc, tauL, tauLD, tauLU, QdotM, QdotSt, CL

    # ---------------------------------------------------------- volume --

    def _volume(self, state: SimulationState, prev: int, i: int):
        p, v = state.p, state.v
        dt = state.dt

        DR1 = DR2 = DT1 = DT2 = 0.0
        if v.VL[prev] > 0:
            if v.FR1[prev] > 0:
                DR1 = v.FR1[prev] / v.VL[prev]
            if v.FR2[prev] > 0:
                DR2 = v.FR2[prev] / v.VL[prev]
            DT1 = v.FT1[prev] / v.VL[prev]
            DT2 = v.FT2[prev] / v.VL[prev]

        dy = ode_volume(0.0, None, v.FR1[prev], v.FR2[prev], v.FH[prev], v.FT1[prev], v.FT2[prev])
        yV = solve_step_linear(
            dy, dt, [v.VL[prev], v.VR1[prev], v.VR2[prev], v.VT2[prev], v.VT1[prev]]
        )
        v.VL[i], v.VR1[i], v.VR2[i], v.VT2[i], v.VT1[i] = yV

        v.VR1in[i] = p.VR10 - v.VR1[prev]
        v.VR2in[i] = p.VR20 - v.VR2[prev]
        v.Vbase[i] = p.VT20 - v.VT2[prev]
        v.Vacid[i] = p.VT10 - v.VT1[prev]

        return DR1, DR2, DT1, DT2

    # ------------------------------------------------- respiration, pH --

    def _respiration_quotient(self, state: SimulationState, prev: int, i: int) -> None:
        v, a = state.v, state.a
        RQ_Z = v.xCO2[prev] / 100 * (1 - v.xOGin[prev]) - a.xCGin * (1 - v.xO2[prev] / 100)
        RQ_N = v.xOGin[prev] * (1 - v.xCO2[prev] / 100) - v.xO2[prev] / 100 * (1 - a.xCGin)
        v.RQ[i] = RQ_Z / RQ_N if RQ_N != 0 else 1.0
        if v.RQ[prev] <= 0:
            v.RQ[prev] = 0.0001

    def _ph_iteration(self, state: SimulationState, prev: int, i: int) -> float:
        """Identical to E. coli's iteration; kept here so the file stands alone."""
        p, v, a = state.p, state.v, state.a

        y1 = (v.CB1Ltot[prev] + 2 * v.CB2Ltot[prev]) / p.CH0
        y2 = (v.CB1Ltot[prev] + v.CB2Ltot[prev]) / p.CH0
        y3 = v.CCLtot[prev] / p.CH0
        y4 = v.cP1L[prev] / p.CH0
        y5 = v.CAlLtot[prev] / p.CH0
        y6 = v.CAcLtot[prev] / p.CH0

        xpH = 10 ** (7 - v.pH[prev])
        QuotpH = 0.9

        A, B, C = a.ApH, a.BpH, a.CpH
        D, E2 = a.DpH, a.EpH
        F, G = a.FpH, a.GpH
        H, I2 = a.HpH, a.IpH

        for _ in range(100):
            if not ((QuotpH <= 0.999 or QuotpH >= 1.001) and xpH >= 0):
                break
            xpHkm1 = xpH
            fpH = (
                xpH**2
                - 1
                + xpH * y1
                - (A * xpH**2 + 2 * B * xpH + 3 * C)
                * xpH
                / (xpH**3 + A * xpH**2 + B * xpH + C)
                * y2
                - (D + 2 * E2 / xpH) * y3
                - F * xpH / (F + xpH) * y4
                + G * xpH**2 / (1 + G * xpH) * y5
                - (H * xpH + 2 * I2) * xpH / (xpH**2 + H * xpH + I2) * y6
            )
            fstrpH = (
                2 * xpH
                + y1
                - (
                    (A**2 - 2 * B) * xpH**4
                    + (2 * A * B - 6 * C) * xpH**3
                    + 2 * B**2 * xpH**2
                    + 4 * B * C * xpH
                    + 3 * C**2
                )
                / ((xpH**3 + A * xpH**2 + B * xpH + C) ** 2)
                * y2
                + 2 * E2 / (xpH * xpH) * y3
                - F**2 / ((xpH + F) ** 2) * y4
                + G * xpH * (2 + G * xpH) / ((1 + G * xpH) ** 2) * y5
                - ((H**2 - 2 * I2) * xpH**2 + 2 * H * I2 * xpH + 2 * I2**2)
                / ((xpH**2 + H * xpH + I2) ** 2)
                * y6
            )
            xpH = xpH - fpH / fstrpH
            QuotpH = xpHkm1 / xpH

        if xpH < 0:
            xpH = -xpH
            a.pH_negative = True

        v.pHL[i] = 7 - np.log10(xpH)
        return xpH * p.CH0

    def _growth(self, state: SimulationState, prev: int, i: int, CHL: float):
        """Growth influences, oxygen and CO2 transfer, glycerol uptake."""
        p, v, a = state.p, state.v, state.a

        if p.pHLmingr <= v.pHL[prev] <= p.pHLmaxgr:
            fpH = (
                (v.pHL[prev] - p.pHLmingr)
                * (v.pHL[prev] - p.pHLmaxgr)
                / (
                    (v.pHL[prev] - p.pHLmingr) * (v.pHL[prev] - p.pHLmaxgr)
                    - (v.pHL[prev] - p.pHLoptgr) ** 2
                )
            )
        else:
            fpH = 0.0

        if p.thetaLmingr <= v.thetaL[prev] <= p.thetaLmaxgr:
            ftheta = ((v.thetaL[prev] - p.thetaLmaxgr) * (v.thetaL[prev] - p.thetaLmingr) ** 2) / (
                (p.thetaLoptgr - p.thetaLmingr)
                * (
                    (p.thetaLoptgr - p.thetaLmingr) * (v.thetaL[prev] - p.thetaLoptgr)
                    - (p.thetaLoptgr - p.thetaLmaxgr)
                    * (p.thetaLoptgr + p.thetaLmingr - 2 * v.thetaL[prev])
                )
            )
        else:
            ftheta = 0.0

        my1max = p.my1opt * fpH * ftheta  # glycerol
        a.qS1pXmax = (my1max + a.mySm) / p.yXpS1gr

        # Methanol goes through the Cornelissen kinetics rather than a Monod
        # term, and my2opt follows from it instead of being a parameter.
        cS2Lopt = np.sqrt(p.kS2 * p.kI22)
        a.qS2pXmax = p.qS2pXsup * (cS2Lopt / (p.kS2 + cS2Lopt)) * (p.kI22 / (p.kI22 + cS2Lopt))
        p.my2opt = p.yXpS2gr * a.qS2pXmax - a.mySm
        my2max = p.my2opt * fpH * ftheta

        a.qOpXmax = (my1max + a.mySm) / p.yXpOgr + p.qOpXm
        v.OURm[i] = p.qOpXm * v.cXL[prev]
        v.OURmax[i] = a.qOpXmax * v.cXL[prev]

        a.HO2 = henry_o2(p, v.thetaL[prev])
        a.cOL100 = p.pGcal * p.xOGcal / a.HO2
        a.cOLmax = v.pG[prev] / a.HO2

        v.QO2max[i] = v.FnG[prev] * 60 * p.MO2 / (p.VnM * v.VL[prev]) if v.VL[prev] > 0 else 0.0
        v.QCO2max[i] = v.QO2max[prev] * p.MCO2 / p.MO2

        eta = p.etaXL * (p.etaH2O / p.etaXL) ** (v.cXL[prev] / p.cXLeta)
        VLwert = (v.VL[prev] / p.VLmin) ** p.alpha
        NStwert = (v.NSt[prev] / p.NStmax) ** (3 * p.alpha)
        FGwert = (v.FnG[prev] / p.FnGmax) ** p.beta
        etawert = (eta / p.etaH2O) ** p.gamma
        v.kLa[i] = p.kLamin + p.kLamax * FGwert * NStwert / VLwert * etawert * (1 - v.AAF[prev])

        v.OTRmax[i] = v.kLa[prev] * a.cOLmax
        StO = v.OTRmax[prev] / v.QO2max[prev] if v.QO2max[prev] > 0 else 1e20
        v.xOL[i] = v.cOL[prev] / a.cOLmax

        denom_OTR = 1 + StO - (1 - v.RQ[prev]) * StO * v.xOL[prev]
        v.OTR[i] = (
            v.OTRmax[prev]
            * (v.xOGin[prev] - v.xOL[prev])
            * 2
            / (
                denom_OTR
                + np.sqrt(denom_OTR**2 - 4 * (1 - v.RQ[prev]) * StO * (v.xOGin[prev] - v.xOL[prev]))
            )
        )
        if v.OTR[prev] < 0:
            v.OTR[prev] = 0.0

        if v.OTR[prev] != 0:
            v.xOG[i] = (v.QO2max[prev] * v.xOGin[prev] - v.OTR[prev]) / (
                v.QO2max[prev] - (1 - v.RQ[prev]) * v.OTR[prev]
            )
        else:
            v.xOG[i] = v.xOGin[prev]

        a.HCO2 = henry_co2(p, v.thetaL[prev])
        a.cCLmax = v.pG[prev] / a.HCO2
        a.cCL = (CHL**2 * p.MCO2 * v.CCLtot[prev]) / (CHL**2 + p.KC1 * CHL + p.KC1 * p.KC2)
        a.xCL = a.cCL / a.cCLmax
        a.CTRmax = p.deltaCpO * v.kLa[prev] * a.cCLmax
        a.StC = a.CTRmax / v.QCO2max[prev] if v.QCO2max[prev] > 0 else 1e20

        denom_CTR = 1 + a.StC - (1 - 1 / v.RQ[prev]) * a.StC * a.xCL
        v.CTR[i] = (
            a.CTRmax
            * (a.xCGin - a.xCL)
            * 2
            / (
                denom_CTR
                + np.sqrt(denom_CTR**2 - 4 * (1 - 1 / v.RQ[prev]) * a.StC * (a.xCGin - a.xCL))
            )
        )
        v.xCG[i] = (v.QCO2max[prev] * a.xCGin - v.CTR[prev]) / (
            v.QCO2max[prev] - (1 - 1 / v.RQ[prev]) * v.CTR[prev]
        )

        qS1pXopt = 0.0 if v.cS1L[prev] <= 0 else a.qS1pXmax * v.cS1L[prev] / (v.cS1L[prev] + p.kS1)
        qS2pXopt = (
            0.0
            if v.cS2L[prev] <= 0
            else a.qS2pXmax
            * (v.cS2L[prev] / (v.cS2L[prev] + p.kS2))
            * (p.kI22 / (p.kI22 + v.cS2L[prev]))
            * (p.kI21 / (p.kI21 + v.cS1L[prev]))
        )

        qXpXSgr = p.yXpS1gr * qS1pXopt + p.yXpS2gr * qS2pXopt
        qXpXOgr = (
            0.0
            if v.cOL[prev] <= 0
            else p.yXpOgr * (a.qOpXmax - p.qOpXm) * v.cOL[prev] / (p.kO + v.cOL[prev])
        )
        qXpXgr = min(qXpXSgr, qXpXOgr)
        a.limitation = "substrate" if qXpXSgr < qXpXOgr else "oxygen"

        # Methanol toxicity — no counterpart in E. coli.
        VS2tox = (v.cS2L[prev] / p.kS2tox) ** p.kappatox / (
            1 + (v.cS2L[prev] / p.kS2tox) ** p.kappatox
        )
        v.qXpX[i] = qXpXgr - a.mySm - VS2tox * p.qXpXtox if p.f_Inoc == 1 else 0.0

        return qXpXgr, my2max, qS1pXopt

    # ---------------------------------------- AOX induction, expression --

    def _induction(self, state: SimulationState, prev: int, i: int, my2max: float) -> float:
        """AOX induction after Cornelissen; returns the methanol uptake rate."""
        p, v = state.p, state.v

        bS2script = p.aS2script + my2max
        bS2trans = p.aS2trans + my2max
        bS2act = p.aS2act + my2max

        VS2ind, VS1rep = self._switch_functions(state, prev)
        v.qS2pXind[i] = VS1rep * VS2ind * p.qS2pXsup

        y = solve_step(
            ode_induction,
            state.dt,
            [v.qS2pXscript[prev], v.qS2pXtrans[prev], v.qS2pXact[prev]],
            args=(
                v.qXpX[prev],
                v.qS2pXind[prev],
                p.aS2script,
                p.aS2trans,
                p.aS2act,
                bS2script,
                bS2trans,
                bS2act,
            ),
        )
        v.qS2pXscript[i], v.qS2pXtrans[i], v.qS2pXact[i] = y

        v.qS2pX[i] = (
            v.qS2pXact[prev]
            * (v.cS2L[prev] / (p.kS2 + v.cS2L[prev]))
            * (p.kI22 / (p.kI22 + v.cS2L[prev]))
            * (p.kI21 / (p.kI21 + v.cS1L[prev]))
        )
        return v.qS2pX[i]

    def _expression(self, state: SimulationState, prev: int, i: int, my2max: float) -> None:
        """Target protein expression with a PI loop on the transcription rate."""
        p, v = state.p, state.v

        bP1script = p.aP1script + my2max
        bP1trans = p.aP1trans + my2max
        bP1act = p.kP1alpha + my2max

        VS2ind, VS1rep = self._switch_functions(state, prev)
        v.qP1pXind[i] = VS1rep * VS2ind * p.qP1pXsup
        v.qP1pXscriptw[i] = VS1rep * VS2ind * p.qP1pXmax

        delta = v.qP1pXscriptw[prev] - v.qP1pXscript[prev]
        if prev > 0:
            # The integral part is a trapezoidal sum over the whole history,
            # recomputed every step. Faithful, and O(n) per step — see the
            # performance note in docs.
            tHist = v.t[: prev + 1]
            deltaHist = v.qP1pXscriptw[: prev + 1] - v.qP1pXscript[: prev + 1]
            intVal = float(np.trapezoid(deltaHist, tHist))
            v.qP1pXback[i] = p.KCP1script * (delta + intVal / p.TIP1script)
        else:
            v.qP1pXback[i] = 0.0

        y = solve_step(
            ode_expression,
            state.dt,
            [v.qP1pXscript[prev], v.qP1pXtrans[prev], v.qP1pXact[prev]],
            args=(
                v.qXpX[prev],
                v.qP1pXind[prev],
                v.qP1pXback[prev],
                p.aP1script,
                p.aP1trans,
                p.kP1alpha,
                bP1script,
                bP1trans,
                bP1act,
            ),
        )
        v.qP1pXscript[i], v.qP1pXtrans[i], v.qP1pXact[i] = y
        v.qP1pX[i] = v.qP1pXact[prev]

    def _switch_functions(self, state: SimulationState, prev: int):
        """Methanol switch-on and glycerol repression [-]."""
        p, v = state.p, state.v
        VS2ind = (v.cS2L[prev] / p.kS2ind) ** p.kappaind / (
            1 + (v.cS2L[prev] / p.kS2ind) ** p.kappaind
        )
        VS1rep = 1 / (1 + (v.cS1L[prev] / p.kS1rep) ** p.kapparep)
        return VS2ind, VS1rep
