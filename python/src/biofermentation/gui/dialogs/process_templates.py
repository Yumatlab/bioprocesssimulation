"""Saving and loading process templates — Projektplan_Prozessvorlagen.md, phases 3 and 4.

SaveTemplateDialog only collects: a name, a description, an author, and shows
what will be stored. LoadTemplateDialog lists the templates of the model,
shows one, and renames or deletes on request — the only two things it writes
itself. What is loaded, how it is placed and what the log says are the
window's (ControlWindow.save_process_template / load_process_template), so
that the dialogs can be tested on their own and the window without a modal
dialog.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...control import PHASE_PARAMETERS, PhaseType
from ...db.models import Phase
from ...db.process_templates import (
    TemplateExistsError,
    delete_process_template,
    is_result_parameter,
    list_process_templates,
    load_process_template,
    rename_process_template,
)


def feed_settings_missing(phase: Phase) -> bool:
    """A feed phase that leaves its settings to the project (finding P0-2).

    A pulse or exponential feed works from the parameters in PHASE_PARAMETERS
    for its reservoir. Whatever the phase does not carry itself, it takes from
    the project's parameter set when it starts — so a template carries only
    what the phase holds, and loading it elsewhere uses that project's values.
    """
    if phase.typeID not in PHASE_PARAMETERS:
        return False
    n = phase.reservoirID or 1
    wanted = {name.replace("{n}", str(n)) for name in PHASE_PARAMETERS[phase.typeID]}
    own = {name for name in phase.parameters if not is_result_parameter(name)}
    return not (wanted & own)


def describe_phase(number: int, phase: Phase, types: dict[int, str]) -> str:
    """One line of the list: number, name, type and what it carries."""
    kind = types.get(phase.typeID, f"type {phase.typeID}")
    line = f"{number}. {phase.name or 'unnamed'} — {kind}"
    if phase.typeID in (PhaseType.PULSE_FEED, PhaseType.EXPONENTIAL_FEED):
        line += f", reservoir {phase.reservoirID or 1}"
    kept = sorted(name for name in phase.parameters if not is_result_parameter(name))
    if kept:
        line += f" ({', '.join(kept)})"
    if feed_settings_missing(phase):
        line += " — feed settings from the project it is loaded into"
    return line


class SaveTemplateDialog(QDialog):
    """Name, description and author for a new process template."""

    def __init__(
        self,
        phases: list[Phase],
        types: dict[int, str],
        *,
        model_name: str = "",
        author: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Save process as template")
        self.setMinimumWidth(520)
        column = QVBoxLayout(self)

        heading = QLabel(
            f"<b>Store these {len(phases)} phases under a name.</b> The template belongs "
            f"to the model{f' {model_name!r}' if model_name else ''}: any project of "
            "this model can load it later. Phases are stored as a plan — no status, "
            "no times, and none of the values a feed wrote when it ran."
        )
        heading.setWordWrap(True)
        column.addWidget(heading)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Standard fed-batch")
        form.addRow("Name", self.name_edit)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText("What the process is for, what to watch out for")
        self.description_edit.setFixedHeight(80)
        form.addRow("Description", self.description_edit)
        self.author_edit = QLineEdit(author or "")
        form.addRow("Author", self.author_edit)
        column.addLayout(form)

        column.addWidget(QLabel("Phases"))
        self.phase_list = QListWidget()
        self.phase_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.phase_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        # Long lines wrap: the note on a feed phase is the part worth reading,
        # and behind a horizontal scroll bar nobody reads it.
        self.phase_list.setWordWrap(True)
        self.phase_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for number, phase in enumerate(phases, start=1):
            self.phase_list.addItem(describe_phase(number, phase, types))
        column.addWidget(self.phase_list)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        column.addWidget(self.buttons)

        self.name_edit.textChanged.connect(self._update_save_button)
        self._update_save_button()

    def _update_save_button(self) -> None:
        self.save_button.setEnabled(bool(self.name_edit.text().strip()))

    def values(self) -> dict[str, str]:
        return {
            "name": self.name_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "author": self.author_edit.text().strip(),
        }


class LoadTemplateDialog(QDialog):
    """The templates of one model: pick one, or rename or delete it."""

    def __init__(
        self,
        db_path: Path | str,
        model_id: int,
        types: dict[int, str],
        *,
        model_name: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.db_path = db_path
        self.model_id = model_id
        self.types = types
        self.setWindowTitle("Load process template")
        self.setMinimumSize(720, 420)

        column = QVBoxLayout(self)
        heading = QLabel(
            f"<b>Process templates of the model{f' {model_name!r}' if model_name else ''}.</b> "
            "Loading asks next whether the template follows the existing phases "
            "or replaces those that have not started."
        )
        heading.setWordWrap(True)
        column.addWidget(heading)

        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(240)
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        row.addWidget(self.list)

        detail = QVBoxLayout()
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        detail.addWidget(self.description_label)
        self.meta_label = QLabel()
        self.meta_label.setStyleSheet("color: #6a6a6a;")
        detail.addWidget(self.meta_label)
        self.preview = QListWidget()
        self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.preview.setWordWrap(True)
        self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail.addWidget(self.preview)
        row.addLayout(detail, 1)
        column.addLayout(row, 1)

        self.buttons = QDialogButtonBox()
        self.load_button = QPushButton("Load…")
        self.rename_button = QPushButton("Rename…")
        self.delete_button = QPushButton("Delete")
        self.buttons.addButton(self.load_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.rename_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.load_button.clicked.connect(self.accept)
        self.rename_button.clicked.connect(lambda _=False: self.ask_rename())
        self.delete_button.clicked.connect(lambda _=False: self.delete_selected())
        self.buttons.rejected.connect(self.reject)
        column.addWidget(self.buttons)

        self.refresh()

    # ---------------------------------------------------------- content --

    def refresh(self, select: int | None = None) -> None:
        self.list.clear()
        for row in list_process_templates(self.db_path, self.model_id):
            item = QListWidgetItem(row["name"])
            item.setData(Qt.ItemDataRole.UserRole, row["templateID"])
            self.list.addItem(item)
            if row["templateID"] == select:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show_selected()

    def selected_template_id(self) -> int | None:
        item = self.list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _show_selected(self) -> None:
        template_id = self.selected_template_id()
        for button in (self.load_button, self.rename_button, self.delete_button):
            button.setEnabled(template_id is not None)
        self.preview.clear()
        if template_id is None:
            self.description_label.setText("This model has no process templates yet.")
            self.meta_label.setText("")
            return
        template = load_process_template(self.db_path, template_id)
        self.description_label.setText(template.description or "<i>No description.</i>")
        made = " · ".join(part for part in (template.author, template.created_on) if part)
        self.meta_label.setText(f"{len(template.phases)} phases" + (f" · {made}" if made else ""))
        for number, phase in enumerate(template.phases, start=1):
            self.preview.addItem(describe_phase(number, phase, self.types))

    # ---------------------------------------------- rename and delete --

    def ask_rename(self) -> bool:
        template_id = self.selected_template_id()
        if template_id is None:
            return False
        current = self.list.currentItem().text()
        name, ok = QInputDialog.getText(self, "Rename process template", "Name", text=current)
        return ok and self.rename(template_id, name)

    def rename(self, template_id: int, name: str) -> bool:
        try:
            rename_process_template(self.db_path, template_id, name)
        except (TemplateExistsError, ValueError) as error:
            QMessageBox.warning(self, "Rename process template", str(error))
            return False
        self.refresh(select=template_id)
        return True

    def delete_selected(self, *, confirmed: bool = False) -> bool:
        template_id = self.selected_template_id()
        if template_id is None:
            return False
        name = self.list.currentItem().text()
        if not confirmed:
            answer = QMessageBox.warning(
                self,
                "Delete process template",
                f"Delete the process template {name!r}?\n\n"
                "Projects that loaded it keep their phases. This cannot be undone.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        delete_process_template(self.db_path, template_id)
        self.refresh()
        return True


__all__ = ["LoadTemplateDialog", "SaveTemplateDialog", "describe_phase", "feed_settings_missing"]
