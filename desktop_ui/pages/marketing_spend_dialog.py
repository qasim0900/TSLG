"""Marketing spend editor for the Leads workspace.

Restores the add/edit/delete spend editor of the retired Flet UI
(``components/marketing_spend_editor.py``). Spend imports are additive and the
Dashboard cannot clear spend, so without this editor a wrong amount could not
be corrected anywhere in the application. Persistence and validation stay in
``LeadsController``/``models.marketing_spend_manager``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from controllers.leads_controller import LeadsController
from domain.source_labels import SOURCE_LABELS
from utils.formatting import format_eur, parse_amount

from ..dialogs import ask_confirmation
from ..modal import ModalDialog
from ..row_actions import RowAction, RowActionDelegate
from ..support import date_text
from ..tables import prepare_table
from ..widgets import labeled_field, sortable_item

_RECORD_ID_ROLE = Qt.ItemDataRole.UserRole + 2


def _source_label(value: Any) -> str:
    raw = str(value or "unknown")
    return SOURCE_LABELS.get(raw, raw.replace("_", " ").title())


class MarketingSpendDialog(ModalDialog):
    """List, add, edit, and delete marketing spend records."""

    def __init__(
        self,
        controller: type[LeadsController] | Any = LeadsController,
        parent: QWidget | None = None,
        *,
        context: Any = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._context = context  # AppContext: checks marketing.manage and audits each change
        self._records: list[dict[str, Any]] = []
        self._editing_id: int | None = None
        self.changed = False
        self.setWindowTitle("Marketing spend")
        self.setModal(True)
        self.resize(720, 560)
        self.setMinimumSize(520, 420)
        self.setAccessibleName("Marketing spend editor")

        root = QVBoxLayout(self)
        title = QLabel("Marketing spend")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "Spend per source feeds CPL, CAC, and ROI on the Leads page. Amounts are in euros."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        form = QGridLayout()
        root.addLayout(form)
        form.setHorizontalSpacing(12)
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.setAccessibleName("Spend source")
        source_editor = self.source_combo.lineEdit()
        if source_editor is not None:
            source_editor.setPlaceholderText("Choose or type a source")
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("e.g. 1,250.00")
        self.amount_edit.setAccessibleName("Spend amount in euros")
        self.amount_edit.setClearButtonEnabled(True)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setAccessibleName("Spend date")
        form.addWidget(labeled_field("Source", self.source_combo), 0, 0)
        form.addWidget(labeled_field("Amount (EUR)", self.amount_edit), 0, 1)
        form.addWidget(labeled_field("Date", self.date_edit), 0, 2)
        for column in range(3):
            form.setColumnStretch(column, 1)

        actions = QHBoxLayout()
        root.addLayout(actions)
        self.error_label = QLabel("")
        self.error_label.setObjectName("formError")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setAccessibleName("Spend validation error")
        self.error_label.hide()
        actions.addWidget(self.error_label, 1)
        self.cancel_edit_button = QPushButton("Cancel edit")
        self.cancel_edit_button.setObjectName("secondaryButton")
        self.cancel_edit_button.clicked.connect(self._reset_form)
        self.cancel_edit_button.hide()
        self.save_button = QPushButton("Add record")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.cancel_edit_button)
        actions.addWidget(self.save_button)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Source", "Amount", "Actions"])
        self.table.setAccessibleName("Marketing spend records")
        prepare_table(self.table, numeric_columns=(2,),
                      empty_text="No spend recorded yet. Add a record above or import a spend CSV.")
        header = self.table.horizontalHeader()
        header.setSortIndicator(0, Qt.SortOrder.DescendingOrder)  # newest first
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._row_actions = (
            RowAction("edit", "Edit", "Edit this spend record"),
            RowAction("delete", "Delete", "Delete this spend record", destructive=True),
        )
        self._action_delegate = RowActionDelegate(
            self._row_actions, id_role=_RECORD_ID_ROLE, view=self.table
        )
        self._action_delegate.triggered.connect(self._run_row_action)
        self.table.setItemDelegateForColumn(3, self._action_delegate)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, self._action_delegate.column_width())
        root.addWidget(self.table, 1)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("filterSummary")
        self.summary_label.setAccessibleName("Spend totals")
        root.addWidget(self.summary_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.reload()

    # ------------------------------------------------------------- data

    def reload(self) -> None:
        self._records = list(self._controller.get_marketing_spend_entries() or [])
        known = dict(SOURCE_LABELS)
        for record in self._records:
            source = str(record.get("source") or "")
            if source and source not in known:
                known[source] = _source_label(source)
        current = self.source_combo.currentText()
        self.source_combo.clear()
        for key, label in sorted(known.items(), key=lambda pair: pair[1].casefold()):
            self.source_combo.addItem(label, key)
        self.source_combo.setEditText(current)

        table = self.table
        table.setSortingEnabled(False)
        table.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            record_id = record.get("id")
            amount = float(record.get("amount") or 0)
            cells = (
                sortable_item(date_text(record.get("date")) or "—", str(record.get("date") or "")),
                QTableWidgetItem(_source_label(record.get("source"))),
                sortable_item(format_eur(amount), amount),
                QTableWidgetItem(),
            )
            cells[2].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cells[3].setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"Actions for {_source_label(record.get('source'))} spend on {record.get('date')}",
            )
            for column, item in enumerate(cells):
                item.setData(_RECORD_ID_ROLE, record_id)
                table.setItem(row, column, item)
        table.setSortingEnabled(True)
        total = sum(float(record.get("amount") or 0) for record in self._records)
        count = len(self._records)
        self.summary_label.setText(
            f"{count} record{'s' if count != 1 else ''} · total {format_eur(total)}"
            if count
            else "No spend recorded yet. Add a record above or import a spend CSV."
        )

    def _record(self, record_id: Any) -> dict[str, Any] | None:
        return next((r for r in self._records if str(r.get("id")) == str(record_id)), None)

    # ------------------------------------------------------------- actions

    def _selected_source(self) -> str:
        text = self.source_combo.currentText().strip()
        index = self.source_combo.findText(text, Qt.MatchFlag.MatchFixedString)
        return str(self.source_combo.itemData(index)) if index >= 0 else text

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setAccessibleDescription(message)
        self.error_label.show()

    def _save(self) -> None:
        self.error_label.hide()
        source = self._selected_source()
        if not source:
            self._show_error("Choose or type a source.")
            self.source_combo.setFocus()
            return
        try:
            amount = parse_amount(self.amount_edit.text())
        except ValueError:
            self._show_error("Enter an amount such as 1,250.00.")
            self.amount_edit.setFocus()
            return
        date_text = self.date_edit.date().toString(Qt.DateFormat.ISODate)

        self.save_button.setEnabled(False)  # no duplicate records from a double click
        details = {"source": source, "amount": amount, "date": date_text}
        try:
            if self._editing_id is None:
                outcome = self._guarded("marketing_spend.created", lambda: self._controller.create_marketing_spend(
                    source, amount, date_text
                ), details)
            else:
                editing = self._editing_id
                outcome = self._guarded("marketing_spend.updated", lambda: self._controller.update_marketing_spend(
                    editing, source, amount, date_text
                ), {**details, "id": editing})
        finally:
            self.save_button.setEnabled(True)
        if outcome is None:
            return
        success, message = outcome[0], outcome[1]
        if not success:
            self._show_error(message)  # keep the user's input for correction
            return
        self.changed = True
        self._reset_form()
        self.reload()
        self.summary_label.setText(f"{message} {self.summary_label.text()}")

    def _guarded(self, action: str, operation: Any, details: dict[str, Any]) -> Any:
        """Run a spend change; with a signed-in session, check the role and audit it."""
        if self._context is None:
            return operation()
        try:
            return self._context.guarded("marketing.manage", action, operation, kind="data",
                                         entity_type="marketing_spend",
                                         changes=lambda outcome: details if outcome[0] else None)
        except Exception as exc:
            from ..support import report

            report(self, exc, title="Marketing spend")
            return None

    def _run_row_action(self, key: str, record_id: str) -> None:
        record = self._record(record_id)
        if record is None:
            self._show_error("That spend record no longer exists.")
            self.reload()
            return
        if key == "edit":
            self._start_edit(record)
        elif key == "delete":
            self._delete(record)

    def _start_edit(self, record: dict[str, Any]) -> None:
        self._editing_id = int(record["id"])
        self.source_combo.setEditText(_source_label(record.get("source")))
        self.amount_edit.setText(f"{float(record.get('amount') or 0):.2f}")
        parsed = QDate.fromString(str(record.get("date") or ""), Qt.DateFormat.ISODate)
        self.date_edit.setDate(parsed if parsed.isValid() else QDate.currentDate())
        self.save_button.setText("Save changes")
        self.cancel_edit_button.show()
        self.error_label.hide()
        self.amount_edit.setFocus()

    def _reset_form(self) -> None:
        self._editing_id = None
        self.amount_edit.clear()
        self.date_edit.setDate(QDate.currentDate())
        self.save_button.setText("Add record")
        self.cancel_edit_button.hide()
        self.error_label.hide()

    def _delete(self, record: dict[str, Any]) -> None:
        if not ask_confirmation(
            self,
            title="Delete spend record",
            heading=(
                f"Delete the {_source_label(record.get('source'))} spend of "
                f"{format_eur(float(record.get('amount') or 0))} on {record.get('date')}?"
            ),
            message="CPL, CAC, and ROI are recalculated without it. This cannot be undone.",
            confirm_text="Delete record",
            destructive=True,
        ):
            return
        outcome = self._guarded("marketing_spend.deleted",
                                lambda: self._controller.delete_marketing_spend(int(record["id"])),
                                {"id": record["id"], "source": record.get("source"), "amount": record.get("amount"),
                                 "date": record.get("date")})
        if outcome is None:
            return
        success, message = outcome
        if not success:
            self._show_error(message)
            return
        self.changed = True
        if self._editing_id == int(record["id"]):
            self._reset_form()
        self.reload()
        self.summary_label.setText(f"{message} {self.summary_label.text()}")


__all__ = ["MarketingSpendDialog"]
