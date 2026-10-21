"""Native Qt sales analytics page for Techset LeadGen.

The page deliberately consumes the existing :class:`AnalysisSnapshot` contract.
Data queries, filtering rules, comparison maths, and HTML report generation stay
in the established controller, service, and report layers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PySide6.QtCore import QDate, QEvent, QObject, QSignalBlocker, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPalette, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from controllers.compare_controller import CompareController
from controllers.ventas_controller import VentasController
from domain.analysis_snapshot import AnalysisSnapshot
from utils.formatting import format_eur

from ..tables import align_headers, change_color, prepare_table, set_header_tips
from ..widgets import KpiCard, labeled_field, sortable_item

logger = logging.getLogger(__name__)

_BRAND_GREEN = "#39B54A"
_BRAND_GREEN_DARK = "#287D35"
_SUMMARY_HEADERS = ("Product", "Quantity", "Total", "Average", "Minimum", "Maximum")
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


class _OpenOnCurrentMonth(QObject):
    """Open an "Any date" editor's calendar on today's month instead of January 1900.

    The optional filters store "no date" as the editor's minimum date, so the
    popup otherwise opened 126 years in the past. Only the page shown changes;
    the value stays "Any date" until the user picks a day.
    """

    def __init__(self, editor: QDateEdit) -> None:
        super().__init__(editor)
        self._editor = editor

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Show and self._editor.date() == self._editor.minimumDate():
            today = QDate.currentDate()
            calendar = self._editor.calendarWidget()
            if calendar is not None:
                calendar.setCurrentPage(today.year(), today.month())
        return False


class _SalesChart(QWidget):
    """Render an isolated Matplotlib Agg figure into a native Qt label.

    A static pixmap is sufficient for these analytical charts and avoids a
    process-global interactive Matplotlib backend.  That keeps report charts
    and repeated offscreen Qt tests deterministic in the same process.
    """

    def __init__(self, accessible_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.figure = Figure(figsize=(8.5, 3.6), constrained_layout=True)
        self._canvas = FigureCanvasAgg(self.figure)
        self._source_pixmap = QPixmap()
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(accessible_name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A QLabel's minimum size is its pixmap's size; with Expanding the chart
        # could grow but never shrink, forcing horizontal scrolling on narrow
        # windows. Ignored lets the layout size it and the pixmap is re-scaled.
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image.setMinimumSize(1, 1)
        self.image.setAccessibleName(accessible_name)
        layout.addWidget(self.image)

    def draw_idle(self) -> None:
        """Draw synchronously and update the scaled native pixmap."""
        self._canvas.draw()
        width, height = self._canvas.get_width_height()
        rgba = bytes(self._canvas.buffer_rgba())
        image = QImage(
            rgba,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self._source_pixmap = QPixmap.fromImage(image)
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            return
        target = self.image.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        self.image.setPixmap(
            self._source_pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._update_pixmap()

    def empty(self, message: str) -> None:
        self.figure.clear()
        palette = self.palette()
        surface = palette.color(QPalette.ColorRole.Base).name()
        muted = palette.color(QPalette.ColorRole.PlaceholderText).name()
        self.figure.set_facecolor(surface)
        axis = self.figure.add_subplot(111)
        axis.set_facecolor(surface)
        axis.set_axis_off()
        axis.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            color=muted,
            fontsize=11,
            wrap=True,
        )
        self.setAccessibleDescription(message)
        self.draw_idle()


class SalesPage(QWidget):
    """Sales filtering, analytics, comparison, import, and export page.

    Parameters
    ----------
    controller:
        Optional ``VentasController``-compatible object. Supplying it makes the
        widget straightforward to test and keeps persistence outside the page.
    compare_controller:
        Optional ``CompareController``-compatible state holder.
    on_import_requested:
        Shell callback for the application-wide import flow. Return ``True``
        when a synchronous import changed the dataset; return ``False``/``None``
        for cancel or an asynchronous flow. Async owners should call
        :meth:`refresh_after_import` after commit.
    on_status:
        Optional callback receiving human-readable status messages.
    clients_provider, products_provider, date_range_provider:
        Optional query callables used to isolate the widget from persistence in
        tests or alternate shells.
    report_generator:
        Optional branded report writer with the existing
        ``(snapshot, filename) -> (success, message, path)`` contract.

    Signals
    -------
    importRequested:
        Emitted whenever the user requests an import, even if a callback exists.
    statusMessage:
        Legacy single-argument feedback signal.
    notification_requested:
        Emitted with a message and one of ``info``, ``success``, ``warning``,
        or ``error`` for the application shell.
    snapshotChanged:
        Emitted after a successful snapshot refresh.
    """

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
        self.context = context  # AppContext: decides who may import and export

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

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("pageScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll_area)

        body = QWidget()
        body.setObjectName("salesPageBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 22, 24, 28)
        body_layout.setSpacing(18)
        self.scroll_area.setWidget(body)

        # Attach each nested layout to its parent before populating it. PySide
        # only transfers widget ownership to the widget tree when the layout
        # already has a parent widget; otherwise Python and Qt both "own" the
        # child and the process can abort while tearing the page down.
        heading_row = QVBoxLayout()
        body_layout.addLayout(heading_row)
        heading_copy = QVBoxLayout()
        heading_row.addLayout(heading_copy)
        title = QLabel("Sales intelligence")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Filter revenue, compare periods, inspect product performance, and export a branded report."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        heading_copy.addWidget(title)
        heading_copy.addWidget(subtitle)

        self.import_button = QPushButton("&Import data")
        self.import_button.setObjectName("secondaryButton")
        self.import_button.setProperty("variant", "secondary")
        self.import_button.setToolTip("Import sales data using the application import workflow")
        self.import_button.setAccessibleDescription(self.import_button.toolTip())
        self.import_button.clicked.connect(self._request_import)

        self.export_button = QPushButton("&Export HTML")
        self.export_button.setObjectName("primaryButton")
        self.export_button.setProperty("variant", "primary")
        self.export_button.setToolTip("Save the currently displayed analysis as a branded HTML report")
        self.export_button.setAccessibleDescription(self.export_button.toolTip())
        self.export_button.clicked.connect(self._choose_export_path)

        self.open_report_button = QPushButton("Open report")
        self.open_report_button.setObjectName("tertiaryButton")
        self.open_report_button.setToolTip("Open the most recently exported report")
        self.open_report_button.setEnabled(False)
        self.open_report_button.clicked.connect(self._open_last_report)

        heading_actions = QHBoxLayout()
        heading_row.addLayout(heading_actions)
        heading_actions.addStretch(1)
        heading_actions.addWidget(self.import_button)
        heading_actions.addWidget(self.export_button)
        if self.context is not None:
            self.import_button.setVisible(self.context.can("data.import"))
            self.export_button.setVisible(self.context.can("data.export"))
        heading_actions.addWidget(self.open_report_button)

        self.filter_group = QGroupBox("Filters")
        self.filter_group.setObjectName("panel")
        filter_outer = QVBoxLayout(self.filter_group)
        self.filter_grid = QGridLayout()
        self.filter_grid.setHorizontalSpacing(14)
        self.filter_grid.setVerticalSpacing(10)
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

        self._filter_fields = [
            self._field("From", self.start_date_edit),
            self._field("To", self.end_date_edit),
            self._field("Client", self.client_combo),
            self._field("Product", self.product_combo),
            self._field("Group trend by", self.grouping_combo),
        ]

        quick_row = QGridLayout()
        filter_outer.addLayout(quick_row)
        quick_row.setHorizontalSpacing(8)
        quick_row.setVerticalSpacing(8)
        quick_label = QLabel("Quick range:")
        quick_label.setObjectName("fieldLabel")
        quick_row.addWidget(quick_label, 0, 0, 1, 4)
        self._quick_buttons: list[QPushButton] = []
        for text, callback in (
            ("Last 7 days", lambda: self._set_last_days(7)),
            ("Last 30 days", lambda: self._set_last_days(30)),
            ("This month", self._set_current_month),
            ("This year", self._set_current_year),
        ):
            button = QPushButton(text)
            button.setObjectName("compactButton")
            button.setToolTip(f"Set the date filter to {text.lower()}")
            button.clicked.connect(callback)
            self._quick_buttons.append(button)
        for index, button in enumerate(self._quick_buttons):
            quick_row.addWidget(button, 1, index)
        quick_row.setColumnStretch(len(self._quick_buttons), 1)  # keep the chips compact

        action_row = QHBoxLayout()
        filter_outer.addLayout(action_row)
        action_row.addStretch(1)
        self.reset_button = QPushButton("&Reset")
        self.reset_button.setObjectName("secondaryButton")
        self.reset_button.setToolTip("Clear all sales filters and comparison settings")
        self.reset_button.clicked.connect(self.reset_filters)
        self.apply_button = QPushButton("&Apply filters")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.setToolTip("Apply the selected sales filters")
        self.apply_button.clicked.connect(self.apply_filters)
        action_row.addWidget(self.reset_button)
        action_row.addWidget(self.apply_button)
        body_layout.addWidget(self.filter_group)

        self.compare_group = QGroupBox("Compare with another period")
        self.compare_group.setObjectName("panel")
        self.compare_group.setCheckable(True)
        self.compare_group.setChecked(False)
        self.compare_group.setToolTip("Enable a second period for side-by-side analysis")
        self.compare_group.toggled.connect(self._comparison_toggled)
        compare_outer = QVBoxLayout(self.compare_group)
        hint = QLabel(
            "Period B uses its own dates and optional segment filters; results show B compared with A."
        )
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        compare_outer.addWidget(hint)
        self.compare_grid = QGridLayout()
        self.compare_grid.setHorizontalSpacing(14)
        self.compare_grid.setVerticalSpacing(10)
        compare_outer.addLayout(self.compare_grid)

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
        body_layout.addWidget(self.compare_group)

        self.kpi_grid = QGridLayout()
        self.kpi_grid.setHorizontalSpacing(12)
        self.kpi_grid.setVerticalSpacing(12)
        self.sales_card = KpiCard("Total sales", accent=_BRAND_GREEN)
        self.transactions_card = KpiCard("Transactions", accent=_BRAND_GOLD)
        self.average_card = KpiCard("Average sale", accent=_BRAND_GREEN)
        self.clients_card = KpiCard("Unique clients", accent=_BRAND_GOLD)
        self.products_card = KpiCard("Products", accent=_BRAND_GREEN)
        self._kpi_cards = [
            self.sales_card,
            self.transactions_card,
            self.average_card,
            self.clients_card,
            self.products_card,
        ]
        # Preserve the former private card's label attributes for callers that
        # inspect the rendered value while all updates use KpiCard's shared API.
        for card in self._kpi_cards:
            card.label = card.title_label
            card.value = card.value_label
            card.note = card.detail_label
        body_layout.addLayout(self.kpi_grid)

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setObjectName("salesContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setAccessibleName("Sales table and charts")

        table_panel = QGroupBox("Sales summary by product")
        table_panel.setObjectName("panel")
        table_layout = QVBoxLayout(table_panel)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("dataTable")
        self.table.setAccessibleName("Sales summary by product")
        self.table.setAccessibleDescription(
            "Sortable product totals, quantities, averages, minimums, and maximums"
        )
        self.table.setHorizontalHeaderLabels(list(_SUMMARY_HEADERS))
        prepare_table(self.table, numeric_columns=range(1, 6), empty_text=_EMPTY_SALES)
        self._label_columns(_SUMMARY_HEADERS)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Largest totals first; enabling sorting otherwise sorts by product, Z-A.
        self.table.sortItems(2, Qt.SortOrder.DescendingOrder)
        table_layout.addWidget(self.table)
        self.content_splitter.addWidget(table_panel)

        chart_panel = QGroupBox("Visual analysis")
        chart_panel.setObjectName("panel")
        chart_layout = QVBoxLayout(chart_panel)
        self.chart_tabs = QTabWidget()
        self.chart_tabs.setDocumentMode(True)
        self.trend_chart = _SalesChart("Sales trend chart")
        self.product_chart = _SalesChart("Sales by product chart")
        self.top_clients_chart = _SalesChart("Top clients chart")
        self.comparison_chart = _SalesChart("Period comparison chart")
        self.chart_tabs.addTab(self.trend_chart, "Trend")
        self.chart_tabs.addTab(self.product_chart, "Products")
        self.chart_tabs.addTab(self.top_clients_chart, "Top clients")
        self._comparison_tab_index = self.chart_tabs.addTab(
            self.comparison_chart, "Period comparison"
        )
        self.chart_tabs.setTabVisible(self._comparison_tab_index, False)
        chart_layout.addWidget(self.chart_tabs)
        self.content_splitter.addWidget(chart_panel)
        self.content_splitter.setSizes([360, 390])
        body_layout.addWidget(self.content_splitter, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusMessage")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.setAccessibleName("Sales page status")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        body_layout.addWidget(self.status_label)

        self._reflow(force=True)

    @staticmethod
    def _make_optional_date_edit(accessible_name: str, tooltip: str) -> QDateEdit:
        editor = QDateEdit()
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("yyyy-MM-dd")
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

    # ---------------------------------------------------------- data state

    def _load_filter_options(self) -> None:
        """Load distinct clients/products while preserving the selection."""
        try:
            clients_provider = self._clients_provider
            products_provider = self._products_provider
            if clients_provider is None or products_provider is None:
                from analysis import get_unique_clients, get_unique_products

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
        self.reload_data()

    def reload_data(self, *, announce: bool = True) -> AnalysisSnapshot | Any | None:
        """Query one fresh snapshot from the existing sales controller."""
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
        """Public shell hook to call after an import transaction commits."""
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
            comparison_note("total_sales", format_eur),
        )
        self.transactions_card.set_value(
            f"{metrics.transactions:,}",
            comparison_note("transactions", lambda value: f"{int(value):,}"),
        )
        self.average_card.set_value(
            format_eur(metrics.avg_ticket),
            comparison_note("avg_ticket", format_eur),
        )
        self.clients_card.set_value(
            f"{metrics.unique_clients:,}",
            comparison_note("unique_clients", lambda value: f"{int(value):,}"),
        )
        self.products_card.set_value(f"{len(period.product_distribution.labels):,}")

        self._populate_table(snapshot)
        self._render_charts(snapshot)

    def _populate_table(self, snapshot: AnalysisSnapshot | Any | None) -> None:
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        if snapshot is None:
            self._label_columns(_SUMMARY_HEADERS)
            self.table.setRowCount(0)
            self.table.setSortingEnabled(True)
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
                comparison_values[4].setForeground(color)
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
                )
                for column, item in enumerate(summary_values):
                    self.table.setItem(row_index, column, item)
            description = "Product quantities, sales totals, averages, minimums, and maximums"

        self.table.setAccessibleDescription(description)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)

    def _label_columns(self, headers: tuple[str, ...]) -> None:
        """Set the columns for the summary or comparison view; numbers are right-aligned."""
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

    # --------------------------------------------------------------- charts

    @staticmethod
    def _style_axis(
        axis: Any,
        colors: dict[str, str],
        *,
        ylabel: str = "Sales",
        grid_axis: str = "y",
        value_axis: str = "y",
    ) -> None:
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color(colors["grid"])
        axis.spines["bottom"].set_color(colors["grid"])
        axis.grid(axis=grid_axis, color=colors["grid"], linewidth=0.8, alpha=0.8)
        axis.set_axisbelow(True)
        axis.tick_params(colors=colors["muted"], labelsize=9)
        axis.xaxis.label.set_color(colors["text"])
        axis.yaxis.label.set_color(colors["text"])
        axis.set_ylabel(ylabel, color=colors["text"])
        formatted_axis = axis.yaxis if value_axis == "y" else axis.xaxis
        formatted_axis.set_major_formatter(
            FuncFormatter(lambda value, _pos: f"€{value:,.0f}")
        )
        formatted_axis.set_major_locator(MaxNLocator(nbins=6))

    def _chart_colors(self) -> dict[str, str]:
        palette = self.palette()
        surface_color = palette.color(QPalette.ColorRole.Base)
        dark = surface_color.lightnessF() < 0.5
        return {
            "surface": surface_color.name(),
            "text": palette.color(QPalette.ColorRole.Text).name(),
            "muted": palette.color(QPalette.ColorRole.PlaceholderText).name(),
            "grid": "#3F4945" if dark else _GRID,
            "primary": _BRAND_GREEN if dark else _BRAND_GREEN_DARK,
            "secondary": _BRAND_GOLD if dark else "#936B00",
        }

    def _prepare_chart(self, chart: _SalesChart) -> tuple[Any, dict[str, str]]:
        colors = self._chart_colors()
        figure = chart.figure
        figure.clear()
        figure.set_facecolor(colors["surface"])
        axis = figure.add_subplot(111)
        axis.set_facecolor(colors["surface"])
        return axis, colors

    def _render_charts(self, snapshot: AnalysisSnapshot | Any | None) -> None:
        """Render all chart pixmaps, including after an application theme change."""
        if snapshot is None:
            self.trend_chart.empty("No sales data for the selected filters")
            self.product_chart.empty("No product data for the selected filters")
            self.top_clients_chart.empty("No client data for the selected filters")
            self.comparison_chart.empty("Enable comparison to compare two periods")
            self.chart_tabs.setTabVisible(self._comparison_tab_index, False)
            return
        self._render_trend_chart(snapshot)
        self._render_product_chart(snapshot)
        self._render_top_clients_chart(snapshot)
        self._render_comparison_chart(snapshot)

    @staticmethod
    def _sparse_ticks(axis: Any, labels: list[str]) -> None:
        count = len(labels)
        if not count:
            return
        step = max(1, count // 8)
        positions = list(range(0, count, step))
        if count - 1 not in positions:
            positions.append(count - 1)
        axis.set_xticks(positions)
        axis.set_xticklabels([labels[index] for index in positions], rotation=30, ha="right")

    def _render_trend_chart(self, snapshot: AnalysisSnapshot | Any) -> None:
        evolution = snapshot.period_a.evolution
        labels = list(evolution.labels or [])
        values = [float(value) for value in evolution.values or []]
        if not labels or not values:
            self.trend_chart.empty("No trend data is available")
            return

        axis, colors = self._prepare_chart(self.trend_chart)
        axis.plot(
            range(len(values)),
            values,
            color=colors["primary"],
            linewidth=2.4,
            marker="o" if len(values) <= 24 else None,
            markersize=4,
            label="Period A",
        )
        axis.fill_between(
            range(len(values)), values, color=colors["primary"], alpha=0.14
        )
        axis.set_title(
            f"Sales trend · {snapshot.metadata.grouping.value.title()}",
            loc="left",
            color=colors["text"],
            fontweight="bold",
        )
        self._style_axis(axis, colors)
        self._sparse_ticks(axis, labels)
        self.trend_chart.setAccessibleDescription(
            f"Sales trend with {len(values)} {snapshot.metadata.grouping.value} data points"
        )
        self.trend_chart.draw_idle()

    def _render_product_chart(self, snapshot: AnalysisSnapshot | Any) -> None:
        distribution = snapshot.period_a.product_distribution
        labels = list(distribution.labels or [])
        values = [float(value) for value in distribution.values or []]
        if not labels or not values:
            self.product_chart.empty("No product distribution is available")
            return

        visible_rows = sorted(zip(labels, values), key=lambda item: item[1])[-12:]
        chart_labels = [label if len(label) <= 26 else f"{label[:25]}…" for label, _ in visible_rows]
        chart_values = [value for _, value in visible_rows]
        axis, colors = self._prepare_chart(self.product_chart)
        # Numeric positions: equal (e.g. truncated) category labels would
        # otherwise be merged by Matplotlib into one overdrawn bar.
        positions = list(range(len(chart_values)))
        bars = axis.barh(positions, chart_values, color=colors["primary"], alpha=0.92)
        axis.set_yticks(positions, chart_labels)
        axis.set_title(
            "Sales by product", loc="left", color=colors["text"], fontweight="bold"
        )
        self._style_axis(
            axis, colors, ylabel="", grid_axis="x", value_axis="x"
        )
        axis.bar_label(
            bars,
            labels=[f"€{value:,.0f}" for value in chart_values],
            padding=4,
            fontsize=8,
            color=colors["text"],
        )
        self.product_chart.setAccessibleDescription(
            f"Horizontal bar chart showing sales for {len(labels)} products"
        )
        self.product_chart.draw_idle()

    def _render_top_clients_chart(self, snapshot: AnalysisSnapshot | Any) -> None:
        """Rank period A's top clients by revenue (restored from the Flet UI)."""
        ranking = sorted(
            snapshot.period_a.top_clients or [],
            key=lambda client: float(client.total_sales),
        )
        if not ranking:
            self.top_clients_chart.empty("No client ranking is available")
            return

        labels = [
            name if len(name) <= 26 else f"{name[:25]}…"
            for name in (str(client.client_name) for client in ranking)
        ]
        values = [float(client.total_sales) for client in ranking]
        axis, colors = self._prepare_chart(self.top_clients_chart)
        positions = list(range(len(values)))  # same-named clients stay separate bars
        bars = axis.barh(positions, values, color=colors["primary"], alpha=0.92)
        axis.set_yticks(positions, labels)
        axis.set_title(
            "Top clients by sales", loc="left", color=colors["text"], fontweight="bold"
        )
        self._style_axis(
            axis, colors, ylabel="", grid_axis="x", value_axis="x"
        )
        axis.bar_label(
            bars,
            labels=[
                f"€{client.total_sales:,.0f} · {client.transactions:,} sales · {client.percentage_of_total:.1f}%"
                for client in ranking
            ],
            padding=4,
            fontsize=8,
            color=colors["text"],
        )
        axis.margins(x=0.35)  # room for the value labels
        self.top_clients_chart.setAccessibleDescription(
            "Top clients by sales: "
            + "; ".join(
                f"{client.client_name} {format_eur(client.total_sales)}" for client in reversed(ranking)
            )
        )
        self.top_clients_chart.draw_idle()

    def _render_comparison_chart(self, snapshot: AnalysisSnapshot | Any) -> None:
        comparison = snapshot.comparison if snapshot.is_compare_mode() else None
        visible = comparison is not None
        self.chart_tabs.setTabVisible(self._comparison_tab_index, visible)
        if comparison is None:
            self.comparison_chart.empty("Enable comparison to compare two periods")
            return

        points = list(comparison.evolution.points or [])
        if not points:
            self.comparison_chart.empty("No overlapping comparison trend is available")
            return
        labels = [point.label for point in points]
        values_a = [float(point.value_a) for point in points]
        values_b = [float(point.value_b) for point in points]
        axis, colors = self._prepare_chart(self.comparison_chart)
        positions = range(len(points))
        axis.plot(
            positions,
            values_a,
            color=colors["primary"],
            linewidth=2.3,
            label="Period A",
        )
        axis.plot(
            positions,
            values_b,
            color=colors["secondary"],
            linewidth=2.3,
            label="Period B",
        )
        axis.set_title(
            "Period A vs. Period B",
            loc="left",
            color=colors["text"],
            fontweight="bold",
        )
        self._style_axis(axis, colors)
        self._sparse_ticks(axis, labels)
        legend = axis.legend(frameon=False, loc="best")
        for label in legend.get_texts():
            label.set_color(colors["text"])
        self.comparison_chart.setAccessibleDescription(
            f"Line chart comparing periods A and B across {len(points)} intervals"
        )
        self.comparison_chart.draw_idle()

    # -------------------------------------------------------------- actions

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
        """Write the visible snapshot to ``filename`` without querying again."""
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
                from ..support import explain

                result = (False, explain(exc)[0], None)
                self._notify(result[1], error=True)
                return result
        try:
            # Lazy import avoids coupling Qt canvas setup to the report module's
            # intentionally headless Matplotlib backend.
            report_generator = self._report_generator
            if report_generator is None:
                from reports.report_html import generate_html_report_from_snapshot

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

    # ----------------------------------------------------------- date ranges

    @Slot(bool)
    def _comparison_toggled(self, enabled: bool) -> None:
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
                from analysis import get_date_range

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

    # ---------------------------------------------------------- responsiveness

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() not in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        }:
            return
        if hasattr(self, "trend_chart"):
            self._render_charts(self.current_snapshot)
        if hasattr(self, "table"):  # gain/loss colours follow the theme
            self._populate_table(self.current_snapshot)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, *, force: bool = False) -> None:
        viewport_width = (
            self.scroll_area.viewport().width()
            if hasattr(self, "scroll_area")
            else self.width()
        )
        # Match breakpoints against usable content, not the outer page. This
        # keeps fields and KPI cards comfortably sized in a 760x600 window.
        width = max(0, viewport_width - 48)
        field_columns = 4 if width >= 1120 else 2 if width >= 620 else 1
        compare_columns = 4 if width >= 1000 else 2 if width >= 620 else 1
        kpi_columns = 5 if width >= 1240 else 3 if width >= 760 else 2 if width >= 480 else 1
        bucket = (field_columns, compare_columns, kpi_columns)
        if not force and bucket == self._last_layout_bucket:
            return
        self._last_layout_bucket = bucket
        self._replace_grid(self.filter_grid, self._filter_fields, field_columns)
        self._replace_grid(self.compare_grid, self._compare_fields, compare_columns)
        self._replace_grid(self.kpi_grid, self._kpi_cards, kpi_columns)

    @staticmethod
    def _replace_grid(
        layout: QGridLayout,
        widgets: Sequence[QWidget],
        columns: int,
    ) -> None:
        # removeWidget() deletes the layout item; takeAt() leaked it (PySide
        # marks the returned item C++-owned, so nothing ever frees it).
        for widget in widgets:
            layout.removeWidget(widget)
        for column in range(6):
            layout.setColumnStretch(column, 0)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, index // columns, index % columns)
        for column in range(max(1, columns)):
            layout.setColumnStretch(column, 1)

    # -------------------------------------------------------------- feedback

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
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)
        self.statusMessage.emit(message)
        if self._on_status is not None:
            try:
                self._on_status(message)
            except Exception:
                logger.exception("Sales status callback failed")

