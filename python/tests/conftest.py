"""Shared fixtures.

Qt is driven headless: QT_QPA_PLATFORM has to be set before the first Qt
import, so it happens here rather than in a test module.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _settings_are_the_defaults(tmp_path_factory, monkeypatch):
    """No test reads the settings file of the machine it runs on.

    `ControlWindow` calls `load_settings()` without a path, which resolves to
    the file next to the user's database. A developer who unticks a box in
    the Settings dialog then changes what the test suite does: the run that
    found this had `couple_refresh_to_dt: false` on one machine, and a test
    about the timer measured 1000 ms where it expected 5000.

    Pointed at an empty directory the loader returns the defaults, which is
    what a test should see unless it says otherwise. A test about the
    settings themselves passes an explicit path.
    """
    pytest.importorskip("PySide6")
    from biofermentation.gui import settings as settings_module

    empty = tmp_path_factory.mktemp("settings") / "settings.yaml"
    monkeypatch.setattr(settings_module, "settings_path", lambda: empty)


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
