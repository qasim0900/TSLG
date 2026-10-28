"""Record workflows shared by the Leads, Clients, Tasks, and Dashboard screens.

Each function opens the dialog for one job (edit a lead, move it to another
stage, assign it, log an activity, manage a contact) and saves through the
business services, which validate, check permissions, and audit the change.
They return whether something was saved so the calling screen can refresh.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QVBoxLayout, QWidget
from sqlalchemy.orm import Session

from techset_leadgen.errors import Conflict, ValidationFailed
from techset_leadgen.services.schemas import (
    ActivityCreate,
    Assignment,
    BulkAssignment,
    ContactCreate,
    ContactUpdate,
    LeadCreate,
    LeadTransition,
    LeadUpdate,
    parse,
)
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import activities, clients, contacts, leads, tasks, users
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.domain.vocabulary import ACTIVITY_TYPES, LEAD_STATUSES, PRIORITIES, REASON_REQUIRED, TASK_STATUSES
from techset_leadgen.domain.source_labels import SOURCE_LABELS

from techset_leadgen.desktop.dialogs import ask_confirmation
from techset_leadgen.desktop.forms import FieldSpec, FormDialog
from techset_leadgen.desktop.modal import ModalDialog
from techset_leadgen.desktop.records import DetailPanel, DetailTab, DetailView
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import attempt, label, local_time, options, person, text

ACTIVITY_COLUMNS = ("When", "Type", "Subject", "By", "Notes")
REASON_LABELS = {"qualified": "Why is this lead qualified?", "lost": "Why was this lead lost?"}


def user_options(context: AppContext, parent: QWidget | None, *, permission: str | None = None
                 ) -> list[tuple[str, str]] | None:
    """Active users as ``[(id, name)]``. Without ``permission`` (assigning to others),
    only the signed-in user is offered; the services enforce the same rule."""
    ok, people = attempt(parent, context, lambda db, actor: [
        (user.id, f"{user.full_name}{' (you)' if user.id == actor.user_id else ''}")
        for user in users.assignable_users(db, actor)
        if permission is None or actor.can(permission) or user.id == actor.user_id
    ])
    return people if ok else None


def client_options(context: AppContext, parent: QWidget | None) -> list[tuple[str, str]] | None:
    ok, found = attempt(parent, context, lambda db, actor: clients.choices(db, actor))
    return found if ok else None


def source_options(current: str | None = None) -> list[tuple[str, str]]:
    choices = list(SOURCE_LABELS.items())
    if current and current not in SOURCE_LABELS:
        choices.insert(0, (current, current.replace("_", " ").title()))
    return choices


def activity_rows(db: Session, actor: Actor, *, timezone: str, **subject: Any) -> list[list[str]]:
    return [[local_time(item.occurred_at, timezone), ACTIVITY_TYPES.get(item.activity_type, item.activity_type),
             item.subject, item.created_by.full_name if item.created_by else "", item.body or ""]
            for item in activities.for_subject(db, actor, **subject)]


def log_activity(parent: QWidget, context: AppContext, *, heading: str, client_id: str | None = None,
                 lead_id: str | None = None) -> bool:
    """Record a call, email, meeting, or note that already happened."""
    zone = context.actor.timezone if context.actor else "UTC"

    def submit(dialog: FormDialog) -> None:
        values = dialog.values()
        data = parse(ActivityCreate, {"client_id": client_id, "lead_id": lead_id, **values})
        context.write("activity", lambda db, actor: activities.create_activity(db, actor, data))

    dialog = FormDialog(
        parent, title="Log activity", heading=heading,
        note="Record something that already happened. To plan future work, add a follow-up task instead.",
        fields=[
            FieldSpec("activity_type", "Type", "choice", options(ACTIVITY_TYPES), required=True, blank=None),
            FieldSpec("occurred_at", "When", "datetime", hint="Leave unset for now."),
            FieldSpec("subject", "Subject", required=True, span=True),
            FieldSpec("body", "Notes", "multiline"),
        ],
        values={"activity_type": "call"}, submit=submit, submit_text="Log activity", timezone=zone,
    )
    return bool(dialog.exec())


# --- leads ----------------------------------------------------------------------


@dataclass
class LeadSnapshot:
    id: str
    title: str
    status: str
    version: int
    view: DetailView
    values: dict[str, Any] = field(default_factory=dict)
    transitions: list[str] = field(default_factory=list)


def load_lead(db: Session, actor: Actor, lead_id: str) -> LeadSnapshot:
    lead = leads.get_lead(db, actor, lead_id)
    zone = actor.timezone
    title = leads.display_title(lead)
    fields = [
        ("Stage", label(LEAD_STATUSES, lead.status)),
        ("Client", lead.client.name if lead.client else "Not linked"),
        ("Owner", person(lead.owner)),
        ("Priority", label(PRIORITIES, lead.priority)),
        ("Source", label(SOURCE_LABELS, lead.source)),
        ("Lead date", lead.created_on),
        ("Meeting", text(lead.meeting_date) or "None scheduled"),
        ("Next follow-up", local_time(lead.next_follow_up_at, zone) or "None scheduled"),
        ("Last activity", local_time(lead.last_activity_at, zone)),
        ("Notes", text(lead.notes)),
    ]
    if lead.qualification_reason:
        fields.append(("Why qualified", lead.qualification_reason))
    if lead.lost_reason:
        fields.append(("Why lost", lead.lost_reason))
    fields += [("Lead ID", lead.id), ("Source record", text(lead.external_id))]
    timeline = [[local_time(entry.occurred_at, zone), entry.kind.replace("_", " ").capitalize(), entry.title,
                 text(entry.actor_name), text(entry.body)] for entry in leads.timeline(db, actor, lead)]
    tabs = [DetailTab("Timeline", ("When", "Type", "What", "By", "Details"), timeline,
                      "No activity yet. Log a call or add a follow-up.")]
    if actor.can("tasks.view"):
        view = "team" if actor.scope("tasks.view") is Scope.ALL else "mine"
        found = tasks.list_tasks(db, actor, page=PageRequest(page_size=100), view=view, due="all", lead_id=lead.id)
        tabs.append(DetailTab("Tasks", ("Task", "Due", "Status", "Assigned to"), [
            [task.title, local_time(task.due_at, zone), label(TASK_STATUSES, task.status), person(task.assigned_to)]
            for task in found.items
        ], "No tasks for this lead."))
    transitions = leads.allowed_transitions(actor, lead)
    allowed = set()
    if actor.can_on("leads.edit", lead):
        allowed.add("edit")
    if transitions:
        allowed.add("stage")
    if actor.can_on("leads.assign", lead) or (lead.owner_id is None and actor.can("leads.edit")):
        allowed.add("assign")  # anyone who works leads may take an unassigned one
    if actor.can("activities.create"):
        allowed.add("activity")
    if actor.can("tasks.create"):
        allowed.add("task")
    subtitle = " · ".join(part for part in (label(LEAD_STATUSES, lead.status),
                                            lead.client.name if lead.client else None,
                                            label(SOURCE_LABELS, lead.source)) if part)
    values = {"title": lead.title or title, "client_id": lead.client_id, "source": lead.source,
              "meeting_date": lead.meeting_date, "owner_id": lead.owner_id, "priority": lead.priority,
              "notes": lead.notes}
    return LeadSnapshot(lead.id, title, lead.status, lead.version,
                        DetailView(lead.id, title, subtitle, fields, tabs, allowed, {"owner_id": lead.owner_id}),
                        values, transitions)


def _lead_fields(people: list[tuple[str, str]], client_choices: list[tuple[str, str]],
                 current_source: str | None) -> list[FieldSpec]:
    return [
        FieldSpec("title", "Lead title", required=True, span=True, placeholder="e.g. Customer portal rebuild"),
        FieldSpec("client_id", "Client", "choice", client_choices, blank="Not linked yet", searchable=True,
                  hint="Link the client once you know who the lead is."),
        FieldSpec("source", "Source", "choice", source_options(current_source), required=True, blank=None),
        FieldSpec("priority", "Priority", "choice", options(PRIORITIES), blank=None),
        FieldSpec("owner_id", "Owner", "choice", people, blank="Unassigned"),
        FieldSpec("meeting_date", "Meeting date", "date"),
        FieldSpec("notes", "Notes", "multiline"),
    ]


def lead_form(parent: QWidget, context: AppContext, *, lead: LeadSnapshot | None = None,
              client_id: str | None = None) -> str | None:
    """Create a lead (``lead`` is None) or edit one. Returns the lead ID when saved."""
    people = user_options(context, parent, permission="leads.assign")
    client_choices = client_options(context, parent)
    if people is None or client_choices is None or context.actor is None:
        return None
    if lead is None:
        def submit(dialog: FormDialog) -> str:
            values = {key: value for key, value in dialog.values().items() if value is not None}
            data = parse(LeadCreate, values)
            try:
                return context.write("lead", lambda db, actor: leads.create_lead(db, actor, data).id)
            except Conflict as exc:
                if exc.details.get("duplicate") != "lead" or not ask_confirmation(
                    dialog, title="Possible duplicate", heading="This client already has an open lead",
                    message=f"“{exc.details.get('existing_title', '')}” is still open. Add another lead anyway?",
                    confirm_text="Add anyway",
                ):
                    raise
            again = parse(LeadCreate, {**values, "allow_duplicate": True})
            return context.write("lead", lambda db, actor: leads.create_lead(db, actor, again).id)

        dialog = FormDialog(parent, title="Lead", heading="New lead", submit=submit, submit_text="Add lead",
                            timezone=context.actor.timezone, fields=_lead_fields(people, client_choices, None),
                            values={"client_id": client_id, "priority": "medium", "source": "manual_import",
                                    "owner_id": context.actor.user_id})
    else:
        def submit(dialog: FormDialog) -> str:
            changes = dialog.changed()
            if changes:
                data = parse(LeadUpdate, {**changes, "version": lead.version})
                context.write("lead", lambda db, actor: leads.update_lead(db, actor, lead.id, data))
            return lead.id

        dialog = FormDialog(parent, title="Lead", heading=f"Edit {lead.title}", submit=submit,
                            submit_text="Save changes", timezone=context.actor.timezone,
                            fields=_lead_fields(people, client_choices, lead.values.get("source")),
                            values=lead.values)
    if dialog.exec():
        return str(dialog.result_value)
    return None


def change_stage(parent: QWidget, context: AppContext, lead: LeadSnapshot) -> bool:
    if not lead.transitions:
        return False

    def submit(dialog: FormDialog) -> None:
        target = dialog.value("status")
        data = parse(LeadTransition, {"status": target, "reason": dialog.value("reason"), "version": lead.version})
        meeting = dialog.value("meeting_date") if target == "meeting" else None
        context.write("lead", lambda db, actor: leads.transition(db, actor, lead.id, data, meeting_date=meeting))

    dialog = FormDialog(
        parent, title="Change stage", heading=f"Move “{lead.title}” on from {LEAD_STATUSES[lead.status]}",
        note="Only the moves allowed from the current stage are listed. Qualifying a lead or marking it Lost "
             "needs a reason, which is kept with the lead's history.",
        fields=[
            FieldSpec("status", "New stage", "choice", [(key, LEAD_STATUSES[key]) for key in lead.transitions],
                      required=True, blank=None),
            FieldSpec("meeting_date", "Meeting date", "date"),
            FieldSpec("reason", "Reason", "multiline"),
        ],
        values={"meeting_date": lead.values.get("meeting_date")}, submit=submit, submit_text="Change stage",
        columns=1,
    )

    dialog.on_change("status", _adapt_stage_form)
    _adapt_stage_form(dialog, dialog.value("status"))
    return bool(dialog.exec())


def _adapt_stage_form(dialog: FormDialog, status: Any) -> None:
    required = status in REASON_REQUIRED
    dialog.set_label("reason", REASON_LABELS.get(status, "Note (optional)") + (" *" if required else ""))
    dialog.set_visible("meeting_date", status == "meeting")


def assign_leads(parent: QWidget, context: AppContext, lead_ids: Sequence[str], *, current_owner: str | None = None,
                 version: int | None = None) -> int:
    """Assign one lead (``version`` given) or several at once. Returns how many were saved."""
    people = user_options(context, parent, permission="leads.assign")
    if people is None or not lead_ids:
        return 0
    count = len(lead_ids)

    def submit(dialog: FormDialog) -> int:
        owner = dialog.value("owner_id")
        if count == 1 and version is not None:
            data = parse(Assignment, {"owner_id": owner, "version": version})
            context.write("lead", lambda db, actor: leads.assign(db, actor, lead_ids[0], data.owner_id, data.version))
            return 1
        try:
            bulk = parse(BulkAssignment, {"lead_ids": list(lead_ids), "owner_id": owner})
        except ValidationFailed as exc:
            raise ValidationFailed(exc.fields.get("lead_ids", exc.message)) from exc
        return context.write("lead", lambda db, actor: leads.bulk_assign(db, actor, bulk))

    heading = "Assign lead" if count == 1 else f"Assign {count} selected leads"
    note = "The owner sees the lead under “My leads”." if count == 1 else \
        "All selected leads change owner together, or none do."
    dialog = FormDialog(parent, title="Assign", heading=heading, note=note, columns=1, submit=submit,
                        submit_text="Assign", values={"owner_id": current_owner},
                        fields=[FieldSpec("owner_id", "Owner", "choice", people, blank="Unassigned")])
    return int(dialog.result_value or 0) if dialog.exec() else 0


class LeadDialog(ModalDialog):
    """One lead: details, timeline, and tasks, with the actions the user's role allows."""

    def __init__(self, parent: QWidget | None, context: AppContext, lead_id: str) -> None:
        super().__init__(parent)
        self.context = context
        self.lead_id = lead_id
        self.changed = False
        self.snapshot: LeadSnapshot | None = None
        self.setWindowTitle("Lead")
        self.setModal(True)
        self.resize(820, 640)
        self.setMinimumSize(560, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        self.panel = DetailPanel(self)
        self.edit_button = self.panel.add_action("Edit", self.edit, primary=True)
        self.stage_button = self.panel.add_action("Change stage…", self.change_stage)
        self.assign_button = self.panel.add_action("Assign…", self.assign)
        self.task_button = self.panel.add_action("Add follow-up", self.add_follow_up)
        self.activity_button = self.panel.add_action("Log activity", self.log_activity)
        layout.addWidget(self.panel, 1)
        buttons = QDialogButtonBox()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addButton(close, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)
        self.reload()

    def reload(self) -> bool:
        ok, snapshot = attempt(self, self.context, lambda db, actor: load_lead(db, actor, self.lead_id))
        if not ok or snapshot is None:
            self.panel.clear("This lead is no longer available.")
            for button in (self.edit_button, self.stage_button, self.assign_button, self.task_button,
                           self.activity_button):
                button.setEnabled(False)
            return False
        self.snapshot = snapshot
        self.setWindowTitle(f"Lead — {snapshot.title}")
        self.panel.show_view(snapshot.view)
        allowed = snapshot.view.allowed
        for button, key in ((self.edit_button, "edit"), (self.stage_button, "stage"), (self.assign_button, "assign"),
                            (self.task_button, "task"), (self.activity_button, "activity")):
            button.setEnabled(key in allowed)
        return True

    def _after(self, saved: Any) -> None:
        if saved:
            self.changed = True
            self.reload()

    def edit(self) -> None:
        if self.snapshot is not None:
            self._after(lead_form(self, self.context, lead=self.snapshot))

    def change_stage(self) -> None:
        if self.snapshot is not None:
            self._after(change_stage(self, self.context, self.snapshot))

    def assign(self) -> None:
        if self.snapshot is not None:
            self._after(assign_leads(self, self.context, [self.snapshot.id],
                                     current_owner=self.snapshot.view.data.get("owner_id"),
                                     version=self.snapshot.version))

    def add_follow_up(self) -> None:
        if self.snapshot is not None:
            from techset_leadgen.desktop.pages.tasks_page import create_task

            self._after(create_task(self, self.context, lead_id=self.snapshot.id,
                                    title=f"Follow up: {self.snapshot.title}"))

    def log_activity(self) -> None:
        if self.snapshot is not None:
            self._after(log_activity(self, self.context, heading=f"Log activity for “{self.snapshot.title}”",
                                     lead_id=self.snapshot.id))


def open_lead(parent: QWidget, context: AppContext, lead_id: str) -> bool:
    """Show a lead; returns True if anything was changed while it was open."""
    dialog = LeadDialog(parent, context, lead_id)
    dialog.exec()
    return dialog.changed


# --- contacts -------------------------------------------------------------------


def contact_form(parent: QWidget, context: AppContext, *, client_id: str,
                 contact: dict[str, Any] | None = None) -> bool:
    """Add a person to a client, or edit one (``contact`` holds its current values and version)."""
    sensitive = context.can("clients.view_sensitive")
    fields = [
        FieldSpec("first_name", "First name", required=True),
        FieldSpec("last_name", "Last name"),
        FieldSpec("job_title", "Job title", span=True),
    ]
    if sensitive:
        fields += [FieldSpec("email", "Email", hint="Each email can belong to one contact."),
                   FieldSpec("phone", "Phone", placeholder="+44 20 7946 0000")]
    fields += [
        FieldSpec("do_not_contact", "Do not contact this person", "bool", span=True),
        FieldSpec("suppression_reason", "Reason for do-not-contact", span=True),
        FieldSpec("notes", "Notes", "multiline"),
    ]

    def submit(dialog: FormDialog) -> None:
        if contact is None:
            values = {key: value for key, value in dialog.values().items() if value is not None}
            data = parse(ContactCreate, {**values, "client_id": client_id})
            context.write("client", lambda db, actor: contacts.create_contact(db, actor, data))
            return
        changes = dialog.changed()
        if changes:
            update = parse(ContactUpdate, {**changes, "version": contact["version"]})
            context.write("client", lambda db, actor: contacts.update_contact(db, actor, contact["id"], update))

    values = dict(contact or {})
    if not sensitive:
        values.pop("email", None)
        values.pop("phone", None)
    dialog = FormDialog(parent, title="Contact", heading="New contact" if contact is None else
                        f"Edit {contact.get('full_name', 'contact')}", fields=fields, values=values, submit=submit,
                        submit_text="Add contact" if contact is None else "Save changes")
    dialog.set_visible("suppression_reason", bool(values.get("do_not_contact")))
    dialog.on_change("do_not_contact", lambda form, on: form.set_visible("suppression_reason", bool(on)))
    return bool(dialog.exec())


def delete_contact(parent: QWidget, context: AppContext, contact_id: str, name: str) -> bool:
    if not ask_confirmation(parent, title="Remove contact", heading=f"Remove {name}?",
                            message="The person is removed from this client. Activities logged with them are kept.",
                            confirm_text="Remove contact", destructive=True):
        return False
    ok, _ = attempt(parent, context, lambda db, actor: contacts.delete_contact(db, actor, contact_id), kind="client")
    return ok


__all__ = [
    "ACTIVITY_COLUMNS", "LeadDialog", "LeadSnapshot", "activity_rows", "assign_leads", "change_stage",
    "client_options", "contact_form", "delete_contact", "lead_form", "load_lead", "log_activity", "open_lead",
    "source_options", "user_options",
]
