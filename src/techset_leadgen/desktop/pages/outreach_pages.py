from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QWidget
from sqlalchemy.orm import Session

from techset_leadgen.database.engine import utcnow
from techset_leadgen.domain.outreach import ACTIVE_ASSIGNMENT_STATUSES, OUTREACH_EVENTS
from techset_leadgen.domain.vocabulary import ASSIGNMENT_STATUSES, PROSPECT_STATUSES, TASK_STATUSES
from techset_leadgen.errors import Conflict
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import assignments, outreach, prospects, tasks
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.services.schemas import FollowUpSchedule, OutreachRecord, parse

from techset_leadgen.desktop.forms import FieldSpec, FormDialog
from techset_leadgen.desktop.pages.prospects_page import _display_name, _status_tone, prospect_view
from techset_leadgen.desktop.records import Column, DetailPanel, DetailView, RecordPage, Row, RowPage
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import date_text, label, local_time, person, text

OUTCOME_NOTE = ("Record only what actually happened on LinkedIn. This application never sends requests or "
                "messages for you.")


def _timezone(context: AppContext) -> str:
    return context.actor.timezone if context.actor is not None else "UTC"


def record_outcome(parent: QWidget, context: AppContext, prospect_id: str, *, title: str,
                   can_complete: bool) -> bool:
    request_id = uuid.uuid4().hex
    fields = [
        FieldSpec("event_type", "What happened", "choice", options=list(OUTREACH_EVENTS.items()), required=True,
                  blank=None, span=True),
        FieldSpec("note", "Notes", "multiline",
                  hint="In your words. Leave out personal details the team does not need."),
        FieldSpec("follow_up_at", "Follow-up", "datetime", span=True,
                  hint="Needed for “Follow-up requested”. Moves the prospect's follow-up if one is already set."),
    ]
    if can_complete:
        fields.append(FieldSpec("complete", "Mark my assignment for this profile complete", "bool", span=True))

    def submit(dialog: FormDialog) -> str:
        values = dialog.values()
        complete = bool(values.pop("complete", False))
        data = parse(OutreachRecord, {**values, "prospect_id": prospect_id, "request_id": request_id})

        def work(db: Session, actor: Actor) -> str:
            event = outreach.record_event(db, actor, data)
            if complete:
                assignment = prospects.open_assignment(db, prospect_id)
                if assignment is None or assignment.status not in ACTIVE_ASSIGNMENT_STATUSES:
                    raise Conflict("This profile has no open assignment to complete.")
                assignments.complete_assignment(db, actor, assignment.id, assignment.version)
            return event.id

        return context.write("prospect", work)

    dialog = FormDialog(parent, title="Record outcome", heading=f"What happened with {title}?", note=OUTCOME_NOTE,
                        fields=fields, submit=submit, submit_text="Save outcome", timezone=_timezone(context),
                        values={"event_type": "connection_sent"})
    return bool(dialog.exec())


def schedule_follow_up(parent: QWidget, context: AppContext, prospect_id: str, *, title: str,
                       version: int | None = None, note: str | None = None) -> bool:
    request_id = uuid.uuid4().hex

    def submit(dialog: FormDialog) -> None:
        data = parse(FollowUpSchedule, {**dialog.values(), "prospect_id": prospect_id, "request_id": request_id})
        context.write("task", lambda db, actor: tasks.schedule_follow_up(db, actor, data, version=version))

    dialog = FormDialog(
        parent, title="Follow-up", heading=f"When should {title} be contacted again?",
        note="The follow-up appears under Follow-ups on the day it is due and stays until it is done or cancelled.",
        fields=[FieldSpec("due_at", "Follow up on", "datetime", required=True, span=True),
                FieldSpec("note", "What to do", "multiline")],
        values={"note": note}, submit=submit, submit_text="Save follow-up", timezone=_timezone(context))
    return bool(dialog.exec())


def open_profile(page: RecordPage, view: DetailView | None) -> None:
    url = str(view.data.get("linkedin_url") or "") if view is not None else ""
    if url and not QDesktopServices.openUrl(QUrl(url)):
        page.status_requested.emit("The LinkedIn profile could not be opened in your browser.")


