# Verification of the *E. coli* model against MATLAB

As of 9 September 2026 · project plan §2.4 and §3 · last extended after phase 3

---

## The question

Does the Python port compute the same thing as the MATLAB application?

This is not a question about the physics — that sits unchanged in the model —
but about the **fidelity of the translation** of 953 lines of
`Escherichia_coli.m` plus 73 lines of ODE definitions and 257 lines of
initialisation.

Errors of this kind are particularly treacherous because they produce plausible
results: an index off by one, an `end-1` instead of `previdx`, a sign, MATLAB's
1-based counting, an `any()` on a scalar. The curves still show growth,
substrate consumption and the pO2 drop. None of this project's 24 plausibility
tests would notice anything.

Worse: in more than two dozen places the MATLAB original writes a value at `idx`
and reads the one at `idx-1` in the next expression. These peculiarities have
deliberately been taken over literally (marked in the code as `# MATLAB lag`).
If one of them had been translated the wrong way round, that would go undetected
without a reference run.

## The data source

A MATLAB licence was not available. What is used instead is `MyProject_11.txt` —
an export the application itself wrote.

| File | Date |
|---|---|
| `Escherichia_coli.m` | 22 April 2026 |
| `Escherichia_coli_Initialization.m` | 19 April 2026 |
| **`MyProject_11.txt`** | **27 April 2026** |

The export is five days younger than the model source and therefore demonstrably
comes from the same code. Contents: 43 variables, 2983 steps, dt = 2 s
(0.000555… h), 1.657 h of process time.

### The parameter set had to be reconstructed

The export contains none. The project it belongs to has been deleted — of 733
projects ever created, 14 still exist (see `docs/` and CLAUDE.md on the database
forensics).

The parameter set of **project 716** of the shipped database is used. The
assignment is evidenced, not guessed:

| Quantity in the run | Value | Parameter in project 716 |
|---|---|---|
| `cS1L(0)` | 10 | `cS1L0` = 10 |
| `thetaL(0)` | 32 | `thetaL0` = 32 |
| `pHL(0)` | 7.5 | `pH0` = 7.5 |
| `pO2(0)` | 100 | `pO20` = 100 |
| `VL(0)` | 10 | `VL0` = 10 |
| `NSt(0)` | 400 | `NStw` = 400 |
| `FnAIR(0)` | 7.5 | `FnAIRw` = 7.5 |
| `xOGin(0)` | 0.2094 | `xOGcal` = 0.2094 |
| `pG(0)` | 200000 | `pGcal` + `deltapGw`·10⁵ = 150000 + 50000 |
| `kLa(0)` | 97.8605 | from `kLamin`, `kLamax`, `FnGw`, `NStw`, `NStmax`, `VL0`, `VLmin` |
| `NSt(1)` | 450 | 0.3 · `NStmax` — the lower limit of the pO2 controller |

Eleven independent quantities, two of them composed from several parameters. The
agreement to 1e-09 that follows confirms the choice conclusively.

### Inoculation

`cXL` is zero in rows 0 and 1 and equals 3.0 in row 2. The inoculation was
therefore switched on **during** the run, not before it. The comparison
reproduces that: `f_InocStart = 0`, and `f_Inoc` is set to 1 in the second step.

## The comparison window: steps 0 to 903

At step 403 a fed-batch phase begins in the run. The project it belongs to has
been deleted, but the phase could be **reconstructed**:

`handleExponentialFeed` computes the start rate from the state at the beginning
of the phase. From the state at step 402 it follows that

```
FRj = ((qXpX1w + qS1pXm·yXpS1gr) · VL · cXL) / (yXpS1gr · cS1R1) = 0.03899203 l/h
```

and the run shows exactly `FR1 = 0.03899203` at step 403 — agreement to eight
decimal places. The feed then grows at a measured 0.100000 1/h, which is exactly
`qXpX1w`. That establishes the type (exponential feed), the reservoir (1) and
the starting point (step 402).

With this phase the comparison reaches **step 903** and covers the exponential
feed as well. The reconstruction is in `tests/reference_data/extract.py`, the
derived values in the metadata set.

At step 904 it ends — that is where the pH controller's dead band takes hold
(see below).

## The result

### State variables and balances

| Quantity | MATLAB @402 | Python @402 | rel. | abs. |
|---|---:|---:|---:|---:|
| `cXL` | 3.22525633 | 3.22525663 | 4.9e-07 | 1.5e-06 |
| `cS1L` | 9.49029966 | 9.49029928 | 2.7e-07 | 2.7e-06 |
| `cS3L` | 0.0281950007 | 0.0281942084 | 4.1e-04 | 7.9e-07 |
| `pHL` | 6.66754008 | 6.66754960 | 1.4e-06 | 9.5e-06 |
| `thetaL` | 31.9531001 | 31.9530837 | 1.1e-06 | 3.5e-05 |
| `VL` | 10.0398611 | 10.0398611 | **5.5e-14** | 5.6e-13 |

Across the full window up to step 903 the primary quantities stay at
**≤ 2.1e-06**, the secondary ones at an absolute ≤ 7.1e-01 (`NSt`, which runs
over 400–1306 rpm).

### Measured quantities (first-order lags)

| Quantity | rel. | abs. |
|---|---:|---:|
| `pHLm` | 2.5e-12 | 1.9e-11 |
| `thetaLm` | 1.0e-12 | 3.2e-11 |
| `pO2m` | 3.1e-11 | 3.1e-09 |
| `cS1Lm` | 9.3e-14 | 9.3e-13 |

