from __future__ import annotations

from datetime import date
from typing import Any, NamedTuple, cast

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
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
from sqlalchemy.orm import Session

from techset_leadgen.database.engine import utcnow
from techset_leadgen.domain.outreach import ACTIVE_ASSIGNMENT_STATUSES, OPEN_ASSIGNMENT_STATUSES, balance_plan
from techset_leadgen.domain.vocabulary import ASSIGNMENT_STATUSES, BATCH_STATUSES, PROSPECT_STATUSES
from techset_leadgen.services import assignments, prospects
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import MAX_PAGE_SIZE, PageRequest
from techset_leadgen.services.schemas import BatchCreate, Reassignment, parse

from techset_leadgen.desktop.dialogs import ask_confirmation
from techset_leadgen.desktop.forms import FieldSpec, FormDialog
from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.modal import ModalDialog
from techset_leadgen.desktop.pages.outreach_pages import open_profile
from techset_leadgen.desktop.pages.prospects_page import ProspectImportDialog, _display_name, prospect_view
from techset_leadgen.desktop.records import Column, DetailPanel, DetailView, RecordPage, Row, RowPage
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import attempt, date_text, label, local_time, text
from techset_leadgen.desktop.widgets import Alert, SearchField, set_table_defaults

ID_ROLE = Qt.ItemDataRole.UserRole


class _Batch(NamedTuple):
    id: str
    name: str
    status: str
    version: int
    total: int
    open: int