class MyWorkPage(RecordPage):
    title = "My Work"
    subtitle = ("LinkedIn profiles assigned to you. Open a profile, do the outreach on LinkedIn, then record "
                "what happened.")
    noun = "assignment"
    plural = "assignments"
    columns = (
        Column("prospect", "Prospect", "prospect", strong=True),
        Column("company", "Company", muted=True),
        Column("stage", "Stage", badge=True, tone="neutral", keep=True),
        Column("status", "Assignment", "status", badge=True, keep=True),
        Column("due", "Due", "due", keep=True, alert=True),
        Column("follow_up", "Follow-up", keep=True, alert=True),
        Column("activity", "Last activity", keep=True),
    )
    default_sort = "due"

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.records.set_empty_state("Nothing assigned here",
                                     "New profiles appear when your manager assigns a batch to you.",
                                     icon="my_work")

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.due_filter = self.filter_combo(bar, "Due date", [("today", "Due today"), ("overdue", "Overdue"),
                                                              ("upcoming", "Next 7 days")], everything="Any due date")
        self.status_filter = self.filter_combo(
            bar, "Assignment status",
            [(key, ASSIGNMENT_STATUSES[key]) for key in ("assigned", "in_progress", "completed", "cancelled",
                                                         "reassigned")],
            everything="Open work")

    def list_filters(self) -> dict[str, Any]:
        filters = super().list_filters()
        if self.due_filter.currentData():
            filters["due"] = self.due_filter.currentData()
        if self.status_filter.currentData():
            filters["status"] = self.status_filter.currentData()
        return filters

    def set_filter_values(self, values: dict[str, str]) -> None:
        for combo, key in ((self.due_filter, "due"), (self.status_filter, "status")):
            combo.blockSignals(True)
            self.set_combo(combo, values.get(key))
            combo.blockSignals(False)

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        now = utcnow()
        today = _iso_today(now, actor)
        found = assignments.list_my_work(db, actor, page=request, now=now, **filters)

        def row(item: Any) -> Row:
            prospect = item.prospect
            open_ = item.status in ACTIVE_ASSIGNMENT_STATUSES
            due = date_text(item.due_on.isoformat()) if item.due_on else "No date"
            late = open_ and item.due_on is not None and item.due_on.isoformat() < today
            follow_late = prospect.next_follow_up_at is not None and prospect.next_follow_up_at < now
            colors = {**({4: "danger"} if late else {}), **({5: "danger"} if follow_late else {})}
            return Row(item.id, [
                _display_name(prospect), text(prospect.company) or "—", label(PROSPECT_STATUSES, prospect.status),
                label(ASSIGNMENT_STATUSES, item.status), due + (" (overdue)" if late else ""),
                local_time(prospect.next_follow_up_at, actor.timezone) or "None",
                local_time(prospect.last_activity_at, actor.timezone) or "Not started",
            ], tooltip=prospect.linkedin_url, emphasis="" if open_ else "muted", colors=colors)

        return RowPage.build(found, row)

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        assignment = assignments.get_assignment(db, actor, record_id)
        view = prospect_view(db, actor, assignment.prospect_id)
        mine = assignment.assignee_id == actor.user_id and assignment.status in ACTIVE_ASSIGNMENT_STATUSES
        allowed = {"open"} | ({"record", "follow_up", "complete"} if mine else set())
        follow_up = tasks.get_open_follow_up(db, actor, assignment.prospect_id) if mine else None
        view.id = assignment.id
        view.allowed = allowed
        view.fields = [("Due", date_text(assignment.due_on.isoformat()) if assignment.due_on else "No date"),
                       ("Batch", assignment.batch.name if assignment.batch else "—"), *view.fields]
        view.data.update({"assignment_version": assignment.version,
                          "follow_up_version": follow_up.version if follow_up else None,
                          "follow_up_note": follow_up.description if follow_up else None})
        view.badges = [(label(PROSPECT_STATUSES, assignment.prospect.status),
                        _status_tone(assignment.prospect.status)),
                       (label(ASSIGNMENT_STATUSES, assignment.status), "info" if mine else "neutral")]
        return view

    def build_actions(self, panel: DetailPanel) -> None:
        self.open_button = panel.add_action("Open LinkedIn", lambda: open_profile(self, self.current_view()),
                                            primary=True, icon="arrow-right")
        self.record_button = panel.add_action("Record outcome", self.record, icon="edit")
        self.follow_up_button = panel.add_action("Follow-up…", self.follow_up, icon="calendar")
        self.complete_button = panel.add_action("Mark complete", self.complete, icon="check")

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        for button, key in ((self.open_button, "open"), (self.record_button, "record"),
                            (self.follow_up_button, "follow_up"), (self.complete_button, "complete")):
            button.setEnabled(key in allowed)

    def edit_current(self) -> None:
        self.record()

    def record(self) -> None:
        view = self.current_view()
        if view is None or "record" not in view.allowed:
            return
        if record_outcome(self, self.context, view.data["prospect_id"], title=view.data["title"], can_complete=True):
            self.after_change(view.id, "Outcome recorded")

    def follow_up(self) -> None:
        view = self.current_view()
        if view is None or "follow_up" not in view.allowed:
            return
        if schedule_follow_up(self, self.context, view.data["prospect_id"], title=view.data["title"],
                              version=view.data.get("follow_up_version"), note=view.data.get("follow_up_note")):
            self.after_change(view.id, "Follow-up saved")

    def complete(self) -> None:
        view = self.current_view()
        if view is None or "complete" not in view.allowed:
            return

        def submit(dialog: FormDialog) -> None:
            reason = dialog.values().get("reason")
            self.context.write("prospect", lambda db, actor: assignments.complete_assignment(
                db, actor, view.id, view.data["assignment_version"], reason=reason))

        dialog = FormDialog(self, title="Complete assignment", heading=f"Complete the work on {view.data['title']}?",
                            note="Completing closes your assignment. Recorded outcomes and any follow-up stay.",
                            fields=[FieldSpec("reason", "Summary (optional)", "multiline")], submit=submit,
                            submit_text="Mark complete")
        if dialog.exec():
            self.after_change(view.id, "Assignment completed")

    def open_link(self, key: str) -> None:
        if key == "linkedin":
            open_profile(self, self.current_view())


