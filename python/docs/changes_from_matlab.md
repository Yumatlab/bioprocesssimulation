# Changes from the MATLAB version

This document lists every place where the Python application deliberately
behaves differently from the MATLAB application it was translated from
(version 2.2), and says **why**. It is written so that a change can be traced
without reading the code: what MATLAB did, what the Python version does, the
reason, and what it changes in the numbers.

What this document does **not** list: anything that only looks different (a
new window, a renamed button) and changes nothing in a run or in the stored
data. Those are in section 6, briefly, and in the manual.

| Version | What it is |
|---|---|
| **3.0.0** | The translation. Line by line, verified against MATLAB for *E. coli* (see `verification_escherichia_coli.md`), with the corrections of sections 1–4 that are marked 3.0.0. |
| **3.0.1** | The same verified translation, plus the changes marked 3.0.1. **The last version in which the *E. coli* model reproduces MATLAB's arithmetic exactly**, including MATLAB's own errors. The verification record of this version is in `verification_escherichia_coli.md`, section "Record for version 3.0.1". |
| **3.1.0** | Fixes errors inherited from MATLAB (list: `FEHLER.md`). From here on, the *E. coli* comparison with MATLAB may differ where an error was fixed — on purpose, and each such fix is added below with its effect. |

How to read the entries: **MATLAB** is what the original does, **Now** what
the Python version does, **Why** the reason, **Effect** what it changes, and
whether that was measured or only read in the code.

---

## 1. Changes to what a run computes

### 1.1 Gas supply: four errors in the aeration — 3.0.0

All four lie outside the verified window (the reference run uses
`Mode_pO2` = 1 with `f_O2` = 1 and never enters these branches). The
comparison with MATLAB stayed identical after each of them — measured.

1. **Oxygen flow mixed a current setpoint with a previous flow.** MATLAB:
   `FnO2 = FnGw - FnAIR(previdx)`. At 100 % oxygen demand the air flow goes to
   zero and oxygen becomes `FnGw - FnGw` = 0 — the gas runs out at the moment
   it is needed most (measured: 27 of 2000 steps). On the way there the flow
   turns negative (−9 l/min for *Pichia*) and the inlet oxygen fraction leaves
   [0, 1]. The MATLAB source carries the comment `% HIER NOCHMAL CHECKEN` at
   exactly this line. **Now:** `FnAIR(idx)`.
2. **Pichia summed the total gas flow from the previous step**, *E. coli*
   from the current one, and the inlet fraction then divided the current
   components by the old sum — measured down to 0.079 where 0.209 (air) is
   the lowest possible value. **Now:** *Pichia* sums like *E. coli*.
3. **Division by zero.** *E. coli* checked `FnG(previdx) > 0` and then divided
   by `FnG(idx)`; a step without gas gave 0/0. **Now:** the index that is
   divided by is checked.
4. **Switching off pure oxygen switched off the air.** In *E. coli* the
   `else` branch of `f_O2` wrote `FnAIR(idx) = 0` instead of `FnO2(idx) = 0`.
   Measured result: air and oxygen both zero next to a total gas flow of
   7.5 l/min fed by nothing, inlet oxygen 0, OTR negative, pO2 falling to 0
   while the screen showed the reactor as aerated. **Now:** the right flow.

**Why:** each is a plain programming error with a measured, wrong result.
**Effect:** none in the verified window; outside it, gas flows and pO2 are
physically possible again. Tests: the inlet mixture stays within
[`xOAIR`, 1], no flow is negative, `FnG` is always the sum of its parts.

### 1.2 Sensor lag of *Pichia* — 3.0.0

**MATLAB:** the first-order lag of a measurement (`meas_transfer_function`)
converts the step width from seconds to hours although it already is in
hours. Each step then closes 2.6·10⁻⁹ of the gap between true and measured
value: **every measured quantity stays at its starting value.**
**Now:** *Pichia* uses `sensor_lag`, the same formula with one conversion
(1/30 per step at τ = 60 s and Δt = 2 s). *E. coli* keeps the MATLAB formula
in 3.0.x — see the box below.
**Why:** *Pichia*'s closed-loop methanol feed is the only controller in the
application that reads a *measured* value; on a frozen measurement it
regulates nothing and the culture dies of methanol toxicity (measured).
*Pichia* is not verified against MATLAB, so nothing verified is lost.
**Effect (measured):** the measured methanol follows the true value (1.086
against 1.092 g/l) and the feed loop works.

