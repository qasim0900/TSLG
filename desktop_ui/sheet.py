"""Modal dialogs shown as cards centred inside their window.

On Wayland the compositor, not the application, places top-level windows: Qt
cannot centre a dialog over the main window, and GNOME gives every dialog
minimise, maximise, and close buttons and lets users drag it away.
``SheetDialog`` keeps QDialog's ``exec()``/``accept()``/``reject()`` API but
shows the dialog as a card centred in its window over a dimmed backdrop. It
has no title bar, cannot be dragged, re-centres and resizes with the window,
and keeps the rest of the window inert (mouse, keyboard focus, and shortcuts)
until it closes. Without a visible parent window, for example a startup error,
it falls back to a frameless top-level dialog.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPaintEvent, QShortcut, QShowEvent
from PySide6.QtWidgets import QApplication, QDialog, QGraphicsDropShadowEffect, QWidget
from shiboken6 import Shiboken

_MARGIN = 24
_BACKDROP = QColor(0, 0, 0, 115)


class _Backdrop(QWidget):
    """Dims the host window, swallows its mouse input, and keeps the sheet centred."""

    def __init__(self, host: QWidget, sheet: SheetDialog) -> None:
        super().__init__(host)
        self._sheet = sheet
        self.setObjectName("sheetBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        host.installEventFilter(self)

    def place(self) -> None:
        host = self.parentWidget()
        if host is None:
            return
        self.setGeometry(host.rect())
        self._sheet.setGeometry(self._sheet.sheet_geometry(self.rect()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.place()
        return False

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        QPainter(self).fillRect(self.rect(), _BACKDROP)

    # Clicks on the backdrop neither reach the window behind nor dismiss the
    # sheet: a destructive question needs an explicit answer.
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        event.accept()


class SheetDialog(QDialog):
    """A modal dialog shown as a centred, undraggable card inside its window."""

    _open: ClassVar[list[SheetDialog]] = []

    @classmethod
    def current(cls) -> SheetDialog | None:
        """Return the top-most open sheet (tests and tooling use this to find it)."""
        for sheet in reversed(cls._open):
            if Shiboken.isValid(sheet) and sheet.isVisible():
                return sheet
        return None

    # ----------------------------------------------------------- geometry hooks

    def preferred_sheet_width(self) -> int:
        return max(self.sizeHint().width(), self._requested_minimum.width())

    def minimum_sheet_width(self) -> int:
        return self.minimumSizeHint().width()

    def height_for_sheet_width(self, width: int) -> int:
        layout = self.layout()
        if layout is not None and layout.hasHeightForWidth():
            return layout.totalHeightForWidth(width)
        return max(self.sizeHint().height(), self.minimumSizeHint().height())

    def sheet_geometry(self, area: QRect) -> QRect:
        """Centre the card in ``area``, as wide as preferred but never wider than fits."""
        max_width = max(area.width() - 2 * _MARGIN, 160)
        max_height = max(area.height() - 2 * _MARGIN, 120)
        width = max(min(self.preferred_sheet_width(), max_width), min(self.minimum_sheet_width(), max_width))
        height = min(self.height_for_sheet_width(width), max_height)
        return QRect(
            area.x() + (area.width() - width) // 2,
            area.y() + (area.height() - height) // 2,
            width,
            height,
        )

    # ------------------------------------------------------------------ exec

    @property
    def _requested_minimum(self) -> QSize:
        return getattr(self, "_saved_minimum", self.minimumSize())

    def exec(self) -> int:
        parent = self.parentWidget()
        host = parent.window() if parent is not None else None
        SheetDialog._open.append(self)
        try:
            if host is not None and host.isVisible():
                return self._exec_embedded(host)
            return self._exec_frameless()
        finally:
            SheetDialog._open.remove(self)

    def _style_as(self, kind: str) -> None:
        self.setProperty("sheet", kind)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.style().unpolish(self)
        self.style().polish(self)

    def _exec_embedded(self, host: QWidget) -> int:
        previous_focus = QApplication.focusWidget()
        self._saved_minimum = QSize(self.minimumSize())
        backdrop = _Backdrop(host, self)
        self.setParent(backdrop, Qt.WindowType.Widget)
        self.setMinimumSize(0, 0)  # the card shrinks with narrow windows
        self._style_as("embedded")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)
        suspended = _suspend_background(host, backdrop)
        backdrop.place()
        backdrop.show()
        backdrop.raise_()
        try:
            return super().exec()
        finally:
            _resume_background(suspended)
            self.hide()
            # Detach both so they are freed with their Python references now,
            # rather than lingering as children of the window.
            self.setParent(None)
            backdrop.hide()
            backdrop.setParent(None)
            if (
                previous_focus is not None
                and Shiboken.isValid(previous_focus)
                and previous_focus.isVisible()
                and previous_focus.isEnabled()
            ):
                previous_focus.setFocus(Qt.FocusReason.OtherFocusReason)

    def _exec_frameless(self) -> int:
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self._style_as("window")
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            # Honoured on X11, Windows, and macOS; Wayland compositors place it.
            self.setGeometry(self.sheet_geometry(screen.availableGeometry()))
        return super().exec()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        target = self.initial_focus_widget()
        if target is not None:
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def initial_focus_widget(self) -> QWidget | None:
        """Widget focused when the sheet opens; subclasses choose a safe default."""
        return None


def _suspend_background(host: QWidget, backdrop: QWidget) -> tuple[list[QWidget], list[QShortcut]]:
    """Disable the window's other content and shortcuts while a sheet is open.

    Disabled widgets cannot take keyboard focus, so Tab stays inside the sheet,
    and window-level shortcuts (Ctrl+1, Ctrl+I, ...) cannot act behind it.
    """
    widgets = [
        child
        # No name argument: findChildren(type, "") matches only *unnamed* children.
        for child in host.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if child is not backdrop and not child.isWindow() and child.isEnabled()
    ]
    shortcuts = [shortcut for shortcut in host.findChildren(QShortcut) if shortcut.isEnabled()]
    for widget in widgets:
        widget.setEnabled(False)
    for shortcut in shortcuts:
        shortcut.setEnabled(False)
    return widgets, shortcuts


def _resume_background(suspended: tuple[list[QWidget], list[QShortcut]]) -> None:
    widgets, shortcuts = suspended
    for widget in widgets:
        if Shiboken.isValid(widget):
            widget.setEnabled(True)
    for shortcut in shortcuts:
        if Shiboken.isValid(shortcut):
            shortcut.setEnabled(True)


__all__ = ["SheetDialog"]
