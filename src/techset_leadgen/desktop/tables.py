"""Shared look and behaviour of every table in the application.

``prepare_table()`` gives a table the house style: no grid lines, comfortable
rows, headers aligned with their values (numbers right), a highlighted row
under the mouse, a calm tinted selection, Ctrl+C to copy the selected rows,
and a message inside the table when it is empty.

``TableDelegate`` draws stage, status, and priority values as coloured labels
("badges") from one tone table, so the same word looks the same in every list.
It can also show a person's initials before their name (avatar columns), IDs
and timestamps in the monospace font, and a second, smaller line under a cell
(``SUBTEXT_ROLE``). The cell text is unchanged, so sorting, searching, copying,
and screen readers keep working with the plain words.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from functools import partial
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    Qt,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QHelpEvent,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from techset_leadgen.branding import PARENT_BRAND, PRODUCT_NAME

from techset_leadgen.desktop.theme import PRIMARY, PRIMARY_DARK, mono_font, tokens
from techset_leadgen.desktop.widgets import badge_colors, initials, paint_badge

ROW_HEIGHT = 52
MAX_AUTO_COLUMN_WIDTH = 360
CELL_INSET = 14  # left padding of cell text, matching the header labels
_HOVER_PROPERTY = "hoverRow"
SUBTEXT_ROLE = Qt.ItemDataRole.UserRole + 65  # a second, smaller line under the cell text
TONE_ROLE = Qt.ItemDataRole.UserRole + 66  # explicit badge tone for one cell

# One meaning per word, whichever list it appears in (tones: neutral, info, success, warning, danger).
BADGE_TONES: dict[str, str] = {
    # Lead stages (domain.lead_stages)
    "lead": "info", "new": "info", "contacted": "neutral", "meeting": "warning", "qualified": "success",
    "nurture": "neutral", "client": "success", "won": "success", "lost": "danger",
    # Priorities
    "low": "neutral", "medium": "warning", "high": "danger", "urgent": "danger",
    # Tasks and meetings
    "open": "info", "done": "success", "cancelled": "neutral", "scheduled": "info",
    # LinkedIn outreach and assignments
    "not contacted": "neutral", "request sent": "info", "connected": "success", "messaged": "info",
    "replied": "success", "meeting requested": "warning", "not interested": "danger",
    "wrong profile": "danger", "planned": "neutral", "assigned": "info", "in progress": "warning",
    "completed": "success", "reassigned": "neutral", "draft": "neutral",
    # Client accounts
    "prospect": "info", "active client": "success", "former client": "neutral", "not a fit": "danger",
    # User accounts and roles
    "active": "success", "inactive": "neutral", "invited (no password yet)": "info", "invited": "info",
    "super admin": "warning", "sales manager": "info", "lead researcher": "success",
    "business development rep": "success", "account executive": "success", "marketing": "success",
    "management (read-only)": "neutral",
    # Audit actions
    "signed in": "success", "signed out": "neutral", "sign-in failed": "danger",
}


_ROWS_PROPERTY = "_rowsEnteredAt"


def animate_rows(table: QAbstractItemView) -> None:
    """Fade and slide the visible rows in, one after another (the design's row entrance)."""
    from techset_leadgen.desktop.motion import animate, reduced_motion

    model = table.model()
    rows = model.rowCount() if model is not None else 0
    if reduced_motion() or not rows or not table.isVisible():
        return
    table.setProperty(_ROWS_PROPERTY, time.monotonic())
    viewport = table.viewport()

    def finished() -> None:
        try:
            table.setProperty(_ROWS_PROPERTY, None)
            viewport.update()
        except RuntimeError:
            pass

    animate(0.0, 1.0, 450 + 35 * min(rows, 13), lambda _value: viewport.update(), owner=table, done=finished)


def row_entrance(view: QAbstractItemView, row: int) -> float | None:
    """Entrance progress (0..1) of ``row`` while its table animates in, else None."""
    started = view.property(_ROWS_PROPERTY)
    if started is None:
        return None
    from techset_leadgen.desktop.motion import EASE

    first = getattr(view, "rowAt", lambda _y: 0)(0)
    position = max(row - max(first, 0), 0)
    elapsed = time.monotonic() - float(started) - 0.035 * min(position, 13)
    return EASE.valueForProgress(max(0.0, min(1.0, elapsed / 0.45)))


def tone_for(text: str) -> str | None:
    return BADGE_TONES.get(text.strip().casefold())


def _is_dark(widget: QWidget | None) -> bool:
    palette = widget.palette() if widget is not None else QGuiApplication.palette()
    return palette.color(QPalette.ColorRole.Base).lightness() < 128


def _hover_color(widget: QWidget | None) -> QColor:
    return QColor(tokens(_is_dark(widget))["rowHover"])


class TableDelegate(QStyledItemDelegate):
    """Row hover, badges, avatars, monospace and two-line cells for the columns that ask for them."""

    def __init__(self, view: QAbstractItemView, badge_columns: Iterable[int] = (), *,
                 avatar_columns: Iterable[int] = (), mono_columns: Iterable[int] = (),
                 strong_columns: Iterable[int] = (), default_tones: Mapping[int, str] | None = None,
                 check_column: int | None = None, large_avatar_columns: Iterable[int] = ()) -> None:
        super().__init__(view)
        self._view = view
        self.check_column = check_column
        self.large_avatar_columns = set(large_avatar_columns)  # 32 px initials (record names) instead of 26
        self.badge_columns = set(badge_columns)
        self.avatar_columns = set(avatar_columns)
        self.mono_columns = set(mono_columns)
        self.strong_columns = set(strong_columns)
        self.default_tones = dict(default_tones or {})

    def _tone(self, index: QModelIndex | QPersistentModelIndex, text: str) -> str | None:
        explicit = index.data(TONE_ROLE)
        if explicit:
            return str(explicit)
        if index.column() not in self.badge_columns or not text:
            return None
        return tone_for(text) or self.default_tones.get(index.column())

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex | QPersistentModelIndex) -> None:
        entrance = row_entrance(self._view, index.row())
        nudge = 2 if self._view.property("hoverNudge") and self._view.property(_HOVER_PROPERTY) == index.row() else 0
        if (entrance is not None and entrance < 1) or nudge:
            painter.save()
            if entrance is not None:
                painter.setOpacity(entrance)
                painter.translate(0, 8 * (1 - entrance))
            if nudge and index.column() == first_visible_column(self._view):
                painter.translate(nudge, 0)
            self._paint(painter, option, index)
            painter.restore()
            return
        self._paint(painter, option, index)

    def _paint(self, painter: QPainter, option: QStyleOptionViewItem,
               index: QModelIndex | QPersistentModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # A selected row is already highlighted, so a box around one of its cells is noise.
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        view = self._view
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        paint_hover(painter, opt.rect, view, index.row(), selected)
        style = view.style()
        column = index.column()
        text = opt.text
        tone = self._tone(index, text)
        subtext = index.data(SUBTEXT_ROLE)
        custom = (tone is not None or column in self.avatar_columns or column in self.mono_columns
                  or column in self.strong_columns or bool(subtext) or column == self.check_column)
        if not custom:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, view)
            return
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, view)
        dark = _is_dark(view)
        cell = QRectF(opt.rect).adjusted(CELL_INSET, 0, -6, 0)
        if column == self.check_column:
            paint_check(painter, check_rect(opt.rect), "on" if selected else "off", dark)
            cell = cell.adjusted(CHECK_SPACE, 0, 0, 0)
        if tone is not None:
            paint_badge(painter, cell, text, tone, dark, opt.font)
            return
        painter.save()
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        color = foreground.color() if isinstance(foreground, QBrush) else (
            foreground if isinstance(foreground, QColor) else opt.palette.color(QPalette.ColorRole.Text))
        if column in self.avatar_columns and text:
            size = 32.0 if column in self.large_avatar_columns else 26.0
            circle = QRectF(cell.left(), cell.center().y() - size / 2, size, size)
            values = tokens(dark)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            unassigned = text.strip() in ("—", "Unassigned", "")
            neutral = unassigned or text.startswith("System")  # system entries: neutral "SY"
            painter.setBrush(QColor(values["muted"] if neutral else values["tint2"]))
            painter.drawEllipse(circle)
            small = QFont(opt.font)
            small.setPixelSize(12 if size > 30 else 10)
            small.setWeight(QFont.Weight.ExtraBold)
            painter.setFont(small)
            painter.setPen(QColor(values["text2"] if neutral else values["primaryInk"]))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, "—" if unassigned else initials(text))
            cell = cell.adjusted(size + 10, 0, 0, 0)
        font = mono_font(12) if column in self.mono_columns else QFont(opt.font)
        if column in self.mono_columns and opt.font.bold():
            font.setBold(True)
        if column in self.strong_columns:
            font.setWeight(QFont.Weight.DemiBold)
        alignment = opt.displayAlignment
        horizontal = alignment & (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignHCenter)
        painter.setPen(color)
        painter.setFont(font)
        if subtext:
            metrics = painter.fontMetrics()
            top = QRectF(cell.left(), cell.center().y() - metrics.height() + 1, cell.width(), metrics.height())
            painter.drawText(top, int(horizontal | Qt.AlignmentFlag.AlignBottom),
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(cell.width())))
            sub_font = mono_font(11) if str(subtext)[:2] in ("L-", "C-") else QFont(opt.font)
            if sub_font.family() == opt.font.family():
                sub_font.setPixelSize(12)
                sub_font.setBold(False)
            painter.setFont(sub_font)
            painter.setPen(QColor(tokens(dark)["text2"]))
            sub_metrics = painter.fontMetrics()
            bottom = QRectF(cell.left(), cell.center().y() + 1, cell.width(), sub_metrics.height())
            painter.drawText(bottom, int(horizontal | Qt.AlignmentFlag.AlignTop),
                             sub_metrics.elidedText(str(subtext), Qt.TextElideMode.ElideRight, int(cell.width())))
        else:
            metrics = painter.fontMetrics()
            painter.drawText(cell, int(horizontal | Qt.AlignmentFlag.AlignVCenter),
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(cell.width())))
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem,  # noqa: N802 - Qt API
                 index: QModelIndex | QPersistentModelIndex) -> Any:
        hint = super().sizeHint(option, index)
        if index.column() == self.check_column:
            hint.setWidth(hint.width() + CHECK_SPACE)
        return hint

    def helpEvent(self, event: QHelpEvent, view: QAbstractItemView, option: QStyleOptionViewItem,  # noqa: N802
                  index: QModelIndex | QPersistentModelIndex) -> bool:
        """Show a shortened ("…") cell's full text on hover when it has no tooltip of its own."""
        if event.type() == QEvent.Type.ToolTip and index.isValid() and not index.data(Qt.ItemDataRole.ToolTipRole):
            text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            if text and option.fontMetrics.horizontalAdvance(text) > view.visualRect(index).width() - 24:
                QToolTip.showText(event.globalPos(), text, view)
                return True
        return super().helpEvent(event, view, option, index)


