"""Meetings: clients, attendees, conflict-free scheduling, suggested slots, and the lifecycle.

The rule (``domain.scheduling``): only scheduled meetings reserve time, and a client
or a team member may not have two meetings whose reserved times (the meeting plus
the organization's buffer) overlap. Cancelled meetings never block; completed
meetings are history.

Concurrency. Creating, editing, and rescheduling lock the client's row and every
attendee's ``users`` row, always in the same order (clients, then users, by ID),
then check the schedule and write, all in one transaction. On PostgreSQL the locks
(``SELECT … FOR NO KEY UPDATE``) make a second computer booking the same client or
person wait for the first to commit; its check, a new statement under READ
COMMITTED, then sees the first meeting and is refused. SQLite's ``BEGIN
IMMEDIATE`` serializes every writer. ``check_availability`` runs the same check
without locks: it is advisory, the save is authoritative.

Visibility. ``meetings.view`` with scope ALL sees every meeting; scope OWN sees the
meetings the user attends or created. A conflict with a meeting the caller may not
see names only its time, never its title or people.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, false, func, or_, select, true
from sqlalchemy.orm import Session, joinedload, selectinload

from techset_leadgen.analytics.models.client_manager import _generate_client_id
from techset_leadgen.database.engine import utcnow
from techset_leadgen.database.models import AuditLog, Client, Meeting, MeetingAttendee, Organization, User
from techset_leadgen.domain import scheduling
from techset_leadgen.domain.scheduling import Interval, SchedulingRules, day_bounds
from techset_leadgen.domain.vocabulary import MEETING_STATUSES
from techset_leadgen.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import audit, notifications, users
from techset_leadgen.services.access import Actor
from techset_leadgen.services.common import check_version
from techset_leadgen.services.pagination import Page, PageRequest, like_pattern, paginate
from techset_leadgen.services.schemas import (
    AvailabilityQuery,
    MeetingCreate,
    MeetingReschedule,
    MeetingUpdate,
    SchedulingRulesUpdate,
)

MAX_ATTENDEES = 20
VIEWS = {
    "today": "Today's meetings",
    "upcoming": "Upcoming",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "conflicts": "Scheduling conflicts",
}
SORTS = {
    "date": Meeting.starts_at,
    "title": func.lower(Meeting.title),
    "client": func.lower(Meeting.client_name),
    "status": Meeting.status,
    "created": Meeting.created_at,
}
AUDITED_FIELDS = (
    "client_id", "client_name", "client_email", "title", "starts_at", "ends_at", "link", "description", "status",
    "cancellation_reason",
)
_LOADED = (selectinload(Meeting.attendee_links).joinedload(MeetingAttendee.user), joinedload(Meeting.created_by))


# --- results --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ClientChoice:
    id: str
    name: str
    email: str | None  # None when the caller may not see client emails
    contact_person: str | None


@dataclass(frozen=True)
class PersonChoice:
    id: str
    full_name: str
    email: str


@dataclass(frozen=True)
class ScheduleEntry:
    """A meeting on a client's schedule; ``title`` is None when the caller may not see it."""

    id: str
    title: str | None
    starts_at: datetime
    ends_at: datetime
    status: str
    attendees: str


@dataclass(frozen=True)
class ClientSchedule:
    client: ClientChoice
    on_date: list[ScheduleEntry]
    upcoming: list[ScheduleEntry]
    past: list[ScheduleEntry]


@dataclass(frozen=True)
class Clash:
    """A stored meeting that blocks the requested time for the client or one attendee."""

    party: str  # "client", or the attendee's user ID
    party_name: str
    kind: str  # "overlap" (the meetings overlap) or "buffer" (too close under the buffer rule)
    meeting_id: str
    title: str | None
    starts_at: datetime
    ends_at: datetime
    message: str


@dataclass(frozen=True)
class Availability:
    starts_at: datetime
    ends_at: datetime
    rules: SchedulingRules
    client_conflicts: list[Clash] = field(default_factory=list)
    attendee_conflicts: list[Clash] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # e.g. the time is in the past
    suggestions: list[Interval] = field(default_factory=list)
    suggestion_day: date | None = None
    suggestions_later: bool = False  # the requested date had no free slot
    outside_hours: bool = False

    @property
    def conflicts(self) -> list[Clash]:
        return [*self.client_conflicts, *self.attendee_conflicts]

    @property
    def buffer_conflicts(self) -> list[Clash]:
        return [clash for clash in self.conflicts if clash.kind == "buffer"]

    @property
    def available(self) -> bool:
        return not self.conflicts and not self.problems


# --- settings -------------------------------------------------------------------------------------

def scheduling_rules(db: Session) -> SchedulingRules:
    organization = db.get(Organization, 1)
    if organization is None:
        return SchedulingRules()
    return SchedulingRules(
        timezone=organization.timezone or "UTC",
        buffer_mode=organization.meeting_buffer_mode,
        buffer_minutes=organization.meeting_buffer_minutes,
        day_start=organization.meeting_day_start,
        day_end=organization.meeting_day_end,
        work_days=organization.meeting_work_days,
    )


