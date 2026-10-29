from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from techset_leadgen.analytics.controllers.dashboard_controller import DashboardController
from techset_leadgen.services import work
from techset_leadgen.utils.formatting import format_day_month_year_time, format_eur
from techset_leadgen.utils.import_templates import write_template

from techset_leadgen.desktop.icons import ThemedIconLabel, set_button_icon
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import local_time, report
from techset_leadgen.desktop.theme import PRIMARY, SECONDARY
from techset_leadgen.desktop.widgets import BarChart, Card, CountChip, EmptyState, IconChip, KpiCard, PageHeader, SectionCard

_TEMPLATES = (
    ("Sales CSV", "sales", "receipt-plain", "green"),
    ("Leads CSV", "leads", "leads", "green"),
    ("Marketing spend CSV", "marketing_spend", "money", "gold"),
)


_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def _long_date(day: date) -> str:
    return f"{_DAYS[day.weekday()]}, {day.day} {_MONTHS[day.month - 1]} {day.year}"


def _link_button(text: str, handler: Callable[[], object]) -> QPushButton:
    button = QPushButton(text + "  →")
    button.setObjectName("linkButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda _checked=False: handler())
    return button


class DashboardPage(QWidget):
    data_changed = Signal()
    status_requested = Signal(str, str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_navigate: Callable[..., object] | None = None,
        on_import_requested: Callable[[], bool | None] | None = None,
        context: AppContext | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self._on_navigate = on_navigate
        self._on_import_requested = on_import_requested
        self.setObjectName("dashboardPage")
        self.setAccessibleName("Dashboard")
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("pageScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setAccessibleName("Scrollable dashboard")
        outer.addWidget(scroll)

        body = QWidget()
        body.setObjectName("pageBody")
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(28, 24, 28, 40)
        self._layout.setSpacing(20)
        scroll.setWidget(body)

        self.header = PageHeader("Dashboard", "Lead, client and sales intelligence at a glance")
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.setAccessibleName("Refresh dashboard metrics")
        set_button_icon(refresh, "refresh")
        refresh.clicked.connect(self._refresh_clicked)
        self.header.add_action(refresh)
        self.import_button = QPushButton("Import data")
        self.import_button.setObjectName("primaryButton")
        self.import_button.setAccessibleName("Import CSV or Excel data")
        set_button_icon(self.import_button, "upload", "onPrimary")
        self.import_button.clicked.connect(self._request_import)
        self.header.add_action(self.import_button)
        self._layout.addWidget(self.header)

        self._kpi_grid = QGridLayout()
        self._kpi_grid.setHorizontalSpacing(16)
        self._kpi_grid.setVerticalSpacing(16)
        self.sales_card = KpiCard("Sales records", accent=PRIMARY, icon="receipt", clickable=True)
        self.clients_card = KpiCard("Clients", accent=SECONDARY, icon="people", clickable=True)
        self.leads_card = KpiCard("Leads", accent=PRIMARY, icon="leads", clickable=True)
        self.conversion_card = KpiCard("Lead conversion", accent=SECONDARY, icon="target", clickable=True)
        self._kpis = (self.sales_card, self.clients_card, self.leads_card, self.conversion_card)
        for card, target in zip(self._kpis, ("sales", "clients", "leads", "leads")):
            card.clicked.connect(lambda page=target: self._navigate(page))
        self._layout.addLayout(self._kpi_grid)
        self._kpi_columns = 0
        self._place_kpis(4)

        self.work_card = SectionCard("My work", divider=False)
        self.work_card.header_layout.setContentsMargins(20, 18, 20, 0)
        self.work_card.body.setContentsMargins(19, 12, 19, 18)
        self.work_card.add_action(_link_button("Open tasks", lambda: self._open_work("open")))
        work_row = QHBoxLayout()
        work_row.setSpacing(8)
        self._work_buttons: dict[str, CountChip] = {}
        for key, label, tone, tooltip in (
            ("overdue", "Overdue", "danger", "Your open tasks whose due time has passed"),
            ("today", "Due today", "warning", "Your open tasks due today"),
            ("open", "Open tasks", "", "All your open tasks"),
            ("my_leads", "Of my leads open", "", "Open leads you own"),
            ("unassigned", "New leads unassigned", "", "New leads nobody owns yet"),
        ):
            button = CountChip(label, tone)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, target=key: self._open_work(target))
            work_row.addWidget(button)
            self._work_buttons[key] = button
        work_row.addStretch(1)
        self.work_card.body.addLayout(work_row)
        self.upcoming_label = QLabel()
        self.upcoming_label.setObjectName("sectionSubtitle")
        self.upcoming_label.setWordWrap(True)
        self.upcoming_label.setTextFormat(Qt.TextFormat.PlainText)
        self.upcoming_label.hide()
        self.work_card.setVisible(False)
        self._layout.addWidget(self.work_card)

        self._lower_grid = QGridLayout()
        self._lower_grid.setHorizontalSpacing(16)
        self._lower_grid.setVerticalSpacing(16)
        self.trend_card = SectionCard("Revenue trend", "Weekly revenue, last 8 weeks")
        self.trend_card.add_action(_link_button("Sales analytics", lambda: self._navigate("sales")))
        self.trend_chart = BarChart("Weekly revenue chart")
        self.trend_card.body.addWidget(self.trend_chart, 1)
        self.trend_empty = EmptyState("No sales yet", "Import a Sales CSV or Excel file to see your revenue trend here.",
                                      icon="chart")
        self.trend_empty_import = self.trend_empty.add_action("Import data", self._request_import, primary=True)
        self.trend_empty.hide()
        self.trend_card.body.addWidget(self.trend_empty, 1)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(16)
        template_card = SectionCard("Import templates", "Correctly structured CSVs, ready to fill", padded=False)
        template_card.body.setContentsMargins(12, 8, 12, 8)
        template_card.body.setSpacing(0)
        for label, template_type, icon_name, tone in _TEMPLATES:
            template_card.body.addWidget(self._template_row(label, template_type, icon_name, tone))
        side_layout.addWidget(template_card)

        status_card = Card()
        status_row = QHBoxLayout(status_card)
        status_row.setContentsMargins(20, 18, 20, 18)
        status_row.setSpacing(14)
        status_row.addWidget(IconChip("check-circle"), 0, Qt.AlignmentFlag.AlignTop)
        status_text = QVBoxLayout()
        status_text.setSpacing(4)
        status_title = QLabel("Data status")
        status_title.setObjectName("sectionTitle")
        self.status_label = QLabel("No data loaded yet.")
        self.status_label.setObjectName("sectionSubtitle")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_text.addWidget(status_title)
        status_text.addWidget(self.status_label)
        status_row.addLayout(status_text, 1)
        side_layout.addWidget(status_card)
        side_layout.addStretch(1)
        self._side = side
        self._place_lower(wide=True)
        self._layout.addLayout(self._lower_grid)
        self._layout.addStretch(1)

    def _template_row(self, label: str, template_type: str, icon_name: str, tone: str) -> QPushButton:
        row = QPushButton(label)
        row.setObjectName("listRow")
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setAccessibleName(f"Download the {label} template")
        row.setToolTip(f"Save a {label} template")
        row.setMinimumHeight(48)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)
        chip = IconChip(icon_name, tone, size=32, icon_size=16)
        download = ThemedIconLabel("download", "text", 18)
        for child in (chip, download):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(chip)
        layout.addStretch(1)
        layout.addWidget(download)
        row.clicked.connect(lambda _checked=False, kind=template_type: self._save_template(kind))
        return row


    def _place_kpis(self, columns: int) -> None:
        if columns == self._kpi_columns:
            return
        self._kpi_columns = columns
        for card in self._kpis:
            self._kpi_grid.removeWidget(card)
        for index, card in enumerate(self._kpis):
            self._kpi_grid.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self._kpi_grid.setColumnStretch(column, 1 if column < columns else 0)

    def _place_lower(self, *, wide: bool) -> None:
        self._lower_grid.removeWidget(self.trend_card)
        self._lower_grid.removeWidget(self._side)
        if wide:
            self._lower_grid.addWidget(self.trend_card, 0, 0)
            self._lower_grid.addWidget(self._side, 0, 1)
            self._lower_grid.setColumnStretch(0, 16)
            self._lower_grid.setColumnStretch(1, 10)
        else:
            self._lower_grid.addWidget(self.trend_card, 0, 0)
            self._lower_grid.addWidget(self._side, 1, 0)
            self._lower_grid.setColumnStretch(0, 1)
            self._lower_grid.setColumnStretch(1, 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = event.size().width()
        self._place_kpis(4 if width >= 1000 else 2)
        self._place_lower(wide=width >= 900)


    def _refresh_work(self) -> None:
        context = self.context
        signed_in = context is not None and context.is_signed_in
        if context is not None:
            self.import_button.setVisible(context.can("data.import"))
        self.work_card.setVisible(signed_in)
        if not signed_in or context is None:
            return
        actor = context.actor
        if actor is not None:
            first_name = actor.full_name.split()[0] if actor.full_name.split() else actor.full_name
            self.header.set_title(f"Welcome back, {first_name}")
        try:
            summary = context.run(lambda db, actor: work.summary(db, actor), busy=False)
        except Exception as exc:
            report(self, exc, title="Dashboard")
            return
        zone = context.actor.timezone if context.actor else "UTC"
        counts = {
            "overdue": (summary.overdue, f"{summary.overdue} overdue"),
            "today": (summary.due_today, f"{summary.due_today} due today"),
            "open": (summary.open_tasks, f"{summary.open_tasks} open tasks"),
            "my_leads": (summary.my_open_leads, f"{summary.my_open_leads} of my leads open"),
            "unassigned": (summary.unassigned_new_leads, f"{summary.unassigned_new_leads} new leads unassigned"),
        }
        for key, button in self._work_buttons.items():
            button.set_count(*counts[key])
        count = summary.open_tasks
        self.work_card.set_subtitle(f"You have {count} open task{'s' if count != 1 else ''}")
        if summary.upcoming:
            lines = [f"• {title} — {local_time(due, zone) or 'no due date'}{' (overdue)' if late else ''}"
                     for _task_id, title, due, late in summary.upcoming]
            self.upcoming_label.setText("Next up:\n" + "\n".join(lines))
        else:
            self.upcoming_label.setText("No open tasks assigned to you.")
        self._work_buttons["open"].setToolTip(self.upcoming_label.text())

    def _open_work(self, key: str) -> None:
        if self._on_navigate is None:
            return
        if key in ("overdue", "today", "open"):
            self._on_navigate("tasks", {"view": "mine", "due": key})
        else:
            self._on_navigate("leads")
            leads_page = self.window().findChild(QWidget, "leadsPage")
            owner = "me" if key == "my_leads" else "none"
            if leads_page is not None and hasattr(leads_page, "owner_combo"):
                leads_page.owner_combo.setCurrentIndex(max(leads_page.owner_combo.findData(owner), 0))

    def ensure_loaded(self) -> None:
        self._refresh_work()

    def refresh(self) -> None:
        self.header.set_subtitle(f"Lead, client and sales intelligence at a glance · {_long_date(date.today())}")
        self._refresh_work()
        snapshot = DashboardController.get_dashboard_kpi_snapshot()
        self.sales_card.set_value(str(snapshot.sales_rows), "Imported transaction rows")
        self.clients_card.set_value(str(snapshot.clients_rows), "Local client profiles")
        self.leads_card.set_value(
            str(snapshot.total_leads),
            f"{snapshot.leads_with_meeting} reached a meeting",
        )
        self.conversion_card.set_value(
            f"{snapshot.leads_conversion_rate:.1f}%",
            f"{snapshot.leads_this_month} leads added this month",
        )
        weeks = DashboardController.get_weekly_revenue(8)
        self.trend_chart.set_data([label for label, _ in weeks], [value for _, value in weeks],
                                  value_format=lambda value: format_eur(value, 0),
                                  empty="No sales in the last 8 weeks.")
        no_sales = snapshot.sales_rows == 0
        self.trend_chart.setVisible(not no_sales)
        self.trend_empty.setVisible(no_sales)
        if self.context is not None:
            self.trend_empty_import.setVisible(self.context.can("data.import"))
        if snapshot.last_import:
            try:
                last_import = format_day_month_year_time(
                    datetime.fromisoformat(snapshot.last_import)
                )
            except (TypeError, ValueError):
                last_import = str(snapshot.last_import)
            self.status_label.setText(
                f"Local database is healthy. Last import: {last_import}. "
                f"{snapshot.sales_rows} sales rows and {snapshot.total_leads} leads are available."
            )
        else:
            self.status_label.setText(
                "Local database is ready. Import a CSV or Excel file to begin analysis."
            )

    def _refresh_clicked(self) -> None:
        self.refresh()
        self.status_requested.emit("Dashboard refreshed", "success")

    def _request_import(self) -> None:
        if self._on_import_requested:
            self._on_import_requested()

    def _navigate(self, page: str) -> None:
        if self._on_navigate:
            self._on_navigate(page)

    def _save_template(self, template_type: str) -> None:
        default_name = f"techset_{template_type}_template.csv"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save import template",
            default_name,
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            destination = write_template(template_type, path)
        except OSError as exc:
            self.status_requested.emit(f"Could not save template: {exc}", "error")
        else:
            self.status_requested.emit(f"Template saved to {destination}", "success")

