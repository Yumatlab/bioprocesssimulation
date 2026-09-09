"""Load Project — the project list (plan section 4.2).

Follows the MATLAB SelectProject window: a table of projects, the database
size in the corner and four buttons. QTableView over a small model rather
than a widget table, so sorting and selection come for free and the data
stays separate from the presentation.
"""

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...db import delete_project, list_projects

MISSING = "<missing>"

# Qt's model API takes an invalid QModelIndex to mean "the root". One shared
# instance rather than a call in the argument default.
NO_PARENT = QModelIndex()


class ProjectTableModel(QAbstractTableModel):
    """projectTab as the window shows it.

    A project whose parameter set is short of what its model defines cannot be
    opened. Those are marked rather than hidden — the production database has
    nine of them, and silently dropping a row would only hide the problem.
    """

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
        header.addStretch()
        self.size_label = QLabel()
        header.addWidget(self.size_label)
        layout.addLayout(header)

        self.model = ProjectTableModel()
        self.table = QTableView(self)
        self.table.setModel(self.model)
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
        self.select_button = QPushButton("Select")
        buttons.addWidget(self.return_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.select_button)
        layout.addLayout(buttons)

        self.return_button.clicked.connect(self.return_requested.emit)
        self.create_button.clicked.connect(self.create_requested.emit)
        self.select_button.clicked.connect(self._select)
        self.delete_button.clicked.connect(self._delete)

        self.refresh()

    # ------------------------------------------------------------ data --

    def refresh(self) -> None:
        self.model.set_projects(list_projects(self.db_path))
        size = self.db_path.stat().st_size / 1024 / 1024 if self.db_path.is_file() else 0.0
        self.size_label.setText(f"Database size: {size:.2f} MB")
        self.table.resizeColumnsToContents()
        self._update_buttons()

    def selected_project(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        return self.model.project_at(rows[0].row()) if rows else None

    # --------------------------------------------------------- actions --

    def _update_buttons(self, *_) -> None:
        rows = self.table.selectionModel().selectedRows()
        has_selection = bool(rows)
        self.delete_button.setEnabled(has_selection)
        # A half-written project can be deleted but not opened.
        self.select_button.setEnabled(has_selection and self.model.is_usable(rows[0].row()))

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
        delete_project(self.db_path, project["projectID"])
        self.refresh()