def get_scheduling_rules(db: Session, actor: Actor) -> SchedulingRules:
    """The rules, for anyone who works with meetings or manages the organization."""
    if not (actor.can("meetings.view") or actor.can("org.manage")):
        raise PermissionDenied()
    return scheduling_rules(db)


def business_timezone(db: Session, actor: Actor) -> str:
    organization = db.get(Organization, 1)
    return organization.timezone if organization is not None else actor.timezone


_RULE_COLUMNS = {
    "buffer_mode": "meeting_buffer_mode", "buffer_minutes": "meeting_buffer_minutes",
    "day_start": "meeting_day_start", "day_end": "meeting_day_end", "work_days": "meeting_work_days",
}


def update_scheduling_rules(db: Session, actor: Actor, data: SchedulingRulesUpdate) -> SchedulingRules:
    """Change the buffer and business hours. Existing meetings stay; ones that now clash are counted
    as scheduling conflicts until someone moves them."""
    actor.require("org.manage")
    organization = users.get_organization(db)
    changes: dict[str, list[Any]] = {}
    for name, column in _RULE_COLUMNS.items():
        value = getattr(data, name)
        if getattr(organization, column) != value:
            changes[name] = [getattr(organization, column), value]
            setattr(organization, column, value)
    if changes:
        audit.record(db, actor, "organization.meeting_rules_updated", entity_type="organization",
                     entity_id=organization.id, changes=changes)
    db.flush()
    return scheduling_rules(db)


# --- visibility -----------------------------------------------------------------------------------

def _attends(user_id: str) -> Any:
    return select(MeetingAttendee.id).where(MeetingAttendee.meeting_id == Meeting.id,
                                            MeetingAttendee.user_id == user_id).exists()


def _visible(actor: Actor) -> Any:
    if actor.require("meetings.view") is Scope.ALL:
        return true()
    return or_(_attends(actor.user_id), Meeting.created_by_id == actor.user_id)


def _involves(actor: Actor, meeting: Meeting) -> bool:
    return actor.user_id in meeting.attendee_ids or meeting.created_by_id == actor.user_id


def _can_see(actor: Actor, meeting: Meeting) -> bool:
    scope = actor.scope("meetings.view")
    return scope is Scope.ALL or (scope is Scope.OWN and _involves(actor, meeting))


def _require_on(actor: Actor, permission: str, meeting: Meeting) -> Scope:
    """Another member's meeting is reported as not found, so IDs cannot be probed."""
    scope = actor.require(permission)
    if scope is Scope.OWN and not _involves(actor, meeting):
        raise NotFound()
    return scope


def _load(db: Session, meeting_id: Any) -> Meeting:
    key = str(meeting_id or "").strip()
    meeting = db.scalar(select(Meeting).where(Meeting.id == key).options(*_LOADED)) if key else None
    if meeting is None:
        raise NotFound()
    return meeting


# --- clients and people ---------------------------------------------------------------------------

def _client_choice(client: Client, sensitive: bool) -> ClientChoice:
    return ClientChoice(client.id, client.name, client.email if sensitive else None, client.contact_person)


def search_clients(db: Session, actor: Actor, query: str = "", *, limit: int = 20) -> list[ClientChoice]:
    """Existing clients by name, contact person, or email (case-insensitive), exact matches first.

    Emails are searched and returned only for callers allowed to see them."""
    actor.require("meetings.create")
    actor.require("clients.view")
    sensitive = actor.can("clients.view_sensitive")
    term = (query or "").strip()[:200]
    statement = select(Client)
    exact: Any = false()
    if term:
        pattern = like_pattern(term)
        conditions = [func.lower(Client.name).like(pattern, escape="\\"),
                      func.lower(Client.contact_person).like(pattern, escape="\\")]
        exact = func.lower(Client.name) == term.lower()
        if sensitive:
            conditions.append(func.lower(Client.email).like(pattern, escape="\\"))
            exact = or_(exact, func.lower(Client.email) == term.lower())
        statement = statement.where(or_(*conditions))
    statement = statement.order_by(case((exact, 0), else_=1), func.lower(Client.name), Client.id)
    return [_client_choice(client, sensitive) for client in db.scalars(statement.limit(min(max(limit, 1), 50)))]


def search_attendees(db: Session, actor: Actor, query: str = "", *, limit: int = 50) -> list[PersonChoice]:
    """Active team members by name or email (case-insensitive)."""
    actor.require("meetings.create")
    statement = select(User).where(User.is_active.is_(True))
    if query and query.strip():
        pattern = like_pattern(query)
        statement = statement.where(or_(func.lower(User.full_name).like(pattern, escape="\\"),
                                        func.lower(User.email).like(pattern, escape="\\")))
    rows = db.scalars(statement.order_by(func.lower(User.full_name), User.email).limit(min(max(limit, 1), 50)))
    return [PersonChoice(user.id, user.full_name, user.email) for user in rows]


def _entry(actor: Actor, meeting: Meeting) -> ScheduleEntry:
    visible = _can_see(actor, meeting)
    return ScheduleEntry(meeting.id, meeting.title if visible else None, meeting.starts_at, meeting.ends_at,
                         meeting.status, ", ".join(user.full_name for user in meeting.attendees) if visible else "")