CHECK_SPACE = 28  # room the selection checkbox takes before the first column's text


def check_rect(cell: QRect) -> QRectF:
    return QRectF(cell.left() + CELL_INSET, cell.top() + (cell.height() - 18) / 2, 18, 18)


def paint_check(painter: QPainter, rect: QRectF, state: str, dark: bool) -> None:
    """A checkbox: "on" (green with a tick), "off" (outline) or "some" (green with a dash)."""
    from techset_leadgen.desktop.icons import pixmap

    values = tokens(dark)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    inner = rect.adjusted(1, 1, -1, -1)
    if state == "off":
        painter.setPen(QPen(QColor(values["lineStrong"]), 2))
        painter.setBrush(QColor(values["surface"]))
        painter.drawRoundedRect(inner, 5, 5)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(values["primary"]))
        painter.drawRoundedRect(inner, 5, 5)
        if state == "on":
            painter.drawPixmap(QPointF(inner.left() + 1, inner.top() + 1), pixmap("check", values["onPrimary"], 14, 3))
        else:
            painter.setPen(QPen(QColor(values["onPrimary"]), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(inner.left() + 4.5, inner.center().y()), QPointF(inner.right() - 4.5,
                                                                                         inner.center().y()))
    painter.restore()


class CheckHeader(QHeaderView):
    """A horizontal header whose first section starts with a select-all checkbox."""

    def __init__(self, table: QTableWidget, column: int = 0) -> None:
        super().__init__(Qt.Orientation.Horizontal, table)
        self._table = table
        self._column = column
        self.setSectionsClickable(True)

    def _state(self) -> str:
        rows = self._table.rowCount()
        selection = self._table.selectionModel()
        chosen = len(selection.selectedRows()) if selection is not None else 0
        return "off" if not rows or not chosen else "on" if chosen >= rows else "some"

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:  # noqa: N802 - Qt API
        if logical_index != self._column:
            super().paintSection(painter, rect, logical_index)
            return
        painter.save()
        super().paintSection(painter, rect.adjusted(CHECK_SPACE, 0, 0, 0), logical_index)
        painter.restore()
        values = tokens(_is_dark(self))
        painter.fillRect(QRect(rect.left(), rect.top(), CHECK_SPACE + CELL_INSET, rect.height() - 1),
                         QColor(values["surface2"]))
        painter.fillRect(QRect(rect.left(), rect.bottom(), CHECK_SPACE + CELL_INSET, 1), QColor(values["line"]))
        paint_check(painter, check_rect(rect), self._state(), _is_dark(self))

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        position = event.position().toPoint()
        section = self.logicalIndexAt(position)
        if section == self._column:
            left = self.sectionViewportPosition(section)
            box = check_rect(QRect(left, 0, self.sectionSize(section), self.height())).adjusted(-4, -6, 4, 6)
            if box.contains(QPointF(position)):
                if self._state() == "on":
                    self._table.clearSelection()
                else:
                    self._table.selectAll()
                self.viewport().update()
                event.accept()
                return
        super().mousePressEvent(event)


class _CheckClicks(QObject):
    """A click on a row's checkbox adds or removes that row from the selection (no Ctrl needed)."""

    def __init__(self, table: QTableWidget, column: int) -> None:
        super().__init__(table)
        self._table = table
        self._column = column
        table.viewport().installEventFilter(self)
        table.itemSelectionChanged.connect(lambda: table.horizontalHeader().viewport().update())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            return False
        try:
            position = event.position().toPoint()  # type: ignore[attr-defined]
            index = self._table.indexAt(position)
            if not index.isValid() or index.column() != self._column:
                return False
            box = check_rect(self._table.visualRect(index)).adjusted(-4, -6, 4, 6)
            if not box.contains(QPointF(position)):
                return False
            if event.type() == QEvent.Type.MouseButtonPress:
                selection = self._table.selectionModel()
                selection.select(index, QItemSelectionModel.SelectionFlag.Toggle
                                 | QItemSelectionModel.SelectionFlag.Rows)
            return True
        except RuntimeError:
            return False


class EmptyOverlay(QWidget):
    """The design's empty state (icon, title, text, actions) inside a table while it has no rows."""

    def __init__(self, table: QTableWidget, state: QWidget) -> None:
        super().__init__(table.viewport())
        self._table = table
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(state)
        table.viewport().installEventFilter(self)
        model = table.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
            signal.connect(self.refresh)
        self.refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Resize:
            try:
                self.setGeometry(self._table.viewport().rect())
            except RuntimeError:
                pass
        return False

    def refresh(self, *_args: object) -> None:
        empty = self._table.rowCount() == 0
        self.setVisible(empty)
        if empty:
            self.setGeometry(self._table.viewport().rect())
            self.raise_()


def set_empty_state(table: QTableWidget, state: QWidget, text: str) -> None:
    """Show ``state`` (an :class:`~desktop_ui.widgets.EmptyState`) in the empty table.

    The plain in-table message keeps ``text`` for assistive tools but stays hidden.
    """
    set_empty_text(table, text)
    message = table.viewport().findChild(EmptyMessage)
    if message is not None:
        message.suppressed = True
        message.refresh()
    EmptyOverlay(table, state)


def change_color(widget: QWidget | None, positive: bool) -> QColor:
    """Readable green/red for gains and losses on the current (light or dark) surface."""
    return QColor(badge_colors("success" if positive else "danger", _is_dark(widget))[1])


def paint_hover(painter: QPainter, rect: QRect, view: QAbstractItemView, row: int, selected: bool) -> None:
    if not selected and view.property(_HOVER_PROPERTY) == row:
        painter.fillRect(rect, _hover_color(view))


def paint_selection_edge(painter: QPainter, rect: QRect, view: QAbstractItemView) -> None:
    painter.fillRect(QRect(rect.left(), rect.top(), 3, rect.height()),
                     QColor(PRIMARY if _is_dark(view) else PRIMARY_DARK))


def first_visible_column(view: QAbstractItemView) -> int:
    header = getattr(view, "horizontalHeader", lambda: None)()
    if header is None:
        return 0
    return header.logicalIndex(0) if not header.isSectionHidden(header.logicalIndex(0)) else 0


def draw_badge(painter: QPainter, cell: QRect, text: str, tone: str, dark: bool, font) -> None:
    paint_badge(painter, QRectF(cell).adjusted(CELL_INSET, 0, -6, 0), text, tone, dark, font)


class _HoverTracker(QObject):
    """Remembers the row under the mouse so delegates can highlight the whole row."""

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view = view
        view.setMouseTracking(True)
        view.viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        try:
            if kind == QEvent.Type.MouseMove:
                row = self._view.rowAt(event.position().toPoint().y())  # type: ignore[attr-defined]
                self._set(row)
            elif kind in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._set(-1)
        except RuntimeError:  # the table is being destroyed
            pass
        return False

    def _set(self, row: int) -> None:
        if self._view.property(_HOVER_PROPERTY) != row:
            self._view.setProperty(_HOVER_PROPERTY, row)
            self._view.viewport().update()


class EmptyMessage(QLabel):
    """A message centred inside a table while it has no rows (the table stays in place)."""

    def __init__(self, table: QTableWidget, text: str) -> None:
        super().__init__(text, table.viewport())
        self.setObjectName("tableEmptyMessage")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._table = table
        self.suppressed = False  # a richer empty state is shown instead
        table.viewport().installEventFilter(self)
        model = table.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
            signal.connect(self.refresh)
        self.refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Resize:
            try:
                self._place()
            except RuntimeError:  # the table is being destroyed
                pass
        return False

    def _place(self) -> None:
        area = self._table.viewport().rect()
        margin = 24
        self.setGeometry(area.adjusted(margin, margin, -margin, -margin))

    def refresh(self, *_args: object) -> None:
        empty = self._table.rowCount() == 0
        self.setVisible(empty and not self.suppressed)
        if empty:
            self._place()
            self.raise_()


def copy_selection(table: QTableWidget) -> str:
    """Copy the selected rows (visible columns with text) as tab-separated lines, with a header row."""
    rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
    if not rows:
        return ""
    columns = [column for column in range(table.columnCount())
               if not table.isColumnHidden(column)
               and any((item := table.item(row, column)) is not None and item.text() for row in rows)]
    header = [heading.text() if (heading := table.horizontalHeaderItem(column)) is not None else ""
              for column in columns]
    lines = ["\t".join(header)]
    for row in rows:
        cells = []
        for column in columns:
            item = table.item(row, column)
            cells.append((item.text() if item is not None else "").replace("\t", " ").replace("\n", " "))
        lines.append("\t".join(cells))
    text = "\n".join(lines)
    QGuiApplication.clipboard().setText(text)
    return text


def align_headers(table: QTableWidget, numeric_columns: Iterable[int] = ()) -> None:
    """Headers sit over their values: left for text, right for numbers."""
    numeric = set(numeric_columns)
    for column in range(table.columnCount()):
        item = table.horizontalHeaderItem(column)
        if item is None:
            continue
        horizontal = Qt.AlignmentFlag.AlignRight if column in numeric else Qt.AlignmentFlag.AlignLeft
        item.setTextAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)