class BatchDialog(ModalDialog):
    def __init__(self, parent: QWidget, context: AppContext, *, preselected: list[str] | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.result_value: str | None = None
        self.chosen: dict[str, str] = {}
        self._members: list[assignments.Member] = []
        for prospect_id in preselected or []:
            self.chosen[prospect_id] = ""
        self.setWindowTitle("New daily batch")
        self.setAccessibleName("Create a daily assignment batch")
        self.setModal(True)
        self.resize(1040, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        root.addWidget(body, 1)

        heading = QLabel("Assign LinkedIn profiles for a work day")
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        intro = QLabel("Tick the profiles and the people. Profiles go to whoever has the least open work, so the "
                       "team stays balanced. Nothing is saved until you confirm.")
        intro.setObjectName("dialogSubtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        details = QGridLayout()
        details.setHorizontalSpacing(12)
        self.name = QLineEdit()
        self.name.setAccessibleName("Batch name")
        self.name.setMaxLength(120)
        self.work_date = QDateEdit(QDate.currentDate())
        self.work_date.setCalendarPopup(True)
        self.work_date.setDisplayFormat("dd MMM yyyy")
        self.work_date.setAccessibleName("Work date")
        self.work_date.dateChanged.connect(self._default_name)
        self.draft = QCheckBox("Save as a draft (team members see it only after you activate it)")
        for column, (caption, widget) in enumerate((("Work date", self.work_date), ("Batch name", self.name))):
            caption_label = QLabel(caption)
            caption_label.setObjectName("fieldLabel")
            caption_label.setBuddy(widget)
            details.addWidget(caption_label, 0, column)
            details.addWidget(widget, 1, column)
        details.setColumnStretch(1, 1)
        layout.addLayout(details)
        self._default_name()

        columns = QHBoxLayout()
        columns.setSpacing(16)
        left = QVBoxLayout()
        search_row = QHBoxLayout()
        self.search = SearchField("Search unassigned prospects")
        self.search.setAccessibleName("Search unassigned prospects")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.load_prospects)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        search_row.addWidget(self.search, 1)
        self.import_button = QPushButton("Paste or import…")
        self.import_button.setObjectName("secondaryButton")
        set_button_icon(self.import_button, "upload", "text")
        self.import_button.clicked.connect(self.import_more)
        self.import_button.setVisible(context.can("prospects.create"))
        search_row.addWidget(self.import_button)
        left.addLayout(search_row)
        self.prospect_table = QTableWidget(0, 3)
        self.prospect_table.setHorizontalHeaderLabels(["Prospect", "Company", "Status"])
        self.prospect_table.setAccessibleName("Unassigned prospects to choose from")
        set_table_defaults(self.prospect_table, badge_columns=[2], empty_text="No unassigned prospects.")
        self.prospect_table.itemChanged.connect(self._prospect_toggled)
        left.addWidget(self.prospect_table, 1)
        self.prospect_note = QLabel()
        self.prospect_note.setObjectName("sectionSubtitle")
        left.addWidget(self.prospect_note)
        columns.addLayout(left, 3)

        right = QVBoxLayout()
        self.member_table = QTableWidget(0, 4)
        self.member_table.setHorizontalHeaderLabels(["Team member", "Open now", "New", "After"])
        self.member_table.setAccessibleName("Team members and their workload")
        set_table_defaults(self.member_table, numeric_columns=[1, 2, 3],
                           empty_text="Nobody can record outreach yet.")
        header = self.member_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.member_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.member_table.itemChanged.connect(lambda _item: self._update_preview())
        right.addWidget(self.member_table, 1)
        columns.addLayout(right, 2)
        layout.addLayout(columns, 1)

        layout.addWidget(self.draft)
        self.notice = Alert("Choose at least one profile and one team member.", "info")
        layout.addWidget(self.notice)

        footer = QFrame()
        footer.setObjectName("modalFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("Assign")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)
        root.addWidget(footer)

        self.load_members()
        self.load_prospects()

    def _default_name(self) -> None:
        if not self.name.isModified():
            self.name.setText(f"Daily batch {date_text(self.work_date.date().toString(Qt.DateFormat.ISODate))}")


    def load_members(self) -> None:
        ok, members = attempt(self, self.context, lambda db, actor: assignments.assignable_members(db, actor),
                              commit=False, title="Team members")
        self._members = list(members or []) if ok else []
        self.member_table.blockSignals(True)
        self.member_table.setRowCount(len(self._members))
        for row, member in enumerate(self._members):
            item = QTableWidgetItem(member.name)
            item.setData(ID_ROLE, member.user_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.member_table.setItem(row, 0, item)
            for column in (1, 2, 3):
                cell = QTableWidgetItem(str(member.open_assignments) if column != 2 else "0")
                cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.member_table.setItem(row, column, cell)
        self.member_table.blockSignals(False)
        self._update_preview()

    def load_prospects(self) -> None:
        query = self.search.text().strip() or None

        def work(db: Session, actor: Actor) -> tuple[list[tuple[str, str, str, str]], int, dict[str, str]]:
            page = prospects.list_prospects(db, actor, page=PageRequest(page_size=MAX_PAGE_SIZE, sort="added"),
                                            q=query, assignee="none")
            rows = [(item.prospect.id, _display_name(item.prospect), text(item.prospect.company) or "—",
                     PROSPECT_STATUSES.get(item.prospect.status, item.prospect.status)) for item in page.items]
            unnamed = [prospect_id for prospect_id, name in self.chosen.items() if not name]
            names = {}
            for prospect_id in unnamed:
                try:
                    names[prospect_id] = _display_name(prospects.get_prospect(db, actor, prospect_id))
                except Exception:
                    names[prospect_id] = ""
            return rows, page.total, names

        ok, result = attempt(self, self.context, work, commit=False, title="Prospects")
        if not ok or result is None:
            return
        rows, total, names = result
        for prospect_id, name in names.items():
            if name:
                self.chosen[prospect_id] = name
            else:
                self.chosen.pop(prospect_id, None)
        self.prospect_table.blockSignals(True)
        self.prospect_table.setRowCount(len(rows))
        for index, (prospect_id, name, company, status) in enumerate(rows):
            item = QTableWidgetItem(name)
            item.setData(ID_ROLE, prospect_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if prospect_id in self.chosen else Qt.CheckState.Unchecked)
            self.prospect_table.setItem(index, 0, item)
            self.prospect_table.setItem(index, 1, QTableWidgetItem(company))
            self.prospect_table.setItem(index, 2, QTableWidgetItem(status))
        self.prospect_table.blockSignals(False)
        shown = f"Showing {len(rows)} of {total} unassigned" if total > len(rows) else f"{total} unassigned"
        self.prospect_note.setText(f"{shown} · {len(self.chosen)} chosen")
        self._update_preview()

    def import_more(self) -> None:
        dialog = ProspectImportDialog(self, self.context)
        if dialog.exec() and dialog.result_value is not None:
            for prospect_id in dialog.result_value.created:
                self.chosen[prospect_id] = ""
            self.load_prospects()


    def _prospect_toggled(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        prospect_id = str(item.data(ID_ROLE))
        if item.checkState() == Qt.CheckState.Checked:
            self.chosen[prospect_id] = item.text()
        else:
            self.chosen.pop(prospect_id, None)
        self.prospect_note.setText(self.prospect_note.text().split(" · ")[0] + f" · {len(self.chosen)} chosen")
        self._update_preview()

    def selected_members(self) -> dict[str, int]:
        chosen: dict[str, int] = {}
        for row, member in enumerate(self._members):
            item = self.member_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                chosen[member.user_id] = member.open_assignments
        return chosen

    def plan(self) -> list[tuple[str, str]]:
        return balance_plan(list(self.chosen), self.selected_members())

    def _update_preview(self) -> None:
        plan = self.plan()
        new = {member.user_id: 0 for member in self._members}
        for _prospect_id, user_id in plan:
            new[user_id] += 1
        self.member_table.blockSignals(True)
        for row, member in enumerate(self._members):
            for column, value in ((2, new[member.user_id]), (3, member.open_assignments + new[member.user_id])):
                cell = self.member_table.item(row, column)
                if cell is not None:
                    cell.setText(str(value))
        self.member_table.blockSignals(False)
        people = len(self.selected_members())
        if not plan:
            self.notice.set_message("Choose at least one profile and one team member.")
        else:
            self.notice.set_message(f"{len(plan)} profile{'s' if len(plan) != 1 else ''} to {people} "
                                 f"{'person' if people == 1 else 'people'}. Members are notified when the batch "
                                 "is active.")
        self.save_button.setEnabled(bool(plan))
        self.save_button.setText(f"Assign {len(plan)}" if plan else "Assign")

    def save(self) -> None:
        plan = self.plan()
        if not plan:
            return
        work_date = cast(date, self.work_date.date().toPython())
        payload = {"name": self.name.text(), "work_date": work_date, "draft": self.draft.isChecked(),
                   "plan": [{"prospect_id": prospect_id, "assignee_id": user_id} for prospect_id, user_id in plan]}

        def work(db: Session, actor: Actor) -> str:
            return assignments.create_batch(db, actor, parse(BatchCreate, payload)).id

        ok, batch_id = attempt(self, self.context, work, kind="assignment", title="Assign profiles")
        if ok and batch_id:
            self.result_value = batch_id
            self.accept()


class AssignmentsPage(RecordPage):
    title = "Daily Assignments"
    subtitle = "Give LinkedIn profiles to team members for a work day, follow progress, and reassign when needed."
    noun = "assignment"
    plural = "assignments"
    columns = (
        Column("prospect", "Prospect", "prospect", strong=True),
        Column("assignee", "Assigned to", "assignee", avatar=True),
        Column("status", "Status", "status", badge=True, keep=True),
        Column("due", "Work day", "due", keep=True, alert=True),
        Column("batch", "Batch", muted=True),
        Column("activity", "Last activity", keep=True),
    )
    default_sort = "-assigned"
    create_permission = "assignments.manage"

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.new_button.setText("New daily batch")
        self.activate_button = QPushButton("Activate draft")
        self.activate_button.setObjectName("secondaryButton")
        set_button_icon(self.activate_button, "check", "text")
        self.activate_button.clicked.connect(self.activate_batch)
        self.cancel_batch_button = QPushButton("Cancel batch")
        self.cancel_batch_button.setObjectName("dangerOutlineButton")
        self.cancel_batch_button.clicked.connect(self.cancel_batch)
        for button in (self.activate_button, self.cancel_batch_button):
            button.hide()
            self.toolbar.insertWidget(0, button)
        self._batches: dict[str, _Batch] = {}
        self.records.set_empty_state("No assignments match", "Create a daily batch to give profiles to the team.",
                                     ("New daily batch", self.create_record), icon="assignments")

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.batch_filter = self.filter_combo(bar, "Batch", [], everything="All batches")
        self.member_filter = self.filter_combo(bar, "Team member", [], everything="Everyone")
        self.status_filter = self.filter_combo(
            bar, "Assignment status", [*((key, ASSIGNMENT_STATUSES[key]) for key in ASSIGNMENT_STATUSES),
                                       ("all", "Any status")], everything="Open work")
        self.due_filter = self.filter_combo(bar, "Work day", [("today", "Today"), ("overdue", "Overdue"),
                                                              ("upcoming", "Next 7 days")], everything="Any day")
        self.batch_filter.currentIndexChanged.connect(lambda _index: self._sync_batch_buttons())
        for combo in (self.batch_filter, self.member_filter, self.status_filter, self.due_filter):
            combo.setMinimumWidth(140)

    def refresh(self) -> None:
        self._load_choices()
        super().refresh()

    def _load_choices(self) -> None:
        def work(db: Session, actor: Actor) -> tuple[list[_Batch], list[Any]]:
            batches = [_Batch(summary.batch.id, summary.batch.name, summary.batch.status, summary.batch.version,
                              summary.total, sum(summary.counts.get(state, 0) for state in OPEN_ASSIGNMENT_STATUSES))
                       for summary in assignments.list_batches(db, actor)]
            return batches, assignments.assignable_members(db, actor)

        ok, result = attempt(self, self.context, work, commit=False, title="Assignments")
        if not ok or result is None:
            return
        batches, members = result
        self._batches = {batch.id: batch for batch in batches}
        for combo, options in (
            (self.batch_filter, [(batch.id, f"{batch.name} · {BATCH_STATUSES.get(batch.status, batch.status)} · "
                                  f"{batch.total}") for batch in batches]),
            (self.member_filter, [(member.user_id, member.name) for member in members]),
        ):
            current = combo.currentData()
            combo.blockSignals(True)
            while combo.count() > 1:
                combo.removeItem(1)
            for value, caption in options:
                combo.addItem(caption, value)
            self.set_combo(combo, current)
            combo.blockSignals(False)
        self._sync_batch_buttons()

    def _sync_batch_buttons(self) -> None:
        batch = self._batches.get(self.batch_filter.currentData() or "")
        self.activate_button.setVisible(batch is not None and batch.status == "draft")
        self.cancel_batch_button.setVisible(batch is not None and batch.status in {"draft", "active"})

    def list_filters(self) -> dict[str, Any]:
        filters = super().list_filters()
        for key, combo in (("batch_id", self.batch_filter), ("assignee_id", self.member_filter),
                           ("status", self.status_filter), ("due", self.due_filter)):
            if combo.currentData():
                filters[key] = combo.currentData()
        if filters.get("batch_id") and "status" not in filters:
            filters["status"] = "all"
        return filters

    def set_filter_values(self, values: dict[str, str]) -> None:
        for combo, key in ((self.batch_filter, "batch_id"), (self.member_filter, "assignee_id"),
                           (self.status_filter, "status"), (self.due_filter, "due")):
            combo.blockSignals(True)
            self.set_combo(combo, values.get(key))
            combo.blockSignals(False)

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        found = assignments.list_assignments(db, actor, page=request, view="team", now=utcnow(), **filters)

        def row(item: Any) -> Row:
            prospect = item.prospect
            open_ = item.status in OPEN_ASSIGNMENT_STATUSES
            return Row(item.id, [
                _display_name(prospect), item.assignee.full_name, label(ASSIGNMENT_STATUSES, item.status),
                date_text(item.due_on.isoformat()) if item.due_on else "—",
                item.batch.name if item.batch else "—",
                local_time(prospect.last_activity_at, actor.timezone) or "Not started",
            ], tooltip=prospect.linkedin_url, emphasis="" if open_ else "muted")

        return RowPage.build(found, row)

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        assignment = assignments.get_assignment(db, actor, record_id)
        view = prospect_view(db, actor, assignment.prospect_id)
        view.id = assignment.id
        open_ = assignment.status in OPEN_ASSIGNMENT_STATUSES
        view.allowed = {"open"} | ({"reassign", "cancel"} if open_ and actor.can("assignments.manage") else set())
        view.fields = [("Assigned to", assignment.assignee.full_name),
                       ("Assignment", label(ASSIGNMENT_STATUSES, assignment.status)),
                       ("Work day", date_text(assignment.due_on.isoformat()) if assignment.due_on else "—"),
                       ("Batch", assignment.batch.name if assignment.batch else "—"),
                       *(field for field in view.fields if field[0] not in {"Assigned to", "Assignment"})]
        view.data.update({"assignment_version": assignment.version, "assignee_id": assignment.assignee_id,
                          "started": assignment.status in ACTIVE_ASSIGNMENT_STATUSES})
        return view

    def build_actions(self, panel: DetailPanel) -> None:
        self.reassign_button = panel.add_action("Reassign", self.reassign, primary=True, icon="assign")
        self.open_button = panel.add_action("Open LinkedIn", lambda: open_profile(self, self.current_view()),
                                            icon="arrow-right")
        self.cancel_button = panel.add_action("Cancel assignment", self.cancel_assignment, destructive=True,
                                              icon="close")

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        for button, key in ((self.reassign_button, "reassign"), (self.open_button, "open"),
                            (self.cancel_button, "cancel")):
            button.setEnabled(key in allowed)

    def create_record(self) -> None:
        self.open_batch_dialog()

    def open_batch_dialog(self, preselected: list[str] | None = None) -> None:
        if not self.context.can("assignments.manage"):
            return
        dialog = BatchDialog(self, self.context, preselected=preselected)
        if dialog.exec() and dialog.result_value:
            self._load_choices()
            self.set_combo(self.batch_filter, dialog.result_value)
            self.after_change(None, "Profiles assigned" if not dialog.draft.isChecked() else "Draft batch saved")

    def reassign(self) -> None:
        view = self.current_view()
        if view is None or "reassign" not in view.allowed:
            return
        options = [(value, caption) for value, caption in
                   ((self.member_filter.itemData(index), self.member_filter.itemText(index))
                    for index in range(1, self.member_filter.count())) if value != view.data["assignee_id"]]

        def submit(dialog: FormDialog) -> None:
            data = parse(Reassignment, {**dialog.values(), "version": view.data["assignment_version"]})
            self.context.write("assignment", lambda db, actor: assignments.reassign(db, actor, view.id, data))

        dialog = FormDialog(self, title="Reassign", heading=f"Give {view.data['title']} to someone else",
                            note="The current assignment is closed and kept in the history; its open follow-up "
                                 "moves to the new person, who is notified.",
                            fields=[FieldSpec("assignee_id", "New team member", "choice", options=options,
                                              required=True, blank=None, searchable=True, span=True),
                                    FieldSpec("reason", "Reason", "multiline")],
                            submit=submit, submit_text="Reassign")
        if dialog.exec():
            self.after_change(None, "Prospect reassigned")

    def cancel_assignment(self) -> None:
        view = self.current_view()
        if view is None or "cancel" not in view.allowed:
            return

        def submit(dialog: FormDialog) -> None:
            reason = dialog.values().get("reason")
            self.context.write("assignment", lambda db, actor: assignments.cancel_assignment(
                db, actor, view.id, view.data["assignment_version"], reason=reason))

        dialog = FormDialog(self, title="Cancel assignment", heading=f"Cancel the assignment of {view.data['title']}?",
                            note="The profile becomes unassigned. Recorded outcomes and history stay.",
                            fields=[FieldSpec("reason", "Reason", "multiline")], submit=submit,
                            submit_text="Cancel assignment")
        if dialog.exec():
            self.after_change(view.id, "Assignment cancelled")

    def activate_batch(self) -> None:
        batch = self._batches.get(self.batch_filter.currentData() or "")
        if batch is None or batch.status != "draft":
            return
        if not ask_confirmation(self, title="Activate batch", heading=f"Activate “{batch.name}”?",
                                message=f"{batch.total} profiles become visible to their team members, who "
                                        "are notified.", confirm_text="Activate"):
            return
        ok, _ = attempt(self, self.context, lambda db, actor: assignments.activate_batch(
            db, actor, batch.id, batch.version), kind="assignment", title="Activate batch")
        if ok:
            self.refresh()
            self.status_requested.emit("Batch activated")

    def cancel_batch(self) -> None:
        batch = self._batches.get(self.batch_filter.currentData() or "")
        if batch is None or batch.status not in {"draft", "active"}:
            return
        if not ask_confirmation(self, title="Cancel batch", heading=f"Cancel “{batch.name}”?",
                                message=f"Its {batch.open} open assignments are cancelled and the profiles become "
                                        "unassigned. Completed work and recorded outcomes stay.",
                                confirm_text="Cancel batch", cancel_text="Keep batch", destructive=True):
            return
        ok, _ = attempt(self, self.context, lambda db, actor: assignments.cancel_batch(
            db, actor, batch.id, batch.version), kind="assignment", title="Cancel batch")
        if ok:
            self.refresh()
            self.status_requested.emit("Batch cancelled")

    def open_link(self, key: str) -> None:
        if key == "linkedin":
            open_profile(self, self.current_view())


__all__ = ["AssignmentsPage", "BatchDialog"]

