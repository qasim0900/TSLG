"""The role matrix for the whole application (see docs/USER_GUIDE.md, "Roles")."""

from __future__ import annotations

import pytest

from techset_leadgen.security.permissions import PERMISSIONS, ROLE_PERMISSIONS, Scope, scope_for
from techset_leadgen.domain.vocabulary import ROLES

A, O = Scope.ALL, Scope.OWN

# role -> {permission: expected scope or None}
EXPECTED: dict[str, dict[str, Scope | None]] = {
    "read_only": {
        "sales.view": A, "clients.view": A, "leads.view": A, "clients.view_sensitive": None,
        "clients.create": None, "clients.edit": None, "clients.delete": None, "leads.create": None,
        "leads.edit": None, "leads.qualify": None, "activities.create": None, "tasks.create": None,
        "tasks.view": A, "data.export": A, "data.import": None, "marketing.manage": None, "users.view": None,
        "meetings.view": None, "meetings.create": None, "meetings.edit": None, "meetings.cancel": None,
    },
    "marketing": {
        "clients.view_sensitive": A, "clients.edit": None, "leads.create": None, "leads.edit": None,
        "activities.create": None, "tasks.view": O, "tasks.create": A, "tasks.edit": O, "marketing.manage": A,
        "data.import": A, "data.export": A, "leads.assign": None, "data.clear": None,
        "meetings.view": O, "meetings.create": O, "meetings.edit": O, "meetings.cancel": O,
    },
    "lead_researcher": {
        "clients.create": A, "clients.edit": A, "clients.delete": None, "clients.merge": None,
        "leads.create": A, "leads.edit": O, "leads.qualify": None, "leads.assign": None,
        "activities.create": A, "tasks.view": O, "data.import": A, "data.export": None,
        "meetings.view": O, "meetings.create": O, "meetings.edit": O, "meetings.cancel": O,
    },
    "bdr": {
        "clients.edit": O, "clients.delete": None, "leads.edit": O, "leads.qualify": O, "leads.assign": None,
        "tasks.assign": None, "activities.create": A, "users.view": None, "data.import": None,
        "marketing.manage": None, "meetings.view": O, "meetings.create": O, "meetings.edit": O,
        "meetings.cancel": O,
    },
    "account_executive": {
        "clients.edit": O, "leads.edit": O, "leads.qualify": O, "leads.assign": None, "data.export": None,
        "meetings.view": O, "meetings.create": O, "meetings.edit": O, "meetings.cancel": O,
    },
    "sales_manager": {
        "leads.assign": A, "leads.qualify": A, "clients.delete": A, "clients.merge": A, "clients.assign": A,
        "tasks.view": A, "tasks.assign": A, "users.view": A, "users.manage": None, "org.manage": None,
        "audit.view": None, "data.clear": None, "data.import": A, "marketing.manage": A,
        "meetings.view": A, "meetings.create": A, "meetings.edit": A, "meetings.cancel": A,
    },
    "super_admin": dict.fromkeys(PERMISSIONS, A),
}


@pytest.mark.parametrize(("role", "permission", "expected"), [
    (role, permission, expected) for role, table in EXPECTED.items() for permission, expected in table.items()
])
def test_role_matrix(role, permission, expected):
    assert scope_for(role, permission) is expected


def test_every_role_is_defined_and_uses_known_permissions():
    assert set(ROLE_PERMISSIONS) == set(ROLES)
    for granted in ROLE_PERMISSIONS.values():
        assert set(granted) <= set(PERMISSIONS)


def test_only_super_admin_can_manage_users_settings_audit_and_clear_data():
    for permission in ("users.manage", "org.manage", "audit.view", "data.clear"):
        assert [role for role in ROLES if scope_for(role, permission)] == ["super_admin"]


def test_every_signed_in_role_sees_the_analytics():
    assert all(scope_for(role, "sales.view") is A for role in ROLES)


def test_unknown_permission_is_a_programming_error():
    with pytest.raises(KeyError):
        scope_for("super_admin", "leads.delete_everything")
