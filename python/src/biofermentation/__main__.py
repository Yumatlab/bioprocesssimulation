"""Entry point of the application.

    python -m biofermentation
    biofermentation                 (the console script)

The frozen build calls main() through build/entry.py, which does the same
thing but has to exist as a real file for PyInstaller to analyse.
"""

import sys

from .gui.app import main

if __name__ == "__main__":
    sys.exit(main())
