"""The redesign's modal shell: every application dialog is a card centred in its window.

``ModalDialog`` is the base class of the app's dialogs. Its ``exec()`` gives the
dialog the design's shell (once):

* a 16 px rounded surface with a hairline border and a soft shadow;
* a 48 px header: the Techset mark, a short kicker (the window title) and a close button;
* a footer band in the soft surface colour behind the dialog's buttons;

and shows the card *inside* the window it belongs to, centred over a dimmed
backdrop. On Wayland the compositor, not the application, places top-level
windows (GNOME opened dialogs in the top-left corner), so a separate dialog
window can never be reliably centred; drawn inside the window, the card is
centred on every platform, re-centres when the window is resized, and needs no
translucent window (whose corners showed black on Wayland). While it is open the
window behind is inert: the backdrop swallows the mouse, and keyboard focus and
the window's shortcuts stay inside the card. ``exec()`` still runs a nested event
loop, so callers, ``accept()``/``reject()`` and the tests see a normal modal dialog.

A dialog with no visible window to sit in (a start-up error) opens as a frameless
top-level window instead. :func:`embed` gives the same treatment to a dialog shown
with ``show()`` (the import progress dialog). System file dialogs keep their
native windows. ``TSLG_NATIVE_DIALOGS=1`` keeps plain native dialog windows everywhere.
"""

from __future__ import annotations

import os
import weakref
from functools import partial

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFocusEvent,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QTextEdit,
    QToolButton,
    QWidget,
)
from shiboken6 import Shiboken

from branding import LOGO_ASSET

from .icons import set_button_icon
from .motion import EASE, EASE_OUT, animate, clear_effect, pop_window, reduced_motion, rise, visible_children
from .theme import asset_path, is_dark, tokens

SHADOW = 20  # transparent margin around the card where its shadow is drawn
HEADER = 48
RADIUS = 16
EDGE = 16  # the smallest gap between the card and the edge of its window
PADDING = (24, 20, 24, 18)  # inside the card, around the dialog's content


def chrome_enabled() -> bool:
    return os.environ.get("TSLG_NATIVE_DIALOGS", "").strip() in ("", "0")


def _shadow(owner: QWidget) -> QGraphicsDropShadowEffect:
    shadow = QGraphicsDropShadowEffect(owner)
    shadow.setBlurRadius(48)
    shadow.setOffset(0, 12)
    shadow.setColor(QColor(0, 0, 0, 120) if is_dark() else QColor(10, 20, 20, 60))
    return shadow


class _Surface(QWidget):
    """The card itself: rounded surface, border, and the shadow (as an effect)."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.alpha = 1.0
        self.setGraphicsEffect(_shadow(self))

    def set_alpha(self, value: float) -> None:
        if Shiboken.isValid(self):
            self.alpha = value
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.alpha)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(t["line"]), 1))
        painter.setBrush(QColor(t["surface"]))
        painter.drawRoundedRect(rect, RADIUS, RADIUS)
        painter.end()


class _FooterBand(QWidget):
    """The soft-surface strip with a top hairline behind a dialog's buttons."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.alpha = 1.0

    def set_alpha(self, value: float) -> None:
        if Shiboken.isValid(self):
            self.alpha = value
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.alpha)
        rect = QRectF(self.rect()).adjusted(1, 0, -1, -1)
        path = QPainterPath()
        radius = RADIUS - 1
        path.moveTo(rect.topLeft())
        path.lineTo(rect.topRight())
        path.lineTo(rect.right(), rect.bottom() - radius)
        path.quadTo(rect.bottomRight(), QPoint(int(rect.right() - radius), int(rect.bottom())))
        path.lineTo(rect.left() + radius, rect.bottom())
        path.quadTo(rect.bottomLeft(), QPoint(int(rect.left()), int(rect.bottom() - radius)))
        path.closeSubpath()
        painter.fillPath(path, QColor(t["surface2"]))
        painter.setPen(QPen(QColor(t["line"]), 1))
        painter.drawLine(QPoint(int(rect.left()), 0), QPoint(int(rect.right()), 0))
        painter.end()


