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

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QPalette, QPixmap
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
from ..settings import load_settings
from ..values import format_value, mode_table
from ..widgets import CONTROL_PANELS, ControllerView, ControlPanel, PhaseGrid, StatusLamp
from ..widgets.log_view import OPERATION_EVENT, LogView
from ..widgets.variable_pool import VariablePool

#: Provenance and licence. The middle paragraph is the one the original's
#: Information tab carries, kept verbatim — it is the licence of the MATLAB
#: application, and the attribution it asks for has to travel with every copy.
#: What it never said is which licence *this* port is under, which left the
#: question open in the one place someone would look it up.
ABOUT_TEXT = """
<p><b>Author:</b> Philipp Yuma Iff. MATLAB application 18.07.2025,
Python port 2026.</p>

<p>The Python port is licensed under the <b>MIT License</b>; the full text and
the attribution below travel with it in the LICENSE file.</p>

<p>It is a port of the Biofermentation Simulation MATLAB App Designer
application, which is licensed under the
<a href="http://creativecommons.org/licenses/by/4.0/">Creative Commons
Attribution 4.0 International License</a>. To view a copy of this license,
visit http://creativecommons.org/licenses/by/4.0/ or send a letter to
Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.</p>

<p>That application continues the work of the previous developer of this
software, <b>Lena Sophia Kaletsch</b>, who developed Version 1.3 of the
Biofermentation Simulation App (01.03.2024). It rests in turn on the BIOSIM
program conceived by Prof. Dr.-Ing. R. Luttmann, and was developed for the
laboratory of Bioprocess Automation at the University of Applied Sciences
Hamburg.</p>

<p style="color:#6a6a6a">A packaged build also contains Qt by way of PySide6,
under the GNU Lesser General Public License v3.</p>

<p style="color:#6a6a6a">The two institutional logos of the original are not
reproduced here: they are the university's image assets, not part of this
port.</p>
"""


#: The gap between two panels of Control Options. Where the panels sit is not
#: here — it is a text file the user can edit; see gui/panel_layout.py.
PANEL_SPACING = 6