def _iso_today(now: datetime, actor: Actor) -> str:
    return now.astimezone(ZoneInfo(actor.timezone)).date().isoformat()


FOLLOW_UP_VIEWS = (("today", "Due today"), ("overdue", "Overdue"), ("upcoming", "Next 7 days"),
                   ("done", "Completed"), ("cancelled", "Cancelled"))


class FollowUpsPage(RecordPage):
    title = "Follow-ups"
    subtitle = "Prospects to contact again. An overdue follow-up stays here until it is done or cancelled."
    noun = "follow-up"
    plural = "follow-ups"
    columns = (
        Column("prospect", "Follow up with", "title", strong=True),
        Column("due", "Due", "due", keep=True, alert=True),
        Column("assignee", "Responsible", "assignee", avatar=True),
        Column("stage", "Stage", badge=True, tone="neutral", keep=True),
        Column("activity", "Last activity", "activity", keep=True),
        Column("note", "What to do", muted=True),
        Column("status", "Status", "status", badge=True, keep=True),
    )
    default_sort = "due"

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.records.set_empty_state("No follow-ups here",
                                     "Follow-ups appear when someone records “Follow-up requested” or sets a date.",
                                     icon="followups")

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.due_filter = self.filter_combo(bar, "Follow-up due", list(FOLLOW_UP_VIEWS), everything="All open")
        self.whose_filter = self.filter_combo(bar, "Whose follow-ups", [("team", "Whole team")],
                                              everything="Mine")

    def update_permissions(self) -> None:
        super().update_permissions()
        actor = self.context.actor
        self.whose_filter.setVisible(actor is not None and actor.scope("tasks.view") is Scope.ALL)

    def list_filters(self) -> dict[str, Any]:
        filters = super().list_filters()
        filters["due"] = self.due_filter.currentData() or "open"
        if self.whose_filter.isVisible() and self.whose_filter.currentData():
            filters["view"] = "team"
        return filters

    def set_filter_values(self, values: dict[str, str]) -> None:
        for combo, key in ((self.due_filter, "due"), (self.whose_filter, "view")):
            combo.blockSignals(True)
            self.set_combo(combo, values.get(key))
            combo.blockSignals(False)

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        now = utcnow()
        found = tasks.list_tasks(db, actor, page=request, kind="follow_up", now=now, **filters)

        def row(task: Any) -> Row:
            prospect = task.prospect
            overdue = task.status == "open" and task.due_at is not None and task.due_at < now
            return Row(task.id, [
                _display_name(prospect) if prospect else task.title,
                local_time(task.due_at, actor.timezone) + (" (overdue)" if overdue else ""),
                person(task.assigned_to), label(PROSPECT_STATUSES, prospect.status) if prospect else "—",
                (local_time(prospect.last_activity_at, actor.timezone) or "—") if prospect else "—",
                text(task.description) or "—", label(TASK_STATUSES, task.status),
            ], emphasis="alert" if overdue else "" if task.status == "open" else "muted",
                colors={1: "danger"} if overdue else {})

        return RowPage.build(found, row)

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        task = tasks.get_task(db, actor, record_id)
        if task.kind != "follow_up" or task.prospect_id is None:
            raise Conflict("This is not a prospect follow-up.")
        view = prospect_view(db, actor, task.prospect_id)
        responsible = task.assigned_to_id == actor.user_id or actor.scope("outreach.record") is Scope.ALL
        allowed = {"open"}
        if task.status == "open" and responsible and actor.can("outreach.record"):
            allowed |= {"done", "reschedule", "cancel"}
        if "record" in view.allowed:
            allowed.add("record")
        view.id = task.id
        view.allowed = allowed
        view.fields = [("Due", local_time(task.due_at, actor.timezone)), ("Responsible", person(task.assigned_to)),
                       ("Follow-up status", label(TASK_STATUSES, task.status)), *view.fields]
        view.notes = "\n\n".join(part for part in (text(task.description), text(task.outcome) and
                                                    f"Outcome: {text(task.outcome)}") if part)
        view.data.update({"task_version": task.version, "note": task.description})
        return view

    def build_actions(self, panel: DetailPanel) -> None:
        self.done_button = panel.add_action("Mark done", self.mark_done, primary=True, icon="check")
        self.reschedule_button = panel.add_action("Reschedule", self.reschedule, icon="calendar")
        self.record_button = panel.add_action("Record outcome", self.record, icon="edit")
        self.open_button = panel.add_action("Open LinkedIn", lambda: open_profile(self, self.current_view()),
                                            icon="arrow-right")
        self.cancel_button = panel.add_action("Cancel follow-up", self.cancel, destructive=True, icon="close")

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        for button, key in ((self.done_button, "done"), (self.reschedule_button, "reschedule"),
                            (self.record_button, "record"), (self.open_button, "open"),
                            (self.cancel_button, "cancel")):
            button.setEnabled(key in allowed)

    def edit_current(self) -> None:
        self.mark_done()

    def mark_done(self) -> None:
        view = self.current_view()
        if view is None or "done" not in view.allowed:
            return

        def submit(dialog: FormDialog) -> None:
            outcome = dialog.values().get("outcome")
            self.context.write("task", lambda db, actor: tasks.complete_follow_up(
                db, actor, view.id, version=view.data["task_version"], outcome=outcome))

        dialog = FormDialog(self, title="Follow-up done", heading=f"Follow-up with {view.data['title']} done",
                            note="To record a reply, a meeting, or another outcome, use Record outcome as well.",
                            fields=[FieldSpec("outcome", "What happened (optional)", "multiline")],
                            submit=submit, submit_text="Mark done")
        if dialog.exec():
            self.after_change(view.id, "Follow-up done")

    def reschedule(self) -> None:
        view = self.current_view()
        if view is None or "reschedule" not in view.allowed:
            return
        if schedule_follow_up(self, self.context, view.data["prospect_id"], title=view.data["title"],
                              version=view.data["task_version"], note=view.data.get("note")):
            self.after_change(view.id, "Follow-up moved")

    def cancel(self) -> None:
        view = self.current_view()
        if view is None or "cancel" not in view.allowed:
            return

        def submit(dialog: FormDialog) -> None:
            reason = dialog.values().get("reason")
            self.context.write("task", lambda db, actor: tasks.cancel_follow_up(
                db, actor, view.id, version=view.data["task_version"], reason=reason))

        dialog = FormDialog(self, title="Cancel follow-up", heading=f"Cancel the follow-up with {view.data['title']}?",
                            note="Nobody will be reminded any more. The history keeps that it was cancelled.",
                            fields=[FieldSpec("reason", "Reason", "multiline")], submit=submit,
                            submit_text="Cancel follow-up")
        if dialog.exec():
            self.after_change(view.id, "Follow-up cancelled")

    def record(self) -> None:
        view = self.current_view()
        if view is None or "record" not in view.allowed:
            return
        if record_outcome(self, self.context, view.data["prospect_id"], title=view.data["title"],
                          can_complete=False):
            self.after_change(view.id, "Outcome recorded")

    def open_link(self, key: str) -> None:
        if key == "linkedin":
            open_profile(self, self.current_view())


__all__ = ["FollowUpsPage", "MyWorkPage", "record_outcome", "schedule_follow_up"]