def set_header_tips(table: QTableWidget, tips: dict[int, str]) -> None:
    for column, tip in tips.items():
        item = table.horizontalHeaderItem(column)
        if item is not None:
            item.setToolTip(tip)


def prepare_table(
    table: QTableWidget,
    *,
    numeric_columns: Iterable[int] = (),
    badge_columns: Iterable[int] = (),
    empty_text: str | None = None,
    multi_select: bool = False,
    row_height: int = ROW_HEIGHT,
    avatar_columns: Iterable[int] = (),
    mono_columns: Iterable[int] = (),
    strong_columns: Iterable[int] = (),
    default_tones: Mapping[int, str] | None = None,
    check_column: int | None = None,
    large_avatar_columns: Iterable[int] = (),
) -> TableDelegate:
    """Apply the shared table style and behaviour; returns the table's delegate.

    ``check_column`` adds the design's selection checkboxes at the start of that column
    (and a select-all box in its header); they show and change the row selection.
    """
    if check_column is not None and not isinstance(table.horizontalHeader(), CheckHeader):
        table.setHorizontalHeader(CheckHeader(table, check_column))
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setFrameShape(QFrame.Shape.NoFrame)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setCornerButtonEnabled(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if multi_select
                           else QAbstractItemView.SelectionMode.SingleSelection)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    vertical = table.verticalHeader()
    vertical.setVisible(False)
    vertical.setDefaultSectionSize(row_height)
    vertical.setMinimumSectionSize(min(row_height, 32))
    # Measure at most 400 rows when sizing columns to their contents (large lists stay fast).
    vertical.setResizeContentsPrecision(400)
    header = table.horizontalHeader()
    header.setResizeContentsPrecision(400)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    header.setMinimumSectionSize(48)
    header.setFixedHeight(42)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    delegate = TableDelegate(table, badge_columns, avatar_columns=avatar_columns, mono_columns=mono_columns,
                             strong_columns=strong_columns, default_tones=default_tones, check_column=check_column,
                             large_avatar_columns=large_avatar_columns)
    if check_column is not None and table.findChild(_CheckClicks) is None:
        _CheckClicks(table, check_column)
    table.setItemDelegate(delegate)
    table.setProperty("numericColumns", sorted(set(numeric_columns)))
    align_headers(table, numeric_columns)
    if table.findChild(_HoverTracker) is None:
        _HoverTracker(table)
    if empty_text is not None:
        existing = table.viewport().findChild(EmptyMessage)
        if existing is None:
            EmptyMessage(table, empty_text)
        else:
            existing.setText(empty_text)
    if not table.property("copyShortcut"):  # one shortcut per table, or Qt treats Ctrl+C as ambiguous
        shortcut = QShortcut(QKeySequence.StandardKey.Copy, table)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(lambda: copy_selection(table))
        table.setProperty("copyShortcut", True)
    return delegate


