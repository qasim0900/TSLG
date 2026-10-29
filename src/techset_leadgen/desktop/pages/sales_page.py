from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QEvent, QObject, QSignalBlocker, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from techset_leadgen.analytics.controllers.compare_controller import CompareController
from techset_leadgen.analytics.controllers.ventas_controller import VentasController
from techset_leadgen.domain.analysis_snapshot import AnalysisSnapshot
from techset_leadgen.utils.formatting import format_eur

from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.tables import TONE_ROLE, align_headers, animate_rows, change_color, fit_table_height, prepare_table, set_header_tips
from techset_leadgen.desktop.theme import tokens
from techset_leadgen.desktop.widgets import (
    BarChart,
    BarRow,
    EmptyState,
    HBarList,
    KpiCard,
    PageHeader,
    SectionCard,
    SwitchButton,
    labeled_field,
    repolish,
    sortable_item,
)

logger = logging.getLogger(__name__)

_BRAND_GREEN = "#39B54A"
_BRAND_GREEN_DARK = "#287D35"
_SUMMARY_HEADERS = ("Product", "Quantity", "Total", "Average", "Minimum", "Maximum", "vs Period B")
_COMPARISON_HEADERS = ("Product", "Period A", "Period B", "Difference", "Change")
_HEADER_TIPS = {
    _SUMMARY_HEADERS: {1: "Number of sales", 2: "Sum of all sale amounts", 3: "Average sale amount",
                       4: "Smallest single sale", 5: "Largest single sale"},
    _COMPARISON_HEADERS: {3: "Period B minus period A", 4: "Change from period A to period B"},
}
_EMPTY_SALES = "No sales in this period. Change the dates or filters, or import sales from the Dashboard."
_BRAND_GOLD = "#FFCB4A"
_INK = "#0A1414"
_MUTED = "#62637A"
_GRID = "#DDE1E6"
_ALL_LABEL = "All"
_GROUPING_WORDS = {"day": "daily", "week": "weekly", "month": "monthly", "quarter": "quarterly", "year": "yearly"}


class _OpenOnCurrentMonth(QObject):
    def __init__(self, editor: QDateEdit) -> None:
        super().__init__(editor)
        self._editor = editor

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show and self._editor.date() == self._editor.minimumDate():
            today = QDate.currentDate()
            calendar = self._editor.calendarWidget()
            if calendar is not None:
                calendar.setCurrentPage(today.year(), today.month())
        return False


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _short_label(label: Any) -> str:
    text = str(label)
    parsed = QDate.fromString(text[:10], Qt.DateFormat.ISODate)
    if len(text) >= 10 and parsed.isValid():
        return f"{parsed.day()} {_MONTHS[parsed.month() - 1]}"
    return text


