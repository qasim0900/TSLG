from __future__ import annotations

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget
from sqlalchemy.orm import Session

from techset_leadgen.database.engine import utcnow
from techset_leadgen.services.schemas import TaskCreate, TaskUpdate, parse
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import leads, prospects, tasks
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.domain.vocabulary import PRIORITIES, TASK_STATUSES

from techset_leadgen.desktop.forms import FieldSpec, FormDialog
from techset_leadgen.desktop.records import Column, DetailPanel, DetailView, RecordPage, Row, RowPage
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import attempt, label, local_time, options, person, text
from techset_leadgen.desktop.tables import tone_for
from techset_leadgen.desktop.workflows import client_options, open_lead, user_options


def _about(task: Any) -> str:
    if task.prospect:
        return f"Prospect {task.prospect.full_name or task.prospect.linkedin_key}"
    if task.lead:
        return f"Lead {leads.display_title(task.lead)}"
    if task.client:
        return f"Client {task.client.name}"
    return ""


def task_fields(people: list[tuple[str, str]], lead_choices: list[tuple[str, str]],
                client_choices: list[tuple[str, str]],
                prospect_choices: list[tuple[str, str]] | None = None) -> list[FieldSpec]:
    fields = [
        FieldSpec("title", "Task", required=True, span=True, placeholder="e.g. Research 50 new fintech profiles"),
        FieldSpec("due_at", "Due", "datetime", hint="Shown in your time zone. Overdue tasks are highlighted."),
        FieldSpec("priority", "Priority", "choice", options(PRIORITIES), blank=None),
        FieldSpec("assigned_to_id", "Assigned to", "choice", people, blank=None),
    ]
    if prospect_choices:
        fields.append(FieldSpec("prospect_id", "Prospect", "choice", prospect_choices, blank="Not about a prospect",
                                searchable=True, hint="Optional: the LinkedIn profile this task is about."))
    if lead_choices:
        fields.append(FieldSpec("lead_id", "Lead", "choice", lead_choices, blank="Not about a lead", searchable=True,
                                hint="A lead's next follow-up is its earliest open task."))
    if client_choices:
        fields.append(FieldSpec("client_id", "Client", "choice", client_choices, blank="Not about a client",
                                searchable=True, hint="Filled in from the lead when one is chosen."))
    fields.append(FieldSpec("description", "Details", "multiline",
                            hint="What “done” means, so the person knows when to complete it."))
    return fields