def _settings() -> QSettings:
    # Explicit defaultFormat(), as in ThemeManager, so tests' settings redirects apply.
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, PARENT_BRAND, PRODUCT_NAME)


def enable_column_choice(table: QTableWidget, key: str, *, locked: Iterable[int] = (),
                         hidden_by_default: Iterable[int] = ()) -> None:
    """Right-click the header to show or hide columns; remembered under ``key``.

    ``locked`` columns (the first column, row actions) are always shown.
    """
    table.setProperty("columnKey", key)
    table.setProperty("lockedColumns", sorted(set(locked)))
    table.setProperty("defaultHidden", sorted(set(hidden_by_default)))
    stored = _settings().value(f"tables/{key}/hidden")
    labels = _column_labels(table)
    if stored is None:
        hidden = set(hidden_by_default)
    else:
        names = {stored} if isinstance(stored, str) else set(stored or ())
        hidden = {column for column, text in labels.items() if text in names}
    for column in range(table.columnCount()):
        table.setColumnHidden(column, column in hidden and column not in set(locked))
    header = table.horizontalHeader()
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    header.setToolTip("Right-click to choose columns")
    if not table.property("columnMenu"):
        header.customContextMenuRequested.connect(partial(_show_column_menu, table))
        table.setProperty("columnMenu", True)


