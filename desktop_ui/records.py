"""Paged record lists with a detail panel, used by the Tasks, Users, and Audit log screens.

Lists are paged and sorted by the database (the services whitelist sort keys),
so a screen stays fast with tens of thousands of records. A ``RecordPage``
supplies the columns, filters, and what to show for one record; this module
supplies search-as-you-type, paging, sorting, selection, and the detail panel.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from crm.services.access import Actor
from crm.services.pagination import Page, PageRequest

from .tables import change_color, enable_column_choice, fit_columns, set_empty_text, set_header_tips
from .widgets import set_table_defaults
from .support import attempt
from .session import AppContext

ID_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    sort: str | None = None  # the service's sort key; None means not sortable
    badge: bool = False  # shown as a coloured label (stage, status, priority)
    numeric: bool = False  # right-aligned
    alert: bool = False  # coloured as a warning on "alert" rows (e.g. the due date of an overdue task)
    keep: bool = False  # never shortened when space is short (dates, short labels)
    tip: str = ""  # header tooltip


@dataclass(frozen=True)
class Row:
    id: str
    cells: Sequence[str]
    tooltip: str = ""
    emphasis: str = ""  # "", "muted" (archived, closed), or "alert" (overdue, do-not-contact)


@dataclass(frozen=True)
class RowPage:
    rows: list[Row]
    page: int
    pages: int
    total: int
    first: int
    last: int

    @classmethod
    def build(cls, page: Page[Any], convert: Callable[[Any], Row]) -> RowPage:
        return cls([convert(item) for item in page.items], page.page, page.pages, page.total,
                   page.first_index, page.last_index)


@dataclass
class DetailTab:
    title: str
    columns: Sequence[str]
    rows: Sequence[Sequence[str]]
    empty: str = "Nothing recorded yet."
    badges: Sequence[int] = ()  # columns shown as coloured labels


@dataclass
class DetailView:
    id: str
    title: str
    subtitle: str = ""
    fields: Sequence[tuple[str, str]] = ()
    tabs: Sequence[DetailTab] = ()
    allowed: set[str] = field(default_factory=set)  # actions the user may take on this record
    data: dict[str, Any] = field(default_factory=dict)  # values the page's actions need (version, ...)


class RecordList(QWidget):
    """A server-paged, server-sorted table."""

    activated = Signal(str)
    selection_changed = Signal()

    def __init__(self, columns: Sequence[Column], loader: Callable[[PageRequest], RowPage | None], *,
                 noun: str, page_size: int = 50, default_sort: str | None = None, multi: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self._loader = loader
        self._noun = noun
        self._page_size = page_size
        self._page = 1
        self._pages = 1
        self._sort = (default_sort or "").lstrip("-") or None
        self._descending = bool(default_sort and default_sort.startswith("-"))
        self.last_page: RowPage | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setObjectName("recordTable")
        self.table.setHorizontalHeaderLabels([column.label for column in self.columns])
        set_table_defaults(
            self.table,
            badge_columns=[index for index, column in enumerate(self.columns) if column.badge],
            numeric_columns=[index for index, column in enumerate(self.columns) if column.numeric],
            empty_text=f"No {noun} yet.",
            multi_select=multi,
        )
        set_header_tips(self.table, {index: column.tip for index, column in enumerate(self.columns) if column.tip})
        enable_column_choice(self.table, f"records/{noun}", locked=(0,))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._sort_by)
        self.table.setAccessibleName(f"{noun.capitalize()} list")
        self.table.itemActivated.connect(lambda item: self.activated.emit(self._id_at(item.row())))
        self.table.itemSelectionChanged.connect(self.selection_changed.emit)
        layout.addWidget(self.table, 1)

        pager = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("statusMessage")
        self.previous_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        for button in (self.previous_button, self.next_button):
            button.setObjectName("compactButton")
        self.previous_button.clicked.connect(lambda: self.reload(page=self._page - 1))
        self.next_button.clicked.connect(lambda: self.reload(page=self._page + 1))
        pager.addWidget(self.summary, 1)
        pager.addWidget(self.previous_button)
        pager.addWidget(self.next_button)
        layout.addLayout(pager)
        self._show_sort_indicator()

    # ------------------------------------------------------------ loading

    def reload(self, *, page: int | None = None, keep_selection: bool = True) -> bool:
        selected = set(self.selected_ids()) if keep_selection else set()
        number = max(page if page is not None else self._page, 1)
        request = PageRequest(page=number, page_size=self._page_size, sort=self._sort, descending=self._descending)
        result = self._loader(request)
        if result is None:
            return False
        self.last_page = result
        self._page, self._pages = result.page, result.pages
        self.table.setUpdatesEnabled(False)
        self.table.clearSelection()
        self.table.setRowCount(len(result.rows))
        warning = change_color(self.table, positive=False)
        for row_index, row in enumerate(result.rows):
            for column_index, value in enumerate(row.cells):
                column = self.columns[column_index] if column_index < len(self.columns) else Column("", "")
                item = QTableWidgetItem(value)
                item.setToolTip(row.tooltip or value)
                if column.numeric:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if row.emphasis == "alert":
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                    if column.alert:
                        item.setForeground(warning)
                elif row.emphasis == "muted" and not column.badge:
                    item.setForeground(self.palette().placeholderText())
                if column_index == 0:
                    item.setData(ID_ROLE, row.id)
                self.table.setItem(row_index, column_index, item)
        for row_index, row in enumerate(result.rows):
            if row.id in selected:
                self.table.selectRow(row_index)
        fit_columns(self.table, max_width=320, min_widths={0: 180},  # the first column names the record
                    keep_columns=[index for index, column in enumerate(self.columns) if column.keep])
        self.table.setUpdatesEnabled(True)
        if result.total:
            self.summary.setText(f"Showing {result.first}–{result.last} of {result.total} {self._noun}")
        else:
            self.summary.setText(f"No {self._noun}")
        self.previous_button.setEnabled(result.page > 1)
        self.next_button.setEnabled(result.page < result.pages)
        self.selection_changed.emit()
        return True

    def set_empty_text(self, message: str) -> None:
        set_empty_text(self.table, message)

    def _sort_by(self, column_index: int) -> None:
        key = self.columns[column_index].sort
        if key is None:
            self._show_sort_indicator()
            return
        if self._sort == key:
            self._descending = not self._descending
        else:
            self._sort, self._descending = key, False
        self._show_sort_indicator()
        self.reload(page=1)

    def _show_sort_indicator(self) -> None:
        header = self.table.horizontalHeader()
        for index, column in enumerate(self.columns):
            if column.sort is not None and column.sort == self._sort:
                order = Qt.SortOrder.DescendingOrder if self._descending else Qt.SortOrder.AscendingOrder
                header.setSortIndicator(index, order)
                return
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    # ------------------------------------------------------------ selection

    def _id_at(self, row: int) -> str:
        item = self.table.item(row, 0)
        return str(item.data(ID_ROLE)) if item is not None else ""

    def ids(self) -> list[str]:
        return [self._id_at(row) for row in range(self.table.rowCount())]

    def selected_ids(self) -> list[str]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self._id_at(row) for row in rows]

    def current_id(self) -> str | None:
        ids = self.selected_ids()
        return ids[0] if ids else None

    def select(self, record_id: str) -> bool:
        for row in range(self.table.rowCount()):
            if self._id_at(row) == record_id:
                self.table.selectRow(row)
                item = self.table.item(row, 0)
                if item is not None:
                    self.table.scrollToItem(item)
                return True
        return False


class DetailPanel(QFrame):
    """Shows one record: key facts, related records in tabs, and the actions allowed on it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        self.action_bar = QWidget()
        self.actions_layout = _FlowRow(self.action_bar)
        layout.addWidget(self.action_bar)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)
        self.placeholder = QLabel()
        self.placeholder.setObjectName("emptyState")
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder, 1)
        self.view: DetailView | None = None
        self.clear("Select a record to see its details.")

    def add_action(self, text: str, handler: Callable[[], object], *, primary: bool = False,
                   destructive: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("dangerButton" if destructive else "primaryButton" if primary else "compactButton")
        # Connect the callable itself: a lambda capturing a dialog's method kept the dialog alive (DEF-026).
        button.clicked.connect(handler)
        self.actions_layout.add(button)
        return button

    def clear(self, message: str) -> None:
        self.view = None
        self.title.setText("")
        self.subtitle.setText("")
        self.title.hide()
        self.subtitle.hide()
        self.action_bar.hide()
        self.tabs.hide()
        self.placeholder.setText(message)
        self.placeholder.show()

    def show_view(self, view: DetailView) -> None:
        self.view = view
        self.placeholder.hide()
        self.title.setText(view.title)
        self.subtitle.setText(view.subtitle)
        self.subtitle.setVisible(bool(view.subtitle))
        self.title.show()
        self.action_bar.show()
        current = self.tabs.currentIndex()
        self.tabs.clear()
        self.tabs.addTab(self._fields_tab(view.fields), "Details")
        for tab in view.tabs:
            self.tabs.addTab(self._table_tab(tab), f"{tab.title} ({len(tab.rows)})")
        self.tabs.setCurrentIndex(max(min(current, self.tabs.count() - 1), 0))
        self.tabs.show()

    @staticmethod
    def _fields_tab(fields: Sequence[tuple[str, str]]) -> QWidget:
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(4, 10, 4, 4)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(7)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for name, value in fields:
            key = QLabel(name)
            key.setObjectName("fieldLabel")
            shown = QLabel(value or "—")
            shown.setWordWrap(True)
            shown.setTextFormat(Qt.TextFormat.PlainText)  # values are user-entered
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            shown.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            form.addRow(key, shown)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        return scroll

    @staticmethod
    def _table_tab(tab: DetailTab) -> QWidget:
        if not tab.rows:
            empty = QLabel(tab.empty)
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            return empty
        table = QTableWidget(len(tab.rows), len(tab.columns))
        table.setHorizontalHeaderLabels(list(tab.columns))
        set_table_defaults(table, badge_columns=tab.badges)
        table.setWordWrap(True)
        for row_index, row in enumerate(tab.rows):
            for column_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(row_index, column_index, item)
        fit_columns(table, max_width=320)
        table.resizeRowsToContents()
        return table


class _FlowRow:
    """Buttons in rows that wrap when the panel is narrow (QHBoxLayout would clip them)."""

    def __init__(self, host: QWidget, per_row: int = 3) -> None:
        self._layout = QVBoxLayout(host)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(6)
        self._per_row = per_row
        self._rows: list[QHBoxLayout] = []

    def add(self, widget: QWidget) -> None:
        if not self._rows or self._rows[-1].count() - 1 >= self._per_row:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addStretch(1)
            self._layout.addLayout(row)
            self._rows.append(row)
        row = self._rows[-1]
        row.insertWidget(row.count() - 1, widget)


class RecordPage(QWidget):
    """Base for Companies, Contacts, Leads, and Tasks: filter bar, paged list, and detail panel."""

    title = ""
    subtitle = ""
    noun = "record"
    plural = "records"
    columns: Sequence[Column] = ()
    default_sort: str | None = None
    multi_select = False
    create_permission = ""
    archivable = False

    status_requested = Signal(str)
    records: RecordList  # created after the filter bar, whose widgets reload it

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName(f"{self.plural}RecordsPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(12)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel(self.title)
        title.setObjectName("pageTitle")
        subtitle = QLabel(self.subtitle)
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        heading.addWidget(title)
        heading.addWidget(subtitle)
        top.addLayout(heading, 1)
        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        top.addLayout(self.toolbar)
        root.addLayout(top)

        self.new_button = QPushButton(f"New {self.noun}")
        self.new_button.setObjectName("primaryButton")
        self.new_button.clicked.connect(self.create_record)
        self.toolbar.addWidget(self.new_button)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {self.plural}")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(f"Search {self.plural}")
        self.search.setMinimumWidth(200)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(lambda: self.records.reload(page=1))
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        filters.addWidget(self.search, 2)
        self.build_filters(filters)
        self.archived_box: QCheckBox | None = None
        if self.archivable:
            self.archived_box = QCheckBox("Archived")
            self.archived_box.setToolTip(f"Show archived {self.plural} instead of active ones")
            self.archived_box.toggled.connect(lambda _on: self.records.reload(page=1))
            filters.addWidget(self.archived_box)
        filters.addStretch(0)
        root.addLayout(filters)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.records = RecordList(self.columns, self._load, noun=self.plural, default_sort=self.default_sort,
                               multi=self.multi_select)
        self.records.set_empty_text(f"No {self.plural} match these filters.")
        self.records.selection_changed.connect(self._selection_changed)
        self.records.activated.connect(lambda _id: self.edit_current())
        self.detail = DetailPanel()
        self.build_actions(self.detail)
        self.splitter.addWidget(self.records)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 2)  # the list gets two thirds of the width
        self.splitter.setStretchFactor(1, 1)
        root.addWidget(self.splitter, 1)
        self._shortcuts = [QShortcut(QKeySequence.StandardKey.Find, self, self.search.setFocus)]
        self._loaded = False

    # ------------------------------------------------------------ hooks

    def build_filters(self, bar: QHBoxLayout) -> None:
        """Add filter widgets to ``bar`` (call ``filter_combo``)."""

    def list_filters(self) -> dict[str, Any]:
        """Keyword arguments for the service's list function (also used by CSV export)."""
        filters: dict[str, Any] = {}
        if self.search.text().strip():
            filters["q"] = self.search.text().strip()
        if self.archived_box is not None and self.archived_box.isChecked():
            filters["archived"] = True
        return filters

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        raise NotImplementedError

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        raise NotImplementedError

    def build_actions(self, panel: DetailPanel) -> None:
        """Create the record's action buttons on ``panel``."""

    def update_actions(self, view: DetailView | None) -> None:
        """Enable the action buttons ``view.allowed`` permits."""

    def update_permissions(self) -> None:
        self.new_button.setVisible(bool(self.create_permission) and self.context.can(self.create_permission))

    def create_record(self) -> None:
        raise NotImplementedError

    def edit_current(self) -> None:
        """Default action for a double-click or Enter on a row."""

    # ------------------------------------------------------------ helpers

    def filter_combo(self, bar: QHBoxLayout, name: str, options: Sequence[tuple[str, str]], *,
                     everything: str) -> QComboBox:
        combo = QComboBox()
        combo.setAccessibleName(name)
        combo.setToolTip(name)
        combo.addItem(everything, None)
        for value, text in options:
            combo.addItem(text, value)
        combo.currentIndexChanged.connect(lambda _index: self.records.reload(page=1))
        bar.addWidget(combo)
        return combo

    @staticmethod
    def set_combo(combo: QComboBox, value: Any) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(index, 0))

    def owner_options(self, include_unassigned: bool = True) -> list[tuple[str, str]]:
        options = [("me", "Mine")]
        if include_unassigned:
            options.append(("none", "Unassigned"))
        return options

    def _load(self, request: PageRequest) -> RowPage | None:
        filters = self.list_filters()
        ok, result = attempt(self, self.context, lambda db, actor: self.fetch(db, actor, request, filters))
        return result if ok else None

    def refresh(self) -> None:
        self.update_permissions()
        self.records.reload()
        self._loaded = True
        if self.detail.view is not None:
            self.show_record(self.detail.view.id, select=False)

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    def apply_filters(self, values: dict[str, str]) -> None:
        """Show the list filtered as requested (used by the overview and search)."""
        self.search.blockSignals(True)
        self.search.setText(values.get("q", ""))
        self.search.blockSignals(False)
        self.set_filter_values(values)
        self.refresh()

    def set_filter_values(self, values: dict[str, str]) -> None:
        """Subclasses set their filter widgets from ``values`` without reloading."""

    def _selection_changed(self) -> None:
        record_id = self.records.current_id()
        if record_id is None:
            if self.detail.view is None or self.detail.view.id not in self.records.ids():
                self.detail.clear(f"Select {_article(self.noun)} {self.noun} to see its details.")
                self.update_actions(None)
            return
        if self.detail.view is None or self.detail.view.id != record_id:
            self.show_record(record_id, select=False)

    def show_record(self, record_id: str, *, select: bool = True) -> None:
        if select:
            self.records.select(record_id)
        ok, view = attempt(self, self.context, lambda db, actor: self.describe(db, actor, record_id))
        if ok and view is not None:
            self.detail.show_view(view)
            self.update_actions(view)
        else:
            self.detail.clear(f"This {self.noun} is no longer available.")
            self.update_actions(None)

    def current_view(self) -> DetailView | None:
        return self.detail.view

    def after_change(self, record_id: str | None, message: str) -> None:
        self.records.reload()
        if record_id:
            self.records.select(record_id)
            self.show_record(record_id, select=False)
        self.status_requested.emit(message)

def _article(noun: str) -> str:
    if noun[:3].lower() in ("use", "uni", "eur"):  # "a user", not "an user"
        return "a"
    return "an" if noun[:1].lower() in "aeiou" else "a"


__all__ = ["Column", "DetailPanel", "DetailTab", "DetailView", "RecordList", "RecordPage", "Row", "RowPage"]
