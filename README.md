# Biofermentation Simulation

Simulation of bioreactor processes (batch, fed-batch, induction) for different
microorganisms. Every time step computes the controllers (pO2, pH, temperature,
liquid weight), the feed and the mass balances; a phase automaton advances the
process phases on configurable start and end conditions.

This repository holds **two versions of the same application**.

| Folder | Version | Status |
|---|---|---|
| [`matlab/`](matlab/) | MATLAB App Designer | version 2.2, the state of the master's thesis (tag `v2.2`) |
| [`python/`](python/) | Python, PySide6 | version 3.0, the reimplementation |

They stand beside each other, not on top of each other: the MATLAB version is
the template that was ported from, and stays readable and runnable as such.

**The Python version is the one being developed further.** It computes the same
simulation — the *Escherichia coli* model is verified against a reference run of
the MATLAB application, as documented in
[`python/docs/verification_escherichia_coli.md`](python/docs/verification_escherichia_coli.md).
What it can do in addition, and where it is built differently, is in
[`python/CLAUDE.md`](python/CLAUDE.md).

## Where to start

- **Using it**: ready-made installation files for Windows and macOS are attached
  to every release. Setup and known limitations are in
  [`python/docs/installation.md`](python/docs/installation.md).
- **Developing**: `python/README.md` describes the development environment and
  how a new organism model comes about.
- **Understanding how it is built**: `python/CLAUDE.md` is the long text for
  that — data model, controller logic, database rules and every decision that
  was not self-explanatory. It is written in German; everything in
  `python/docs/` is English.

## Licence

The Python version is under the MIT licence, see
[`python/LICENSE`](python/LICENSE). The MATLAB application is under
[CC BY 4.0](http://creativecommons.org/licenses/by/4.0/); it continues the work
of the previous developer **Lena Sophia Kaletsch** (version 1.3, 01.03.2024) and
rests on the BIOSIM program conceived by Prof. Dr.-Ing. R. Luttmann. Developed
for the Laboratory of Bioprocess Automation at the HAW Hamburg.
