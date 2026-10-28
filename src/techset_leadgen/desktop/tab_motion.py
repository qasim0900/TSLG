"""The selected-tab underline: a 3 px brand-green bar that grows out from the tab's centre.

``TabMotion`` (installed app-wide by :func:`desktop_ui.motion.install`) gives every
``QTabBar`` an indicator child that replaces the stylesheet underline. With
reduced motion the indicator is not attached and the stylesheet draws a static
underline instead.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QTabBar, QWidget
from shiboken6 import Shiboken

from techset_leadgen.desktop.motion import EASE, animate, reduced_motion
from techset_leadgen.desktop.theme import tokens
from techset_leadgen.desktop.widgets import repolish

_INSET = 10
_HEIGHT = 3

# Keeps each indicator's Python half alive until Qt destroys the widget. Its parent is
# usually a tab bar Qt made inside a QTabWidget, whose Python wrapper nothing keeps: the
# garbage collector freed the pair, and the widget lived on without its attributes
# (every later event failed with "'TabIndicator' object has no attribute 'bar'").
_LIVE: dict[int, TabIndicator] = {}


class TabIndicator(QWidget):
    def __init__(self, bar: QTabBar) -> None:
        super().__init__(bar)
        _LIVE[id(self)] = self
        self.destroyed.connect(partial(_LIVE.pop, id(self), None))
        self.bar = bar
        self._progress = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bar.currentChanged.connect(self._changed)
        bar.installEventFilter(self)
        bar.setProperty("animatedIndicator", True)
        repolish(bar)
        self.place()

    def _target(self) -> QRect:
        index = self.bar.currentIndex()
        if index < 0:
            return QRect()
        tab = self.bar.tabRect(index)
        return QRect(tab.left() + _INSET, tab.bottom() - _HEIGHT + 1, max(tab.width() - 2 * _INSET, 0), _HEIGHT)

    def place(self) -> None:
        target = self._target()
        width = round(target.width() * self._progress)
        self.setGeometry(target.center().x() - width // 2, target.top(), width, _HEIGHT)
        self.setVisible(target.width() > 0 and self.bar.isVisible())
        self.raise_()

    def set_progress(self, value: float) -> None:
        if Shiboken.isValid(self):
            self._progress = value
            self.place()

    def _changed(self, _index: int) -> None:
        animate(0.0, 1.0, 300, self.set_progress, curve=EASE, owner=self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest,
                            QEvent.Type.FontChange, QEvent.Type.StyleChange):
            try:
                self.place()
            except RuntimeError:
                pass
        return False

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens()["brand"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0, 0, 0, 2), 1.5, 1.5)  # rounded top only
        painter.end()


class TabMotion(QObject):
    """Attach a :class:`TabIndicator` to every tab bar when it is first shown."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Show and isinstance(watched, QTabBar) and not reduced_motion():
            if watched.findChild(TabIndicator) is None:
                TabIndicator(watched)
        return False


__all__ = ["TabIndicator", "TabMotion"]