def _column_labels(table: QTableWidget) -> dict[int, str]:
    return {column: item.text() for column in range(table.columnCount())
            if (item := table.horizontalHeaderItem(column)) is not None and item.text()}


def _show_column_menu(table: QTableWidget, position: QPoint) -> None:
    menu = QMenu(table)
    menu.setToolTipsVisible(True)
    locked = set(table.property("lockedColumns") or ())
    menu.addSection("Show columns")
    for column, text in _column_labels(table).items():
        if column in locked:
            continue
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(not table.isColumnHidden(column))
        action.toggled.connect(partial(set_column_shown, table, column))
    menu.addSeparator()
    reset = menu.addAction("Reset columns")
    reset.triggered.connect(partial(reset_columns, table))
    menu.exec(table.horizontalHeader().mapToGlobal(position))
    menu.deleteLater()


def set_column_shown(table: QTableWidget, column: int, shown: bool) -> None:
    table.setColumnHidden(column, not shown)
    _remember_columns(table)


def reset_columns(table: QTableWidget, *_args: object) -> None:
    default = set(table.property("defaultHidden") or ())
    for column in range(table.columnCount()):
        table.setColumnHidden(column, column in default)
    key = table.property("columnKey")
    if key:
        _settings().remove(f"tables/{key}/hidden")
    _refit(table)


