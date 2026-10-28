"""Recording LinkedIn outreach outcomes, exactly as team members report them.

Each outcome is one append-only ``outreach_events`` row. Recording it also, in
the same transaction:

* moves the prospect's stage forward (``domain.outreach.next_prospect_status``)
  and sets its last activity;
* starts the member's assignment (``assigned`` → ``in_progress``) on its first event;
* with a follow-up date (required for "Follow-up requested"), schedules or moves
  the prospect's single open follow-up;
* for a closing outcome (not interested, wrong profile), cancels the open
  follow-up, so nobody is reminded to contact someone who declined.

Nothing is inferred: only the outcome the member chose is stored, and a manager
reading the history sees who recorded what and when. The desktop sends a
``request_id`` with each save; retrying the same save returns the first event
instead of recording it twice.

Who may record: the current assignee of the prospect (``outreach.record`` with
own scope), or a manager with ``outreach.record`` for all records.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from techset_leadgen.database.engine import utcnow
from techset_leadgen.database.models import OutreachEvent, Task
from techset_leadgen.domain.outreach import (
    ACTIVE_ASSIGNMENT_STATUSES,
    CLOSED_PROSPECT_STATUSES,
    EVENT_STAGE,
    FOLLOW_UP_EVENTS,
    next_prospect_status,
)
from techset_leadgen.errors import Conflict, PermissionDenied, ValidationFailed
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import audit, prospects, tasks
from techset_leadgen.services.access import Actor
from techset_leadgen.services.schemas import FollowUpSchedule, OutreachRecord

CLOCK_SKEW = timedelta(minutes=5)  # computers' clocks differ a little; more is a typing mistake


def _same_event(event: OutreachEvent, data: OutreachRecord, actor: Actor) -> bool:
    return (event.prospect_id == data.prospect_id and event.event_type == data.event_type
            and event.recorded_by_id == actor.user_id and event.note == data.note)


def _follow_up_request(request_id: str | None) -> str | None:
    """The follow-up saved with an outcome gets its own retry key, derived from the outcome's."""
    if not request_id:
        return None
    return "fu-" + hashlib.sha256(request_id.encode()).hexdigest()[:40]


def record_event(db: Session, actor: Actor, data: OutreachRecord, *, now: datetime | None = None) -> OutreachEvent:
    """Record one outcome for a prospect (see the module docstring for everything it updates)."""
    scope = actor.require("outreach.record")
    moment = now or utcnow()
    if data.request_id:
        prior = db.scalar(select(OutreachEvent).where(OutreachEvent.request_id == data.request_id))
        if prior is not None:
            if not _same_event(prior, data, actor):
                raise Conflict("This save request was already used for a different outcome.")
            return prior
    prospect = prospects.get_prospect(db, actor, data.prospect_id)
    assignment = prospects.open_assignment(db, prospect.id)
    if scope is Scope.OWN and not prospects.works_on(actor, assignment):
        raise PermissionDenied("You can record outreach only for prospects currently assigned to you.")
    active = assignment if assignment is not None and assignment.status in ACTIVE_ASSIGNMENT_STATUSES else None

    occurred_at = data.occurred_at or moment
    if occurred_at > moment + CLOCK_SKEW:
        raise ValidationFailed("An outcome cannot be recorded in the future.",
                               fields={"occurred_at": "Choose the time it happened."})
    if data.event_type in FOLLOW_UP_EVENTS and data.follow_up_at is None:
        raise ValidationFailed("Choose when to follow up.", fields={"follow_up_at": "Choose a date and time."})
    closing = EVENT_STAGE[data.event_type] in CLOSED_PROSPECT_STATUSES
    if data.follow_up_at is not None:
        if closing:
            raise ValidationFailed("A closed prospect needs no follow-up.",
                                   fields={"follow_up_at": "Remove the follow-up date."})
        if data.follow_up_at <= moment:
            raise ValidationFailed("Choose a follow-up time in the future.",
                                   fields={"follow_up_at": "Choose a later date and time."})

    event = OutreachEvent(prospect_id=prospect.id, assignment_id=active.id if active is not None else None,
                          event_type=data.event_type, note=data.note, occurred_at=occurred_at,
                          recorded_by_id=actor.user_id, created_at=moment, request_id=data.request_id)
    db.add(event)
    previous = prospect.status
    prospect.status = next_prospect_status(previous, data.event_type)
    if prospect.last_activity_at is None or occurred_at > prospect.last_activity_at:
        prospect.last_activity_at = occurred_at
    prospect.updated_at = moment
    if active is not None and active.status == "assigned":
        active.status = "in_progress"
        active.started_at = moment
    db.flush()
    if prospect.status != previous:
        audit.record(db, actor, "prospect.status_changed", entity_type="prospect", entity_id=prospect.id,
                     changes={"status": [previous, prospect.status], "event": data.event_type})

    if data.follow_up_at is not None:
        tasks.schedule_follow_up(db, actor, FollowUpSchedule(
            prospect_id=prospect.id, due_at=data.follow_up_at, note=data.note,
            request_id=_follow_up_request(data.request_id)), assignment=assignment)
    elif closing:
        open_follow_up = db.scalar(select(Task).where(Task.kind == "follow_up", Task.status == "open",
                                                      Task.prospect_id == prospect.id))
        if open_follow_up is not None:
            tasks.cancel_follow_up(db, actor, open_follow_up.id,
                                   reason=f"Prospect closed: {data.event_type.replace('_', ' ')}")
    return event


__all__ = ["CLOCK_SKEW", "record_event"]