def client_schedule(db: Session, actor: Actor, client_id: str, *, on_date: date | None = None,
                    now: datetime | None = None, limit: int = 5) -> ClientSchedule:
    """The client's meetings on ``on_date``, the next scheduled ones, and recent past ones.

    Meetings the caller may not see are listed by time only, so nobody double-books a client
    whose other meetings belong to a colleague."""
    actor.require("meetings.view")
    actor.require("clients.view")
    client = db.get(Client, str(client_id or ""))
    if client is None:
        raise NotFound()
    current = (now or utcnow()).astimezone(UTC)
    base = select(Meeting).where(Meeting.client_id == client.id).options(*_LOADED)
    day: list[Meeting] = []
    if on_date is not None:
        start, end = day_bounds(on_date, scheduling_rules(db).zone)
        day = list(db.scalars(base.where(Meeting.status != "cancelled", Meeting.starts_at < end,
                                         Meeting.ends_at > start).order_by(Meeting.starts_at)))
    upcoming = list(db.scalars(base.where(Meeting.status == "scheduled", Meeting.starts_at >= current)
                               .order_by(Meeting.starts_at).limit(limit)))
    past = list(db.scalars(base.where(Meeting.status != "cancelled", Meeting.starts_at < current)
                           .order_by(Meeting.starts_at.desc()).limit(limit)))
    return ClientSchedule(_client_choice(client, actor.can("clients.view_sensitive")),
                          [_entry(actor, item) for item in day], [_entry(actor, item) for item in upcoming],
                          [_entry(actor, item) for item in past])


def _resolve_client(db: Session, actor: Actor, data: MeetingCreate | MeetingUpdate) -> tuple[Client, str]:
    """The meeting's client and the email used for it: an existing client, or a new one added now."""
    if data.client_id:
        actor.require("clients.view")
        client = db.get(Client, data.client_id)
        if client is None:
            raise ValidationFailed("Choose an existing client.", fields={"client_id": "This client no longer exists."})
        email = data.client_email or (client.email or "").strip().lower() or None
    else:
        if not data.client_name:
            raise ValidationFailed("Choose a client.", fields={
                "client_id": "Search for the client by name or email, or add a new client."})
        client, email = None, data.client_email
    if not email:
        raise ValidationFailed("Enter the client's email address.", fields={
            "client_email": "An email address is required for the meeting."})
    if client is None:
        client = _add_client(db, actor, str(data.client_name), email)
    return client, email


def _add_client(db: Session, actor: Actor, name: str, email: str) -> Client:
    """A new client typed into the meeting form, unless one already has that name or email."""
    actor.require("clients.create")
    target = name.strip().casefold()
    for client_id, existing in db.execute(select(Client.id, Client.name)):
        if str(existing or "").strip().casefold() == target:
            raise Conflict(f"A client named '{existing}' already exists. Choose it in the search results "
                           "instead of adding it again.", fields={"client_name": "This client already exists."},
                           details={"duplicate": "client", "existing_id": client_id})
    same_email = db.scalar(select(Client).where(func.lower(Client.email) == email))
    if same_email is not None:
        raise Conflict(f"{same_email.name} already uses the email {email}. Select that client instead of "
                       "adding a new one.", fields={"client_email": "Another client already uses this email."},
                       details={"duplicate": "client", "existing_id": same_email.id})
    client_id = _generate_client_id()
    while db.get(Client, client_id) is not None:
        client_id = _generate_client_id()
    now = utcnow()
    client = Client(id=client_id, name=name.strip(), cif="-", email=email, account_status="prospect",
                    created_by_id=actor.user_id, created_at=now, updated_at=now)
    db.add(client)
    db.flush()
    audit.record(db, actor, "client.created", entity_type="client", entity_id=client.id,
                 changes={"name": client.name, "email": email, "source": "meeting"})
    return client


# --- scheduling checks ----------------------------------------------------------------------------

