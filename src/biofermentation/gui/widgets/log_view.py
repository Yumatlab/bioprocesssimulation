"""The process log (point 8 of the review).

The original keeps a five-column table — datetime, event type, message,
projectID, process time — and shows three of them in a uitable. This widget
keeps the same five fields but reads like a terminal: one line per entry,
monospaced, with the wall-clock time, the process time and the event title
in front of the message.

Entries are held as records, not as text. The view is rebuilt from them
whenever the filter changes, and `entries` is what gets written to logTab.
"""

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

#: Event types and the colour they print in. Chosen against the dark ground
#: the stylesheet gives QTextEdit#logTerminal, not against white.
EVENT_COLORS = {
    "Process": "#6cb6ff",
    "Phase Event": "#5fd08a",
    "Phase Information": "#c3a6ff",
    "Parameter Value Change": "#e5b567",
    "Project": "#9aa0a6",
    "Error": "#ff7b72",
}
DEFAULT_COLOR = "#9aa0a6"

#: The event type the "include parameter updates" switch filters out.
PARAMETER_EVENT = "Parameter Value Change"


@dataclass
class LogEntry:
    """One row of the original's logTable."""

    datetime: str
    event_type: str
    message: str
    process_time: float

    def as_line(self) -> str:
        """Plain text, as it goes into logTab and into an export."""
        return f"{self.datetime}  t={self.process_time:8.3f} h  [{self.event_type}] {self.message}"


class LogView(QWidget):
    """Terminal-style log with a filter, as the Log tab shows it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.entries: list[LogEntry] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.rebuild)
        controls.addWidget(QLabel("Search:"))
        controls.addWidget(self.filter_edit, 1)

        self.parameter_checkbox = QCheckBox("Include parameter updates")
        self.parameter_checkbox.setChecked(True)
        self.parameter_checkbox.toggled.connect(self.rebuild)
        controls.addWidget(self.parameter_checkbox)
        layout.addLayout(controls)

        self.view = QTextEdit()
        self.view.setObjectName("logTerminal")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.view.setFont(QFont(_monospace(), 11))
        layout.addWidget(self.view, 1)

    # ------------------------------------------------------------ write --

    def append(self, message: str, event_type: str = "Process", process_time: float = 0.0):
        """Record an event and, if it passes the filter, print it."""
        entry = LogEntry(
            datetime=datetime.now().strftime("%d.%m.%Y %H:%M:%S.%f")[:-3],
            event_type=event_type,
            message=message,
            process_time=float(process_time),
        )
        self.entries.append(entry)
        if self._passes(entry):
            self._print(entry)
        return entry

    def rebuild(self) -> None:
        """Redraw everything the filter lets through."""
        self.view.clear()
        for entry in self.entries:
            if self._passes(entry):
                self._print(entry)

    def text(self) -> str:
        return "\n".join(entry.as_line() for entry in self.entries)

    # ----------------------------------------------------------- render --

    def _passes(self, entry: LogEntry) -> bool:
        if not self.parameter_checkbox.isChecked() and entry.event_type == PARAMETER_EVENT:
            return False
        needle = self.filter_edit.text().strip().lower()
        if not needle:
            return True
        return needle in f"{entry.event_type} {entry.message}".lower()

    def _print(self, entry: LogEntry) -> None:
        color = EVENT_COLORS.get(entry.event_type, DEFAULT_COLOR)
        line = (
            f'<span style="color:#7e848c;">{_escape(entry.datetime)}</span>'
            f'&nbsp;&nbsp;<span style="color:#7e848c;">t={entry.process_time:8.3f}&nbsp;h</span>'
            f'&nbsp;&nbsp;<span style="color:{color}; font-weight:bold;">'
            f"{_escape(entry.event_type)}</span>"
            f'&nbsp;&nbsp;<span style="color:#d6d6d6;">{_escape(entry.message)}</span>'
        )
        self.view.append(line)
        # Follow the tail, the way a terminal does.
        self.view.moveCursor(QTextCursor.MoveOperation.End)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())


def _escape(text: str) -> str:
    import html

    return html.escape(str(text)).replace(" ", "&nbsp;")


def _monospace() -> str:
    """A fixed-pitch family Qt will actually find, on either platform."""
    from PySide6.QtGui import QFontDatabase

    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    return font.family()


__all__ = ["EVENT_COLORS", "LogEntry", "LogView"]