def _remember_columns(table: QTableWidget) -> None:
    key = table.property("columnKey")
    if key:
        hidden = [text for column, text in _column_labels(table).items() if table.isColumnHidden(column)]
        _settings().setValue(f"tables/{key}/hidden", hidden)
    _refit(table)


def _refit(table: QTableWidget) -> None:
    fitter = table.findChild(_ColumnFitter)
    if fitter is not None:
        fitter.apply()


def fit_table_height(table: QTableWidget, *, max_rows: int = 12, min_rows: int = 3) -> None:
    """Size a table to its rows (scrolling inside after ``max_rows``) instead of a fixed box."""
    rows = min(max(table.rowCount(), min_rows), max_rows)
    vertical = table.verticalHeader()
    height = table.horizontalHeader().height() + rows * vertical.defaultSectionSize() + 4
    if not table.rowCount() and table.viewport().findChild(EmptyOverlay) is not None:
        height = max(height, 340)  # room for the empty state's icon, text and buttons
    scroll_bar = table.horizontalScrollBar()
    if scroll_bar.maximum() > 0:
        height += scroll_bar.sizeHint().height()
    table.setMinimumHeight(0)
    table.setFixedHeight(height)


def set_empty_text(table: QTableWidget, text: str) -> None:
    message = table.viewport().findChild(EmptyMessage)
    if message is None:
        EmptyMessage(table, text)
    else:
        message.setText(text)
        message.refresh()