def _interval(start: object, end: object) -> tuple[datetime, datetime]:
    if not isinstance(start, datetime) or not isinstance(end, datetime) or start.tzinfo is None or end.tzinfo is None:
        raise ValidationFailed("Enter a valid meeting date and time.", fields={
            "starts_at": "A date and time are required.", "ends_at": "A date and time are required."})
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end <= start:
        raise ValidationFailed("The end time must be later than the start time.", fields={
            "ends_at": "Choose an end time after the start time."})
    if end - start > scheduling.MAX_DURATION:
        hours = int(scheduling.MAX_DURATION.total_seconds() // 3600)
        raise ValidationFailed(f"A meeting can last at most {hours} hours.", fields={
            "ends_at": f"Choose an end time within {hours} hours of the start."})
    return start, end


def _past_problem(start: datetime, now: datetime) -> str | None:
    if start < now - scheduling.PAST_GRACE:
        return "This time is in the past. Choose a time from now on."
    return None


def _not_past(start: datetime, now: datetime) -> None:
    problem = _past_problem(start, now)
    if problem:
        raise ValidationFailed(problem, fields={"starts_at": "Choose a date and time from now on."})


def _attendee_list(ids: list[str]) -> list[str]:
    if not ids:
        raise ValidationFailed("Choose at least one team member to attend.", fields={
            "attendee_ids": "Choose at least one attendee."})
    if len(ids) > MAX_ATTENDEES:
        raise ValidationFailed(f"Choose at most {MAX_ATTENDEES} attendees.", fields={
            "attendee_ids": f"Choose at most {MAX_ATTENDEES} attendees."})
    return ids


def _people(db: Session, ids: set[str], *, must_be_active: set[str], lock: bool) -> dict[str, User]:
    """The attendees' accounts, locked in ID order when ``lock`` (after any client locks)."""
    if not ids:
        return {}
    statement = select(User).where(User.id.in_(sorted(ids))).order_by(User.id)
    if lock:
        statement = statement.with_for_update(key_share=True)
    found = {user.id: user for user in db.scalars(statement)}
    if set(found) != ids or any(not found[user_id].is_active for user_id in must_be_active):
        raise ValidationFailed("Choose active team members as attendees.", fields={
            "attendee_ids": "One of the chosen team members does not exist or is no longer active."})
    return found


def _lock_clients(db: Session, client_ids: set[str]) -> None:
    for client_id in sorted(client_ids):
        db.execute(select(Client.id).where(Client.id == client_id).with_for_update(key_share=True))


def _blocking_meetings(db: Session, *, client_id: str | None, attendee_ids: set[str], start: datetime,
                       end: datetime, gap: timedelta, exclude_id: str | None) -> list[Meeting]:
    """Scheduled meetings of the client or any attendee whose reserved time could touch [start, end)."""
    shared = []
    if client_id:
        shared.append(Meeting.client_id == client_id)
    if attendee_ids:
        shared.append(select(MeetingAttendee.id).where(MeetingAttendee.meeting_id == Meeting.id,
                                                       MeetingAttendee.user_id.in_(sorted(attendee_ids))).exists())
    if not shared:
        return []
    statement = select(Meeting).where(Meeting.status == "scheduled", or_(*shared),
                                      Meeting.starts_at < end + gap, Meeting.ends_at > start - gap)
    if exclude_id:
        statement = statement.where(Meeting.id != exclude_id)
    return list(db.scalars(statement.options(*_LOADED).order_by(Meeting.starts_at, Meeting.id)))


def _clash_message(who: str, meeting: Meeting, kind: str, title: str | None, rules: SchedulingRules,
                   reference: date) -> str:
    span = scheduling.span_text(meeting.starts_at, meeting.ends_at, rules.zone, reference=reference)
    named = f" ({title})" if title else ""
    if kind == "overlap":
        scheduled = " scheduled" if who == "This client" else ""
        return f"{who} already has a meeting{scheduled} {span}{named}."
    if rules.buffer_mode == "around":
        rule = (f"a {rules.buffer_minutes}-minute buffer is required before and after each meeting "
                f"({2 * rules.buffer_minutes} minutes between meetings)")
    else:
        rule = f"a {rules.buffer_minutes}-minute buffer is required after each meeting"
    return f"{who} has a meeting {span}{named}, and {rule}."


def _clashes(actor: Actor, rules: SchedulingRules, client_id: str | None, people: dict[str, User],
             start: datetime, end: datetime, meetings: list[Meeting]) -> tuple[list[Clash], list[Clash]]:
    reference = start.astimezone(rules.zone).date()
    for_client: list[Clash] = []
    for_people: list[Clash] = []
    for meeting in meetings:
        kind = scheduling.conflict_kind(meeting.starts_at, meeting.ends_at, start, end, rules.gap)
        if kind is None:
            continue
        title = meeting.title if _can_see(actor, meeting) else None
        if client_id and meeting.client_id == client_id:
            for_client.append(Clash("client", "This client", kind, meeting.id, title, meeting.starts_at,
                                    meeting.ends_at, _clash_message("This client", meeting, kind, title, rules,
                                                                    reference)))
        for user_id in sorted(meeting.attendee_ids & people.keys(), key=lambda key: people[key].full_name):
            name = people[user_id].full_name
            for_people.append(Clash(user_id, name, kind, meeting.id, title, meeting.starts_at, meeting.ends_at,
                                    _clash_message(name, meeting, kind, title, rules, reference)))
    return for_client, for_people


def _suggest(db: Session, rules: SchedulingRules, *, client_id: str | None, attendee_ids: set[str],
             start: datetime, end: datetime, exclude_id: str | None, now: datetime) -> scheduling.Suggestions:
    window_start, window_end = scheduling.search_window(start, rules)
    busy = _blocking_meetings(db, client_id=client_id, attendee_ids=attendee_ids, start=window_start,
                              end=window_end, gap=rules.gap, exclude_id=exclude_id)
    return scheduling.suggest([Interval(item.starts_at, item.ends_at) for item in busy], end - start, rules,
                              start, now)


def slot_text(slot: Interval, rules: SchedulingRules) -> str:
    return f"{scheduling.clock(slot.starts_at, rules.zone)}–{scheduling.clock(slot.ends_at, rules.zone)}"


def _unavailable(rules: SchedulingRules, clashes: list[Clash], suggestions: scheduling.Suggestions) -> Conflict:
    lines = [clash.message for clash in clashes]
    if suggestions.slots and suggestions.day is not None:
        when = "Available alternatives" + (f" on {scheduling.day_text(suggestions.day)}"
                                           if suggestions.later_day else "")
        lines.append(f"{when}: " + ", ".join(slot_text(slot, rules) for slot in suggestions.slots) + ".")
    else:
        lines.append(f"No free time was found in the next {scheduling.SEARCH_DAYS} days within business hours "
                     f"({rules.hours_text()}). Try another date or fewer attendees.")
    return Conflict("This time slot is unavailable.", fields={"availability": "\n".join(lines)}, details={
        "conflicts": [{"party": clash.party, "kind": clash.kind, "meeting_id": clash.meeting_id,
                       "starts_at": clash.starts_at.isoformat(), "ends_at": clash.ends_at.isoformat()}
                      for clash in clashes],
        "suggestions": [[slot.starts_at.isoformat(), slot.ends_at.isoformat()] for slot in suggestions.slots],
    })


def _ensure_free(db: Session, actor: Actor, rules: SchedulingRules, *, client_id: str | None,
                 people: dict[str, User], start: datetime, end: datetime, exclude_id: str | None,
                 now: datetime) -> None:
    """The final check, made while the client and attendees are locked."""
    meetings = _blocking_meetings(db, client_id=client_id, attendee_ids=set(people), start=start, end=end,
                                  gap=rules.gap, exclude_id=exclude_id)
    for_client, for_people = _clashes(actor, rules, client_id, people, start, end, meetings)
    if for_client or for_people:
        suggestions = _suggest(db, rules, client_id=client_id, attendee_ids=set(people), start=start, end=end,
                               exclude_id=exclude_id, now=now)
        raise _unavailable(rules, [*for_client, *for_people], suggestions)


def check_availability(db: Session, actor: Actor, query: AvailabilityQuery, *,
                       now: datetime | None = None) -> Availability:
    """Is the proposed time free for the client and every attendee? If not: why, and free slots.

    Informational: nothing is locked or saved; ``create_meeting`` and the edits check again."""
    current = (now or utcnow()).astimezone(UTC)
    exclude_id = None
    if query.meeting_id:
        meeting = _load(db, query.meeting_id)
        _require_on(actor, "meetings.edit", meeting)
        exclude_id = meeting.id
    else:
        actor.require("meetings.create")
    start, end = _interval(query.starts_at, query.ends_at)
    rules = scheduling_rules(db)
    if query.client_id and db.get(Client, query.client_id) is None:
        raise ValidationFailed("Choose an existing client.", fields={"client_id": "This client no longer exists."})
    ids = set(query.attendee_ids)
    people = _people(db, ids, must_be_active=set(), lock=False)
    problems = [problem for problem in (_past_problem(start, current),) if problem]
    meetings = _blocking_meetings(db, client_id=query.client_id, attendee_ids=ids, start=start, end=end,
                                  gap=rules.gap, exclude_id=exclude_id)
    for_client, for_people = _clashes(actor, rules, query.client_id, people, start, end, meetings)
    result = Availability(start, end, rules, for_client, for_people, problems,
                          outside_hours=scheduling.outside_hours(start, end, rules))
    if result.available:
        return result
    suggestions = _suggest(db, rules, client_id=query.client_id, attendee_ids=ids, start=start, end=end,
                           exclude_id=exclude_id, now=current)
    return Availability(start, end, rules, for_client, for_people, problems, suggestions.slots, suggestions.day,
                        suggestions.later_day, result.outside_hours)


# --- changes --------------------------------------------------------------------------------------

def _check_request(db: Session, actor: Actor, request_id: str | None) -> Meeting | None:
    if not request_id:
        return None
    existing = db.scalar(select(Meeting).where(Meeting.request_id == request_id).options(*_LOADED))
    if existing is None:
        return None
    if existing.created_by_id != actor.user_id:
        raise Conflict("This save request has already been used.")
    return existing


def _snapshot(meeting: Meeting) -> dict[str, Any]:
    values = audit.snapshot(meeting, AUDITED_FIELDS)
    values["attendee_ids"] = sorted(meeting.attendee_ids)
    return values


def _notify(db: Session, actor: Actor, meeting: Meeting, recipients: set[str], *, kind: str, title: str,
            action: str) -> None:
    for recipient_id in sorted(recipients):
        notifications.notify(
            db, recipient_id, kind=kind, title=title, body=f"{meeting.title} with {meeting.client_name}.",
            entity_type="meeting", entity_id=meeting.id,
            dedupe_key=f"{action}:{meeting.id}:{meeting.version}:{recipient_id}", actor=actor,
        )


def create_meeting(db: Session, actor: Actor, data: MeetingCreate, *, now: datetime | None = None) -> Meeting:
    scope = actor.require("meetings.create")
    duplicate = _check_request(db, actor, data.request_id)
    if duplicate is not None:
        return duplicate
    current = (now or utcnow()).astimezone(UTC)
    start, end = _interval(data.starts_at, data.ends_at)
    _not_past(start, current)
    attendee_ids = _attendee_list(data.attendee_ids)
    if scope is Scope.OWN and actor.user_id not in attendee_ids:
        raise PermissionDenied("You can schedule only meetings that you attend. Add yourself as an attendee.")
    client, email = _resolve_client(db, actor, data)
    rules = scheduling_rules(db)
    _lock_clients(db, {client.id})
    people = _people(db, set(attendee_ids), must_be_active=set(attendee_ids), lock=True)
    _ensure_free(db, actor, rules, client_id=client.id, people=people, start=start, end=end, exclude_id=None,
                 now=current)
    meeting = Meeting(client_id=client.id, client_name=client.name, client_email=email, title=data.title,
                      starts_at=start, ends_at=end, link=data.link, description=data.description,
                      created_by_id=actor.user_id, created_at=current, updated_at=current,
                      request_id=data.request_id)
    meeting.attendee_links = [MeetingAttendee(user_id=user_id, created_at=current) for user_id in attendee_ids]
    db.add(meeting)
    db.flush()
    audit.record(db, actor, "meeting.created", entity_type="meeting", entity_id=meeting.id,
                 changes={key: value for key, value in _snapshot(meeting).items() if value is not None})
    _notify(db, actor, meeting, set(attendee_ids), kind="meeting.scheduled",
            title="A meeting was scheduled for you", action="meeting-scheduled")
    return meeting


def _editable(db: Session, actor: Actor, meeting_id: str, version: int | None) -> tuple[Meeting, Scope]:
    meeting = _load(db, meeting_id)
    scope = _require_on(actor, "meetings.edit", meeting)
    if meeting.status != "scheduled":
        raise Conflict(f"This meeting is {MEETING_STATUSES[meeting.status].lower()} and can no longer be changed.")
    check_version(meeting, version)
    return meeting, scope


def _record_change(db: Session, actor: Actor, meeting: Meeting, before: dict[str, Any],
                   previous_attendees: set[str]) -> None:
    changes = audit.diff(before, _snapshot(meeting))
    if not changes:
        return
    rescheduled = "starts_at" in changes or "ends_at" in changes
    audit.record(db, actor, "meeting.rescheduled" if rescheduled else "meeting.updated", entity_type="meeting",
                 entity_id=meeting.id, changes=changes)
    current = meeting.attendee_ids
    _notify(db, actor, meeting, current - previous_attendees, kind="meeting.scheduled",
            title="You were added to a meeting", action="meeting-added")
    _notify(db, actor, meeting, previous_attendees - current, kind="meeting.removed",
            title="You were removed from a meeting", action="meeting-removed")
    _notify(db, actor, meeting, current & previous_attendees, kind="meeting.updated",
            title="A meeting was rescheduled" if rescheduled else "A meeting was updated", action="meeting-updated")


def update_meeting(db: Session, actor: Actor, meeting_id: str, data: MeetingUpdate, *,
                   now: datetime | None = None) -> Meeting:
    """Change any detail of a scheduled meeting; the resulting schedule is checked like a new one."""
    current = (now or utcnow()).astimezone(UTC)
    meeting, scope = _editable(db, actor, meeting_id, data.version)
    start, end = _interval(data.starts_at, data.ends_at)
    if (start, end) != (meeting.starts_at, meeting.ends_at):
        _not_past(start, current)
    attendee_ids = _attendee_list(data.attendee_ids)
    previous = meeting.attendee_ids
    if scope is Scope.OWN and set(attendee_ids) != previous and actor.user_id not in attendee_ids:
        raise PermissionDenied("You cannot remove yourself from a meeting you manage. Ask a manager instead.")
    client, email = _resolve_client(db, actor, data)
    rules = scheduling_rules(db)
    _lock_clients(db, {key for key in (client.id, meeting.client_id) if key})
    people = _people(db, set(attendee_ids) | previous, must_be_active=set(attendee_ids) - previous, lock=True)
    attending = {user_id: people[user_id] for user_id in attendee_ids}
    _ensure_free(db, actor, rules, client_id=client.id, people=attending, start=start, end=end,
                 exclude_id=meeting.id, now=current)
    before = _snapshot(meeting)
    meeting.client_id, meeting.client_name, meeting.client_email = client.id, client.name, email
    meeting.title, meeting.link, meeting.description = data.title, data.link, data.description
    meeting.starts_at, meeting.ends_at = start, end
    meeting.attendee_links = [link for link in meeting.attendee_links if link.user_id in attendee_ids] + [
        MeetingAttendee(user_id=user_id, created_at=current) for user_id in attendee_ids if user_id not in previous]
    meeting.updated_at = current
    db.flush()
    _record_change(db, actor, meeting, before, previous)
    return meeting


def reschedule_meeting(db: Session, actor: Actor, meeting_id: str, data: MeetingReschedule, *,
                       now: datetime | None = None) -> Meeting:
    """Move a scheduled meeting; it never conflicts with itself."""
    current = (now or utcnow()).astimezone(UTC)
    meeting, _scope = _editable(db, actor, meeting_id, data.version)
    start, end = _interval(data.starts_at, data.ends_at)
    _not_past(start, current)
    rules = scheduling_rules(db)
    _lock_clients(db, {meeting.client_id} if meeting.client_id else set())
    people = _people(db, meeting.attendee_ids, must_be_active=set(), lock=True)
    _ensure_free(db, actor, rules, client_id=meeting.client_id, people=people, start=start, end=end,
                 exclude_id=meeting.id, now=current)
    before = _snapshot(meeting)
    meeting.starts_at, meeting.ends_at, meeting.updated_at = start, end, current
    db.flush()
    _record_change(db, actor, meeting, before, meeting.attendee_ids)
    return meeting


def cancel_meeting(db: Session, actor: Actor, meeting_id: str, reason: str | None = None,
                   *, version: int | None = None) -> Meeting:
    """Cancel a scheduled meeting: it stays in the history and no longer reserves time."""
    meeting = _load(db, meeting_id)
    _require_on(actor, "meetings.cancel", meeting)
    check_version(meeting, version)
    if meeting.status != "scheduled":
        raise Conflict("Only scheduled meetings can be cancelled.")
    before = _snapshot(meeting)
    meeting.status = "cancelled"
    meeting.cancellation_reason = reason.strip()[:500] if reason and reason.strip() else None
    meeting.updated_at = utcnow()
    db.flush()
    audit.record(db, actor, "meeting.cancelled", entity_type="meeting", entity_id=meeting.id,
                 changes=audit.diff(before, _snapshot(meeting)))
    _notify(db, actor, meeting, meeting.attendee_ids, kind="meeting.cancelled", title="A meeting was cancelled",
            action="meeting-cancelled")
    return meeting


def complete_meeting(db: Session, actor: Actor, meeting_id: str, *, version: int | None = None,
                     now: datetime | None = None) -> Meeting:
    """Mark a meeting that has started as held; it becomes history."""
    current = (now or utcnow()).astimezone(UTC)
    meeting = _load(db, meeting_id)
    _require_on(actor, "meetings.edit", meeting)
    check_version(meeting, version)
    if meeting.status != "scheduled":
        raise Conflict("Only scheduled meetings can be marked completed.")
    if meeting.starts_at > current:
        raise Conflict("This meeting has not started yet. Mark it completed once it has taken place.")
    before = _snapshot(meeting)
    meeting.status = "completed"
    meeting.completed_at = meeting.updated_at = current
    db.flush()
    audit.record(db, actor, "meeting.completed", entity_type="meeting", entity_id=meeting.id,
                 changes=audit.diff(before, _snapshot(meeting)))
    return meeting


# --- reading --------------------------------------------------------------------------------------

def get_meeting(db: Session, actor: Actor, meeting_id: str) -> Meeting:
    meeting = _load(db, meeting_id)
    _require_on(actor, "meetings.view", meeting)
    return meeting


def history(db: Session, actor: Actor, meeting_id: str, *, limit: int = 100) -> list[AuditLog]:
    """What happened to a meeting (created, updated, rescheduled, cancelled, completed), newest first,
    for anyone who may see the meeting."""
    meeting = get_meeting(db, actor, meeting_id)
    return list(db.scalars(select(AuditLog).where(AuditLog.entity_type == "meeting", AuditLog.entity_id == meeting.id)
                           .options(joinedload(AuditLog.actor))
                           .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)))


