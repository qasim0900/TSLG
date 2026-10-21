"""User and role management, and the audit log (administrators)."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.schemas import UserAdminUpdate, UserInvite, parse
from crm.security.permissions import PERMISSIONS, ROLE_PERMISSIONS
from crm.services import audit, users
from crm.services.access import Actor
from crm.services.pagination import PageRequest
from crm.models import Activity, Client, Contact, Lead, Task, User
from crm.services import leads
from crm.vocabulary import ACCOUNT_STATUSES, LEAD_STATUSES, PRIORITIES, ROLES, TASK_STATUSES

from ..support import attempt, label, local_time, options
from ..session import AppContext
from ..forms import FieldSpec, FormDialog
from ..records import Column, DetailPanel, DetailTab, DetailView, RecordPage, Row, RowPage


def role_summary(role: str) -> str:
    granted = ROLE_PERMISSIONS.get(role, {})
    own = sorted(PERMISSIONS[p] for p, scope in granted.items() if scope.value == "own")
    text = f"{len(granted)} of {len(PERMISSIONS)} permissions"
    return text + (f"; limited to their own records for: {'; '.join(own)}" if own else "")


class CodeDialog(QDialog):
    """Shows a one-time activation or reset code once, with a copy button."""

    def __init__(self, parent: QWidget | None, *, name: str, code: str, purpose: str, hours: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("One-time code")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        action = "activate their account" if purpose == "invite" else "choose a new password"
        heading = QLabel(f"Give this code to {name}")
        heading.setObjectName("dialogHeading")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(heading)
        message = QLabel(
            f"On the {QGuiApplication.applicationDisplayName() or 'Techset LeadGen'} sign-in screen they choose "
            f"“I have an activation or password-reset code”, enter it, and {action}. The code works once, "
            f"expires in {hours} hours, "
            "and is not shown again. Share it privately (in person or by phone), not in a group chat."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        self.code_field = QLineEdit(code)
        self.code_field.setReadOnly(True)
        self.code_field.setAccessibleName("One-time code")
        self.code_field.selectAll()
        layout.addWidget(self.code_field)
        buttons = QDialogButtonBox()
        copy = QPushButton("Copy code")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(code))
        done = QPushButton("Done")
        done.setObjectName("primaryButton")
        done.clicked.connect(self.accept)
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(done, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)
        self.setMinimumWidth(520)


class UsersPage(RecordPage):
    title = "Users"
    subtitle = "Accounts in your organization. Roles decide what each person can see and change."
    noun = "user"
    plural = "users"
    columns = (
        Column("name", "Name", "name"),
        Column("email", "Email", "email"),
        Column("role", "Role", "role"),
        Column("status", "Status", badge=True),
        Column("last_login", "Last sign-in", "last_login", keep=True),
    )
    default_sort = "name"
    create_permission = "users.manage"

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.new_button.setText("Invite user")

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.active_filter = self.filter_combo(bar, "Account status", [("active", "Active only")],
                                               everything="Active and inactive")

    def list_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {"include_inactive": self.active_filter.currentData() != "active"}
        if self.search.text().strip():
            filters["q"] = self.search.text().strip()
        return filters

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        zone = actor.timezone
        page = users.list_users(db, actor, page=request, **filters)
        return RowPage.build(page, lambda user: Row(str(user.id), [
            user.full_name + (" (you)" if user.id == actor.user_id else ""), user.email, label(ROLES, user.role),
            _status(user), local_time(user.last_login_at, zone) or "Never",
        ], emphasis="" if user.is_active else "muted"))

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        user = users.get_user(db, actor, record_id)
        zone = actor.timezone
        fields = [
            ("Email", user.email),
            ("Role", label(ROLES, user.role)),
            ("What the role allows", role_summary(user.role)),
            ("Status", _status(user)),
            ("Time zone", user.timezone),
            ("Last sign-in", local_time(user.last_login_at, zone) or "Never"),
            ("Created", local_time(user.created_at, zone)),
        ]
        granted = ROLE_PERMISSIONS.get(user.role, {})
        tabs = [DetailTab("Permissions", ("Permission", "Scope"), [
            [PERMISSIONS[name], "All records" if scope.value == "all" else "Own records only"]
            for name, scope in sorted(granted.items(), key=lambda item: PERMISSIONS[item[0]])
        ])]
        allowed = set()
        if actor.can("users.manage"):
            allowed.add("edit")
            if user.is_active:
                allowed.add("code")
        return DetailView(str(user.id), user.full_name, label(ROLES, user.role), fields, tabs, allowed, {
            "values": {"full_name": user.full_name, "role": user.role, "is_active": user.is_active},
            "invited": user.password_hash is None,
        })

    def build_actions(self, panel: DetailPanel) -> None:
        self.edit_button = panel.add_action("Edit role or status", self.edit_current, primary=True)
        self.code_button = panel.add_action("Issue sign-in code", self.issue_code)

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        self.edit_button.setEnabled("edit" in allowed)
        self.code_button.setEnabled("code" in allowed)
        if view is not None:
            self.code_button.setText("Issue activation code" if view.data["invited"] else "Issue password-reset code")

    def create_record(self) -> None:
        settings = self.context.settings

        def submit(dialog: FormDialog) -> tuple[str, str, str]:
            data = parse(UserInvite, dialog.values())

            def work(db: Session, actor: Actor) -> tuple[str, str, str]:
                user, code = users.invite_user(db, actor, settings, data)
                return str(user.id), user.full_name, code

            return self.context.write("user", work)

        dialog = FormDialog(
            self, title="Invite user", heading="Invite a colleague",
            note="The account is created without a password. You receive a one-time code to give them; "
                 "they choose their own password with it.",
            fields=[
                FieldSpec("full_name", "Full name", required=True),
                FieldSpec("email", "Work email", required=True),
                FieldSpec("role", "Role", "choice", options(ROLES), required=True, blank=None,
                          hint="Roles can be changed later. A role change signs the user out everywhere."),
            ],
            values={"role": "bdr"}, submit=submit, submit_text="Create account", columns=1,
        )
        if dialog.exec():
            user_id, name, code = dialog.result_value
            CodeDialog(self, name=name, code=code, purpose="invite", hours=settings.token_ttl_hours).exec()
            self.after_change(user_id, f"Account created for {name}")

    def edit_current(self) -> None:
        view = self.current_view()
        if view is None or "edit" not in view.allowed:
            return

        def submit(dialog: FormDialog) -> None:
            changes = dialog.changed()
            if not changes:
                return
            data = parse(UserAdminUpdate, changes)
            self.context.write("user", lambda db, actor: users.update_user(db, actor, view.id, data))

        dialog = FormDialog(
            self, title="Edit user", heading=f"Edit {view.title}",
            note="Changing the role or deactivating the account ends all of this user's sessions immediately.",
            fields=[
                FieldSpec("full_name", "Full name", required=True),
                FieldSpec("role", "Role", "choice", options(ROLES), required=True, blank=None),
                FieldSpec("is_active", "Account is active (can sign in)", "bool"),
            ],
            values=view.data["values"], submit=submit, submit_text="Save changes", columns=1,
        )
        if dialog.exec():
            self.after_change(view.id, "User saved")

    def issue_code(self) -> None:
        view = self.current_view()
        if view is None or "code" not in view.allowed:
            return
        settings = self.context.settings
        ok, issued = attempt(self, self.context,
                             lambda db, actor: users.issue_access_code(db, actor, settings, view.id), kind="user")
        if ok and issued is not None:
            code, purpose = issued
            CodeDialog(self, name=view.title, code=code, purpose=purpose, hours=settings.token_ttl_hours).exec()
            self.after_change(view.id, "Code issued")


def _status(user: Any) -> str:
    if not user.is_active:
        return "Inactive"
    return "Invited (no password yet)" if user.password_hash is None else "Active"


_ENTITY_TYPES = {"client": "Clients", "contact": "Contacts", "lead": "Leads", "task": "Tasks",
                 "activity": "Activities", "user": "Users and sign-ins", "organization": "Organization",
                 "data": "Imports, exports, and clearing", "marketing_spend": "Marketing spend"}


# Plain-language names for audit actions; the code stays visible in the entry's details.
ACTION_LABELS = {
    "auth.login": "Signed in",
    "auth.login_failed": "Sign-in failed",
    "auth.logout": "Signed out",
    "auth.password_changed": "Password changed",
    "auth.password_reset": "Password reset with a code",
    "user.invited": "User invited",
    "user.invite_accepted": "Invitation accepted",
    "user.invite_code_issued": "Activation code issued",
    "user.password_reset_code_issued": "Password-reset code issued",
    "user.updated": "User changed",
    "user.profile_updated": "Own profile changed",
    "users.carried_over": "Accounts carried over",
    "organization.created": "Organization set up",
    "organization.updated": "Organization changed",
    "database.backed_up": "Database backed up",
    "client.created": "Client added",
    "client.updated": "Client changed",
    "client.deleted": "Client deleted",
    "client.assigned": "Client owner changed",
    "client.duplicates_merged": "Duplicate clients merged",
    "contact.created": "Contact added",
    "contact.updated": "Contact changed",
    "contact.deleted": "Contact removed",
    "lead.created": "Lead added",
    "lead.updated": "Lead changed",
    "lead.status_changed": "Lead stage changed",
    "lead.assigned": "Lead owner changed",
    "task.created": "Task added",
    "task.updated": "Task changed",
    "task.status_changed": "Task status changed",
    "activity.created": "Activity logged",
    "marketing_spend.created": "Marketing spend added",
    "marketing_spend.updated": "Marketing spend changed",
    "marketing_spend.deleted": "Marketing spend deleted",
    "data.imported": "Data imported",
    "data.exported": "Report exported",
    "data.cleared_sales": "All sales cleared",
    "data.cleared_leads": "All leads cleared",
    "data.cleared_clients": "All clients cleared",
}

_RECORD_KINDS = {"client": "Client", "contact": "Contact", "lead": "Lead", "task": "Task", "activity": "Activity",
                 "user": "User", "organization": "Organization", "data": "Data", "marketing_spend": "Marketing spend"}
# Change keys that hold another record's ID: (record kind, what to call it).
_REFERENCES = {"owner_id": ("user", "owner"), "assigned_to_id": ("user", "assigned to"),
               "admin_user_id": ("user", "administrator"), "client_id": ("client", "client"),
               "lead_id": ("lead", "lead"), "contact_id": ("contact", "contact")}
_VOCABULARIES: dict[str, dict[str, str]] = {"priority": PRIORITIES, "role": ROLES, "account_status": ACCOUNT_STATUSES}
_STATUS_VOCABULARIES = {"lead": LEAD_STATUSES, "task": TASK_STATUSES}
_REASONS = {"bad_password": "wrong password", "inactive": "account inactive"}
_NAMERS: dict[str, tuple[Any, Callable[[Any], str]]] = {
    "user": (User, lambda user: user.full_name),
    "client": (Client, lambda client: client.name or client.id),
    "contact": (Contact, lambda contact: contact.full_name),
    "lead": (Lead, leads.display_title),
    "task": (Task, lambda task: task.title),
    "activity": (Activity, lambda activity: activity.subject or activity.activity_type.capitalize()),
}


def action_label(action: str) -> str:
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]
    return action.replace(".", " ").replace("_", " ").strip().capitalize()


def actions_matching(text: str) -> list[str]:
    """Action codes whose name or code contains ``text`` (so "stage" finds "Lead stage changed")."""
    wanted = text.strip().casefold()
    return [code for code, name in ACTION_LABELS.items() if wanted in name.casefold() or wanted in code]


def record_names(db: Session, entries: Sequence[Any]) -> dict[tuple[str, str], str]:
    """Names of the records and people the given entries mention, looked up together."""
    wanted: dict[str, set[str]] = {}
    for entry in entries:
        if entry.entity_type in _NAMERS and entry.entity_id:
            wanted.setdefault(entry.entity_type, set()).add(str(entry.entity_id))
        for key, value in (entry.changes or {}).items():
            if key in _REFERENCES:
                for item in value if isinstance(value, list) else [value]:
                    if item:
                        wanted.setdefault(_REFERENCES[key][0], set()).add(str(item))
    names: dict[tuple[str, str], str] = {}
    for kind, ids in wanted.items():
        model, namer = _NAMERS[kind]
        for record in db.scalars(select(model).where(model.id.in_(sorted(ids)))):
            names[(kind, str(record.id))] = namer(record)
    return names


def _record_text(entry: Any, names: dict[tuple[str, str], str]) -> str:
    kind = _RECORD_KINDS.get(entry.entity_type or "", (entry.entity_type or "").replace("_", " ").capitalize())
    if not entry.entity_id or entry.entity_type in ("organization", "data"):
        return kind
    name = names.get((entry.entity_type, str(entry.entity_id)))
    return f"{kind}: {name}" if name else f"{kind} {str(entry.entity_id)[:8]} (deleted)"


def _changes_summary(changes: dict[str, Any] | None, *, entity_type: str | None = None,
                     names: dict[tuple[str, str], str] | None = None, zone: str = "UTC") -> str:
    if not changes:
        return ""
    names = names or {}

    def shown(key: str, value: Any) -> str:
        if key in _REFERENCES:
            kind = _REFERENCES[key][0]
            if not value:
                return "Unassigned" if kind == "user" else "—"
            return names.get((kind, str(value))) or f"{str(value)[:8]} (deleted)"
        vocabulary = _STATUS_VOCABULARIES.get(entity_type or "") if key == "status" else _VOCABULARIES.get(key)
        if vocabulary and isinstance(value, str):
            return vocabulary.get(value, value)
        if key == "reason" and isinstance(value, str):
            return _REASONS.get(value, value)
        if key.endswith("_at") and isinstance(value, str):
            try:
                return local_time(datetime.fromisoformat(value), zone) or value
            except ValueError:
                return value
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return _short(value)

    parts = []
    for key, value in changes.items():
        field = _REFERENCES[key][1] if key in _REFERENCES else key.replace("_", " ")
        if isinstance(value, list) and len(value) == 2:
            parts.append(f"{field}: {shown(key, value[0])} → {shown(key, value[1])}")
        else:
            parts.append(f"{field}: {shown(key, value)}")
    summary = "; ".join(parts)
    return summary if len(summary) <= 140 else summary[:139] + "…"


def _short(value: Any) -> str:
    if value is None or value == "":
        return "—"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 40 else text[:39] + "…"


class AuditPage(RecordPage):
    title = "Audit log"
    subtitle = "Who changed what, when, and from which computer. Entries cannot be edited or deleted here."
    noun = "entry"
    plural = "entries"
    columns = (
        Column("created", "When", "created", keep=True),
        Column("who", "Who"),
        Column("action", "Action", alert=True, keep=True),
        Column("record", "Record", tip="The record the action changed"),
        Column("changes", "Changes", tip="What changed: old → new"),
        Column("computer", "Computer", tip="The computer the action came from"),
    )
    default_sort = "-created"

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.search.setPlaceholderText("Filter by action, e.g. stage changed, signed in")
        self.search.setAccessibleName("Filter by action")
        self.search.setToolTip("Matches the action's name, for example \"Lead stage changed\" or \"Sign-in failed\"")

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.entity_filter: QComboBox = self.filter_combo(bar, "Record type", list(_ENTITY_TYPES.items()),
                                                          everything="All record types")

    def update_permissions(self) -> None:
        self.new_button.hide()

    def list_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.entity_filter.currentData():
            filters["entity_type"] = self.entity_filter.currentData()
        if self.search.text().strip():
            filters["actions"] = actions_matching(self.search.text()) or [self.search.text().strip()]
        return filters

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        zone = actor.timezone
        page = audit.list_entries(db, actor, page=request, **filters)
        names = record_names(db, page.items)
        return RowPage.build(page, lambda entry: Row(str(entry.id), [
            local_time(entry.created_at, zone), entry.actor.full_name if entry.actor else "System / sign-in",
            action_label(entry.action), _record_text(entry, names),
            _changes_summary(entry.changes, entity_type=entry.entity_type, names=names, zone=zone),
            entry.client_host or "",
        ], emphasis="alert" if entry.action == "auth.login_failed" else ""))

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        entry = audit.get_entry(db, actor, record_id)
        names = record_names(db, [entry])
        fields = [
            ("When", local_time(entry.created_at, actor.timezone)),
            ("Who", entry.actor.full_name if entry.actor else "System / sign-in"),
            ("Action", f"{action_label(entry.action)} ({entry.action})"),
            ("Record", _record_text(entry, names)),
            ("Record ID", entry.entity_id or ""),
            ("Summary", _changes_summary(entry.changes, entity_type=entry.entity_type, names=names,
                                         zone=actor.timezone)),
            ("Computer", entry.client_host or ""),
            ("Changes", json.dumps(entry.changes, indent=2, ensure_ascii=False) if entry.changes else ""),
        ]
        return DetailView(record_id, action_label(entry.action), local_time(entry.created_at, actor.timezone), fields)

    def create_record(self) -> None:
        return


__all__ = ["AuditPage", "CodeDialog", "UsersPage"]
