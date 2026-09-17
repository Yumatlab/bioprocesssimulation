# Architecture

How the application is built — for anyone who reads or changes the source.

This document is a **map**, not a complete description. The reasons behind every
non-obvious decision are in [`../CLAUDE.md`](../CLAUDE.md), at length. Repeating
them here would mean maintaining two texts that drift apart by the third change.
What is here is the map; `CLAUDE.md` is the travel diary.

---

## 1. The five packages

```
src/biofermentation/
├── db/           3,700 lines   database access
├── core/           650 lines   state, preallocation, runner
├── organisms/    3,150 lines   base class, registry, the models
├── control/        540 lines   phase automaton
└── gui/          9,550 lines   PySide6 interface
```

The dependencies run in **one** direction: `gui` knows all of them, `control`
knows `core`, `organisms` knows `core`, `core` knows nothing of the others, and
`db` knows only itself and the data classes.

**Two rules protect that direction:**

`core/runner.py` runs without an interface and without PySide6. Only
`core/simulation_runner.py` imports Qt, and `core/__init__.py` does not pull it
in. A reference run or a test must never need a GUI dependency.

Windows do not open windows. Each one reports through a signal what the user
asked for; `gui/app.py` decides what opens. That is the only thing that makes a
window testable on its own.

---

## 2. The data model: `p`, `v`, `a`

Taken over from MATLAB, names included — and that is deliberate, because any
comparison against the reference run would otherwise become unreadable.

| | What is in it | Stored? |
|---|---|---|
| **`p`** | parameters: setpoints, constants, modes, flags | yes, `project_parameterTab` |
| **`v`** | time series: one numpy array per variable across all steps | yes, `dataTab`/`timeTab` |
| **`a`** | auxiliary quantities and controller states | **no** |

All three are a `Namespace` — a `MutableMapping` with attribute access, so that
`state.p.pHw` and `state.p["pHw"]` are the same thing. That allows formulas that
look like the MATLAB template and, at the same time, keys built from names at
runtime (`p[f"FR{n}max"]`).

> **`a` is not stored** — and that has been the source of several defects.
> Anything put into `a` that has to survive a restart must be reconstructed from
> `v` or `p` when loading. The section "Ein wieder geöffnetes Projekt ist schon
> beimpft" in `CLAUDE.md` tells how that went wrong.

**The domain notation is kept literally:** `cXL`, `cS1L`, `qXpX`, `NSt`, `kLa`,
`thetaL`. The `pep8-naming` rules are deliberately switched off for it in
`pyproject.toml`.

---

## 3. One time step

`OrganismModel.calculate_step(state)` computes **one** step. The index
`prev = state.idx` is the last one computed, `i = prev + 1` the new one.

```
ensure_capacity(i)      double the arrays when needed
_feeding                feed: exponential, pulse, pO2-controlled, PID
_po2_control            stirrer / aeration / gas mixing
_aeration               gas composition at the inlet
_liquid_weight          liquid weight and harvest
_antifoam               antifoam
_ph_control             pH cascade
_temperature_control    jacket
_volume                 dilution rates DR1, DT1, DT2
ode_luttmann            18 balances, solved with LSODA
_growth, _ph_iteration  kinetics and pH equilibrium
carry_forward           whatever was not recomputed is carried forward
```

Three peculiarities worth knowing:

**Preallocation.** Time series do not grow element by element. `ensure_capacity`
doubles the arrays; `np.append` per step would be O(n²) and cost 7.3 s over
20,000 steps instead of 0.25 µs per step.

**NaN means "not computed".** A preallocation slot is NaN until somebody writes
into it. `carry_forward` fills, at the end of every step, the series the model
did not touch. NaN slots are filtered out before every database write — **NaN is
never stored**, because MATLAB wrote 0 there, which turned "not measured" into a
measured zero.

**MATLAB peculiarities are translated literally.** Where the original writes at
`idx` and reads `idx-1` in the next expression, the code says `# MATLAB lag`.
There are exactly **four** deliberate exceptions, all in the aeration, all
outside the verified window, each one measured individually. They are in
`CLAUDE.md` with a reason and a measured value.

---

## 4. Organisms as plugins

An organism model is a folder under `organisms/` with a class that inherits from
`OrganismModel` and carries `@register`. `discover_organisms()` finds them
through `pkgutil.iter_modules` — **nobody imports them by name**.

The base class requires four initialisation steps and one computation step:

```python
init_controller_states(state)   # PID states and flags
init_physical_constants(state)  # vessel: heat, Henry, pH
init_kinetics(state)            # growth, uptake, yields
init_variables(state)           # initial values at t = 0, for a fresh run only
calculate_step(state)           # one time step
```

What both shipped organisms have in common is in `organisms/shared.py`. What
sets them apart is in their own file — and **the two are deliberately not
unified**: Pichia's MATLAB source is a later revision with different controller
tappings. Each file is the reference for its own organism.

> **Careful when distributing:** because the registry searches through
> `pkgutil`, PyInstaller's import analysis does not see the plugins. Each one
> needs an entry in `build/specs.py`. If one is missing, the built application
> starts **without an error message** and with an empty organism list.
> `tests/test_packaging.py` compares the list against `discover_organisms()`.

