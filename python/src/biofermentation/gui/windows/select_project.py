"""Load Project — the project list (plan section 4.2).

Follows the MATLAB SelectProject window: a table of projects, the database
size in the corner and four buttons. QTableView over a small model rather
than a widget table, so sorting and selection come for free and the data
stays separate from the presentation.
"""

from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...db import list_projects

MISSING = "<missing>"

# Qt's model API takes an invalid QModelIndex to mean "the root". One shared
# instance rather than a call in the argument default.
NO_PARENT = QModelIndex()


def _sort_key(column: str, value):
    """Something that compares the way a reader expects.

    Dates come out of the database as "20.11.2024 21:26:10.399" and sort as
    text by the day of the month. Turned round they sort by date. Everything
    else sorts case-insensitively, because a project called "abc" belongs
    next to "ABC" and not after "Zeta".
    """
    if value in (None, ""):
        # Empty last, whichever way round the column is sorted.
        return ""
    if column == "recent_use":
        date, _, clock = str(value).partition(" ")
        parts = date.split(".")
        if len(parts) == 3:
            day, month, year = parts
            return f"{year}-{month.zfill(2)}-{day.zfill(2)} {clock}"
    return str(value).casefold()


class ProjectTableModel(QAbstractTableModel):
    """projectTab as the window shows it.

    A project whose parameter set is short of what its model defines cannot be
    opened. Those are marked rather than hidden — the production database has
    nine of them, and silently dropping a row would only hide the problem.
    """

    #: The role the proxy sorts by. Sorting on what is displayed would order
    #: "Last used on" as text — "20.11.2024" before "3.12.2024", because "2"
    #: comes before "3". This role hands out something that compares.
    SORT_ROLE = Qt.ItemDataRole.UserRole + 1

    COLUMNS = (
        ("name", "Title"),
        ("description", "Description"),
        ("recent_use", "Last used on"),
        ("author", "Author"),
        ("organism_name", "Organism"),
        ("bioreactor_name", "Bioreactor"),
    )

    def __init__(self, projects: list[dict] | None = None):
        super().__init__()
        self._projects = projects or []

    def set_projects(self, projects: list[dict]) -> None:
        self.beginResetModel()
        self._projects = projects
        self.endResetModel()

    def project_at(self, row: int) -> dict | None:
        return self._projects[row] if 0 <= row < len(self._projects) else None

    def is_usable(self, row: int) -> bool:
        project = self.project_at(row)
        return bool(project) and project["parameters"] >= project["expected"] > 0

    def rowCount(self, parent=NO_PARENT) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._projects)

    def columnCount(self, parent=NO_PARENT) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        project = self._projects[index.row()]
        key = self.COLUMNS[index.column()][0]

        if role == Qt.ItemDataRole.DisplayRole:
            value = project.get(key)
            return MISSING if value in (None, "") else str(value)
        if role == self.SORT_ROLE:
            return _sort_key(key, project.get(key))
        if role == Qt.ItemDataRole.ForegroundRole and not self.is_usable(index.row()):
            return QColor(150, 150, 150)
        if role == Qt.ItemDataRole.ToolTipRole and not self.is_usable(index.row()):
            return (
                f"{project['parameters']} of {project['expected']} parameters — "
                "this project was left half written and cannot be opened"
            )
        return None

    def headerData(  # noqa: N802 - Qt API
        self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole
    ):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][1]
        return None


class SelectProjectWindow(QWidget):
    """Pick a project, delete one, or go on to create a new one."""

    project_selected = Signal(int)
    create_requested = Signal()
    return_requested = Signal()
    import_requested = Signal()

    def __init__(self, db_path: Path | str, parent: QWidget | None = None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.setWindowTitle("Load Project")
        self.resize(1000, 520)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        heading = QLabel("Select a Project:")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        header.addWidget(heading)
        header.addSpacing(16)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by title, author, organism …")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(280)
        header.addWidget(self.filter_edit)
        header.addStretch()
        self.size_label = QLabel()
        header.addWidget(self.size_label)
        layout.addLayout(header)

        self.model = ProjectTableModel()
        # Between the table and the model: it does the sorting the model has
        # no sort() for — the header arrow used to appear and nothing moved —
        # and it does the filtering the window had none of.
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(ProjectTableModel.SORT_ROLE)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # -1: every column is searched, so one box covers the whole row.
        self.proxy.setFilterKeyColumn(-1)
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)
        self.filter_edit.textChanged.connect(self._update_count)

        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(self._select)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.return_button = QPushButton("Return")
        self.delete_button = QPushButton("Delete Selected Project")
        self.create_button = QPushButton("Create New Project")
        self.import_button = QPushButton("Import Project…")
        self.import_button.setToolTip(
            "Read an exported folder back in and carry on from where it left off"
        )
        self.select_button = QPushButton("Select")
        buttons.addWidget(self.return_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        buttons.addWidget(self.import_button)
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.select_button)
        layout.addLayout(buttons)

        self.return_button.clicked.connect(self.return_requested.emit)
        self.create_button.clicked.connect(self.create_requested.emit)
        self.import_button.clicked.connect(self.import_requested.emit)
        self.select_button.clicked.connect(self._select)
        self.delete_button.clicked.connect(self._delete)

        self.refresh()

    # ------------------------------------------------------------ data --

    def refresh(self) -> None:
        self.model.set_projects(list_projects(self.db_path))
        self.table.resizeColumnsToContents()
        self._update_count()
        self._update_buttons()

    def _update_count(self, *_) -> None:
        """How many rows the filter lets through, and how large the file is.

        Without the count a filter that matches nothing looks like a database
        that lost its projects.
        """
        shown, total = self.proxy.rowCount(), self.model.rowCount()
        size = self.db_path.stat().st_size / 1024 / 1024 if self.db_path.is_file() else 0.0
        counted = f"{shown} of {total} projects" if shown != total else f"{total} projects"
        self.size_label.setText(f"{counted} — database {size:.2f} MB")

    def selected_project(self) -> dict | None:
        row = self._source_row()
        return self.model.project_at(row) if row is not None else None

    def _source_row(self) -> int | None:
        """The row in the model behind the row the table shows.

        With a proxy in between the two differ as soon as anything is sorted
        or filtered, and reading the project at the *view's* row number would
        quietly open or delete the wrong one.
        """
        rows = self.table.selectionModel().selectedRows()
        return self.proxy.mapToSource(rows[0]).row() if rows else None

    # --------------------------------------------------------- actions --

    def _update_buttons(self, *_) -> None:
        row = self._source_row()
        self.delete_button.setEnabled(row is not None)
        # A half-written project can be deleted but not opened.
        self.select_button.setEnabled(row is not None and self.model.is_usable(row))

    def _select(self, *_) -> None:
        project = self.selected_project()
        if project and self.select_button.isEnabled():
            self.project_selected.emit(project["projectID"])

    def _delete(self) -> None:
        project = self.selected_project()
        if project is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Project",
            f"Delete {project['name']!r} and all of its data?\nThis cannot be undone.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # Through the progress dialog: a database that has not been migrated
        # takes half a minute for this, and a dead window looks like a crash.
        from ..dialogs.deleting import delete_with_progress

        delete_with_progress(self, self.db_path, project["projectID"], project["name"])
        self.refresh()
