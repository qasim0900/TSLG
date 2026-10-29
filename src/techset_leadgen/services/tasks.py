from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from techset_leadgen.domain.outreach import ACTIVE_ASSIGNMENT_STATUSES

from techset_leadgen.database.engine import utcnow
from techset_leadgen.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from techset_leadgen.database.models import Lead, Prospect, ProspectAssignment, Task, User
from techset_leadgen.services.schemas import FollowUpSchedule, TaskCreate, TaskUpdate
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import audit, notifications, prospects
from techset_leadgen.services.access import Actor, get_record, id_filter, owns
from techset_leadgen.services.common import check_version, drop_unset_defaults, referenced_client, referenced_lead, require_values, resolve_owner
from techset_leadgen.services.pagination import Page, PageRequest, like_pattern, paginate

VIEWS = {"mine": "My tasks", "team": "Everyone's tasks"}
DUE_FILTERS = {
    "open": "Open",
    "overdue": "Overdue",
    "today": "Due today",
    "upcoming": "Next 7 days",
    "done": "Completed",
    "cancelled": "Cancelled",
    "all": "All",
}
AUDITED_FIELDS = ("title", "description", "client_id", "lead_id", "prospect_id", "assigned_to_id", "priority",
                  "due_at", "status")
_ASSIGNEE = aliased(User)
_PROSPECT = aliased(Prospect)
SORTS = {"due": Task.due_at,
         "priority": case({"low": 0, "medium": 1, "high": 2, "urgent": 3}, value=Task.priority, else_=1),
         "title": Task.title, "created": Task.created_at, "status": Task.status,
         "assignee": func.lower(_ASSIGNEE.full_name), "activity": _PROSPECT.last_activity_at}