---

## 5. The phase automaton

`control/phases.py`. Three entry points, and the runner calls them in this
order:

```python
started = automaton.check_start(state)   # before the block: start a phase?
...                                       # the steps of the block
ended = automaton.check_end(state)        # after the block: end the phase?
```

`check_start` applies the phase's parameters **and returns the index
afterwards**; only then does the runner emit its signal. So anyone reacting to
"a phase changed something" can rely on the values already being in `p`.

`adopt_active_phase()` is the loading path: the automaton's state is in
`processTab`, and without this call a loaded project restarts its running phase.

`drain_log()` hands back the messages the automaton wrote — it cannot emit a Qt
signal, because `control/` stays free of Qt.

`PHASE_PARAMETERS` says which parameters a phase type offers. The table sits
next to the handlers that read it, on purpose.

---

## 6. The database

SQLite, `sqlite3` from the standard library, no ORM.

**Two accesses per session.** Read once when opening (`load_phases`,
`load_project_state`), write once at the end (`save_project`). No database
access during the simulation; every editor works on memory.

**The rules that are not negotiable:**

- Always `with get_connection(path) as conn:` — never `sqlite3.connect(` without
  a context manager, never a global connection.
- One block, one connection, **one** transaction. `get_connection` opens `BEGIN`
  and closes with `COMMIT` or `ROLLBACK`.
- **SQLite does the cascading.** No rebuilding it by hand, and under no
  circumstances `PRAGMA foreign_keys = OFF`.
- Backups through the **sqlite3 backup API**, never `shutil.copy` — in WAL mode
  a committed transaction lives in the WAL first, and a file copy without the
  WAL loses it.

These rules are not a matter of style. The MATLAB version's production database
died of their violation: of 733 projects, 14 are left; of 11.3 million data
rows, not one. The forensics are in `CLAUDE.md` under "Anforderung an Phase 5".

**The rebuild path** is `resources/defaults/` — 23 CSVs plus `load_defaults()` /
`export_defaults()`. Project data is not included.

---

## 7. The interface

`gui/` is the largest package and is split into three levels:

| | |
|---|---|
| `windows/` | the windows: starting screen, project selection, ControlApp, FigureApp, DataTable |
| `widgets/` | the building blocks: control panels, phase grid, plot, variable pool, log |
| `dialogs/` | phase, parameter, plot, export and library dialogs |

**Every write goes through `runner.editing()`.** A setpoint changed while a
timer tick is in the middle of a step is exactly the case the guard flag exists
for.

**Three text files instead of code** — the pattern is the same everywhere: a
default shipped under `resources/`, a file of the same name next to the database
beats it, and a broken file never takes anything away but yields the default
plus a reason for the log.

| File | Controls |
|---|---|
| `styles/default.qss` | colours, spacing, fonts |
| `layouts/control_options.yaml` | arrangement of the panels, kind of mode selector |
| `settings.yaml` | visible tabs, student view |

Qt has traps, and this project has stepped into most of them once. They are
collected in `CLAUDE.md` — styled combo boxes, `clicked(bool)`, `isVisible()`,
cosmetic pens, `findData` with an `IntEnum`. Anyone working on the interface
reads the "UX-Durchgang" section once, in full.

---

## 8. Tests

```bash
pytest                     # everything, around 70 seconds
pytest tests/test_organisms.py -q    # the models only
ruff check .               # lint
```

Currently **605 tests**, one skipped and one expected failure.

**Three rules:**

Test against a **copy of the real database**, not against mocks. The template is
in `resources/`; every fixture copies it into a temporary directory.

**No ODE code without a reference run in hand.** The comparison tests skip
themselves while the CSV is missing — a test that is green without a reference
proves nothing.

**A modal dialog in a fixture is a hanging test run.** `conftest.py` answers the
closing dialog centrally with "discard". That happened twice before it was put
there.

The `xfail(strict=True)` in `test_organisms.py` is not a forgotten defect but a
recorded inconsistency of the database: `variable_handlingTab` matches neither
of the two models. While that is so, the test **must** fail; if somebody repairs
the table it stops failing and reports itself as `XPASS`.

---

## 9. Building and distributing

| What | How |
|---|---|
| Developing | `pip install -e ".[dev]"`, then `python -m biofermentation.gui.app` |
| A shortcut onto the source tree | `python tools/make_launcher.py` |
| A single file for distribution | `pyinstaller --noconfirm build/macos.spec` or `build/windows.spec` |
| Both at once | GitHub Actions, on a `v*` tag or on demand |

**PyInstaller has no cross-compiling.** A Windows `.exe` is only produced on
Windows; that is what the CI matrix is for.

The details and the known limitations are in
[`installation.md`](installation.md).

---

## 10. Where to find what

| Question | File |
|---|---|
| Why is it built this way? | `../CLAUDE.md` |
| Do the numbers hold up? | `verification_escherichia_coli.md` |
| How do I operate it? | `manual.md` |
| How do I develop it further? | `development.md` |
| How do I install it? | `installation.md` |
| Where do the default values come from? | `../src/biofermentation/resources/defaults/README.md` |
| Where do the reference runs come from? | `../tests/reference_data/README.md` |