def conflicting_ids(db: Session, rules: SchedulingRules, now: datetime | None = None) -> set[str]:
    """Scheduled meetings, not yet over, whose reserved time overlaps another scheduled meeting of the
    same client or attendee under the current rules (e.g. booked before the buffer was raised)."""
    current = (now or utcnow()).astimezone(UTC)
    gap = rules.gap
    window = (Meeting.status == "scheduled", Meeting.ends_at > current - gap)
    times: dict[str, tuple[datetime, datetime]] = {}
    resources: dict[str, list[str]] = defaultdict(list)
    for meeting_id, client_id, starts_at, ends_at in db.execute(
            select(Meeting.id, Meeting.client_id, Meeting.starts_at, Meeting.ends_at).where(*window)):
        times[meeting_id] = (starts_at, ends_at)
        if client_id:
            resources[f"client:{client_id}"].append(meeting_id)
    for meeting_id, user_id in db.execute(select(MeetingAttendee.meeting_id, MeetingAttendee.user_id)
                                          .join(Meeting, Meeting.id == MeetingAttendee.meeting_id).where(*window)):
        resources[f"user:{user_id}"].append(meeting_id)
    found: set[str] = set()
    for ids in resources.values():
        latest: str | None = None  # the earlier meeting that ends last
        for meeting_id in sorted(ids, key=lambda key: times[key]):
            starts_at, ends_at = times[meeting_id]
            if latest is not None and starts_at < times[latest][1] + gap:
                found.update((latest, meeting_id))
            if latest is None or ends_at > times[latest][1]:
                latest = meeting_id
    return {meeting_id for meeting_id in found if times[meeting_id][1] > current}