#: Air above and below the two signal lamps in the menu bar. It makes the bar
#: taller, which is the point: flush against the window frame they read as
#: part of the title bar rather than as part of the application.
LAMP_MARGIN = 7


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
        # What this installation shows, read once here. A window keeps what it
        # was built with; the dialog says so rather than pretending otherwise.
        self.settings, self._settings_problem = load_settings()
        # What the mode numbers are called. parameter_controlmodesTab is the
        # only place that knows, and both the dialogs and the log need it.
        self.modes = mode_table(setup.p_modes)
        # Set once the closing question has been answered, so the answer is
        # not asked for twice on the way out.
        self._leave_confirmed = False

        info = setup.info
        # The student view is named in the title because it is the one setting
        # that changes what the window can do. Someone looking at a screenshot
        # of a locked Δt should not have to guess why it is locked.
        title = f"Control App - {info.name} - {info.organism_name} - {info.bioreactor_name}"
        if self.settings.student_view:
            title += " - Student View"
        self.setWindowTitle(title)
        self._open_at_a_sensible_size()

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)

        self._build_menus()

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        outer.addWidget(self._build_run_column())

        self.panels: dict[str, ControlPanel] = {}
        # Built either way, added only if the settings show it: the window
        # refreshes them by name, and a tab that exists but is not shown is
        # less trouble than one that does not exist at all.
        self.tabs.addTab(self._build_control_options(), "Control Options")
        # Held on the window, not only in the tab bar: a page that is built
        # and not added has no parent, and Python collecting it would take the
        # log view and the phase grid down with it.
        self.pages = {
            "Controllers": self._build_controllers(),
            "Variable Pool": self._build_variable_pool(),
            "Process Manager": self._build_process_manager(),
            "Log": self._build_log(),
        }
        for title, page in self.pages.items():
            if self.settings.shows(title):
                self.tabs.addTab(page, title)
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
        self._report_resumed_state()
        if self._settings_problem:
            self.note(f"Settings not used — {self._settings_problem}", "Error")
        if self._layout_problem:
            # Said here rather than in a box at startup: the tab is drawn
            # either way, and the log is where the session keeps its record.
            self.note(f"Panel layout not used — {self._layout_problem}", "Error")

    # ------------------------------------------------------------ build --

    def _open_at_a_sensible_size(self) -> None:
        """Wide enough for the panels, and never wider than the screen.

        1420 x 680 was typed in once and then stopped being true. What the
        Control Options tab needs depends on the layout file and on the
        system's font: measured 936 x 672 here, and half as much again on a
        Windows runner. Opening below that means opening already scrolled.

        So: ask for what the panels want plus the run column, and let the
        screen have the last word — a window larger than the display is the
        one size that helps nobody. Anything still left over scrolls.
        """
        wanted = QSize(1420, 770)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry().size()
            wanted = wanted.boundedTo(QSize(available.width() - 40, available.height() - 80))
        self.resize(wanted.expandedTo(QSize(900, 560)))

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
        add(settings, "Panel layout…", self.edit_panel_layout)

        # Held on the window: setCornerWidget does not take ownership of a
        # temporary, and the lamps were collected out from under it.
        self.signal_lights = self._build_signal_lights()
        bar.setCornerWidget(self.signal_lights, Qt.Corner.TopRightCorner)

    def _build_signal_lights(self) -> QWidget:
        """The two state lamps, in the empty right half of the menu bar.

        They used to head the run column, which put them below the tab bar
        with a strip of nothing above them — while the menu bar ran the whole
        width of the window with four entries on it. This is the same height
        as the menus and costs no room at all.

        No "Connected" lamp: there is no standing connection to report. The
        database is read once at the start and written once at the end, and a
        lamp that is green for the life of the window says nothing.

        The margins are the whole point of the corner widget being this tall:
        a menu bar sizes itself around its corner widget, so the padding here
        lifts the lamps off the window frame instead of leaving them pressed
        against it.
        """
        strip = QWidget()
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, LAMP_MARGIN, 10, LAMP_MARGIN)
        row.setSpacing(6)
        self.lamps: dict[str, StatusLamp] = {}
        for name in ("Process Running", "Inoculated"):
            row.addWidget(QLabel(name))
            lamp = StatusLamp()
            self.lamps[name] = lamp
            row.addWidget(lamp)
            row.addSpacing(8)
        return strip

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
        """The controller panels, arranged the way the layout file says.

        In a scroll area, like the Process Manager, and for the same reason:
        **the window has to be able to be narrower than its contents.** What
        the panels need is not a fixed number — it is however wide the
        system's font draws five panels side by side, and that is a different
        number on every platform. Measured: 1174 px here against 1538 on a
        Windows runner, where the screen this is meant for is 1440. Without
        the scroll area the window simply cannot be made to fit, and a
        minimum width nobody can satisfy is worse than a scrollbar nobody
        needs.

        It also keeps the arrangement a matter of taste. The layout file may
        put all five panels on one row; whether that fits is then the screen's
        question, not the application's.
        """
        from ..panel_layout import load_layout

        page = QWidget()
        layout = QGridLayout(page)
        layout.setSpacing(PANEL_SPACING)
        reservoirs = int(self.setup.info.reservoirs or 1)
        specs = {spec.title: spec for spec in CONTROL_PANELS}
        layout_file, self._layout_problem = load_layout(list(specs))
        self.placements = layout_file.places

        for title, place in self.placements.items():
            panel = ControlPanel(
                specs[title],
                reservoirs=reservoirs,
                mode_selector=layout_file.selector_for(title),
            )
            panel.setObjectName("controlPanel")
            panel.parameter_changed.connect(self._set_parameter)
            panel.parameters_requested.connect(self.open_controller_parameters)
            self.panels[title] = panel
            # No alignment: every panel fills its cell, and the stretch above
            # its button turns the slack into one gap at the foot of the
            # panel instead of an empty strip under the whole tab.
            layout.addWidget(panel, place.row, place.column, place.row_span, place.column_span)

        self._size_panel_grid(layout)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(page)
        self.control_options = page
        return area

    def _size_panel_grid(self, layout) -> None:
        """Equal columns, equal rows — whatever the arrangement turns out to be.

        A panel covering two cells needs half of what it asks for out of each,
        and two panels sharing a column only come out equal if they are given
        the same minimum: stretch alone shares out the slack, and the taller
        one would keep its head start at every window size.
        """
        columns = max(p.column + p.column_span for p in self.placements.values())
        rows = max(p.row + p.row_span for p in self.placements.values())

        width = max(
            self.panels[title].content_width() // place.column_span
            for title, place in self.placements.items()
        )
        for column in range(columns):
            layout.setColumnMinimumWidth(column, width)
            layout.setColumnStretch(column, 1)

        height = max(
            self.panels[title].minimumSizeHint().height() // place.row_span
            for title, place in self.placements.items()
        )
        for row in range(rows):
            layout.setRowMinimumHeight(row, height)
            layout.setRowStretch(row, 1)

    def _build_run_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(210)
        layout = QVBoxLayout(column)

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
        if self.settings.student_view:
            # Shown but locked: the step width decides what the numbers mean,
            # and a room that ran at one Δt can compare its results. The speed
            # factor is not shown at all — it changes nothing about the result
            # and everything about how long one waits for it.
            self.dt_box.setReadOnly(True)
            self.dt_box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            self.dt_box.setToolTip("Fixed for this installation — see Settings")
        else:
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

    def _build_controllers(self) -> QWidget:
        """What every loop is doing — the tab the control panels lead to.

        The loops come from the organism, not from here: which signals a
        controller taps is the model's business, and a model that does not
        describe them gets an empty tab rather than a wrong one.
        """
        self.controller_view = ControllerView(
            getattr(self.runner.organism, "control_loops", ()),
            self.setup.info.reservoirs or 1,
        )
        return self.controller_view

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

    def _report_resumed_state(self) -> None:
        """Say what a resumed run could not bring back with it.

        `load_project_state` works this out and then says nothing — the window
        is where a session keeps its record, and for two years this was
        recorded into a field that nothing read.

        It matters because of what is in the list. `variable_handlingTab`
        assigns neither organism the offgas fractions, so `xO2` and `xCO2`
        never reach the database; a continued run restarts them at the
        composition of air. They are ODE states. A run that quietly resets an
        ODE state is a run whose numbers nobody can account for afterwards,
        and the one place that knows has to say so.
        """
        state = self.runner.state
        if state.idx == 0:
            return  # nothing was resumed; there is nothing to report
        restarted = list(state.a.get("restarted_variables") or ())
        if restarted:
            self.note(
                f"Resumed at step {state.idx}: {', '.join(restarted)} are not stored for "
                "this organism and restart from their initial values",
                "Error",
            )
        skipped = list(state.a.get("skipped_variables") or ())
        if skipped:
            # The other direction, and harmless: the table is wider than the
            # model, and those columns come back empty.
            self.note(
                f"Stored series this organism does not compute, left aside: {', '.join(skipped)}",
                "Project",
            )

    def load_panels(self) -> None:
        """Re-read every panel from p: modes, setpoints, switches, reservoir.

        Called whenever something other than the panel itself has written into
        the parameter set — a dialog, or a phase. `refresh()` deliberately
        does not do this: it runs after every block, and re-reading a spin box
        the operator is typing into would take the half-typed number away.
        """
        p = self.runner.state.p
        for panel in self.panels.values():
            panel.load(p)

    def load_from_state(self) -> None:
        self.load_panels()
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
        elif self.tabs.currentWidget() is self.controller_view:
            self.controller_view.refresh(state)

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
            self.note(
                f"Parameter {name} changed from {self._named(name, old)}"
                f" to {self._named(name, value)}"
            )

    def _set_dt(self, seconds: int) -> None:
        with self.runner.editing() as state:
            state.p["deltatsec"] = float(seconds)
            state.dt = seconds / 3600
        # Nur wenn die Einstellung es verlangt. Gekoppelt folgt der Takt der
        # Schrittweite, damit ein Speedfactor von 1 Echtzeit bleibt; entkoppelt
        # hat der Anwender den Takt selbst gesetzt und Δt darf ihn nicht
        # wieder überschreiben.
        self.runner.set_interval(self.settings.interval_ms(seconds))
        self.note(
            f"Δt set to {seconds} s, refresh every {self.runner.interval_ms} ms",
            OPERATION_EVENT,
        )

    def toggle_run(self) -> None:
        if self.runner.running:
            self.runner.pause()
            self.note("Process paused", OPERATION_EVENT)
        else:
            self.runner.start()
            self.note("Process started", OPERATION_EVENT)
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
            modes=self.modes,
            parent=self,
        )
        with self.runner.editing():
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            self._apply_changes(dialog.changes, "Parameters")

    def _named(self, name: str, value) -> str:
        """A parameter's value as it is read: a mode by name, else a number."""
        return format_value(name, value, self.modes)

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
                    f"Parameter {name} has been changed from {self._named(name, old)}"
                    f" to {self._named(name, value)}",
                    "Parameter Value Change",
                )
        self.load_panels()
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
        # A phase writes into p — setpoints, modes, the feed reservoir — and
        # until now nothing re-read them. An "Update Parameter Set" phase that
        # switched the feed to closed loop left the tab showing Manual, and
        # the tab is the one place someone looks to find out what the process
        # is doing. The parameters are already applied when this signal
        # arrives: check_start writes them, then the runner emits.
        self.load_panels()
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
            modes=self.modes,
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
        from ..dialogs.closing import Choice, ClosingDialog
        from ..dialogs.deleting import delete_with_progress

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
            if delete_with_progress(
                self, self.db_path, self.setup.info.projectID, self.setup.info.name
            ) is None:
                # Abgebrochen heißt: nichts gelöscht. Dann bleibt das
                # Fenster stehen, statt ein Projekt zu schließen, das
                # es noch gibt.
                if was_running:
                    self.runner.start()
                return False
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

    def edit_panel_layout(self) -> None:
        """Open the layout file, creating it from the bundled one if need be.

        The arrangement of Control Options is taste, not logic. This is the
        way to change it without a Python file and without a rebuild — the
        same deal the stylesheet has.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ..panel_layout import write_user_layout

        path = write_user_layout()
        QMessageBox.information(
            self,
            "Panel layout",
            f"The arrangement of this tab is a file:\n\n{path}\n\n"
            "It opens now in your editor. Save it and reopen the project to "
            "see the new arrangement.",
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

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
        self.note(f"Plot opened ({window.template.name})", OPERATION_EVENT)
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
        self.note("Data table opened", OPERATION_EVENT)
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
