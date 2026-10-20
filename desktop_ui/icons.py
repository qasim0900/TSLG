"""Theme-aware line icons for the navigation rail, drawn with QPainter.

The shell previously used unrelated ``QStyle`` standard pixmaps (a monitor, an
arrow, a check mark, a list). They did not describe the pages, and the black
arrow was invisible on the dark sidebar, where compact mode shows icons only.
Drawing simple strokes in the active text colour keeps one consistent style in
both themes without adding image assets or an icon dependency.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_CANVAS = 24  # logical drawing grid
_SCALE = 2  # render at 2x for high-DPI screens


def _dashboard(painter: QPainter) -> None:
    for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
        painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.6, 1.6)


def _sales(painter: QPainter) -> None:
    path = QPainterPath(QPointF(3, 17))
    for x, y in ((9, 11), (13, 15), (21, 7)):
        path.lineTo(x, y)
    painter.drawPath(path)
    arrow = QPainterPath(QPointF(15.5, 7))
    arrow.lineTo(21, 7)
    arrow.lineTo(21, 12.5)
    painter.drawPath(arrow)
    painter.drawLine(QPointF(3, 21), QPointF(21, 21))


def _leads(painter: QPainter) -> None:
    funnel = QPainterPath(QPointF(3, 4))
    for x, y in ((21, 4), (14, 12.5), (14, 19), (10, 21), (10, 12.5)):
        funnel.lineTo(x, y)
    funnel.closeSubpath()
    painter.drawPath(funnel)


def _clients(painter: QPainter) -> None:
    painter.drawEllipse(QRectF(5.5, 4, 7, 7))
    painter.drawArc(QRectF(2.5, 13, 13, 12), 0, 180 * 16)
    painter.drawEllipse(QRectF(14.5, 5.5, 5.5, 5.5))
    painter.drawArc(QRectF(13.5, 13.5, 9, 9), 0, 180 * 16)


_DRAWERS: dict[str, Callable[[QPainter], None]] = {
    "dashboard": _dashboard,
    "sales": _sales,
    "leads": _leads,
    "clients": _clients,
}


def _pixmap(name: str, color: QColor, size: int) -> QPixmap:
    pixmap = QPixmap(size * _SCALE, size * _SCALE)
    pixmap.setDevicePixelRatio(_SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / _CANVAS, size / _CANVAS)
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _DRAWERS[name](painter)
    painter.end()
    return pixmap


def navigation_icon(name: str, color: str, checked_color: str, size: int = 20) -> QIcon:
    """Return an icon drawn in ``color``, and in ``checked_color`` when its button is checked."""
    icon = QIcon()
    normal = _pixmap(name, QColor(color), size)
    checked = _pixmap(name, QColor(checked_color), size)
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
        icon.addPixmap(normal, mode, QIcon.State.Off)
        icon.addPixmap(checked, mode, QIcon.State.On)
    return icon


NAVIGATION_ICON_NAMES = tuple(_DRAWERS)

__all__ = ["NAVIGATION_ICON_NAMES", "navigation_icon"]
