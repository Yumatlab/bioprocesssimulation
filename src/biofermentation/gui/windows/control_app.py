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

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QPalette, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...control import PhaseStatus
from ...core.simulation_runner import SimulationRunner
from ...db import load_project_log, save_project_with_backup
from ...db.models import ProjectSetup
from ...resources import app_icon_path
from ..widgets import CONTROL_PANELS, ControlPanel, PhaseGrid, StatusLamp
from ..widgets.log_view import LogView
from ..widgets.variable_pool import VariablePool

#: Provenance and licence. Taken from the Information tab of the original,
#: which is the only place either is recorded.
ABOUT_TEXT = """
<p><b>Author of the MATLAB application:</b> Philipp Yuma Iff, 18.07.2025</p>

<p>This work is licensed under the
<a href="http://creativecommons.org/licenses/by/4.0/">Creative Commons
Attribution 4.0 International License</a>. To view a copy of this license,
visit http://creativecommons.org/licenses/by/4.0/ or send a letter to
Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.</p>

<p>This application is based on Version 1.3 of the Biofermentation Simulation
App by Lena Sophia Kaletsch (01.03.2024) and the BIOSIM program conceived by
Prof. Dr.-Ing. R. Luttmann. It was developed for the laboratory of Bioprocess
Automation at the University of Applied Sciences Hamburg.</p>

<p style="color:#6a6a6a">The two institutional logos of the original are not
reproduced here: they are the university's image assets, not part of this
port.</p>
"""


#: Where each panel of Control Options sits: column, row, how many rows it
#: spans. Four columns, all of them filling the tab from top to bottom — the
#: first three hold one panel each, the fourth is split into two equal halves.
PANEL_PLACES = {
    "pH-Control": (0, 0, 2),
    "Temperature-Control": (1, 0, 2),
    "pO2-Control": (2, 0, 2),
    "Liquid Weight": (3, 0, 1),
    "Feed Control": (3, 1, 1),
}
PANEL_SPACING = 6


