"""Lead stages: the one definition used by imports, funnel analytics, reports, and screens.

The first five stages are the original funnel; "qualified" and "nurture" came
with the CRM workflow. Stored values are codes; "converted" is shown as "Client".
"""

from __future__ import annotations

LEAD_STATUSES: dict[str, str] = {
    "new": "Lead",
    "contacted": "Contacted",
    "meeting": "Meeting",
    "qualified": "Qualified",
    "nurture": "Nurture",
    "converted": "Client",
    "lost": "Lost",
}
# Stages that count as having reached the meeting stage in the funnel.
MEETING_OR_LATER = frozenset({"meeting", "qualified", "converted"})
CLOSED_STATUSES = frozenset({"converted", "lost"})
# Moves allowed through the screens. Imports record whatever stage the source reports.
LEAD_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"contacted", "meeting", "qualified", "nurture", "lost"}),
    "contacted": frozenset({"meeting", "qualified", "nurture", "lost"}),
    "meeting": frozenset({"contacted", "qualified", "nurture", "converted", "lost"}),
    "qualified": frozenset({"meeting", "nurture", "converted", "lost"}),
    "nurture": frozenset({"contacted", "meeting", "qualified", "lost"}),
    "converted": frozenset(),
    "lost": frozenset({"nurture", "contacted"}),
}
REASON_REQUIRED = frozenset({"qualified", "lost"})

_BY_NAME = {**{code: code for code in LEAD_STATUSES}, **{label.casefold(): code for code, label in LEAD_STATUSES.items()},
            "client": "converted", "won": "converted", "customer": "converted", "disqualified": "lost"}


def normalize_lead_status(value: str | None, default: str = "new") -> str:
    """A stage code from an imported value ("Client", "contacted", ...); unknown values are refused."""
    text = (value or "").strip()
    if not text:
        return default
    code = _BY_NAME.get(text.casefold())
    if code is None:
        known = ", ".join(LEAD_STATUSES.values())
        raise ValueError(f"Unknown lead stage {text!r}. Use one of: {known}.")
    return code