def _prospect_choices(db: Session, actor: Actor, current: str | None) -> list[tuple[str, str]]:
    if not actor.can("prospects.view"):
        return []
    page = prospects.list_prospects(db, actor, page=PageRequest(page_size=100, sort="activity", descending=True))
    choices = [(item.prospect.id, item.prospect.full_name or item.prospect.linkedin_key) for item in page.items]
    if current and current not in {value for value, _label in choices}:
        prospect = prospects.get_prospect(db, actor, current)
        choices.insert(0, (prospect.id, prospect.full_name or prospect.linkedin_key))
    return choices


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
    ok, prospect_choices = attempt(parent, context, lambda db, actor: _prospect_choices(
        db, actor, values.get("prospect_id")), commit=False)
    if not ok:
        return None
    return FormDialog(parent, title="Task", heading=heading, values=values, submit=submit, submit_text=submit_text,
                      timezone=context.actor.timezone,
                      fields=task_fields(people, lead_choices, client_choices, prospect_choices))


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
    subtitle = ("General team tasks: research, reports, data clean-up. Follow-ups with prospects are under "
                "Follow-ups.")
    noun = "task"
    plural = "tasks"
    columns = (
        Column("title", "Task", "title", strong=True),
        Column("due", "Due", "due", keep=True, strong=True),
        Column("priority", "Priority", "priority", badge=True),
        Column("status", "Status", "status", badge=True),
        Column("assignee", "Assigned to", avatar=True),
        Column("related", "About", muted=True),
    )
    default_sort = None
    create_permission = "tasks.create"

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.records.table.setProperty("hoverNudge", True)
        self.empty_state = self.records.set_empty_state(
            "No tasks match these filters", "Change the filters, or create a follow-up with New task.",
            ("New task", self.create_record))

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.view_filter = QComboBox()
        self.view_filter.setAccessibleName("Whose tasks")
        self.view_filter.setMinimumWidth(190)
        for value, text_ in tasks.VIEWS.items():
            self.view_filter.addItem(text_, value)
        self.view_filter.currentIndexChanged.connect(lambda _index: self.records.reload(page=1))
        bar.addWidget(self.view_filter)
        self.due_filter = QComboBox()
        self.due_filter.setAccessibleName("Due")
        self.due_filter.setMinimumWidth(190)
        for value, text_ in tasks.DUE_FILTERS.items():
            self.due_filter.addItem(text_, value)
        self.due_filter.currentIndexChanged.connect(lambda _index: self.records.reload(page=1))
        bar.addWidget(self.due_filter)

    def update_permissions(self) -> None:
        super().update_permissions()
        for button in self.empty_state.findChildren(QPushButton):
            button.setVisible(self.context.can("tasks.create"))
        actor = self.context.actor
        if actor is not None:
            self.header.set_subtitle("General team tasks: research, reports, data clean-up. Follow-ups with "
                                     f"prospects are under Follow-ups. Times are in your time zone ({actor.timezone}).")
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
                                   "due": self.due_filter.currentData() or "open", "kind": "task"}
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
        start, end = tasks.local_day_bounds(zone, now)
        page = tasks.list_tasks(db, actor, page=request, **filters)

        def row(task: Any) -> Row:
            overdue = task.status == "open" and task.due_at is not None and task.due_at < now
            today = task.status == "open" and task.due_at is not None and start <= task.due_at < end
            related = _about(task)
            colors = {1: "danger"} if overdue else {1: "goldInk"} if today else {}
            return Row(task.id, [
                task.title, local_time(task.due_at, zone) + (" (overdue)" if overdue else ""),
                label(PRIORITIES, task.priority), label(TASK_STATUSES, task.status),
                person(task.assigned_to), related,
            ], emphasis="muted" if task.status != "open" else "", colors=colors)

        return RowPage.build(page, row)

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        task = tasks.get_task(db, actor, record_id)
        zone = actor.timezone
        overdue = task.status == "open" and task.due_at is not None and task.due_at < utcnow()
        about = _about(task)
        fields = [
            ("Due", (local_time(task.due_at, zone) or "No due date") + (" (overdue)" if overdue else "")),
            ("Assigned to", person(task.assigned_to)),
            ("About", about or "—"),
            ("Completed", local_time(task.completed_at, zone)),
            ("Created", local_time(task.created_at, zone)),
        ]
        links = {}
        if task.lead_id and actor.can("leads.view"):
            links["About"] = "lead"
        elif task.client_id and actor.can("clients.view"):
            links["About"] = "client"
        allowed = set()
        if actor.can_on("tasks.edit", task):
            allowed.add("edit" if task.status == "open" else "reopen")
            if task.status == "open":
                allowed |= {"done", "cancel"}
        if task.lead_id and actor.can("leads.view"):
            allowed.add("lead")
        if "edit" in allowed:
            allowed.add("snooze")
        values = {"title": task.title, "description": task.description, "priority": task.priority,
                  "due_at": task.due_at, "assigned_to_id": task.assigned_to_id, "lead_id": task.lead_id,
                  "client_id": task.client_id, "prospect_id": task.prospect_id,
                  "lead_label": leads.display_title(task.lead) if task.lead else None}
        priority = label(PRIORITIES, task.priority)
        status = label(TASK_STATUSES, task.status)
        return DetailView(task.id, task.title, "", fields, (), allowed,
                          {"version": task.version, "values": values, "lead_id": task.lead_id,
                           "client_id": task.client_id, "due_at": task.due_at},
                          badges=[(f"{priority} priority", tone_for(priority) or "neutral"),
                                  ("Completed" if task.status == "done" else status, tone_for(status) or "neutral")],
                          links=links, notes=text(task.description) or "No details added.")

    def build_actions(self, panel: DetailPanel) -> None:
        self.done_button = panel.add_action("Mark complete", lambda: self.set_status("done"), primary=True,
                                            icon="check")
        self.reopen_button = panel.add_action("Reopen", lambda: self.set_status("open"), primary=True,
                                              icon="refresh")
        self.edit_button = panel.add_action("Edit", self.edit_current)
        self.snooze_button = panel.add_action("Snooze", self.snooze, ghost=True)
        self.cancel_button = panel.add_action("Cancel task", lambda: self.set_status("cancelled"), ghost=True)
        self.lead_button = panel.add_action("Open lead", self.open_lead, icon="leads")
        self.lead_button.hide()

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        self.done_button.setEnabled("done" in allowed)
        self.reopen_button.setEnabled("reopen" in allowed)
        self.done_button.setVisible("reopen" not in allowed)
        self.reopen_button.setVisible("reopen" in allowed)
        self.edit_button.setEnabled("edit" in allowed)
        self.snooze_button.setEnabled("snooze" in allowed)
        self.cancel_button.setEnabled("cancel" in allowed)
        self.cancel_button.setVisible("cancel" in allowed)
        self.lead_button.setEnabled("lead" in allowed)

    def snooze(self) -> None:
        view = self.current_view()
        if view is None or "snooze" not in view.allowed or self.context.actor is None:
            return
        zone = ZoneInfo(self.context.actor.timezone)
        now = utcnow()
        due = view.data.get("due_at")
        if due is None:
            tomorrow = (now.astimezone(zone) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            new_due = tomorrow
        else:
            new_due = max(due, now) + timedelta(days=1)
        data = parse(TaskUpdate, {"due_at": new_due, "version": view.data["version"]})
        ok, _ = attempt(self, self.context, lambda db, actor: tasks.update_task(db, actor, view.id, data),
                        kind="task")
        if ok:
            self.after_change(view.id, f"Task snoozed to {local_time(new_due, self.context.actor.timezone)}")

    def open_link(self, key: str) -> None:
        view = self.current_view()
        if view is None:
            return
        if key == "lead":
            self.open_lead()
        elif key == "client" and view.data.get("client_id"):
            window = self.window()
            if hasattr(window, "open_record"):
                window.open_record("clients", str(view.data["client_id"]))

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

