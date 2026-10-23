"""Native PySide6 client management page.

The list and sales figures come from the established controller/analysis layers.
Adding, editing, and deleting clients, their contacts, activities, and tasks go
through the business services via the signed-in session (format and duplicate
rules from ``models.client_validators``, plus roles and the audit trail).
Duplicate merging keeps its original implementation, guarded the same way.
"""

from __future__ import annotations

from functools import partial

import logging
import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QPlainTextEdit,
    QCheckBox,
    QComboBox,
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
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analysis.leads_analysis import get_leads
from controllers.clients_controller import ClientsController
from controllers.leads_controller import LeadsController
from crm.models import Client
from crm.schemas import ClientCreate, ClientUpdate, parse
from crm.security.permissions import Scope
from crm.services import clients as client_service
from crm.services import contacts as contact_service
from crm.services import leads as lead_service
from crm.services import tasks as task_service
from crm.services.pagination import PageRequest
from crm.vocabulary import ACCOUNT_STATUSES, EMPLOYEE_RANGES, TASK_STATUSES
from domain.lead_stages import LEAD_STATUSES
from domain.source_labels import SOURCE_LABELS
from models.lead_manager import get_latest_lead_per_client
from reports.report_client_html import generate_client_html_report

from ..dialogs import ask_confirmation
from ..modal import ModalDialog
from ..row_actions import RowAction, RowActionDelegate, install_row_action_menu
from ..session import AppContext
from ..support import date_text, explain, local_time, person, report
from ..tables import (
    enable_column_choice,
    fit_columns,
    fit_table_height,
    prepare_table,
    set_empty_state,
    set_header_tips,
)
from ..theme import mono_font, tokens
from ..icons import icon, set_button_icon
from ..widgets import (
    EmptyState,
    KpiCard,
    PageHeader,
    SearchField,
    SectionCard,
    bulk_table_update,
    set_table_defaults,
    sortable_item,
)
from ..workflows import (
    ACTIVITY_COLUMNS,
    activity_rows,
    contact_form,
    delete_contact,
    log_activity,
    open_lead,
    user_options,
)

logger = logging.getLogger(__name__)

_STATUS_LABELS = LEAD_STATUSES
_CLIENT_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_ACTIONS_COLUMN = 11
_ACCOUNT_FIELDS = ("account_status", "owner_id", "industry", "website_url", "primary_domain", "employee_range",
                   "country", "city", "notes")


def _source_label(value: Any) -> str:
    raw = str(value or "unknown")
    return SOURCE_LABELS.get(raw, raw.replace("_", " ").title())


def _display(value: Any) -> str:
    text = str(value or "").strip()
    return text if text and text != "-" else "—"


