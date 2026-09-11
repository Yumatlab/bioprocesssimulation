"""Reusable pieces of the control surface — phase 5."""

from .control_panel import ControlPanel, FieldSpec, PanelSpec, SwitchSpec
from .indicators import (
    RotarySelector,
    SegmentedControl,
    SlideSwitch,
    StatusLamp,
    ToggleSwitch,
    ValueRow,
    select_data,
)
from .panel_specs import CONTROL_PANELS
from .phase_panel import ArrowButton, PhaseGrid, PhasePanel, condition_text
from .tex import tex_label, tex_to_html

__all__ = [
    "CONTROL_PANELS",
    "ArrowButton",
    "ControlPanel",
    "FieldSpec",
    "PanelSpec",
    "PhaseGrid",
    "PhasePanel",
    "RotarySelector",
    "SegmentedControl",
    "SlideSwitch",
    "StatusLamp",
    "SwitchSpec",
    "ToggleSwitch",
    "ValueRow",
    "condition_text",
    "select_data",
    "tex_label",
    "tex_to_html",
]
