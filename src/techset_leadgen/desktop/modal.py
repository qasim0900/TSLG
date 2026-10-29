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

from techset_leadgen.branding import LOGO_ASSET

from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.motion import EASE, EASE_OUT, animate, clear_effect, pop_window, reduced_motion, rise, visible_children
from techset_leadgen.desktop.theme import asset_path, is_dark, tokens

SHADOW = 20
HEADER = 48
RADIUS = 16
EDGE = 16
PADDING = (24, 20, 24, 18)


def chrome_enabled() -> bool:
    return os.environ.get("TSLG_NATIVE_DIALOGS", "").strip() in ("", "0")


def _shadow(owner: QWidget) -> QGraphicsDropShadowEffect:
    shadow = QGraphicsDropShadowEffect(owner)
    shadow.setBlurRadius(48)
    shadow.setOffset(0, 12)
    shadow.setColor(QColor(0, 0, 0, 120) if is_dark() else QColor(10, 20, 20, 60))
    return shadow


class _Surface(QWidget):
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.alpha = 1.0
        self.setGraphicsEffect(_shadow(self))

    def set_alpha(self, value: float) -> None:
        if Shiboken.isValid(self):
            self.alpha = value
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
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
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.alpha = 1.0

    def set_alpha(self, value: float) -> None:
        if Shiboken.isValid(self):
            self.alpha = value
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
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
        self.close_button.setObjectName("iconButtonSmall")
        self.close_button.setAccessibleName("Close dialog")
        self.close_button.setToolTip("Close")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        set_button_icon(self.close_button, "close", "text2", 16)
        self.close_button.clicked.connect(dialog.reject)
        row.addWidget(mark)
        row.addWidget(self.kicker, 1)
        row.addWidget(self.close_button)
        self._drag: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.dialog.isWindow():
            self._drag = event.globalPosition().toPoint() - self.dialog.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.dialog.move(event.globalPosition().toPoint() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag = None


class Backdrop(QWidget):
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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and Shiboken.isValid(self):
            host = self.parentWidget()
            if host is not None:
                self.setGeometry(host.rect())
        return False

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        color = QColor(0, 0, 0, 158) if is_dark() else QColor(10, 20, 20, 115)
        color.setAlphaF(color.alphaF() * self._alpha)
        painter.fillRect(self.rect(), color)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        event.accept()


def _footer_widget(dialog: QDialog) -> QWidget | None:
    marked = dialog.findChild(QWidget, "modalFooter")
    if marked is not None:
        return None
    boxes = [box for box in dialog.findChildren(QDialogButtonBox) if box.window() is dialog.window()]
    return boxes[-1] if boxes else None


class _Chrome(QObject):
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.surface = _Surface(dialog)
        self.band = _FooterBand(dialog)
        self.header = ModalHeader(dialog)
        self.backdrop: Backdrop | None = None
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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
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
            ref = weakref.ref(self)

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
    if dialog.property("modalChrome") or not chrome_enabled():
        return
    dialog.setProperty("modalChrome", True)
    layout = dialog.layout()
    if layout is not None:
        margins = layout.contentsMargins()
        left, top, right, bottom = margins.left(), margins.top(), margins.right(), margins.bottom()
        if left or top or right or bottom:
            left, top, right, bottom = max(left, PADDING[0]), max(top, PADDING[1]), \
                max(right, PADDING[2]), max(bottom, PADDING[3])
        layout.setContentsMargins(left + SHADOW, top + SHADOW + HEADER, right + SHADOW, bottom + SHADOW)
        footer = _footer_widget(dialog)
        index = layout.indexOf(footer) if footer is not None and isinstance(layout, QBoxLayout) else -1
        if isinstance(layout, QBoxLayout) and index > 0:
            layout.insertSpacing(index, 16)
    size = dialog.size()
    dialog.resize(size.width() + 2 * SHADOW, size.height() + 2 * SHADOW + HEADER)
    minimum = dialog.minimumSize()
    if minimum.width() or minimum.height():
        dialog.setMinimumSize(minimum.width() + 2 * SHADOW if minimum.width() else 0,
                              minimum.height() + 2 * SHADOW + HEADER if minimum.height() else 0)
    for box in dialog.findChildren(QDialogButtonBox):
        for button in box.buttons():
            if box.buttonRole(button) in (QDialogButtonBox.ButtonRole.AcceptRole,
                                          QDialogButtonBox.ButtonRole.YesRole) and not button.objectName():
                button.setObjectName("primaryButton")
                button.style().unpolish(button)
                button.style().polish(button)
    for scroll in dialog.findChildren(QScrollArea):
        scroll.viewport().setAutoFillBackground(False)
        body = scroll.widget()
        if body is not None:
            body.setAutoFillBackground(False)
    chrome = _Chrome(dialog)
    chrome.place()
    dialog.style().unpolish(dialog)
    dialog.style().polish(dialog)


def _as_window(dialog: QDialog) -> None:
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.FramelessWindowHint
                          | Qt.WindowType.NoDropShadowWindowHint)


