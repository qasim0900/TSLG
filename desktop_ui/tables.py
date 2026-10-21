"""Shared look and behaviour of every table in the application.

``prepare_table()`` gives a table the house style: no grid lines, comfortable
rows, headers aligned with their values (numbers right), a highlighted row
under the mouse, a calm selection marked by a brand-green edge, Ctrl+C to copy
the selected rows, and a message inside the table when it is empty.

``TableDelegate`` draws stage, status, and priority values as coloured labels
("badges") from one tone table, so the same word looks the same in every list.
The cell text is unchanged, so sorting, searching, copying, and screen readers
keep working with the plain words.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QPoint, QRect, QRectF, QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QHelpEvent, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QToolTip,
    QWidget,
)

from branding import PARENT_BRAND, PRODUCT_NAME

from .theme import PRIMARY, PRIMARY_DARK

ROW_HEIGHT = 40
MAX_AUTO_COLUMN_WIDTH = 360
_HOVER_PROPERTY = "hoverRow"

# Tones: (background, text) for light and for dark surfaces; every pair is >= 4.5:1.
_TONES: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "neutral": (("#ECEEF0", "#3A4046"), ("#2B3533", "#D8DEDB")),
    "info": (("#E2ECF8", "#1E4C7A"), ("#1B3150", "#BBD5F4")),
    "success": (("#DFF1E3", "#1D5E28"), ("#183C22", "#A9E2B4")),
    "warning": (("#FFF1CC", "#6E5000"), ("#3E3216", "#FFD86E")),
    "danger": (("#FBE3E3", "#8E1B1B"), ("#4A2020", "#FFB4AB")),
}

# One meaning per word, whichever list it appears in.
BADGE_TONES: dict[str, str] = {
    # Lead stages (domain.lead_stages)
    "lead": "neutral", "contacted": "info", "meeting": "warning", "qualified": "success",
    "nurture": "neutral", "client": "success", "lost": "danger",
    # Priorities
    "low": "neutral", "medium": "info", "high": "warning", "urgent": "danger",
    # Tasks
    "open": "info", "done": "success", "cancelled": "neutral",
    # Client accounts
    "prospect": "info", "active client": "success", "former client": "neutral", "not a fit": "danger",
    # User accounts
    "active": "success", "inactive": "neutral", "invited (no password yet)": "warning",
}


def tone_for(text: str) -> str | None:
    return BADGE_TONES.get(text.strip().casefold())


def _is_dark(widget: QWidget | None) -> bool:
    palette = widget.palette() if widget is not None else QGuiApplication.palette()
    return palette.color(QPalette.ColorRole.Base).lightness() < 128


def _hover_color(widget: QWidget | None) -> QColor:
    return QColor("#1A2B28") if _is_dark(widget) else QColor("#F1F6F1")


class TableDelegate(QStyledItemDelegate):
    """Row hover, the selection edge, and badges for the columns listed in ``badge_columns``."""

    def __init__(self, view: QAbstractItemView, badge_columns: Iterable[int] = ()) -> None:
        super().__init__(view)
        self._view = view
        self.badge_columns = set(badge_columns)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex | QPersistentModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # A selected row is already highlighted, so a box around one of its cells is noise;
        # elsewhere (Ctrl+arrow in multi-select lists) the box still shows the keyboard position.
        if opt.state & QStyle.StateFlag.State_Selected:
            opt.state &= ~QStyle.StateFlag.State_HasFocus
        view = self._view
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        paint_hover(painter, opt.rect, view, index.row(), selected)
        style = view.style()
        tone = tone_for(opt.text) if index.column() in self.badge_columns and opt.text else None
        if tone is None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, view)
        else:
            text = opt.text
            opt.text = ""
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, view)
            draw_badge(painter, opt.rect, text, tone, _is_dark(view), opt.font)
        if selected and index.column() == first_visible_column(view):
            paint_selection_edge(painter, opt.rect, view)

    def helpEvent(self, event: QHelpEvent, view: QAbstractItemView, option: QStyleOptionViewItem,  # noqa: N802
                  index: QModelIndex | QPersistentModelIndex) -> bool:
        """Show a shortened ("…") cell's full text on hover when it has no tooltip of its own."""
        if event.type() == QEvent.Type.ToolTip and index.isValid() and not index.data(Qt.ItemDataRole.ToolTipRole):
            text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            if text and option.fontMetrics.horizontalAdvance(text) > view.visualRect(index).width() - 24:
                QToolTip.showText(event.globalPos(), text, view)
                return True
        return super().helpEvent(event, view, option, index)


def change_color(widget: QWidget | None, positive: bool) -> QColor:
    """Readable green/red for gains and losses on the current (light or dark) surface."""
    return QColor(_TONES["success" if positive else "danger"][1 if _is_dark(widget) else 0][1])


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
    background, foreground = _TONES[tone][1 if dark else 0]
    painter.save()
    painter.setFont(font)
    metrics = painter.fontMetrics()
    width = min(metrics.horizontalAdvance(text) + 20, max(cell.width() - 12, 24))
    height = min(metrics.height() + 8, cell.height() - 8)
    pill = QRectF(cell.left() + 8, cell.top() + (cell.height() - height) / 2, width, height)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(pill, height / 2, height / 2)
    painter.setPen(QColor(foreground))
    shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(pill.width()) - 16)
    painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, shown)
    painter.restore()


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
        self.setVisible(empty)
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
) -> TableDelegate:
    """Apply the shared table style and behaviour; returns the table's delegate."""
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
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
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    delegate = TableDelegate(table, badge_columns)
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
            width += 14  # a badge's own padding around the text
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
    "BADGE_TONES", "ROW_HEIGHT", "EmptyMessage", "TableDelegate", "align_headers", "change_color", "copy_selection",
    "draw_badge", "enable_column_choice", "fit_columns", "first_visible_column", "paint_hover",
    "paint_selection_edge", "prepare_table", "reset_columns", "set_column_shown", "set_empty_text", "set_header_tips",
    "tone_for",
]