def _blank(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text and text != "-" else None


def _problem(exc: Exception) -> str:
    """The message a client form shows for a failed save (field messages first)."""
    from crm.errors import DomainError

    if isinstance(exc, DomainError) and exc.fields:
        return " ".join(dict.fromkeys(exc.fields.values()))
    heading, details = explain(exc)
    return heading if not details else f"{heading} {details}"


def _mask_sensitive(value: Any) -> str:
    text = _display(value)
    if text == "—":
        return text
    if "@" in text:
        local, domain = text.split("@", 1)
        visible = local[:1]
        return f"{visible}{'•' * max(3, len(local) - 1)}@{domain}"
    if len(text) <= 4:
        return "•" * len(text)
    return f"{text[:2]}{'•' * (len(text) - 4)}{text[-2:]}"


def _item(value: Any, *, numeric: float | int | None = None, sort_key: Any = None) -> QTableWidgetItem:
    """A read-only cell; ``numeric`` right-aligns and sorts by number, ``sort_key`` only sorts."""
    result = sortable_item(_display(value), numeric if numeric is not None else sort_key)
    result.setFlags(result.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if numeric is not None:
        result.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return result


class ClientFormDialog(ModalDialog):
    """Add/edit form with optional linked-lead editing.

    ``on_submit`` performs the save while the dialog is still open. When it
    returns ``(False, message)`` the message is shown inline and the user's
    input is kept, instead of closing the form and discarding what was typed.
    """

    def __init__(
        self,
        *,
        client: tuple | None = None,
        lead: dict[str, Any] | None = None,
        parent: QWidget | None = None,
        on_submit: Callable[[ClientFormDialog], tuple[bool, str]] | None = None,
        account: dict[str, Any] | None = None,
        people: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.lead = lead
        self._account_initial = dict(account or {})
        self._on_submit = on_submit
        self.result_message = ""
        self.setWindowTitle("Edit client" if client else "Add client")
        self.setModal(True)
        self.resize(620, 580 if lead else 450)
        self.setMinimumWidth(440)
        self.setAccessibleName(self.windowTitle())

        values = client or (None, "", "", "", "", "")
        root = QVBoxLayout(self)
        title = QLabel(self.windowTitle())
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.setAccessibleName("Client editor sections")
        root.addWidget(tabs, 1)

        client_tab = QWidget()
        form = QFormLayout(client_tab)
        form.setContentsMargins(16, 16, 16, 16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_edit = self._line_edit("Client name", values[1], required=True)
        self.tax_edit = self._line_edit("Tax ID (CIF/NIF)", values[2])
        self.address_edit = self._line_edit("Address", values[3])
        self.contact_edit = self._line_edit("Contact person", values[4])
        self.email_edit = self._line_edit("Email address", values[5])
        form.addRow("Name *", self.name_edit)
        form.addRow("Tax ID", self.tax_edit)
        form.addRow("Address", self.address_edit)
        form.addRow("Contact person", self.contact_edit)
        form.addRow("Email", self.email_edit)
        tabs.addTab(client_tab, "Client details")

        account_tab = QWidget()
        account_form = QFormLayout(account_tab)
        account_form.setContentsMargins(16, 16, 16, 16)
        account_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.status_combo = QComboBox()
        self.status_combo.setAccessibleName("Account status")
        for value, text in ACCOUNT_STATUSES.items():
            self.status_combo.addItem(text, value)
        self.owner_combo = QComboBox()
        self.owner_combo.setAccessibleName("Owner")
        self.owner_combo.addItem("Unassigned", None)
        for value, text in people or []:
            self.owner_combo.addItem(text, value)
        self.industry_edit = self._line_edit("Industry", None)
        self.website_edit = self._line_edit("Website", None)
        self.website_edit.setPlaceholderText("https://example.com")
        self.domain_edit = self._line_edit("Domain", None)
        self.domain_edit.setPlaceholderText("example.com (taken from the website when empty)")
        self.employees_combo = QComboBox()
        self.employees_combo.setAccessibleName("Employees")
        self.employees_combo.addItem("—", None)
        for value in EMPLOYEE_RANGES:
            self.employees_combo.addItem(value, value)
        self.country_edit = self._line_edit("Country", None)
        self.city_edit = self._line_edit("City", None)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setAccessibleName("Notes")
        self.notes_edit.setTabChangesFocus(True)
        self.notes_edit.setMaximumHeight(110)
        account_form.addRow("Status", self.status_combo)
        account_form.addRow("Owner", self.owner_combo)
        account_form.addRow("Industry", self.industry_edit)
        account_form.addRow("Website", self.website_edit)
        account_form.addRow("Domain", self.domain_edit)
        account_form.addRow("Employees", self.employees_combo)
        account_form.addRow("Country", self.country_edit)
        account_form.addRow("City", self.city_edit)
        account_form.addRow("Notes", self.notes_edit)
        tabs.addTab(account_tab, "Account")
        self._set_account(self._account_initial)

        if lead:
            # Shown for reference. Stage changes follow the lead workflow (allowed moves,
            # reasons, history) from the Leads page or the client profile.
            lead_tab = QWidget()
            lead_form = QFormLayout(lead_tab)
            lead_form.setContentsMargins(16, 16, 16, 16)
            for caption, value in (
                ("Source", _source_label(lead.get("source"))),
                ("Stage", _STATUS_LABELS.get(str(lead.get("status") or "new").lower(), "—")),
                ("Created", str(lead.get("created_at") or "")[:10] or "—"),
                ("Meeting", str(lead.get("meeting_date") or "")[:10] or "—"),
            ):
                field = QLineEdit(value)
                field.setReadOnly(True)
                field.setAccessibleName(f"Linked lead {caption.lower()}")
                lead_form.addRow(caption, field)
            help_text = QLabel("To change the stage or meeting date, open the lead from the client profile "
                               "or the Leads page.")
            help_text.setWordWrap(True)
            help_text.setObjectName("helpText")
            lead_form.addRow(help_text)
            tabs.addTab(lead_tab, "Linked lead")

        self.error_label = QLabel("")
        self.error_label.setObjectName("formError")
        self.error_label.setWordWrap(True)
        self.error_label.setAccessibleName("Form validation error")
        self.error_label.hide()
        root.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._validate_required)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    @staticmethod
    def _line_edit(name: str, value: Any, *, required: bool = False) -> QLineEdit:
        field = QLineEdit("" if value in (None, "-") else str(value))
        field.setAccessibleName(name)
        field.setProperty("required", required)
        field.setClearButtonEnabled(True)
        return field

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setAccessibleDescription(message)
        self.error_label.show()

    def _validate_required(self) -> None:
        if len(self.name_edit.text().strip()) < 2:
            self._show_error("The name must have at least 2 characters.")
            self.name_edit.setFocus()
            return
        if self._on_submit is not None:
            save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
            save_button.setEnabled(False)  # no duplicate submissions while saving
            try:
                success, message = self._on_submit(self)
            finally:
                save_button.setEnabled(True)
            if not success:
                self._show_error(message)
                return
            self.result_message = message
        self.accept()

    def client_values(self) -> tuple[str, str, str, str, str]:
        return (
            self.name_edit.text().strip(),
            self.tax_edit.text().strip(),
            self.address_edit.text().strip(),
            self.contact_edit.text().strip(),
            self.email_edit.text().strip(),
        )

    def _set_account(self, values: dict[str, Any]) -> None:
        self.status_combo.setCurrentIndex(max(self.status_combo.findData(values.get("account_status") or "prospect"), 0))
        self.owner_combo.setCurrentIndex(max(self.owner_combo.findData(values.get("owner_id")), 0))
        self.employees_combo.setCurrentIndex(max(self.employees_combo.findData(values.get("employee_range")), 0))
        for edit, key in ((self.industry_edit, "industry"), (self.website_edit, "website_url"),
                          (self.domain_edit, "primary_domain"), (self.country_edit, "country"),
                          (self.city_edit, "city")):
            edit.setText(values.get(key) or "")
        self.notes_edit.setPlainText(values.get("notes") or "")

    def account_values(self) -> dict[str, Any]:
        def text(edit: QLineEdit) -> str | None:
            return edit.text().strip() or None

        return {
            "account_status": self.status_combo.currentData(),
            "owner_id": self.owner_combo.currentData(),
            "industry": text(self.industry_edit),
            "website_url": text(self.website_edit),
            "primary_domain": text(self.domain_edit),
            "employee_range": self.employees_combo.currentData(),
            "country": text(self.country_edit),
            "city": text(self.city_edit),
            "notes": self.notes_edit.toPlainText().strip() or None,
        }

    def changed_account_values(self) -> dict[str, Any]:
        """Only the account fields the user changed (so unchanged owners need no permission)."""
        return {key: value for key, value in self.account_values().items()
                if value != (self._account_initial.get(key) or (None if key != "account_status" else "prospect"))}


def client_profile_snapshot(db: Any, actor: Any, client_id: str) -> dict[str, Any]:
    """Account fields, people, leads, activity, and tasks of one client, with the allowed actions."""
    zone = actor.timezone
    record = db.get(Client, client_id)
    snapshot: dict[str, Any] = {"exists": record is not None, "account": {}, "contacts": [], "leads": [],
                                "activity": [], "tasks": [], "allowed": set()}
    if record is not None:
        snapshot["account"] = {key: getattr(record, key) for key in _ACCOUNT_FIELDS}
        snapshot["owner_name"] = person(record.owner)
        snapshot["version"] = record.version
        sensitive = actor.can("clients.view_sensitive")
        snapshot["contacts"] = [
            {"id": contact.id, "full_name": contact.full_name, "first_name": contact.first_name,
             "last_name": contact.last_name, "job_title": contact.job_title,
             "email": contact.email if sensitive else None, "phone": contact.phone if sensitive else None,
             "do_not_contact": contact.do_not_contact, "suppression_reason": contact.suppression_reason,
             "notes": contact.notes, "version": contact.version}
            for contact in contact_service.list_for_client(db, actor, client_id)
        ]
        snapshot["activity"] = activity_rows(db, actor, timezone=zone, client_id=client_id)
        if actor.can_on("clients.edit", record):
            snapshot["allowed"].add("edit")
        if actor.can("activities.create"):
            snapshot["allowed"].add("activity")
    if actor.can("leads.view"):
        found = lead_service.for_client(db, actor, client_id)
        snapshot["leads"] = [{"id": lead.id, "title": lead_service.display_title(lead),
                              "stage": _STATUS_LABELS.get(lead.status, lead.status), "owner": person(lead.owner),
                              "date": lead.created_on} for lead in found]
        if actor.can("leads.create"):
            snapshot["allowed"].add("lead")
    if actor.can("tasks.view") and record is not None:
        view = "team" if actor.scope("tasks.view") is Scope.ALL else "mine"
        page = task_service.list_tasks(db, actor, page=PageRequest(page_size=100), view=view, due="all",
                                       client_id=client_id)
        snapshot["tasks"] = [[task.title, local_time(task.due_at, zone), TASK_STATUSES.get(task.status, task.status),
                              person(task.assigned_to)] for task in page.items]
        if actor.can("tasks.create"):
            snapshot["allowed"].add("task")
    return snapshot


class ClientDetailDialog(ModalDialog):
    """Accessible client profile: account, purchase history, and (when signed in) people,
    leads, activity, and tasks, with the actions the user's role allows."""

    export_requested = Signal(str)

    def __init__(
        self,
        client: dict[str, Any],
        stats: dict[str, Any],
        lead: dict[str, Any] | None = None,
        parent: QWidget | None = None,
        *,
        context: AppContext | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.stats = stats
        self.lead = lead
        self.context = context
        self.changed = False
        self._snapshot: dict[str, Any] = {}
        self.setWindowTitle(f"Client profile — {client.get('name', '')}")
        self.setModal(True)
        self.resize(900, 680)
        self.setMinimumSize(560, 460)
        self.setAccessibleName(f"Client profile for {client.get('name', '')}")

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel(_display(client.get("name")))
        title.setObjectName("dialogTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(title, 1)
        export_button = QPushButton("Export HTML")
        export_button.setObjectName("primaryButton")
        export_button.setAccessibleName(f"Export report for {client.get('name', 'client')}")
        # A bound method, not a lambda capturing self: PySide keeps lambdas
        # alive, which kept every profile dialog alive and, after exec(),
        # owned by both Python and its parent page.
        export_button.clicked.connect(self._request_export)
        header.addWidget(export_button)
        root.addLayout(header)

        metrics = QHBoxLayout()
        for label, value in (
            ("Total spent", f"€{float(stats.get('total_amount', 0)):,.2f}"),
            ("Transactions", str(int(stats.get("total_sales", 0)))),
            ("Average sale", f"€{float(stats.get('avg_amount', 0)):,.2f}"),
        ):
            card = KpiCard(label, compact=True)
            card.set_value(value)
            metrics.addWidget(card)
        root.addLayout(metrics)

        tabs = QTabWidget()
        tabs.setAccessibleName("Client profile sections")
        self.tabs = tabs
        root.addWidget(tabs, 1)

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        self.reveal_box = QCheckBox("Reveal sensitive details")
        self.reveal_box.setAccessibleDescription("Reveals tax ID and email while this dialog is open")
        overview_layout.addWidget(self.reveal_box)
        info_form = QFormLayout()
        self._tax_value = QLabel()
        self._email_value = QLabel()
        self._tax_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._email_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._tax_value.setAccessibleName("Client tax ID")
        self._email_value.setAccessibleName("Client email")
        info_form.addRow("Tax ID", self._tax_value)
        info_form.addRow("Email", self._email_value)
        info_form.addRow("Contact", self._selectable_label(client.get("contact_person")))
        info_form.addRow("Address", self._selectable_label(client.get("address")))
        info_form.addRow("Client ID", self._selectable_label(client.get("client_id")))
        self._account_form = info_form
        overview_layout.addLayout(info_form)

        lead_group = QGroupBox("Marketing / lead")
        lead_form = QFormLayout(lead_group)
        if lead:
            lead_form.addRow("Source", QLabel(_source_label(lead.get("source"))))
            lead_form.addRow("Stage", QLabel(_STATUS_LABELS.get(str(lead.get("status")), str(lead.get("status") or "—"))))
            lead_form.addRow("Lead created", QLabel(str(lead.get("created_at") or "")[:10] or "—"))
            lead_form.addRow("Meeting", QLabel(str(lead.get("meeting_date") or "")[:10] or "—"))
        else:
            lead_form.addRow(QLabel("No linked lead."))
        overview_layout.addWidget(lead_group)
        overview_layout.addStretch(1)
        overview_scroll = QScrollArea()  # account rows added below need room on small screens
        overview_scroll.setWidgetResizable(True)
        overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        overview_scroll.setWidget(overview)
        tabs.addTab(overview_scroll, "Overview")

        history = QTableWidget(0, 3)
        history.setHorizontalHeaderLabels(["Date", "Product", "Amount"])
        history.setAccessibleName("Client purchase history")
        prepare_table(history, numeric_columns=(2,), empty_text="No sales recorded for this client yet.")
        history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        sales = list(stats.get("sales") or [])
        history.setRowCount(len(sales))
        for row, sale in enumerate(sales):
            history.setItem(row, 0, _item(date_text(sale.get("date")), sort_key=str(sale.get("date") or "")[:10]))
            history.setItem(row, 1, _item(sale.get("product_type")))
            history.setItem(
                row,
                2,
                _item(f"€{float(sale.get('price') or 0):,.2f}", numeric=float(sale.get("price") or 0)),
            )
        history.setSortingEnabled(True)
        history.sortItems(0, Qt.SortOrder.DescendingOrder)  # newest first
        tabs.addTab(history, f"Purchase history ({len(sales)})")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.reveal_box.toggled.connect(self._update_sensitive_values)
        self._update_sensitive_values(False)
        if context is not None and context.is_signed_in:
            self.reveal_box.setVisible(context.can("clients.view_sensitive"))
            self._build_work_tabs()
            self.reload()

    # ------------------------------------------------------------ people, leads, activity, tasks

    def _tab(self, columns: tuple[str, ...] | list[str], actions: list[tuple[str, Callable[[], object]]],
             *, empty: str, badges: tuple[int, ...] = ()) -> tuple[QWidget, QTableWidget, dict[str, QPushButton]]:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        row = QHBoxLayout()
        buttons: dict[str, QPushButton] = {}
        for text, handler in actions:
            button = QPushButton(text)
            button.setObjectName("compactButton")
            button.clicked.connect(handler)  # bound methods only (DEF-026)
            row.addWidget(button)
            buttons[text] = button
        row.addStretch(1)
        layout.addLayout(row)
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(list(columns))
        set_table_defaults(table, badge_columns=badges, empty_text=empty)
        layout.addWidget(table, 1)
        return holder, table, buttons

    def _build_work_tabs(self) -> None:
        self.contacts_tab, self.contacts_table, self.contact_buttons = self._tab(
            ("Name", "Job title", "Email", "Phone", "Do not contact"),
            [("Add contact", self.add_contact), ("Edit", self.edit_contact), ("Remove", self.remove_contact)],
            empty="No other people recorded for this client. Use Add contact.")
        self.contacts_table.itemActivated.connect(self.edit_contact)
        self.leads_tab, self.leads_table, self.lead_buttons = self._tab(
            ("Lead", "Stage", "Owner", "Date"), [("Open lead", self.open_selected_lead), ("Add lead", self.add_lead)],
            empty="No leads for this client.", badges=(1,))
        self.leads_table.itemActivated.connect(self.open_selected_lead)
        self.activity_tab, self.activity_table, self.activity_buttons = self._tab(
            ACTIVITY_COLUMNS, [("Log activity", self.log_activity)],
            empty="No calls, emails, or meetings logged yet.")
        self.tasks_tab, self.tasks_table, self.task_buttons = self._tab(
            ("Task", "Due", "Status", "Assigned to"), [("Add task", self.add_task)],
            empty="No tasks for this client.", badges=(2,))
        for widget, name in ((self.contacts_tab, "Contacts"), (self.leads_tab, "Leads"),
                             (self.activity_tab, "Activity"), (self.tasks_tab, "Tasks")):
            self.tabs.addTab(widget, name)

    def reload(self) -> None:
        if self.context is None:
            return
        client_id = str(self.client.get("client_id"))
        try:
            self._snapshot = self.context.run(lambda db, actor: client_profile_snapshot(db, actor, client_id))
        except Exception as exc:
            report(self, exc, title="Client")
            return
        snapshot = self._snapshot
        allowed = snapshot["allowed"]
        account = snapshot["account"]
        if account and not getattr(self, "_account_rows", None):
            self._account_rows = True
            for caption, value in (
                ("Owner", snapshot.get("owner_name", "Unassigned")),
                ("Status", ACCOUNT_STATUSES.get(account.get("account_status") or "", "—")),
                ("Industry", _display(account.get("industry"))),
                ("Website", _display(account.get("website_url") or account.get("primary_domain"))),
                ("Location", _display(", ".join(part for part in (account.get("city"), account.get("country")) if part))),
                ("Notes", _display(account.get("notes"))),
            ):
                self._account_form.addRow(caption, self._selectable_label(value))
        self._fill(self.contacts_table, [[c["full_name"], _display(c["job_title"]), _display(c["email"]),
                                          _display(c["phone"]),
                                          (c["suppression_reason"] or "Yes") if c["do_not_contact"] else ""]
                                         for c in snapshot["contacts"]])
        self._fill(self.leads_table, [[lead["title"], lead["stage"], lead["owner"], date_text(lead["date"])]
                                      for lead in snapshot["leads"]])
        self._fill(self.activity_table, snapshot["activity"])
        self._fill(self.tasks_table, snapshot["tasks"])
        for widget, name, rows in ((self.contacts_tab, "Contacts", snapshot["contacts"]),
                                   (self.leads_tab, "Leads", snapshot["leads"]),
                                   (self.activity_tab, "Activity", snapshot["activity"]),
                                   (self.tasks_tab, "Tasks", snapshot["tasks"])):
            self.tabs.setTabText(self.tabs.indexOf(widget), f"{name} ({len(rows)})")
        for button in self.contact_buttons.values():
            button.setEnabled("edit" in allowed)
        self.lead_buttons["Add lead"].setEnabled("lead" in allowed)
        self.lead_buttons["Open lead"].setEnabled(bool(snapshot["leads"]))
        self.activity_buttons["Log activity"].setEnabled("activity" in allowed)
        self.task_buttons["Add task"].setEnabled("task" in allowed)

    @staticmethod
    def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                text = str(value) if value not in (None, "") else ""
                item = QTableWidgetItem(text)
                if text:
                    item.setToolTip(text)
                table.setItem(row, column, item)
        fit_columns(table)

    def _saved(self, saved: object) -> None:
        if saved:
            self.changed = True
            self.reload()

    def _selected_contact(self) -> dict[str, Any] | None:
        row = self.contacts_table.currentRow()
        contacts = self._snapshot.get("contacts", [])
        return contacts[row] if 0 <= row < len(contacts) else None

    def add_contact(self, *_args: Any) -> None:
        if self.context is not None:
            self._saved(contact_form(self, self.context, client_id=str(self.client.get("client_id"))))

    def edit_contact(self, *_args: Any) -> None:
        contact = self._selected_contact()
        if contact is not None and self.context is not None and "edit" in self._snapshot.get("allowed", set()):
            self._saved(contact_form(self, self.context, client_id=str(self.client.get("client_id")),
                                     contact=contact))

    def remove_contact(self, *_args: Any) -> None:
        contact = self._selected_contact()
        if contact is not None and self.context is not None:
            self._saved(delete_contact(self, self.context, contact["id"], contact["full_name"]))

    def open_selected_lead(self, *_args: Any) -> None:
        row = self.leads_table.currentRow()
        leads = self._snapshot.get("leads", [])
        if self.context is not None and 0 <= row < len(leads):
            self._saved(open_lead(self, self.context, leads[row]["id"]))

    def add_lead(self, *_args: Any) -> None:
        if self.context is not None:
            from ..workflows import lead_form

            self._saved(lead_form(self, self.context, client_id=str(self.client.get("client_id"))))

    def log_activity(self, *_args: Any) -> None:
        if self.context is not None:
            self._saved(log_activity(self, self.context, heading=f"Log activity for {self.client.get('name')}",
                                     client_id=str(self.client.get("client_id"))))

    def add_task(self, *_args: Any) -> None:
        if self.context is not None:
            from .tasks_page import create_task

            self._saved(create_task(self, self.context, client_id=str(self.client.get("client_id")),
                                    title=f"Follow up with {self.client.get('name')}"))

    def _request_export(self) -> None:
        self.export_requested.emit(str(self.client.get("client_id")))

    @staticmethod
    def _selectable_label(value: Any) -> QLabel:
        label = QLabel(_display(value))
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _update_sensitive_values(self, reveal: bool) -> None:
        tax = self.client.get("cif")
        email = self.client.get("email")
        self._tax_value.setText(_display(tax) if reveal else _mask_sensitive(tax))
        self._email_value.setText(_display(email) if reveal else _mask_sensitive(email))
        state = "revealed" if reveal else "masked"
        self._tax_value.setAccessibleDescription(f"Sensitive value is {state}")
        self._email_value.setAccessibleDescription(f"Sensitive value is {state}")


class ClientsPage(QWidget):
    """Searchable client list with CRUD, profile, merge, and export flows."""

    notification_requested = Signal(str, str)
    data_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        controller: type[ClientsController] = ClientsController,
        leads_controller: type[LeadsController] = LeadsController,
        latest_leads_provider: Callable[[], dict[str, dict[str, Any]]] = get_latest_lead_per_client,
        report_generator=generate_client_html_report,
        context: AppContext | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self._extras: dict[str, client_service.ClientExtras] = {}
        self._controller = controller
        self._leads_controller = leads_controller
        self._latest_leads_provider = latest_leads_provider
        self._report_generator = report_generator
        self._clients: list[dict[str, Any]] = []
        self._filtered_clients: list[dict[str, Any]] = []
        self._lead_map: dict[str, dict[str, Any]] = {}
        self._layout_columns: int | None = None

        self.setObjectName("clientsPage")
        self.setAccessibleName("Client management workspace")
        self._build_ui()
        self._reflow_toolbar()
        self._install_shortcuts()
        self.refresh()

    @property
    def visible_clients(self) -> list[dict[str, Any]]:
        return list(self._filtered_clients)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("pageScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAccessibleName("Scrollable client content")
        outer.addWidget(scroll)

        self._body = QWidget()
        self._body.setObjectName("pageBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(28, 24, 28, 40)
        self._layout.setSpacing(20)
        scroll.setWidget(self._body)

        self._layout.addWidget(PageHeader("Client management",
                                          "Maintain client records and inspect sales and lead history."))

        toolbar_box = SectionCard("Client tools", divider=False)
        toolbar_box.header_layout.setContentsMargins(20, 18, 20, 0)
        toolbar_box.body.setContentsMargins(19, 12, 19, 18)
        self._toolbar_grid = QGridLayout()
        self._toolbar_grid.setContentsMargins(0, 0, 0, 0)
        self._toolbar_grid.setSpacing(12)
        toolbar_box.body.addLayout(self._toolbar_grid)
        self.add_button = QPushButton("Add client")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setAccessibleName("Add a new client")
        set_button_icon(self.add_button, "plus", "onPrimary")
        self.add_button.clicked.connect(self.add_client)
        self.merge_button = QPushButton("Merge duplicates")
        self.merge_button.setObjectName("secondaryButton")
        self.merge_button.setToolTip("Review and merge client IDs that share the same name")
        self.merge_button.setAccessibleName("Merge duplicate clients")
        set_button_icon(self.merge_button, "merge")
        self.merge_button.clicked.connect(self.merge_duplicates)
        self.search_edit = SearchField("Search clients by name")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("Search clients by name")
        self.search_edit.textChanged.connect(self.apply_search)
        self._toolbar_widgets: tuple[QWidget, ...] = (self.add_button, self.merge_button, self.search_edit)
        self._layout.addWidget(toolbar_box)

        metrics_layout = QGridLayout()
        metrics_layout.setSpacing(16)
        self.total_card = KpiCard("Clients", icon="people")
        self.buyers_card = KpiCard("Clients with sales", accent="gold", icon="receipt")
        self.revenue_card = KpiCard("Lifetime revenue", icon="sales")
        metrics_layout.addWidget(self.total_card, 0, 0)
        metrics_layout.addWidget(self.buyers_card, 0, 1)
        metrics_layout.addWidget(self.revenue_card, 0, 2)
        for column in range(3):
            metrics_layout.setColumnStretch(column, 1)
        self._layout.addLayout(metrics_layout)

        table_box = SectionCard("Clients", "", padded=False)
        self.result_label = table_box.subtitle_label
        self.result_label.setAccessibleName("Client search results")
        self.result_label.show()
        self.clients_table = QTableWidget(0, 12)
        self.clients_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Tax ID", "Email", "Sales", "Total", "Lead source", "Stage", "Lead date", "Owner",
             "Status", "Actions"]
        )
        self.clients_table.setAccessibleName("Client list")
        prepare_table(self.clients_table, numeric_columns=(4, 5), badge_columns=(7, 10),
                      avatar_columns=(1, 9), mono_columns=(0,), strong_columns=(1, 5), large_avatar_columns=(1,),
                      empty_text="No clients match this search. Clear the search, or add a client.")
        clients_empty = EmptyState("No clients match this search", "Clear the search, or add a client.",
                                   icon="clients")
        self.empty_add_client = clients_empty.add_action("Add client", self.add_client, primary=True, icon="plus")
        set_empty_state(self.clients_table, clients_empty,
                        "No clients match this search. Clear the search, or add a client.")
        set_header_tips(self.clients_table, {
            4: "Number of sales recorded for the client",
            5: "Lifetime sales amount",
            6: "Source of the client's latest lead",
            7: "Stage of the client's latest lead",
            8: "Date of the client's latest lead",
            10: "Account status",
        })
        # Tax ID and email are masked in this list for every role (the profile shows them),
        # so they start hidden to leave room; right-click the header to show them.
        enable_column_choice(self.clients_table, "clients", locked=(1, _ACTIONS_COLUMN),
                             hidden_by_default=(2, 3))
        self.clients_table.setSortingEnabled(True)
        self.clients_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.clients_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Explicit default: enabling sorting otherwise re-sorts by ID, descending.
        self.clients_table.sortItems(1, Qt.SortOrder.AscendingOrder)
        # Enter or double-click opens the profile. Row buttons are painted by a
        # delegate (no widget per row); the context menu and Delete key give
        # keyboard users the same actions.
        self.clients_table.activated.connect(self._client_activated)
        self._client_row_actions = (
            RowAction("view", "View", "View client profile", icon="eye"),
            RowAction("edit", "Edit", "Edit client details", icon="edit"),
            RowAction("more", "More", "More actions", icon="more"),
        )
        self._client_menu_actions = (
            RowAction("view", "View", "View client profile"),
            RowAction("edit", "Edit", "Edit client details"),
            RowAction("delete", "Delete", "Delete client and linked sales", destructive=True),
        )
        self._client_action_delegate = RowActionDelegate(
            self._client_row_actions, id_role=_CLIENT_ID_ROLE, view=self.clients_table
        )
        self._client_action_delegate.triggered.connect(self._run_client_action)
        self.clients_table.setItemDelegateForColumn(_ACTIONS_COLUMN, self._client_action_delegate)
        install_row_action_menu(
            self.clients_table,
            self._client_menu_actions,
            lambda index: str(index.data(_CLIENT_ID_ROLE) or ""),
            self._run_client_action,
        )
        delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.clients_table)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_current_client)
        self._table_shortcuts = [delete_shortcut]
        table_box.body.addWidget(self.clients_table)
        footer = QFrame()
        footer.setObjectName("cardFooter")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(20, 12, 20, 14)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("statusMessage")
        self.status_label.setAccessibleName("Client status message")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        footer_row.addWidget(self.status_label)
        table_box.body.addWidget(footer)
        self._layout.addWidget(table_box)
        self._layout.addStretch(1)

    def _install_shortcuts(self) -> None:
        self._shortcuts = [
            QShortcut(QKeySequence.StandardKey.Find, self),
            QShortcut(QKeySequence.StandardKey.New, self),
            QShortcut(QKeySequence.StandardKey.Refresh, self),
        ]
        self._shortcuts[0].activated.connect(self._focus_search)
        self._shortcuts[1].activated.connect(self.add_client)
        self._shortcuts[2].activated.connect(self.refresh)

    def _focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._reflow_toolbar()

    def _reflow_toolbar(self) -> None:
        columns = 1 if self.width() < 680 else 3
        if columns == self._layout_columns:
            return
        self._layout_columns = columns
        for widget in self._toolbar_widgets:
            self._toolbar_grid.removeWidget(widget)  # takeAt() leaked the item
        if columns == 1:
            for row, widget in enumerate(self._toolbar_widgets):
                self._toolbar_grid.addWidget(widget, row, 0)
        else:
            self._toolbar_grid.addWidget(self.add_button, 0, 0)
            self._toolbar_grid.addWidget(self.merge_button, 0, 1)
            self._toolbar_grid.addWidget(self.search_edit, 0, 2)
        # Reset all columns so stretch from the other layout cannot linger.
        for column in range(3):
            self._toolbar_grid.setColumnStretch(column, 1 if column == (2 if columns > 1 else 0) else 0)

    def update_permissions(self) -> None:
        context = self.context
        self.add_button.setVisible(context is None or context.can("clients.create"))
        self.merge_button.setVisible(context is None or context.can("clients.merge"))
        self.empty_add_client.setVisible(context is None or context.can("clients.create"))

    def _load_extras(self) -> None:
        """Owner and account status of each client, from the same client rows."""
        self._extras = {}
        if self.context is not None and self.context.is_signed_in:
            try:
                self._extras = self.context.run(lambda db, actor: client_service.extras(db, actor), busy=False)
            except Exception as exc:
                report(self, exc, title="Clients")

    def refresh(self, preserve_search: bool = True) -> None:
        if not preserve_search:
            self.search_edit.clear()
        self.update_permissions()
        try:
            self._clients = list(self._controller.get_all_clients_with_sales() or [])
            self._lead_map = dict(self._latest_leads_provider() or {})
            self._load_extras()
            self.apply_search()
            self._notify(f"Loaded {len(self._clients)} clients.", "info")
        except Exception as exc:
            logger.exception("Could not refresh PySide6 clients page")
            self._clients = []
            self._lead_map = {}
            self.apply_search()
            self._notify(f"Could not load clients: {exc}", "error")

    def apply_search(self) -> None:
        term = self.search_edit.text().strip().casefold()
        self._filtered_clients = [
            client for client in self._clients
            if not term or term in str(client.get("name") or "").casefold()
        ]
        self.result_label.setText(
            f"{len(self._filtered_clients)} result"
            f"{'s' if len(self._filtered_clients) != 1 else ''}"
            + (f' for "{self.search_edit.text().strip()}"' if term else "")
        )
        self._update_metrics()
        self._populate_table()

    def _update_metrics(self) -> None:
        total = len(self._filtered_clients)
        buyers = sum(int(client.get("total_sales", 0)) > 0 for client in self._filtered_clients)
        revenue = sum(float(client.get("total_amount", 0) or 0) for client in self._filtered_clients)
        self.total_card.set_value(str(total), "Local client profiles")
        self.buyers_card.set_value(str(buyers), "At least one sales record")
        self.revenue_card.set_value(f"€{revenue:,.2f}", "All sales across clients")

    def _populate_table(self) -> None:
        table = self.clients_table
        # With twelve columns the Name column was once squeezed to "Glo…" (OPEN-06); it keeps
        # a readable minimum while wider columns such as Email give up space first.
        with bulk_table_update(
            table,
            stretch_column=1,
            fixed_columns={_ACTIONS_COLUMN: self._client_action_delegate.column_width()},
            min_widths={1: 180},
        ):
            table.clearContents()
            table.setRowCount(len(self._filtered_clients))
            for row, client in enumerate(self._filtered_clients):
                client_id = str(client.get("client_id") or "")
                lead = self._lead_map.get(client_id)
                cells = (
                    _item(client_id),
                    _item(client.get("name")),
                    _item(_mask_sensitive(client.get("cif"))),
                    _item(_mask_sensitive(client.get("email"))),
                    _item(int(client.get("total_sales", 0)), numeric=int(client.get("total_sales", 0))),
                    _item(f"€{float(client.get('total_amount', 0) or 0):,.2f}", numeric=float(client.get("total_amount", 0) or 0)),
                    _item(_source_label(lead.get("source")) if lead else "—"),
                    _item(_STATUS_LABELS.get(str(lead.get("status")), str(lead.get("status") or "—")) if lead else "—"),
                    _item(date_text(lead.get("created_at")) if lead else "—",
                          sort_key=str(lead.get("created_at") or "")[:10] if lead else ""),
                    _item(self._extras[client_id].owner_name or "Unassigned" if client_id in self._extras else "—"),
                    _item(ACCOUNT_STATUSES.get(self._extras[client_id].account_status or "", "—")
                          if client_id in self._extras else "—"),
                )
                cells[0].setFont(mono_font(12))  # the delegate paints IDs in the monospace font
                cells[0].setForeground(QColor(tokens()["text2"]))
                for column, item in enumerate(cells):
                    item.setData(_CLIENT_ID_ROLE, client_id)
                    table.setItem(row, column, item)
                action_item = QTableWidgetItem()
                action_item.setFlags(action_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                action_item.setData(_CLIENT_ID_ROLE, client_id)
                action_item.setData(
                    Qt.ItemDataRole.AccessibleTextRole,
                    f"Actions for {client.get('name') or client_id}: view, edit, delete",
                )
                table.setItem(row, _ACTIONS_COLUMN, action_item)
        fit_table_height(table, max_rows=14)

    def _client_activated(self, index) -> None:
        client_id = str(index.data(_CLIENT_ID_ROLE) or "")
        if client_id:
            self.show_client_profile(client_id)

    def _run_client_action(self, key: str, client_id: str) -> None:
        if not client_id:
            return
        if key == "more":  # the ⋯ button: the same actions as the context menu
            menu = QMenu(self.clients_table)
            for action in self._client_menu_actions:
                entry = menu.addAction(action.label, partial(self._run_client_action, action.key, client_id))
                if action.destructive:
                    entry.setIcon(icon("trash", tokens()["danger"], 16))
            menu.exec(QCursor.pos())
            menu.deleteLater()
            return
        {
            "view": self.show_client_profile,
            "edit": self.edit_client,
            "delete": self.delete_client,
        }[key](client_id)

    def _delete_current_client(self) -> None:
        index = self.clients_table.currentIndex()
        if index.isValid():
            self._run_client_action("delete", str(index.data(_CLIENT_ID_ROLE) or ""))

    def _require_session(self) -> AppContext | None:
        if self.context is None or not self.context.is_signed_in:
            self._notify("Sign in to change clients.", "warning")
            return None
        return self.context

    def _people(self) -> list[tuple[str, str]]:
        if self.context is None:
            return []
        return user_options(self.context, self, permission="clients.assign") or []

    def add_client(self) -> bool:
        context = self._require_session()
        if context is None:
            return False

        def submit(form: ClientFormDialog) -> tuple[bool, str]:
            values = dict(zip(("name", "cif", "address", "contact_person", "email"), form.client_values(),
                              strict=True))
            values.update(form.account_values())
            try:
                data = parse(ClientCreate, {key: value for key, value in values.items() if value not in (None, "")})
                context.write("client", lambda db, actor: client_service.create_client(db, actor, data))
            except Exception as exc:
                return False, _problem(exc)
            return True, f"✔ {values['name']} added."

        dialog = ClientFormDialog(parent=self, on_submit=submit, people=self._people(),
                                  account={"owner_id": context.actor.user_id if context.actor else None})
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._notify(dialog.result_message, "success")
        self.refresh()
        self.data_changed.emit()
        return True

    def edit_client(self, client_id: str) -> bool:
        client = self._controller.find_client(client_id)
        if not client:
            self._notify("Client not found. Refresh the page and try again.", "error")
            return False
        context = self._require_session()
        if context is None:
            return False
        extra = self._extras.get(str(client_id))
        if extra is not None and not extra.editable:
            self._notify("Your role cannot edit this client.", "warning")
            return False
        lead = self._lead_map.get(str(client_id))
        if lead is None:
            try:
                lead_rows = get_leads(client_id=client_id)
                lead = lead_rows[0] if lead_rows else None
            except Exception:
                logger.exception("Could not load linked lead for client %s", client_id)
        try:
            snapshot = context.run(lambda db, actor: client_profile_snapshot(db, actor, str(client_id)))
        except Exception as exc:
            report(self, exc, title="Clients")
            return False
        initial = dict(zip(("name", "cif", "address", "contact_person", "email"),
                           (_blank(value) for value in client[1:6]), strict=True))

        def submit(form: ClientFormDialog) -> tuple[bool, str]:
            values = dict(zip(("name", "cif", "address", "contact_person", "email"), form.client_values(),
                              strict=True))
            changes = {key: value or None for key, value in values.items() if (value or None) != initial[key]}
            changes.update(form.changed_account_values())
            if not changes:
                return True, "No changes to save."
            try:
                data = parse(ClientUpdate, {**changes, "version": snapshot.get("version")})
                context.write("client", lambda db, actor: client_service.update_client(db, actor, client_id, data))
            except Exception as exc:
                return False, _problem(exc)
            return True, "✔ Client updated."

        dialog = ClientFormDialog(client=client, lead=lead, parent=self, on_submit=submit, people=self._people(),
                                  account=snapshot.get("account") or {})
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._notify(dialog.result_message, "success")
        self.refresh()
        self.data_changed.emit()
        return True

    def delete_client(self, client_id: str) -> bool:
        client = self._controller.find_client(client_id)
        if not client:
            self._notify("Client not found. Refresh the page and try again.", "error")
            return False
        name = _display(client[1])
        context = self._require_session()
        if context is None:
            return False
        extra = self._extras.get(str(client_id))
        if extra is not None and not extra.deletable:
            self._notify("Your role cannot delete clients.", "warning")
            return False
        if not ask_confirmation(
            self,
            title="Delete client",
            heading=f"Delete {name}?",
            message=(
                "The client, all of their sales, their contacts, tasks, and activity are removed. Their "
                "leads are kept but no longer linked to a client. This cannot be undone."
            ),
            confirm_text="Delete client",
            destructive=True,
        ):
            return False
        try:
            context.write("client", lambda db, actor: client_service.delete_client(db, actor, client_id))
        except Exception as exc:
            report(self, exc, title="Delete client")
            return False
        self._notify(f"✔ {name} was deleted.", "success")
        self.refresh()
        self.data_changed.emit()
        return True

    def merge_duplicates(self) -> bool:
        count, summary = self._controller.get_duplicates_info()
        if not count:
            self._notify("No clients share the same name.", "info")
            return False
        if not ask_confirmation(
            self,
            title="Merge duplicate clients",
            heading="Merge duplicate clients?",
            message=(
                f"{summary}\n\nFor each name, one client ID is kept and the contact details are "
                "combined. Sales, leads, and funnel events move to that ID, and the other IDs are "
                "deleted. This cannot be undone."
            ),
            confirm_text="Merge clients",
            level="warning",
        ):
            return False
        if self.context is None:
            success, message = self._controller.merge_duplicate_clients()
        else:
            try:
                success, message = self.context.guarded(
                    "clients.merge", "client.duplicates_merged", self._controller.merge_duplicate_clients,
                    kind="client", entity_type="client",
                    changes=lambda outcome: {"result": outcome[1], "groups": count} if outcome[0] else None,
                )
            except Exception as exc:
                report(self, exc, title="Merge duplicates")
                return False
        self._notify(message, "success" if success else "error")
        if success:
            self.refresh()
            self.data_changed.emit()
        return bool(success)

    def _client_snapshot(self, client_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        client = self._controller.find_client(client_id)
        if not client:
            return None
        cid, name, cif, address, contact, email = client
        client_dict = {
            "client_id": cid,
            "name": name,
            "cif": cif,
            "address": address,
            "contact_person": contact,
            "email": email,
        }
        return client_dict, self._controller.get_client_sales_stats(client_id)

    def show_client_profile(self, client_id: str) -> bool:
        snapshot = self._client_snapshot(client_id)
        if not snapshot:
            self._notify("Client not found. Refresh the page and try again.", "error")
            return False
        client, stats = snapshot
        dialog = ClientDetailDialog(client, stats, self._lead_map.get(str(client_id)), self, context=self.context)
        dialog.export_requested.connect(lambda cid: self.export_client_report(cid))
        dialog.exec()
        if dialog.changed:
            self.refresh()
            self.data_changed.emit()
        return True

    def export_client_report(
        self,
        client_id: str,
        filename: str | os.PathLike[str] | None = None,
    ) -> str | None:
        snapshot = self._client_snapshot(client_id)
        if not snapshot:
            self._notify("Client not found. Refresh the page and try again.", "error")
            return None
        client, stats = snapshot
        if filename is None:
            safe_name = "".join(
                character for character in str(client.get("name") or "Client")
                if character.isalnum() or character in (" ", "-", "_")
            ).strip()
            selected, _filter = QFileDialog.getSaveFileName(
                self,
                "Export client profile",
                f"Client_Profile_{safe_name}.html",
                "HTML files (*.html)",
            )
            if not selected:
                return None
            filename = selected
        path = str(Path(filename).expanduser())
        if not path.lower().endswith(".html"):
            path += ".html"
        if self.context is not None:
            try:
                self.context.run(lambda db, actor: actor.require("data.export"))
            except Exception as exc:
                report(self, exc, title="Export")
                return None
        success, message, generated = self._report_generator(
            client_info=client,
            stats=stats,
            filename=path,
        )
        self._notify(message, "success" if success else "error")
        if success and self.context is not None:
            self.context.record("data.exported", entity_type="client", entity_id=client_id,
                                changes={"report": "client profile"})
        return str(generated) if success and generated else None

    def _notify(self, message: str, level: str) -> None:
        """Show inline feedback; the hosting shell decides whether to pop up errors."""
        self.status_label.setText(message)
        self.status_label.setProperty("level", level)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.notification_requested.emit(message, level)


__all__ = ["ClientDetailDialog", "ClientFormDialog", "ClientsPage"]
