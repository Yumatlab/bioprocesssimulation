# Further development

For the person who takes this software over.

This document assumes that you know bioprocess engineering and not necessarily
programming. It takes you to the point where you can develop a version 4 with
the help of **Claude Code** — an AI assistant that works in your terminal and
can read and write files. The finished starter prompt is in section 5.

One thing first, because it sets the tone of the whole document: **you do not
have to understand every line to change things responsibly.** You have to know
what you can check and what you cannot. That is what section 6 is for, and it is
the most important section here.

---

## 1. Setting up

### What you need

| | What for |
|---|---|
| **Python 3.11 or newer** | the language the application is written in |
| **Git** | manages the versions of the source code |
| **A terminal** | "Terminal" on macOS, "PowerShell" on Windows |

Python from [python.org](https://www.python.org/downloads/), Git from
[git-scm.com](https://git-scm.com/downloads). Install both with their defaults.

### Getting the source

```bash
git clone git@github.com:Yumatlab/bioprocesssimulation.git
cd bioprocesssimulation/python
```

The repository holds two folders: `matlab/` with the original MATLAB application
(version 2.2) and `python/` with this one. You work in `python/`.

### Setting up the environment

```bash
python3.11 -m venv ../.venv
source ../.venv/bin/activate          # Windows: ..\.venv\Scripts\activate
pip install -e ".[dev]"
```

A **virtual environment** (`venv`) is a self-contained folder with its own
Python installation and its own packages. It keeps this project from disturbing
any other and the other way round. The `source …/activate` switches it on; the
terminal then shows `(.venv)` in front of the prompt. Activate it again in every
new terminal window.

### Checking that everything stands

```bash
pytest
```

Expected: **605 passed, 1 skipped, 1 xfailed** in a little over a minute. If
that runs through, your environment is in order — and you have incidentally
shown that the application computes correctly on your machine.

`1 skipped` and `1 xfailed` are **not a failure**. The skipped test would need a
Pichia reference run that does not exist; the expected failure records a known
inconsistency of the database. Both explain themselves if you run `pytest -rsx`.

### Starting it

```bash
python -m biofermentation.gui.app
```

Or, on macOS, create a shortcut in `~/Applications`:

```bash
python tools/make_launcher.py
```

---

## 2. Finding your way around

Read in this order:

1. **[`manual.md`](manual.md)** — what the application can do. Operate it first,
   change it second.
2. **[`architecture.md`](architecture.md)** — how it is built, in ten pages.
3. **[`../CLAUDE.md`](../CLAUDE.md)** — *why* it is built that way. Long, but the
   most important file in the project.

`CLAUDE.md` is not an ordinary document. It is the file Claude Code **reads
automatically** before it does anything. It holds every rule, every trap and
every measurement this project has learned the expensive way. If you change
something fundamental, the reasoning belongs in there — otherwise it is lost,
and the next person makes the same mistake again.

> `CLAUDE.md` is written in German, because that is the language this project
> was developed in. It is the one file that has stayed that way; everything in
> `docs/` is English. If you would rather work in English, translating it is a
> reasonable first task — its content is what matters, not its language.

---

## 3. What you can work on without programming

A great deal can be changed without a line of code. Check first whether your
plan is one of them:

| Plan | Way |
|---|---|
| A new organism with different values | **Library → Organisms… → New from selected…**, then **Make selectable…** |
| A new bioreactor | **Library → Bioreactors…**, the same way |
| A new combination of organism and vessel | **Library → Models… → New model…** |
| Different controller gains for an exercise | **Library → Models… → Duplicate…**, then find the values with the filter field under `KP_` |
| A different arrangement of the control panels | `control_options.yaml` next to the database |
| Different colours, fonts, spacing | `style.qss` next to the database |
| Hiding tabs, student view | **Settings…** on the starting screen |
| A new plot template | **Plots → Open plot from template** |

**The line runs at the kinetics.** Different numbers are data; different balance
equations are a program. A copy of *E. coli* with different yield coefficients is
a form. An organism with product inhibition that does not exist yet is code.

---

## 4. How to work with Claude Code

Claude Code runs in the terminal, in the project folder. It reads `CLAUDE.md`
itself and therefore knows the project's rules before you say anything.

**Three habits that make the difference:**

**Say what you want to achieve — not how.** "The feed controller oscillates at
low setpoints, find out why" leads to better results than "change KP_feedR1 to
5". The question is your contribution, the debugging is its.

**Demand measurements instead of claims.** This project has the habit of backing
statements up: "measured 1174 px against 1538", "RMS 8.3 to 2.0". Ask for the
number when none comes. A change without a measurement is a guess.

**Run `pytest` after every change.** Not at the end — after every one. 605 tests
in a minute are cheap; working out a week later which of twenty changes broke
something is not.

**And a warning:** check what was changed. `git diff` shows you. You are
responsible for what you commit, even when somebody else wrote it.

---

## 5. The starter prompt for version 4

Copy this text into Claude Code when you begin. Adapt the last paragraph to your
own plan.

```text
I am taking over the development of the Biofermentation Simulation and
starting version 4. My background is pharmaceutical biotechnology, not
computer science — explain technical decisions so that I can judge them,
and ask me when a domain decision comes up that only I can make.

Read CLAUDE.md in full first. It holds the rules of this project, the traps
it has already fallen into, and the measurements behind every decision. It
is written in German; translate what you need. Then read
docs/architecture.md for the map and
docs/verification_escherichia_coli.md for what has been checked about this
model and what has not.

These rules are not negotiable:

1. The Escherichia coli model is verified against a MATLAB reference run.
   Every change to the simulation core is checked against that run before
   it stays: pytest tests/test_organisms.py. If the run deviates, tell me
   with numbers instead of loosening the tolerance.
2. Database access: always `with get_connection(path) as conn:`, one
   block, one connection, one transaction. Never
   `PRAGMA foreign_keys = OFF`. SQLite does the cascading. The MATLAB
   version's production database died of the violation of these rules; the
   forensics are in CLAUDE.md.
3. Backups through the sqlite3 backup API, never through shutil.copy.
4. The MATLAB code under matlab/ is a source to read. It is not changed.
5. No new ODE code without a reference run it can be checked against. A
   test that is green without a reference proves nothing.
6. pytest runs after every change. Carry on only when it is green.
7. Code comments and docstrings in English. Reply to me in the language I
   write to you in.

The way of working I expect:

- Back statements up with measurements. If you say something is faster,
  better or broken, give the number and how you measured it.
- Change no more than necessary. Small, traceable commits with a reason
  that says WHY, not what.
- If you make an assumption, tell me instead of hiding it.
- If something does not work, say so. An honest "this does not hold up" is
  worth more to me than a solution that is green in the test run and not in
  operation.
- Record new findings in CLAUDE.md — where they belong.

The open points are at the end of CLAUDE.md under "Offen aus Phase …".
Look at them and tell me which you consider the most important.

My first plan for version 4 is: <ENTER YOUR PLAN HERE>. Explain to me first
what it touches and what can go wrong, before you start.
```

### Why the prompt looks like this

Every paragraph has a reason, and most of them were paid for dearly:

**"Read CLAUDE.md first"** — without it every session starts from zero and
repeats solved problems.

**The seven rules** are the ones whose violation has already done damage in this
project. Rule 2 cost a database with 11.3 million data rows.

**"Back statements up with measurements"** — the single most effective sentence.
It turns "that should be better now" into "RMS 8.3 to 2.0, measured on project
716".

**"Tell me your assumptions"** — a hidden assumption is a defect that gets more
expensive later.

**"Explain first what it touches"** — in a simulation whose numbers are
verified, the reach of a change matters more than its elegance.

---

## 6. How to make a change safe

This is the section to keep.

### The three questions before every change

1. **Does it touch the simulation core?** That is `organisms/`, `core/` or
   `control/`. If yes: the reference run is your safeguard, and it has to run
   before and after.
2. **Does it touch the database?** That is `db/` or the schema. If yes: work
   against a **copy**, never against the original, and run
   `PRAGMA foreign_key_check` afterwards.
3. **Does it touch only the interface?** Then the risk is small — but layout
   promises only hold on the system you measured them on.

### Measure, change, measure again

The rule is not "test afterwards" but: **the number first, then the change.** An
example from this project you can follow:

The feed controller missed a setpoint. Instead of guessing gains, the project
was computed on a copy of the database:

```
without anti-windup   cS1L = 2.377 at setpoint 3,  I term -13.4
with    anti-windup   cS1L = 3.005,                I term   0.277
```

Only those two lines justify the change. Without them it would have been an
opinion.

### A new organism: the path

1. Create a folder under `src/biofermentation/organisms/`.
2. Derive a class from `OrganismModel`, with `@register` above it.
3. Write the four initialisation methods and `calculate_step`.
4. **Add an entry in `build/specs.py`** — otherwise the organism is missing from
   the built application, without any error message.
5. Create or import the database rows through `db/definitions.py`.
6. Create a **model** (organism × vessel), or it cannot be selected.
7. Obtain a reference run and write the comparison tests.

Step 7 is the one you will want to leave out, and the one without which the
other six are worthless.

### What nobody takes off your hands

The application can check whether it computes the same as yesterday. It
**cannot** check whether the model describes the biology correctly. That is your
job, and it is what you were trained for.

---

## 7. Traps that have already snapped shut

All of them in detail in `CLAUDE.md`; here are the ones most easily tripped
over.

| Trap | What to remember |
|---|---|
| `a` is not stored | What has to survive a restart belongs in `p` or `v` — or must be reconstructed when loading |
| A plugin without an entry in `build/specs.py` | The built application starts with an empty organism list, without an error |
| A test that imports an undeclared library | Runs on your machine and on no other |
| Pixel-exact layout promises | Hold only with your font |
| `findData` with an `IntEnum` | Returns −1; use `widgets.select_data()` |
| A modal dialog in a test fixture | The test run hangs, without a message |
| Writing NaN into the database | Turns "not measured" into a measured zero |

---

## 8. What is open

The open points are at the end of `CLAUDE.md`, sorted by phase. The ones I would
look at first for a version 4:

**In the domain:**

- **Pichia is not verified.** A reference run from the current MATLAB source is
  missing. While it is missing, every statement about the Pichia numbers is
  unsupported.
- **`variable_handlingTab` matches neither of the two models.** Seven *E. coli*
  time series are computed and never stored, ODE states among them. A resumed
  run restarts them.
- **Unchecked control modes**: `Mode_pH` = Manual, `Mode_temp` = Manual,
  `Mode_pO2` = Aeration / Gasmix / Feed. The reference run does not use them.

**Technically:**

- **Anti-windup is half finished.** The controller building block and the four
  database parameters (`f_awpO2`, `f_awtemp`, `f_awLW`, `f_awfeed`) are there and
  take effect; the controls in the controller dialog and in the settings are
  missing, and the Pichia model is not wired up yet.
- **`PhaseFeedEditor`** from the MATLAB version is not ported.
- **Two plot settings have no effect**: `axisyoffset` and
  `axisylabeloffsetabove`/`-below`.

---

## 9. If you get stuck

**The log is the first place to look** — in the application, and for a start
that does not even reach a window, under `/tmp/biofermentation-launch.log`
(macOS).

**`git diff` shows what you changed.** `git stash` puts it aside if you want to
get back to a working state. `git log --oneline` shows what happened before —
this project's commit messages deliberately explain the *why*, not the what.

**And if something breaks:** every save places a backup next to the database
(`SimulationAppDB.backup.db`). The shipped template can be rolled out again at
any time by renaming the working database — the application creates a fresh copy
on the next start.
