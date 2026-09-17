# Manual

Biofermentation Simulation 3.0 — for the people who use it.

This manual describes what the application does and how to operate it. It
assumes a basic knowledge of bioprocess engineering, but no programming. If you
want to know how the application is *built*, that is in
[`architecture.md`](architecture.md); if you want to develop it further, in
[`development.md`](development.md).

Every statement here can be checked. Where a parameter is named, it is named
the way the application and the database name it — `pHw`, `cS1Lw`, `Mode_pO2`.
To look one up, open **Project → Parameters…**.

---

## 1. What the application simulates

A stirred-tank reactor in batch, fed-batch or induction operation. Every time
step computes:

- **Mass balances** for biomass, substrates, product, dissolved oxygen,
  dissolved CO₂ and the titration agents — eighteen coupled differential
  equations, solved with LSODA.
- **Four control loops**: pH, temperature, oxygen partial pressure and liquid
  weight.
- **The feed**: manual, exponential, as a pulse, or controlled against a
  substrate concentration.
- **A phase automaton** that advances the process on conditions you define
  yourself.

Two organisms ship with it: *Escherichia coli* and *Pichia pastoris*.

The step width is `deltatsec` in the project — the organisms that ship bring
2 seconds of process time with them. The **Δt [s]** field in the control window
shows and changes exactly that value; the application takes it from the project
when it opens one, not from a default of its own. A 24-hour fermentation
computes in a few seconds.

**What the application is not:** a replacement for an experiment. It computes a
model, and a model is only as good as its parameters. Section 9 says what has
been checked against real data and what has not.

---

## 2. The first run

### Creating a project

After the start you see four buttons. **Start New Project** opens the creation
window. There you enter a name and choose a **model** from the list.

A model is the combination of an organism and a bioreactor — "Escherichia coli
in BIOSTAT ED", say. The project's complete parameter set is copied from it:
around 280 values, from the vessel geometry to the growth kinetics. That copy
belongs to the project alone from then on. If you later change the organism's
default values, that reaches **new** projects, not existing ones. This is
deliberate — it is the only thing that keeps a stored run reproducible.

### The control window

The control window opens next. Tabs on the left, the run controls on the right:

| Element | Meaning |
|---|---|
| **Run / Pause** | starts and holds the simulation |
| **Inoculate** | inoculates the vessel |
| **Parameters…** | the complete parameter set |
| **Δt [s]** | step width in seconds of process time |
| **Speed factor [x]** | how many steps per screen refresh |
| **Open Plot / Save / Exit** | plot, save, quit |

Two lamps at the top right: **Process Running** and **Inoculated**.

### Inoculating and starting

**Before** the first step, `Inoculate` is a toggle: pressed means the run starts
with cells in the vessel (`cXL0`, 3 g/l by default). Not pressed means the
vessel starts sterile.

**During** the run it is a single press: the inoculation happens in the next
step and the button goes dark afterwards.

Without inoculation nothing grows — the growth terms are tied to `f_Inoc`.
Anyone who starts the run and sees nothing happen has usually forgotten this.

---

## 3. The tabs

| Tab | What for |
|---|---|
| **Control Options** | the five control panels — the workplace |
| **Controllers** | what each controller is computing right now |
| **Variable Pool** | every state variable as a number |
| **Process Manager** | the phases of the process |
| **Log** | the record of the session |
| **Information** | project data and where the application comes from |

Four of them can be switched off under **Settings…** on the starting screen;
Control Options and Information always stay.

---

## 4. The control panels

Every panel is built the same way: the **mode selector** with a lamp at the top,
below it the **setpoints** (left) and **measured values** (right, grey, not
writable), below those the **switches**, and at the foot a **Parameters** button
for this loop's controller gains.

The lamp beside the mode says whether this loop is *controlling* — not which
mode is selected. The button says that.

### pH-Control

