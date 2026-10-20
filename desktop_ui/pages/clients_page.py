"""Native PySide6 client management page.

CRUD, duplicate merging, lead updates, and report generation remain delegated to
the repository's established controller/model/report layers.  This module only
owns desktop interaction and presentation state.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QDate, Qt, Signal
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
from domain.source_labels import SOURCE_LABELS
from models.lead_manager import VALID_LEAD_STATUSES, get_latest_lead_per_client
from reports.report_client_html import generate_client_html_report

from ..dialogs import ask_confirmation
from ..row_actions import RowAction, RowActionDelegate, install_row_action_menu
from ..widgets import bulk_table_update, sortable_item

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    "new": "Lead",
    "contacted": "Contacted",
    "meeting": "Meeting",
    "converted": "Client",
    "lost": "Lost",
}
_CLIENT_ID_ROLE = Qt.ItemDataRole.UserRole + 1


def _source_label(value: Any) -> str:
    raw = str(value or "unknown")
    return SOURCE_LABELS.get(raw, raw.replace("_", " ").title())


def _display(value: Any) -> str:
    text = str(value or "").strip()
    return text if text and text != "-" else "—"


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


def _item(value: Any, *, numeric: float | int | None = None) -> QTableWidgetItem:
    result = sortable_item(_display(value), numeric)
    result.setFlags(result.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if numeric is not None:
        result.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return result


class _MetricCard(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.label = QLabel(label)
        self.label.setObjectName("metricLabel")
        self.value = QLabel("0")
        self.value.setObjectName("metricValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label)
        layout.addWidget(self.value)

    def set_value(self, value: str, description: str = "") -> None:
        self.value.setText(value)
        self.setAccessibleDescription(description or f"{self.label.text()}: {value}")


class ClientFormDialog(QDialog):
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
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.lead = lead
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

        self.lead_status: QComboBox | None = None
        self.has_meeting: QCheckBox | None = None
        self.meeting_date: QDateEdit | None = None
        if lead:
            lead_tab = QWidget()
            lead_form = QFormLayout(lead_tab)
            lead_form.setContentsMargins(16, 16, 16, 16)
            source = QLineEdit(_source_label(lead.get("source")))
            source.setReadOnly(True)
            source.setAccessibleName("Lead source")
            created = QLineEdit(str(lead.get("created_at") or "")[:10] or "—")
            created.setReadOnly(True)
            created.setAccessibleName("Lead created date")
            self.lead_status = QComboBox()
            self.lead_status.setAccessibleName("Linked lead stage")
            for status in sorted(VALID_LEAD_STATUSES, key=lambda item: tuple(_STATUS_LABELS).index(item)):
                self.lead_status.addItem(_STATUS_LABELS.get(status, status.title()), status)
            index = self.lead_status.findData(str(lead.get("status") or "new").lower())
            self.lead_status.setCurrentIndex(max(index, 0))
            meeting_raw = str(lead.get("meeting_date") or "")[:10]
            parsed = QDate.fromString(meeting_raw, Qt.DateFormat.ISODate)
            self.has_meeting = QCheckBox("Meeting scheduled")
            self.has_meeting.setChecked(bool(meeting_raw))
            self.meeting_date = QDateEdit(parsed if parsed.isValid() else QDate.currentDate())
            self.meeting_date.setDisplayFormat("yyyy-MM-dd")
            self.meeting_date.setCalendarPopup(True)
            self.meeting_date.setEnabled(bool(meeting_raw))
            self.meeting_date.setAccessibleName("Linked lead meeting date")
            self.has_meeting.toggled.connect(self.meeting_date.setEnabled)
            lead_form.addRow("Source", source)
            lead_form.addRow("Created", created)
            lead_form.addRow("Stage", self.lead_status)
            lead_form.addRow(self.has_meeting, self.meeting_date)
            help_text = QLabel("Saving updates both tabs. Clearing the checkbox removes the meeting date.")
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

    def linked_lead_values(self) -> tuple[str, str, str | None] | None:
        if not self.lead or not self.lead_status or not self.has_meeting or not self.meeting_date:
            return None
        meeting = (
            self.meeting_date.date().toString(Qt.DateFormat.ISODate)
            if self.has_meeting.isChecked()
            else None
        )
        return str(self.lead.get("id")), str(self.lead_status.currentData()), meeting


class ClientDetailDialog(QDialog):
    """Accessible client profile with a transaction-history tab."""

    export_requested = Signal(str)

    def __init__(
        self,
        client: dict[str, Any],
        stats: dict[str, Any],
        lead: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.stats = stats
        self.lead = lead
        self.setWindowTitle(f"Client profile — {client.get('name', '')}")
        self.setModal(True)
        self.resize(880, 620)
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
            card = _MetricCard(label)
            card.set_value(value)
            metrics.addWidget(card)
        root.addLayout(metrics)

        tabs = QTabWidget()
        tabs.setAccessibleName("Client profile sections")
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
        tabs.addTab(overview, "Overview")

        history = QTableWidget(0, 3)
        history.setHorizontalHeaderLabels(["Date", "Product", "Amount"])
        history.setAccessibleName("Client purchase history")
        history.setAlternatingRowColors(True)
        history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        history.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        history.verticalHeader().hide()
        history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        sales = list(stats.get("sales") or [])
        history.setRowCount(len(sales))
        for row, sale in enumerate(sales):
            history.setItem(row, 0, _item(str(sale.get("date") or "")[:10]))
            history.setItem(row, 1, _item(sale.get("product_type")))
            history.setItem(
                row,
                2,
                _item(f"€{float(sale.get('price') or 0):,.2f}", numeric=float(sale.get("price") or 0)),
            )
        tabs.addTab(history, f"Purchase history ({len(sales)})")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.reveal_box.toggled.connect(self._update_sensitive_values)
        self._update_sensitive_values(False)

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
    ) -> None:
        super().__init__(parent)
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
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAccessibleName("Scrollable client content")
        outer.addWidget(scroll)

        self._body = QWidget()
        self._body.setObjectName("pageBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(24, 20, 24, 32)
        self._layout.setSpacing(18)
        scroll.setWidget(self._body)

        title = QLabel("Client management")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Maintain client records and inspect sales and lead history.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        self._layout.addWidget(title)
        self._layout.addWidget(subtitle)

        toolbar_box = QGroupBox("Client tools")
        toolbar_box.setObjectName("card")
        self._toolbar_grid = QGridLayout(toolbar_box)
        self._toolbar_grid.setContentsMargins(16, 16, 16, 16)
        self._toolbar_grid.setSpacing(10)
        self.add_button = QPushButton("Add client")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setAccessibleName("Add a new client")
        self.add_button.clicked.connect(self.add_client)
        self.merge_button = QPushButton("Merge duplicates")
        self.merge_button.setObjectName("warningButton")
        self.merge_button.setToolTip("Review and merge client IDs that share the same name")
        self.merge_button.setAccessibleName("Merge duplicate clients")
        self.merge_button.clicked.connect(self.merge_duplicates)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search clients by name…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("Search clients by name")
        self.search_edit.textChanged.connect(self.apply_search)
        self._toolbar_widgets: tuple[QWidget, ...] = (self.add_button, self.merge_button, self.search_edit)
        self._layout.addWidget(toolbar_box)

        metrics_layout = QGridLayout()
        metrics_layout.setSpacing(12)
        self.total_card = _MetricCard("Clients")
        self.buyers_card = _MetricCard("Clients with sales")
        self.revenue_card = _MetricCard("Lifetime revenue")
        metrics_layout.addWidget(self.total_card, 0, 0)
        metrics_layout.addWidget(self.buyers_card, 0, 1)
        metrics_layout.addWidget(self.revenue_card, 0, 2)
        for column in range(3):
            metrics_layout.setColumnStretch(column, 1)
        self._layout.addLayout(metrics_layout)

        table_box = QGroupBox("Clients")
        table_box.setObjectName("card")
        table_layout = QVBoxLayout(table_box)
        self.result_label = QLabel("")
        self.result_label.setObjectName("filterSummary")
        self.result_label.setAccessibleName("Client search results")
        self.result_label.setTextFormat(Qt.TextFormat.PlainText)  # echoes search text
        table_layout.addWidget(self.result_label)
        self.clients_table = QTableWidget(0, 10)
        self.clients_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Tax ID", "Email", "Sales", "Total", "Lead source", "Stage", "Lead date", "Actions"]
        )
        self.clients_table.setAccessibleName("Client list")
        self.clients_table.setAlternatingRowColors(True)
        self.clients_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.clients_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.clients_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.clients_table.setSortingEnabled(True)
        self.clients_table.verticalHeader().hide()
        self.clients_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.clients_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.clients_table.setMinimumHeight(420)
        # Explicit default: enabling sorting otherwise re-sorts by ID, descending.
        self.clients_table.sortItems(1, Qt.SortOrder.AscendingOrder)
        self.clients_table.verticalHeader().setDefaultSectionSize(36)
        # Enter or double-click opens the profile. Row buttons are painted by a
        # delegate (no widget per row); the context menu and Delete key give
        # keyboard users the same actions.
        self.clients_table.activated.connect(self._client_activated)
        self._client_row_actions = (
            RowAction("view", "View", "View client profile"),
            RowAction("edit", "Edit", "Edit client details"),
            RowAction("delete", "Delete", "Delete client and linked sales", destructive=True),
        )
        self._client_action_delegate = RowActionDelegate(
            self._client_row_actions, id_role=_CLIENT_ID_ROLE, view=self.clients_table
        )
        self._client_action_delegate.triggered.connect(self._run_client_action)
        self.clients_table.setItemDelegateForColumn(9, self._client_action_delegate)
        install_row_action_menu(
            self.clients_table,
            self._client_row_actions,
            lambda index: str(index.data(_CLIENT_ID_ROLE) or ""),
            self._run_client_action,
        )
        delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.clients_table)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_current_client)
        self._table_shortcuts = [delete_shortcut]
        table_layout.addWidget(self.clients_table)
        self.empty_label = QLabel("No clients match this search.")
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setAccessibleName("No client results")
        self.empty_label.hide()
        table_layout.addWidget(self.empty_label)
        self._layout.addWidget(table_box)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("statusMessage")
        self.status_label.setAccessibleName("Client status message")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._layout.addWidget(self.status_label)

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
            self._toolbar_grid.setColumnStretch(column, 1 if column == columns - 1 else 0)

    def refresh(self, preserve_search: bool = True) -> None:
        if not preserve_search:
            self.search_edit.clear()
        try:
            self._clients = list(self._controller.get_all_clients_with_sales() or [])
            self._lead_map = dict(self._latest_leads_provider() or {})
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
        self.total_card.set_value(str(total), "Clients in the current result set")
        self.buyers_card.set_value(str(buyers), "Clients with one or more sales")
        self.revenue_card.set_value(f"€{revenue:,.2f}", "Lifetime sales for visible clients")

    def _populate_table(self) -> None:
        table = self.clients_table
        with bulk_table_update(
            table,
            stretch_column=1,
            fixed_columns={9: self._client_action_delegate.column_width()},
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
                    _item(str(lead.get("created_at") or "")[:10] if lead else "—"),
                )
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
                table.setItem(row, 9, action_item)
        table.setVisible(bool(self._filtered_clients))
        self.empty_label.setVisible(not self._filtered_clients)

    def _client_activated(self, index) -> None:
        client_id = str(index.data(_CLIENT_ID_ROLE) or "")
        if client_id:
            self.show_client_profile(client_id)

    def _run_client_action(self, key: str, client_id: str) -> None:
        if not client_id:
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

    def add_client(self) -> bool:
        def submit(form: ClientFormDialog) -> tuple[bool, str]:
            return self._controller.create_client(*form.client_values())

        dialog = ClientFormDialog(parent=self, on_submit=submit)
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
        lead = self._lead_map.get(str(client_id))
        if lead is None:
            try:
                lead_rows = get_leads(client_id=client_id)
                lead = lead_rows[0] if lead_rows else None
            except Exception:
                logger.exception("Could not load linked lead for client %s", client_id)
        notification_level = "success"

        def submit(form: ClientFormDialog) -> tuple[bool, str]:
            nonlocal notification_level
            success, message = self._controller.update_client_info(client_id, *form.client_values())
            if not success:
                return False, message
            lead_values = form.linked_lead_values()
            if lead_values:
                lead_success, lead_message = self._leads_controller.update_lead_info(*lead_values)
                if not lead_success:
                    # The client row is already committed, so close the form and
                    # report the partial result rather than inviting a re-save.
                    notification_level = "warning"
                    return True, f"Client saved, but the linked lead was not updated: {lead_message}"
                message = f"{message} Linked lead updated."
            return True, message

        dialog = ClientFormDialog(client=client, lead=lead, parent=self, on_submit=submit)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._notify(dialog.result_message, notification_level)
        self.refresh()
        self.data_changed.emit()
        return True

    def delete_client(self, client_id: str) -> bool:
        client = self._controller.find_client(client_id)
        if not client:
            self._notify("Client not found. Refresh the page and try again.", "error")
            return False
        name = _display(client[1])
        if not ask_confirmation(
            self,
            title="Delete client",
            heading=f"Delete {name}?",
            message=(
                "The client and all of their sales are removed. Their leads are kept but no "
                "longer linked to a client. This cannot be undone."
            ),
            confirm_text="Delete client",
            destructive=True,
        ):
            return False
        success, message = self._controller.remove_client(client_id)
        self._notify(message, "success" if success else "error")
        if success:
            self.refresh()
            self.data_changed.emit()
        return bool(success)

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
        success, message = self._controller.merge_duplicate_clients()
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
        dialog = ClientDetailDialog(client, stats, self._lead_map.get(str(client_id)), self)
        dialog.export_requested.connect(lambda cid: self.export_client_report(cid))
        dialog.exec()
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
        success, message, generated = self._report_generator(
            client_info=client,
            stats=stats,
            filename=path,
        )
        self._notify(message, "success" if success else "error")
        return str(generated) if success and generated else None

    def _notify(self, message: str, level: str) -> None:
        """Show inline feedback; the hosting shell decides whether to pop up errors."""
        self.status_label.setText(message)
        self.status_label.setProperty("level", level)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.notification_requested.emit(message, level)


__all__ = ["ClientDetailDialog", "ClientFormDialog", "ClientsPage"]