class ControlWindow(QMainWindow):
    """The running process: setpoints on the left, the run controls on the right."""

    closed = Signal()
    requested_new_project = Signal()
    requested_open_project = Signal()

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
        self.figure_windows: list = []
        self.data_tables: list = []
        # Set once the closing question has been answered, so the answer is
        # not asked for twice on the way out.
        self._leave_confirmed = False

        info = setup.info
        self.setWindowTitle(
            f"Control App - {info.name} - {info.organism_name} - {info.bioreactor_name}"
        )
        # The five controller panels and the run column need this much; see
        # ControlPanel.content_width and indicators.FIELD_MIN_WIDTH. The
        # height carries the tallest panel and the run column.
        self.resize(1420, 680)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)

        self._build_menus()

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        outer.addWidget(self._build_run_column())

        self.panels: dict[str, ControlPanel] = {}
        self.tabs.addTab(self._build_control_options(), "Control Options")
        self.tabs.addTab(self._build_variable_pool(), "Variable Pool")
        self.tabs.addTab(self._build_process_manager(), "Process Manager")
        self.tabs.addTab(self._build_log(), "Log")
        self.information_tab = self._build_information()
        self.tabs.addTab(self.information_tab, "Information")
        self._style_tab_pages()
        # Connected only now: adding a tab fires currentChanged, and refresh
        # reads widgets the later tabs have not built yet.
        self.tabs.currentChanged.connect(lambda _: self.refresh())

        runner.block_completed.connect(self.refresh)
        runner.phase_started.connect(self._phase_changed)
        runner.phase_ended.connect(self._phase_changed)
        runner.stopped.connect(self._on_stopped)
        runner.failed.connect(self._on_failed)

        self.load_from_state()
        self.load_log()

    # ------------------------------------------------------------ build --

    def _style_tab_pages(self) -> None:
        """Let the stylesheet paint the pages.

        A plain QWidget ignores a background from a style sheet unless it is
        told to draw itself through the style — QFrame and friends do it on
        their own, QWidget does not. The colour stays in default.qss; only the
        permission is given here.
        """
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            page.setObjectName("tabPage")
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if isinstance(page, QScrollArea):
                page.setFrameShape(QScrollArea.Shape.NoFrame)
                # The viewport is a widget of its own and paints its palette
                # over the page — that is why the Process Manager stayed
                # grey. Neither a style sheet rule nor a transparent viewport
                # reaches it reliably, so it is pointed at the palette role
                # that is white: Base, the ground of an editable surface.
                # Renaming it is not an option, Qt looks the viewport up by
                # its own object name internally.
                page.setBackgroundRole(QPalette.ColorRole.Base)
                page.viewport().setBackgroundRole(QPalette.ColorRole.Base)
                page.viewport().setAutoFillBackground(True)
                inner = page.widget()
                if inner is not None:
                    inner.setObjectName("tabPage")
                    inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def _build_menus(self) -> None:
        """The menu bar of the original: Project, Export, Settings.

        Quick start is gone — it did the same as Start new project (point 2),
        so the submenu it lived in collapsed into one entry.
        """
        bar = self.menuBar()
        # macOS lifts the menu bar out of the window by default, which puts
        # it a screen away from the app it belongs to.
        bar.setNativeMenuBar(False)
        self.actions_by_name: dict[str, QAction] = {}

        def add(menu, text, slot, shortcut: str = "", tip: str = "") -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            if tip:
                action.setStatusTip(tip)
            action.triggered.connect(slot)
            menu.addAction(action)
            self.actions_by_name[text] = action
            return action

        project = bar.addMenu("Project")
        add(project, "Start new project", self.start_new_project)
        add(project, "Open project", self.open_project)
        project.addSeparator()
        add(project, "Parameters…", self.open_parameters, "Ctrl+P")
        add(project, "Project information", self.show_information)
        project.addSeparator()
        add(project, "Save", lambda: self.save(), "Ctrl+S")
        add(project, "Save and exit", self.save_and_exit)
        add(project, "Exit", self.close, "Ctrl+W")

        export = bar.addMenu("Export")
        add(export, "Open data table", lambda: self.open_data_table(), "Ctrl+T")
        add(export, "Export project…", self.export_project, "Ctrl+E")

        plots = bar.addMenu("Plots")
        add(plots, "Open plot", lambda: self.open_plot(), "Ctrl+G")
        self.template_menu = plots.addMenu("Open plot from template")
        self.template_menu.aboutToShow.connect(self._fill_template_menu)

        settings = bar.addMenu("Settings")
        add(settings, "Reset controller parameters", self.reset_controller_gains)

    def _fill_template_menu(self) -> None:
        """Filled on opening, as the original's context menu is."""
        from ...db.plots import list_plot_templates

        self.template_menu.clear()
        try:
            templates = list_plot_templates(self.db_path)
        except Exception as error:  # a template table that will not read
            self.template_menu.addAction(f"unavailable: {error}").setEnabled(False)
            return
        for template in templates:
            action = self.template_menu.addAction(template["name"] or "unnamed")
            action.setToolTip(template.get("description") or "")
            action.triggered.connect(
                lambda _=False, tid=template["templateID"]: self.open_plot(tid)
            )

    def _build_control_options(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setSpacing(PANEL_SPACING)
        reservoirs = int(self.setup.info.reservoirs or 1)
        specs = {spec.title: spec for spec in CONTROL_PANELS}
        for title, (column, row, span) in PANEL_PLACES.items():
            panel = ControlPanel(specs[title], reservoirs=reservoirs)
            panel.setObjectName("controlPanel")
            panel.parameter_changed.connect(self._set_parameter)
            panel.parameters_requested.connect(self.open_controller_parameters)
            self.panels[title] = panel
            # No alignment: every panel fills its cell, and the stretch above
            # its button turns the slack into one gap at the foot of the
            # panel instead of an empty strip under the whole tab.
            layout.addWidget(panel, row, column, span, 1)

        # One width for all four columns, so the panels are equally wide.
        width = max(panel.content_width() for panel in self.panels.values())
        for column in range(4):
            layout.setColumnMinimumWidth(column, width)
            layout.setColumnStretch(column, 1)
        # Two equal halves in the split column. Equal stretch alone only
        # shares out what is left over, and the two panels do not need the
        # same amount to begin with — the taller one would keep its head start
        # at every window size. A common minimum takes it away.
        half = max(
            self.panels[title].minimumSizeHint().height()
            for title, (_, _, span) in PANEL_PLACES.items()
            if span == 1
        )
        for row in range(2):
            layout.setRowMinimumHeight(row, half)
            layout.setRowStretch(row, 1)
        return page

    def _build_run_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(210)
        layout = QVBoxLayout(column)

        # No "Connected" lamp: there is no standing connection to report. The
        # database is read once at the start and written once at the end, and
        # a lamp that is green for the life of the window says nothing.
        self.lamps: dict[str, StatusLamp] = {}
        for name in ("Process Running", "Inoculated"):
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(QLabel(name))
            lamp = StatusLamp()
            self.lamps[name] = lamp
            row.addWidget(lamp)
            layout.addLayout(row)
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
        self.run_button.clicked.connect(lambda: self.toggle_run())
        layout.addWidget(self.run_button)

        self.inoculate_button = QPushButton("Inoculate")
        self.inoculate_button.setCheckable(True)
        self.inoculate_button.clicked.connect(lambda: self.inoculate())
        layout.addWidget(self.inoculate_button)

        self.parameters_button = QPushButton("Parameters…")
        self.parameters_button.setToolTip(
            "All parameters of the project. Before the first step everything "
            "is editable, afterwards only what the model re-reads each cycle."
        )
        self.parameters_button.clicked.connect(lambda: self.open_parameters())
        layout.addWidget(self.parameters_button)
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
        # clicked(bool) would arrive as template_id; the same trap as
        # QAction.triggered(bool) in the menus below.
        self.plot_button.clicked.connect(lambda: self.open_plot())
        layout.addWidget(self.plot_button)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(lambda: self.save())
        layout.addWidget(self.save_button)
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(lambda: self.close())
        layout.addWidget(self.exit_button)
        return column

    def _build_variable_pool(self) -> QWidget:
        self.variable_pool = VariablePool(
            self.setup.lookups.variable, self.setup.info.reservoirs or 1
        )
        return self.variable_pool

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
        self.log_view = LogView()
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
        layout.addWidget(self._about_box())
        layout.addStretch()
        return page

    def _about_box(self) -> QGroupBox:
        """Provenance and licence, as the original's Information tab has them.

        The two logos of the original are not reproduced — they are the
        university's image assets, not part of this port.
        """
        from .starting_screen import VERSION

        box = QGroupBox("About")
        outer = QHBoxLayout(box)

        mark = QLabel()
        mark.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon = app_icon_path(128)
        if icon.is_file():
            mark.setPixmap(QPixmap(str(icon)))
        outer.addWidget(mark, 0)

        layout = QVBoxLayout()
        outer.addLayout(layout, 1)

        heading = QLabel(
            f"<b>Biofermentation Simulation</b><br>Version {VERSION} "
            "(Python port of the MATLAB App Designer application 2.x)"
        )
        heading.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(heading)

        body = QLabel(ABOUT_TEXT)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(body)
        return box

    # ------------------------------------------------------------ state --

    def load_log(self) -> None:
        """Put the stored log back, so a reopened project keeps its history.

        A log that cannot be read back is only half a log — the phase
        transitions and parameter changes of the run so far are exactly what
        someone reopening a project wants to see.
        """
        try:
            rows = load_project_log(self.db_path, self.setup.info.projectID)
        except Exception as error:  # a logTab that will not read
            self.note(f"Log could not be loaded: {error}", "Error")
            return
        if rows:
            self.log_view.load(rows)

    def load_from_state(self) -> None:
        state = self.runner.state
        for panel in self.panels.values():
            panel.load(state.p)
        self.refresh_phases()
        self.refresh()

    def refresh(self, *_) -> None:
        """Everything the running simulation changes. One place, one moment."""
        self._drain_phase_log()
        state = self.runner.state
        index = state.idx
        self.time_label.setText(f"{float(state.v.t[index]):.3f}")
        self.lamps["Process Running"].set_on(self.runner.running)
        self.phase_grid.set_editable(not self.runner.running)
        self.lamps["Inoculated"].set_on(bool(state.a.get("inoc_occ", 0)))
        self.run_button.setText("Pause" if self.runner.running else "Run")
        self._update_inoculate_button()

        for panel in self.panels.values():
            panel.update_actuals(state.v, index)

        # Only the visible tab is redrawn, as the original's timerFcn does.
        if self.tabs.currentWidget() is self.variable_pool:
            self.variable_pool.refresh(state)

        for table in list(self.data_tables):
            table.refresh()

    def refresh_phases(self) -> None:
        # A phase changed under a running automaton would take effect halfway
        # through a block; the process is paused for that, not guarded.
        self.phase_grid.set_editable(not self.runner.running)
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
        # The refresh rate follows the step width, so speedfactor 1 is real
        # time whatever Δt is.
        self.runner.sync_interval_to_dt()
        self.note(f"Δt set to {seconds} s, refresh every {self.runner.interval_ms} ms")

    def toggle_run(self) -> None:
        if self.runner.running:
            self.runner.pause()
            self.note("Process paused", "Process")
        else:
            self.runner.start()
            self.note("Process started", "Process")
        self.refresh()
        self.refresh_phases()

    def _update_inoculate_button(self) -> None:
        """Toggle before the run, one shot during it, dead afterwards.

        The model reads two flags. f_InocStart is the setting the initial
        values are built from — inoculated at t = 0 or not. f_Inoc is the
        event: the step that sees it replaces cXL once and lets the growth
        terms out of the gate. Before the first step the button writes both,
        afterwards only the event.
        """
        state = self.runner.state
        happened = bool(state.a.get("inoc_occ", 0))
        started = state.idx > 0
        # Once it has been pressed during a run it stays dead, whether or not
        # the next step has already set inoc_occ.
        requested = started and bool(state.p.get("f_Inoc", 0))

        self.inoculate_button.setEnabled(not (started and (happened or requested)))
        self.inoculate_button.setCheckable(not started)
        if not started:
            self.inoculate_button.blockSignals(True)
            self.inoculate_button.setChecked(bool(state.p.get("f_InocStart", 0)))
            self.inoculate_button.blockSignals(False)
            self.inoculate_button.setToolTip(
                "Start the process with the culture already inoculated"
            )
        elif happened:
            self.inoculate_button.setToolTip("Already inoculated")
        else:
            self.inoculate_button.setToolTip("Inoculate now")

    def inoculate(self) -> None:
        state = self.runner.state
        if state.idx == 0:
            # Still a setting: on and off as often as you like. cXL at t = 0
            # has to follow, because initialize() has already run.
            wanted = self.inoculate_button.isChecked()
            with self.runner.editing() as editable:
                editable.p["f_InocStart"] = float(wanted)
                editable.p["f_Inoc"] = float(wanted)
                editable.a["inoc_occ"] = 1 if wanted else 0
                editable.v.cXL[0] = float(editable.p["cXL0"]) if wanted else 0.0
            self.note(f"Inoculation at start {'armed' if wanted else 'disarmed'}", "Process")
        else:
            with self.runner.editing() as editable:
                editable.p["f_Inoc"] = 1.0
            # Dead immediately, not only once the next step has set inoc_occ:
            # the press is the feedback that it was taken.
            self.inoculate_button.setEnabled(False)
            self.inoculate_button.setToolTip("Inoculating…")
            self.note("Inoculation requested", "Process")
        self.refresh()

    def open_controller_parameters(self, title: str) -> None:
        """The "Parameters" button of one controller panel (point 3)."""
        from ..dialogs import ControllerParametersDialog

        panel = self.panels[title]
        dialog = ControllerParametersDialog(
            panel.spec,
            self.runner.state.p,
            reservoirs=self.setup.info.reservoirs or 1,
            editable=True,  # controller gains are cyclic, so always editable
            parent=self,
        )
        with self.runner.editing():
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            self._apply_changes(dialog.changes, f"{title} parameters")

    def open_parameters(self) -> None:
        """The whole parameter set (point 4).

        What stays editable during a run is decided by categoryTab.reading_rate,
        not by this window.
        """
        from ..dialogs import ParameterDialog

        dialog = ParameterDialog(
            self.setup.p_meta,
            self.runner.state.p,
            started=self.runner.state.idx > 0,
            parent=self,
        )
        with self.runner.editing():
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            self._apply_changes(dialog.changes, "Parameters")

    def _apply_changes(self, changes: dict[str, float], what: str) -> None:
        """One guarded write for a whole dialog, not one per field."""
        if not changes:
            self.note(f"{what}: nothing changed", "Parameter Value Change")
            return
        with self.runner.editing() as state:
            for name, value in changes.items():
                old = state.p.get(name)
                state.p[name] = value
                self.note(
                    f"Parameter {name} has been changed from {old} to {value}",
                    "Parameter Value Change",
                )
        for panel in self.panels.values():
            panel.load(self.runner.state.p)
        self.refresh()

    def _drain_phase_log(self) -> None:
        """What the automaton wrote — feed summaries, parameter updates.

        It cannot emit a signal of its own; core/ stays free of Qt.
        """
        if self.runner.phases is None:
            return
        for message in self.runner.phases.drain_log():
            kind = (
                "Phase Event"
                if "] started" in message or "] ended" in message
                else ("Phase Information")
            )
            self.note(message, kind)

    def _phase_changed(self, _index: int) -> None:
        """A phase started or ended: take the automaton's notes and redraw.

        The window used to write its own "X started at t = …" next to the
        automaton's, which says the same thing from the place that knows. One
        of the two had to go, and it was this one.
        """
        self._drain_phase_log()
        self.refresh_phases()

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
            phase,
            self.setup.lookups,
            reservoirs=self.setup.info.reservoirs or 1,
            parent=self,
            p_meta=self.setup.p_meta,
            p=self.runner.state.p,
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

    def start_new_project(self) -> None:
        """Back to the launcher, which is the only place that creates one."""
        self.requested_new_project.emit()

    def open_project(self) -> None:
        self.requested_open_project.emit()

    def save_and_exit(self) -> None:
        self.save(announce=False)
        self._leave_confirmed = True
        self.close()

    def confirm_leave(self) -> bool:
        """Ask what is to become of the project. False means: stay.

        Every way out of a project goes through here — the window's close box,
        Exit, and the two menu entries that open another one. Only one project
        is open at a time, so leaving one is always a decision about it and
        never just a navigation step.
        """
        from ...db import delete_project
        from ..dialogs.closing import Choice, ClosingDialog

        if self._leave_confirmed:
            return True

        was_running = self.runner.running
        self.runner.pause()
        dialog = ClosingDialog(self.setup.info, running=was_running, parent=self)
        dialog.export_requested.connect(lambda: self.export_project(parent=dialog))
        dialog.exec()

        if dialog.choice is Choice.SAVE:
            self.save(announce=False, info=dialog.info_fields())
        elif dialog.choice is Choice.DELETE:
            if not self._confirm_delete():
                if was_running:
                    self.runner.start()
                return False
            delete_project(self.db_path, self.setup.info.projectID)
        elif dialog.choice is Choice.CANCEL:
            if was_running:
                self.runner.start()
            return False

        self._leave_confirmed = True
        return True

    def _confirm_delete(self) -> bool:
        """A second question, because the first one cannot be taken back."""
        answer = QMessageBox.warning(
            self,
            "Delete Project",
            f"Delete {self.setup.info.name!r} and everything measured in it?\n\n"
            "This cannot be undone. A backup of the database is written first.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_information(self) -> None:
        self.tabs.setCurrentWidget(self.information_tab)

    def reset_controller_gains(self) -> None:
        """Put every controller gain back to the model default."""
        from ...db import load_model_defaults

        defaults = load_model_defaults(self.db_path, self.setup.info.organismID)
        gains = {
            meta["parametername"]
            for meta in self.setup.p_meta
            if meta.get("categoryname") == "Controller gain"
        }
        changes = {
            name: value
            for name, value in defaults.items()
            if name in gains and abs(value - self.runner.state.p.get(name, value)) > 1e-15
        }
        self._apply_changes(changes, "Controller gains reset")

    def save(self, announce: bool = True, info: dict[str, str] | None = None) -> None:
        """The one write at session end, with the backup of plan 1.3.

        announce = False for the automatic save on exit, which must not stop
        to be acknowledged. `info` carries the three fields of the closing
        dialog; without it only recent_use is stamped.
        """
        was_running = self.runner.running
        self.runner.pause()
        state = self.runner.state
        from ...db.models import VariableSeries

        trimmed = state.trimmed()
        series = VariableSeries(t=trimmed.get("t"), v=trimmed, real_t=[""] * (state.idx + 1))
        rows = self.log_view.rows()
        result, backup = save_project_with_backup(
            self.db_path,
            self.setup.info.projectID,
            p=dict(state.p),
            series=series,
            phases=self.setup.phases,
            log=rows,
            info=info,
        )
        # The ids the write handed out; without them the next save would
        # store the same entries again.
        self.log_view.adopt_ids(rows)
        if info:
            self.setup.info.name = info.get("name") or self.setup.info.name
            self.setup.info.author = info.get("author", self.setup.info.author)
            self.setup.info.description = info.get("description", self.setup.info.description)
        message = (
            f"Saved {result['times']} time points and {result['parameters']} "
            f"parameters — backup {backup.name}"
        )
        self.note(message, "Project")
        self.statusBar().showMessage(message, 10_000)
        if announce:
            # A box, because the status line and the button flash were missed.
            # It is modal, so a save cannot be confused with one that failed.
            self._flash_saved()
            QMessageBox.information(
                self,
                "Project saved",
                f"{self.setup.info.name} saved.\n\n"
                f"{result['times']} time points, {result['parameters']} parameters, "
                f"{result['phases']} phases, {result['log']} new log entries.\n"
                f"Backup: {backup.name}",
            )
        if was_running:
            self.runner.start()
        return result

    def _flash_saved(self) -> None:
        """The Save button confirms, then goes back to being a Save button."""
        self.save_button.setText("Saved ✓")
        self.save_button.setEnabled(False)
        QTimer.singleShot(1500, self._reset_save_button)

    def _reset_save_button(self) -> None:
        self.save_button.setText("Save")
        self.save_button.setEnabled(True)

    # ------------------------------------------------------------- log --

    def open_plot(self, template_id: int = 1) -> None:
        """A Figure App on the same runner. As many as wanted (point 13).

        MATLAB keeps its figure windows in a cell array and refreshes all of
        them each tick; the same here, except that each window listens to the
        runner itself instead of being polled.
        """
        from .figure_app import open_figure

        window = open_figure(self.db_path, self.runner, template_id, control=self)
        window.closed.connect(lambda w=window: self._figure_closed(w))
        self.figure_windows.append(window)
        window.show()
        window.raise_()
        self.note(f"Plot opened ({window.template.name})")
        return window

    def _figure_closed(self, window) -> None:
        if window in self.figure_windows:
            self.figure_windows.remove(window)

    def open_data_table(self) -> None:
        """The Data Table window of point 18."""
        from .data_table import DataTableWindow

        window = DataTableWindow(self.setup, self.runner, parent=self)
        window.closed.connect(lambda w=window: self._table_closed(w))
        self.data_tables.append(window)
        window.show()
        window.raise_()
        self.note("Data table opened")
        return window

    def _table_closed(self, window) -> None:
        if window in self.data_tables:
            self.data_tables.remove(window)

    def export_project(self, parent=None) -> None:
        """Variables, parameters, phases and log to a folder (point 18).

        `parent` is the closing dialog when the export is started from there —
        a modal dialog only takes input from a window above it.
        """
        from ..dialogs.export import ExportDialog

        dialog = ExportDialog(self.setup, self.runner.state, self.log_lines, parent=parent or self)
        with self.runner.editing():
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted and dialog.written:
            self.note(f"Exported {len(dialog.written)} file(s) to {dialog.target}", "Project")

    def note(self, message: str, event_type: str = "Process") -> None:
        """One log entry: wall-clock time, process time, event title, message."""
        state = self.runner.state
        self.log_view.append(message, event_type, float(state.v.t[state.idx]))

    @property
    def log_lines(self) -> list[str]:
        """The log as plain text, for the export and for logTab."""
        return [entry.as_line() for entry in self.log_view.entries]

    def _on_stopped(self, reason: str) -> None:
        self.note(f"Process stopped: {reason}", "Process")
        self.refresh()

    def _on_failed(self, message: str) -> None:
        self.note(f"Simulation failed: {message}", "Error")
        self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self.confirm_leave():
            event.ignore()
            return
        for window in list(self.figure_windows) + list(self.data_tables):
            window.close()
        self.runner.pause()
        self.closed.emit()
        super().closeEvent(event)
