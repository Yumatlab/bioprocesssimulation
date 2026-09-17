"""Managing models — an organism in a vessel.

The third dialog of this shape, and the one the other two have been pointing
at: a project is created from a **model**, and `create_project` reads nothing
but `model_parameterTab`. Until now a model could only be made in passing,
through "Make selectable…" next to an organism or a bioreactor, and once made
there was no way to look at one, rename it, correct a value or remove it. This
is that place.

Three things this dialog does not offer, each for a reason:

  * **The organism and the vessel cannot be swapped.** They are not two more
    fields of a model, they are what it is made of: the parameter set was
    copied from them when it was built, and a swap would leave values from a
    vessel the model no longer names. A different pairing is a different
    model.
  * **Parameters cannot be added or removed.** Which parameters a model
    carries is what the organism and the vessel between them decide. A form
    that let somebody add one would be offering to build a model that does not
    match either side.
  * **A change does not reach existing projects.** A project copies the values
    when it is created and keeps its own from then on — two layers of copy,
    and both are what make a stored run reproducible. The dialog says so on
    the front, because everybody expects it the other way round once.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...db.bioreactors import list_bioreactors
from ...db.definitions import list_organisms
from ...db.project import (
    create_model,
    delete_model,
    duplicate_model,
    free_model_name,
    list_models,
    model_parameters,
    model_usage,
    save_model_parameters,
    update_model,
)
from ..widgets.tex import rich_label, tex_label
from .parameters import decimals_for

#: The list item carries the modelID. The name is unique in the database, but
#: it is also the thing this dialog renames, and a selection that survives a
#: rename has to hang on something that does not change.
MODEL_ID = Qt.ItemDataRole.UserRole


class NewModelDialog(QDialog):
    """Organism, vessel, name — the three things a model needs.

    Two QInputDialogs in a row would ask the same questions, but the name is
    made out of the other two answers, and a suggestion that cannot see them
    is not a suggestion.
    """

    def __init__(self, organisms: list[dict], bioreactors: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("New model")
        self.setMinimumWidth(420)
        self._organisms = organisms
        self._bioreactors = bioreactors
        # True while the name is ours; a name somebody typed is never
        # overwritten by the next change of a dropdown.
        self._name_is_suggested = True

        layout = QVBoxLayout(self)
        note = QLabel(
            "A model is an organism in a vessel. It is what a project is "
            "created from, and it carries the parameter values of both — the "
            "vessel wins where they name the same parameter."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.organism_box = QComboBox()
        for row in organisms:
            self.organism_box.addItem(row["name"], row["organismID"])
        self.bioreactor_box = QComboBox()
        for row in bioreactors:
            self.bioreactor_box.addItem(row["name"], row["bioreactorID"])
        self.name_edit = QLineEdit()
        form.addRow("Organism:", self.organism_box)
        form.addRow("Bioreactor:", self.bioreactor_box)
        form.addRow("Name:", self.name_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.organism_box.currentIndexChanged.connect(self._suggest_name)
        self.bioreactor_box.currentIndexChanged.connect(self._suggest_name)
        self.name_edit.textEdited.connect(self._name_was_typed)
        self._suggest_name()

    def _name_was_typed(self, _text: str) -> None:
        self._name_is_suggested = False

    def _suggest_name(self) -> None:
        if not self._name_is_suggested:
            return
        organism = self.organism_box.currentText()
        vessel = self.bioreactor_box.currentText()
        if organism and vessel:
            self.name_edit.setText(f"{organism} in {vessel}")

    def choice(self) -> tuple[int, int, str]:
        """Organism id, bioreactor id and the name, as the boxes stand."""
        return (
            self.organism_box.currentData(),
            self.bioreactor_box.currentData(),
            self.name_edit.text().strip(),
        )


class ModelManager(QDialog):
    """The models of this database, and the values one is made of."""

    def __init__(self, db_path: Path | str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Models")
        self.resize(900, 680)
        self.db_path = Path(db_path)
        self._boxes: dict[str, QDoubleSpinBox] = {}
        self._rows: list[tuple[QGroupBox, QWidget, QWidget, str]] = []
        self._current: int | None = None

        layout = QVBoxLayout(self)
        note = QLabel(
            "A model is an <b>organism in a vessel</b> — it is what a project "
            "is created from. Changes here reach <b>new projects</b>: a project "
            "copies the values when it is created and keeps its own from then "
            "on, which is what makes a stored run reproducible."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        body = QHBoxLayout()
        layout.addLayout(body, 1)

        # ------------------------------------------------------ the list --
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._item_selected)
        left.addWidget(self.list, 1)
        self.new_button = QPushButton("New model…")
        self.new_button.setToolTip("Pair an organism with a bioreactor")
        self.copy_button = QPushButton("Duplicate…")
        self.copy_button.setToolTip("A copy with the values as they are now, edited ones included")
        self.delete_button = QPushButton("Delete…")
        self.new_button.clicked.connect(lambda: self.create_model())
        self.copy_button.clicked.connect(lambda: self.duplicate_selected())
        self.delete_button.clicked.connect(lambda: self.delete_selected())
        left.addWidget(self.new_button)
        left.addWidget(self.copy_button)
        left.addWidget(self.delete_button)
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(250)
        body.addWidget(holder)

        # ----------------------------------------------------- the model --
        right = QVBoxLayout()
        head = QFormLayout()
        self.name_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.organism_label = QLabel()
        self.bioreactor_label = QLabel()
        pairing = (
            "What a model is made of. A different pairing is a different "
            "model — the parameter values were copied from these two."
        )
        self.organism_label.setToolTip(pairing)
        self.bioreactor_label.setToolTip(pairing)
        head.addRow("Name:", self.name_edit)
        head.addRow("Description:", self.description_edit)
        head.addRow("Organism:", self.organism_label)
        head.addRow("Bioreactor:", self.bioreactor_label)
        right.addLayout(head)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter parameters by name, symbol, category or text …")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        right.addWidget(self.filter_edit)

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

    def models(self) -> list[dict]:
        return list_models(self.db_path)

    def refresh(self, select: int | None = None) -> None:
        """Reread the list. `select` is the modelID to land on afterwards."""
        wanted = select if select is not None else self._current
        self.list.blockSignals(True)
        self.list.clear()
        rows = self.models()
        for row in rows:
            item = QListWidgetItem(row["name"])
            item.setData(MODEL_ID, row["modelID"])
            item.setToolTip(
                f"{row['organism_name'] or '<missing organism>'} in "
                f"{row['bioreactor_name'] or '<missing bioreactor>'} — "
                f"{row['parameters']} parameters"
            )
            self.list.addItem(item)
        self.list.blockSignals(False)

        ids = [row["modelID"] for row in rows]
        if ids:
            self.list.setCurrentRow(ids.index(wanted) if wanted in ids else 0)
            self._select(self.list.currentItem().data(MODEL_ID))
        else:
            self._current = None
            self._clear()

    def _item_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is not None:
            self._select(current.data(MODEL_ID))

    def _clear(self) -> None:
        """No models at all — a database can be in that state."""
        self.name_edit.clear()
        self.description_edit.clear()
        self.organism_label.clear()
        self.bioreactor_label.clear()
        self.area.setWidget(QWidget())
        self._boxes, self._rows = {}, []
        self.usage_label.setText("This database has no models yet.")
        for button in (self.copy_button, self.delete_button, self.save_button):
            button.setEnabled(False)

    def _select(self, model_id: int) -> None:
        model = next((row for row in self.models() if row["modelID"] == model_id), None)
        if model is None:
            return
        self._current = model_id
        for button in (self.copy_button, self.save_button):
            button.setEnabled(True)
        self.name_edit.setText(model["name"])
        self.description_edit.setText(model["description"] or "")
        self.organism_label.setText(model["organism_name"] or "<missing>")
        self.bioreactor_label.setText(model["bioreactor_name"] or "<missing>")
        self._build_form(model_parameters(self.db_path, model_id))
        self._apply_filter(self.filter_edit.text())

        projects = model_usage(self.db_path, model_id)["projects"]
        self.usage_label.setText(
            f"{len(self._boxes)} parameters — used by {projects} project(s), "
            "which keep their own copy of these values."
            if projects
            else f"{len(self._boxes)} parameters — used by no project, safe to delete."
        )
        self.delete_button.setEnabled(not projects)
        self.delete_button.setToolTip(
            "" if not projects else "A model a project was created from cannot be deleted."
        )

    def _build_form(self, rows: list[dict]) -> None:
        """One group per category, one field per parameter."""
        self._boxes, self._rows = {}, []
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
            # Where the value came from is the one thing a model adds over the
            # two sets it was built out of.
            box.setToolTip(
                f"{row['parametername']} — from the {row['origin']}\n"
                f"{row['description'] or ''}".strip()
            )
            self._boxes[row["parametername"]] = box
            label = rich_label(tex_label(row["tex"] or row["parametername"], row["unit"]))
            label.setToolTip(box.toolTip())
            form.addRow(label, box)
            self._rows.append(
                (
                    group,
                    label,
                    box,
                    " ".join(
                        str(part or "")
                        for part in (
                            row["parametername"],
                            row["tex"],
                            row["categoryname"],
                            row["description"],
                            title,
                        )
                    ).casefold(),
                )
            )

        column.addStretch()
        self.area.setWidget(inner)

    def _apply_filter(self, text: str) -> None:
        """Hide what does not match, and any group left with nothing in it.

        A model carries around 250 parameters — four times what a vessel has.
        Scrolling for one of them is the difference between a dialog that is
        used and one that is opened once.
        """
        needle = text.strip().casefold()
        shown: dict[QGroupBox, int] = {}
        for group, label, box, haystack in self._rows:
            matches = not needle or needle in haystack
            label.setVisible(matches)
            box.setVisible(matches)
            shown[group] = shown.get(group, 0) + (1 if matches else 0)
        for group, count in shown.items():
            group.setVisible(bool(count))

    # ---------------------------------------------------------- actions --

    def create_model(
        self,
        organism_id: int | None = None,
        bioreactor_id: int | None = None,
        name: str | None = None,
    ) -> int | None:
        """Pair an organism with a vessel. The arguments are for tests."""
        organisms = list_organisms(self.db_path)
        bioreactors = list_bioreactors(self.db_path)
        if not organisms or not bioreactors:
            QMessageBox.warning(
                self,
                "New model",
                "A model needs an organism and a bioreactor; this database has "
                f"{len(organisms)} organism(s) and {len(bioreactors)} bioreactor(s).",
            )
            return None

        if organism_id is None or bioreactor_id is None or name is None:
            dialog = NewModelDialog(organisms, bioreactors, parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            organism_id, bioreactor_id, name = dialog.choice()

        organism = next(row for row in organisms if row["organismID"] == organism_id)
        vessel = next(row for row in bioreactors if row["bioreactorID"] == bioreactor_id)
        try:
            model_id = create_model(
                self.db_path,
                free_model_name(self.db_path, name),
                organism_id,
                bioreactor_id,
                description=f"{organism['name']} in {vessel['name']}",
            )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "New model", str(error))
            return None

        self.refresh(select=model_id)
        return model_id

    def duplicate_selected(self, name: str | None = None) -> int | None:
        """A copy of this model, values as they stand."""
        if self._current is None:
            return None
        current = next(row for row in self.models() if row["modelID"] == self._current)
        if name is None:
            suggestion = free_model_name(self.db_path, f"{current['name']} (copy)")
            name, accepted = QInputDialog.getText(
                self, "Duplicate model", "Name of the new model:", text=suggestion
            )
            if not accepted:
                return None
        try:
            model_id = duplicate_model(self.db_path, self._current, name)
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Duplicate model", str(error))
            return None
        self.refresh(select=model_id)
        return model_id

    def delete_selected(self, *, confirmed: bool = False) -> bool:
        if self._current is None:
            return False
        current = next(row for row in self.models() if row["modelID"] == self._current)
        if not confirmed:
            answer = QMessageBox.warning(
                self,
                "Delete model",
                f"Delete the model {current['name']!r} and its "
                f"{current['parameters']} parameter values?\n\n"
                "The organism and the bioreactor stay. This cannot be undone.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            delete_model(self.db_path, self._current)
        except ValueError as error:
            QMessageBox.warning(self, "Delete model", str(error))
            return False
        self._current = None
        self.refresh()
        return True

    def save(self, *, announce: bool = True) -> bool:
        """Name, description and the values. A rename is a rename."""
        if self._current is None:
            return False
        try:
            update_model(
                self.db_path,
                self._current,
                name=self.name_edit.text(),
                description=self.description_edit.text(),
            )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Model", str(error))
            return False

        result = save_model_parameters(
            self.db_path,
            self._current,
            {name: box.value() for name, box in self._boxes.items()},
        )
        self.refresh(select=self._current)
        if announce:
            QMessageBox.information(
                self,
                "Model",
                f"{self.name_edit.text().strip()} saved — {result['parameters']} "
                "parameter values.\n\nNew projects will use them; projects that "
                "already exist keep their own copy.",
            )
        return True


__all__ = ["MODEL_ID", "ModelManager", "NewModelDialog"]