| | |
|---|---|
| Modes | `Mode_pH`: **Manual**, **Auto** |
| Setpoint | `pHw` — pH setpoint |
| Measured | `pHL` |
| Switches | `f_alkali`, `f_acid` — alkali and acid pump by hand |

In Auto mode a cascade is at work: a master controller turns the deviation into
a manipulated variable, two slave controllers drive acid and alkali. The
controller has a **hard dead band of 0.1 pH** — inside it, it does nothing. That
is not a defect; it stops the pumps from cycling endlessly.

### Temperature-Control

| | |
|---|---|
| Modes | `Mode_temp`: **Manual**, **Auto** |
| Setpoint | `thetaLw` [°C] |
| Measured | `thetaL` |
| Switches | `f_cooling`, `f_heating` |

Control is through the jacket; the model computes the cooling-water and steam
mass flows along with it.

### pO2-Control

The only loop with five modes, which is why it is drawn as a **rotary switch**.
The dot on the knob is green for a control mode and red for manual operation.

| `Mode_pO2` | Manipulated variable |
|---|---|
| **Manual** | nothing is controlled; the setpoints below apply |
| **Agitation** | stirrer speed `NSt` (limits 0.3 to 1.0 of the maximum speed) |
| **Aeration** | total aeration rate `FnG` (30 to 100 %) |
| **Gasmix** | oxygen fraction in the inlet gas `xOGin` |
| **Feed** | the feed rate — limiting the oxygen demand through the substrate |

Fields: `pO2w` [%] setpoint, `NStw` [1/min] stirrer speed, `FnGw` [l/min]
selected aeration rate, `FnAIRw` [l/min] air, `FnO2w` [l/min] pure oxygen.
Which field is active depends on the mode; the rest go grey.

> **pO2 above 100 % is not an arithmetic error.** The probe is calibrated
> against air. Aerating with enriched oxygen can take you above it — 124 %
> measured at 15 l/min air plus 1 l/min O₂. That is physically correct.

### Liquid Weight

| | |
|---|---|
| Modes | `Mode_harvest`: **Manual**, **Auto** |
| Setpoints | `LWw` [kg] liquid weight setpoint, `FHrelw` [%] harvest rate |
| Switches | `f_harvest` |

### Feed Control

| | |
|---|---|
| Modes | `Mode_feed`: **Manual**, **Closed loop** |
| Setpoints | `cS1Lw` [g/l] substrate setpoint, `FR1w` [l/h] pump rate |
| Read-only | `FR1max` [l/h] maximum pump rate of the reservoir |
| Switches | `f_feed` — the pump |

If the organism has several reservoirs, a selector **R1 / R2** stands above
them; the parameter behind it is `R_feed`.

> **The mode chooses *how* to pump — the switch, *whether*.** With `f_feed`
> off, nothing happens whatever mode is selected. The controller does not even
> compute. This is the most common cause of "the feed controller does nothing".

In closed-loop mode a PID controller drives the pump so that `cS1L` is held at
`cS1Lw`. It can only add, not remove: if the substrate concentration is
**above** the setpoint, the pump stands still until the organism has used up
the excess.

### Anti-windup

Three of the panels carry a switch at the foot of their **Parameters** dialog:
pO2-Control, Liquid Weight and Feed Control.

**What it does.** An integrator keeps adding up the deviation. While the
manipulated variable already sits at its limit — the pump at its maximum, the
stirrer at its ceiling — adding more changes nothing in the process but does
change the controller: the integral runs up, and when the deviation finally
turns round the controller keeps pushing the wrong way until it has unwound
again. With the switch on, the integral stops growing exactly while the output
is at its limit and the deviation would push it further out, and it resumes the
moment the deviation turns.

**Off is the default, in every project.** The integrator that runs on is the
structure of the MATLAB version, and the verified reference run was recorded
with it. Switching this on changes the numbers — deliberately.