_OPEN: list[_Embedding] = []


_HOME = "_modalHome"


def _host_for(dialog: QDialog) -> QWidget | None:
    parent = dialog.parentWidget()
    if parent is None:
        home = getattr(dialog, _HOME, None)
        parent = home if home is not None and Shiboken.isValid(home) else None
    host = parent.window() if parent is not None else None
    if host is None or host is dialog or not host.isVisible() or isinstance(host, QDialog):
        return None
    return host


def _later(owner: QObject, method: str, *args: object) -> None:
    ref = weakref.ref(owner)

    def call() -> None:
        target = ref()
        if target is not None:
            getattr(target, method)(*args)

    QTimer.singleShot(0, call)


def current_modal() -> QDialog | None:
    for embedding in reversed(_OPEN):
        if Shiboken.isValid(embedding.dialog) and embedding.dialog.isVisible():
            return embedding.dialog
    return None


class _Embedding(QObject):
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
        self._explicit = QSize(dialog.size()) if dialog.testAttribute(Qt.WidgetAttribute.WA_Resized) else QSize()
        self._previous_focus = QApplication.focusWidget()
        initial = dialog.focusWidget()
        self._initial = initial if initial is not None and initial is not dialog else None
        self._margin = SHADOW if dialog.property("modalChrome") else 0
        self._own_shadow = False
        if not dialog.property("modalChrome") and dialog.graphicsEffect() is None:
            dialog.setGraphicsEffect(_shadow(dialog))
            self._own_shadow = True
        self.backdrop = Backdrop(host)
        dialog.setParent(self.backdrop, Qt.WindowType.Widget)
        dialog.hide()
        dialog.setMinimumSize(0, 0)
        self.backdrop.show()
        self.backdrop.raise_()
        self.place()
        dialog.installEventFilter(self)
        host.installEventFilter(self)
        _OPEN.append(self)


    def place(self) -> None:
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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
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
            ref = weakref.ref(self)

            def slide(value: float) -> None:
                embedding = ref()
                if embedding is not None:
                    embedding._slide(value)

            animate(14.0, 0.0, 360, slide, curve=EASE_OUT, owner=self)
        _later(self, "_focus_inside")


    def contains(self, widget: QWidget) -> bool:
        return Shiboken.isValid(self.dialog) and (widget is self.dialog or self.dialog.isAncestorOf(widget))

    def focusables(self) -> list[QWidget]:
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


    def release(self) -> None:
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
            remembered = dialog.focusWidget()
            if remembered is not None:
                remembered.clearFocus()
            if self._own_shadow:
                clear_effect(dialog)
            dialog.setMinimumSize(self._minimum)
            dialog.setParent(None, self._flags)
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
    if Shiboken.isValid(widget):
        widget.hide()
        widget.deleteLater()


def embed(dialog: QDialog) -> bool:
    host = _host_for(dialog) if chrome_enabled() else None
    if host is None:
        return False
    _Embedding(dialog, host, release_on_hide=True)
    return True


class ModalDialog(QDialog):
    def exec(self) -> int:
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
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
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

