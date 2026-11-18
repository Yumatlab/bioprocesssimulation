"""The test platform has to draw with real fonts, or layout tests mean nothing.

Qt's offscreen platform falls back to boxes as wide as the font is high when
it finds no font — seen on the Windows runner on 18.11.2026, see CLAUDE.md.
Every layout test then measures boxes. This test says so in one line instead
of letting the flow-sheet tests fail with numbers nobody can explain.
"""

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_test_platform_draws_with_real_fonts(qapp):
    from PySide6.QtWidgets import QWidget

    metrics = QWidget().fontMetrics()
    narrow, wide = metrics.horizontalAdvance("iiii"), metrics.horizontalAdvance("WWWW")
    assert narrow < wide, (
        f"every glyph is {narrow // 4} px wide: Qt found no font and draws boxes. "
        "Point QT_QPA_FONTDIR at a font folder (tests/conftest.py does it on Windows)."
    )