> **Why *E. coli* still has the frozen measurements in 3.0.x.** The
> verification shows the translation is right *because* it reproduces
> MATLAB to 10⁻¹² — including this error. *E. coli* does not notice it: its
> feed controller reads the true concentration. The frozen values only show in
> plots, the data table and exports. Fixing it is item F-02 of `FEHLER.md`,
> planned for 3.1.0.

### 1.3 Anti-windup, switchable per controller — 3.0.0

**MATLAB:** the integrators of the controllers keep integrating while the
output is stuck at its limit (windup). *Pichia*'s stirrer controller has a
clamp meant as anti-windup, but in the wrong unit: it limits a normalised
value (0…1) with the stirrer speed in rpm. The upper limit can never act, the
lower one always does — the integral can never become negative, and a
stirrer that has been driven up never comes down again.
**Now:** a switch per controller (`f_awpO2`, `f_awLW`, `f_awfeed`) in the
controller dialogs, default **off** = exactly MATLAB. On, the integrator
stops while the output is at a limit and the error pushes further out. For
*Pichia*'s stirrer the switch replaces the wrong clamp.
**Why:** windup is the most common reason a controller overshoots for a long
time; students should be able to see and switch it.
**Effect (measured):** off — identical to MATLAB. *Pichia*, project 519,
stirrer mode: pO2 ends at 108.7 % with the original clamp and at 78.3 % with
the switch on. *E. coli*, project 716: pO2 29.8 → 32.1 %.

### 1.4 *Pichia*: feed gains of reservoir 2 had the wrong sign — 3.0.0 / 3.0.1

**MATLAB database:** `KP/KI/KD_feedR2` = −2 / −15 / −0.009, digit for digit
the gains of the pO2 feed controller. There a negative sign is right (high
pO2 means the culture can take more substrate); on a substrate loop, whose
error is `setpoint − concentration`, it reverses the controller: too little
methanol gives a negative output and a pump that stays shut.
**Now:** 1 / 5 / 0.005, found by measurement (`tools/tune_pichia.py`).
**3.0.0:** corrected in the shipped organism defaults and models.
**3.0.1:** also in projects and in databases created before the correction —
at application start, with a backup copy, only where the value is still the
wrong one, and never in a project that has a stored run (its recording was
computed with the old values). A corrected project says so in its log.
**Why:** measured before: the pump at its stop for 100 % of an eight-hour run.
**Effect (measured):** methanol held at 1.38 g/l against 1.5, pump never at a
stop, biomass 21.0 instead of falling to 17.4 g/l.

### 1.5 *Pichia*: three default parameters carried other parameters' values — 3.0.0

**MATLAB database:** the default set of *Pichia* listed `yXpOgr`, `yCpO` and
`qOpXm` twice; the second row carried value *and* description of the methanol
toxicity parameters. Projects created from it computed with `yXpOgr` = 40
instead of 1.773, `yCpO` = 15 instead of 1.375, `qOpXm` = 0.5 instead of
0.0117.
**Now:** repaired (`db/repair.py`); the project values restored from the
model set, which was correct throughout.
**Effect:** roughly three times the oxygen uptake before; the pO2 of 1000 %
seen earlier came from this.

### 1.6 Liquid-weight controller: no harvest below the setpoint — 3.0.1

**MATLAB:** in automatic mode the integral part kept the harvest pump running
after the weight had fallen below its setpoint, until the integral had
unwound.
**Now:** at or below the setpoint nothing leaves the reactor and the
integral starts from zero again.
**Why:** requested by the author — harvesting below the setpoint empties the
reactor further than intended.
**Effect:** none in manual mode or in the reference run (`Mode_harvest` = 0).
Test: without the change the harvest test fails.

### 1.7 Equality in phase conditions — 3.0.0

**MATLAB:** the condition "=" is stored as `=`, but the code compares with
`==` — an equality condition never fired.
**Now:** both spellings are understood.

### 1.8 No stored zero for "not measured" — 3.0.0

