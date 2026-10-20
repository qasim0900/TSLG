"""PySide6 leads workspace.

The widget deliberately depends on the existing controller and report layers,
not on the retired Flet controls.  It can therefore be embedded in the main
desktop shell or constructed independently in tests.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from controllers.leads_controller import LeadsController
from controllers.leads_filter_controller import (
    ALL_LEADS_DESCRIPTION,
    ALL_SOURCES,
    ALL_STAGES,
    ALL_TIME,
    _DATE_RANGE_OPTIONS,
    _STAGE_STATUS_MAP,
    filter_leads,
)
from domain.source_labels import SOURCE_LABELS
from utils.formatting import format_eur
from reports.report_leads_html import generate_leads_html_report

from .marketing_spend_dialog import MarketingSpendDialog
from ..row_actions import RowAction, RowActionDelegate, install_row_action_menu
from ..widgets import bulk_table_update, labeled_field, sortable_item

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    "new": "Lead",
    "contacted": "Contacted",
    "meeting": "Meeting",
    "converted": "Client",
    "lost": "Lost",
}
_STATUS_VALUES = tuple(_STATUS_LABELS)
SEARCH_DEBOUNCE_MS = 200


def _source_label(value: Any) -> str:
    raw = str(value or "unknown")
    return SOURCE_LABELS.get(raw, raw.replace("_", " ").title())


def _readonly_item(value: Any, *, numeric: float | int | None = None) -> QTableWidgetItem:
    item = sortable_item(str(value if value not in (None, "") else "—"), numeric)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if numeric is not None:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


class _MetricCard(QFrame):
    """Small stylesheet-friendly KPI card used by the responsive grid."""

    def __init__(self, title: str, *, accent: str = "green", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setProperty("accent", accent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(92)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        self._title = QLabel(title)
        self._title.setObjectName("metricLabel")
        self._value = QLabel("0")
        self._value.setObjectName("metricValue")
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        self.setAccessibleName(title)

    def set_value(self, value: str, description: str = "") -> None:
        self._value.setText(value)
        self.setAccessibleDescription(description or f"{self._title.text()}: {value}")
        self.setToolTip(description)


class _OptionalDate(QWidget):
    """A checkable ISO date field which also supports open-ended ranges."""

    changed = Signal()

    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.enabled_box = QCheckBox(label)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setEnabled(False)
        self.enabled_box.setAccessibleName(f"Enable {label.lower()} date")
        self.date_edit.setAccessibleName(label)
        self.enabled_box.toggled.connect(self.date_edit.setEnabled)
        self.enabled_box.toggled.connect(self.changed)
        self.date_edit.dateChanged.connect(self.changed)
        layout.addWidget(self.enabled_box)
        layout.addWidget(self.date_edit)

    def value(self) -> str | None:
        if not self.enabled_box.isChecked():
            return None
        return self.date_edit.date().toString(Qt.DateFormat.ISODate)

    def clear(self) -> None:
        self.enabled_box.setChecked(False)


class LeadEditDialog(QDialog):
    """Edit one lead's pipeline stage and optional meeting date."""

    def __init__(self, lead: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._lead = lead
        self.setWindowTitle(f"Edit lead {lead.get('id', '')}")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setAccessibleName("Edit lead")

        root = QVBoxLayout(self)
        intro = QLabel(
            f"{_source_label(lead.get('source'))}  ·  "
            f"Created {(str(lead.get('created_at') or '')[:10] or '—')}"
        )
        intro.setObjectName("dialogSubtitle")
        root.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.status_combo = QComboBox()
        for value, label in _STATUS_LABELS.items():
            self.status_combo.addItem(label, value)
        current = self.status_combo.findData((lead.get("status") or "new").lower())
        self.status_combo.setCurrentIndex(max(current, 0))
        self.status_combo.setAccessibleName("Lead stage")

        self.has_meeting = QCheckBox("Meeting scheduled")
        meeting_raw = str(lead.get("meeting_date") or "")[:10]
        meeting_date = QDate.fromString(meeting_raw, Qt.DateFormat.ISODate)
        self.meeting_date = QDateEdit(meeting_date if meeting_date.isValid() else QDate.currentDate())
        self.meeting_date.setDisplayFormat("yyyy-MM-dd")
        self.meeting_date.setCalendarPopup(True)
        self.meeting_date.setAccessibleName("Meeting date")
        self.has_meeting.setChecked(bool(meeting_raw))
        self.meeting_date.setEnabled(bool(meeting_raw))
        self.has_meeting.toggled.connect(self.meeting_date.setEnabled)
        form.addRow("Stage", self.status_combo)
        form.addRow(self.has_meeting, self.meeting_date)
        root.addLayout(form)

        hint = QLabel("Meeting date may be cleared. Dates are stored in YYYY-MM-DD format.")
        hint.setWordWrap(True)
        hint.setObjectName("helpText")
        root.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> tuple[str, str | None]:
        status = str(self.status_combo.currentData())
        meeting = (
            self.meeting_date.date().toString(Qt.DateFormat.ISODate)
            if self.has_meeting.isChecked()
            else None
        )
        return status, meeting


class LeadsPage(QWidget):
    """Responsive lead analytics and management page.

    Parameters are injectable to keep the widget straightforward to test.  The
    default controller is the existing pure/application controller; ``refresh``
    is the only method that queries it for a new snapshot.
    """

    notification_requested = Signal(str, str)
    data_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        controller: type[LeadsController] = LeadsController,
        report_generator=generate_leads_html_report,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._report_generator = report_generator
        self._all_leads: list[dict[str, Any]] = []
        self._filtered_leads: list[dict[str, Any]] = []
        self._funnel_stats: dict[str, Any] = {}
        self._sources_data: dict[str, dict[str, Any]] = {}
        self._marketing_summary: dict[str, Any] = {}
        self._marketing_metrics: list[dict[str, Any]] = []
        self._spend_by_source: dict[str, float] = {}
        self._revenue_by_client: dict[str, float] = {}
        self._layout_mode: tuple[int, int, int] | None = None

        self.setObjectName("leadsPage")
        self.setAccessibleName("Leads workspace")
        self._build_ui()
        self._reflow()
        self._install_shortcuts()
        self.refresh()

    @property
    def active_leads(self) -> list[dict[str, Any]]:
        """Return a copy of the current filtered snapshot."""
        return list(self._filtered_leads)

    @property
    def funnel_stats(self) -> dict[str, Any]:
        return dict(self._funnel_stats)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAccessibleName("Scrollable leads content")
        outer.addWidget(scroll)

        self._body = QWidget()
        self._body.setObjectName("pageBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(24, 20, 24, 32)
        self._layout.setSpacing(18)
        scroll.setWidget(self._body)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Leads")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Track pipeline health, source performance, and upcoming meetings.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.export_button = QPushButton("Export HTML")
        self.export_button.setObjectName("primaryButton")
        self.export_button.setToolTip("Export the currently filtered lead snapshot (Ctrl+E)")
        self.export_button.setAccessibleName("Export filtered leads to HTML")
        self.export_button.clicked.connect(self.export_report)
        header.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignTop)
        self._layout.addLayout(header)

        filters_box = QGroupBox("Filters")
        filters_box.setObjectName("card")
        filters_box.setAccessibleDescription("Filter the lead snapshot without modifying the database")
        self._filter_grid = QGridLayout(filters_box)
        self._filter_grid.setContentsMargins(16, 18, 16, 16)
        self._filter_grid.setHorizontalSpacing(12)
        self._filter_grid.setVerticalSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search lead ID, source, or client…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("Search leads")
        self.search_edit.setToolTip("Searches lead ID, source, and client name")
        self.source_combo = QComboBox()
        self.source_combo.setAccessibleName("Filter by source")
        self.stage_combo = QComboBox()
        self.stage_combo.setAccessibleName("Filter by stage")
        self.stage_combo.addItem(ALL_STAGES, ALL_STAGES)
        for label in _STAGE_STATUS_MAP:
            self.stage_combo.addItem(label, label)
        self.quick_range_combo = QComboBox()
        self.quick_range_combo.setAccessibleName("Quick date range")
        for label, _days in _DATE_RANGE_OPTIONS:
            self.quick_range_combo.addItem(label, label)
        self.quick_range_combo.setCurrentIndex(
            self.quick_range_combo.findData(ALL_TIME)
        )
        self.start_date = _OptionalDate("From")
        self.end_date = _OptionalDate("To")
        self.clear_filters_button = QPushButton("Clear filters")
        self.clear_filters_button.setObjectName("secondaryButton")
        self.clear_filters_button.setAccessibleName("Clear all lead filters")

        self._filter_widgets = [
            labeled_field("Search", self.search_edit),
            labeled_field("Source", self.source_combo),
            labeled_field("Stage", self.stage_combo),
            labeled_field("Period", self.quick_range_combo),
            self.start_date,
            self.end_date,
            self.clear_filters_button,
        ]
        self._layout.addWidget(filters_box)

        self.filter_summary = QLabel(ALL_LEADS_DESCRIPTION)
        self.filter_summary.setObjectName("filterSummary")
        self.filter_summary.setTextFormat(Qt.TextFormat.PlainText)  # echoes search text
        self.filter_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.filter_summary.setAccessibleName("Active lead filters")
        self._layout.addWidget(self.filter_summary)

        self._kpi_grid = QGridLayout()
        self._kpi_grid.setHorizontalSpacing(12)
        self._kpi_grid.setVerticalSpacing(12)
        card_specs = (
            ("total", "Total leads", "green"),
            ("meetings", "Meetings", "gold"),
            ("converted", "Converted", "green"),
            ("lead_rate", "Lead → meeting", "blue"),
            ("client_rate", "Meeting → client", "green"),
            ("lost", "Lost", "red"),
            ("new", "Awaiting action", "gold"),
            ("avg_days", "Avg. time to meeting", "blue"),
        )
        self._kpi_cards = {
            key: _MetricCard(label, accent=accent) for key, label, accent in card_specs
        }
        self._layout.addLayout(self._kpi_grid)

        funnel_box = QGroupBox("Conversion funnel")
        funnel_box.setObjectName("card")
        funnel_layout = QVBoxLayout(funnel_box)
        self._funnel_bars: dict[str, QProgressBar] = {}
        for key, label, stage in (
            ("total", "Leads", "lead"),
            ("meetings", "Meetings", "meeting"),
            ("converted", "Clients", "client"),
        ):
            row = QHBoxLayout()
            caption = QLabel(label)
            caption.setMinimumWidth(90)
            bar = QProgressBar()
            bar.setTextVisible(True)
            bar.setProperty("stage", stage)
            bar.setAccessibleName(f"{label} funnel stage")
            row.addWidget(caption)
            row.addWidget(bar, 1)
            funnel_layout.addLayout(row)
            self._funnel_bars[key] = bar
        self.funnel_insight = QLabel()
        self.funnel_insight.setWordWrap(True)
        self.funnel_insight.setObjectName("insightText")
        funnel_layout.addWidget(self.funnel_insight)
        self._layout.addWidget(funnel_box)

        analytics_tabs = QTabWidget()
        analytics_tabs.setObjectName("analyticsTabs")
        analytics_tabs.setAccessibleName("Lead analytics")
        self.source_table = self._make_table(
            ["Source", "Leads", "Meetings", "Clients", "Conversion", "M→C", "Avg. days"],
            "Lead source performance",
        )
        self.source_table.setMinimumHeight(230)
        # Explicit defaults: enabling sorting otherwise re-sorts by column 0, descending.
        self.source_table.sortItems(1, Qt.SortOrder.DescendingOrder)
        analytics_tabs.addTab(self.source_table, "Source performance")
        marketing_tab = QWidget()
        marketing_layout = QVBoxLayout(marketing_tab)
        marketing_layout.setContentsMargins(12, 12, 12, 12)
        marketing_layout.setSpacing(10)
        # Overall efficiency for the active snapshot (restored from the Flet
        # UI's marketing summary); reflowed between 5 and 3 columns.
        self._marketing_summary_grid = QGridLayout()
        marketing_layout.addLayout(self._marketing_summary_grid)
        self._marketing_summary_grid.setHorizontalSpacing(18)
        self._marketing_summary_values: dict[str, QLabel] = {}
        self._marketing_summary_cells: list[QWidget] = []
        for key, caption_text in (
            ("total_spend", "Total spend"),
            ("total_revenue", "Attributed revenue"),
            ("avg_cpl", "Cost per lead"),
            ("avg_cac", "Cost per client"),
            ("overall_roi", "ROI"),
        ):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)
            caption_label = QLabel(caption_text)
            caption_label.setObjectName("metricLabel")
            value_label = QLabel("—")
            value_label.setObjectName("summaryValue")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setAccessibleName(caption_text)
            cell_layout.addWidget(caption_label)
            cell_layout.addWidget(value_label)
            self._marketing_summary_values[key] = value_label
            self._marketing_summary_cells.append(cell)
        spend_row = QHBoxLayout()
        marketing_layout.addLayout(spend_row)
        self.spend_hint = QLabel("")
        self.spend_hint.setObjectName("filterSummary")
        self.spend_hint.setWordWrap(True)
        spend_row.addWidget(self.spend_hint, 1)
        self.manage_spend_button = QPushButton("Manage spend…")
        self.manage_spend_button.setObjectName("secondaryButton")
        self.manage_spend_button.setToolTip("Add, correct, or delete marketing spend records")
        self.manage_spend_button.setAccessibleName("Manage marketing spend records")
        self.manage_spend_button.clicked.connect(self.manage_spend)
        spend_row.addWidget(self.manage_spend_button)
        self.marketing_table = self._make_table(
            ["Source", "Leads", "Clients", "Revenue", "Spend", "CPL", "CAC", "ROI"],
            "Marketing efficiency by source",
        )
        self.marketing_table.setMinimumHeight(230)
        self.marketing_table.sortItems(1, Qt.SortOrder.DescendingOrder)
        marketing_layout.addWidget(self.marketing_table, 1)
        analytics_tabs.addTab(marketing_tab, "Marketing efficiency")
        self.upcoming_list = QListWidget()
        self.upcoming_list.setAccessibleName("Upcoming meetings")
        self.upcoming_list.setAlternatingRowColors(True)
        analytics_tabs.addTab(self.upcoming_list, "Upcoming meetings")
        self._layout.addWidget(analytics_tabs)

        table_box = QGroupBox("Lead management")
        table_box.setObjectName("card")
        table_layout = QVBoxLayout(table_box)
        self.leads_table = self._make_table(
            ["Date", "Source", "Stage", "Meeting", "Client", "Lead ID", "Actions"],
            "Filtered leads",
        )
        self.leads_table.setMinimumHeight(380)
        self.leads_table.sortItems(0, Qt.SortOrder.DescendingOrder)  # newest first
        self.leads_table.verticalHeader().setDefaultSectionSize(36)
        # Enter or double-click opens the editor; the painted button and the
        # context menu offer the same action without a widget per row.
        self.leads_table.activated.connect(self._on_lead_activated)
        self._lead_row_actions = (
            RowAction("edit", "Edit", "Edit stage and meeting date"),
        )
        self._lead_action_delegate = RowActionDelegate(
            self._lead_row_actions, id_role=Qt.ItemDataRole.UserRole, view=self.leads_table
        )
        self._lead_action_delegate.triggered.connect(lambda _key, lead_id: self.edit_lead(lead_id))
        self.leads_table.setItemDelegateForColumn(6, self._lead_action_delegate)
        install_row_action_menu(
            self.leads_table,
            self._lead_row_actions,
            lambda index: str(index.data(Qt.ItemDataRole.UserRole) or ""),
            lambda _key, lead_id: self.edit_lead(lead_id),
        )
        table_layout.addWidget(self.leads_table)
        self.empty_label = QLabel("No leads match the active filters.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAccessibleName("No lead results")
        self.empty_label.hide()
        table_layout.addWidget(self.empty_label)
        self._layout.addWidget(table_box)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusMessage")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Leads status message")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._layout.addWidget(self.status_label)

        # Re-filtering 5,000 leads costs up to ~0.3 s; wait for a typing pause
        # (or Enter) instead of re-rendering on every keystroke.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.apply_filters)
        self.search_edit.textChanged.connect(self._search_timer.start)
        self.search_edit.returnPressed.connect(self.apply_filters)
        self.source_combo.currentIndexChanged.connect(self.apply_filters)
        self.stage_combo.currentIndexChanged.connect(self.apply_filters)
        self.quick_range_combo.currentIndexChanged.connect(self._quick_range_changed)
        self.start_date.changed.connect(self._custom_date_changed)
        self.end_date.changed.connect(self._custom_date_changed)
        self.clear_filters_button.clicked.connect(self.clear_filters)

    def _install_shortcuts(self) -> None:
        self._shortcuts = [
            QShortcut(QKeySequence.StandardKey.Find, self),
            QShortcut(QKeySequence("Ctrl+E"), self),
            QShortcut(QKeySequence.StandardKey.Refresh, self),
        ]
        self._shortcuts[0].activated.connect(self._focus_search)
        self._shortcuts[1].activated.connect(self.export_report)
        self._shortcuts[2].activated.connect(self.refresh)

    def _focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    @staticmethod
    def _make_table(headers: list[str], accessible_name: str) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAccessibleName(accessible_name)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return table

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        width = max(self.width(), 360)
        filter_columns = 1 if width < 620 else (2 if width < 1000 else 4)
        kpi_columns = 2 if width < 720 else 4
        summary_columns = 5 if width >= 1000 else 3
        mode = (filter_columns, kpi_columns, summary_columns)
        if mode == self._layout_mode:
            return
        self._layout_mode = mode

        for widget in self._filter_widgets:
            self._filter_grid.removeWidget(widget)  # takeAt() leaked the item
        for index, widget in enumerate(self._filter_widgets):
            row, column = divmod(index, filter_columns)
            # Bottom-align so the button lines up with the editors, not their labels.
            alignment = Qt.AlignmentFlag.AlignBottom if widget is self.clear_filters_button else Qt.AlignmentFlag(0)
            self._filter_grid.addWidget(widget, row, column, alignment)
        # Reset every column: stretch left on columns from a wider layout would
        # otherwise reserve empty space after switching to fewer columns.
        for column in range(4):
            self._filter_grid.setColumnStretch(column, 1 if column < filter_columns else 0)

        for card in self._kpi_cards.values():
            self._kpi_grid.removeWidget(card)
        for index, card in enumerate(self._kpi_cards.values()):
            row, column = divmod(index, kpi_columns)
            self._kpi_grid.addWidget(card, row, column)
        for column in range(4):
            self._kpi_grid.setColumnStretch(column, 1 if column < kpi_columns else 0)

        for cell in self._marketing_summary_cells:
            self._marketing_summary_grid.removeWidget(cell)
        for index, cell in enumerate(self._marketing_summary_cells):
            row, column = divmod(index, summary_columns)
            self._marketing_summary_grid.addWidget(cell, row, column)
        for column in range(5):
            self._marketing_summary_grid.setColumnStretch(column, 1 if column < summary_columns else 0)

    def refresh(self, preserve_filters: bool = True) -> None:
        """Reload database-backed reference data and reapply active filters."""
        previous_source = self.source_combo.currentData() if preserve_filters else ALL_SOURCES
        try:
            self._all_leads = list(self._controller.get_leads_enriched() or [])
            self._spend_by_source = dict(self._controller.get_spend_by_source() or {})
            self._revenue_by_client = dict(self._controller.get_revenue_by_client() or {})
            sources = sorted(
                {str(lead.get("source")) for lead in self._all_leads if lead.get("source")},
                key=lambda value: _source_label(value).casefold(),
            )
            self.source_combo.blockSignals(True)
            self.source_combo.clear()
            self.source_combo.addItem(ALL_SOURCES, ALL_SOURCES)
            for source in sources:
                self.source_combo.addItem(_source_label(source), source)
            restored = self.source_combo.findData(previous_source)
            self.source_combo.setCurrentIndex(max(restored, 0))
            self.source_combo.blockSignals(False)
            self.apply_filters()
            self._notify(f"Loaded {len(self._all_leads)} leads.", "info")
        except Exception as exc:  # controllers normally contain their own failures
            logger.exception("Could not refresh PySide6 leads page")
            self._all_leads = []
            self.apply_filters()
            self._notify(f"Could not load leads: {exc}", "error")

    def clear_filters(self) -> None:
        widgets = (self.search_edit, self.source_combo, self.stage_combo, self.quick_range_combo)
        for widget in widgets:
            widget.blockSignals(True)
        self.search_edit.clear()
        self.source_combo.setCurrentIndex(0)
        self.stage_combo.setCurrentIndex(0)
        self.quick_range_combo.setCurrentIndex(self.quick_range_combo.findData(ALL_TIME))
        self.start_date.clear()
        self.end_date.clear()
        for widget in widgets:
            widget.blockSignals(False)
        self.apply_filters()

    def _quick_range_changed(self) -> None:
        if self.quick_range_combo.currentData() != ALL_TIME:
            self.start_date.enabled_box.blockSignals(True)
            self.end_date.enabled_box.blockSignals(True)
            self.start_date.clear()
            self.end_date.clear()
            self.start_date.enabled_box.blockSignals(False)
            self.end_date.enabled_box.blockSignals(False)
        self.apply_filters()

    def _custom_date_changed(self) -> None:
        if self.start_date.value() or self.end_date.value():
            self.quick_range_combo.blockSignals(True)
            self.quick_range_combo.setCurrentIndex(self.quick_range_combo.findData(ALL_TIME))
            self.quick_range_combo.blockSignals(False)
        self.apply_filters()

    def apply_filters(self) -> None:
        self._search_timer.stop()  # this run already includes the latest search text
        start = self.start_date.value()
        end = self.end_date.value()
        if start and end and start > end:
            self._notify("The From date cannot be after the To date.", "warning")
            return
        source = self.source_combo.currentData() or ALL_SOURCES
        stage = self.stage_combo.currentData() or ALL_STAGES
        date_label = self.quick_range_combo.currentData() or ALL_TIME
        self._filtered_leads = filter_leads(
            all_leads=self._all_leads,
            source=str(source),
            stage=str(stage),
            date_label=str(date_label),
            start_date=start,
            end_date=end,
            search_term=self.search_edit.text(),
        )
        self._funnel_stats = self._controller.get_funnel_stats(self._filtered_leads)
        self._sources_data = self._controller.group_leads_by_source(self._filtered_leads)
        marketing = self._controller.get_marketing_data(
            leads=self._filtered_leads,
            spend_by_source=self._spend_by_source,
            revenue_by_client=self._revenue_by_client,
        )
        self._marketing_summary = dict(marketing.get("summary") or {})
        self._marketing_metrics = list(marketing.get("metrics") or [])
        self._update_filter_summary()
        self._update_kpis()
        self._update_funnel()
        self._populate_source_table()
        self._populate_marketing_table()
        self._update_marketing_summary()
        self._populate_upcoming_meetings()
        self._populate_leads_table()

    def _filters_description(self) -> str:
        parts: list[str] = []
        source = self.source_combo.currentData()
        if source and source != ALL_SOURCES:
            parts.append(f"Source: {_source_label(source)}")
        stage = self.stage_combo.currentData()
        if stage and stage != ALL_STAGES:
            parts.append(f"Stage: {stage}")
        start, end = self.start_date.value(), self.end_date.value()
        if start and end:
            parts.append(f"Period: {start} → {end}")
        elif start:
            parts.append(f"From: {start}")
        elif end:
            parts.append(f"To: {end}")
        else:
            quick = self.quick_range_combo.currentData()
            if quick and quick != ALL_TIME:
                parts.append(f"Period: {quick}")
        if self.search_edit.text().strip():
            parts.append(f'Search: "{self.search_edit.text().strip()}"')
        return " · ".join(parts) if parts else ALL_LEADS_DESCRIPTION

    def _update_filter_summary(self) -> None:
        description = self._filters_description()
        self.filter_summary.setText(
            f"{description}  ·  {len(self._filtered_leads)} result"
            f"{'s' if len(self._filtered_leads) != 1 else ''}"
        )

    def _update_kpis(self) -> None:
        stats = self._funnel_stats
        total = int(stats.get("total", 0))
        meetings = int(stats.get("meetings", 0))
        converted = int(stats.get("converted", 0))
        new_count = sum(lead.get("status") == "new" for lead in self._filtered_leads)
        self._kpi_cards["total"].set_value(str(total), "Leads in the active snapshot")
        self._kpi_cards["meetings"].set_value(str(meetings), "Leads that reached a meeting")
        self._kpi_cards["converted"].set_value(str(converted), "Converted clients")
        self._kpi_cards["lead_rate"].set_value(f"{stats.get('lead_to_meeting_pct', 0):.1f}%")
        self._kpi_cards["client_rate"].set_value(f"{stats.get('meeting_to_client_pct', 0):.1f}%")
        self._kpi_cards["lost"].set_value(str(int(stats.get("lost", 0))))
        self._kpi_cards["new"].set_value(str(new_count), "New leads awaiting action")
        self._kpi_cards["avg_days"].set_value(f"{stats.get('avg_time_to_meeting', 0):.1f} days")

    def _update_funnel(self) -> None:
        total = int(self._funnel_stats.get("total", 0))
        for key, bar in self._funnel_bars.items():
            value = int(self._funnel_stats.get(key, 0))
            bar.setRange(0, max(total, 1))
            bar.setValue(value)
            percent = (value / total * 100) if total else 0.0
            bar.setFormat(f"{value}  ·  {percent:.1f}%")
            bar.setAccessibleDescription(f"{value} of {total}; {percent:.1f} percent")
        dropoff = int(self._funnel_stats.get("lead_dropoff", 0))
        self.funnel_insight.setText(
            f"{dropoff} lead{'s' if dropoff != 1 else ''} have not reached a meeting. "
            f"Average time to meeting is {self._funnel_stats.get('avg_time_to_meeting', 0):.1f} days."
        )

    def _populate_source_table(self) -> None:
        table = self.source_table
        table.setSortingEnabled(False)
        table.setRowCount(len(self._sources_data))
        ordered = sorted(
            self._sources_data.items(), key=lambda pair: (-int(pair[1].get("total", 0)), _source_label(pair[0]))
        )
        for row, (source, values) in enumerate(ordered):
            total = int(values.get("total", 0))
            clients = int(values.get("clients", 0))
            conversion = clients / total * 100 if total else 0.0
            cells = (
                _readonly_item(_source_label(source)),
                _readonly_item(total, numeric=total),
                _readonly_item(int(values.get("meetings", 0)), numeric=int(values.get("meetings", 0))),
                _readonly_item(clients, numeric=clients),
                _readonly_item(f"{conversion:.1f}%", numeric=conversion),
                _readonly_item(
                    f"{values.get('meeting_to_client_pct', 0):.1f}%",
                    numeric=float(values.get("meeting_to_client_pct", 0)),
                ),
                _readonly_item(
                    f"{values.get('avg_time_to_meeting', 0):.1f}",
                    numeric=float(values.get("avg_time_to_meeting", 0)),
                ),
            )
            for column, item in enumerate(cells):
                table.setItem(row, column, item)
        table.setSortingEnabled(True)

    def _populate_marketing_table(self) -> None:
        table = self.marketing_table
        table.setSortingEnabled(False)
        table.setRowCount(len(self._marketing_metrics))
        for row, values in enumerate(self._marketing_metrics):
            roi = float(values.get("roi", 0)) * 100
            cells = (
                _readonly_item(_source_label(values.get("source"))),
                _readonly_item(int(values.get("leads", 0)), numeric=int(values.get("leads", 0))),
                _readonly_item(int(values.get("customers", 0)), numeric=int(values.get("customers", 0))),
                _readonly_item(f"€{float(values.get('revenue', 0)):,.2f}", numeric=float(values.get("revenue", 0))),
                _readonly_item(f"€{float(values.get('spend', 0)):,.2f}", numeric=float(values.get("spend", 0))),
                _readonly_item(f"€{float(values.get('cpl', 0)):,.2f}", numeric=float(values.get("cpl", 0))),
                _readonly_item(f"€{float(values.get('cac', 0)):,.2f}", numeric=float(values.get("cac", 0))),
                _readonly_item(f"{roi:.1f}%", numeric=roi),
            )
            for column, item in enumerate(cells):
                table.setItem(row, column, item)
        table.setSortingEnabled(True)

    def _populate_upcoming_meetings(self) -> None:
        self.upcoming_list.clear()
        today = date.today().isoformat()
        upcoming = sorted(
            (
                lead for lead in self._filtered_leads
                if lead.get("meeting_date") and str(lead["meeting_date"])[:10] >= today
            ),
            key=lambda lead: str(lead.get("meeting_date")),
        )
        if not upcoming:
            self.upcoming_list.addItem("No upcoming meetings in this snapshot.")
            return
        for lead in upcoming[:20]:
            self.upcoming_list.addItem(
                f"{str(lead.get('meeting_date'))[:10]}  ·  "
                f"{lead.get('client_name') or lead.get('id') or 'Lead'}  ·  "
                f"{_source_label(lead.get('source'))}"
            )

    def _populate_leads_table(self) -> None:
        table = self.leads_table
        with bulk_table_update(
            table,
            stretch_column=0,
            fixed_columns={6: self._lead_action_delegate.column_width()},
        ):
            table.clearContents()
            table.setRowCount(len(self._filtered_leads))
            for row, lead in enumerate(self._filtered_leads):
                lead_id = str(lead.get("id") or "")
                values = (
                    str(lead.get("created_at") or "")[:10] or "—",
                    _source_label(lead.get("source")),
                    _STATUS_LABELS.get(str(lead.get("status") or "").lower(), str(lead.get("status") or "—")),
                    str(lead.get("meeting_date") or "")[:10] or "—",
                    lead.get("client_name") or "—",
                    lead_id or "—",
                )
                for column, value in enumerate(values):
                    item = _readonly_item(value)
                    item.setData(Qt.ItemDataRole.UserRole, lead_id)
                    table.setItem(row, column, item)
                action_item = QTableWidgetItem()
                action_item.setFlags(action_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                action_item.setData(Qt.ItemDataRole.UserRole, lead_id)
                action_item.setData(Qt.ItemDataRole.AccessibleTextRole, f"Edit lead {lead_id}")
                table.setItem(row, 6, action_item)
        self.empty_label.setVisible(not self._filtered_leads)
        table.setVisible(bool(self._filtered_leads))

    def _on_lead_activated(self, index) -> None:
        lead_id = str(index.data(Qt.ItemDataRole.UserRole) or "")
        if lead_id:
            self.edit_lead(lead_id)

    def edit_lead(self, lead_id: str) -> bool:
        lead = next((item for item in self._all_leads if str(item.get("id")) == str(lead_id)), None)
        if not lead:
            self._notify("Lead not found. Refresh the page and try again.", "error")
            return False
        dialog = LeadEditDialog(lead, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        status, meeting_date = dialog.values()
        success, message = self._controller.update_lead_info(lead_id, status, meeting_date)
        self._notify(message, "success" if success else "error")
        if success:
            self.refresh()
            self.data_changed.emit()
        return bool(success)

    def _update_marketing_summary(self) -> None:
        summary = self._marketing_summary
        spend = float(summary.get("total_spend", 0) or 0)
        has_spend = spend > 0
        values = {
            "total_spend": format_eur(spend),
            "total_revenue": format_eur(summary.get("total_revenue", 0)),
            # Without spend these ratios are undefined rather than zero.
            "avg_cpl": format_eur(summary.get("avg_cpl", 0)) if has_spend else "—",
            "avg_cac": format_eur(summary.get("avg_cac", 0)) if has_spend else "—",
            "overall_roi": f"{float(summary.get('overall_roi', 0) or 0) * 100:+.1f}%" if has_spend else "—",
        }
        for key, label in self._marketing_summary_values.items():
            label.setText(values[key])
        self.spend_hint.setText(
            "Figures cover the leads in the active filters."
            if has_spend
            else "No marketing spend recorded for these sources. Import a spend CSV or add records."
        )

    def manage_spend(self) -> bool:
        """Open the spend editor; refresh efficiency metrics if records changed."""
        dialog = MarketingSpendDialog(self._controller, self)
        dialog.exec()
        if not dialog.changed:
            return False
        self.refresh()
        self.data_changed.emit()
        self._notify("Marketing spend updated; CPL, CAC, and ROI were recalculated.", "success")
        return True

    def export_report(self, filename: str | os.PathLike[str] | bool | None = None) -> str | None:
        """Export the active snapshot; passing a path avoids the file dialog."""
        if isinstance(filename, bool):  # Qt's clicked(bool) signal
            filename = None
        if filename is None:
            selected, _filter = QFileDialog.getSaveFileName(
                self,
                "Export leads report",
                "Leads_Report.html",
                "HTML files (*.html)",
            )
            if not selected:
                return None
            filename = selected
        path = str(Path(filename).expanduser())
        if not path.lower().endswith(".html"):
            path += ".html"
        success, message, generated_path = self._report_generator(
            leads=self._filtered_leads,
            funnel_stats=self._funnel_stats,
            sources_data=self._sources_data,
            filters_desc=self._filters_description(),
            filename=path,
            marketing_summary=self._marketing_summary,
            marketing_metrics=self._marketing_metrics,
        )
        self._notify(message, "success" if success else "error")
        return str(generated_path) if success and generated_path else None

    def _notify(self, message: str, level: str) -> None:
        """Show inline feedback; the hosting shell decides whether to pop up errors."""
        self.status_label.setText(message)
        self.status_label.setProperty("level", level)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.notification_requested.emit(message, level)


__all__ = ["LeadEditDialog", "LeadsPage"]
