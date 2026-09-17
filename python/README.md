# Biofermentation Simulation

Simulation of bioreactor processes (batch, fed-batch, induction) for different
microorganisms. A Python port of the MATLAB App Designer application, version
2.x.

Every time step computes the controllers (pO2, pH, temperature, liquid weight),
the feed and the mass balances; a phase automaton advances the process phases on
configurable start and end conditions.

## Status

Version 3.0 — the port is feature-complete. Phases 0 to 8 are finished (data
layer, simulation core, phase automaton, interface, plot engine, distribution,
documentation). The *E. coli* model is verified against a MATLAB reference run
(`docs/verification_escherichia_coli.md`); the Pichia model deliberately is not
— the reason is in the same document.

The current progress and every open point are in `CLAUDE.md`.

## Documentation

| You want to… | Read |
|---|---|
| operate the application | [`docs/manual.md`](docs/manual.md) |
| install it | [`docs/installation.md`](docs/installation.md) |
| know how it is built | [`docs/architecture.md`](docs/architecture.md) |
| develop it further | [`docs/development.md`](docs/development.md) |
| know whether the numbers hold up | [`docs/verification_escherichia_coli.md`](docs/verification_escherichia_coli.md) |
| know *why* it is built this way | [`CLAUDE.md`](CLAUDE.md) |

## Development environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Structure

```
src/biofermentation/
  db/          database access (phase 1)
  core/        simulation state, preallocation, runner (phases 2/4)
  organisms/   organism models + plugin registry (phase 2)
  control/     phase automaton and controllers (phase 3)
  gui/         PySide6 interface (phases 4-6)
  resources/   SimulationAppDB_template.db
tests/         pytest, including the MATLAB reference runs
build/         PyInstaller spec files (phase 7)
docs/          documentation (phase 8)
```

## A new organism model

Two ways, neither of them touching existing code:

- **Parameters only:** create a `definition.yaml` in the organism folder; an
  import script fills the parameter tables of the database.
- **New kinetics:** write a subclass of `OrganismModel` and mark it with
  `@register`. The registry finds it automatically at start.

The details are in [`docs/development.md`](docs/development.md), the interface
in `src/biofermentation/organisms/base.py`.

## Licence

MIT — see [LICENSE](LICENSE).

The port descends from the MATLAB application version 2.2, which is under
[CC BY 4.0](http://creativecommons.org/licenses/by/4.0/). That application
continues the work of the **previous developer Lena Sophia Kaletsch**, who wrote
version 1.3 of the Biofermentation Simulation App (01.03.2024), and rests in turn
on the BIOSIM program conceived by Prof. Dr.-Ing. R. Luttmann. This attribution
is in `LICENSE` and in the application's Information tab, and has to accompany
every copy.

A **packaged** version additionally contains Qt through PySide6 under the
LGPLv3. Anyone distributing it takes on those obligations; see
`docs/installation.md`.
