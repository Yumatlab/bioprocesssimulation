"""The Control App (plan section 5).

Five tabs, as the original has them: Control Options, Variable Pool, Process
Manager, Log and Information. The layout follows the screenshot on page 54 of
the thesis.

Two rules the window keeps to:

  * Every write into the simulation state goes through the runner's guard.
    A setpoint changed while a timer tick is halfway through a step is what
    the guard exists for.
  * The window reads the state, it never computes. Everything shown comes out
    of v and p; nothing is derived here.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...control import PhaseStatus
from ...core.simulation_runner import SimulationRunner
from ...db import save_project_with_backup
from ...db.models import ProjectSetup
from ..widgets import CONTROL_PANELS, ControlPanel, PhaseGrid, StatusLamp


class ControlWindow(QMainWindow):
    """The running process: setpoints on the left, the run controls on the right."""

    closed = Signal()

    def __init__(
        self,
        setup: ProjectSetup,
        runner: SimulationRunner,
        db_path: Path | str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setup = setup
        self.runner = runner
        self.db_path = Path(db_path)
        self.log_lines: list[str] = []
        self.figure_window = None

        info = setup.info
        self.setWindowTitle(
            f"Control App - {info.name} - {info.organism_name} - {info.bioreactor_name}"
        )
        self.resize(1290, 690)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        outer.addWidget(self._build_run_column())

        self.panels: dict[str, ControlPanel] = {}
        self.tabs.addTab(self._build_control_options(), "Control Options")
        self.tabs.addTab(self._build_variable_pool(), "Variable Pool")
        self.tabs.addTab(self._build_process_manager(), "Process Manager")
        self.tabs.addTab(self._build_log(), "Log")
        self.tabs.addTab(self._build_information(), "Information")

        runner.block_completed.connect(self.refresh)
        runner.phase_started.connect(lambda _: self.refresh_phases())
        runner.phase_ended.connect(lambda _: self.refresh_phases())
        runner.stopped.connect(self._on_stopped)
        runner.failed.connect(self._on_failed)

        self.load_from_state()

    # ------------------------------------------------------------ build --

    def _build_control_options(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setSpacing(6)
        for spec in CONTROL_PANELS:
            panel = ControlPanel(spec)
            panel.setObjectName("controlPanel")
            panel.parameter_changed.connect(self._set_parameter)
            self.panels[spec.title] = panel
            layout.addWidget(panel)
        return page

    def _build_run_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(210)
        layout = QVBoxLayout(column)

        self.lamps: dict[str, StatusLamp] = {}
        for name in ("Connected", "Process Running", "Inoculated"):
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(QLabel(name))
            lamp = StatusLamp()
            self.lamps[name] = lamp
            row.addWidget(lamp)
            layout.addLayout(row)
        self.lamps["Connected"].set_on(True)
        layout.addSpacing(20)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Process Time [h]"))
        self.time_label = QLabel("0.000")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_row.addWidget(self.time_label)
        layout.addLayout(time_row)
        layout.addSpacing(10)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.setMinimumHeight(44)
        font = self.run_button.font()
        font.setPointSize(font.pointSize() + 4)
        self.run_button.setFont(font)
        self.run_button.clicked.connect(self.toggle_run)
        layout.addWidget(self.run_button)

        self.inoculate_button = QPushButton("Inoculate")
        self.inoculate_button.setCheckable(True)
        self.inoculate_button.clicked.connect(self.inoculate)
        layout.addWidget(self.inoculate_button)
        layout.addSpacing(20)

        form = QFormLayout()
        self.dt_box = QSpinBox()
        self.dt_box.setRange(1, 3600)
        self.dt_box.setValue(int(self.runner.state.p.get("deltatsec", 2) or 2))
        self.dt_box.valueChanged.connect(self._set_dt)
        form.addRow("Δt [s]", self.dt_box)

        self.speed_box = QSpinBox()
        self.speed_box.setRange(1, 1000)
        self.speed_box.setValue(self.runner.speedfactor)
        self.speed_box.valueChanged.connect(self.runner.set_speedfactor)
        form.addRow("Speed factor [x]", self.speed_box)
        layout.addLayout(form)

        layout.addStretch()
        self.plot_button = QPushButton("Open Plot")
        self.plot_button.clicked.connect(self.open_plot)
        layout.addWidget(self.plot_button)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.close)
        layout.addWidget(self.exit_button)
        return column

    def _build_variable_pool(self) -> QWidget:
        self.variable_table = QTableWidget(0, 3)
        self.variable_table.setHorizontalHeaderLabels(["Variable", "Value", "Unit"])
        self.variable_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.variable_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return self.variable_table

    def _build_process_manager(self) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        self.phase_grid = PhaseGrid()
        self.phase_grid.force_start_requested.connect(self.force_start)
        self.phase_grid.delete_requested.connect(self.delete_phase)
        self.phase_grid.edit_requested.connect(self.edit_phase)
        self.phase_grid.add_requested.connect(self.add_phase)
        area.setWidget(self.phase_grid)
        return area

    def _build_log(self) -> QWidget:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        return self.log_view

    def _build_information(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Project")
        form = QFormLayout(box)
        info = self.setup.info
        for label, value in (
            ("Name", info.name),
            ("Description", info.description),
            ("Author", info.author),
            ("Created on", info.created_on),
            ("Last used", info.recent_use),
            ("Organism", info.organism_name),
            ("Bioreactor", info.bioreactor_name),
            ("Reservoirs", info.reservoirs),
            ("Parameters", len(self.setup.p)),
            ("Phases", len(self.setup.phases)),
        ):
            form.addRow(f"{label}:", QLabel(str(value if value not in (None, "") else "-")))
        layout.addWidget(box)
        layout.addStretch()
        return page

    # ------------------------------------------------------------ state --

    def load_from_state(self) -> None:
        state = self.runner.state
        for panel in self.panels.values():
            panel.load(state.p)
        self.refresh_phases()
        self.refresh()

    def refresh(self, *_) -> None:
        """Everything the running simulation changes. One place, one moment."""
        state = self.runner.state
        index = state.idx
        self.time_label.setText(f"{float(state.v.t[index]):.3f}")
        self.lamps["Process Running"].set_on(self.runner.running)
        self.lamps["Inoculated"].set_on(bool(state.a.get("inoc_occ", 0)))
        self.run_button.setText("Pause" if self.runner.running else "Run")
        self._update_inoculate_button()

        for panel in self.panels.values():
            panel.update_actuals(state.v, index)

        if self.tabs.currentIndex() == 1:
            self._refresh_variables()

    def _refresh_variables(self) -> None:
        state = self.runner.state
        units = {row["name"]: row.get("unit", "") for row in self.setup.lookups.process_variable}
        names = sorted(name for name, series in state.v.items() if hasattr(series, "size"))
        self.variable_table.setRowCount(len(names))
        for row, name in enumerate(names):
            value = float(state.v[name][state.idx])
            self.variable_table.setItem(row, 0, QTableWidgetItem(name))
            self.variable_table.setItem(row, 1, QTableWidgetItem(f"{value:.6g}"))
            self.variable_table.setItem(row, 2, QTableWidgetItem(units.get(name, "")))

    def refresh_phases(self) -> None:
        self.phase_grid.rebuild(
            self.setup.phases,
            {row["process_typeID"]: row["type"] for row in self.setup.lookups.process_type},
            {row["process_statusID"]: row["status"] for row in self.setup.lookups.process_status},
            {row["variableID"]: row for row in self.setup.lookups.process_variable},
            {
                row["process_operatorID"]: row["condition"]
                for row in self.setup.lookups.process_operator
            },
        )

    # ---------------------------------------------------------- actions --

    def _set_parameter(self, name: str, value: float) -> None:
        """Every write goes through the guard, so no tick sees it half done."""
        with self.runner.editing() as state:
            old = state.p.get(name)
            state.p[name] = value
            self.note(f"Parameter {name} changed from {old} to {value}")

    def _set_dt(self, seconds: int) -> None:
        with self.runner.editing() as state:
            state.p["deltatsec"] = float(seconds)
            state.dt = seconds / 3600
        self.note(f"Δt set to {seconds} s")

    def toggle_run(self) -> None:
        if self.runner.running:
            self.runner.pause()
            self.note("Process paused")
        else:
            self.runner.start()
            self.note("Process started")
        self.refresh()

    def _update_inoculate_button(self) -> None:
        """Toggle before the run, one shot during it, dead afterwards.

        Before the first step the flag is just a setting and may be turned
        on and off. Once the simulation is running, inoculating is an event
        that happens once — so the button fires once and is then done.
        """
        state = self.runner.state
        happened = bool(state.a.get("inoc_occ", 0))
        started = state.idx > 0

        self.inoculate_button.setEnabled(not happened)
        self.inoculate_button.setCheckable(not started)
        if not started:
            self.inoculate_button.blockSignals(True)
            self.inoculate_button.setChecked(bool(state.p.get("f_Inoc", 0)))
            self.inoculate_button.blockSignals(False)
            self.inoculate_button.setToolTip("Inoculate at the first step")
        elif happened:
            self.inoculate_button.setToolTip("Already inoculated")
        else:
            self.inoculate_button.setToolTip("Inoculate now")

    def inoculate(self) -> None:
        state = self.runner.state
        if state.idx == 0:
            # Still a setting: on and off as often as you like.
            wanted = self.inoculate_button.isChecked()
            with self.runner.editing() as editable:
                editable.p["f_Inoc"] = float(wanted)
            self.note(f"Inoculation at start {'armed' if wanted else 'disarmed'}")
        else:
            with self.runner.editing() as editable:
                editable.p["f_Inoc"] = 1.0
            self.note("Inoculation requested")
        self.refresh()

    def force_start(self, index: int) -> None:
        """The arrow between two panels: end the current phase, start the next."""
        with self.runner.editing():
            if index > 0:
                self.setup.phases[index - 1].statusID = PhaseStatus.COMPLETED
            self.setup.phases[index].statusID = PhaseStatus.PENDING
            if self.runner.phases is not None:
                self.runner.phases.current = None
        self.note(f"Phase {index + 1} forced to start")
        self.refresh_phases()

    def edit_phase(self, index: int) -> None:
        """exec() blocks the way waitfor(dialog) does, so nothing races it."""
        from ..dialogs import PhaseEditor

        phase = self.setup.phases[index]
        dialog = PhaseEditor(
            phase, self.setup.lookups, reservoirs=self.setup.info.reservoirs or 1, parent=self
        )
        with self.runner.editing():
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            self.note(f"Phase {index + 1} edited: {phase.name}")
            self.refresh_phases()

    def add_phase(self) -> None:
        from ...control import EndCondition, PhaseType, StartCondition
        from ...control import PhaseStatus as Status
        from ...db.models import Condition, Phase

        with self.runner.editing():
            phase = Phase(
                processID=self.setup.next_process_id,
                projectID=self.setup.info.projectID,
                statusID=Status.UPCOMING,
                typeID=PhaseType.MANUAL,
                name=f"Phase {len(self.setup.phases) + 1}",
                reservoirID=1,
                start=Condition(typeID=StartCondition.PREVIOUS_ENDED),
                end=Condition(typeID=EndCondition.TIMER, value=1.0),
            )
            self.setup.phases.append(phase)
            self.setup.next_process_id += 1
            if self.runner.phases is not None:
                self.runner.phases.phases = self.setup.phases
        self.note(f"Phase {phase.name!r} added")
        self.refresh_phases()

    def delete_phase(self, index: int) -> None:
        with self.runner.editing():
            phase = self.setup.phases.pop(index)
            if self.runner.phases is not None:
                self.runner.phases.phases = self.setup.phases
                self.runner.phases.current = None
        self.note(f"Phase {phase.name!r} deleted")
        self.refresh_phases()

    def save(self) -> None:
        """The one write at session end, with the backup of plan 1.3."""
        was_running = self.runner.running
        self.runner.pause()
        state = self.runner.state
        from ...db.models import VariableSeries

        trimmed = state.trimmed()
        series = VariableSeries(t=trimmed.get("t"), v=trimmed, real_t=[""] * (state.idx + 1))
        result, backup = save_project_with_backup(
            self.db_path,
            self.setup.info.projectID,
            p=dict(state.p),
            series=series,
            phases=self.setup.phases,
        )
        self.note(f"Saved: {result['times']} time points, backup at {backup.name}")
        if was_running:
            self.runner.start()

    # ------------------------------------------------------------- log --

    def open_plot(self) -> None:
        """The Figure App, on the same runner. One window at a time."""
        from .figure_app import open_figure

        if self.figure_window is None:
            self.figure_window = open_figure(self.db_path, self.runner)
            self.figure_window.closed.connect(self._figure_closed)
        self.figure_window.show()
        self.figure_window.raise_()
        self.note("Plot opened")

    def _figure_closed(self) -> None:
        self.figure_window = None

    def note(self, message: str) -> None:
        self.log_lines.append(message)
        self.log_view.appendPlainText(message)

    def _on_stopped(self, reason: str) -> None:
        self.note(f"Process stopped: {reason}")
        self.refresh()

    def _on_failed(self, message: str) -> None:
        self.note(f"Simulation failed: {message}")
        self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.figure_window is not None:
            self.figure_window.close()
        self.runner.pause()
        self.closed.emit()
        super().closeEvent(event)
