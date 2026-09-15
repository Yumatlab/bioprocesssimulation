"""Managing plot templates (point 5 of the review).

Follows FigureAppTemplateManager.mlapp: a list of templates on the left, what
one contains on the right, and the four things one does with them — select,
create, delete, reset to default.

Two things the original does not do, and one it does that is kept:

  * A new template can be made **from the plot as it stands**, not only as a
    copy of the first template in the table. That is what "I have arranged
    this figure and want to keep it" actually needs.
  * The contents are shown with the colours and line styles themselves, not
    as a list of names — a template is a look, and a list of ids is not one.
  * The default template cannot be deleted. Here it cannot be overwritten
    either: it is the only way back to a known state, and
    default_plot_variableTab is the only thing holding its variable rows.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...db.plots import (
    DEFAULT_TEMPLATE_ID,
    ProtectedTemplateError,
    create_template,
    delete_template,
    list_plot_templates,
    load_plot_template,
    reset_template_variables,
    save_plot_template,
)
from ..widgets.tex import tex_label

#: What the contents table shows per variable.
COLUMNS = ("Variable", "Axis", "Min", "Max", "Decimals", "Colour", "Line")


class TemplateManager(QDialog):
    """The list, what is in the selected one, and the four actions."""

    def __init__(self, db_path: Path | str, current, styles: dict, parent=None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        #: The template the figure window is showing, so it can be saved as-is.
        self.current = current
        self.styles = styles
        #: Set when the user picks one; the caller loads it.
        self.selected_id: int | None = None

        self.setWindowTitle("Plot Templates")
        self.resize(900, 560)

        layout = QHBoxLayout(self)
        layout.addWidget(self._build_list(), 0)
        layout.addWidget(self._build_details(), 1)

        self.refresh()

    # ------------------------------------------------------------ build --

    def _build_list(self) -> QWidget:
        box = QGroupBox("Templates")
        box.setFixedWidth(260)
        layout = QVBoxLayout(box)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        self.list.itemDoubleClicked.connect(lambda *_: self.select())
        layout.addWidget(self.list, 1)

        for text, slot, tip in (
            ("Save current plot as…", self.save_as_new, "Keep the figure as it stands"),
            ("Duplicate", self.duplicate, "A copy of the selected template"),
            ("Reset to default", self.reset, "Back to default_plot_variableTab"),
            ("Delete", self.delete, "Remove the selected template"),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            layout.addWidget(button)
            setattr(self, f"{slot.__name__}_button", button)
        return box

    def _build_details(self) -> QWidget:
        box = QGroupBox("Contents")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._rename)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(56)
        self.description_edit.focusOutEvent = self._description_left
        form.addRow("Name:", self.name_edit)
        form.addRow("Description:", self.description_edit)
        layout.addLayout(form)

        self.protected_note = QLabel(
            "The default template is read only. It is the way back to a known "
            "state — save a copy to keep your own arrangement."
        )
        self.protected_note.setWordWrap(True)
        self.protected_note.setStyleSheet("color: #a06000;")
        layout.addWidget(self.protected_note)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        header = self.table.horizontalHeader()
        # The variable column holds rendered labels with sub- and superscripts;
        # stretching it squeezed them into the header.
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 150)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.select_button = buttons.addButton(
            "Use this template", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.select_button.clicked.connect(self.select)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        return box

    # ------------------------------------------------------------ state --

    def refresh(self, keep: int | None = None) -> None:
        wanted = keep if keep is not None else self.template_id()
        self.list.blockSignals(True)
        self.list.clear()
        for entry in list_plot_templates(self.db_path):
            item = QListWidgetItem(entry["name"] or "unnamed")
            item.setData(Qt.ItemDataRole.UserRole, entry["templateID"])
            item.setToolTip(entry.get("description") or "")
            if entry["templateID"] == DEFAULT_TEMPLATE_ID:
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
                item.setToolTip("The default template — read only")
            self.list.addItem(item)
        self.list.blockSignals(False)

        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == wanted:
                self.list.setCurrentRow(row)
                break
        else:
            self.list.setCurrentRow(0)
        self._show_selected()

    def template_id(self) -> int | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_selected(self) -> None:
        template_id = self.template_id()
        if template_id is None:
            return
        template = load_plot_template(self.db_path, template_id)
        protected = template_id == DEFAULT_TEMPLATE_ID

        self.name_edit.setText(template.name or "")
        self.description_edit.setPlainText(template.description or "")
        self.name_edit.setReadOnly(protected)
        self.description_edit.setReadOnly(protected)
        self.protected_note.setVisible(protected)
        self.delete_button.setEnabled(not protected)

        selected = template.selected()
        # Emptied first: setCellWidget hands the old widget to deleteLater, so
        # simply overwriting a row leaves the previous label painted on top of
        # the new one until the event loop gets round to it.
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(selected))
        for row, variable in enumerate(selected):
            self._fill_row(row, variable)

    def _fill_row(self, row: int, variable) -> None:
        by_color = {entry["colorID"]: entry for entry in self.styles["colors"]}
        by_style = {entry["linestyleID"]: entry for entry in self.styles["linestyles"]}
        color = by_color.get(variable.colorID, {})

        label = QLabel(tex_label(variable.shorttex or variable.name, variable.tex_unit))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setContentsMargins(6, 0, 6, 0)
        label.setToolTip(variable.name)
        self.table.setCellWidget(row, 0, label)
        self.table.setRowHeight(row, 26)

        cells = (
            "auto" if variable.auto_limits else "fixed",
            f"{variable.ymin:g}",
            f"{variable.ymax:g}",
            variable.decimal,
            color.get("color_name", str(variable.colorID)),
            by_style.get(variable.linestyleID, {}).get("linestyle_symbol", "-"),
        )
        for column, text in enumerate(cells, start=1):
            item = QTableWidgetItem(str(text))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if column == 5 and color.get("rgb"):
                from ..dialogs.plot_settings import color_icon

                item.setIcon(color_icon(color["rgb"]))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, column, item)

    # ---------------------------------------------------------- actions --

    def save_as_new(self) -> None:
        """The figure as it stands, under a new name."""
        name, chosen = QInputDialog.getText(
            self, "Save current plot", "Name:", text=f"{self.current.name} (copy)"
        )
        if not chosen or not name.strip():
            return
        template_id = create_template(
            self.db_path,
            name.strip(),
            based_on=self.current.templateID,
            description=self.current.description or "",
            variables=self.current.variables,
        )
        self.refresh(keep=template_id)

    def duplicate(self) -> None:
        template_id = self.template_id()
        if template_id is None:
            return
        source = load_plot_template(self.db_path, template_id)
        name, chosen = QInputDialog.getText(
            self, "Duplicate template", "Name:", text=f"{source.name} (copy)"
        )
        if not chosen or not name.strip():
            return
        new_id = create_template(
            self.db_path,
            name.strip(),
            based_on=template_id,
            description=source.description or "",
        )
        self.refresh(keep=new_id)

    def reset(self) -> None:
        template_id = self.template_id()
        if template_id is None:
            return
        name = self.name_edit.text()
        answer = QMessageBox.question(
            self,
            "Reset to default",
            f"Put the variables of {name!r} back to the default settings?\n\n"
            "Selection, limits, colours, line styles and decimals are all "
            "taken from default_plot_variableTab.",
            QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Reset:
            return
        changed = reset_template_variables(self.db_path, template_id)
        self._show_selected()
        QMessageBox.information(self, "Reset to default", f"{changed} variables of {name!r} reset.")

    def delete(self) -> None:
        template_id = self.template_id()
        if template_id is None:
            return
        name = self.name_edit.text()
        answer = QMessageBox.question(
            self,
            "Delete template",
            f"Delete the template {name!r}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_template(self.db_path, template_id)
        except ProtectedTemplateError as error:
            QMessageBox.warning(self, "Delete template", str(error))
            return
        self.refresh(keep=DEFAULT_TEMPLATE_ID)

    def select(self) -> None:
        self.selected_id = self.template_id()
        self.accept()

    # ------------------------------------------------------------ edits --

    def _rename(self) -> None:
        self._write_text(name=self.name_edit.text().strip())

    def _description_left(self, event) -> None:
        QPlainTextEdit.focusOutEvent(self.description_edit, event)
        self._write_text(description=self.description_edit.toPlainText())

    def _write_text(self, **fields) -> None:
        """Name and description are the only things edited in place here."""
        template_id = self.template_id()
        if template_id is None or template_id == DEFAULT_TEMPLATE_ID:
            return
        template = load_plot_template(self.db_path, template_id)
        changed = False
        for key, value in fields.items():
            if value and getattr(template, key) != value:
                setattr(template, key, value)
                changed = True
        if not changed:
            return
        save_plot_template(self.db_path, template)
        self.refresh(keep=template_id)