def fit_columns(table: QTableWidget, *, stretch_column: int | None = None,
                fixed_columns: dict[int, int] | None = None, max_width: int = MAX_AUTO_COLUMN_WIDTH,
                min_widths: dict[int, int] | None = None, keep_columns: Iterable[int] = ()) -> None:
    """Size columns to their contents (capped), stretch one, and fix action columns.

    When the columns are wider than the table, text columns give up width in proportion
    to how wide they are (long text is shortened with "…" and shown in full on hover), so
    the last columns and the row actions stay on screen. Nothing shrinks below its header
    or ``min_widths``, and ``keep_columns`` (like numbers and badges) are never shortened;
    past that point the table scrolls sideways.
    """
    header = table.horizontalHeader()
    fixed = fixed_columns or {}
    delegate = table.itemDelegate()
    badge_columns = delegate.badge_columns if isinstance(delegate, TableDelegate) else set()
    avatar_columns = delegate.avatar_columns if isinstance(delegate, TableDelegate) else set()
    natural: dict[int, int] = {}
    for column in range(table.columnCount()):
        if column in fixed:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(column, fixed[column])
            continue
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        table.resizeColumnToContents(column)
        width = max(header.sectionSize(column), header.sectionSizeHint(column)) + 6
        if column in badge_columns:
            width += 26  # a badge's dot and padding around the text
        if column in avatar_columns:
            width += 36  # the initials circle before the name
        natural[column] = min(width, max_width)
    numeric = set(table.property("numericColumns") or ())
    fitter = table.findChild(_ColumnFitter)
    if fitter is None:
        fitter = _ColumnFitter(table)
    fitter.configure(natural, fixed, stretch_column, min_widths or {}, badge_columns | numeric | set(keep_columns))


