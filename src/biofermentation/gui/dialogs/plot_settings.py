"""The two Figure App editors (points 16 and 17 of the review).

`VariableEditor` is FigureAppVariableEditor.mlapp: one row per variable with
whether it is drawn, whether its axis scales itself, its limits, the number
of decimals on the tick labels, the colour and the line style.

`PlotSettingsDialog` is FigureAppSettings.mlapp: the four tabs Title, Graph,
Axes and Flags, each with a "Reset to standard" button.

Both work on a copy of the template and write back only on Ok — the same
rule the phase editor keeps to, so a cancelled dialog leaves nothing behind.
"""

from copy import deepcopy
from dataclasses import fields

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets.indicators import select_data
from ..widgets.tex import tex_label

#: The standard each "Reset to standard" button restores. Taken from the
#: Default template as it ships in the database.
STANDARD = {
    "graphlinewidth": 1.5,
    "graphvlinewidth": 2.0,
    "graphfontsize": 12.0,
    "graphtitlefontsize": 18.0,
    "axisxlabel": "Process time",
    "axisxunit": "h",
    "axisxtick": 5.0,
    "axisytick": 5.0,
    "axisyoffset": 50.0,
    "axislabelfontsize": 12.0,
    "axislinewidth": 1.75,
    "flaglength": 0.005,
    "flagangle": 0.0,
    "flaglinewidth": 1.25,
    "flagfontsize": 16.0,
}


def _spin(value: float, decimals: int = 2, maximum: float = 1e6) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(-maximum, maximum)
    box.setValue(float(value))
    box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    box.setMaximumWidth(100)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    return box


def color_icon(rgb: tuple[int, int, int]) -> QIcon:
    """A filled swatch, so the dropdown shows the colour and not just its name."""
    pixmap = QPixmap(24, 12)
    pixmap.fill(QColor(*rgb))
    return QIcon(pixmap)


