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

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QHelpEvent, QMouseEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
)

from .icons import pixmap
from .theme import BUTTON_HEIGHT, ERROR, ERROR_ON_DARK, tokens

_PADDING_X = 16  # as the app's other buttons
_SPACING = 6
_MARGIN = 6
_BUTTON_HEIGHT = BUTTON_HEIGHT


@dataclass(frozen=True)
class RowAction:
    key: str
    label: str
    tooltip: str = ""
    destructive: bool = False
    icon: str = ""  # shown as an icon-only button (the label becomes its tooltip)


_ICON_BUTTON = 32  # a borderless glyph's hit area


def _label_font(base: QFont) -> QFont:
    """The app's button lettering (13 px semibold), not the table's."""
    font = QFont(base)
    font.setPixelSize(13)
    font.setWeight(QFont.Weight.DemiBold)
    return font


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
        metrics = QFontMetrics(_label_font(option.font))
        height = min(_BUTTON_HEIGHT, max(cell.height() - 6, 16))
        top = cell.top() + (cell.height() - height) // 2
        left = cell.left() + _MARGIN
        rects = []
        for action in self.actions:
            if action.icon:
                icon_top = cell.top() + (cell.height() - _ICON_BUTTON) // 2
                rects.append(QRect(left, icon_top, _ICON_BUTTON, _ICON_BUTTON))
                left += _ICON_BUTTON + 4
                continue
            width = metrics.horizontalAdvance(action.label) + 2 * _PADDING_X
            rects.append(QRect(left, top, width, height))
            left += width + _SPACING
        return rects

    def _width_for(self, metrics: QFontMetrics) -> int:
        width = 0
        for action in self.actions:
            width += (_ICON_BUTTON + 4) if action.icon else metrics.horizontalAdvance(action.label) + 2 * _PADDING_X
        return width + _SPACING * (len(self.actions) - 1) + 2 * _MARGIN

    def column_width(self) -> int:
        """Width for a fixed-size action column, computed once instead of per row."""
        return self._width_for(QFontMetrics(_label_font(self._view.font())))

    def sizeHint(  # noqa: N802
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(self._width_for(QFontMetrics(_label_font(option.font))), _BUTTON_HEIGHT + 8)

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
        from .tables import row_entrance  # the shared row entrance (tables imports nothing from here)

        entrance = row_entrance(self._view, index.row())
        if entrance is not None and entrance < 1:
            painter.save()
            painter.setOpacity(entrance)
            painter.translate(0, 8 * (1 - entrance))
            self._paint(painter, option, index)
            painter.restore()
            return
        self._paint(painter, option, index)

    def _paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        from .tables import paint_hover  # the shared row hover (tables imports nothing from here)

        paint_hover(painter, option.rect, self._view, index.row(),
                    bool(option.state & QStyle.StateFlag.State_Selected))
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
            if action.icon:
                values = tokens(dark_surface)
                if hovered:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(values["hover"]))
                    painter.drawRoundedRect(rect, 8, 8)
                tint = values["danger"] if action.destructive else values["text2"]
                image = pixmap(action.icon, tint, 18)
                painter.drawPixmap(rect.center().x() - 9 + 1, rect.center().y() - 9 + 1, image)
                continue
            accent = (
                QColor(ERROR_ON_DARK if dark_surface else ERROR)
                if action.destructive
                else palette.color(QPalette.ColorRole.Text)
            )
            values = tokens(dark_surface)
            border = accent if action.destructive else QColor(values["lineStrong"])
            fill = QColor(values["surface"])
            if hovered:
                fill = QColor(accent)
                fill.setAlpha(36)
            painter.setPen(QPen(border, 1))
            painter.setBrush(fill)
            # Drawn like the app's other buttons: same height, radius, border, and lettering.
            painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
            painter.setFont(_label_font(option.font))
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
        if hit is not None and (self.actions[hit].tooltip or self.actions[hit].icon):
            QToolTip.showText(event.globalPos(), self.actions[hit].tooltip or self.actions[hit].label, view)
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
