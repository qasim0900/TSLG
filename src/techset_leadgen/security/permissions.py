"""Role-based permissions with ownership scopes, for the whole application.

Each role maps a permission to a scope:

* ``all`` – any record;
* ``own`` – only records the user owns (see ``crm.services.access.owns``).

A permission missing from a role is denied. These checks run in the service
layer (``crm.services``), so every path that changes data is covered; the
screens only hide or disable controls as a convenience.
"""

from __future__ import annotations

from enum import StrEnum


class Scope(StrEnum):
    ALL = "all"
    OWN = "own"


PERMISSIONS: dict[str, str] = {
    "org.manage": "Manage organization settings and back up the database",
    "users.manage": "Invite users, change roles, activate and deactivate accounts",
    "users.view": "View the user directory",
    "audit.view": "View the audit log",
    "sales.view": "View sales analytics and the dashboard",
    "clients.view": "View clients",
    "clients.view_sensitive": "Reveal tax IDs, emails, and phone numbers",
    "clients.create": "Add clients",
    "clients.edit": "Edit clients and their contacts",
    "clients.assign": "Assign client owners",
    "clients.delete": "Delete clients (and their sales)",
    "clients.merge": "Merge duplicate clients",
    "leads.view": "View leads",
    "leads.create": "Add leads",
    "leads.edit": "Edit leads and move them between stages",
    "leads.qualify": "Mark leads Qualified or Lost, or move them out of those stages",
    "leads.assign": "Assign lead owners (including several at once)",
    "activities.create": "Log calls, emails, meetings, and notes",
    "tasks.view": "View tasks",
    "tasks.create": "Create tasks and follow-ups",
    "tasks.edit": "Edit, complete, and cancel tasks",
    "tasks.assign": "Assign tasks to other users",
    "marketing.manage": "Add, correct, and delete marketing spend",
    "data.import": "Import sales, leads, and marketing spend files",
    "data.export": "Export reports",
    "data.clear": "Clear all sales, clients, or leads",
    "prospects.view": "View LinkedIn prospects",
    "prospects.create": "Add and import LinkedIn prospects",
    "prospects.edit": "Edit prospect details",
    "assignments.manage": "Create daily assignment batches, assign, reassign, and cancel outreach work",
    "outreach.record": "Record outreach outcomes and complete assignments",
    "team.view": "View team workload and performance",
    "archive.view": "Open the retired sales, lead, and client analytics",
    "meetings.view": "View scheduled meetings",
    "meetings.create": "Schedule meetings",
    "meetings.edit": "Edit and complete meetings",
    "meetings.cancel": "Cancel meetings",
}

A, O = Scope.ALL, Scope.OWN

_READ = {"sales.view": A, "clients.view": A, "leads.view": A}

# Outreach team members: they see and work the prospects assigned to them.
_OUTREACH_MEMBER = {
    "prospects.view": O,
    "prospects.edit": O,
    "outreach.record": O,
}

_FRONT_LINE = {  # business development reps and account executives
    **_READ,
    **_OUTREACH_MEMBER,
    "clients.view_sensitive": A,
    "clients.create": A,
    "clients.edit": O,
    "leads.create": A,
    "leads.edit": O,
    "leads.qualify": O,
    "activities.create": A,
    "tasks.view": O,
    "tasks.create": A,
    "tasks.edit": O,
    "meetings.view": O,
    "meetings.create": O,
    "meetings.edit": O,
    "meetings.cancel": O,
}

ROLE_PERMISSIONS: dict[str, dict[str, Scope]] = {
    "super_admin": dict.fromkeys(PERMISSIONS, A),
    "sales_manager": {
        permission: A
        for permission in PERMISSIONS
        if permission not in {"org.manage", "users.manage", "audit.view", "data.clear"}
    },
    "lead_researcher": {
        **_READ,
        **_OUTREACH_MEMBER,
        "prospects.view": A,
        "prospects.create": A,
        "prospects.edit": A,
        "clients.view_sensitive": A,
        "clients.create": A,
        "clients.edit": A,
        "leads.create": A,
        "leads.edit": O,
        "activities.create": A,
        "tasks.view": O,
        "tasks.create": A,
        "tasks.edit": O,
        "meetings.view": O,
        "meetings.create": O,
        "meetings.edit": O,
        "meetings.cancel": O,
        "data.import": A,
    },
    "bdr": dict(_FRONT_LINE),
    "account_executive": dict(_FRONT_LINE),
    "marketing": {
        **_READ,
        "clients.view_sensitive": A,
        "tasks.view": O,
        "tasks.create": A,
        "tasks.edit": O,
        "marketing.manage": A,
        "data.import": A,
        "data.export": A,
        "archive.view": A,
        "meetings.view": O,
        "meetings.create": O,
        "meetings.edit": O,
        "meetings.cancel": O,
    },
    "read_only": {**_READ, "tasks.view": A, "data.export": A, "prospects.view": A, "team.view": A,
                  "archive.view": A},
}


def scope_for(role: str, permission: str) -> Scope | None:
    if permission not in PERMISSIONS:
        raise KeyError(f"Unknown permission {permission!r}")  # programming error, not user input
    return ROLE_PERMISSIONS.get(role, {}).get(permission)
