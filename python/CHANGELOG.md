# Changelog

What each version brought. Differences from the MATLAB application, and why,
are in [`docs/changes_from_matlab.md`](docs/changes_from_matlab.md); known
errors and their state in [`FEHLER.md`](FEHLER.md).

Version numbers: the third digit is a release of the same verified
translation, the second a step that changes what a run computes.

---

## 3.1.0 — in progress

Fixing errors inherited from MATLAB (`FEHLER.md`, section 2). Each fix is
recorded in `docs/changes_from_matlab.md` with its measured effect. The
*E. coli* comparison with MATLAB may differ where an error is fixed; the
verified state before that is version 3.0.1.

Planned next: the controller tuning tool (`Projektplan_Regleroptimierung.md`).

---

## 3.0.1 — 2026-11-18

**Closes the verified translation.** The last version in which the *E. coli*
model reproduces MATLAB's arithmetic, its errors included; the verification
record of this version is measured in `docs/verification_escherichia_coli.md`
("Record for version 3.0.1").

### Added

- **PCS tab**: the plant as an operable flow sheet — valves and pumps switch
  the same flags as the control panels, lines show what flows and how much,
  vessels their level, the reactor with double jacket, stirrer, sparger,
  bubbles, broth colour and its pH, pO₂ and temperature beside it.
- **Detachable tabs**: any tab of the control window can be taken out into a
  window of its own and brought back.
- **Process templates**: save the phases of a process under a name for the
  model, load them into another project, appending or replacing the phases
  that have not started. Switchable in Settings for courses.
- **Data limit**: a run pauses at 90 % of 5 million stored values and stops at
  99 %, measured from what reopening a project costs.
- **Antifoam reservoir**: the antifoam bottle has a level (display only).
- **Plot**: "Extend t max with the run".
- **Documentation**: `docs/changes_from_matlab.md`, `FEHLER.md`, this file;
  `tools/verification_record.py`.

### Changed

- Liquid-weight controller: no harvest below the setpoint (requested
  deviation from MATLAB).
- Plot: y-axes with a negative part keep zero on a tick and their ticks in
  line with the other axes; tick labels with the decimals the value needs;
  the time axis ends at *t* max unless it may grow.
- Cooling and heating shown in g/h on the flow sheet.
- `tools/make_launcher.py` writes to `/Applications` by default, where a
  Finder shortcut points.

### Fixed

- *Pichia*: the inverted feed gains of reservoir 2 are corrected in projects
  and older databases too, at start-up, with a backup copy (F-01).
- Deleting an upcoming phase restarted the running one (F-30).
- Flow readings that had no unit (harvest flow).
- PySide6 limited to below 6.12: version 6.12.0 crashes the interpreter
  when windows are destroyed (FEHLER.md, F-32). Found by the CI after all
  tests had passed.

---

## 3.0.0 — 2026-09-17

The Python port of the MATLAB application 2.2: line-by-line translation,
verified against MATLAB for *E. coli*, with the corrections listed under 3.0.0
in `docs/changes_from_matlab.md`. Installers for Windows and macOS.
