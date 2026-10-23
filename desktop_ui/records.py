"""Paged record lists with a detail panel, used by the Tasks, Users, and Audit log screens.

Lists are paged and sorted by the database (the services whitelist sort keys),
so a screen stays fast with tens of thousands of records. A ``RecordPage``
supplies the columns, filters, and what to show for one record; this module
supplies search-as-you-type, paging, sorting, selection, and the detail panel.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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

from .icons import set_button_icon
from .tables import animate_rows, change_color, enable_column_choice, fit_columns, set_empty_text, set_header_tips
from .widgets import Alert, Avatar, Badge, Card, DefinitionList, EmptyState, PageHeader, Pager, SearchField, repolish
from .widgets import set_table_defaults
from .support import attempt
from .theme import mono_font, tokens
from .session import AppContext

ID_ROLE = Qt.ItemDataRole.UserRole
PAGE_SIZES = (10, 25, 50, 100)


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
    avatar: bool = False  # a person: initials before the name
    mono: bool = False  # IDs and timestamps in the monospace font
    tone: str = ""  # badge tone for values the shared tone table does not know
    strong: bool = False  # semibold text (record titles, due dates)
    muted: bool = False  # secondary text colour (emails, "about")


@dataclass(frozen=True)
class Row:
    id: str
    cells: Sequence[str]
    tooltip: str = ""
    emphasis: str = ""  # "", "muted" (archived, closed), "alert" (overdue), or "failed" (tinted row)
    colors: Mapping[int, str] = field(default_factory=dict)  # column -> colour token ("danger", "goldInk")


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
    badges: Sequence[tuple[str, str]] = ()  # (text, tone) shown above the title; the last sits on the right
    avatar: str = ""  # a person's name: their initials are shown beside the title
    badge_fields: Mapping[str, str] = field(default_factory=dict)  # field name -> tone: shown as a badge
    links: Mapping[str, str] = field(default_factory=dict)  # field name -> action key for ``link_activated``
    notes: str = ""  # a "Notes" block under the facts
    notice: str = ""  # an information alert under the facts
    closable: bool = False  # a close button clears the selection


class RecordList(QWidget):
    """A server-paged, server-sorted table with a pager footer."""

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
        layout.setSpacing(0)
        self.card = Card()
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        card_layout.setSpacing(0)
        self._card_layout = card_layout
        self.empty_state: EmptyState | None = None
        layout.addWidget(self.card)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setObjectName("recordTable")
        self.table.setHorizontalHeaderLabels([column.label for column in self.columns])
        set_table_defaults(
            self.table,
            badge_columns=[index for index, column in enumerate(self.columns) if column.badge],
            numeric_columns=[index for index, column in enumerate(self.columns) if column.numeric],
            avatar_columns=[index for index, column in enumerate(self.columns) if column.avatar],
            mono_columns=[index for index, column in enumerate(self.columns) if column.mono],
            large_avatar_columns=[index for index, column in enumerate(self.columns)
                                  if column.avatar and column.strong],
            default_tones={index: column.tone for index, column in enumerate(self.columns) if column.tone},
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
        card_layout.addWidget(self.table, 1)

        footer = QFrame()
        footer.setObjectName("cardFooter")
        pager = QHBoxLayout(footer)
        pager.setContentsMargins(16, 10, 16, 10)
        pager.setSpacing(6)
        self.summary = QLabel()
        self.summary.setObjectName("sectionSubtitle")
        self.pager = Pager()
        self.pager.page_requested.connect(lambda number: self.reload(page=number))
        self.previous_button = self.pager.previous_button
        self.next_button = self.pager.next_button
        self.size_combo = QComboBox()
        self.size_combo.setAccessibleName("Rows per page")
        for size in PAGE_SIZES:
            self.size_combo.addItem(f"{size} / page", size)
        self.size_combo.setCurrentIndex(max(self.size_combo.findData(page_size), 0))
        self.size_combo.currentIndexChanged.connect(self._page_size_changed)
        self.size_combo.setMinimumWidth(120)
        pager.addWidget(self.summary, 1)
        pager.addWidget(self.pager)
        pager.addSpacing(8)
        pager.addWidget(self.size_combo)
        card_layout.addWidget(footer)
        self._show_sort_indicator()

    # ------------------------------------------------------------ loading

    def _page_size_changed(self, _index: int) -> None:
        self._page_size = int(self.size_combo.currentData() or 50)
        self.reload(page=1)

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
        failed_row = QColor(tokens()["failRow"])
        for row_index, row in enumerate(result.rows):
            for column_index, value in enumerate(row.cells):
                column = self.columns[column_index] if column_index < len(self.columns) else Column("", "")
                item = QTableWidgetItem(value)
                item.setToolTip(row.tooltip or value)
                if column.mono:  # measured in the font it is painted in, so it is not cut short
                    item.setFont(mono_font(12))
                if column.strong:
                    strong = QFont(item.font())
                    strong.setWeight(QFont.Weight.DemiBold)
                    item.setFont(strong)
                if column.muted:
                    item.setForeground(QColor(tokens()["text2"]))
                if column_index in row.colors:
                    item.setForeground(QColor(tokens().get(row.colors[column_index], row.colors[column_index])))
                if column.numeric:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if row.emphasis in ("alert", "failed"):
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                    if column.alert:
                        item.setForeground(warning)
                    if row.emphasis == "failed":
                        item.setBackground(failed_row)
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
        self.pager.set_state(result.page, result.pages)
        empty = not result.rows and self.empty_state is not None
        self.table.setVisible(not empty)
        if self.empty_state is not None:
            self.empty_state.setVisible(empty)
        self.selection_changed.emit()
        animate_rows(self.table)
        return True

    def set_empty_state(self, title: str, message: str, action: tuple[str, Callable[[], object]] | None = None,
                        icon: str = "tasks") -> EmptyState:
        """Show an empty state (with an optional action) instead of an empty table."""
        state = EmptyState(title, message, icon=icon)
        if action is not None:
            state.add_action(action[0], action[1], primary=True, icon="plus")
        state.hide()
        self._card_layout.insertWidget(1, state, 1)
        self.empty_state = state
        return state

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
    """Shows one record: badges, title, key facts, related records in tabs, and the allowed actions."""

    closed = Signal()
    link_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(320)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("detailBody")
        holder.setStyleSheet("QWidget#detailBody { background: transparent; }")
        scroll.setWidget(holder)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll, 1)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.badge_row = QHBoxLayout()
        self.badge_row.setSpacing(8)
        top.addLayout(self.badge_row, 1)
        self.close_button = QPushButton()
        self.close_button.setObjectName("iconButtonSmall")
        self.close_button.setAccessibleName("Close details")
        self.close_button.setToolTip("Close details")
        set_button_icon(self.close_button, "close", "text2", 16)
        self.close_button.clicked.connect(self.closed.emit)
        top.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        heading = QHBoxLayout()
        heading.setSpacing(14)
        self.avatar = Avatar("", 52)
        heading.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("detailTitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("sectionSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        heading.addLayout(titles, 1)
        layout.addLayout(heading)
        self.fields = DefinitionList(key_width=110)
        layout.addWidget(self.fields)
        self.notes_box = QWidget()
        notes_layout = QVBoxLayout(self.notes_box)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(6)
        notes_caption = QLabel("Notes")
        notes_caption.setObjectName("fieldLabel")
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setTextFormat(Qt.TextFormat.PlainText)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        notes_layout.addWidget(notes_caption)
        notes_layout.addWidget(self.notes)
        layout.addWidget(self.notes_box)
        self.notice = Alert("", "info")
        layout.addWidget(self.notice)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumHeight(220)
        layout.addWidget(self.tabs, 1)
        self.action_bar = QWidget()
        self.actions_layout = _FlowRow(self.action_bar)
        layout.addWidget(self.action_bar)
        self.placeholder = EmptyState("", "", icon="file")
        layout.addWidget(self.placeholder, 1)
        self.stretch = QWidget()
        self.stretch.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.stretch)
        self._badges: list[Badge] = []
        self.view: DetailView | None = None
        self.clear("Select a record to see its details.")

    def add_action(self, text: str, handler: Callable[[], object], *, primary: bool = False,
                   destructive: bool = False, icon: str | None = None, ghost: bool = False) -> QPushButton:
        button = QPushButton(text)
        if destructive:
            button.setObjectName("dangerOutlineButton")
        elif primary:
            button.setObjectName("primaryButton")
        elif ghost:
            button.setObjectName("ghostButton")
        if icon:
            set_button_icon(button, icon, "onPrimary" if primary else "danger" if destructive else "text")
        # Connect the callable itself: a lambda capturing a dialog's method kept the dialog alive (DEF-026).
        button.clicked.connect(handler)
        self.actions_layout.add(button)
        return button

    def _set_badges(self, badges: Sequence[tuple[str, str]]) -> None:
        for badge in self._badges:
            self.badge_row.removeWidget(badge)
            badge.deleteLater()
        self._badges = []
        while self.badge_row.count():
            self.badge_row.takeAt(0)
        for index, (text, tone) in enumerate(badges):
            if index == len(badges) - 1 and len(badges) > 1:
                self.badge_row.addStretch(1)
            badge = Badge(text, tone)
            self._badges.append(badge)
            self.badge_row.addWidget(badge)
        if len(badges) == 1:
            self.badge_row.addStretch(1)

    def clear(self, message: str) -> None:
        self.view = None
        self.title.setText("")
        self.subtitle.setText("")
        self._set_badges(())
        for widget in (self.title, self.subtitle, self.avatar, self.fields, self.action_bar, self.tabs,
                       self.notes_box, self.notice, self.close_button):
            widget.hide()
        self.placeholder.set_text("", message)
        self.placeholder.show()
        self.stretch.hide()

    def show_view(self, view: DetailView) -> None:
        self.view = view
        self.placeholder.hide()
        self._set_badges(view.badges)
        self.title.setText(view.title)
        self.subtitle.setText(view.subtitle)
        self.subtitle.setVisible(bool(view.subtitle))
        self.title.show()
        self.avatar.set_name(view.avatar)
        self.avatar.setVisible(bool(view.avatar))
        self.title.setStyleSheet("font-size: 18px;" if view.avatar else "")
        rows: list[tuple[str, str | QWidget]] = []
        for name, value in view.fields:
            if name in view.badge_fields and value:
                holder = QWidget()
                holder_row = QHBoxLayout(holder)
                holder_row.setContentsMargins(0, 8, 0, 8)
                holder_row.addWidget(Badge(value, view.badge_fields[name]))
                holder_row.addStretch(1)
                rows.append((name, holder))
            elif name in view.links and value:
                link = QLabel(f'<a href="{view.links[name]}">{_escape(value)}</a>')
                link.setTextFormat(Qt.TextFormat.RichText)
                link.setContentsMargins(0, 11, 0, 11)
                link.linkActivated.connect(self.link_activated.emit)
                link.setStyleSheet(f"color: {tokens()['primary']};")
                rows.append((name, link))
            else:
                rows.append((name, value))
        self.fields.set_rows(rows)
        self.fields.setVisible(bool(view.fields))
        self.notes.setText(view.notes)
        self.notes_box.setVisible(bool(view.notes))
        self.notice.set_message(view.notice)
        self.close_button.setVisible(view.closable)
        self.action_bar.show()
        current = self.tabs.currentIndex()
        self.tabs.clear()
        for tab in view.tabs:
            self.tabs.addTab(self._table_tab(tab), f"{tab.title} ({len(tab.rows)})")
        self.tabs.setCurrentIndex(max(min(current, self.tabs.count() - 1), 0))
        self.tabs.setVisible(bool(view.tabs))
        self.stretch.setVisible(not view.tabs)

    @staticmethod
    def _table_tab(tab: DetailTab) -> QWidget:
        if not tab.rows:
            return EmptyState("", tab.empty, icon="file")
        table = QTableWidget(len(tab.rows), len(tab.columns))
        table.setHorizontalHeaderLabels(list(tab.columns))
        set_table_defaults(table, badge_columns=tab.badges, row_height=44)
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
        self._layout.setContentsMargins(0, 6, 0, 0)
        self._layout.setSpacing(8)
        self._per_row = per_row
        self._rows: list[QHBoxLayout] = []

    def add(self, widget: QWidget) -> None:
        if not self._rows or self._rows[-1].count() - 1 >= self._per_row:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addStretch(1)
            self._layout.addLayout(row)
            self._rows.append(row)
        row = self._rows[-1]
        row.insertWidget(row.count() - 1, widget)


class RecordPage(QWidget):
    """Base for Tasks, Users, and the Audit log: filter card, paged list, and detail panel."""

    title = ""
    subtitle = ""
    noun = "record"
    plural = "records"
    columns: Sequence[Column] = ()
    default_sort: str | None = None
    multi_select = False
    create_permission = ""
    create_icon = "plus"
    archivable = False

    status_requested = Signal(str)
    records: RecordList  # created after the filter bar, whose widgets reload it

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName(f"{self.plural}RecordsPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(20)

        self.header = PageHeader(self.title, self.subtitle)
        self.toolbar = self.header.actions_row
        root.addWidget(self.header)

        self.new_button = QPushButton(f"New {self.noun}")
        self.new_button.setObjectName("primaryButton")
        set_button_icon(self.new_button, self.create_icon, "onPrimary")
        self.new_button.clicked.connect(self.create_record)
        self.toolbar.addWidget(self.new_button)

        filter_card = Card()
        filters = QHBoxLayout(filter_card)
        filters.setContentsMargins(20, 16, 20, 16)
        filters.setSpacing(12)
        self.search = SearchField(f"Search {self.plural}")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(f"Search {self.plural}")
        self.search.setMinimumWidth(200)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(lambda: self.records.reload(page=1))
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        filters.addWidget(self.search, 1)
        self.build_filters(filters)
        self.archived_box: QCheckBox | None = None
        if self.archivable:
            self.archived_box = QCheckBox("Archived")
            self.archived_box.setToolTip(f"Show archived {self.plural} instead of active ones")
            self.archived_box.toggled.connect(lambda _on: self.records.reload(page=1))
            filters.addWidget(self.archived_box)
        root.addWidget(filter_card)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(16)
        self.records = RecordList(self.columns, self._load, noun=self.plural, default_sort=self.default_sort,
                                  multi=self.multi_select)
        self.records.set_empty_text(f"No {self.plural} match these filters.")
        self.records.selection_changed.connect(self._selection_changed)
        self.records.activated.connect(lambda _id: self.edit_current())
        self.detail = DetailPanel()
        self.detail.closed.connect(self.close_details)
        self.detail.link_activated.connect(self.open_link)
        self.build_actions(self.detail)
        self.splitter.addWidget(self.records)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([900, 360])
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

    def open_link(self, key: str) -> None:
        """A link in the details (for example a task's lead) was clicked."""

    def close_details(self) -> None:
        self.records.table.clearSelection()
        self.detail.clear(f"Select {_article(self.noun)} {self.noun} to see its details.")
        self.update_actions(None)

    # ------------------------------------------------------------ helpers

    def filter_combo(self, bar: QHBoxLayout, name: str, options: Sequence[tuple[str, str]], *,
                     everything: str) -> QComboBox:
        combo = QComboBox()
        combo.setAccessibleName(name)
        combo.setToolTip(name)
        combo.setMinimumWidth(190)
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

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # Narrow windows stack the detail panel under the list instead of squeezing both.
        vertical = event.size().width() < 900
        orientation = Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            repolish(self.splitter)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _article(noun: str) -> str:
    if noun[:3].lower() in ("use", "uni", "eur"):  # "a user", not "an user"
        return "a"
    return "an" if noun[:1].lower() in "aeiou" else "a"


__all__ = ["Column", "DetailPanel", "DetailTab", "DetailView", "RecordList", "RecordPage", "Row", "RowPage"]
