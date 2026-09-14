"""Shared fixtures.

Qt is driven headless: QT_QPA_PLATFORM has to be set before the first Qt
import, so it happens here rather than in a test module.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _closing_dialog_answers_discard(monkeypatch):
    """Closing a project asks a question; a test has nobody to answer it.

    ClosingDialog is modal, so a window closed in a fixture teardown would
    hang the run forever. Here it answers "discard" without being shown —
    confirm_leave() still runs, so the path under test is the real one. A test
    about the dialog itself patches exec() again with what it wants to see.
    """
    pytest.importorskip("PySide6")
    from biofermentation.gui.dialogs.closing import Choice, ClosingDialog

    def answer(self) -> int:
        self.choice = Choice.DISCARD
        return int(ClosingDialog.DialogCode.Accepted)

    monkeypatch.setattr(ClosingDialog, "exec", answer)