**It is `cyclic`**, so it can be thrown during a run. That is the interesting
way to use it: open the **Controllers** tab, watch the I bar of one loop grow
while its manipulated variable is stuck, and throw the switch.

Two panels have no switch, for two different reasons. **pH-Control** has no
integrator at all — it is a P controller with a dead band. **Temperature-Control**
has one, but its output never comes near the stops of the split range: measured
between −2.3 and +3.2 over a two-hour batch against a setpoint 12 K away, on a
loop whose stops sit at −10 and +10000. There is nothing there to wind up, and a
switch that changes nothing would only suggest otherwise.

**For *Pichia* the switch does more than hold an integrator.** Its stirrer
controller carries an anti-windup of its own from the MATLAB source, written in
the wrong unit: it keeps the integral from ever going negative, so a stirrer
that has once been driven up cannot come down again. With the switch off that
is reproduced exactly; with it on, the integral is free and pO2 ends at 78 %
instead of 109 % on the shipped Pichia project. Neither reaches the 20 %
setpoint — see section 9.

---

## 5. How a process runs: phases

The **Process Manager** shows the process as a row of phases with arrows
between them. Each phase has a name, a type, a start and an end condition, and a
status lamp.

### The five phase types

| Type | What happens when the phase starts |
|---|---|
| **Manual** | nothing; the phase only waits for its end condition |
| **Update Parameter Set** | the stored parameter values are applied |
| **Exponential Feed** | the pump rate grows as `FR = FRj · e^(qXpX1w·(t−tj))` |
| **Pulse Feed** | the pump runs at `FR1max · kR1` |
| **Stop** | the run is halted |

### Conditions

**Start**: "End of previous phase", a variable condition (`cXL > 5 g/l`), or
"Batch end" — detection of substrate exhaustion through the rise in pO2.

**End**: "Next phase condition", a variable condition, or a timer.

### What a phase offers in parameters

The **Parameters…** button in the phase dialog shows different things depending
on the type:

- **Update Parameter Set**: every parameter that can be changed during a run —
  setpoints, modes, flags, controller gains.
- **Exponential Feed**: the five values the rate is computed from, for this
  phase's reservoir.
- **Pulse Feed**: `kR1` and `FR1max`.
- **Manual** and **Stop**: nothing, the button stays disabled.

Only what you actually change is stored. An untouched field means "leave it as
it happens to be then" — not "set it to this value".

> **A running or completed phase can no longer be edited.** The automaton has
> already read its conditions and applied its parameters; a change afterwards
> would describe a process that did not take place that way.

The **arrow** between two panels forces the transition to the next phase without
waiting for the condition. It is only active after the running phase.

Editing phases is only possible while the process is **paused**.

---

## 6. Understanding the controller: the Controllers tab

The application computes the P, I and D terms of every controller in every
step — and in the MATLAB version it showed none of that. Anyone who saw pO2
oscillate did not see the I term running up, and that is usually the
explanation.

The tab shows, per loop, setpoint, measured value, deviation, the three terms as
signed bars on a shared scale, the gain and the manipulated variable.

**This is the most useful tool for learning control behaviour.** A controller
whose I bar keeps growing while the manipulated variable sits at its limit is in
windup — it will keep pushing the wrong way long after the deviation has changed
sign.

---

## 7. Evaluating

### Plot

**Open Plot** (Ctrl+G) opens a plot window that follows the run. Several windows
at once are possible. Under **Plots → Open plot from template** are stored
combinations of axes and curves.

### Data table

**Export → Open data table** (Ctrl+T) shows every time series as a table.

### Export

**Export → Export project…** (Ctrl+E) writes the run into readable files: CSVs
for people — phase type, status and unit spelled out rather than numbered — and
beside them a manifest `project.yaml`, which the application itself can read
back in.

---

## 8. Saving, closing, setting up

### Saving

**Save** (Ctrl+S) writes parameters, time series, phases and the log in **one**
transaction and then places a backup copy next to the database. The database is
not touched during the simulation: read once when the project opens, write once
at the end.

