"""The Figure App (plan section 6).

Follows the window on page 55 of the thesis: axis limits on the left, the
plot in the middle, the variable selection on the right.

The window owns no data. It reads the simulation state through the runner
and the styling through a plot template, and it never computes a value of
its own — the same rule the control window keeps to.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...db.plots import (
    PlotTemplate,
    list_plot_templates,
    load_plot_styles,
    load_plot_template,
    save_plot_template,
)
from ..widgets.plot_view import MultiAxisPlot
from ..widgets.tex import tex_to_html


class FigureWindow(QMainWindow):
    """Live plot of a running simulation."""

    closed = Signal()

    def __init__(
        self,
        template: PlotTemplate,
        runner,
        db_path: Path | str,
        parent: QWidget | None = None,
        control=None,
        phases=None,
    ):
        super().__init__(parent)
        self.template = template
        self.runner = runner
        self.db_path = Path(db_path)
        self.control = control
        #: The list the control window owns, not a copy — a phase that starts
        #: while this window is open has to show up on its own.
        self.phases = phases if phases is not None else []
        self.auto_update = True

        self.setWindowTitle(f"Figure - {template.name}")
        self.resize(1500, 815)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        self.limits_panel = self._build_limits()
        self.configuration_panel = self._build_configuration()
        layout.addWidget(self.limits_panel, 0)
        layout.addWidget(self._build_plot(), 1)
        layout.addWidget(self.configuration_panel, 0)

        self._build_menus()

        if runner is not None:
            runner.block_completed.connect(self._on_block)

        self.apply_template()

    # ------------------------------------------------------------ menus --

    def _build_menus(self) -> None:
        """Export, Template and Options, as the original's menu bar has them."""
        bar = self.menuBar()
        bar.setNativeMenuBar(False)

        def add(menu, text, slot, shortcut: str = "") -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            menu.addAction(action)
            return action

        export = bar.addMenu("Export")
        add(export, "Save figure as image…", self.export_image, "Ctrl+Shift+S")
        add(export, "Open data table", self.open_data_table, "Ctrl+T")

        template_menu = bar.addMenu("Template")
        add(template_menu, "Save template", self.save_template, "Ctrl+S")
        self.load_menu = template_menu.addMenu("Load template")
        self.load_menu.aboutToShow.connect(self._fill_load_menu)

        options = bar.addMenu("Options")
        add(options, "Variable editor…", self.open_variable_editor, "Ctrl+Shift+V")
        add(options, "Plot settings…", self.open_settings, "Ctrl+,")
        options.addSeparator()

        self.limits_action = QAction("Show variable limits", self, checkable=True)
        self.limits_action.setChecked(True)
        self.limits_action.toggled.connect(self.limits_panel.setVisible)
        options.addAction(self.limits_action)

        self.configuration_action = QAction("Show plot configuration", self, checkable=True)
        self.configuration_action.setChecked(True)
        self.configuration_action.toggled.connect(self.configuration_panel.setVisible)
        options.addAction(self.configuration_action)

        self.fullscreen_action = QAction("Plot only", self, checkable=True)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.toggled.connect(self.set_plot_only)
        options.addAction(self.fullscreen_action)

        options.addSeparator()
        self.markers_action = QAction("Show phase markers", self, checkable=True)
        self.markers_action.setChecked(True)
        self.markers_action.setShortcut(QKeySequence("Ctrl+M"))
        self.markers_action.toggled.connect(self.plot.set_markers_visible)
        options.addAction(self.markers_action)

    # ------------------------------------------------------------ build --

    def _build_limits(self) -> QWidget:
        box = QGroupBox("Variable Limits")
        box.setFixedWidth(250)
        layout = QVBoxLayout(box)

        time_box = QGroupBox("Time Axis")
        time_grid = QGridLayout(time_box)
        time_grid.addWidget(QLabel("Min"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        time_grid.addWidget(QLabel("Max"), 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        time_grid.addWidget(QLabel("t [h]:"), 1, 0)
        self.tstart_box = self._spin(self.template.tstart)
        self.tend_box = self._spin(self.template.tend)
        self.tstart_box.valueChanged.connect(self._time_range_changed)
        self.tend_box.valueChanged.connect(self._time_range_changed)
        time_grid.addWidget(self.tstart_box, 1, 1)
        time_grid.addWidget(self.tend_box, 1, 2)
        layout.addWidget(time_box)

        self.axis_box = QGroupBox("Variable Axis")
        self.axis_grid = QGridLayout(self.axis_box)
        layout.addWidget(self.axis_box)
        layout.addStretch()
        return box

    def _build_plot(self) -> QWidget:
        box = QGroupBox("Plot")
        layout = QVBoxLayout(box)
        self.plot = MultiAxisPlot()
        layout.addWidget(self.plot)
        return box

    def _build_configuration(self) -> QWidget:
        box = QGroupBox("Plot Configuration")
        box.setFixedWidth(260)
        layout = QVBoxLayout(box)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self.checkbox_layout = QVBoxLayout(inner)
        self.checkbox_layout.setSpacing(2)
        area.setWidget(inner)
        layout.addWidget(area)

        self.checkboxes: dict[str, QCheckBox] = {}
        self._rebuild_checkboxes()

        self.auto_button = QPushButton("Auto Update")
        self.auto_button.setCheckable(True)
        self.auto_button.setChecked(True)
        self.auto_button.toggled.connect(self._auto_update_changed)
        layout.addWidget(self.auto_button)

        self.save_button = QPushButton("Save Template")
        self.save_button.clicked.connect(self.save_template)
        layout.addWidget(self.save_button)
        return box

    def _rebuild_checkboxes(self) -> None:
        """One row per variable. Rebuilt when the template changes underneath."""
        while self.checkbox_layout.count():
            item = self.checkbox_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.checkboxes.clear()

        for variable in sorted(self.template.variables, key=lambda item: item.variableID):
            checkbox = QCheckBox()
            checkbox.setText("")
            label = QLabel(
                f"{tex_to_html(variable.shorttex or variable.name)} "
                f"[{tex_to_html(variable.tex_unit or '-')}]"
            )
            label.setTextFormat(Qt.TextFormat.RichText)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(checkbox)
            row_layout.addWidget(label)
            row_layout.addStretch()
            checkbox.setChecked(variable.selected)
            checkbox.toggled.connect(
                lambda checked, name=variable.name: self._selection_changed(name, checked)
            )
            self.checkboxes[variable.name] = checkbox
            self.checkbox_layout.addWidget(row)
        self.checkbox_layout.addStretch()

    def _spin(self, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setDecimals(3)
        box.setRange(-1e9, 1e9)
        box.setValue(float(value))
        box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        return box

    # ------------------------------------------------------------ state --

    def apply_template(self) -> None:
        """Rebuild plot and limit rows from the template."""
        self.plot.set_template(self.template)
        for box, value in (
            (self.tstart_box, self.template.tstart),
            (self.tend_box, self.template.tend),
        ):
            box.blockSignals(True)
            box.setValue(float(value))
            box.blockSignals(False)
        self._rebuild_axis_rows()
        self.refresh()

    def _rebuild_axis_rows(self) -> None:
        while self.axis_grid.count():
            item = self.axis_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        for column, text in enumerate(("Variable", "Min", "Max", "Auto"), start=0):
            self.axis_grid.addWidget(
                QLabel(text), 0, column, alignment=Qt.AlignmentFlag.AlignCenter
            )

        self.limit_rows: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox, QCheckBox]] = {}
        for row, variable in enumerate(self.template.selected(), start=1):
            label = QLabel(f"{row}: {tex_to_html(variable.label())}")
            label.setTextFormat(Qt.TextFormat.RichText)
            self.axis_grid.addWidget(label, row, 0)

            lower = self._spin(variable.ymin)
            upper = self._spin(variable.ymax)
            auto = QCheckBox()
            auto.setChecked(variable.auto_limits)
            auto.setToolTip("Auto: y-axis limits grow when data leaves the plot area.")

            for box in (lower, upper):
                box.setEnabled(not variable.auto_limits)
                box.valueChanged.connect(
                    lambda _=0.0, name=variable.name: self._limits_changed(name)
                )
            auto.toggled.connect(
                lambda checked, name=variable.name: self._auto_changed(name, checked)
            )

            self.axis_grid.addWidget(lower, row, 1)
            self.axis_grid.addWidget(upper, row, 2)
            self.axis_grid.addWidget(auto, row, 3, alignment=Qt.AlignmentFlag.AlignCenter)
            self.limit_rows[variable.name] = (lower, upper, auto)

    def refresh(self) -> None:
        if self.runner is None:
            return
        state = self.runner.state
        trimmed = state.trimmed()
        time = trimmed.get("t")
        if time is None:
            return
        self.plot.update_data(time, trimmed)
        self.plot.set_phase_markers(self.phases)
        self._sync_limit_rows()

    def _sync_limit_rows(self) -> None:
        """Automatic limits change on their own; the fields have to follow."""
        for variable in self.template.selected():
            row = getattr(self, "limit_rows", {}).get(variable.name)
            if row is None:
                continue
            lower, upper, _ = row
            for box, value in ((lower, variable.ymin), (upper, variable.ymax)):
                if abs(box.value() - value) > 1e-12:
                    box.blockSignals(True)
                    box.setValue(value)
                    box.blockSignals(False)

    # ---------------------------------------------------------- actions --

    def _on_block(self, *_) -> None:
        if self.auto_update:
            self.refresh()

    def _auto_update_changed(self, checked: bool) -> None:
        self.auto_update = checked
        if checked:
            self.refresh()

    def _selection_changed(self, name: str, checked: bool) -> None:
        for variable in self.template.variables:
            if variable.name == name:
                variable.selected = checked
                break
        self.apply_template()

    def _auto_changed(self, name: str, checked: bool) -> None:
        for variable in self.template.variables:
            if variable.name == name:
                variable.limit_type = 1 if checked else 0
                break
        row = self.limit_rows.get(name)
        if row is not None:
            row[0].setEnabled(not checked)
            row[1].setEnabled(not checked)
        self.refresh()

    def _limits_changed(self, name: str) -> None:
        row = self.limit_rows.get(name)
        if row is None:
            return
        lower, upper, _ = row
        for variable in self.template.variables:
            if variable.name == name:
                variable.ymin, variable.ymax = lower.value(), upper.value()
                break
        self.plot.set_y_range(name, lower.value(), upper.value())

    def _time_range_changed(self) -> None:
        self.template.tstart = self.tstart_box.value()
        self.template.tend = self.tend_box.value()
        self.plot.set_x_range(self.template.tstart, self.template.tend)

    def set_plot_only(self, on: bool) -> None:
        """Hide both side panels so the plot has the window (point 15)."""
        self.limits_action.setChecked(not on)
        self.configuration_action.setChecked(not on)
        self.limits_panel.setVisible(not on)
        self.configuration_panel.setVisible(not on)

    def open_variable_editor(self) -> None:
        """Colour, line style, decimals and limits of every variable (point 16)."""
        from ..dialogs.plot_settings import VariableEditor

        dialog = VariableEditor(self.template, load_plot_styles(self.db_path), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._rebuild_checkboxes()
            self.apply_template()

    def open_settings(self) -> None:
        """Title, graph, axes and flag settings of the template (point 17)."""
        from ..dialogs.plot_settings import PlotSettingsDialog

        dialog = PlotSettingsDialog(self.template, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.setWindowTitle(f"Figure - {self.template.name}")
            self.apply_template()

    def open_data_table(self) -> None:
        if self.control is not None:
            self.control.open_data_table()

    def export_image(self) -> None:
        """The plot as it stands, as a picture."""
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save figure",
            str(Path.home() / f"{self.template.name or 'figure'}.png"),
            "PNG (*.png);;JPEG (*.jpg)",
        )
        if not target:
            return
        if not self.plot.grab().save(target):
            QMessageBox.warning(self, "Export failed", f"Could not write {target}")
            return
        QMessageBox.information(self, "Export", f"Written to {target}")

    def _fill_load_menu(self) -> None:
        self.load_menu.clear()
        for entry in list_plot_templates(self.db_path):
            action = self.load_menu.addAction(entry["name"] or "unnamed")
            action.setEnabled(entry["templateID"] != self.template.templateID)
            action.triggered.connect(
                lambda _=False, tid=entry["templateID"]: self.load_template(tid)
            )

    def load_template(self, template_id: int) -> None:
        self.template = load_plot_template(self.db_path, template_id)
        self.setWindowTitle(f"Figure - {self.template.name}")
        self._rebuild_checkboxes()
        self.apply_template()

    def save_template(self) -> None:
        save_plot_template(self.db_path, self.template)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closed.emit()
        super().closeEvent(event)


def open_figure(db_path: Path | str, runner, template_id: int = 1, control=None) -> FigureWindow:
    """The Open Plot button of the control window.

    The phase list is handed over, not copied: a phase that starts while this
    window is open has to bring its marker with it.
    """
    setup = getattr(control, "setup", None)
    return FigureWindow(
        load_plot_template(db_path, template_id),
        runner,
        db_path,
        control=control,
        phases=getattr(setup, "phases", None),
    )