def local_day_bounds(timezone: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    today = (now or utcnow()).astimezone(zone).date()
    start = datetime.combine(today, time.min, tzinfo=zone)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def _visibility(actor: Actor) -> Any:
    scope = actor.require("tasks.view")
    if scope is Scope.ALL:
        return Task.id.is_not(None)
    return or_(Task.assigned_to_id == actor.user_id,
               (Task.kind != "follow_up") & (Task.created_by_id == actor.user_id))


def list_tasks(
    db: Session,
    actor: Actor,
    *,
    page: PageRequest,
    view: str = "mine",
    due: str = "open",
    q: str | None = None,
    lead_id: Any = None,
    client_id: Any = None,
    prospect_id: Any = None,
    kind: str | None = None,
    now: datetime | None = None,
) -> Page[Task]:
    statement = (select(Task).where(_visibility(actor))
                 .outerjoin(_ASSIGNEE, _ASSIGNEE.id == Task.assigned_to_id)
                 .outerjoin(_PROSPECT, _PROSPECT.id == Task.prospect_id)
                 .options(joinedload(Task.assigned_to), joinedload(Task.lead), joinedload(Task.client),
                          joinedload(Task.prospect)))
    if view == "team":
        if actor.scope("tasks.view") is not Scope.ALL:
            raise PermissionDenied("You can view only your own tasks.")
    elif lead_id is None and client_id is None and prospect_id is None:
        statement = statement.where(Task.assigned_to_id == actor.user_id)
    if lead_id is not None:
        statement = id_filter(statement, Task.lead_id, lead_id)
    if client_id is not None:
        statement = id_filter(statement, Task.client_id, client_id)
    if prospect_id is not None:
        statement = id_filter(statement, Task.prospect_id, prospect_id)
    if kind is not None:
        if kind not in {"task", "follow_up"}:
            raise ValidationFailed("Choose a valid task type.", fields={"kind": "Choose a listed task type."})
        statement = statement.where(Task.kind == kind)
    current = now or utcnow()
    if due == "overdue":
        statement = statement.where(Task.status == "open", Task.due_at < current)
    elif due == "today":
        start, end = local_day_bounds(actor.timezone, current)
        statement = statement.where(Task.status == "open", Task.due_at >= start, Task.due_at < end)
    elif due == "upcoming":
        statement = statement.where(Task.status == "open", Task.due_at >= current,
                                    Task.due_at < current + timedelta(days=7))
    elif due == "done":
        statement = statement.where(Task.status == "done")
    elif due == "cancelled":
        statement = statement.where(Task.status == "cancelled")
    elif due != "all":
        statement = statement.where(Task.status == "open")
    if q and q.strip():
        statement = statement.where(func.lower(Task.title).like(like_pattern(q), escape="\\"))
    default = "-created" if due == "done" else "due"
    return paginate(db, statement, page, SORTS, default, tiebreaker=Task.id)


def get_task(db: Session, actor: Actor, task_id: Any) -> Task:
    scope = actor.require("tasks.view")
    task = get_record(db, Task, task_id)
    is_owner = task.assigned_to_id == actor.user_id if task.kind == "follow_up" else owns(task, actor.user_id)
    if scope is Scope.OWN and not is_owner:
        raise NotFound()
    return task


def refresh_follow_up(db: Session, lead_id: str | None) -> None:
    if lead_id is None:
        return
    db.flush()
    earliest = db.scalar(select(func.min(Task.due_at)).where(Task.lead_id == lead_id, Task.status == "open"))
    lead = db.get(Lead, lead_id)
    if lead is not None and lead.next_follow_up_at != earliest:
        lead.next_follow_up_at = earliest


def refresh_prospect_follow_up(db: Session, prospect_id: str | None) -> None:
    if prospect_id is None:
        return
    db.flush()
    earliest = db.scalar(select(func.min(Task.due_at)).where(
        Task.prospect_id == prospect_id, Task.kind == "follow_up", Task.status == "open"))
    prospect = db.get(Prospect, prospect_id)
    if prospect is not None and prospect.next_follow_up_at != earliest:
        prospect.next_follow_up_at = earliest


def _links(db: Session, actor: Actor, values: dict[str, Any]) -> None:
    lead = referenced_lead(db, values["lead_id"]) if values.get("lead_id") else None
    if values.get("client_id"):
        referenced_client(db, values["client_id"])
    if values.get("prospect_id"):
        if lead is not None or values.get("client_id"):
            raise ValidationFailed("A task can link to a lead/client or to a prospect, not both.", fields={
                "prospect_id": "Remove the lead/client link or the prospect link."})
        try:
            prospects.get_prospect(db, actor, values["prospect_id"])
        except NotFound as exc:
            raise ValidationFailed("Choose an existing prospect.",
                                   fields={"prospect_id": "Choose an existing prospect."}) from exc
    if lead is not None:
        if values.get("client_id") and values["client_id"] != lead.client_id:
            raise ValidationFailed("The client does not match the lead.", fields={"client_id": "Does not match the lead."})
        values["client_id"] = lead.client_id


def create_task(db: Session, actor: Actor, data: TaskCreate) -> Task:
    actor.require("tasks.create")
    values = data.model_dump()
    _links(db, actor, values)
    assignee = values.get("assigned_to_id") or actor.user_id
    values["assigned_to_id"] = resolve_owner(db, actor, "tasks.assign", assignee, current=None, record=None,
                                             field="assigned_to_id")
    values["priority"] = values.get("priority") or "medium"
    request_id = values.get("request_id")
    if request_id:
        prior = db.scalar(select(Task).where(Task.request_id == request_id))
        if prior is not None:
            same = (
                prior.kind == "task"
                and prior.created_by_id == actor.user_id
                and prior.title == values["title"]
                and prior.description == values.get("description")
                and prior.client_id == values.get("client_id")
                and prior.lead_id == values.get("lead_id")
                and prior.prospect_id == values.get("prospect_id")
                and prior.assigned_to_id == values.get("assigned_to_id")
                and prior.priority == values.get("priority")
                and prior.due_at == values.get("due_at")
            )
            if not same:
                raise Conflict("This save request was already used for a different task.")
            return prior
    duplicate = db.scalar(select(Task.id).where(
        Task.kind == "task",
        Task.status == "open",
        func.lower(Task.title) == values["title"].lower(),
        Task.assigned_to_id == values["assigned_to_id"],
        Task.lead_id == values["lead_id"] if values.get("lead_id") else Task.lead_id.is_(None),
        Task.prospect_id == values["prospect_id"] if values.get("prospect_id") else Task.prospect_id.is_(None),
        Task.due_at == values["due_at"] if values.get("due_at") else Task.due_at.is_(None),
    ))
    if duplicate is not None:
        raise Conflict("An identical open task already exists.", details={"existing_id": duplicate,
                                                                           "duplicate": "task"})
    task = Task(**values, status="open", created_by_id=actor.user_id)
    db.add(task)
    db.flush()
    refresh_follow_up(db, task.lead_id)
    refresh_prospect_follow_up(db, task.prospect_id)
    audit.record(db, actor, "task.created", entity_type="task", entity_id=task.id,
                 changes={"title": task.title, "assigned_to_id": task.assigned_to_id, "due_at": task.due_at,
                          "lead_id": task.lead_id})
    return task


def update_task(db: Session, actor: Actor, task_id: Any, data: TaskUpdate) -> Task:
    task = get_task(db, actor, task_id)
    if task.kind == "follow_up":
        _require_follow_up_owner(db, actor, task)
    else:
        actor.require_on("tasks.edit", task)
    changes = data.model_dump(exclude_unset=True)
    check_version(task, changes.pop("version", None))
    require_values(changes, "title")
    drop_unset_defaults(changes, "priority")
    if task.kind == "follow_up" and {"lead_id", "client_id", "prospect_id", "assigned_to_id"} & changes.keys():
        raise ValidationFailed("Use the prospect assignment workflow to move a follow-up.", fields={
            field: "This link is controlled by the prospect assignment."
            for field in {"lead_id", "client_id", "prospect_id", "assigned_to_id"} & changes.keys()
        })
    if {"lead_id", "client_id", "prospect_id"} & changes.keys():
        merged = {key: changes.get(key, getattr(task, key)) for key in ("lead_id", "client_id", "prospect_id")}
        if "lead_id" in changes and "client_id" not in changes:
            merged["client_id"] = None
        _links(db, actor, merged)
        changes.update(merged)
    if "assigned_to_id" in changes:
        if changes["assigned_to_id"] is None:
            raise ValidationFailed("Choose who should do this task.", fields={"assigned_to_id": "Choose a user."})
        changes["assigned_to_id"] = resolve_owner(db, actor, "tasks.assign", changes["assigned_to_id"],
                                                  current=task.assigned_to_id, record=task, field="assigned_to_id")
    previous_lead = task.lead_id
    previous_prospect = task.prospect_id
    before = audit.snapshot(task, AUDITED_FIELDS)
    for field, value in changes.items():
        setattr(task, field, value)
    delta = audit.diff(before, audit.snapshot(task, AUDITED_FIELDS))
    if delta:
        refresh_follow_up(db, task.lead_id)
        if previous_lead != task.lead_id:
            refresh_follow_up(db, previous_lead)
        refresh_prospect_follow_up(db, task.prospect_id)
        if previous_prospect != task.prospect_id:
            refresh_prospect_follow_up(db, previous_prospect)
        audit.record(db, actor, "task.updated", entity_type="task", entity_id=task.id, changes=delta)
    return task


def _prospect_title(prospect: Prospect) -> str:
    return prospect.full_name or prospect.company or prospect.linkedin_key


def _require_follow_up_owner(db: Session, actor: Actor, task: Task) -> None:
    scope = actor.require("outreach.record")
    if task.kind != "follow_up" or task.prospect_id is None:
        raise NotFound()
    if scope is Scope.OWN and task.assigned_to_id != actor.user_id:
        raise PermissionDenied("This follow-up is no longer assigned to you.")
    prospects.get_prospect(db, actor, task.prospect_id)


def _schedule_context(
    db: Session,
    actor: Actor,
    prospect_id: Any,
    assignment: ProspectAssignment | None,
) -> tuple[Prospect, ProspectAssignment | None, Task | None]:
    prospect = prospects.get_prospect(db, actor, prospect_id)
    current = prospects.open_assignment(db, prospect.id)
    if assignment is not None and (assignment.prospect_id != prospect.id or current is None
                                   or current.id != assignment.id):
        raise Conflict("The prospect assignment changed. Reload it and try again.")
    assignment = current
    existing = db.scalar(select(Task).where(
        Task.kind == "follow_up", Task.status == "open", Task.prospect_id == prospect.id))
    scope = actor.require("outreach.record")
    if assignment is not None and assignment.status == "planned":
        raise Conflict("Activate the assignment before scheduling its follow-up.")
    if scope is Scope.OWN:
        owns_assignment = (assignment is not None and assignment.assignee_id == actor.user_id
                           and assignment.status in ACTIVE_ASSIGNMENT_STATUSES)
        owns_existing = existing is not None and existing.assigned_to_id == actor.user_id
        if not owns_assignment and not owns_existing:
            raise PermissionDenied("You can schedule follow-ups only for your own outreach work.")
    return prospect, assignment, existing


def _same_schedule(task: Task, data: FollowUpSchedule, actor: Actor) -> bool:
    return (task.kind == "follow_up" and task.prospect_id == data.prospect_id
            and task.created_by_id == actor.user_id and task.due_at == data.due_at
            and task.description == data.note)


def schedule_follow_up(
    db: Session,
    actor: Actor,
    data: FollowUpSchedule,
    *,
    assignment: ProspectAssignment | None = None,
    version: int | None = None,
) -> Task:
    prospect, assignment, existing = _schedule_context(db, actor, data.prospect_id, assignment)
    if data.request_id:
        prior = db.scalar(select(Task).where(Task.request_id == data.request_id))
        if prior is not None:
            if not _same_schedule(prior, data, actor):
                raise Conflict("This save request was already used for a different follow-up.")
            return prior

    responsible_id = assignment.assignee_id if assignment is not None else (
        (existing.assigned_to_id if existing is not None else None) or actor.user_id)
    if existing is None:
        if version is not None:
            raise Conflict("The follow-up changed. Reload it and try again.")
        task = Task(
            title=f"Follow up with {_prospect_title(prospect)}",
            description=data.note,
            assigned_to_id=responsible_id,
            priority="medium",
            due_at=data.due_at,
            status="open",
            created_by_id=actor.user_id,
            kind="follow_up",
            prospect_id=prospect.id,
            assignment_id=assignment.id if assignment is not None else None,
            request_id=data.request_id,
        )
        db.add(task)
        db.flush()
        action = "follow_up.scheduled"
        changes: dict[str, Any] = {
            "prospect_id": prospect.id,
            "assigned_to_id": responsible_id,
            "due_at": data.due_at,
        }
        notification_kind = "follow_up_scheduled"
        notification_verb = "scheduled"
    else:
        check_version(existing, version)
        task = existing
        before = audit.snapshot(task, ("due_at", "description", "assigned_to_id", "assignment_id"))
        task.due_at = data.due_at
        task.description = data.note
        task.assigned_to_id = responsible_id
        task.assignment_id = assignment.id if assignment is not None else task.assignment_id
        if data.request_id:
            task.request_id = data.request_id
        changes = audit.diff(before, audit.snapshot(
            task, ("due_at", "description", "assigned_to_id", "assignment_id")))
        if not changes:
            return task
        action = "follow_up.rescheduled"
        notification_kind = "follow_up_rescheduled"
        notification_verb = "rescheduled"

    refresh_prospect_follow_up(db, prospect.id)
    audit.record(db, actor, action, entity_type="task", entity_id=task.id, changes=changes)
    notifications.notify(
        db,
        responsible_id,
        kind=notification_kind,
        title=f"Follow-up {notification_verb}",
        body=f"{_prospect_title(prospect)} · {data.due_at.isoformat()}",
        entity_type="task",
        entity_id=task.id,
        dedupe_key=f"follow-up:{task.id}:{notification_kind}:{task.version}",
        actor=actor,
    )
    return task


def get_open_follow_up(db: Session, actor: Actor, prospect_id: Any) -> Task | None:
    prospect = prospects.get_prospect(db, actor, prospect_id)
    task = db.scalar(select(Task).where(
        Task.kind == "follow_up", Task.status == "open", Task.prospect_id == prospect.id
    ).options(joinedload(Task.assigned_to), joinedload(Task.prospect)))
    if task is None:
        return None
    scope = actor.require("tasks.view")
    if scope is Scope.OWN and task.assigned_to_id != actor.user_id:
        raise NotFound()
    return task


def _close_follow_up(
    db: Session,
    actor: Actor,
    task_id: Any,
    status: str,
    *,
    version: int | None,
    outcome: str | None,
) -> Task:
    task = get_task(db, actor, task_id)
    _require_follow_up_owner(db, actor, task)
    check_version(task, version)
    if task.status == status:
        return task
    if task.status != "open":
        raise Conflict("This follow-up is already closed.", details={
            "current_status": task.status, "current_version": task.version})
    cleaned = outcome.strip() if outcome and outcome.strip() else None
    if cleaned is not None and len(cleaned) > 5000:
        raise ValidationFailed("Keep the outcome under 5,000 characters.", fields={
            "outcome": "Keep the outcome under 5,000 characters."})
    previous = task.status
    task.status = status
    task.completed_at = utcnow() if status == "done" else None
    task.outcome = cleaned
    refresh_prospect_follow_up(db, task.prospect_id)
    audit.record(
        db,
        actor,
        "follow_up.completed" if status == "done" else "follow_up.cancelled",
        entity_type="task",
        entity_id=task.id,
        changes={"status": [previous, status], "outcome_recorded": cleaned is not None},
    )
    return task


def complete_follow_up(
    db: Session,
    actor: Actor,
    task_id: Any,
    *,
    version: int | None = None,
    outcome: str | None = None,
) -> Task:
    return _close_follow_up(db, actor, task_id, "done", version=version, outcome=outcome)


def cancel_follow_up(
    db: Session,
    actor: Actor,
    task_id: Any,
    *,
    version: int | None = None,
    reason: str | None = None,
) -> Task:
    return _close_follow_up(db, actor, task_id, "cancelled", version=version, outcome=reason)


def set_status(db: Session, actor: Actor, task_id: Any, status: str, version: int | None = None) -> Task:
    if status not in {"open", "done", "cancelled"}:
        raise ValidationFailed("Choose a valid task status.", fields={"status": "Choose a valid status."})
    task = get_task(db, actor, task_id)
    if task.kind == "follow_up":
        _require_follow_up_owner(db, actor, task)
        if status == "open" and task.status != "open":
            raise Conflict("Closed follow-ups cannot be reopened; schedule a new follow-up instead.")
    else:
        actor.require_on("tasks.edit", task)
    check_version(task, version)
    if task.status == status:
        return task
    previous = task.status
    task.status = status
    task.completed_at = utcnow() if status == "done" else None
    refresh_follow_up(db, task.lead_id)
    refresh_prospect_follow_up(db, task.prospect_id)
    action = ("follow_up.completed" if status == "done" else "follow_up.cancelled") \
        if task.kind == "follow_up" else "task.status_changed"
    audit.record(db, actor, action, entity_type="task", entity_id=task.id,
                 changes={"status": [previous, status]})
    return task


def counts(db: Session, actor: Actor, *, now: datetime | None = None, kind: str | None = None) -> dict[str, int]:
    if not actor.can("tasks.view"):
        return {"open": 0, "overdue": 0, "today": 0}
    current = now or utcnow()
    start, end = local_day_bounds(actor.timezone, current)
    base = select(func.count()).select_from(Task).where(Task.assigned_to_id == actor.user_id, Task.status == "open")
    if kind is not None:
        base = base.where(Task.kind == kind)
    return {
        "open": db.scalar(base) or 0,
        "overdue": db.scalar(base.where(Task.due_at < current)) or 0,
        "today": db.scalar(base.where(Task.due_at >= start, Task.due_at < end)) or 0,
    }

