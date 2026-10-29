from __future__ import annotations

from collections.abc import Mapping, Sequence

PROSPECT_STATUSES: dict[str, str] = {
    "new": "Not contacted",
    "connection_sent": "Request sent",
    "connected": "Connected",
    "messaged": "Messaged",
    "replied": "Replied",
    "meeting": "Meeting requested",
    "not_interested": "Not interested",
    "invalid": "Wrong profile",
}
_PROGRESS = ("new", "connection_sent", "connected", "messaged", "replied", "meeting")
CLOSED_PROSPECT_STATUSES = frozenset({"not_interested", "invalid"})

OUTREACH_EVENTS: dict[str, str] = {
    "connection_sent": "Connection request sent",
    "connection_accepted": "Connection accepted",
    "message_sent": "Message sent",
    "reply_received": "Reply received",
    "follow_up_requested": "Follow-up requested",
    "meeting_requested": "Meeting requested",
    "not_interested": "Not interested",
    "wrong_profile": "Wrong or irrelevant profile",
    "note": "Note",
}
EVENT_STAGE: dict[str, str | None] = {
    "connection_sent": "connection_sent",
    "connection_accepted": "connected",
    "message_sent": "messaged",
    "reply_received": "replied",
    "follow_up_requested": "replied",
    "meeting_requested": "meeting",
    "not_interested": "not_interested",
    "wrong_profile": "invalid",
    "note": None,
}
FOLLOW_UP_EVENTS = frozenset({"follow_up_requested"})


def next_prospect_status(current: str, event_type: str) -> str:
    if event_type not in EVENT_STAGE:
        raise ValueError(f"Unknown outreach event {event_type!r}")
    stage = EVENT_STAGE[event_type]
    if stage is None:
        return current
    if stage in CLOSED_PROSPECT_STATUSES:
        return stage
    if current in CLOSED_PROSPECT_STATUSES or current not in _PROGRESS:
        return stage
    return max(current, stage, key=_PROGRESS.index)


ASSIGNMENT_STATUSES: dict[str, str] = {
    "planned": "Planned",
    "assigned": "Assigned",
    "in_progress": "In progress",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "reassigned": "Reassigned",
}
OPEN_ASSIGNMENT_STATUSES = frozenset({"planned", "assigned", "in_progress"})
ACTIVE_ASSIGNMENT_STATUSES = frozenset({"assigned", "in_progress"})
CLOSED_ASSIGNMENT_STATUSES = frozenset({"completed", "cancelled", "reassigned"})

BATCH_STATUSES: dict[str, str] = {
    "draft": "Draft",
    "active": "Active",
    "cancelled": "Cancelled",
}

TASK_KINDS: dict[str, str] = {"task": "Task", "follow_up": "Follow-up"}


def balance_plan(prospect_ids: Sequence[str], open_work: Mapping[str, int]) -> list[tuple[str, str]]:
    if not open_work:
        return []
    load = dict(open_work)
    order = {member: index for index, member in enumerate(load)}
    plan: list[tuple[str, str]] = []
    for prospect_id in prospect_ids:
        member = min(load, key=lambda candidate: (load[candidate], order[candidate]))
        plan.append((prospect_id, member))
        load[member] += 1
    return plan