class VariableEditor(QDialog):
    """Colour, line style, decimals and limits of every variable."""

    HEADERS = (
        "Variable",
        "Draw",
        "Auto",
        "y min",
        "y max",
        "Decimals",
        "Color",
        "Linestyle",
    )

    def __init__(self, template, styles: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Variable Editor")
        self.resize(760, 640)
        self._draft = deepcopy(template)
        self._source = template
        self.styles = styles

        layout = QVBoxLayout(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setHorizontalSpacing(10)
        for column, text in enumerate(self.HEADERS):
            label = QLabel(text)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            self.grid.addWidget(label, 0, column, alignment=Qt.AlignmentFlag.AlignCenter)

        self.rows: dict[str, dict] = {}
        for row, variable in enumerate(
            sorted(self._draft.variables, key=lambda item: item.variableID), start=1
        ):
            self._add_row(row, variable)
        self.grid.setRowStretch(len(self._draft.variables) + 1, 1)
        area.setWidget(holder)
        layout.addWidget(area, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self, row: int, variable) -> None:
        label = QLabel(tex_label(variable.longtex or variable.name, variable.tex_unit) + ":")
        label.setTextFormat(Qt.TextFormat.RichText)
        self.grid.addWidget(label, row, 0)

        selected = QCheckBox()
        selected.setChecked(variable.selected)
        self.grid.addWidget(selected, row, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        auto = QCheckBox()
        auto.setChecked(variable.auto_limits)
        self.grid.addWidget(auto, row, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        lower = _spin(variable.ymin, 4, 1e9)
        upper = _spin(variable.ymax, 4, 1e9)
        auto.toggled.connect(
            lambda checked: (lower.setEnabled(not checked), upper.setEnabled(not checked))
        )
        lower.setEnabled(not variable.auto_limits)
        upper.setEnabled(not variable.auto_limits)
        self.grid.addWidget(lower, row, 3)
        self.grid.addWidget(upper, row, 4)

        decimals = QComboBox()
        decimals.setMinimumWidth(80)
        for entry in self.styles["decimals"]:
            decimals.addItem(entry["decimal_name"], entry["decimalID"])
        select_data(decimals, variable.decimalID)
        self.grid.addWidget(decimals, row, 5)

        color = QComboBox()
        for entry in self.styles["colors"]:
            color.addItem(color_icon(entry["rgb"]), entry["color_name"], entry["colorID"])
        select_data(color, variable.colorID)
        self.grid.addWidget(color, row, 6)

        linestyle = QComboBox()
        linestyle.setMinimumWidth(80)
        for entry in self.styles["linestyles"]:
            linestyle.addItem(entry["linestyle_symbol"], entry["linestyleID"])
        select_data(linestyle, variable.linestyleID)
        self.grid.addWidget(linestyle, row, 7)

        self.rows[variable.name] = {
            "selected": selected,
            "auto": auto,
            "ymin": lower,
            "ymax": upper,
            "decimals": decimals,
            "color": color,
            "linestyle": linestyle,
        }

    def accept(self) -> None:
        """Write the widgets into the real template, resolving the style ids."""
        by_color = {entry["colorID"]: entry for entry in self.styles["colors"]}
        by_style = {entry["linestyleID"]: entry for entry in self.styles["linestyles"]}
        by_decimal = {entry["decimalID"]: entry for entry in self.styles["decimals"]}

        for variable in self._source.variables:
            widgets = self.rows.get(variable.name)
            if widgets is None:
                continue
            variable.selected = widgets["selected"].isChecked()
            variable.limit_type = 1 if widgets["auto"].isChecked() else 0
            variable.ymin = widgets["ymin"].value()
            variable.ymax = widgets["ymax"].value()

            variable.colorID = widgets["color"].currentData()
            entry = by_color.get(variable.colorID)
            if entry:
                variable.color = entry["rgb"]

            variable.linestyleID = widgets["linestyle"].currentData()
            entry = by_style.get(variable.linestyleID)
            if entry:
                variable.linestyle = entry["linestyle_symbol"]

            variable.decimalID = widgets["decimals"].currentData()
            entry = by_decimal.get(variable.decimalID)
            if entry:
                variable.decimal = entry["decimal_symbol"]
        super().accept()


class PlotSettingsDialog(QDialog):
    """Title, graph, axes and flag settings of the template."""

    def __init__(self, template, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plot Settings")
        self.resize(460, 520)
        self._source = template

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.widgets: dict[str, QWidget] = {}
        self.tabs.addTab(self._title_tab(), "Title")
        self.tabs.addTab(
            self._numeric_tab(
                "General graph settings",
                [
                    ("graphlinewidth", "Line width"),
                    ("graphvlinewidth", "Vertical line width"),
                    ("graphfontsize", "Font size"),
                    ("graphtitlefontsize", "Title font size"),
                ],
            ),
            "Graph",
        )
        self.tabs.addTab(self._axes_tab(), "Axes")
        self.tabs.addTab(
            self._numeric_tab(
                "Flag settings",
                [
                    ("flaglength", "Flag line length"),
                    ("flagangle", "Flag line angle [°]"),
                    ("flaglinewidth", "Flag line width"),
                    ("flagfontsize", "Flag font size"),
                ],
            ),
            "Flags",
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------ build --

    def _title_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        name = QLineEdit(self._source.name or "")
        title = QLineEdit(self._source.plottitle or "")
        description = QLineEdit(self._source.description or "")
        show = QCheckBox("Show title above the plot")
        show.setChecked(self._source.show_title)
        self.widgets["name"] = name
        self.widgets["plottitle"] = title
        self.widgets["description"] = description
        self.widgets["titlebool"] = show
        form.addRow("Template name:", name)
        form.addRow("Description:", description)
        form.addRow("Plot title:", title)
        form.addRow("", show)
        return page

    def _numeric_tab(self, heading: str, entries: list[tuple[str, str]]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox(heading)
        form = QFormLayout(box)
        for key, label in entries:
            widget = _spin(getattr(self._source, key, 0.0), 3)
            self.widgets[key] = widget
            form.addRow(f"{label}:", widget)
        layout.addWidget(box)
        reset = QPushButton("Reset to standard")
        reset.clicked.connect(lambda: self._reset([key for key, _ in entries]))
        layout.addWidget(reset)
        layout.addStretch()
        return page

    def _axes_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Axes settings")
        form = QFormLayout(box)

        xlabel = QLineEdit(self._source.axisxlabel or "")
        xunit = QLineEdit(self._source.axisxunit or "")
        self.widgets["axisxlabel"] = xlabel
        self.widgets["axisxunit"] = xunit
        form.addRow("x axis label:", xlabel)
        form.addRow("x axis unit:", xunit)

        numeric = [
            ("axisxtick", "x axis tick"),
            ("axisytick", "y axis tick"),
            ("axisyoffset", "y axis offset [px]"),
            ("axislabelfontsize", "Axis label font size"),
            ("axislinewidth", "Axis line width"),
        ]
        for key, label in numeric:
            widget = _spin(getattr(self._source, key, 0.0), 3)
            self.widgets[key] = widget
            form.addRow(f"{label}:", widget)
        layout.addWidget(box)

        reset = QPushButton("Reset to standard")
        reset.clicked.connect(
            lambda: self._reset(["axisxlabel", "axisxunit", *[key for key, _ in numeric]])
        )
        layout.addWidget(reset)
        layout.addStretch()
        return page

    # ---------------------------------------------------------- actions --

    def _reset(self, keys: list[str]) -> None:
        for key in keys:
            if key not in STANDARD:
                continue
            widget = self.widgets.get(key)
            if isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(STANDARD[key]))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(STANDARD[key]))

    def accept(self) -> None:
        known = {field.name for field in fields(self._source)}
        for key, widget in self.widgets.items():
            if key not in known:
                continue
            if isinstance(widget, QDoubleSpinBox):
                setattr(self._source, key, widget.value())
            elif isinstance(widget, QLineEdit):
                setattr(self._source, key, widget.text())
            elif isinstance(widget, QCheckBox):
                setattr(self._source, key, float(widget.isChecked()))
        super().accept()


__all__ = ["STANDARD", "PlotSettingsDialog", "VariableEditor", "color_icon"]
