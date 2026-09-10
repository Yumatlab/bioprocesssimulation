"""The window the application opens with (plan section 4.2).

Follows the MATLAB StartingScreen: title, version, the three entry buttons,
the model configurator and an exit. The logo of the original is not
reproduced — it is the university's image asset, not part of this port.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

VERSION = "3.0"  # the Python port; the MATLAB application stopped at 2.2


class StartingScreen(QWidget):
    """Emits what the user chose; it owns no windows itself.

    Keeping the navigation out of here is what makes the window testable
    without opening anything: a test clicks a button and checks a signal.
    """

    new_project_requested = Signal()
    load_project_requested = Signal()
    model_configurator_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Biofermentation Simulation")
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 24)
        layout.setSpacing(12)

        title = QLabel("Biofermentation\nSimulation")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(28)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        version = QLabel(f"Version {VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        layout.addSpacing(24)

        # Quick Start and Start New Project did the same thing here, so there
        # is one button. The original's Quick Start created a project without
        # asking anything; that is a shortcut inside the creation window, not
        # a second entry point.
        self.new_project_button = self._button("Start New Project", self.new_project_requested)
        self.load_project_button = self._button("Load Project", self.load_project_requested)
        for button in (
            self.new_project_button,
            self.load_project_button,
        ):
            button.setMinimumHeight(34)
            layout.addWidget(button)

        layout.addSpacing(16)
        self.model_configurator_button = self._button(
            "Model Configurator", self.model_configurator_requested
        )
        layout.addWidget(self.model_configurator_button)

        layout.addSpacing(8)
        self.exit_button = self._button("Exit", self.exit_requested)
        layout.addWidget(self.exit_button)

    def _button(self, text: str, signal: Signal) -> QPushButton:
        button = QPushButton(text, self)
        button.clicked.connect(signal.emit)
        return button