def _business_dates(db: Session, start_day: date | None, end_day: date | None) -> tuple[datetime | None, datetime | None]:
    zone = scheduling_rules(db).zone
    start = day_bounds(start_day, zone)[0] if start_day else None
    end = day_bounds(end_day, zone)[1] if end_day else None
    return start, end


def _view_filter(db: Session, view: str, current: datetime, rules: SchedulingRules) -> Any:
    if view == "today":
        start, end = day_bounds(current.astimezone(rules.zone).date(), rules.zone)
        return (Meeting.status != "cancelled", Meeting.starts_at >= start, Meeting.starts_at < end)
    if view == "upcoming":
        return (Meeting.status == "scheduled", Meeting.starts_at >= current)
    if view in ("completed", "cancelled"):
        return (Meeting.status == view,)
    if view == "conflicts":
        return (Meeting.id.in_(sorted(conflicting_ids(db, rules, current)) or [""]),)
    raise ValidationFailed("Choose a listed view.", fields={"view": "Choose a listed view."})


def list_meetings(
    db: Session,
    actor: Actor,
    *,
    page: PageRequest,
    q: str | None = None,
    view: str | None = None,
    status: str | None = None,
    on_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    attendee_id: str | None = None,
    client_id: str | None = None,
    client_q: str | None = None,
    now: datetime | None = None,
) -> Page[Meeting]:
    """One page of the meetings the caller may see, with attendees and creator loaded."""
    current = (now or utcnow()).astimezone(UTC)
    statement = select(Meeting).where(_visible(actor)).options(*_LOADED)
    term = (q or "").strip()[:200]
    if term:
        pattern = like_pattern(term)
        people = select(MeetingAttendee.id).join(User, User.id == MeetingAttendee.user_id).where(
            MeetingAttendee.meeting_id == Meeting.id,
            or_(func.lower(User.full_name).like(pattern, escape="\\"),
                func.lower(User.email).like(pattern, escape="\\"))).exists()
        statement = statement.where(or_(
            func.lower(Meeting.title).like(pattern, escape="\\"),
            func.lower(Meeting.client_name).like(pattern, escape="\\"),
            func.lower(Meeting.client_email).like(pattern, escape="\\"),
            func.lower(Meeting.id) == term.lower(),
            people,
        ))
    rules = scheduling_rules(db)
    if view:
        statement = statement.where(*_view_filter(db, view, current, rules))
    if status:
        if status not in MEETING_STATUSES:
            raise ValidationFailed("Choose a valid meeting status.", fields={"status": "Choose a listed status."})
        statement = statement.where(Meeting.status == status)
    if on_date is not None:
        date_from = date_to = on_date
    if date_from and date_to and date_to < date_from:
        raise ValidationFailed("The end of the date range is before its start.", fields={
            "date_to": "Choose a date on or after the start date."})
    start, end = _business_dates(db, date_from, date_to)
    if start is not None:
        statement = statement.where(Meeting.starts_at >= start)
    if end is not None:
        statement = statement.where(Meeting.starts_at < end)
    if attendee_id:
        statement = statement.where(_attends(attendee_id))
    if client_id:
        statement = statement.where(Meeting.client_id == client_id)
    if client_q and client_q.strip():
        pattern = like_pattern(client_q)
        statement = statement.where(or_(func.lower(Meeting.client_name).like(pattern, escape="\\"),
                                        func.lower(Meeting.client_email).like(pattern, escape="\\")))
    return paginate(db, statement, page, SORTS, "date", tiebreaker=Meeting.id)