class SalesPage(QWidget):
    importRequested = Signal()
    statusMessage = Signal(str)
    notification_requested = Signal(str, str)
    snapshotChanged = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        controller: VentasController | Any | None = None,
        compare_controller: CompareController | Any | None = None,
        on_import_requested: Callable[[], bool | None] | None = None,
        on_status: Callable[[str], None] | None = None,
        clients_provider: Callable[[], Iterable[Any]] | None = None,
        products_provider: Callable[[], Iterable[Any]] | None = None,
        date_range_provider: Callable[[], tuple[Any, Any]] | None = None,
        report_generator: Callable[..., tuple[bool, str, str | None]] | None = None,
        context: Any = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("salesPage")
        self.setAccessibleName("Sales analytics")
        self.context = context

        self.controller = controller or VentasController()
        self.compare_controller = compare_controller or CompareController()
        self._on_import_requested = on_import_requested
        self._on_status = on_status
        self._clients_provider = clients_provider
        self._products_provider = products_provider
        self._date_range_provider = date_range_provider
        self._report_generator = report_generator
        self.current_snapshot: AnalysisSnapshot | Any | None = None
        self._last_report_path: Path | None = None
        self._last_layout_bucket: tuple[int, int, int] | None = None

        self._build_ui()
        self._load_filter_options()
        self.reload_data(announce=False)


    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("pageScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(self.scroll_area)

        body = QWidget()
        body.setObjectName("salesPageBody")
        body_layout = QVBoxLayout(body)
        self._body_layout = body_layout
        body_layout.setContentsMargins(28, 24, 28, 40)
        body_layout.setSpacing(20)
        self.scroll_area.setWidget(body)

        self.header = PageHeader(
            "Sales intelligence",
            "Filter revenue, compare periods, inspect product performance and export a branded report.",
        )
        body_layout.addWidget(self.header)

        self.import_button = QPushButton("Import data")
        self.import_button.setObjectName("secondaryButton")
        self.import_button.setProperty("variant", "secondary")
        self.import_button.setToolTip("Import sales data using the application import workflow")
        self.import_button.setAccessibleDescription(self.import_button.toolTip())
        set_button_icon(self.import_button, "upload")
        self.import_button.clicked.connect(self._request_import)

        self.export_button = QPushButton("Export HTML")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.setProperty("variant", "secondary")
        self.export_button.setToolTip("Save the currently displayed analysis as a branded HTML report")
        self.export_button.setAccessibleDescription(self.export_button.toolTip())
        set_button_icon(self.export_button, "download")
        self.export_button.clicked.connect(self._choose_export_path)

        self.open_report_button = QPushButton("Open report")
        self.open_report_button.setObjectName("primaryButton")
        self.open_report_button.setToolTip("Open the most recently exported report")
        self.open_report_button.setEnabled(False)
        set_button_icon(self.open_report_button, "file", "onPrimary")
        self.open_report_button.clicked.connect(self._open_last_report)

        self.header.add_action(self.import_button)
        self.header.add_action(self.export_button)
        if self.context is not None:
            self.import_button.setVisible(self.context.can("data.import"))
            self.export_button.setVisible(self.context.can("data.export"))
        self.header.add_action(self.open_report_button)

        self.filter_group = SectionCard("Filters", "All dates", padded=False)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setObjectName("ghostButton")
        self.reset_button.setToolTip("Clear all sales filters and comparison settings")
        self.reset_button.clicked.connect(self.reset_filters)
        self.apply_button = QPushButton("Apply filters")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.setToolTip("Apply the selected sales filters")
        set_button_icon(self.apply_button, "leads", "onPrimary")
        self.apply_button.clicked.connect(self.apply_filters)
        self.filter_group.add_action(self.reset_button)
        self.filter_group.add_action(self.apply_button)
        filters_body = QWidget()
        filter_outer = QVBoxLayout(filters_body)
        filter_outer.setContentsMargins(20, 16, 20, 18)
        filter_outer.setSpacing(14)
        self.filter_group.body.addWidget(filters_body)
        self.filter_grid = QGridLayout()
        self.filter_grid.setHorizontalSpacing(16)
        self.filter_grid.setVerticalSpacing(14)
        filter_outer.addLayout(self.filter_grid)

        self.start_date_edit = self._make_optional_date_edit(
            "Start date", "Include sales on or after this date"
        )
        self.end_date_edit = self._make_optional_date_edit(
            "End date", "Include sales on or before this date"
        )
        self.client_combo = self._make_combo("Client", "Filter by client")
        self.product_combo = self._make_combo("Product", "Filter by product type")
        self.grouping_combo = self._make_combo(
            "Time grouping", "Choose how the trend chart groups sales"
        )
        for label, value in (
            ("Daily", "day"),
            ("Weekly", "week"),
            ("Monthly", "month"),
            ("Quarterly", "quarter"),
            ("Yearly", "year"),
        ):
            self.grouping_combo.addItem(label, value)

        quick_block = QWidget()
        quick_layout = QVBoxLayout(quick_block)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(6)
        quick_label = QLabel("Quick range")
        quick_label.setObjectName("fieldLabel")
        quick_layout.addWidget(quick_label)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        quick_layout.addLayout(quick_row)
        self._quick_buttons: list[QPushButton] = []
        self._quick_group = QButtonGroup(self)
        self._quick_group.setExclusive(True)
        for text, callback in (
            ("Last 7 days", lambda: self._set_last_days(7)),
            ("Last 30 days", lambda: self._set_last_days(30)),
            ("This month", self._set_current_month),
            ("This year", self._set_current_year),
        ):
            button = QPushButton(text)
            button.setObjectName("chipButton")
            button.setCheckable(True)
            button.setToolTip(f"Set the date filter to {text.lower()}")
            button.clicked.connect(callback)
            self._quick_group.addButton(button)
            self._quick_buttons.append(button)
            quick_row.addWidget(button)
        quick_row.addStretch(1)

        self._filter_fields = [
            self._field("From", self.start_date_edit),
            self._field("To", self.end_date_edit),
            self._field("Client", self.client_combo),
            self._field("Product", self.product_combo),
            self._field("Group trend by", self.grouping_combo),
            quick_block,
        ]

        compare_frame = QFrame()
        compare_frame.setObjectName("cardFooter")
        compare_outer = QVBoxLayout(compare_frame)
        compare_outer.setContentsMargins(20, 16, 20, 18)
        compare_outer.setSpacing(14)
        self.filter_group.body.addWidget(compare_frame)
        switch_row = QHBoxLayout()
        switch_row.setSpacing(12)
        self.compare_group = SwitchButton()
        self.compare_group.setAccessibleName("Compare with another period")
        self.compare_group.setToolTip("Enable a second period for side-by-side analysis")
        self.compare_group.setChecked(False)
        self.compare_group.toggled.connect(self._comparison_toggled)
        switch_row.addWidget(self.compare_group, 0, Qt.AlignmentFlag.AlignTop)
        switch_copy = QVBoxLayout()
        switch_copy.setSpacing(2)
        switch_title = QLabel("Compare with another period")
        switch_title.setObjectName("strongText")
        switch_title.setBuddy(self.compare_group)
        hint = QLabel(
            "Period B uses its own dates and optional segment filters; results show B compared with A."
        )
        hint.setObjectName("sectionSubtitle")
        hint.setWordWrap(True)
        switch_copy.addWidget(switch_title)
        switch_copy.addWidget(hint)
        switch_row.addLayout(switch_copy, 1)
        compare_outer.addLayout(switch_row)
        self.compare_fields_box = QWidget()
        self.compare_grid = QGridLayout(self.compare_fields_box)
        self.compare_grid.setContentsMargins(0, 0, 0, 0)
        self.compare_grid.setHorizontalSpacing(16)
        self.compare_grid.setVerticalSpacing(14)
        compare_outer.addWidget(self.compare_fields_box)

        self.compare_start_edit = self._make_optional_date_edit(
            "Comparison start date", "First date in comparison period B"
        )
        self.compare_end_edit = self._make_optional_date_edit(
            "Comparison end date", "Last date in comparison period B"
        )
        self.compare_client_combo = self._make_combo(
            "Comparison client", "Optional client filter for period B"
        )
        self.compare_product_combo = self._make_combo(
            "Comparison product", "Optional product filter for period B"
        )
        self._compare_fields = [
            self._field("Period B from", self.compare_start_edit),
            self._field("Period B to", self.compare_end_edit),
            self._field("Period B client", self.compare_client_combo),
            self._field("Period B product", self.compare_product_combo),
        ]
        self.compare_fields_box.setVisible(False)
        body_layout.addWidget(self.filter_group)

        self.kpi_grid = QGridLayout()
        self.kpi_grid.setHorizontalSpacing(16)
        self.kpi_grid.setVerticalSpacing(16)
        self.sales_card = KpiCard("Total sales", accent=_BRAND_GREEN, icon="sales")
        self.transactions_card = KpiCard("Transactions", accent=_BRAND_GOLD, icon="receipt")
        self.average_card = KpiCard("Average sale", accent=_BRAND_GREEN, icon="target")
        self.clients_card = KpiCard("Unique clients", accent=_BRAND_GOLD, icon="people")
        self.products_card = KpiCard("Products", accent=_BRAND_GREEN, icon="box")
        self._kpi_cards = [
            self.sales_card,
            self.transactions_card,
            self.average_card,
            self.clients_card,
            self.products_card,
        ]
        for card in self._kpi_cards:
            card.label = card.title_label
            card.value = card.value_label
            card.note = card.detail_label
        body_layout.addLayout(self.kpi_grid)

        self.table_panel = SectionCard("Sales summary by product", "", padded=False)
        self.table = QTableWidget(0, len(_SUMMARY_HEADERS))
        self.table.setObjectName("dataTable")
        self.table.setAccessibleName("Sales summary by product")
        self.table.setAccessibleDescription(
            "Sortable product totals, quantities, averages, minimums, and maximums"
        )
        self.table.setHorizontalHeaderLabels(list(_SUMMARY_HEADERS))
        prepare_table(self.table, numeric_columns=range(1, 6), empty_text=_EMPTY_SALES, strong_columns=(0, 2))
        self._label_columns(_SUMMARY_HEADERS)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.sortItems(2, Qt.SortOrder.DescendingOrder)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table_panel.body.addWidget(self.table)
        self.table_empty = EmptyState("No sales in this period",
                                      "Change the dates or filters, or import sales from the Dashboard.",
                                      icon="receipt")
        self.table_empty.add_action("Reset filters", self.reset_filters)
        self.table_empty_import = self.table_empty.add_action("Import data", self._request_import, primary=True)
        self.table_empty.hide()
        self.table_panel.body.addWidget(self.table_empty)
        body_layout.addWidget(self.table_panel)

        self.chart_panel = SectionCard("Visual analysis", "Revenue grouped daily", padded=False, divider=False)
        legend = QLabel()
        legend.setObjectName("sectionSubtitle")
        self.chart_legend = legend
        self.chart_panel.add_action(legend)
        self.chart_tabs = QTabWidget()
        self.chart_tabs.setDocumentMode(True)
        self.trend_chart = BarChart("Sales trend chart")
        self.product_chart = HBarList("Sales by product chart")
        self.top_clients_chart = HBarList("Top clients chart")
        self.chart_tabs.addTab(self._chart_page(self.trend_chart, (20, 24, 20, 20)), "Trend")
        self.chart_tabs.addTab(self._chart_page(self.product_chart), "Products")
        self.chart_tabs.addTab(self._chart_page(self.top_clients_chart), "Top clients")
        self.chart_tabs.currentChanged.connect(lambda index: self.chart_legend.setVisible(index == 0))
        self.chart_tabs.currentChanged.connect(lambda _index: self._replay_current_chart())
        self.chart_panel.body.addWidget(self.chart_tabs)
        self.chart_empty = EmptyState("No sales data for the selected filters", "", icon="chart")
        self.chart_empty.hide()
        self.chart_panel.body.addWidget(self.chart_empty)
        body_layout.addWidget(self.chart_panel)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusMessage")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.setAccessibleName("Sales page status")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        body_layout.addWidget(self.status_label)
        body_layout.addStretch(1)

        self._update_legend()
        self._reflow(force=True)

    @staticmethod
    def _chart_page(chart: QWidget, margins: tuple[int, int, int, int] = (20, 20, 20, 20)) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(*margins)
        layout.addWidget(chart)
        layout.addStretch(1)
        return page

    def _replay_current_chart(self) -> None:
        chart = (self.trend_chart, self.product_chart, self.top_clients_chart)[max(self.chart_tabs.currentIndex(), 0)]
        chart.replay()

    @staticmethod
    def _make_optional_date_edit(accessible_name: str, tooltip: str) -> QDateEdit:
        editor = QDateEdit()
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("dd MMM yyyy")
        editor.setMinimumDate(QDate(1900, 1, 1))
        editor.setMaximumDate(QDate(2999, 12, 31))
        editor.setSpecialValueText("Any date")
        editor.setDate(editor.minimumDate())
        editor.setAccessibleName(accessible_name)
        editor.setAccessibleDescription(tooltip)
        editor.setToolTip(tooltip)
        calendar = editor.calendarWidget()
        if calendar is not None:
            calendar.installEventFilter(_OpenOnCurrentMonth(editor))
        return editor

    @staticmethod
    def _make_combo(accessible_name: str, tooltip: str) -> QComboBox:
        combo = QComboBox()
        combo.setAccessibleName(accessible_name)
        combo.setAccessibleDescription(tooltip)
        combo.setToolTip(tooltip)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(14)
        return combo

    @staticmethod
    def _field(label_text: str, editor: QWidget) -> QWidget:
        return labeled_field(label_text, editor)


    def _load_filter_options(self) -> None:
        try:
            clients_provider = self._clients_provider
            products_provider = self._products_provider
            if clients_provider is None or products_provider is None:
                from techset_leadgen.analytics.analysis import get_unique_clients, get_unique_products

                clients_provider = clients_provider or get_unique_clients
                products_provider = products_provider or get_unique_products

            clients = clients_provider() or []
            products = products_provider() or []
        except Exception:
            logger.exception("Could not load sales filter options")
            clients, products = [], []

        self._replace_combo_values(self.client_combo, clients)
        self._replace_combo_values(self.compare_client_combo, clients)
        self._replace_combo_values(self.product_combo, products)
        self._replace_combo_values(self.compare_product_combo, products)

    @staticmethod
    def _replace_combo_values(combo: QComboBox, values: Iterable[Any]) -> None:
        old_value = combo.currentData()
        blocker = QSignalBlocker(combo)
        combo.clear()
        combo.addItem(_ALL_LABEL, None)
        seen: set[str] = set()
        for raw_value in values:
            value = str(raw_value or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            combo.addItem(value, value)
        index = combo.findData(old_value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        del blocker

    @staticmethod
    def _optional_date(editor: QDateEdit) -> str | None:
        value = editor.date()
        if value == editor.minimumDate():
            return None
        return value.toString(Qt.DateFormat.ISODate)

    @staticmethod
    def _set_optional_date(editor: QDateEdit, value: str | None) -> None:
        parsed = QDate.fromString(value or "", Qt.DateFormat.ISODate)
        editor.setDate(parsed if parsed.isValid() else editor.minimumDate())

    def _sync_controller_from_controls(self) -> tuple[bool, str | None]:
        start = self._optional_date(self.start_date_edit)
        end = self._optional_date(self.end_date_edit)
        self.controller.set_start_date(start)
        self.controller.set_end_date(end)
        self.controller.set_client(self.client_combo.currentData())
        self.controller.set_product(self.product_combo.currentData())

        valid, message = self.controller.validate_filters()
        if not valid:
            return False, message or "The selected date range is invalid."

        if not self.compare_group.isChecked():
            self.compare_controller.deactivate_compare()
            return True, None

        comparison_start = self._optional_date(self.compare_start_edit)
        comparison_end = self._optional_date(self.compare_end_edit)
        if not start or not end:
            return False, "Choose both Period A dates before enabling comparison."
        if not comparison_start or not comparison_end:
            return False, "Choose both Period B dates before applying comparison."
        if start > end:
            return False, "Period A start date must not be after its end date."
        if comparison_start > comparison_end:
            return False, "Period B start date must not be after its end date."

        self.compare_controller.set_period_a(start, end)
        self.compare_controller.set_client_a(self.client_combo.currentData())
        self.compare_controller.set_product_a(self.product_combo.currentData())
        self.compare_controller.set_period_b(comparison_start, comparison_end)
        self.compare_controller.set_client_b(self.compare_client_combo.currentData())
        self.compare_controller.set_product_b(self.compare_product_combo.currentData())
        self.compare_controller.set_grouping(self.grouping_combo.currentData() or "day")
        self.compare_controller.activate_compare()
        return True, None

    @Slot()
    def apply_filters(self) -> None:
        valid, message = self._sync_controller_from_controls()
        if not valid:
            self._notify(message or "Please review the selected filters.", error=True)
            return
        self.reload_data()

    @Slot()
    def reset_filters(self) -> None:
        self.controller.clear_filters()
        self.compare_controller.clear()
        for editor in (
            self.start_date_edit,
            self.end_date_edit,
            self.compare_start_edit,
            self.compare_end_edit,
        ):
            editor.setDate(editor.minimumDate())
        for combo in (
            self.client_combo,
            self.product_combo,
            self.compare_client_combo,
            self.compare_product_combo,
            self.grouping_combo,
        ):
            combo.setCurrentIndex(0)
        blocker = QSignalBlocker(self.compare_group)
        self.compare_group.setChecked(False)
        del blocker
        self.compare_fields_box.setVisible(False)
        self._quick_group.setExclusive(False)
        for button in self._quick_buttons:
            button.setChecked(False)
        self._quick_group.setExclusive(True)
        self._update_legend()
        self.reload_data()

    def reload_data(self, *, announce: bool = True) -> AnalysisSnapshot | Any | None:
        self._set_busy(True)
        try:
            grouping = self.grouping_combo.currentData() or "day"
            compare = self.compare_controller if self.compare_controller.is_compare_active() else None
            snapshot = self.controller.get_sales_snapshot(
                grouping=grouping,
                compare_controller=compare,
            )
            self.current_snapshot = snapshot
            self._render_snapshot(snapshot)
            self.export_button.setEnabled(snapshot is not None)
            if snapshot is not None:
                self.snapshotChanged.emit(snapshot)
                if announce:
                    mode = "comparison" if snapshot.is_compare_mode() else "sales"
                    self._notify(f"Updated {mode} analysis.")
            else:
                self._notify("No sales match the selected filters.")
            return snapshot
        except Exception as exc:
            logger.exception("Could not refresh the native sales page")
            self.current_snapshot = None
            self._render_snapshot(None)
            self.export_button.setEnabled(False)
            self._notify(f"Could not load sales analysis: {exc}", error=True)
            return None
        finally:
            self._set_busy(False)

    def refresh_after_import(self) -> None:
        try:
            self.controller.invalidate_snapshot_cache()
        except AttributeError:
            logger.debug("Injected sales controller has no snapshot cache")
        self._load_filter_options()
        self.reload_data()

    def _render_snapshot(self, snapshot: AnalysisSnapshot | Any | None) -> None:
        if snapshot is None:
            for card in self._kpi_cards:
                card.set_value("—")
            self.filter_group.set_subtitle(f"{self._period_text()} · no sales match the selected filters")
            self.table_panel.set_subtitle("")
            self._populate_table(None)
            self._render_charts(None)
            return

        period = snapshot.period_a
        metrics = period.metrics
        comparison = snapshot.comparison if snapshot.is_compare_mode() else None
        period_b = snapshot.period_b if snapshot.is_compare_mode() else None

        def comparison_note(metric_name: str, formatter: Callable[[Any], str]) -> str:
            if comparison is None or period_b is None:
                return ""
            b_value = getattr(period_b.metrics, metric_name)
            percentage = comparison.metrics.percentage_changes.get(metric_name, 0.0)
            return f"Period B: {formatter(b_value)} ({percentage:+.1f}%)"

        self.sales_card.set_value(
            format_eur(metrics.total_sales),
            comparison_note("total_sales", format_eur) or "Revenue in Period A",
        )
        self.transactions_card.set_value(
            f"{metrics.transactions:,}",
            comparison_note("transactions", lambda value: f"{int(value):,}") or "Imported sales rows",
        )
        self.average_card.set_value(
            format_eur(metrics.avg_ticket),
            comparison_note("avg_ticket", format_eur) or "Per transaction",
        )
        self.clients_card.set_value(
            f"{metrics.unique_clients:,}",
            comparison_note("unique_clients", lambda value: f"{int(value):,}") or "Bought in this period",
        )
        distribution = period.product_distribution
        top = ""
        if distribution.labels and distribution.values:
            top = max(zip(distribution.labels, distribution.values), key=lambda item: float(item[1]))[0]
        self.products_card.set_value(f"{len(distribution.labels):,}", f"Top: {top}" if top else "")

        period_text = self._period_text()
        self.filter_group.set_subtitle(
            f"{period_text} · {metrics.transactions:,} sale{'s' if metrics.transactions != 1 else ''} "
            "match the selected filters")
        products = len(distribution.labels)
        self.table_panel.set_subtitle(f"{products} product{'s' if products != 1 else ''} · {period_text}")
        self._populate_table(snapshot)
        self._render_charts(snapshot)

    def _populate_table(self, snapshot: AnalysisSnapshot | Any | None) -> None:
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        if snapshot is None:
            self._label_columns(_SUMMARY_HEADERS)
            self.table.setRowCount(0)
            self.table.setSortingEnabled(True)
            self._fit_table_height()
            return

        if snapshot.is_compare_mode() and snapshot.comparison is not None:
            products = snapshot.comparison.products
            self._label_columns(_COMPARISON_HEADERS)
            self.table.setRowCount(len(products.labels))
            for row_index, label in enumerate(products.labels):
                comparison_values = (
                    self._text_item(label),
                    self._number_item(products.series_a[row_index], format_eur),
                    self._number_item(products.series_b[row_index], format_eur),
                    self._number_item(products.differences[row_index], format_eur),
                    self._number_item(
                        products.percentage_diff[row_index],
                        lambda value: f"{value:+.1f}%",
                    ),
                )
                difference = products.differences[row_index]
                color = change_color(self.table, difference >= 0)
                comparison_values[3].setForeground(color)
                comparison_values[4].setData(TONE_ROLE, "success" if difference >= 0 else "danger")
                for column, item in enumerate(comparison_values):
                    self.table.setItem(row_index, column, item)
            description = "Product sales comparison between periods A and B"
        else:
            rows = snapshot.period_a.table_data
            self._label_columns(_SUMMARY_HEADERS)
            self.table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                summary_values = (
                    self._text_item(row.product_type),
                    self._number_item(row.quantity, lambda value: f"{int(value):,}"),
                    self._number_item(row.total_sales, format_eur),
                    self._number_item(row.avg_price, format_eur),
                    self._number_item(row.min_price, format_eur),
                    self._number_item(row.max_price, format_eur),
                    self._vs_b_item(),
                )
                for column, item in enumerate(summary_values):
                    self.table.setItem(row_index, column, item)
            description = "Product quantities, sales totals, averages, minimums, and maximums"

        self.table.setAccessibleDescription(description)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self._fit_table_height()

    def _fit_table_height(self) -> None:
        empty = self.table.rowCount() == 0
        self.table.setVisible(not empty)
        self.table_empty.setVisible(empty)
        if self.context is not None:
            self.table_empty_import.setVisible(self.context.can("data.import"))
        fit_table_height(self.table)
        animate_rows(self.table)

    @staticmethod
    def _vs_b_item() -> QTableWidgetItem:
        item = QTableWidgetItem("—")
        item.setData(TONE_ROLE, "neutral")
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setToolTip("Turn on “Compare with another period” to compare with Period B")
        return item

    def _label_columns(self, headers: tuple[str, ...]) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(list(headers))
        align_headers(self.table, range(1, len(headers)))
        set_header_tips(self.table, _HEADER_TIPS.get(headers, {}))

    @staticmethod
    def _text_item(value: Any) -> QTableWidgetItem:
        return QTableWidgetItem(str(value))

    @staticmethod
    def _number_item(value: Any, formatter: Callable[[Any], str]) -> QTableWidgetItem:
        number = float(value or 0)
        item = sortable_item(formatter(number), number)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        return item


    def _render_charts(self, snapshot: AnalysisSnapshot | Any | None) -> None:
        has_data = snapshot is not None and bool(snapshot.period_a.table_data)
        self.chart_tabs.setVisible(has_data)
        self.chart_empty.setVisible(not has_data)
        if snapshot is None:
            self.trend_chart.set_data([], [], empty="No sales data for the selected filters")
            self.product_chart.set_rows([], empty="No product data for the selected filters")
            self.top_clients_chart.set_rows([], empty="No client data for the selected filters")
            return
        self._render_trend_chart(snapshot)
        self._render_product_chart(snapshot)
        self._render_top_clients_chart(snapshot)

    def _render_trend_chart(self, snapshot: AnalysisSnapshot | Any) -> None:
        grouping = snapshot.metadata.grouping.value
        self.chart_panel.set_subtitle(f"Revenue grouped {_GROUPING_WORDS.get(grouping, 'by period')}")
        comparison = snapshot.comparison if snapshot.is_compare_mode() else None
        money = lambda value: format_eur(value, 0)
        if comparison is not None and comparison.evolution.points:
            points = list(comparison.evolution.points)
            self.trend_chart.set_data([_short_label(point.label) for point in points],
                                      [float(point.value_a) for point in points],
                                      values_b=[float(point.value_b) for point in points], value_format=money)
            description = f"Revenue trend comparing periods A and B across {len(points)} intervals"
        else:
            evolution = snapshot.period_a.evolution
            labels = [_short_label(label) for label in evolution.labels or []]
            values = [float(value) for value in evolution.values or []]
            self.trend_chart.set_data(labels, values, value_format=money, empty="No trend data is available")
            description = f"Sales trend with {len(values)} {grouping} data points"
        self.trend_chart.setAccessibleDescription(description + ". " + self.trend_chart.accessibleDescription())

    def _render_product_chart(self, snapshot: AnalysisSnapshot | Any) -> None:
        distribution = snapshot.period_a.product_distribution
        pairs = sorted(zip(list(distribution.labels or []), [float(value) for value in distribution.values or []]),
                       key=lambda item: item[1], reverse=True)[:12]
        total = sum(value for _label, value in pairs) or 1.0
        top = max((value for _label, value in pairs), default=1.0) or 1.0
        self.product_chart.set_rows(
            [BarRow(label, value / top, format_eur(value), f"{value / total * 100:.0f}%")
             for label, value in pairs],
            empty="No product distribution is available",
        )

    def _render_top_clients_chart(self, snapshot: AnalysisSnapshot | Any) -> None:
        ranking = sorted(snapshot.period_a.top_clients or [], key=lambda client: float(client.total_sales),
                         reverse=True)
        top = max((float(client.total_sales) for client in ranking), default=1.0) or 1.0
        self.top_clients_chart.set_rows(
            [BarRow(str(client.client_name), float(client.total_sales) / top, format_eur(client.total_sales),
                    f"{client.transactions:,} sales", avatar=str(client.client_name), color="chartB",
                    tooltip=f"{client.client_name}: {format_eur(client.total_sales)} · {client.transactions:,} sales "
                            f"· {client.percentage_of_total:.1f}% of revenue")
             for client in ranking],
            empty="No client ranking is available",
        )
        self.top_clients_chart.setAccessibleDescription(
            "Top clients by sales: " + "; ".join(
                f"{client.client_name} {format_eur(client.total_sales)}" for client in ranking))


    @Slot()
    def _request_import(self) -> None:
        self.importRequested.emit()
        if self._on_import_requested is None:
            self._notify("Choose a file from the main application import flow.")
            return
        try:
            changed = self._on_import_requested()
        except Exception as exc:
            logger.exception("Sales import callback failed")
            self._notify(f"Could not start the import: {exc}", error=True)
            return
        if changed is True:
            self.refresh_after_import()

    @Slot()
    def _choose_export_path(self) -> None:
        if self.current_snapshot is None:
            self._notify("There is no sales analysis to export.", error=True)
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = str(Path.home() / f"Techset_LeadGen_Sales_{timestamp}.html")
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export sales report",
            default_name,
            "HTML report (*.html)",
        )
        if filename:
            self.export_report(filename)

    def export_report(self, filename: str | Path) -> tuple[bool, str, str | None]:
        if self.current_snapshot is None:
            result = (False, "There is no sales analysis to export.", None)
            self._notify(result[1], error=True)
            return result

        path = Path(filename).expanduser()
        if path.suffix.lower() != ".html":
            path = path.with_suffix(".html")
        if self.context is not None:
            try:
                self.context.run(lambda db, actor: actor.require("data.export"))
            except Exception as exc:
                from techset_leadgen.desktop.support import explain

                result = (False, explain(exc)[0], None)
                self._notify(result[1], error=True)
                return result
        try:
            report_generator = self._report_generator
            if report_generator is None:
                from techset_leadgen.reports.report_html import generate_html_report_from_snapshot

                report_generator = generate_html_report_from_snapshot
            success, message, written_path = report_generator(
                self.current_snapshot,
                str(path),
            )
        except Exception as exc:
            logger.exception("Could not export the sales report")
            success, message, written_path = False, f"Could not export report: {exc}", None

        if success and written_path:
            self._last_report_path = Path(written_path).resolve()
            self.open_report_button.setEnabled(True)
            if self.context is not None:
                self.context.record("data.exported", entity_type="data", changes={"report": "sales"})
        self._notify(message, error=not success)
        return success, message, written_path

    @Slot()
    def _open_last_report(self) -> None:
        if self._last_report_path is None or not self._last_report_path.exists():
            self._notify("The exported report could not be found.", error=True)
            self.open_report_button.setEnabled(False)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_report_path))):
            self._notify("The operating system could not open the report.", error=True)


    @Slot(bool)
    def _comparison_toggled(self, enabled: bool) -> None:
        self.compare_fields_box.setVisible(enabled)
        self._update_legend()
        if not enabled:
            self.compare_controller.deactivate_compare()
            if self.current_snapshot is not None and self.current_snapshot.is_compare_mode():
                self.reload_data()
            return
        self._ensure_period_a_dates()
        start = self.start_date_edit.date()
        end = self.end_date_edit.date()
        if start == self.start_date_edit.minimumDate() or end == self.end_date_edit.minimumDate():
            return
        days = max(1, start.daysTo(end) + 1)
        comparison_end = start.addDays(-1)
        comparison_start = comparison_end.addDays(-(days - 1))
        self.compare_start_edit.setDate(comparison_start)
        self.compare_end_edit.setDate(comparison_end)

    def _ensure_period_a_dates(self) -> None:
        if (
            self.start_date_edit.date() != self.start_date_edit.minimumDate()
            and self.end_date_edit.date() != self.end_date_edit.minimumDate()
        ):
            return
        try:
            date_range_provider = self._date_range_provider
            if date_range_provider is None:
                from techset_leadgen.analytics.analysis import get_date_range

                date_range_provider = get_date_range
            start, end = date_range_provider()
        except Exception:
            logger.exception("Could not infer a date range for comparison")
            start, end = None, None
        if start and end:
            self._set_optional_date(self.start_date_edit, str(start))
            self._set_optional_date(self.end_date_edit, str(end))

    def _set_last_days(self, days: int) -> None:
        end = QDate.currentDate()
        self.start_date_edit.setDate(end.addDays(-(max(1, days) - 1)))
        self.end_date_edit.setDate(end)

    def _set_current_month(self) -> None:
        today = QDate.currentDate()
        self.start_date_edit.setDate(QDate(today.year(), today.month(), 1))
        self.end_date_edit.setDate(QDate(today.year(), today.month(), today.daysInMonth()))

    def _set_current_year(self) -> None:
        year = QDate.currentDate().year()
        self.start_date_edit.setDate(QDate(year, 1, 1))
        self.end_date_edit.setDate(QDate(year, 12, 31))


    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() not in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        }:
            return
        if hasattr(self, "trend_chart"):
            for chart in (self.trend_chart, self.product_chart, self.top_clients_chart):
                chart.update()
            self._update_legend()
        if hasattr(self, "table"):
            self._populate_table(self.current_snapshot)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, *, force: bool = False) -> None:
        width = max(0, self.width() - 70)
        field_columns = 4 if width >= 880 else 2 if width >= 520 else 1
        compare_columns = field_columns
        kpi_columns = 5 if width >= 1000 else 3 if width >= 600 else 2 if width >= 400 else 1
        bucket = (field_columns, compare_columns, kpi_columns)
        if not force and bucket == self._last_layout_bucket:
            return
        self._last_layout_bucket = bucket
        self._place_filter_fields(field_columns)
        self._replace_grid(self.compare_grid, self._compare_fields, compare_columns)
        self._replace_grid(self.kpi_grid, self._kpi_cards, kpi_columns)
        for layout in (self.filter_grid, self.filter_group.card_layout, self._body_layout):
            layout.invalidate()
            layout.activate()

    def _place_filter_fields(self, columns: int) -> None:
        layout = self.filter_grid
        for widget in self._filter_fields:
            layout.removeWidget(widget)
        for column in range(6):
            layout.setColumnStretch(column, 0)
        *fields, quick = self._filter_fields
        for index, widget in enumerate(fields):
            layout.addWidget(widget, index // columns, index % columns)
        used = len(fields) % columns
        row = len(fields) // columns
        if used == 0 or columns < 4:
            layout.addWidget(quick, row + (1 if used else 0), 0, 1, columns)
        else:
            layout.addWidget(quick, row, used, 1, columns - used)
        for column in range(columns):
            layout.setColumnStretch(column, 1)

    def _period_text(self) -> str:
        start = self.start_date_edit.date()
        end = self.end_date_edit.date()
        if start == self.start_date_edit.minimumDate() and end == self.end_date_edit.minimumDate():
            return "All dates"
        first = "the beginning" if start == self.start_date_edit.minimumDate() else start.toString("d MMM yyyy")
        last = "today" if end == self.end_date_edit.minimumDate() else end.toString("d MMM yyyy")
        return f"{first} – {last}"

    def _update_legend(self) -> None:
        values = tokens()
        swatch = '<span style="color:{0}">■</span>'
        text = f'{swatch.format(values["chartA"])} Period A'
        if self.compare_group.isChecked():
            text += f'&nbsp;&nbsp;&nbsp;{swatch.format(values["chartB"])} Period B'
        self.chart_legend.setTextFormat(Qt.TextFormat.RichText)
        self.chart_legend.setText(text)

    @staticmethod
    def _replace_grid(
        layout: QGridLayout,
        widgets: Sequence[QWidget],
        columns: int,
    ) -> None:
        for widget in widgets:
            layout.removeWidget(widget)
        for column in range(6):
            layout.setColumnStretch(column, 0)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, index // columns, index % columns)
        for column in range(max(1, columns)):
            layout.setColumnStretch(column, 1)


    def _set_busy(self, busy: bool) -> None:
        self.apply_button.setEnabled(not busy)
        self.reset_button.setEnabled(not busy)
        if busy:
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.unsetCursor()

    def _notify(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("severity", "error" if error else "info")
        self.status_label.setAccessibleDescription(message)
        self.status_label.setVisible(error)
        repolish(self.status_label)
        self.statusMessage.emit(message)
        if self._on_status is not None:
            try:
                self._on_status(message)
            except Exception:
                logger.exception("Sales status callback failed")

