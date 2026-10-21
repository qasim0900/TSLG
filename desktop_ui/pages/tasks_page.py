"""Tasks and follow-ups. A lead's next follow-up is its earliest open task."""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget
from sqlalchemy.orm import Session

from crm.db import utcnow
from crm.schemas import TaskCreate, TaskUpdate, parse
from crm.security.permissions import Scope
from crm.services import leads, tasks
from crm.services.access import Actor
from crm.services.pagination import PageRequest
from crm.vocabulary import PRIORITIES, TASK_STATUSES

from ..forms import FieldSpec, FormDialog
from ..records import Column, DetailPanel, DetailView, RecordPage, Row, RowPage
from ..session import AppContext
from ..support import attempt, label, local_time, options, person, text
from ..workflows import client_options, open_lead, user_options


def task_fields(people: list[tuple[str, str]], lead_choices: list[tuple[str, str]],
                client_choices: list[tuple[str, str]]) -> list[FieldSpec]:
    return [
        FieldSpec("title", "Task", required=True, span=True, placeholder="e.g. Call to confirm requirements"),
        FieldSpec("due_at", "Due", "datetime", hint="Shown in your time zone. Overdue tasks are highlighted."),
        FieldSpec("priority", "Priority", "choice", options(PRIORITIES), blank=None),
        FieldSpec("assigned_to_id", "Assigned to", "choice", people, blank=None),
        FieldSpec("lead_id", "Lead", "choice", lead_choices, blank="Not about a lead", searchable=True,
                  hint="A lead's next follow-up is its earliest open task."),
        FieldSpec("client_id", "Client", "choice", client_choices, blank="Not about a client", searchable=True,
                  hint="Filled in from the lead when one is chosen."),
        FieldSpec("description", "Details", "multiline"),
    ]


def _form(parent: QWidget, context: AppContext, *, heading: str, values: dict[str, Any], submit: Any,
          submit_text: str) -> FormDialog | None:
    people = user_options(context, parent, permission="tasks.assign")
    ok, lead_choices = attempt(parent, context, lambda db, actor: leads.open_choices(db, actor)
                               if actor.can("leads.view") else [])
    client_choices = client_options(context, parent) if context.can("clients.view") else []
    if people is None or not ok or lead_choices is None or client_choices is None or context.actor is None:
        return None
    current = values.get("lead_id")
    if current and current not in {value for value, _label in lead_choices}:
        lead_choices = [(current, values.get("lead_label") or "Current lead"), *lead_choices]
    return FormDialog(parent, title="Task", heading=heading, values=values, submit=submit, submit_text=submit_text,
                      timezone=context.actor.timezone, fields=task_fields(people, lead_choices, client_choices))


def create_task(parent: QWidget, context: AppContext, *, lead_id: str | None = None, client_id: str | None = None,
                title: str = "") -> str | None:
    if context.actor is None:
        return None

    def submit(dialog: FormDialog) -> str:
        values = {key: value for key, value in dialog.values().items() if value is not None}
        data = parse(TaskCreate, values)
        return context.write("task", lambda db, actor: tasks.create_task(db, actor, data).id)

    dialog = _form(parent, context, heading="New task", submit=submit, submit_text="Create task",
                   values={"title": title or None, "priority": "medium", "lead_id": lead_id, "client_id": client_id,
                           "assigned_to_id": context.actor.user_id})
    if dialog is not None and dialog.exec():
        return str(dialog.result_value)
    return None