class ModalHeader(QFrame):
    """Mark, kicker and close button (a dialog in its own window can be dragged by it)."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.setObjectName("modalHeader")
        self.dialog = dialog
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(QIcon(str(asset_path(LOGO_ASSET))).pixmap(QSize(18, 18)))
        mark.setFixedSize(18, 18)
        self.kicker = QLabel(dialog.windowTitle())
        self.kicker.setObjectName("modalKicker")
        self.close_button = QToolButton()
        self.close_button.setObjectName("iconButtonSmall")  # a borderless glyph, like the design's
        self.close_button.setAccessibleName("Close dialog")
        self.close_button.setToolTip("Close")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        set_button_icon(self.close_button, "close", "text2", 16)
        self.close_button.clicked.connect(dialog.reject)
        row.addWidget(mark)
        row.addWidget(self.kicker, 1)
        row.addWidget(self.close_button)
        self._drag: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self.dialog.isWindow():
            self._drag = event.globalPosition().toPoint() - self.dialog.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.dialog.move(event.globalPosition().toPoint() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        self._drag = None


class Backdrop(QWidget):
    """Dims the window behind an open dialog; the window gets none of its input."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("modalBackdrop")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self._alpha = 1.0
        self.setGeometry(host.rect())
        host.installEventFilter(self)

    def set_alpha(self, value: float) -> None:
        if Shiboken.isValid(self):
            self._alpha = value
            self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Resize and Shiboken.isValid(self):
            host = self.parentWidget()
            if host is not None:
                self.setGeometry(host.rect())
        return False

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        color = QColor(0, 0, 0, 158) if is_dark() else QColor(10, 20, 20, 115)
        color.setAlphaF(color.alphaF() * self._alpha)
        painter.fillRect(self.rect(), color)
        painter.end()

    # Clicks on the backdrop neither reach the window behind nor dismiss the dialog:
    # a question needs an explicit answer. Keys the dialog leaves alone stop here too.
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802 - Qt API
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        event.accept()


def _footer_widget(dialog: QDialog) -> QWidget | None:
    """The widget holding the dialog's main buttons (a button box, or a marked row)."""
    marked = dialog.findChild(QWidget, "modalFooter")
    if marked is not None:
        return None  # the dialog draws its own full-width footer
    boxes = [box for box in dialog.findChildren(QDialogButtonBox) if box.window() is dialog.window()]
    return boxes[-1] if boxes else None


