"""Escherichia coli — one reservoir, 18 ODE states (plan section 2.4).

Line-by-line translation of Escherichia_coli.m. The section order and the
order of statements inside each section follow the MATLAB source so the two
can be read side by side.

Several places in the original compute a value at idx and then use the value
at idx - 1 of the same variable in the very next formula. That is almost
certainly unintended, but it defines the numbers the reference run contains,
so it is reproduced exactly and marked with "MATLAB lag" where it happens.
Fixing any of it before the reference run is available would make a deviation
impossible to attribute.
"""

import numpy as np

from ...core.integrate import solve_step, solve_step_linear
from ...core.state import SimulationState
from ..base import OrganismMetadata, OrganismModel
from ..registry import register
from ..shared import (
    CONTROL_LOOPS,
    anti_windup,
    clamp,
    henry_co2,
    henry_o2,
    init_common_kinetics,
    init_common_variables,
    init_controller_states,
    init_physical_constants,
    integrate,
    meas_transfer_function,
    pt1_filter,
)
from .ode import LuttmannTerms, ode_luttmann, ode_volume


@register
class EscherichiaColi(OrganismModel):
    metadata = OrganismMetadata(
        name="escherichia_coli",
        display_name="Escherichia coli",
        n_reservoirs=1,
        description="Glucose, glycerol and acetate on one reservoir; 18 ODE states.",
        version="2.2",
    )

    #: Both models tap the same controller signals; see shared.py.
    control_loops = CONTROL_LOOPS

    # ------------------------------------------------------------ setup --

    def init_controller_states(self, state: SimulationState) -> None:
        init_controller_states(state)

    def init_physical_constants(self, state: SimulationState) -> None:
        init_physical_constants(state)
        state.a.numReservoir = self.metadata.n_reservoirs

    def init_kinetics(self, state: SimulationState) -> None:
        init_common_kinetics(state)
        p, a = state.p, state.a
        # Acetate is the third substrate and only E. coli has it.
        a.qS3pXmax = (p.my3opt + a.mySm) / p.yXpS3gr

        # Start time and start rate of an exponential feed phase. They exist
        # in parameterTab but belong to no project until the phase automaton
        # of phase 3 writes them.
        for name in ("t1j", "FR1j"):
            p.setdefault(name, 0.0)

    def init_variables(self, state: SimulationState) -> None:
        init_common_variables(state)
        p, v = state.p, state.v

        state.series("cS3L", p.cS3L0)
        state.series("cS3Lm", p.cS3L0)

        # One reservoir
        state.series("VR1", p.VR10)
        state.series("VR1in", 0.0)
        state.series("FR1", 0.0)
        state.series("QS1in", (v.FR1[0] * p.cS1R1) / v.VL[0])

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

        # Mole fraction at the reactor inlet [-]. The CO2 term is dropped in
        # the original: this simulation never aerates with CO2.
        #
        # Corrected, not reproduced: the original guards on FnG(previdx) and
        # then divides by FnG(idx), so a step that stops the gas divides by
        # zero — 0/0, whose NaN carry_forward then replaces with the previous
        # mixture, leaving the step to transfer oxygen out of a gas stream
        # that is not flowing. Pichia's copy of this line already tests the
        # index it divides by; this now matches it.
        if v.FnG[i] > 0:
            v.xOGin[i] = (p.xOAIR * v.FnAIR[i] + v.FnO2[i]) / v.FnG[i]
        else:
            v.xOGin[i] = 0.0

        AAFin = self._antifoam(state, prev)
        self._ph_control(state, prev, i)
        PH = self._temperature_control(state, prev)

        # Eigenvalues of the foam and anti-foam equations [1/h]
        lamdaF = -v.AAF[prev] / p.tauF0 / (1 + p.KFpX * v.cXL[prev])
        lamdaAF = -v.cXL[prev] / p.KAF

        DR1, DT1, DT2 = self._volume(state, prev, i)
        Din = DR1 + DT1 + DT2

        TL = v.thetaL[prev] + p.TnG  # liquid temperature [K]

        # Pressure in the gas phase [N/m^2]
        if v.thetaL[prev] < 100:
            v.pG[i] = a.pGw
        else:
            ExppDL = 10.9 - 2461 / TL - 2.065 * np.log10(v.thetaL[prev] / p.TnG)
            v.pG[i] = 9.8067 * 10**ExppDL

        a.deltapG = (v.pG[prev] - p.pnG) / 1e5  # over pressure [bar]

        self._respiration_quotient(state, prev, i)
        CHL = self._ph_iteration(state, prev, i)
        _qXpXgr, rates = self._growth(state, prev, i, CHL)
        CER = p.yCpO * v.OUR[prev]
        AlTR = -p.KAlvol * v.FnG[prev] * v.CAlLtot[prev] * p.MAl / v.VL[prev]

        thetaTc, tauL, tauLD, tauLU, QdotM, QdotSt, CL = self._temperature_system(state, prev, PH)

        terms = LuttmannTerms(
            qXpX=v.qXpX[prev],
            Din=Din,
            cS1R1=p.cS1R1,
            qS1pX=rates["qS1pX"],
            cS2R1=p.cS2R1,
            qS2pX=rates["qS2pX"],
            cP1R1=p.cP1R1,
            qP1pX=rates["qP1pX"],
            MP1=p.MP1,
            cOT1=p.cOT1,
            cOT2=p.cOT2,
            cOR1=p.cOR1,
            OTR=v.OTR[prev],
            OUR=v.OUR[prev],
            cOL100=a.cOL100,
            TMpO2=p.TMpO2,
            DT1=DT1,
            CAcT1tot=p.CAcT1tot,
            qAcpX=rates["qAcpX"],
            MAc=p.MAc,
            DT2=DT2,
            CAlT2tot=p.CAlT2tot,
            qAlpX=rates["qAlpX"],
            AlTR=AlTR,
            MAl=p.MAl,
            DR1=DR1,
            CCR1tot=p.CCR1tot,
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
        y = np.where(y < 0, 0.0, y)  # no state may go negative

        # Inoculation replaces the integrated cell concentration once.
        if p.f_Inoc == 1 and a.inoc_occ == 0:
            v.cXL[i] = p.cXL0
            a.ToI = v.t[prev]
            a.inoc_occ = 1
        else:
            v.cXL[i] = y[0]

        v.cS1L[i] = y[1]
        v.cS2L[i] = y[2]
        v.cP1L[i] = y[3]
        v.cOL[i] = y[4]
        v.pO2[i] = y[5]
        v.CB1Ltot[i] = y[6]
        v.CB2Ltot[i] = y[7]
        v.CAcLtot[i] = y[8]
        v.CAlLtot[i] = y[9]
        v.CCLtot[i] = y[10]
        v.pH[i] = y[11]
        v.xO2[i] = y[12]
        v.xCO2[i] = y[13]
        v.hF[i] = y[14]
        v.AAF[i] = y[15]
        v.thetaD[i] = y[16]
        v.thetaL[i] = y[17]

        # MATLAB clamps the previous slot, not the one just written.
        if v.thetaL[prev] > 100.0:
            v.thetaL[prev] = 100.0
            a.temperature_exceeded = True

        v.QS1in[i] = (v.FR1[prev] * p.cS1R1) / v.VL[i]

        # Measured values, each behind its own first-order lag
        v.pHLm[i] = meas_transfer_function(v.pHL[prev], v.pHLm[prev], p.taupHL, dt)
        v.pO2m[i] = meas_transfer_function(v.pO2[prev], v.pO2m[prev], p.taupO2, dt)
        v.thetaLm[i] = meas_transfer_function(v.thetaL[prev], v.thetaLm[prev], p.tauthetaL, dt)
        v.cS1Lm[i] = meas_transfer_function(v.cS1L[prev], v.cS1Lm[prev], p.taucS1L, dt)

        v.t[i] = v.t[prev] + dt

        if v.VL[prev] >= p.VLmax:
            a.VolumeFlag = 1

        # Variables this model never recomputes keep their previous value
        # instead of turning into a gap. See SimulationState.carry_forward.
        a.carried_forward = state.carry_forward(i)

        state.idx = i

    # --------------------------------------------------------- feeding --

    def _feeding(self, state: SimulationState, prev: int, i: int) -> None:
        """Feed rate. The order of the branches is the priority, one wins."""
        p, v, a = state.p, state.v, state.a
        dt = state.dt

        v.FR1[i] = 0.0

        if a.get("switch_exp", False):
            # Exponential feed. MATLAB hardcodes reservoir 1 for the growth
            # rate setpoint and the pump limit even inside the reservoir loop.
            for reservoir in range(1, int(a.numReservoir) + 1):
                FRwj = p[f"FR{reservoir}j"]
                qxpxwj = p.qXpX1w
                tj = p.t1j
                FR = FRwj * np.exp(qxpxwj * (v.t[prev] - tj))
                if FR < p.FR1max:  # noqa: SIM300
                    v.FR1[i] = FR
                else:
                    a.switch_exp = False
                    a.feed_limit_hit = reservoir
            return

        if a.get("switch_pulse", False):
            v.FR1[i] = p.FR1max * p.kR1
            return

        if p.Mode_pO2 == 4:
            # pO2 controlled feed. Cannot run next to exponential or pulse
            # feed, which is why it lives in this branch chain.
            cEfeedpO2 = p.pO2w - v.pO2[prev]
            a.cE_feedpO2 = pt1_filter(cEfeedpO2, a.cE_feedpO2, dt)
            a.ce_feedpO2[i] = a.cE_feedpO2 / (100 - 0)

            a.cP_feedpO2 = a.ce_feedpO2[i] * p.KP_feedpO2
            increment = (a.ce_feedpO2[i] + a.ce_feedpO2[prev]) / 2 * dt * p.KI_feedpO2
            a.cD_feedpO2 = (a.ce_feedpO2[i] - a.ce_feedpO2[prev]) / dt * p.KD_feedpO2

            raw = ((a.cP_feedpO2 + a.cI_feedpO2 + increment + a.cD_feedpO2) * 100 + a.yfeedpO2) / 2
            a.cI_feedpO2 = integrate(
                a.cI_feedpO2, increment, raw, 0.0, 100.0, active=anti_windup(p, a, "f_awpO2")
            )
            a.yfeedpO2 = ((a.cP_feedpO2 + a.cI_feedpO2 + a.cD_feedpO2) * 100 + a.yfeedpO2) / 2
            a.yfeedpO2 = clamp(a.yfeedpO2, 0.0, 100.0)

            v.FR1[i] = a.yfeedpO2 / 100 * p.FR1max
            return

        if p.f_feed == 1:
            n = int(p.R_feed)
            if p.Mode_feed == 0:
                v[f"FR{n}"][i] = p[f"FR{n}w"]
            elif p.Mode_feed == 1:
                cSLw = p[f"cS{n}Lw"]
                cSL = v[f"cS{n}L"][prev]
                cSLwmax = p[f"cS{n}R{n}"] * 0.2
                cSLwmin = 0.01

                cEfeedR = cSLw - cSL
                a[f"cE_feedR{n}"] = pt1_filter(cEfeedR, a[f"cE_feedR{n}"], dt)
                a[f"ce_feedR{n}"][i] = a[f"cE_feedR{n}"] / (cSLwmax - cSLwmin)

                # MATLAB lag: the P part reads idx - 1 while I and D read idx.
                a[f"cP_feedR{n}"] = a[f"ce_feedR{n}"][prev] * p[f"KP_feedR{n}"]
                increment = (
                    (a[f"ce_feedR{n}"][i] + a[f"ce_feedR{n}"][prev]) / 2 * dt * p[f"KI_feedR{n}"]
                )
                a[f"cD_feedR{n}"] = (
                    (a[f"ce_feedR{n}"][i] - a[f"ce_feedR{n}"][prev]) / dt * p[f"KD_feedR{n}"]
                )

                yFR = a[f"cP_feedR{n}"] + a[f"cI_feedR{n}"] + increment + a[f"cD_feedR{n}"]
                a[f"cI_feedR{n}"] = integrate(
                    a[f"cI_feedR{n}"],
                    increment,
                    yFR,
                    0.0,
                    1.0,
                    active=anti_windup(p, a, "f_awfeed"),
                )
                yFR = clamp(
                    a[f"cP_feedR{n}"] + a[f"cI_feedR{n}"] + a[f"cD_feedR{n}"], 0.0, 1.0
                )
                v[f"FR{n}"][i] = p[f"FR{n}max"] * yFR

    # ----------------------------------------------------- pO2 control --

    def _po2_control(self, state: SimulationState, prev: int, i: int) -> None:
        p, v, a = state.p, state.v, state.a
        dt = state.dt

        if p.f_aeration == 1:
            v.FnN2[i] = p.FnN2w if p.f_N2 == 1 else 0.0
            v.FnCO2[i] = p.FnCO2w if p.f_CO2 == 1 else 0.0

        if p.Mode_pO2 == 1:  # agitation
            cEagi = p.pO2w - v.pO2[prev]
            a.cE_agi = pt1_filter(cEagi, a.cE_agi, dt)
            a.ce_agi[i] = a.cE_agi / (100 - 1)

            a.cP_agi = a.ce_agi[i] * p.KP_agi
            increment = (a.ce_agi[i] + a.ce_agi[prev]) / 2 * dt * p.KI_agi
            a.cD_agi = (a.ce_agi[i] - a.ce_agi[prev]) / dt * p.KD_agi

            a.cI_agi = integrate(
                a.cI_agi,
                increment,
                a.cP_agi + a.cI_agi + increment + a.cD_agi,
                0.3,
                1.0,
                active=anti_windup(p, a, "f_awpO2"),
            )
            yNSt = clamp(a.cP_agi + a.cI_agi + a.cD_agi, 0.3, 1.0)
            v.NSt[i] = yNSt * p.NStmax

        elif p.Mode_pO2 == 2:  # aeration
            cEaeration = p.pO2w - v.pO2[prev]
            a.cE_aeration = pt1_filter(cEaeration, a.cE_aeration, dt)
            a.ce_aeration[i] = a.cE_aeration / (100 - 1)

            a.cP_aeration = a.ce_aeration[i] * p.KP_aeration
            increment = (a.ce_aeration[i] + a.ce_aeration[prev]) / 2 * dt * p.KI_aeration
            a.cD_aeration = (a.ce_aeration[i] - a.ce_aeration[prev]) / dt * p.KD_aeration

            # The limits are the 30 and 100 the branch below applies; they are
            # named here because the integrator has to know them a line early.
            a.cI_aeration = integrate(
                a.cI_aeration,
                increment,
                (a.cP_aeration + a.cI_aeration + increment + a.cD_aeration) * 100,
                30.0,
                100.0,
                active=anti_windup(p, a, "f_awpO2"),
            )
            yaeration = (a.cP_aeration + a.cI_aeration + a.cD_aeration) * 100
            diff = 0.0
            if yaeration < 30:
                yaeration = 30.0
            elif yaeration > 100:
                diff = min(yaeration - 100, 100.0)
                yaeration = 100.0

            v.FnAIR[i] = yaeration / 100 * p.FnAIRmax
            v.FnO2[i] = diff / 100 * p.FnO2max
            v.FnG[i] = v.FnAIR[i] + v.FnO2[i] + v.FnN2[i] + v.FnCO2[i]

        elif p.Mode_pO2 == 3:  # gas mixing
            cEgasmix = p.pO2w - v.pO2[prev]
            a.cE_gasmix = pt1_filter(cEgasmix, a.cE_gasmix, dt)
            a.ce_gasmix[i] = a.cE_gasmix / (1 - p.xOAIR)

            a.cP_gasmix = a.ce_gasmix[i] * p.KP_gasmix
            increment = (a.ce_gasmix[i] + a.ce_gasmix[prev]) / 2 * dt * p.KI_gasmix
            a.cD_gasmix = (a.ce_gasmix[i] - a.ce_gasmix[prev]) / dt * p.KD_gasmix
            a.cI_gasmix[i] = integrate(
                a.cI_gasmix[prev],
                increment,
                (a.cP_gasmix + a.cI_gasmix[prev] + increment + a.cD_gasmix) * 100,
                p.xOAIR * 100,
                100.0,
                active=anti_windup(p, a, "f_awpO2"),
            )

            # MATLAB writes cD_gasmix as a scalar and then indexes it with
            # (idx), which raises once idx passes 1. Taken as the scalar here,
            # which is plainly what was meant.
            ygasmix = (a.cP_gasmix + a.cI_gasmix[i] + a.cD_gasmix) * 100
            ygasmix = clamp(ygasmix, p.xOAIR * 100, 100.0)

            xOGinw = ygasmix / 100 * 1
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
            v.FnG[i] = v.FnAIR[i] + v.FnO2[i] + v.FnN2[i] + v.FnCO2[i]

        # Stirrer speed unless pO2 controls it [1/min]
        if p.Mode_pO2 != 1:
            v.NSt[i] = p.NStw if p.f_motor == 1 else 0.0

    def _aeration(self, state: SimulationState, prev: int, i: int) -> None:
        """Aeration rate when pO2 control does not already set it [l/min]."""
        p, v = state.p, state.v
        if p.Mode_pO2 in (2, 3):
            return
        if p.f_aeration == 1:
            v.FnAIR[i] = p.FnAIRw if p.f_air == 1 else 0.0
            # Corrected, not reproduced. The source has two blocks of the same
            # shape here, and the second carries the variable of the first:
            #
            #     if app.p.f_O2 == 1
            #         app.v.FnO2(idx) = app.p.FnO2w;
            #     else
            #         app.v.FnAIR(idx) = 0;      % should be FnO2
            #     end
            #
            # Switching pure oxygen off therefore switched the *air* off, and
            # left FnO2 unwritten — a preallocation NaN, which poisons the sum
            # below, so carry_forward hands both FnO2 and the total the values
            # of the step before. The total then freezes at whatever it was:
            # measured, FnAIR = 0 and FnO2 = 0 next to FnG = 7.5 l/min, a gas
            # stream no component feeds, and pO2 falls to zero while the
            # window reports the reactor as aerated.
            #
            # The Pichia source has this line right. f_O2 is a cyclic flag and
            # can be switched during a run, but the reference run never leaves
            # it — project 716 has f_O2 = 1 — so the verified window is
            # untouched. See CLAUDE.md.
            v.FnO2[i] = p.FnO2w if p.f_O2 == 1 else 0.0
            v.FnG[i] = v.FnAIR[i] + v.FnO2[i] + v.FnN2[i] + v.FnCO2[i]
        else:
            v.FnG[i] = 0.0

    # ------------------------------------------------ liquid weight --

    def _liquid_weight(self, state: SimulationState, prev: int, i: int) -> None:
        p, v, a = state.p, state.v, state.a
        dt = state.dt

        if p.Mode_harvest == 1:
            cELW = v.VL[prev] * p.rhoL - p.LWw
            a.cE_LW = pt1_filter(cELW, a.cE_LW, dt)
            a.ce_LW[i] = a.cE_LW / (p.VLmax * p.rhoL - p.VLmin * p.rhoL)

            cP_LW = a.ce_LW[i] * p.KP_LW
            a.cP_LW = cP_LW
            increment = (a.ce_LW[i] + a.ce_LW[prev]) / 2 * dt * p.KI_LW
            cD_LW = (a.ce_LW[i] - a.ce_LW[prev]) / dt * p.KD_LW
            a.cD_LW = cD_LW
            a.cI_LW[i] = integrate(
                a.cI_LW[prev],
                increment,
                (cP_LW + a.cI_LW[prev] + increment + cD_LW) * 100,
                0.0,
                100.0,
                active=anti_windup(p, a, "f_awLW"),
            )

            yLW = clamp((cP_LW + a.cI_LW[i] + cD_LW) * 100, 0.0, 100.0)
            v.FH[i] = yLW / 100 * p.FHmax
        else:
            v.FH[i] = p.FHrelw / 100 * p.FHmax if p.f_harvest == 1 else 0.0

    def _antifoam(self, state: SimulationState, prev: int) -> float:
        """Anti-foam dosing activity [1/h]."""
        p, v, a = state.p, state.v, state.a
        if p.f_antifoam == 1 and a.ToI != 0:
            TON = v.t[prev] - a.ToI
            return p.AAFtast * p.VAF ** (TON / p.Ttast)
        return 0.0

    # ------------------------------------------------------ pH control --

    def _ph_control(self, state: SimulationState, prev: int, i: int) -> None:
        p, v, a = state.p, state.v, state.a
        dt = state.dt

        if p.Mode_pH == 0:  # manual
            v.FT2[i] = p.FT2max if p.f_alkali == 1 else 0.0
            v.FT1[i] = p.FT1max if p.f_acid == 1 else 0.0
            return

        if p.Mode_pH != 1:  # auto
            return

        if abs(p.pHw - v.pHL[prev]) < 0.1:
            # Inside the dead band the controller does nothing, and the
            # Controllers tab has to be able to say so rather than show the
            # last values from before it.
            a.ce_pH = 0.0
            a.cP_pH = 0.0
            v.FT1[i] = 0.0
            v.FT2[i] = 0.0
            return

        epH = p.pHw - v.pHL[prev]
        a.cEpH = pt1_filter(epH, a.cEpH, dt)
        cepH = a.cEpH / (p.pHLmaxgr - p.pHLmingr)

        # Kept for the Controllers tab; nothing in the model reads them.
        a.ce_pH = cepH
        a.cP_pH = cepH * p.KP_pH * 100

        ypH = clamp(cepH * p.KP_pH * 100, -100.0, 100.0)

        cEypH = p.ypH_SET - (ypH / 100)
        ceypH = cEypH / (1 - (-1))
        cP_ypH = ceypH * 100

        # MATLAB crosses the pump limits here: the acid rate is scaled with
        # FT2max and the alkali rate with FT1max. Reproduced.
        if cP_ypH > 0:
            yT1 = min(cP_ypH * p.KP_pH2a, 100.0)
            v.FT1[i] = yT1 / 100 * p.FT2max
            v.FT2[i] = 0.0
        elif cP_ypH < 0:
            yT2 = cP_ypH * p.KP_pH2b
            if yT2 > 100:
                yT2 = 100.0
            v.FT1[i] = 0.0
            v.FT2[i] = yT2 / 100 * p.FT1max
        else:
            v.FT1[i] = 0.0
            v.FT2[i] = 0.0

    # --------------------------------------------- temperature control --

    def _temperature_control(self, state: SimulationState, prev: int) -> float:
        """Sets a.mdotC and a.mdotH, returns the electrical heating power."""
        p, v, a = state.p, state.v, state.a
        dt = state.dt
        PH = 0.0

        if p.Mode_temp == 0:  # manual
            a.mdotC = p.mdotCmax if p.f_cooling == 1 else 0.0
            PH = p.PHmax if p.f_heating == 1 else 0.0
            return PH

        if p.Mode_temp == 1:  # split range, cascade
            e = p.thetaLw - v.thetaL[prev]
            a.cE = pt1_filter(e, a.cE, dt)
            i = state.idx + 1
            a.ce[i] = a.cE / (p.thetaLmaxgr - p.thetaLmingr)

            a.cP_Part = a.ce[i] * p.KP_temp1
            a.cI_Part[i] = a.cI_Part[prev] + (a.ce[i] + a.ce[prev]) / 2 * dt * p.KI_temp1

            wDJ = a.cP_Part + a.cI_Part[i] + p.thetaDJ_WP
            cDJ = wDJ - a.thetaDJ
            CDJ = cDJ / (100 - 0)
            yDJ = clamp(CDJ * 100, -100.0, 100.0)

            if yDJ > 0:
                yH = min(yDJ * p.KP_temp2h, 100.0)
                a.mdotH = (yH / 100) * p.mdotHmax
                a.mdotC = 0.0
            else:
                yC = -yDJ * p.KP_temp2c
                if yC < -100:
                    yC = -100.0
                a.mdotH = 0.0
                # The factor 10 is in the original.
                a.mdotC = (yC / 100) * p.mdotCmax * 10
        return PH

    def _temperature_system(self, state: SimulationState, prev: int, PH: float):
        """Heat exchanger, cooling and the time constants of the liquid."""
        p, v, a = state.p, state.v, state.a

        tauHTh = a.mHmax * p.cH2O / (a.kHTh * p.AHTh)

        if p.Mode_temp == 0:
            if p.f_heating == 1:
                a.thetaTh = v.thetaD[prev] + a.RT * PH
            else:
                a.thetaTh = v.thetaL[prev]
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
        a.thetaDJ = a.thetaTc  # cascade control quantity

        CL = p.rhoL * v.VL[prev] * p.cH2O + p.mWL * p.cW
        tauLD = CL / (a.kDL * p.ADL)
        tauLU = CL / (a.kLU * p.ALU)
        tauL = 1 / (1 / tauLD + 1 / tauLU)

        QdotM = p.KHM * v.VL[prev] * v.OUR[prev]  # microbial heat [W]
        QdotSt = p.KHSt * v.VL[prev] * v.NSt[prev] ** 3  # stirrer heat [W]

        return a.thetaTc, tauL, tauLD, tauLU, QdotM, QdotSt, CL

    # ---------------------------------------------------------- volume --

    def _volume(self, state: SimulationState, prev: int, i: int):
        p, v = state.p, state.v
        dt = state.dt

        DR1 = DT1 = DT2 = 0.0
        if v.VL[prev] > 0:
            if v.FR1[prev] > 0:
                DR1 = v.FR1[prev] / v.VL[prev]
            DT1 = v.FT1[prev] / v.VL[prev]
            DT2 = v.FT2[prev] / v.VL[prev]

        dy = ode_volume(0.0, None, v.FR1[prev], v.FH[prev], v.FT1[prev], v.FT2[prev])
        yV = solve_step_linear(dy, dt, [v.VL[prev], v.VR1[prev], v.VT2[prev], v.VT1[prev]])
        v.VL[i], v.VR1[i], v.VT2[i], v.VT1[i] = yV

        v.VR1in[i] = p.VR10 - v.VR1[prev]
        v.Vbase[i] = p.VT20 - v.VT2[prev]
        v.Vacid[i] = p.VT10 - v.VT1[prev]

        return DR1, DT1, DT2

    # ------------------------------------------------- respiration, pH --

    def _respiration_quotient(self, state: SimulationState, prev: int, i: int) -> None:
        v, a = state.v, state.a
        RQ_Z = v.xCO2[prev] / 100 * (1 - v.xOGin[prev]) - a.xCGin * (1 - v.xO2[prev] / 100)
        RQ_N = v.xOGin[prev] * (1 - v.xCO2[prev] / 100) - v.xO2[prev] / 100 * (1 - a.xCGin)
        v.RQ[i] = RQ_Z / RQ_N if RQ_N != 0 else 1.0
        if v.RQ[prev] <= 0:
            # The carbon balance divides by RQ; MATLAB patches the previous
            # slot rather than the current one.
            v.RQ[prev] = 0.0001

    def _ph_iteration(self, state: SimulationState, prev: int, i: int) -> float:
        """Newton iteration for the pH of the liquid phase.

        Returns the molar H+ concentration. Translated one to one, including
        the convergence window and the 100 iteration cap.
        """
        p, v, a = state.p, state.v, state.a

        y1 = (v.CB1Ltot[prev] + 2 * v.CB2Ltot[prev]) / p.CH0  # buffer cations
        y2 = (v.CB1Ltot[prev] + v.CB2Ltot[prev]) / p.CH0  # buffer anions
        y3 = v.CCLtot[prev] / p.CH0  # dissolved CO2
        y4 = v.cP1L[prev] / p.CH0  # acetate
        y5 = v.CAlLtot[prev] / p.CH0  # titrated base
        y6 = v.CAcLtot[prev] / p.CH0  # titrated acid

        xpH = 10 ** (7 - v.pH[prev])
        QuotpH = 0.9

        # Short names for the dimensionless dissociation constants; the
        # formulas below are unreadable with the a.XpH prefix on every term.
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
        """Growth influences, oxygen and CO2 transfer, uptake rates."""
        p, v, a = state.p, state.v, state.a

        # Influence of pH and temperature on growth
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

        my1max = p.my1opt * fpH * ftheta
        my2max = p.my2opt * fpH * ftheta
        my3max = p.my3opt * fpH * ftheta

        a.qS1pXmax = (my1max + a.mySm) / p.yXpS1gr
        a.qS2pXmax = (my2max + a.mySm) / p.yXpS2gr
        a.qS3pXmax = (my3max + a.mySm) / p.yXpS3gr
        a.qOpXmax = (my1max + a.mySm) / p.yXpOgr + p.qOpXm

        v.OURm[i] = p.qOpXm * v.cXL[prev]
        v.OURmax[i] = a.qOpXmax * v.cXL[prev]

        a.HO2 = henry_o2(p, v.thetaL[prev])
        a.cOL100 = p.pGcal * p.xOGcal / a.HO2
        a.cOLmax = v.pG[prev] / a.HO2

        if v.VL[prev] > 0:
            v.QO2max[i] = v.FnG[prev] * 60 * p.MO2 / (p.VnM * v.VL[prev])
        else:
            v.QO2max[i] = 0.0
        v.QCO2max[i] = v.QO2max[prev] * p.MCO2 / p.MO2  # MATLAB lag

        eta = p.etaXL * (p.etaH2O / p.etaXL) ** (v.cXL[prev] / p.cXLeta)

        VLwert = (v.VL[prev] / p.VLmin) ** p.alpha
        NStwert = (v.NSt[prev] / p.NStmax) ** (3 * p.alpha)
        FGwert = (v.FnG[prev] / p.FnGmax) ** p.beta
        etawert = (eta / p.etaH2O) ** p.gamma
        v.kLa[i] = p.kLamin + p.kLamax * FGwert * NStwert / VLwert * etawert * (1 - v.AAF[prev])

        v.OTRmax[i] = v.kLa[prev] * a.cOLmax  # MATLAB lag
        StO = v.OTRmax[prev] / v.QO2max[prev] if v.QO2max[prev] > 0 else 1e20

        v.xOL[i] = v.cOL[prev] / a.cOLmax

        base = 1 + StO - (1 - v.RQ[prev]) * StO * v.xOL[prev]
        v.OTR[i] = (
            v.OTRmax[prev]
            * (v.xOGin[prev] - v.xOL[prev])
            * 2
            / (base + np.sqrt(base**2 - 4 * (1 - v.RQ[prev]) * StO * (v.xOGin[prev] - v.xOL[prev])))
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

        cbase = 1 + a.StC - (1 - 1 / v.RQ[prev]) * a.StC * a.xCL
        v.CTR[i] = (
            a.CTRmax
            * (a.xCGin - a.xCL)
            * 2
            / (cbase + np.sqrt(cbase**2 - 4 * (1 - 1 / v.RQ[prev]) * a.StC * (a.xCGin - a.xCL)))
        )
        v.xCG[i] = (v.QCO2max[prev] * a.xCGin - v.CTR[prev]) / (
            v.QCO2max[prev] - (1 - 1 / v.RQ[prev]) * v.CTR[prev]
        )

        # Optimal specific uptake rates [1/h]
        qS1pXopt = 0.0 if v.cS1L[prev] <= 0 else a.qS1pXmax * v.cS1L[prev] / (v.cS1L[prev] + p.kS1)
        qS2pXopt = (
            0.0
            if v.cS2L[prev] <= 0
            else a.qS2pXmax
            * v.cS2L[prev]
            / (v.cS2L[prev] + p.kS2)
            * p.kI21
            / (v.cS1L[prev] + p.kI21)
        )

        # Acetate is the product, fed back as the third substrate.
        v.cS3L[i] = 0.0 if v.cP1L[prev] <= 0 else v.cP1L[prev]
        qS3pXopt = (
            0.0
            if v.cS3L[prev] <= 0
            else a.qS3pXmax
            * v.cS3L[prev]
            / (v.cS3L[prev] + p.kS3)
            * p.kI31
            / (v.cS1L[prev] + p.kI31)
            * p.kI32
            / (v.cS2L[prev] + p.kI32)
        )

        qXpXSgr = p.yXpS1gr * qS1pXopt + p.yXpS2gr * qS2pXopt
        qXpXOgr = (
            0.0
            if v.cOL[prev] <= 0
            else p.yXpOgr * (a.qOpXmax - p.qOpXm) * v.cOL[prev] / (p.kO + v.cOL[prev])
        )
        qXpXgr = min(qXpXSgr, qXpXOgr)
        a.limitation = "substrate" if qXpXSgr < qXpXOgr else "oxygen"

        v.qXpX[i] = qXpXgr - a.mySm if p.f_Inoc == 1 else 0.0

        qS1pX = min(qXpXgr / p.yXpS1gr, qS1pXopt)
        qS2pX = min((qXpXgr - p.yXpS1gr * qS1pX) / p.yXpS2gr, qS2pXopt)
        qS3pX = min((qXpXgr - p.yXpS1gr * qS1pX - p.yXpS2gr * qS2pX) / p.yXpS3gr, qS3pXopt)

        qAlpX = p.yAlpXgr * qXpXgr
        qAcpX = p.yAcpXgr * qXpXgr
        qOpX = qXpXgr / p.yXpOgr + p.qOpXm

        v.OUR[i] = qOpX * v.cXL[prev] if p.f_Inoc == 1 else 0.0

        qP1pX = (p.yP1pS1 * qS1pXopt + p.yP1pS2 * qS2pXopt) * p.kIP1O / (
            p.kIP1O + v.cOL[prev]
        ) - p.yP1pS3 * qS3pX

        return qXpXgr, {
            "qS1pX": qS1pX,
            "qS2pX": qS2pX,
            "qS3pX": qS3pX,
            "qAlpX": qAlpX,
            "qAcpX": qAcpX,
            "qOpX": qOpX,
            "qP1pX": qP1pX,
        }