class TasksPage(RecordPage):
    title = "Tasks"
    subtitle = "Follow-ups and to-dos for leads and clients. Times are shown in your time zone."
    noun = "task"
    plural = "tasks"
    columns = (
        Column("title", "Task", "title"),
        Column("due", "Due", "due", alert=True, keep=True),
        Column("priority", "Priority", "priority", badge=True),
        Column("status", "Status", "status", badge=True),
        Column("assignee", "Assigned to"),
        Column("related", "About"),
    )
    default_sort = None
    create_permission = "tasks.create"

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.view_filter = QComboBox()
        self.view_filter.setAccessibleName("Whose tasks")
        for value, text_ in tasks.VIEWS.items():
            self.view_filter.addItem(text_, value)
        self.view_filter.currentIndexChanged.connect(lambda _index: self.records.reload(page=1))
        bar.addWidget(self.view_filter)
        self.due_filter = QComboBox()
        self.due_filter.setAccessibleName("Due")
        for value, text_ in tasks.DUE_FILTERS.items():
            self.due_filter.addItem(text_, value)
        self.due_filter.currentIndexChanged.connect(lambda _index: self.records.reload(page=1))
        bar.addWidget(self.due_filter)

    def update_permissions(self) -> None:
        super().update_permissions()
        actor = self.context.actor
        team = actor is not None and actor.scope("tasks.view") is Scope.ALL
        model = self.view_filter.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(self.view_filter.findData("team"))
            if item is not None:
                item.setEnabled(team)
        if not team and self.view_filter.currentData() == "team":
            self.view_filter.setCurrentIndex(0)

    def list_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {"view": self.view_filter.currentData() or "mine",
                                   "due": self.due_filter.currentData() or "open"}
        if self.search.text().strip():
            filters["q"] = self.search.text().strip()
        return filters

    def set_filter_values(self, values: dict[str, str]) -> None:
        for combo, key in ((self.view_filter, "view"), (self.due_filter, "due")):
            combo.blockSignals(True)
            if values.get(key):
                self.set_combo(combo, values[key])
            combo.blockSignals(False)

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        zone = actor.timezone
        now = utcnow()
        page = tasks.list_tasks(db, actor, page=request, **filters)

        def row(task: Any) -> Row:
            overdue = task.status == "open" and task.due_at is not None and task.due_at < now
            related = leads.display_title(task.lead) if task.lead else (task.client.name if task.client else "")
            return Row(task.id, [
                task.title, local_time(task.due_at, zone) + (" (overdue)" if overdue else ""),
                label(PRIORITIES, task.priority), label(TASK_STATUSES, task.status),
                person(task.assigned_to), related,
            ], emphasis="alert" if overdue else "muted" if task.status != "open" else "")

        return RowPage.build(page, row)

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        task = tasks.get_task(db, actor, record_id)
        zone = actor.timezone
        fields = [
            ("Status", label(TASK_STATUSES, task.status)),
            ("Due", local_time(task.due_at, zone) or "No due date"),
            ("Priority", label(PRIORITIES, task.priority)),
            ("Assigned to", person(task.assigned_to)),
            ("Lead", leads.display_title(task.lead) if task.lead else ""),
            ("Client", task.client.name if task.client else ""),
            ("Details", text(task.description)),
            ("Completed", local_time(task.completed_at, zone)),
            ("Created", local_time(task.created_at, zone)),
        ]
        allowed = set()
        if actor.can_on("tasks.edit", task):
            allowed.add("edit" if task.status == "open" else "reopen")
            if task.status == "open":
                allowed |= {"done", "cancel"}
        if task.lead_id and actor.can("leads.view"):
            allowed.add("lead")
        values = {"title": task.title, "description": task.description, "priority": task.priority,
                  "due_at": task.due_at, "assigned_to_id": task.assigned_to_id, "lead_id": task.lead_id,
                  "client_id": task.client_id, "lead_label": leads.display_title(task.lead) if task.lead else None}
        return DetailView(task.id, task.title, label(TASK_STATUSES, task.status), fields, (), allowed,
                          {"version": task.version, "values": values, "lead_id": task.lead_id})

    def build_actions(self, panel: DetailPanel) -> None:
        self.done_button = panel.add_action("Mark done", lambda: self.set_status("done"), primary=True)
        self.edit_button = panel.add_action("Edit", self.edit_current)
        self.reopen_button = panel.add_action("Reopen", lambda: self.set_status("open"))
        self.cancel_button = panel.add_action("Cancel task", lambda: self.set_status("cancelled"))
        self.lead_button = panel.add_action("Open lead", self.open_lead)

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        self.done_button.setEnabled("done" in allowed)
        self.edit_button.setEnabled("edit" in allowed)
        self.reopen_button.setEnabled("reopen" in allowed)
        self.cancel_button.setEnabled("cancel" in allowed)
        self.lead_button.setEnabled("lead" in allowed)

    def create_record(self) -> None:
        record_id = create_task(self, self.context)
        if record_id:
            self.after_change(record_id, "Task created")

    def edit_current(self) -> None:
        view = self.current_view()
        if view is None or "edit" not in view.allowed:
            return

        def submit(dialog: FormDialog) -> None:
            changes = dialog.changed()
            if not changes:
                return
            data = parse(TaskUpdate, {**changes, "version": view.data["version"]})
            self.context.write("task", lambda db, actor: tasks.update_task(db, actor, view.id, data))

        dialog = _form(self, self.context, heading=f"Edit {view.title}", values=view.data["values"], submit=submit,
                       submit_text="Save changes")
        if dialog is not None and dialog.exec():
            self.after_change(view.id, "Task saved")

    def set_status(self, status: str) -> None:
        view = self.current_view()
        if view is None:
            return
        version = view.data["version"]
        ok, _ = attempt(self, self.context, lambda db, actor: tasks.set_status(db, actor, view.id, status, version),
                        kind="task")
        if ok:
            self.after_change(view.id, {"done": "Task completed", "open": "Task reopened",
                                        "cancelled": "Task cancelled"}[status])

    def open_lead(self) -> None:
        view = self.current_view()
        if view is not None and view.data.get("lead_id") and open_lead(self, self.context, view.data["lead_id"]):
            self.after_change(view.id, "Lead updated")


__all__ = ["TasksPage", "create_task"]
