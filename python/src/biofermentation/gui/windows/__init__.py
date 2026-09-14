"""Application windows — phases 4 to 6."""

from .control_app import ControlWindow
from .create_project import CreateProjectWindow
from .figure_app import FigureWindow, open_figure
from .select_project import SelectProjectWindow
from .starting_screen import StartingScreen

__all__ = [
    "ControlWindow",
    "CreateProjectWindow",
    "FigureWindow",
    "SelectProjectWindow",
    "StartingScreen",
    "open_figure",
]