class _ColumnFitter(QObject):
    """Re-fits a table's columns to its width whenever the table is resized."""

    SHORT = 120  # values up to this wide (dates, names, labels) are never shortened

    def __init__(self, table: QTableWidget) -> None:
        super().__init__(table)
        self._table = table
        self._natural: dict[int, int] = {}
        self._fixed: dict[int, int] = {}
        self._stretch: int | None = None
        self._minimum: dict[int, int] = {}
        self._protected: set[int] = set()  # badge and number columns keep their width
        self._busy = False
        table.viewport().installEventFilter(self)

    def configure(self, natural: dict[int, int], fixed: dict[int, int], stretch: int | None,
                  minimum: dict[int, int], protected: set[int]) -> None:
        self._natural, self._fixed, self._stretch = natural, fixed, stretch
        self._minimum, self._protected = minimum, set(protected)
        self.apply()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Resize and self._natural:
            try:
                self.apply()
            except RuntimeError:  # the table is being destroyed
                pass
        return False

    def widths(self, available: int) -> dict[int, int]:
        """Column widths that fit ``available`` pixels where possible.

        The widest columns give up width first: every column is capped at one common
        width, as high as still fits. Short values (dates, amounts, labels) are never cut,
        numbers and badges keep their width, and nothing goes below ``min_widths``.
        """
        table = self._table
        visible = {column: width for column, width in self._natural.items() if not table.isColumnHidden(column)}
        fixed_total = sum(width for column, width in self._fixed.items() if not table.isColumnHidden(column))
        target = available - fixed_total
        if sum(visible.values()) <= target or available < 160:  # fits, or not laid out yet
            return dict(visible)
        floors = {}
        for column, width in visible.items():
            floor = self.SHORT if column not in self._protected else width
            floors[column] = min(width, max(floor, self._minimum.get(column, 0)))

        def total(cap: int) -> int:
            return sum(max(floors[column], min(width, cap)) for column, width in visible.items())

        low, high = 0, max(visible.values())
        while low < high:  # the highest cap that still fits
            middle = (low + high + 1) // 2
            if total(middle) <= target:
                low = middle
            else:
                high = middle - 1
        return {column: max(floors[column], min(width, low)) for column, width in visible.items()}

    def apply(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            table = self._table
            header = table.horizontalHeader()
            available = table.viewport().width()
            widths = self.widths(available)
            fixed_total = sum(width for column, width in self._fixed.items() if not table.isColumnHidden(column))
            fits = fixed_total + sum(widths.values()) <= available
            for column, width in widths.items():
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
                header.resizeSection(column, width)
            # A stretched column fills spare width; when nothing is spare it keeps its own
            # width (Qt would otherwise squeeze it to the minimum, e.g. "Glo…").
            if self._stretch is not None and fits:
                header.setSectionResizeMode(self._stretch, QHeaderView.ResizeMode.Stretch)
            header.setStretchLastSection(self._stretch is None and fits)
        finally:
            self._busy = False


__all__ = [
    "BADGE_TONES", "CELL_INSET", "CheckHeader", "EmptyOverlay", "ROW_HEIGHT", "set_empty_state", "SUBTEXT_ROLE", "TONE_ROLE", "animate_rows", "row_entrance", "EmptyMessage", "TableDelegate", "align_headers", "change_color", "copy_selection",
    "draw_badge", "enable_column_choice", "fit_columns", "fit_table_height", "first_visible_column", "paint_hover",
    "paint_selection_edge", "prepare_table", "reset_columns", "set_column_shown", "set_empty_text", "set_header_tips",
    "tone_for",
]