### The fast oxygen loop

These quantities pass through zero, which makes a relative bound meaningless
there — what counts is the absolute deviation in relation to the range they
cover.

| Quantity | rel. | abs. | Range in the run |
|---|---:|---:|---|
| `pO2` | 6.4e-04 | 2.1e-02 | 11.3 … 101.1 |
| `cOL` | 8.9e-04 | 3.6e-06 | 0.00128 … 0.0118 |
| `OUR` | 8.7e-05 | 8.0e-05 | 0 … 0.982 |
| `OTR` | 2.0e-03 | 1.2e-03 | 0 … 0.869 |
| `kLa` | 2.1e-03 | 2.2e-01 | 69.9 … 124.1 |
| `NSt` | 1.4e-03 | 7.1e-01 | 400 … 550 |
| `xOG` | 7.5e-05 | 1.5e-05 | 0.196 … 0.209 |
| `RQ` | 3.9e-02 | 1.4e-04 | 0.0001 … 1.047 |
| `CTR` | 1.8e-02 | 3.9e-04 | −1.271 … 0.143 |

Exactly identical across the whole window: `pG`, `FnG`, `FT1`, `FT2`, `QO2max`
(to within 5e-14).

### The first twelve steps

Before any controller switches, the two implementations are numerically the same
program:

| Quantity | rel. deviation |
|---|---:|
| `VL` | 4.6e-15 |
| `pHL` | 1.3e-10 |
| `cS1L` | 2.8e-09 |
| `cXL` | 4.8e-09 |
| `thetaL` | 2.7e-07 |

`thetaL` lags by one decimal. The temperature balance is the stiffest part of
the system and shows MATLAB's own solver tolerance first.

## What the run covers

**Checked:** the 18 ODE states, the Newton iteration for the pH, oxygen and CO₂
transfer with Stanton numbers, the temperature system with jacket and cooling
circuit, the growth kinetics with substrate and oxygen limitation, acetate
formation and re-utilisation, the stirrer controller over 400–1306 rpm, both pH
pump directions, the first-order lags of the measured quantities, the volume
balance with titration, and — since phase 3 — the **exponential feed including a
phase transition**.

**Not checked:** pure O₂, N₂ or CO₂ aeration (`FnO2`, `FnN2`, `FnCO2` zero
throughout), antifoam addition (`AAF` zero), harvest, glycerol as a substrate
(`cS2L` zero), pulse feed, the operating modes `Mode_pO2` 2, 3 and 4, `Mode_pH`
0, `Mode_temp` 0.

## Why there can be no global tolerance

The plan foresees a bound of `rtol = 1e-4` across the whole run in §2.4. For this
system that is unreachable, however good the translation.

The pH controller has a hard dead band:

```matlab
if abs(app.p.pHw - app.v.pHL(previdx)) < 0.1
    app.v.FT1(idx) = 0;  app.v.FT2(idx) = 0;
```

The process sits practically on that threshold. In **19 % of all steps** MATLAB
is closer than 1e-3 to it. At step 785 it looks like this:

```
MATLAB  pHL = 6.5999948   distance 0.1000052   controller ON
Python  pHL = 6.6000085   distance 0.0999915   controller OFF
Difference in pH: 1.4e-05
```

(Without the reconstructed feed phase the first divergence was at step 785 and
the deciding difference was 1.0e-04. With better agreement the divergence moves
later and the difference that triggers it becomes **smaller** — exactly the
picture that amplification at a discontinuity produces.)

A difference in the fourth decimal place decides whether the alkali pump runs.
Across the full run, **1016 of 2983 steps** come out differently. Every rounding
difference — between `ode15s` and LSODA, between two MATLAB versions, between
two processors — is amplified at this discontinuity.

Bit-exact long-term reproduction is **fundamentally** impossible here, not merely
difficult. Hence: a sharp check in the window before the first switch, none
after it.

This is not a defect of the model. A two-point controller with a dead band is
usual and correct in bioprocess engineering. It is a property one has to know
about when designing a regression test.

## Reproduction

```bash
pytest tests/test_organisms.py -k reference -v
```

The fixtures are under `tests/reference_data/` and can be regenerated with
`python tests/reference_data/extract.py ecoli` as long as
`~/Documents/Biofermentation Simulation Version 2.2/MyProject_11.txt` is
present.

The tolerances in `test_organisms.py` are derived from the tables above and have
at least a factor of two in reserve. They are measured, not guessed — anyone who
loosens them later should add the reason here.

## Pichia pastoris

Not verified, and that stays so for the time being.

The only available run (`Thesis_SimulationAppDB.db`, project 520, 2 March 2025)
is 14 months older than `Pichia_pastoris.m` (22 April 2026). It shows in `kLa`:
the current formula does not reproduce the run's values, although the
translation follows it line by line.

The reason is known: the strategy of the software was changed and only the
*E. coli* model was brought along. Pichia still stands on the older approach. A
template from the current source does not exist, and while that is so there can
be no verification.

The Pichia translation follows the source that does exist line by line and is
backed by structural and plausibility tests — that is weaker than a verification
and is not presented as one here.

The thesis run stays in place as a fixture. With its seven phases it is the
natural template for the phase automaton of phase 3, as soon as the Pichia model
is brought up to date.
