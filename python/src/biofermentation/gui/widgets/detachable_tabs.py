"""A tab widget whose pages can be taken out into a window of their own.

Two screens, or one wide one: the flow sheet beside the panels, the Variable
Pool beside a plot. A tab is detached from the context menu of its tab or by
a double click on it. Its page then lives in its own window; the tab stays
where it was and shows a button that brings the page back. Closing the window
does the same.

**The page is moved, never copied.** Every page of the control window keeps
its state in its widgets — a half-typed setpoint, the scroll position of the
log, which valve is locked — so there is exactly one of each, and it is
re-parented with its state intact.

Tabs are named by their title, as `ControlWindow.pages` names them.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QMenu,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

#: Shown on the tab bar.
DETACH_HINT = "Double-click or right-click a tab to show it in its own window"


class DetachedWindow(QWidget):
    """The window a detached page lives in. Closing it brings the page back."""

    closing = Signal()

    def __init__(self, page: QWidget, title: str):
        super().__init__()
        self.setWindowTitle(title)
        column = QVBoxLayout(self)
        # No margins: the window asks for no more room than the page does.
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(page)
        # Ctrl+W / Cmd+W, as in any window: the page goes back to its tab.
        QShortcut(QKeySequence(QKeySequence.StandardKey.Close), self, self.close)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)


class DetachableTabs(QTabWidget):
    """A QTabWidget with `detach(title)` and `attach(title)`."""

    #: A page went out or came back. The owner redraws what is now visible.
    detached_changed = Signal()

    def __init__(self, owner_name: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        #: Written behind the tab's name in the title of a detached window.
        self.owner_name = owner_name
        #: Per detached tab: its page, the placeholder in its place, its window.
        self._detached: dict[str, tuple[QWidget, QWidget, DetachedWindow]] = {}

        bar = self.tabBar()
        # The only place that says it can be done: neither gesture is visible.
        bar.setToolTip(DETACH_HINT)
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._show_menu)
        self.tabBarDoubleClicked.connect(self._toggle)

    # ------------------------------------------------------------ asking --

    def index_of(self, title: str) -> int:
        """The index of the tab with this title, or -1 if it is not shown."""
        for index in range(self.count()):
            if self.tabText(index) == title:
                return index
        return -1

    def is_detached(self, title: str) -> bool:
        return title in self._detached

    def detached_window(self, title: str) -> DetachedWindow | None:
        entry = self._detached.get(title)
        return entry[2] if entry else None

    def visible_pages(self) -> list[QWidget]:
        """What the operator can see: the front tab and every detached page."""
        pages = [page for page, _, _ in self._detached.values()]
        current = self.currentWidget()
        if current is not None:
            pages.append(current)
        return pages

    # ------------------------------------------------------------ moving --

    def detach(self, title: str) -> bool:
        """Move the page of this tab into its own window. False if it cannot."""
        index = self.index_of(title)
        if index < 0 or title in self._detached:
            return False
        page = self.widget(index)
        size = page.size()
        was_current = self.currentIndex() == index

        placeholder = self._placeholder(title)
        self.removeTab(index)
        self.insertTab(index, placeholder, title)
        if was_current:
            self.setCurrentIndex(index)

        name = f"{title} — {self.owner_name}" if self.owner_name else title
        window = DetachedWindow(page, name)
        window.closing.connect(lambda: self.attach(title))
        self._detached[title] = (page, placeholder, window)
        # removeTab hid the page; in its new window it is to be seen again.
        page.show()
        window.resize(size)
        window.show()
        self.detached_changed.emit()
        return True

    def attach(self, title: str) -> bool:
        """Bring the page back to the index its tab has. False if it is in."""
        entry = self._detached.pop(title, None)
        if entry is None:
            return False
        page, placeholder, window = entry
        index = self.indexOf(placeholder)
        was_current = self.currentIndex() == index
        self.removeTab(index)
        # insertTab re-parents the page out of the window's layout.
        self.insertTab(index, page, title)
        if was_current:
            self.setCurrentIndex(index)
        placeholder.deleteLater()
        # The entry is gone, so the window's closing signal finds nothing to
        # do — whether this was called by it or is closing it now.
        window.close()
        window.deleteLater()
        self.detached_changed.emit()
        return True

    def attach_all(self) -> None:
        """Bring every page back: before the owner closes, nothing is lost."""
        for title in list(self._detached):
            self.attach(title)

    def reveal(self, page: QWidget) -> None:
        """Show this page: its tab in front, or its window if it is out."""
        for held, _, window in self._detached.values():
            if held is page:
                window.raise_()
                window.activateWindow()
                return
        self.setCurrentWidget(page)

    # ---------------------------------------------------------- operating --

    def _placeholder(self, title: str) -> QWidget:
        """What the tab shows while its page is out: one sentence, one button."""
        placeholder = QWidget()
        # Painted like every other page of the tab widget (default.qss).
        placeholder.setObjectName("tabPage")
        placeholder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column = QVBoxLayout(placeholder)
        column.addStretch(1)
        note = QLabel(f"{title} is shown in its own window.")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(note)
        button = QPushButton("Bring back")
        button.setObjectName("bringBack")
        button.clicked.connect(lambda _=False: self.attach(title))
        column.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        return placeholder

    def _toggle(self, index: int) -> None:
        """A double click on a tab: out if it is in, back if it is out."""
        if index < 0:
            return
        title = self.tabText(index)
        if not self.attach(title):
            self.detach(title)

    def _show_menu(self, position) -> None:
        bar = self.tabBar()
        index = bar.tabAt(position)
        if index < 0:
            return
        title = self.tabText(index)
        menu = QMenu(self)
        if self.is_detached(title):
            menu.addAction("Bring back", lambda: self.attach(title))
        else:
            menu.addAction("Detach", lambda: self.detach(title))
        menu.exec(bar.mapToGlobal(position))


__all__ = ["DETACH_HINT", "DetachableTabs", "DetachedWindow"]
