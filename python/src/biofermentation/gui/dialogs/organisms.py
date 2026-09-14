"""Managing organisms without editing the database.

The companion of the bioreactor dialog, one level up: an organism is a set of
default parameter values plus the *kinetics*, and only the first of the two is
data. A copy of Escherichia coli with different yields is a new organism and
needs no Python; a new set of balance equations is a model plugin and does.

The dialog says which of the two it can do. `function_file` — the plugin whose
kinetics the organism runs — is shown and not editable: a copy keeps the
kinetics it was copied from, and pointing an organism at a plugin that does
not exist would produce a project that cannot be opened.

**A saved change reaches new models**, and through them new projects. A model
copies the values when it is created, a project copies them again from the
model. That is two layers of copy, and both are what make a stored run
reproducible.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...db.bioreactors import list_bioreactors
from ...db.definitions import (
    delete_organism,
    export_definition,
    free_organism_name,
    import_definition,
    list_organisms,
    organism_parameters,
    organism_usage,
    save_organism_parameters,
    update_organism,
)
from ...db.project import create_model, free_model_name
from ..widgets.tex import rich_label, tex_label
from .parameters import decimals_for


class OrganismManager(QDialog):
    """The organisms of this database, and the values that make one up."""

    def __init__(self, db_path: Path | str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Organisms")
        self.resize(920, 700)
        self.db_path = Path(db_path)
        self._boxes: dict[str, QDoubleSpinBox] = {}
        self._current: str | None = None

        layout = QVBoxLayout(self)
        note = QLabel(
            "An organism is a set of default values and a set of kinetics. The "
            "values are edited here and reach <b>new models</b>, and through them "
            "new projects. The kinetics are a model plugin: a copy keeps the ones "
            "it was copied from."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        body = QHBoxLayout()
        layout.addLayout(body, 1)

        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._select)
        left.addWidget(self.list, 1)
        self.new_button = QPushButton("New from selected…")
        self.model_button = QPushButton("Make selectable…")
        self.model_button.setToolTip(
            "A project is created from a model — an organism in a vessel. "
            "Until one exists, this organism cannot be chosen anywhere."
        )
        self.delete_button = QPushButton("Delete…")
        self.new_button.clicked.connect(lambda: self.create_from_selected())
        self.model_button.clicked.connect(lambda: self.create_model_for_selected())
        self.delete_button.clicked.connect(lambda: self.delete_selected())
        for button in (self.new_button, self.model_button, self.delete_button):
            left.addWidget(button)
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(240)
        body.addWidget(holder)

        right = QVBoxLayout()
        head = QFormLayout()
        self.name_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.kinetics_label = QLabel("")
        self.kinetics_label.setStyleSheet("color: #6a6a6a;")
        self.reservoirs_label = QLabel("")
        self.reservoirs_label.setStyleSheet("color: #6a6a6a;")
        head.addRow("Name:", self.name_edit)
        head.addRow("Description:", self.description_edit)
        head.addRow("Kinetics:", self.kinetics_label)
        head.addRow("Reservoirs:", self.reservoirs_label)
        right.addLayout(head)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        right.addWidget(self.area, 1)
        self.usage_label = QLabel("")
        self.usage_label.setStyleSheet("color: #6a6a6a;")
        right.addWidget(self.usage_label)
        body.addLayout(right, 1)

        buttons = QDialogButtonBox()
        self.save_button = QPushButton("Save")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(lambda: self.save())
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.ApplyRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh()

    # ------------------------------------------------------------- list --

    def refresh(self, select: str | None = None) -> None:
        wanted = select or self._current
        self.list.blockSignals(True)
        self.list.clear()
        names = [row["name"] for row in list_organisms(self.db_path)]
        self.list.addItems(names)
        self.list.blockSignals(False)
        if names:
            self.list.setCurrentRow(names.index(wanted) if wanted in names else 0)
            self._select(self.list.currentItem().text())

    def _select(self, name: str) -> None:
        if not name:
            return
        self._current = name
        definition = export_definition(self.db_path, name)
        self.name_edit.setText(definition.display_name)
        self.description_edit.setText(definition.description or "")
        self.kinetics_label.setText(
            f"{definition.function_file or '—'} — a copy keeps these; new ones are a plugin"
        )
        self.reservoirs_label.setText(str(definition.n_reservoirs))
        self._build_form(organism_parameters(self.db_path, name))

        usage = organism_usage(self.db_path, name)
        in_use = usage["models"] or usage["projects"]
        self.usage_label.setText(
            f"Used by {usage['models']} model(s) and {usage['projects']} project(s)."
            if in_use
            else "Used by nothing — safe to delete."
        )
        self.delete_button.setEnabled(not in_use)
        self.delete_button.setToolTip(
            "" if not in_use else "An organism something stands on cannot be deleted."
        )

    def _build_form(self, rows: list[dict]) -> None:
        """One group per category, one field per parameter."""
        self._boxes = {}
        inner = QWidget()
        column = QVBoxLayout(inner)
        form: QFormLayout | None = None
        heading = None

        for row in rows:
            title = f"{row['categorysection']} — {row['categoryname']}"
            if title != heading:
                heading = title
                group = QGroupBox(title)
                form = QFormLayout(group)
                form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
                column.addWidget(group)

            value = float(row["value"] or 0.0)
            box = QDoubleSpinBox()
            box.setDecimals(decimals_for(value))
            box.setRange(-1e12, 1e12)
            box.setValue(value)
            box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            box.setAlignment(Qt.AlignmentFlag.AlignRight)
            box.setMinimumWidth(130)
            box.setToolTip(f"{row['parametername']}\n{row['description'] or ''}".strip())
            self._boxes[row["parametername"]] = box
            label = rich_label(tex_label(row["tex"] or row["parametername"], row["unit"]))
            label.setToolTip(box.toolTip())
            form.addRow(label, box)

        column.addStretch()
        self.area.setWidget(inner)

    # ---------------------------------------------------------- actions --

    def create_from_selected(self, name: str | None = None) -> str | None:
        """A copy under a new name: same kinetics, its own values.

        The models of the original do not come along. They belong to it, and a
        copy that carried them would carry parameter sets nobody asked for —
        "Make selectable…" builds the one model the copy actually needs.
        """
        if self._current is None:
            return None
        if name is None:
            suggestion = free_organism_name(self.db_path, f"{self._current} (copy)")
            name, accepted = QInputDialog.getText(
                self, "New organism", "Name of the new organism:", text=suggestion
            )
            if not accepted:
                return None
        name = name.strip()
        if not name:
            return None
        if name in {row["name"] for row in list_organisms(self.db_path)}:
            QMessageBox.warning(self, "New organism", f"{name!r} already exists.")
            return None

        copy = export_definition(self.db_path, self._current)
        copy.display_name = name
        copy.name = name.lower().replace(" ", "_")
        copy.models = []
        import_definition(self.db_path, copy)
        self.refresh(select=name)
        return name

    def create_model_for_selected(
        self, bioreactor_id: int | None = None, name: str | None = None
    ) -> int | None:
        """Build a model so this organism can be chosen for a project."""
        vessels = list_bioreactors(self.db_path)
        if not vessels or self._current is None:
            return None
        if bioreactor_id is None:
            labels = [row["name"] for row in vessels]
            label, accepted = QInputDialog.getItem(
                self, "Make selectable", "Bioreactor:", labels, 0, False
            )
            if not accepted:
                return None
            bioreactor_id = vessels[labels.index(label)]["bioreactorID"]

        vessel = next(row for row in vessels if row["bioreactorID"] == bioreactor_id)
        if name is None:
            suggestion = free_model_name(self.db_path, f"{self._current} in {vessel['name']}")
            name, accepted = QInputDialog.getText(
                self, "Make selectable", "Name of the model:", text=suggestion
            )
            if not accepted:
                return None

        try:
            model_id = create_model(
                self.db_path,
                name.strip(),
                self._organism_id(),
                bioreactor_id,
                description=f"{self._current} in {vessel['name']}",
            )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Make selectable", str(error))
            return None

        self._select(self._current)
        QMessageBox.information(
            self, "Make selectable", f"{name} can now be chosen when a new project is created."
        )
        return model_id

    def _organism_id(self) -> int:
        return next(
            row["organismID"]
            for row in list_organisms(self.db_path)
            if row["name"] == self._current
        )

    def delete_selected(self, *, confirmed: bool = False) -> bool:
        if self._current is None:
            return False
        if not confirmed:
            answer = QMessageBox.warning(
                self,
                "Delete organism",
                f"Delete {self._current!r} and its default values?\n\nThis cannot be undone.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            delete_organism(self.db_path, self._current)
        except ValueError as error:
            QMessageBox.warning(self, "Delete organism", str(error))
            return False
        self._current = None
        self.refresh()
        return True

    def save(self, *, announce: bool = True) -> bool:
        """Write back what this dialog shows, and nothing else.

        `save_organism_parameters` touches the default values; a rename and a
        description are one UPDATE on the organism row. Rewriting the
        categories, variables and models on the way out would be a lot of risk
        for four numbers.
        """
        if self._current is None:
            return False
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Organism", "an organism needs a name")
            return False

        try:
            save_organism_parameters(
                self.db_path,
                self._current,
                {key: box.value() for key, box in self._boxes.items()},
            )
            update_organism(
                self.db_path,
                self._current,
                new_name=name,
                description=self.description_edit.text().strip() or None,
            )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Organism", str(error))
            return False

        self._current = name
        self.refresh(select=name)
        if announce:
            QMessageBox.information(
                self, "Organism", f"{name} saved. New models will use these values."
            )
        return True