### Closing

Every way out of a project leads through the same dialog: name, author,
description, the stored resolution, and then **Save**, **Discard**, **Delete**,
**Export** or **Cancel**. Export does not close the dialog — a decision about
the project is still due. Deleting asks a second time.

The field **"Store one point per … steps"** is preset from the setting under
**Settings…** and can be changed here for this one run; the text beside it says
what the value means at this Δt. See "Stored resolution" below.

Only one project is ever open at a time.

### Three text files next to the database

They sit next to the database and can be changed with any editor:

| System | Location |
|---|---|
| macOS | `~/Library/Application Support/Biofermentation Simulation/` |
| Windows | `%APPDATA%\Biofermentation Simulation\` |
| Linux | `~/.local/share/biofermentation/` |

The environment variable `BIOFERMENTATION_DB` overrides the location — which
lets two installations run side by side without sharing a database.


| File | What for |
|---|---|
| `style.qss` | colours, spacing, fonts |
| `control_options.yaml` | arrangement of the control panels and the kind of mode selector |
| `settings.yaml` | which tabs appear, student view, refresh, stored resolution |

**Settings → Panel layout…** in the control window creates `control_options.yaml`
and opens it. A faulty file never throws the tab away: the application takes the
fallback arrangement and writes the reason into the log.

### Library

**Library…** on the starting screen manages organisms, bioreactors and models,
and imports or exports the first two. A copy of an organism with different
values is a new organism and needs no Python — the copy takes the kinetics from
its template.

**Important:** a new organism or vessel can only be selected once a **model**
exists for it. That is what the **Make selectable…** button is for — or the
**Models…** entry.

#### Models

A model is an **organism in a vessel**. It is what a project is made from: when
a project is created, the application copies the model's parameter set into it,
and from then on the project has its own. Exactly these two copies make a stored
run reproducible — and they are also why a change to a model reaches **new
projects only**.

Under **Library → Models…** the list is on the left, the model on the right:

- **New model…** — pick organism and vessel, name suggested. The parameter set
  is the union of both; where both name the same parameter, the vessel wins.
- **Duplicate…** — a copy *with the values as they are now*. This is how to make
  variants, for example a model with different controller gains for an exercise.
- **Delete…** — only if no project was created from it. The parameter values go
  with it; organism and vessel stay.
- **Name, description and every value** can be edited. The filter field above
  the list helps: a model carries around 250 parameters. A tooltip says for each
  one whether the value comes from the organism or from the vessel.

**Organism and vessel themselves cannot be swapped.** They are not two more
fields, they are what the model is made of — a swap would leave values from a
vessel the model no longer names. A different pairing is a different model.

### Untying the refresh rate from Δt

Under **Settings…** there is the check box **"Tie the refresh rate to Δt"**.
Ticked — the default — the application computes one step per tick: a speed
factor of 1 then runs in real time, whatever Δt is set to.

Untick it and the field below becomes active and sets the pace. **This changes
the speed as well:** at Δt = 10 s and a 2 s refresh the process advances ten
seconds per tick but ticks every two — the run is five times faster than
reality. The ratio of Δt to refresh *is* the factor.

In short: **Δt decides how finely it is computed, the refresh how often you see
it.** How much of it ends up in the file is a third question — the next section.

### Stored resolution

A 14-hour run at Δt = 2 s is 25,200 time points and, times 56 variables, about
1.44 million measured values. That is why projects grow large.

**Raising Δt is the wrong lever for it.** The controllers are tuned for
Δt = 2 s, and a larger Δt makes control measurably worse: the pO2 deviation
(RMS) is 9 at Δt = 2 s, 37 at 20 s and 121 at 60 s. You would get a smaller file
and a different process.

So **Settings…** has the group **Stored resolution** with the field **"Store one
point per … steps"**:

- **1 step** — the default, everything is stored.
- **5 steps** — every fifth time point is stored, so at Δt = 2 s one every
  10 seconds. The file becomes about five times smaller.

**The run itself is unchanged.** Every step is computed, controlled and
plotted; only the writing is thinned. The last computed step is always stored
whatever the value is — otherwise a resumed run would not start where it
stopped.

**The value can be changed again when saving.** The closing dialog carries the
same field, preset from the setting. That is the only moment at which anybody
knows how long the run actually turned out to be. The check box **"Offer this
again in the closing dialog"** takes that question away: unticked, saving uses
the value set here without asking — one decision for a whole course instead of
one per student.

**What a thinned project shows when loaded:** exactly the points that were
stored. Plot, data table and export then have the coarser resolution — the steps
in between were not lost, they were deliberately not written. The resumed run
computes at the full Δt again. If you need a run for an evaluation, leave the
value at 1.

### Student view

**Settings…** can lock the run controls: Δt stays visible but unchangeable, and
the speed factor disappears entirely. A run everybody started with the same step
width is comparable. When it is active, the window title says so.

---

## 9. What has been checked, and what has not

Honesty about the limits is part of a simulation tool.

**Verified: the *E. coli* model.** Against a reference run of the MATLAB
application. Across the batch phase, biomass, substrate, pH and temperature
agree to ≤ 1.5·10⁻⁶, the liquid volume to 5.5·10⁻¹⁴. The comparison reaches into
the fed-batch phase and therefore also covers the exponential feed and one phase
transition. The details, and the reason why this needs a time window rather than
a global tolerance, are in
[`verification_escherichia_coli.md`](verification_escherichia_coli.md).

**Not verified: the *Pichia* model.** The only available reference run is 14
months older than the model source and does not reproduce its kLa formula. The
translation follows the source line by line and is backed by structural and
plausibility tests — but that is not a verification, and it is not presented as
one.

**Unchecked in detail:** `Mode_pH` = Manual, `Mode_temp` = Manual and
`Mode_pO2` = Aeration / Gasmix / Feed. The reference run does not use them. The
pulse feed is only tested structurally.

**The *Pichia* control loops do not close, and this is measured.** Its
closed-loop feed carries the gains of the pO2 feed controller — the same three
numbers, negative — which inverts a substrate loop: too little methanol gives a
positive error, a negative output, and a pump that stays shut. And it reads the
*measured* concentration, which barely moves: the first-order lag converts the
step width twice, so a step closes 2.6·10⁻⁹ of the gap. That second one is the
MATLAB original's own arithmetic and is part of what the reference run verifies,
so it is left as it is and named here instead. The consequence for a user is
concrete: with *Pichia*, **Closed loop on the feed does nothing**, and because
nothing grows, pO2 stays far above its setpoint whatever the controller gains
are. `python tools/tune_pichia.py` prints the whole chain of measurements.

**A known quirk:** some time series are computed but not stored. The offgas
fractions are called `xO2` and `xCO2` in the model and have no row at all in
`variableTab` — what is in there is `xOG`, `xCG`, `xOGin` and `xOL`. What has no
row is not written, and a resumed run restarts these quantities at their initial
value. This affects ODE states, so it is not cosmetic; when a resumed project is
opened, the application writes into the log which quantities are affected.

---

## 10. When something does not work

| Observation | Likely cause |
|---|---|
| Nothing grows | not inoculated — `Inoculate` |
| The feed controller does nothing | `f_feed` is off |
| A controller does not act | the mode is **Manual** |
| A setpoint cannot be changed | the parameter is only read at the first step (`reading_rate` = `once`) |
| The window is wider than the screen | Control Options scrolls; or use a narrower arrangement in `control_options.yaml` |
| The pH barely moves | dead band of 0.1 pH |

The **Log** is the first place to look. It records phase transitions, parameter
changes and errors with clock time and process time. The "Include operations"
filter additionally shows what was done with the application itself — plot
opened, process paused.
