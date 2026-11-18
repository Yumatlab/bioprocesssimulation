"""Tabs of the control window that can be taken out into their own window.

Built on project 716 with the real control window: the page that moves is the
real page, and the questions are whether it is still the same object, whether
it is still refreshed, and whether a click in it still writes the guarded way.
"""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from biofermentation.control import PhaseAutomaton
from biofermentation.core.runner import load_project_state
from biofermentation.core.simulation_runner import SimulationRunner
from biofermentation.db import load_phases
from biofermentation.gui.widgets.detachable_tabs import DetachableTabs
from biofermentation.gui.windows import ControlWindow, control_app
from biofermentation.organisms import discover_organisms

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DB = REPO_ROOT / "src" / "biofermentation" / "resources" / "SimulationAppDB_template.db"
PROJECT = 716


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    target = tmp_path / "SimulationAppDB.db"
    shutil.copy(TEMPLATE_DB, target)
    return target


def _build(db_copy: Path) -> ControlWindow:
    discover_organisms()
    setup = load_phases(db_copy, PROJECT)
    state, organism = load_project_state(db_copy, PROJECT)
    runner = SimulationRunner(organism, state, phases=PhaseAutomaton.from_setup(setup))
    return ControlWindow(setup, runner, db_copy)


@pytest.fixture
def window(qapp, db_copy):
    window = _build(db_copy)
    window.show()
    QApplication.processEvents()
    yield window
    window.tabs.attach_all()
    window.close()


def _titles(tabs: DetachableTabs) -> list[str]:
    return [tabs.tabText(index) for index in range(tabs.count())]


def test_detaching_moves_the_page_into_its_own_window(window):
    tabs = window.tabs
    assert tabs.detach("PCS")
    assert tabs.is_detached("PCS")
    own = tabs.detached_window("PCS")
    # The same object, moved: its state lives in its widgets.
    assert window.pcs_view.window() is own
    assert own.isVisible() and window.pcs_view.isVisible()
    assert tabs.indexOf(window.pcs_view) == -1
    assert own.windowTitle() == f"PCS — {window.setup.info.name}"
    # Asked a second time, there is nothing left to detach.
    assert not tabs.detach("PCS")


def test_the_window_asks_for_no_more_room_than_its_page(window):
    window.tabs.detach("PCS")
    own = window.tabs.detached_window("PCS")
    assert own.minimumSizeHint() == window.pcs_view.minimumSizeHint()


def test_the_tab_bar_says_that_a_tab_can_be_detached(window):
    """Neither gesture is visible, so the tooltip is the only announcement."""
    assert "own window" in window.tabs.tabBar().toolTip()


def test_the_close_shortcut_brings_the_page_back(window):
    from PySide6.QtGui import QKeySequence, QShortcut

    tabs = window.tabs
    tabs.detach("Log")
    own = tabs.detached_window("Log")
    shortcuts = own.findChildren(QShortcut)
    assert [shortcut.key() for shortcut in shortcuts] == [
        QKeySequence(QKeySequence.StandardKey.Close)
    ]
    shortcuts[0].activated.emit()
    assert not tabs.is_detached("Log")


def test_the_tab_shows_a_button_while_its_page_is_out(window):
    tabs = window.tabs
    before = _titles(tabs)
    index = tabs.index_of("PCS")
    tabs.detach("PCS")
    # The tab stays where it was, under its name.
    assert _titles(tabs) == before
    placeholder = tabs.widget(index)
    assert placeholder is not window.pcs_view
    buttons = placeholder.findChildren(QPushButton)
    assert [button.text() for button in buttons] == ["Bring back"]


def test_the_button_brings_the_page_back_to_the_same_index(window):
    tabs = window.tabs
    before = _titles(tabs)
    index = tabs.index_of("PCS")
    tabs.setCurrentIndex(index)
    tabs.detach("PCS")
    button = tabs.widget(index).findChild(QPushButton)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not tabs.is_detached("PCS")
    assert tabs.widget(index) is window.pcs_view
    assert _titles(tabs) == before
    assert tabs.currentWidget() is window.pcs_view
    assert window.pcs_view.window() is window


