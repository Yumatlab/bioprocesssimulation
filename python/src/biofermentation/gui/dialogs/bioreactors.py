"""Managing bioreactors without editing the database.

A vessel is pure data: a row in `bioreactorTab` and sixty values in
`default_bioreactorTab`. Adding one has needed a YAML file and the import
menu, or SQL — which is a strange thing to ask of somebody whose laboratory
just bought a different reactor.

So: the list on the left, the vessel on the right, and the four things one
does with them — select, create from an existing one, edit, delete. Creating
from an existing one is not a shortcut but the design: which parameters make
up a vessel is not something a form should ask, it is something the vessel
next to it already knows.

**A saved change reaches new projects only.** `create_project` copies the
values into `project_parameterTab`, and a project that is already running
carries its own copy — which is what makes a stored run reproducible, and why
this dialog says so on the front.
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

from ...db.bioreactors import (
    BioreactorDefinition,
    bioreactor_parameters,
    bioreactor_usage,
    delete_bioreactor,
    export_bioreactor,
    free_bioreactor_name,
    import_bioreactor,
    list_bioreactors,
)
from ...db.definitions import list_organisms
from ...db.project import create_model, free_model_name
from ..widgets.tex import rich_label, tex_label
from .parameters import decimals_for


class BioreactorManager(QDialog):
    """The vessels of this database, and what a vessel is made of."""

    def __init__(self, db_path: Path | str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bioreactors")
        self.resize(880, 660)
        self.db_path = Path(db_path)
        self._boxes: dict[str, QDoubleSpinBox] = {}
        self._current: str | None = None

        layout = QVBoxLayout(self)
        note = QLabel(
            "A bioreactor is a set of parameter values. Changes here reach "
            "<b>new projects</b>: a project copies the values when it is created "
            "and keeps its own from then on, which is what makes a stored run "
            "reproducible."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        body = QHBoxLayout()
        layout.addLayout(body, 1)

        # ------------------------------------------------------ the list --
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._select)
        left.addWidget(self.list, 1)
        self.new_button = QPushButton("New from selected…")
        self.model_button = QPushButton("Make selectable…")
        self.model_button.setToolTip(
            "A project is created from a model — an organism in a vessel. "
            "Until one exists, this bioreactor cannot be chosen anywhere."
        )
        self.delete_button = QPushButton("Delete…")
        self.new_button.clicked.connect(lambda: self.create_from_selected())
        self.model_button.clicked.connect(lambda: self.create_model_for_selected())
        self.delete_button.clicked.connect(lambda: self.delete_selected())
        left.addWidget(self.new_button)
        left.addWidget(self.model_button)
        left.addWidget(self.delete_button)
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(230)
        body.addWidget(holder)

        # --------------------------------------------------- the vessel --
        right = QVBoxLayout()
        head = QFormLayout()
        self.name_edit = QLineEdit()
        self.manufacturer_edit = QLineEdit()
        self.description_edit = QLineEdit()
        head.addRow("Name:", self.name_edit)
        head.addRow("Manufacturer:", self.manufacturer_edit)
        head.addRow("Description:", self.description_edit)
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
        close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh()

    # ------------------------------------------------------------- list --

    def refresh(self, select: str | None = None) -> None:
        """Reread the list. `select` is the name to land on afterwards."""
        wanted = select or self._current
        self.list.blockSignals(True)
        self.list.clear()
        names = [row["name"] for row in list_bioreactors(self.db_path)]
        self.list.addItems(names)
        self.list.blockSignals(False)
        if names:
            self.list.setCurrentRow(names.index(wanted) if wanted in names else 0)
            self._select(self.list.currentItem().text())

    def _select(self, name: str) -> None:
        if not name:
            return
        self._current = name
        definition = export_bioreactor(self.db_path, name)
        self.name_edit.setText(definition.name)
        self.manufacturer_edit.setText(definition.manufacturer or "")
        self.description_edit.setText(definition.description or "")
        self._build_form(bioreactor_parameters(self.db_path, name))

        usage = bioreactor_usage(self.db_path, name)
        in_use = usage["models"] or usage["projects"]
        self.usage_label.setText(
            f"Used by {usage['models']} model(s) and {usage['projects']} project(s)."
            if in_use
            else "Used by nothing — safe to delete."
        )
        self.delete_button.setEnabled(not in_use)
        self.delete_button.setToolTip(
            "" if not in_use else "A vessel something stands on cannot be deleted."
        )

    def _build_form(self, rows: list[dict]) -> None:
        """One group per category, one field per parameter."""
        self._boxes = {}
        inner = QWidget()
        column = QVBoxLayout(inner)
        group: QGroupBox | None = None
        form: QFormLayout | None = None
        heading = None

        for row in rows:
            title = f"{row['categorysection']} — {row['categoryname']}"
            if title != heading:
                heading, group = title, QGroupBox(title)
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

    def definition(self) -> BioreactorDefinition:
        """What the form currently describes."""
        return BioreactorDefinition(
            name=self.name_edit.text().strip(),
            manufacturer=self.manufacturer_edit.text().strip() or None,
            description=self.description_edit.text().strip() or None,
            parameters={name: box.value() for name, box in self._boxes.items()},
        )

    def create_from_selected(self, name: str | None = None) -> str | None:
        """A copy of the selected vessel under a new name.

        Which parameters make up a vessel is not asked here — the one it is
        copied from knows, and a form that asked would be asking the user to
        know the model.
        """
        if self._current is None:
            return None
        if name is None:
            suggestion = free_bioreactor_name(self.db_path, f"{self._current} (copy)")
            name, accepted = QInputDialog.getText(
                self, "New bioreactor", "Name of the new bioreactor:", text=suggestion
            )
            if not accepted:
                return None
        name = name.strip()
        if not name:
            return None
        if name in {row["name"] for row in list_bioreactors(self.db_path)}:
            QMessageBox.warning(self, "New bioreactor", f"{name!r} already exists.")
            return None

        copy = export_bioreactor(self.db_path, self._current)
        copy.name = name
        import_bioreactor(self.db_path, copy)
        self.refresh(select=name)
        return name

    def create_model_for_selected(
        self, organism_id: int | None = None, name: str | None = None
    ) -> int | None:
        """Build a model on this vessel so a project can be created from it.

        `create_project` reads nothing but `model_parameterTab`; a vessel
        without a model is a vessel nobody can choose. MATLAB has a window of
        its own for this (ModelCreator); here it is the button next to the
        vessel it concerns.
        """
        organisms = list_organisms(self.db_path)
        if not organisms or self._current is None:
            return None
        if organism_id is None:
            labels = [row["name"] for row in organisms]
            label, accepted = QInputDialog.getItem(
                self, "Make selectable", "Organism:", labels, 0, False
            )
            if not accepted:
                return None
            organism_id = organisms[labels.index(label)]["organismID"]

        organism = next(row for row in organisms if row["organismID"] == organism_id)
        if name is None:
            suggestion = free_model_name(self.db_path, f"{organism['name']} in {self._current}")
            name, accepted = QInputDialog.getText(
                self, "Make selectable", "Name of the model:", text=suggestion
            )
            if not accepted:
                return None

        try:
            model_id = create_model(
                self.db_path,
                name.strip(),
                organism_id,
                self._bioreactor_id(),
                description=f"{organism['name']} in {self._current}",
            )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Make selectable", str(error))
            return None

        self._select(self._current)
        QMessageBox.information(
            self,
            "Make selectable",
            f"{name} can now be chosen when a new project is created.",
        )
        return model_id

    def _bioreactor_id(self) -> int:
        return next(
            row["bioreactorID"]
            for row in list_bioreactors(self.db_path)
            if row["name"] == self._current
        )

    def delete_selected(self, *, confirmed: bool = False) -> bool:
        if self._current is None:
            return False
        if not confirmed:
            answer = QMessageBox.warning(
                self,
                "Delete bioreactor",
                f"Delete {self._current!r} and its parameter values?\n\n"
                "This cannot be undone.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            delete_bioreactor(self.db_path, self._current)
        except ValueError as error:
            QMessageBox.warning(self, "Delete bioreactor", str(error))
            return False
        self._current = None
        self.refresh()
        return True

    def save(self, *, announce: bool = True) -> bool:
        """Write the form back. A rename is a rename, not a second vessel."""
        definition = self.definition()
        problems = definition.validate()
        if problems:
            QMessageBox.warning(self, "Bioreactor", "\n".join(problems))
            return False

        renamed = self._current is not None and definition.name != self._current
        if renamed and definition.name in {row["name"] for row in list_bioreactors(self.db_path)}:
            QMessageBox.warning(self, "Bioreactor", f"{definition.name!r} already exists.")
            return False

        try:
            if renamed:
                # The values move with the name: write the new one, then drop
                # the old. Refused by the database while anything stands on
                # it, which is the same answer as deleting it outright.
                import_bioreactor(self.db_path, definition)
                delete_bioreactor(self.db_path, self._current)
            else:
                import_bioreactor(self.db_path, definition, replace=True)
        except ValueError as error:
            QMessageBox.warning(self, "Bioreactor", str(error))
            return False

        self.refresh(select=definition.name)
        if announce:
            QMessageBox.information(
                self, "Bioreactor", f"{definition.name} saved. New projects will use these values."
            )
        return True
