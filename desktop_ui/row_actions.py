"""Painted per-row action buttons for large Qt tables.

Creating a ``QToolButton`` with ``setCellWidget`` for every row is O(rows) in
widgets, style polishing and layout work: filtering 5,000 leads took about half
a second per keystroke. ``RowActionDelegate`` paints the same buttons and
hit-tests clicks, so its cost is proportional to the rows actually on screen.
Keyboard users reach the same actions through ``install_row_action_menu``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QHelpEvent, QMouseEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
)

from .theme import ERROR, ERROR_ON_DARK

_PADDING_X = 10
_SPACING = 6
_MARGIN = 6
_BUTTON_HEIGHT = 26


@dataclass(frozen=True)
class RowAction:
    key: str
    label: str
    tooltip: str = ""
    destructive: bool = False


class RowActionDelegate(QStyledItemDelegate):
    """Paint ``actions`` as buttons in one column and emit ``triggered(key, record_id)``."""

    triggered = Signal(str, str)

    def __init__(
        self,
        actions: Sequence[RowAction],
        *,
        id_role: int,
        view: QAbstractItemView,
    ) -> None:
        super().__init__(view)
        self.actions = tuple(actions)
        self._id_role = id_role
        self._view = view
        self._hovered: tuple[int, int] | None = None  # (row, action index)
        view.setMouseTracking(True)

    # ------------------------------------------------------------ geometry

    def _button_rects(self, cell: QRect, option: QStyleOptionViewItem) -> list[QRect]:
        metrics = option.fontMetrics
        height = min(_BUTTON_HEIGHT, max(cell.height() - 6, 16))
        top = cell.top() + (cell.height() - height) // 2
        left = cell.left() + _MARGIN
        rects = []
        for action in self.actions:
            width = metrics.horizontalAdvance(action.label) + 2 * _PADDING_X
            rects.append(QRect(left, top, width, height))
            left += width + _SPACING
        return rects

    def _width_for(self, metrics: QFontMetrics) -> int:
        width = sum(metrics.horizontalAdvance(a.label) + 2 * _PADDING_X for a in self.actions)
        return width + _SPACING * (len(self.actions) - 1) + 2 * _MARGIN

    def column_width(self) -> int:
        """Width for a fixed-size action column, computed once instead of per row."""
        return self._width_for(self._view.fontMetrics())

    def sizeHint(  # noqa: N802
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(self._width_for(option.fontMetrics), _BUTTON_HEIGHT + 8)

    def _hit(self, option: QStyleOptionViewItem, position: QPoint) -> int | None:
        for action_index, rect in enumerate(self._button_rects(option.rect, option)):
            if rect.contains(position):
                return action_index
        return None

    # ------------------------------------------------------------ painting

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        style = option.widget.style() if option.widget else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget)

        palette = option.palette
        dark_surface = palette.color(QPalette.ColorRole.Base).lightness() < 128
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for action_index, (action, rect) in enumerate(
            zip(self.actions, self._button_rects(option.rect, option))
        ):
            hovered = self._hovered == (index.row(), action_index)
            accent = (
                QColor(ERROR_ON_DARK if dark_surface else ERROR)
                if action.destructive
                else palette.color(QPalette.ColorRole.Text)
            )
            border = accent if action.destructive else palette.color(QPalette.ColorRole.Mid)
            fill = palette.color(QPalette.ColorRole.Base)
            if hovered:
                fill = QColor(accent)
                fill.setAlpha(36)
            painter.setPen(QPen(border, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 6, 6)
            painter.setPen(accent)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, action.label)
        painter.restore()

    # ------------------------------------------------------------ interaction

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if isinstance(event, QMouseEvent):
            hit = self._hit(option, event.position().toPoint())
            hovered = (index.row(), hit) if hit is not None else None
            if hovered != self._hovered:
                self._hovered = hovered
                self._view.viewport().update()
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and hit is not None
            ):
                self.triggered.emit(self.actions[hit].key, str(index.data(self._id_role) or ""))
                return True
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick) and hit is not None:
                return True  # a button press must not also start a row double-click
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event: QHelpEvent, view, option, index) -> bool:  # noqa: N802
        hit = self._hit(option, event.pos())
        if hit is not None and self.actions[hit].tooltip:
            QToolTip.showText(event.globalPos(), self.actions[hit].tooltip, view)
            return True
        return super().helpEvent(event, view, option, index)


def install_row_action_menu(
    view: QAbstractItemView,
    actions: Sequence[RowAction],
    record_id: Callable[[QModelIndex], str],
    on_triggered: Callable[[str, str], object],
) -> None:
    """Offer the same row actions from a context menu (right-click, Menu key, Shift+F10)."""

    def show_menu(position: QPoint) -> None:
        index = view.indexAt(position)
        if not index.isValid():
            index = view.currentIndex()
        if not index.isValid():
            return
        identifier = record_id(index)
        menu = QMenu(view)
        for action in actions:
            menu.addAction(action.label, partial(on_triggered, action.key, identifier))
        menu.exec(view.viewport().mapToGlobal(position))
        menu.deleteLater()  # one menu per right-click would otherwise accumulate

    view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    view.customContextMenuRequested.connect(show_menu)


__all__ = ["RowAction", "RowActionDelegate", "install_row_action_menu"]