**MATLAB:** unused slots of a time series were written to the database as 0
— "not measured" became a measured zero.
**Now:** values that were not computed are not written; they come back as
"no value".

### 1.9 Antifoam reservoir — 3.0.1 (addition)

**MATLAB:** antifoam has no volume; `AAF` is an effect that decays.
**Now:** two parameters (`VT30`, `FT3max`) and two series (`VT3`, `FT3`)
give the antifoam bottle a level that empties at the pump rate while dosing.
**Effect:** display only — the antifoam effect does not read the reservoir,
the volume does not enter the reactor. Measured: every other series
identical.

---

## 2. Changes to what the operator sees (the run is the same)

| Change | Version | MATLAB | Now, and why |
|---|---|---|---|
| Acid and alkali pump in the Variable Pool | 3.0.0 | the field labelled `F_T1` showed `FT2` | each shows its own pump |
| Running and completed phases | 3.0.0 | could be edited after they had been applied | locked: a change would describe a process that did not take place |
| y-axes with a negative part | 3.0.1 | ticks on multiples of the step, so a scale from −0.1 to 0.5 had its ticks 40 px off all others | zero on a tick and round steps (µ: −0.125 … 0.5); the scales can be read across again |
| Tick labels | 3.0.1 | 0.36 labelled "0.4" (decimals from the step size) | as many decimals as the value needs |
| Time axis | 3.0.1 | widened by itself once the run passed *t* max | ends at *t* max; "Extend t max with the run" lets it grow |

---

## 3. Changes to the database

All of these keep the stored data; none rewrites a value of a stored run.

| Change | Version | Why |
|---|---|---|
| `processTab.end_typeID` pointed at the wrong table | 3.0.0 | 12 foreign-key violations |
| `MATCH SIMPLE` removed; foreign keys switched on per connection | 3.0.0 | SQLite has foreign keys **off** by default — the real reason cascades did not work |
| `UNIQUE (projectID, parameterID)` enforced | 3.0.0 | a parameter twice in a project |
| BIOSTAT B carried the values of BIOSTAT ED | 3.0.0 | corrected from `Parameter Overview.xlsx` |
| Log stores event type and process time | 3.0.0 | a reopened project could not rebuild its log |
| Process ids numbered per table, not per project | 3.0.0 | the second project to be saved collided with the first |
| Indexes on foreign keys | 3.0.0 | deleting a project: 22.8 s → 0.28 s (measured) |
| Creating and deleting a project in one transaction, cascade by SQLite | 3.0.0 | **the productive MATLAB database was destroyed this way**: deleting switched foreign keys off and deleted step by step without a transaction |
| Backup after every save | 3.0.0 | never implemented in MATLAB; the database was corrupted twice |
| `tmax` removed | 3.0.0 | a parameter nothing read |
| Stored resolution (one step in *n*) | 3.0.0 | file size without changing Δt |
| Data limit (5 million values) | 3.0.1 | reopening a larger project needs more memory than a laptop can be counted on to give (measured) |
| Process templates (three tables) | 3.0.1 | new |

---

## 4. Errors of the translation itself, found and fixed

Not differences from MATLAB but mistakes of the port, listed so they are not
taken for one:

- A reopened project was inoculated again, replacing the grown biomass
  (3.0.0). MATLAB had the right check; the translation had lost it.
- Deleting an upcoming phase restarted the running one: its start time was
  overwritten and the fed-batch rate recomputed to 0 (3.0.1).

---

## 5. Inherited from MATLAB and still open

The errors of the original that 3.0.1 still contains are listed with their
effect in `FEHLER.md`, section 2 — among them the frozen measurements of
*E. coli* (F-02), the crossed pump limits of acid and alkali (F-04), the
antifoam that never doses after inoculation at time 0 (F-07) and the
controller states lost on reopening (F-12). Each one that is fixed moves into
this document with its version and its measured effect.

---

## 6. Additions without a MATLAB counterpart

Short, because they change nothing MATLAB computed: the Controllers tab (P, I
and D of every loop), the PCS tab (the plant as a flow sheet, operable),
detachable tabs, settings and student view, the library for bioreactors,
organisms and models, export and import of projects and definitions, process
templates, the data limit, the stored resolution. Their use is described in
`manual.md`.