def meeting_counts(db: Session, actor: Actor, now: datetime | None = None) -> dict[str, int]:
    """The summary cards, from stored meetings; each matches the list ``view`` of the same name."""
    current = (now or utcnow()).astimezone(UTC)
    rules = scheduling_rules(db)
    visible = _visible(actor)

    def count(*conditions: Any) -> Any:
        return func.coalesce(func.sum(case((and_(*conditions), 1), else_=0)), 0)

    names = ("today", "upcoming", "completed", "cancelled")
    row = db.execute(select(*(count(*_view_filter(db, name, current, rules)) for name in names))
                     .select_from(Meeting).where(visible)).one()
    counts = dict(zip(names, (int(value or 0) for value in row), strict=True))
    ids = conflicting_ids(db, rules, current)
    counts["conflicts"] = (db.scalar(select(func.count()).select_from(Meeting).where(visible, Meeting.id.in_(sorted(ids))))
                           or 0) if ids else 0
    return counts


__all__ = [
    "Availability", "Clash", "ClientChoice", "ClientSchedule", "MAX_ATTENDEES", "PersonChoice", "ScheduleEntry",
    "VIEWS", "business_timezone", "cancel_meeting", "check_availability", "client_schedule", "complete_meeting",
    "conflicting_ids", "create_meeting", "get_meeting", "get_scheduling_rules", "history", "list_meetings", "meeting_counts",
    "reschedule_meeting", "scheduling_rules", "search_attendees", "search_clients", "slot_text",
    "update_meeting", "update_scheduling_rules",
]
