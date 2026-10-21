"""PySide6 dashboard: sales and lead intelligence, plus the signed-in user's work."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

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

from controllers.dashboard_controller import DashboardController
from crm.services import work
from utils.formatting import format_day_month_year_time
from utils.import_templates import write_template

from ..dialogs import ask_confirmation
from ..session import AppContext
from ..support import local_time, report
from ..theme import PRIMARY, SECONDARY
from ..widgets import Card, KpiCard, PageHeader


class DashboardPage(QWidget):
    """Overview, quick actions, import help, and destructive maintenance actions."""

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
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setAccessibleName("Scrollable dashboard")
        outer.addWidget(scroll)

        body = QWidget()
        body.setObjectName("pageBody")
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(24, 22, 24, 30)
        self._layout.setSpacing(20)
        scroll.setWidget(body)

        heading_row = QHBoxLayout()
        heading_row.addWidget(
            PageHeader("Dashboard", "Lead, client, and sales intelligence at a glance."),
            1,
        )
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.setAccessibleName("Refresh dashboard metrics")
        refresh.clicked.connect(self.refresh)
        heading_row.addWidget(refresh, 0, Qt.AlignmentFlag.AlignTop)
        self._layout.addLayout(heading_row)

        self._kpi_grid = QGridLayout()
        self._kpi_grid.setHorizontalSpacing(14)
        self._kpi_grid.setVerticalSpacing(14)
        self.sales_card = KpiCard("Sales records", accent=PRIMARY)
        self.clients_card = KpiCard("Clients", accent=SECONDARY)
        self.leads_card = KpiCard("Leads", accent=PRIMARY)
        self.conversion_card = KpiCard("Lead conversion", accent=SECONDARY)
        for index, card in enumerate(
            (self.sales_card, self.clients_card, self.leads_card, self.conversion_card)
        ):
            self._kpi_grid.addWidget(card, index // 2, index % 2)
        self._layout.addLayout(self._kpi_grid)

        # The signed-in user's work: their tasks and leads, counted live.
        self.work_card = Card()
        work_layout = QVBoxLayout(self.work_card)
        work_layout.setContentsMargins(20, 18, 20, 20)
        work_title = QLabel("My work")
        work_title.setObjectName("sectionTitle")
        work_layout.addWidget(work_title)
        work_row = QHBoxLayout()
        self._work_buttons: dict[str, QPushButton] = {}
        for key, tooltip in (
            ("overdue", "Your open tasks whose due time has passed"),
            ("today", "Your open tasks due today"),
            ("open", "All your open tasks"),
            ("my_leads", "Open leads you own"),
            ("unassigned", "New leads nobody owns yet"),
        ):
            button = QPushButton()
            button.setObjectName("secondaryButton")
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, target=key: self._open_work(target))
            work_row.addWidget(button)
            self._work_buttons[key] = button
        work_row.addStretch(1)
        work_layout.addLayout(work_row)
        self.upcoming_label = QLabel()
        self.upcoming_label.setObjectName("pageSubtitle")
        self.upcoming_label.setWordWrap(True)
        self.upcoming_label.setTextFormat(Qt.TextFormat.PlainText)
        work_layout.addWidget(self.upcoming_label)
        self.work_card.setVisible(False)
        self._layout.addWidget(self.work_card)

        actions = Card()
        action_layout = QVBoxLayout(actions)
        action_layout.setContentsMargins(20, 18, 20, 20)
        heading = QLabel("Quick actions")
        heading.setObjectName("sectionTitle")
        action_layout.addWidget(heading)
        action_row = QHBoxLayout()
        import_button = QPushButton("Import data")
        import_button.setObjectName("primaryButton")
        import_button.setAccessibleName("Import CSV or Excel data")
        import_button.clicked.connect(self._request_import)
        self.import_button = import_button
        action_row.addWidget(import_button)
        for label, target in (("Sales analytics", "sales"), ("Leads", "leads"), ("Clients", "clients")):
            button = QPushButton(label)
            button.setObjectName("secondaryButton")
            button.clicked.connect(lambda _checked=False, page=target: self._navigate(page))
            action_row.addWidget(button)
        action_row.addStretch(1)
        action_layout.addLayout(action_row)
        self._layout.addWidget(actions)

        lower = QGridLayout()
        lower.setHorizontalSpacing(16)
        lower.setVerticalSpacing(16)
        template_card = Card()
        template_layout = QVBoxLayout(template_card)
        template_layout.setContentsMargins(20, 18, 20, 20)
        template_title = QLabel("Import templates")
        template_title.setObjectName("sectionTitle")
        template_copy = QLabel(
            "Download a correctly structured CSV for sales, leads, or marketing spend."
        )
        template_copy.setObjectName("pageSubtitle")
        template_copy.setWordWrap(True)
        template_layout.addWidget(template_title)
        template_layout.addWidget(template_copy)
        template_buttons = QHBoxLayout()
        for label, template_type in (
            ("Sales CSV", "sales"),
            ("Leads CSV", "leads"),
            ("Spend CSV", "marketing_spend"),
        ):
            button = QPushButton(label)
            button.setObjectName("secondaryButton")
            button.clicked.connect(
                lambda _checked=False, kind=template_type: self._save_template(kind)
            )
            template_buttons.addWidget(button)
        template_layout.addLayout(template_buttons)
        template_layout.addStretch(1)  # align titles across the row
        lower.addWidget(template_card, 0, 0)

        status_card = Card()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 18, 20, 20)
        status_title = QLabel("Data status")
        status_title.setObjectName("sectionTitle")
        self.status_label = QLabel("No data loaded yet.")
        self.status_label.setObjectName("pageSubtitle")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_layout.addWidget(status_title)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch(1)
        lower.addWidget(status_card, 0, 1)
        self._layout.addLayout(lower)

        maintenance = Card()
        self.maintenance_card = maintenance
        maintenance_layout = QVBoxLayout(maintenance)
        maintenance_layout.setContentsMargins(20, 18, 20, 20)
        maintenance_title = QLabel("Data maintenance")
        maintenance_title.setObjectName("sectionTitle")
        warning = QLabel(
            "These actions permanently clear local records. Client removal also removes linked sales."
        )
        warning.setObjectName("pageSubtitle")
        warning.setWordWrap(True)
        maintenance_layout.addWidget(maintenance_title)
        maintenance_layout.addWidget(warning)
        maintenance_buttons = QHBoxLayout()
        for label, key in (
            ("Clear sales", "sales"),
            ("Clear leads", "leads"),
            ("Clear clients", "clients"),
        ):
            button = QPushButton(label)
            button.setObjectName("dangerButton")
            button.clicked.connect(lambda _checked=False, table=key: self._clear_data(table))
            maintenance_buttons.addWidget(button)
        maintenance_buttons.addStretch(1)
        maintenance_layout.addLayout(maintenance_buttons)
        self._layout.addWidget(maintenance)
        self._layout.addStretch(1)

    def _refresh_work(self) -> None:
        context = self.context
        signed_in = context is not None and context.is_signed_in
        if context is not None:
            self.import_button.setVisible(context.can("data.import"))
            self.maintenance_card.setVisible(context.can("data.clear"))
        self.work_card.setVisible(signed_in)
        if not signed_in or context is None:
            return
        try:
            summary = context.run(lambda db, actor: work.summary(db, actor), busy=False)
        except Exception as exc:
            report(self, exc, title="Dashboard")
            return
        zone = context.actor.timezone if context.actor else "UTC"
        labels = {
            "overdue": f"{summary.overdue} overdue",
            "today": f"{summary.due_today} due today",
            "open": f"{summary.open_tasks} open tasks",
            "my_leads": f"{summary.my_open_leads} of my leads open",
            "unassigned": f"{summary.unassigned_new_leads} new leads unassigned",
        }
        for key, button in self._work_buttons.items():
            button.setText(labels[key])
            button.setAccessibleName(labels[key])
        self._work_buttons["overdue"].setProperty("alert", summary.overdue > 0)
        self._work_buttons["overdue"].style().unpolish(self._work_buttons["overdue"])
        self._work_buttons["overdue"].style().polish(self._work_buttons["overdue"])
        if summary.upcoming:
            lines = [f"• {title} — {local_time(due, zone) or 'no due date'}{' (overdue)' if late else ''}"
                     for _task_id, title, due, late in summary.upcoming]
            self.upcoming_label.setText("Next up:\n" + "\n".join(lines))
        else:
            self.upcoming_label.setText("No open tasks assigned to you.")

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
        if snapshot.last_import:
            try:
                last_import = format_day_month_year_time(
                    datetime.fromisoformat(snapshot.last_import)
                )
            except (TypeError, ValueError):
                last_import = str(snapshot.last_import)
            self.status_label.setText(
                f"Local database active. Last import: {last_import}. "
                f"{snapshot.sales_rows} sales rows and {snapshot.total_leads} leads are available."
            )
        else:
            self.status_label.setText(
                "Local database is ready. Import a CSV or Excel file to begin analysis."
            )

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

    _CLEAR_CONFIRMATIONS = {
        "sales": (
            "Delete sales records",
            "Delete all sales records?",
            "Every imported sale is removed from this computer. Clients and leads are kept. "
            "This cannot be undone.",
            "Delete sales",
        ),
        "leads": (
            "Delete leads",
            "Delete all leads?",
            "Every lead is removed, including stages and meeting dates. Clients and sales are kept. "
            "This cannot be undone.",
            "Delete leads",
        ),
        "clients": (
            "Delete clients",
            "Delete all clients?",
            "Every client and all of their sales are removed. Leads are kept but no longer linked "
            "to a client. This cannot be undone.",
            "Delete clients and sales",
        ),
    }

    def _clear_data(self, table: str) -> None:
        title, heading, message, confirm_text = self._CLEAR_CONFIRMATIONS[table]
        if not ask_confirmation(
            self,
            title=title,
            heading=heading,
            message=message,
            confirm_text=confirm_text,
            destructive=True,
        ):
            return
        operation = {
            "sales": DashboardController.clear_sales,
            "leads": DashboardController.clear_leads,
            "clients": DashboardController.clear_clients,
        }[table]
        if self.context is None:
            success, message = operation()
        else:
            try:
                success, message = self.context.guarded(
                    "data.clear", f"data.cleared_{table}", operation, kind="data", entity_type="data",
                    changes=lambda outcome: {"table": table, "result": outcome[1]} if outcome[0] else None,
                )
            except Exception as exc:
                report(self, exc, title="Data maintenance")
                return
        self.status_requested.emit(message, "success" if success else "error")
        if success:
            self.refresh()
            self.data_changed.emit()
