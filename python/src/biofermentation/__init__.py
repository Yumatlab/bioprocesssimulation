"""Biofermentation Simulation — bioreactor process simulation.

Python port of the MATLAB App Designer application (Version 2.x).
See CLAUDE.md for the architecture and the phase plan.
"""

#: The one place the version lives. pyproject.toml reads it from here
#: (hatch, dynamic version), the starting screen shows it and
#: tools/make_launcher.py stamps it into the .app bundle — they drifted to
#: "3.0" in the window and "0.1.0" in the package once already, which is two
#: answers to a question that has one.
__version__ = "3.0.0"