def test_closing_the_window_brings_the_page_back(window):
    tabs = window.tabs
    index = tabs.index_of("Variable Pool")
    tabs.detach("Variable Pool")
    tabs.detached_window("Variable Pool").close()
    assert not tabs.is_detached("Variable Pool")
    assert tabs.widget(index) is window.variable_pool
    assert tabs.tabText(index) == "Variable Pool"


def test_a_double_click_on_the_tab_detaches_it_and_brings_it_back(window):
    tabs = window.tabs
    index = tabs.index_of("Log")
    centre = tabs.tabBar().tabRect(index).center()
    QTest.mouseDClick(tabs.tabBar(), Qt.MouseButton.LeftButton, pos=centre)
    assert tabs.is_detached("Log")
    QTest.mouseDClick(tabs.tabBar(), Qt.MouseButton.LeftButton, pos=centre)
    assert not tabs.is_detached("Log")


def test_a_detached_tab_is_refreshed_while_another_tab_is_in_front(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window.pcs_view, "refresh", lambda state, *rest: calls.append("pcs"))
    monkeypatch.setattr(window.controller_view, "refresh", lambda state: calls.append("loops"))
    window.tabs.detach("PCS")
    window.tabs.setCurrentWidget(window.variable_pool)
    calls.clear()
    window.refresh()
    # The detached sheet is seen and redrawn; the Controllers tab is neither.
    assert calls == ["pcs"]


def test_a_tab_behind_and_not_detached_is_still_not_refreshed(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window.pcs_view, "refresh", lambda state, *rest: calls.append("pcs"))
    window.tabs.setCurrentWidget(window.variable_pool)
    calls.clear()
    window.refresh()
    assert calls == []


def test_a_hidden_tab_cannot_be_detached(qapp, db_copy, monkeypatch):
    from biofermentation.gui.settings import Settings

    settings = Settings(hidden_tabs={"PCS"})
    monkeypatch.setattr(control_app, "load_settings", lambda: (settings, ""))
    window = _build(db_copy)
    assert window.tabs.index_of("PCS") == -1
    assert not window.tabs.detach("PCS")
    assert not window.tabs.is_detached("PCS")
    # Built all the same, and still without a window of its own.
    assert window.pcs_view.window() is not None
    assert window.tabs.detached_window("PCS") is None
    window.close()


def test_closing_the_main_window_closes_the_detached_ones(window):
    tabs = window.tabs
    index = tabs.index_of("PCS")
    tabs.detach("PCS")
    tabs.detach("Log")
    own = [tabs.detached_window("PCS"), tabs.detached_window("Log")]
    window.close()
    assert not any(detached.isVisible() for detached in own)
    # Back first, then closed: the pages are where they were.
    assert tabs.widget(index) is window.pcs_view
    assert not tabs.is_detached("PCS") and not tabs.is_detached("Log")


def test_a_valve_click_in_a_detached_pcs_tab_still_writes_through_the_guard(window, monkeypatch):
    state = window.runner.state
    state.p["Mode_pH"] = 0.0  # manual: the acid pump is the operator's
    state.p["f_acid"] = 0.0
    window.load_panels()
    window.tabs.detach("PCS")
    QApplication.processEvents()

    seen = []
    original = window.runner.editing

    def watched():
        seen.append("guarded")
        return original()

    monkeypatch.setattr(window.runner, "editing", watched)
    pump = window.pcs_view.element("acid_pump")
    assert pump.isEnabled()
    QTest.mouseClick(
        pump, Qt.MouseButton.LeftButton, pos=QPoint(pump.width() // 2, pump.height() // 2)
    )
    assert seen == ["guarded"]
    assert state.p["f_acid"] == 1.0
    # The click did not bring the page back: it is still in its own window.
    assert window.pcs_view.window() is window.tabs.detached_window("PCS")
