"""Shared fixtures.

Qt is driven headless: QT_QPA_PLATFORM has to be set before the first Qt
import, so it happens here rather than in a test module.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
