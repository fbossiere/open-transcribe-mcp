"""Shared native widgets.

Status is never carried by colour alone, every control has an accessible name, and changes that
matter are announced so a screen reader user hears them.
"""

from collections.abc import Callable
from typing import override

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAccessible, QAccessibleEvent, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

SEVERITY_MARK = {
    "ok": "✓",
    "info": "•",
    "warning": "!",
    "error": "✕",
}
"""A textual mark accompanies every status, so red and green are never the only difference."""


def announce(widget: QWidget, message: str) -> None:
    """Tell assistive technology that something the user needs to know has changed."""
    widget.setAccessibleDescription(message)
    QAccessible.updateAccessibility(QAccessibleEvent(widget, QAccessible.Event.Alert))


class WrappedLabel(QLabel):
    """A paragraph that wraps to the width it is given and grows to the height it needs."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setWordWrap(True)

    @override
    def minimumSizeHint(self) -> QSize:
        # A paragraph must be free to wrap to the available width. Its preferred unbroken width
        # is not a minimum, and must never widen the page it sits on.
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    @override
    def setText(self, text: str) -> None:
        super().setText(text)
        self._fit_height()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_height()

    def _fit_height(self) -> None:
        # Qt's default minimum would let a wrapped label shrink to one line and clip the rest.
        # Inside a scroll area there is no reason to crop: let the page grow instead.
        self.setMinimumHeight(max(0, self.heightForWidth(self.width())))


class FormScrollArea(QScrollArea):
    """Bring the whole focused control into view, not just its text cursor."""

    @override
    def ensureWidgetVisible(
        self,
        childWidget: QWidget,
        xmargin: int = 50,
        ymargin: int = 50,
    ) -> None:
        super().ensureWidgetVisible(childWidget, xmargin, ymargin)
        page = self.widget()
        if page is None or not page.isAncestorOf(childWidget):
            return
        viewport = self.viewport()
        bounds = QRect(childWidget.mapTo(viewport, QPoint()), childWidget.size())
        if bounds.height() > viewport.height():
            return
        padding = min(ymargin, (viewport.height() - bounds.height()) // 2)
        bar = self.verticalScrollBar()
        if bounds.top() < 0:
            bar.setValue(bar.value() + bounds.top() - padding)
        elif bounds.bottom() >= viewport.height():
            bar.setValue(bar.value() + bounds.bottom() - viewport.height() + 1 + padding)

    @override
    def focusNextPrevChild(self, next: bool) -> bool:
        moved = super().focusNextPrevChild(next)
        focused = self.focusWidget()
        if moved and focused is not None and focused.hasFocus():
            self.ensureWidgetVisible(focused)
        return moved


class PageStack(QStackedWidget):
    """A stack that asks for the size of the page on show, not of the tallest page it holds.

    A stacked widget reserves room for every page at once, which would leave a short step
    scrolling inside the height the longest step needs.
    """

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(lambda _: self.updateGeometry())

    @override
    def sizeHint(self) -> QSize:
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    @override
    def minimumSizeHint(self) -> QSize:
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


def body_label(text: str) -> QLabel:
    label = WrappedLabel(text)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def heading_label(text: str, level: int = 1) -> QLabel:
    label = WrappedLabel(text)
    label.setProperty("heading", level)
    label.setAccessibleName(text)
    return label


class StatusRow(QWidget):
    """One check: a mark, a plain statement, and — when needed — one recovery action."""

    def __init__(
        self,
        title: str,
        severity: str,
        recovery: str | None = None,
        action: tuple[str, Callable[[], None]] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("statusRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)
        mark = QLabel(SEVERITY_MARK.get(severity, "•"))
        mark.setProperty("severity", severity)
        mark.setAccessibleName(severity)
        layout.addWidget(mark)

        text = QVBoxLayout()
        headline = body_label(title)
        headline.setProperty("severity", severity)
        text.addWidget(headline)
        if recovery:
            note = body_label(recovery)
            note.setProperty("muted", True)
            text.addWidget(note)
        layout.addLayout(text, 1)

        if action is not None:
            label, handler = action
            button = QPushButton(label)
            button.setAccessibleName(f"{label}: {title}")
            button.clicked.connect(handler)
            layout.addWidget(button)
        self.setAccessibleName(f"{severity}: {title}")


class SecretField(QWidget):
    """A key entry with paste, an accessible reveal control, and a clear on leaving the step."""

    def __init__(self, label: str, reveal_label: str, help_text: str | None = None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(label)
        layout.addWidget(caption)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setAccessibleName(label)
        self.edit.setClearButtonEnabled(True)
        caption.setBuddy(self.edit)
        layout.addWidget(self.edit)

        self.reveal = QCheckBox(reveal_label)
        self.reveal.setAccessibleName(reveal_label)
        self.reveal.toggled.connect(self._set_visible)
        layout.addWidget(self.reveal)

        if help_text:
            note = body_label(help_text)
            note.setProperty("muted", True)
            self.edit.setAccessibleDescription(help_text)
            layout.addWidget(note)

        self.error = body_label("")
        self.error.setProperty("severity", "error")
        self.error.hide()
        layout.addWidget(self.error)

    def _set_visible(self, visible: bool) -> None:
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)

    def value(self) -> str:
        return self.edit.text().strip()

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()
        self.edit.setAccessibleDescription(message)
        announce(self.edit, message)
        self.edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def clear_error(self) -> None:
        self.error.clear()
        self.error.hide()

    def clear_secret(self) -> None:
        """Sensitive input is kept only as long as the step that needs it."""
        self.edit.clear()
        self.reveal.setChecked(False)


class BusyBar(QWidget):
    """Named progress with a working Cancel, and no invented percentage."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(120)
        layout.addWidget(self.bar)
        self.cancel = QPushButton("")
        self._cancel_connected = False
        layout.addWidget(self.cancel)
        self.hide()

    def start(self, message: str, cancel_label: str, on_cancel: Callable[[], None]) -> None:
        self.label.setText(message)
        self.cancel.setText(cancel_label)
        if self._cancel_connected:
            self.cancel.clicked.disconnect()
        self.cancel.clicked.connect(on_cancel)
        self._cancel_connected = True
        self.show()
        announce(self, message)

    def stop(self) -> None:
        self.hide()