class _Chrome(QObject):
    """Keeps the surface, header and footer band placed; runs the card's entrance."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.surface = _Surface(dialog)
        self.band = _FooterBand(dialog)
        self.header = ModalHeader(dialog)
        self.backdrop: Backdrop | None = None  # a dialog in its own window dims its parent window
        self.band.stackUnder(self.header)
        self.surface.lower()
        dialog.installEventFilter(self)

    def place(self) -> None:
        dialog = self.dialog
        card = dialog.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        self.surface.setGeometry(card)
        self.header.setGeometry(card.left(), card.top(), card.width(), HEADER)
        footer = _footer_widget(dialog)
        if footer is not None and footer.isVisible():
            top = footer.mapTo(dialog, QPoint(0, 0)).y() - 14
            self.band.setGeometry(QRect(card.left(), top, card.width(), card.bottom() - top + 1))
            self.band.show()
            self.band.lower()
            self.surface.lower()
        else:
            self.band.hide()

    def set_alpha(self, value: float) -> None:
        self.surface.set_alpha(value)
        self.band.set_alpha(value)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        try:
            if kind in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.Show):
                self.place()
            if kind == QEvent.Type.WindowTitleChange:
                self.header.kicker.setText(self.dialog.windowTitle())
            if kind == QEvent.Type.Show:
                self._opened()
            elif kind == QEvent.Type.Hide:
                self._closed()
        except RuntimeError:
            pass
        return False

    def _opened(self) -> None:
        dialog = self.dialog
        if dialog.isWindow():
            parent = dialog.parentWidget()
            host = parent.window() if parent is not None else None
            if host is not None and host.isVisible() and dialog.isModal() and self.backdrop is None:
                self.backdrop = Backdrop(host)
                self.backdrop.show()
                self.backdrop.raise_()
                animate(0.0, 1.0, 220, self.backdrop.set_alpha, curve=EASE, owner=self.backdrop)
            pop_window(dialog)
        elif not reduced_motion():
            ref = weakref.ref(self)  # see _Embedding._opened

            def fade(value: float) -> None:
                chrome = ref()
                if chrome is not None:
                    chrome.set_alpha(value)

            animate(0.0, 1.0, 240, fade, curve=EASE, owner=self.surface, done=partial(fade, 1.0))
        if not reduced_motion():
            rise([self.header, *visible_children(dialog)], step=30, start=60, duration=400, dy=10)

    def _closed(self) -> None:
        backdrop, self.backdrop = self.backdrop, None
        if backdrop is not None:
            _retire(backdrop)


def apply_chrome(dialog: QDialog) -> None:
    """Give ``dialog`` the modal shell (once)."""
    if dialog.property("modalChrome") or not chrome_enabled():
        return
    dialog.setProperty("modalChrome", True)
    layout = dialog.layout()
    if layout is not None:
        margins = layout.contentsMargins()
        left, top, right, bottom = margins.left(), margins.top(), margins.right(), margins.bottom()
        if left or top or right or bottom:
            # The card's padding: every dialog the same, whatever margins it was built with
            # (dialogs with zero margins pad their own sections and full-width footer).
            left, top, right, bottom = max(left, PADDING[0]), max(top, PADDING[1]), \
                max(right, PADDING[2]), max(bottom, PADDING[3])
        layout.setContentsMargins(left + SHADOW, top + SHADOW + HEADER, right + SHADOW, bottom + SHADOW)
        footer = _footer_widget(dialog)
        index = layout.indexOf(footer) if footer is not None and isinstance(layout, QBoxLayout) else -1
        if isinstance(layout, QBoxLayout) and index > 0:
            layout.insertSpacing(index, 16)  # room for the footer band above the buttons
    size = dialog.size()
    dialog.resize(size.width() + 2 * SHADOW, size.height() + 2 * SHADOW + HEADER)
    minimum = dialog.minimumSize()
    if minimum.width() or minimum.height():
        dialog.setMinimumSize(minimum.width() + 2 * SHADOW if minimum.width() else 0,
                              minimum.height() + 2 * SHADOW + HEADER if minimum.height() else 0)
    for box in dialog.findChildren(QDialogButtonBox):
        # As in the app's other dialogs: the action is the green button (on the right, after
        # Cancel: the stylesheet gives button boxes the GNOME order on every platform).
        for button in box.buttons():
            if box.buttonRole(button) in (QDialogButtonBox.ButtonRole.AcceptRole,
                                          QDialogButtonBox.ButtonRole.YesRole) and not button.objectName():
                button.setObjectName("primaryButton")
                button.style().unpolish(button)
                button.style().polish(button)
    for scroll in dialog.findChildren(QScrollArea):  # let the card's surface show through
        scroll.viewport().setAutoFillBackground(False)
        body = scroll.widget()
        if body is not None:
            body.setAutoFillBackground(False)
    chrome = _Chrome(dialog)
    chrome.place()
    dialog.style().unpolish(dialog)
    dialog.style().polish(dialog)


def _as_window(dialog: QDialog) -> None:
    """A frameless, translucent top-level window (when there is no window to sit in).

    Translucency is set before the flags: changing the flags re-creates the native
    window, and only a window created translucent has see-through corners.
    """
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.FramelessWindowHint
                          | Qt.WindowType.NoDropShadowWindowHint)


# ------------------------------------------------------------ inside the window


_OPEN: list[_Embedding] = []


_HOME = "_modalHome"  # the parent a dialog had before it was first shown in a window


def _host_for(dialog: QDialog) -> QWidget | None:
    """The application window the dialog is shown in, or None for its own window."""
    parent = dialog.parentWidget()
    if parent is None:
        home = getattr(dialog, _HOME, None)
        parent = home if home is not None and Shiboken.isValid(home) else None
    host = parent.window() if parent is not None else None
    if host is None or host is dialog or not host.isVisible() or isinstance(host, QDialog):
        return None
    return host


def _later(owner: QObject, method: str, *args: object) -> None:
    """Call ``owner.method(*args)`` on the next turn of the event loop, if ``owner`` still exists.

    Holds only a weak reference: a pending call must not keep a closed dialog alive.
    """
    ref = weakref.ref(owner)

    def call() -> None:
        target = ref()
        if target is not None:
            getattr(target, method)(*args)

    QTimer.singleShot(0, call)


def current_modal() -> QDialog | None:
    """The top-most dialog open inside a window (tests and tooling use this to find it)."""
    for embedding in reversed(_OPEN):
        if Shiboken.isValid(embedding.dialog) and embedding.dialog.isVisible():
            return embedding.dialog
    return None


class _Embedding(QObject):
    """One dialog shown inside ``host``: backdrop, centring, focus, and the way back out.

    It has no Qt parent, so it (and the dialog it refers to) is freed with its last Python
    reference rather than by ``deleteLater()``, which never runs without an outer event loop.
    """

    def __init__(self, dialog: QDialog, host: QWidget, *, release_on_hide: bool) -> None:
        super().__init__()
        self.dialog = dialog
        self.host = host
        self.release_on_hide = release_on_hide
        self.released = False
        self.offset = 0
        self._parent = dialog.parentWidget() or getattr(dialog, _HOME, None)
        self._flags = dialog.windowFlags()
        self._minimum = QSize(dialog.minimumSize())
        # A size the dialog chose for itself (resize() in its constructor) is kept.
        self._explicit = QSize(dialog.size()) if dialog.testAttribute(Qt.WidgetAttribute.WA_Resized) else QSize()
        self._previous_focus = QApplication.focusWidget()
        initial = dialog.focusWidget()  # setFocus() calls made before it opened (lost when reparented)
        self._initial = initial if initial is not None and initial is not dialog else None
        self._margin = SHADOW if dialog.property("modalChrome") else 0
        self._own_shadow = False
        if not dialog.property("modalChrome") and dialog.graphicsEffect() is None:
            dialog.setGraphicsEffect(_shadow(dialog))  # a styled card without the shell (progress)
            self._own_shadow = True
        self.backdrop = Backdrop(host)
        dialog.setParent(self.backdrop, Qt.WindowType.Widget)
        dialog.hide()  # shown by exec()/show(), not along with the backdrop
        dialog.setMinimumSize(0, 0)  # the card may shrink with a small window
        self.backdrop.show()
        self.backdrop.raise_()
        self.place()
        dialog.installEventFilter(self)
        host.installEventFilter(self)
        _OPEN.append(self)

    # ------------------------------------------------------------ geometry

    def place(self) -> None:
        """Centre the card: its preferred size, never larger than the window."""
        dialog = self.dialog
        if self.released or not Shiboken.isValid(dialog):
            return
        area = self.backdrop.rect()
        allowance = 2 * self._margin - 2 * EDGE
        most_width = max(area.width() + allowance, 160)
        most_height = max(area.height() + allowance, 120)
        hint = dialog.sizeHint()
        floor = dialog.minimumSizeHint()
        width = self._explicit.width() if self._explicit.isValid() else hint.width()
        width = min(max(width, self._minimum.width(), floor.width()), most_width)
        layout = dialog.layout()
        if layout is not None and layout.hasHeightForWidth():
            needed = layout.totalHeightForWidth(width)
        else:
            needed = max(hint.height(), floor.height())
        explicit_height = self._explicit.height() if self._explicit.isValid() else 0
        height = min(max(needed, explicit_height, self._minimum.height()), most_height)
        dialog.setGeometry(area.x() + (area.width() - width) // 2,
                           area.y() + (area.height() - height) // 2 + self.offset, width, height)

    def _slide(self, value: float) -> None:
        if self.released or not Shiboken.isValid(self.dialog):
            return
        self.offset = round(value)
        area = self.backdrop.rect()
        self.dialog.move(self.dialog.x(), area.y() + (area.height() - self.dialog.height()) // 2 + self.offset)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        try:
            if watched is self.host and kind == QEvent.Type.Resize:
                self.backdrop.setGeometry(self.host.rect())
                self.place()
            elif watched is self.dialog:
                if kind == QEvent.Type.LayoutRequest:
                    self.place()
                elif kind == QEvent.Type.Show:
                    self._opened()
                elif kind == QEvent.Type.Hide and self.release_on_hide:
                    _later(self, "release")
        except RuntimeError:
            pass
        return False

    def _opened(self) -> None:
        if not reduced_motion():
            animate(0.0, 1.0, 220, self.backdrop.set_alpha, curve=EASE, owner=self.backdrop)
            # Weakly: the animation is this object's child, and a callback holding the last
            # reference would delete it from inside the animation's own destructor.
            ref = weakref.ref(self)

            def slide(value: float) -> None:
                embedding = ref()
                if embedding is not None:
                    embedding._slide(value)

            animate(14.0, 0.0, 360, slide, curve=EASE_OUT, owner=self)
        _later(self, "_focus_inside")

    # --------------------------------------------------------------- focus

    def contains(self, widget: QWidget) -> bool:
        return Shiboken.isValid(self.dialog) and (widget is self.dialog or self.dialog.isAncestorOf(widget))

    def focusables(self) -> list[QWidget]:
        """The card's widgets that Tab stops at, in the order they were built (the Tab order).

        Not by walking ``nextInFocusChain()``: PySide's return-value heuristic makes each
        widget it returns a Python child of the one it was called on, and walking the
        whole window's chain tied unrelated widgets into an ownership cycle that freed
        memory twice (a crash after the Marketing spend dialog).
        """
        return [
            widget for widget in self.dialog.findChildren(QWidget)
            if widget.isVisible() and widget.isEnabled() and widget.focusProxy() is None
            and widget.focusPolicy().value & Qt.FocusPolicy.TabFocus.value
        ]

    def _focus_inside(self) -> None:
        if self.released or not Shiboken.isValid(self.dialog) or not self.dialog.isVisible():
            return
        focus = QApplication.focusWidget()
        if focus is not None and self.contains(focus):
            return
        target = self._initial
        if target is None or not Shiboken.isValid(target) or not self.contains(target) \
                or not target.isVisible() or not target.isEnabled():
            items = self.focusables()
            target = items[0] if items else self.dialog
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def refocus(self, reason: Qt.FocusReason) -> None:
        """Focus went behind the card (Tab past its last field): bring it back inside."""
        if self.released or not Shiboken.isValid(self.dialog) or not self.dialog.isVisible():
            return
        focus = QApplication.focusWidget()
        if focus is not None and self.contains(focus):
            return
        items = self.focusables()
        if items:
            items[-1 if reason == Qt.FocusReason.BacktabFocusReason else 0].setFocus(reason)
        else:
            self.dialog.setFocus(reason)

    # ---------------------------------------------------------------- close

    def release(self) -> None:
        """Hand the dialog back to its parent and fade the backdrop out."""
        if self.released:
            return
        self.released = True
        if self in _OPEN:
            _OPEN.remove(self)
        if Shiboken.isValid(self.host):
            self.host.removeEventFilter(self)
        dialog = self.dialog
        if Shiboken.isValid(dialog):
            dialog.removeEventFilter(self)
            if dialog.isVisible():
                dialog.hide()
            # Clear the card's remembered focus while it is still inside the window: the
            # window's widgets keep pointers to it, which would dangle once it is detached.
            remembered = dialog.focusWidget()
            if remembered is not None:
                remembered.clearFocus()
            if self._own_shadow:
                clear_effect(dialog)
            dialog.setMinimumSize(self._minimum)
            # Detached, not handed back to its parent: after exec() Python owns a dialog,
            # so it is freed with its last reference instead of lingering in the window
            # (see DEF-026). Its parent is remembered for the next exec().
            dialog.setParent(None, self._flags)  # type: ignore[call-overload]
            setattr(dialog, _HOME, self._parent)
        previous = self._previous_focus
        if previous is not None and Shiboken.isValid(previous) and previous.isVisible() and previous.isEnabled():
            previous.setFocus(Qt.FocusReason.OtherFocusReason)
        backdrop = self.backdrop
        if Shiboken.isValid(backdrop):
            backdrop.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            animate(1.0, 0.0, 160, backdrop.set_alpha, curve=EASE, owner=backdrop,
                    done=partial(_retire, backdrop))


def _retire(widget: QWidget) -> None:
    """Hide ``widget`` and let Qt delete it (it stays owned by its window until then).

    Not detached for Python to free: its own fade-out animation's callback holds a
    reference, and dropping that last reference would delete the widget, and with it
    the animation, from inside the animation's destructor.
    """
    if Shiboken.isValid(widget):
        widget.hide()
        widget.deleteLater()


def embed(dialog: QDialog) -> bool:
    """Show ``dialog`` (opened with ``show()``) centred inside its window.

    Returns False when it has no visible window to sit in and stays a window.
    """
    host = _host_for(dialog) if chrome_enabled() else None
    if host is None:
        return False
    _Embedding(dialog, host, release_on_hide=True)
    return True


class ModalDialog(QDialog):
    """Base class of the app's dialogs: the design's card, centred in its window."""

    def exec(self) -> int:  # type: ignore[override]
        if not chrome_enabled():
            return super().exec()
        apply_chrome(self)
        host = _host_for(self)
        if host is None:
            _as_window(self)
            return super().exec()
        embedding = _Embedding(self, host, release_on_hide=False)
        try:
            return super().exec()
        finally:
            embedding.release()


class FocusTrap(QObject):
    """While a dialog is open inside a window, keep the keyboard inside the card.

    Tab and Shift+Tab cycle through the card's fields, focus that lands behind it
    returns, and the window's shortcuts (Ctrl+K, Ctrl+1 …) do nothing.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if not _OPEN:
            return False
        top = _OPEN[-1]
        kind = event.type()
        try:
            if kind == QEvent.Type.KeyPress and isinstance(watched, QWidget) and isinstance(event, QKeyEvent):
                return self._cycle(top, watched, event)
            if kind == QEvent.Type.Shortcut:
                owner = watched.parent() if isinstance(watched, QShortcut) else watched
                return isinstance(owner, QWidget) and owner.window() is top.host and not top.contains(owner)
            if kind == QEvent.Type.FocusIn and isinstance(watched, QWidget) and isinstance(event, QFocusEvent) \
                    and top.dialog.isVisible() and watched.window() is top.host and not top.contains(watched):
                _later(top, "refocus", event.reason())
        except RuntimeError:
            pass
        return False

    @staticmethod
    def _cycle(top: _Embedding, watched: QWidget, event: QKeyEvent) -> bool:
        key = event.key()
        if key not in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) or not top.contains(watched):
            return False
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        if isinstance(watched, (QPlainTextEdit, QTextEdit)) and not watched.tabChangesFocus():
            return False
        items = top.focusables()
        if not items:
            return False
        backwards = key == Qt.Key.Key_Backtab or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if backwards and watched is items[0]:
            items[-1].setFocus(Qt.FocusReason.BacktabFocusReason)
            return True
        if not backwards and watched is items[-1]:
            items[0].setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return False


__all__ = [
    "Backdrop", "FocusTrap", "ModalDialog", "ModalHeader", "apply_chrome", "chrome_enabled",
    "current_modal", "embed",
]
