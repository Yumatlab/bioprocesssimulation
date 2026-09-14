"""The script PyInstaller analyses.

A frozen build needs a real file to start from — `python -m biofermentation`
is not something the analysis can follow. This module does nothing beyond
what __main__.py does.
"""

import multiprocessing
import sys

from biofermentation.gui.app import main

if __name__ == "__main__":
    # Without this a frozen build on Windows re-runs the whole application in
    # every worker process it spawns. Harmless here today, and the line costs
    # nothing if scipy ever reaches for a process pool.
    multiprocessing.freeze_support()
    sys.exit(main())
