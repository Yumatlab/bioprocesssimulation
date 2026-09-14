"""Create Project — the new-project form (plan section 4.2).

Follows the MATLAB CreateProject window: title, author, description and a
table of models.

The plan asks for the organism choice to come from the plugin registry. Both
sources are needed and they answer different questions: modelTab says which
model configurations exist and carries the default parameters, the registry
says which organisms this build can actually simulate. A model whose organism
has no plugin is listed but cannot be chosen — hiding it would leave a user
wondering where their model went.
"""

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...db import create_project, list_models, unique_project_name
from ...organisms import available_organisms, discover_organisms

MISSING = "<missing>"
NO_PARENT = QModelIndex()


def registry_key(model: dict) -> str:
    """organismTab.function_file is the folder name of the plugin."""
    return (
        str(model.get("function_file") or model.get("organism_name") or "")
        .lower()
        .replace(" ", "_")
    )


class ModelTableModel(QAbstractTableModel):
    COLUMNS = (
        ("name", "Model name"),
        ("organism_name", "Organism"),
        ("bioreactor_name", "Bioreactor"),
        ("description", "Description"),
    )

    def __init__(self, models: list[dict], simulatable: set[str]):
        super().__init__()
        self._models = models
        self._simulatable = simulatable

    def model_at(self, row: int) -> dict | None:
        return self._models[row] if 0 <= row < len(self._models) else None

    def is_selectable(self, row: int) -> bool:
        model = self.model_at(row)
        if model is None:
            return False
        return registry_key(model) in self._simulatable and model["parameters"] > 0

    def rowCount(self, parent=NO_PARENT) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._models)

    def columnCount(self, parent=NO_PARENT) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        model = self._models[index.row()]
        key = self.COLUMNS[index.column()][0]

        if role == Qt.ItemDataRole.DisplayRole:
            value = model.get(key)
            return MISSING if value in (None, "") else str(value)
        if role == Qt.ItemDataRole.ForegroundRole and not self.is_selectable(index.row()):
            return QColor(150, 150, 150)
        if role == Qt.ItemDataRole.ToolTipRole and not self.is_selectable(index.row()):
            if model["parameters"] == 0:
                return "this model has no parameters"
            return f"no simulation model is registered for {model['organism_name']}"
        return None

    def headerData(  # noqa: N802 - Qt API
        self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole
    ):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][1]
        return None


class CreateProjectWindow(QWidget):
    """Emits the id of the project it created."""

    project_created = Signal(int)
    return_requested = Signal()

    def __init__(self, db_path: Path | str, parent: QWidget | None = None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.setWindowTitle("Create Project")
        self.resize(560, 600)

        layout = QVBoxLayout(self)

        heading = QLabel("Create a New Project:")
        font = heading.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 3)
        heading.setFont(font)
        layout.addWidget(heading)
        layout.addSpacing(8)

        form = QFormLayout()
        self.title_edit = QLineEdit("MyProject")
        self.author_edit = QLineEdit()
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(70)
        form.addRow("Project title:", self.title_edit)
        form.addRow("Author (optional):", self.author_edit)
        form.addRow("Project description (optional):", self.description_edit)
        layout.addLayout(form)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Select a Model:"))

        discover_organisms()
        self.model = ModelTableModel(list_models(self.db_path), set(available_organisms()))
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.return_button = QPushButton("Return")
        self.create_button = QPushButton("Create")
        buttons.addWidget(self.return_button)
        buttons.addStretch()
        buttons.addWidget(self.create_button)
        layout.addLayout(buttons)

        self.return_button.clicked.connect(self.return_requested.emit)
        self.create_button.clicked.connect(self._create)
        self.title_edit.textChanged.connect(self._update_buttons)
        self._update_buttons()

    def selected_model(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        return self.model.model_at(rows[0].row()) if rows else None

    def _update_buttons(self, *_) -> None:
        rows = self.table.selectionModel().selectedRows()
        selectable = bool(rows) and self.model.is_selectable(rows[0].row())
        self.create_button.setEnabled(selectable and bool(self.title_edit.text().strip()))

    def _create(self) -> None:
        model = self.selected_model()
        if model is None or not self.create_button.isEnabled():
            return
        # uniqueProjectname of the original: projectTab.name is UNIQUE, so a
        # taken name gets a suffix rather than an error.
        name = unique_project_name(self.db_path, self.title_edit.text().strip())
        try:
            project_id = create_project(
                self.db_path,
                name,
                model["modelID"],
                author=self.author_edit.text().strip(),
                description=self.description_edit.toPlainText().strip(),
            )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Create Project", str(error))
            return
        self.project_created.emit(project_id)
