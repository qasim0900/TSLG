"""Controlled vocabularies shared by models, validation, analytics, and the screens.

Stored values are short codes; labels are for display only. Changing a stored
value requires a data migration.
"""

from __future__ import annotations

from collections.abc import Iterable

from domain.lead_stages import (  # noqa: F401  (re-exported for the services)
    CLOSED_STATUSES,
    LEAD_STATUSES,
    LEAD_TRANSITIONS,
    MEETING_OR_LATER,
    REASON_REQUIRED,
)

ROLES = {
    "super_admin": "Super Admin",
    "sales_manager": "Sales Manager",
    "lead_researcher": "Lead Researcher",
    "bdr": "Business Development Rep",
    "account_executive": "Account Executive",
    "marketing": "Marketing",
    "read_only": "Management (read-only)",
}

PRIORITIES = {"low": "Low", "medium": "Medium", "high": "High", "urgent": "Urgent"}

ACCOUNT_STATUSES = {
    "prospect": "Prospect",
    "active": "Active client",
    "former": "Former client",
    "not_a_fit": "Not a fit",
}

EMPLOYEE_RANGES = ("1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001+")

ACTIVITY_TYPES = {"note": "Note", "call": "Call", "email": "Email", "meeting": "Meeting", "other": "Other"}

TASK_STATUSES = {"open": "Open", "done": "Done", "cancelled": "Cancelled"}

TOKEN_PURPOSES = ("invite", "password_reset")


def check_in(column: str, values: Iterable[str]) -> str:
    """SQL CHECK expression restricting ``column`` to ``values`` (module constants only)."""
    options = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({options})"
