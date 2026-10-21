"""Tasks and follow-ups.

A lead's ``next_follow_up_at`` is derived from its open tasks (earliest due
date), so scheduling a follow-up always means creating a task someone owns.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import utcnow
from ..errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from ..models import Lead, Task
from ..schemas import TaskCreate, TaskUpdate
from ..security.permissions import Scope
from . import audit
from .access import Actor, get_record, id_filter, owns
from .common import check_version, drop_unset_defaults, referenced_client, referenced_lead, require_values, resolve_owner
from .pagination import Page, PageRequest, like_pattern, paginate

VIEWS = {"mine": "My tasks", "team": "Everyone's tasks"}
DUE_FILTERS = {
    "open": "Open",
    "overdue": "Overdue",
    "today": "Due today",
    "upcoming": "Next 7 days",
    "done": "Completed",
    "all": "All",
}
AUDITED_FIELDS = ("title", "description", "client_id", "lead_id", "assigned_to_id", "priority", "due_at", "status")
SORTS = {"due": Task.due_at, "priority": Task.priority, "title": Task.title, "created": Task.created_at,
         "status": Task.status}


def local_day_bounds(timezone: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """UTC start/end of the current calendar day in ``timezone`` (DST-safe)."""
    zone = ZoneInfo(timezone)
    today = (now or utcnow()).astimezone(zone).date()
    start = datetime.combine(today, time.min, tzinfo=zone)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def _visibility(actor: Actor) -> Any:
    scope = actor.require("tasks.view")
    if scope is Scope.ALL:
        return Task.id.is_not(None)
    return or_(Task.assigned_to_id == actor.user_id, Task.created_by_id == actor.user_id)


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
    now: datetime | None = None,
) -> Page[Task]:
    statement = select(Task).where(_visibility(actor)).options(
        joinedload(Task.assigned_to), joinedload(Task.lead), joinedload(Task.client)
    )
    if view == "team":
        if actor.scope("tasks.view") is not Scope.ALL:
            raise PermissionDenied("You can view only your own tasks.")
    elif lead_id is None and client_id is None:
        statement = statement.where(Task.assigned_to_id == actor.user_id)
    if lead_id is not None:
        statement = id_filter(statement, Task.lead_id, lead_id)
    if client_id is not None:
        statement = id_filter(statement, Task.client_id, client_id)
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
    elif due != "all":
        statement = statement.where(Task.status == "open")
    if q and q.strip():
        statement = statement.where(func.lower(Task.title).like(like_pattern(q), escape="\\"))
    default = "-created" if due == "done" else "due"
    return paginate(db, statement, page, SORTS, default, tiebreaker=Task.id)


def get_task(db: Session, actor: Actor, task_id: Any) -> Task:
    scope = actor.require("tasks.view")
    task = get_record(db, Task, task_id)
    if scope is Scope.OWN and not owns(task, actor.user_id):
        raise NotFound()
    return task


def refresh_follow_up(db: Session, lead_id: str | None) -> None:
    """Recompute a lead's next follow-up from its open tasks."""
    if lead_id is None:
        return
    db.flush()
    earliest = db.scalar(select(func.min(Task.due_at)).where(Task.lead_id == lead_id, Task.status == "open"))
    lead = db.get(Lead, lead_id)
    if lead is not None and lead.next_follow_up_at != earliest:
        lead.next_follow_up_at = earliest


def _links(db: Session, values: dict[str, Any]) -> None:
    lead = referenced_lead(db, values["lead_id"]) if values.get("lead_id") else None
    if values.get("client_id"):
        referenced_client(db, values["client_id"])
    if lead is not None:
        if values.get("client_id") and values["client_id"] != lead.client_id:
            raise ValidationFailed("The client does not match the lead.", fields={"client_id": "Does not match the lead."})
        values["client_id"] = lead.client_id


def create_task(db: Session, actor: Actor, data: TaskCreate) -> Task:
    actor.require("tasks.create")
    values = data.model_dump()
    _links(db, values)
    assignee = values.get("assigned_to_id") or actor.user_id
    values["assigned_to_id"] = resolve_owner(db, actor, "tasks.assign", assignee, current=None, record=None,
                                             field="assigned_to_id")
    values["priority"] = values.get("priority") or "medium"
    duplicate = db.scalar(select(Task.id).where(
        Task.status == "open",
        func.lower(Task.title) == values["title"].lower(),
        Task.assigned_to_id == values["assigned_to_id"],
        Task.lead_id == values["lead_id"] if values.get("lead_id") else Task.lead_id.is_(None),
        Task.due_at == values["due_at"] if values.get("due_at") else Task.due_at.is_(None),
    ))
    if duplicate is not None:
        raise Conflict("An identical open task already exists.", details={"existing_id": duplicate,
                                                                           "duplicate": "task"})
    task = Task(**values, status="open", created_by_id=actor.user_id)
    db.add(task)
    db.flush()
    refresh_follow_up(db, task.lead_id)
    audit.record(db, actor, "task.created", entity_type="task", entity_id=task.id,
                 changes={"title": task.title, "assigned_to_id": task.assigned_to_id, "due_at": task.due_at,
                          "lead_id": task.lead_id})
    return task


def update_task(db: Session, actor: Actor, task_id: Any, data: TaskUpdate) -> Task:
    task = get_task(db, actor, task_id)
    actor.require_on("tasks.edit", task)
    changes = data.model_dump(exclude_unset=True)
    check_version(task, changes.pop("version", None))
    require_values(changes, "title")
    drop_unset_defaults(changes, "priority")
    if {"lead_id", "client_id"} & changes.keys():
        merged = {key: changes.get(key, getattr(task, key)) for key in ("lead_id", "client_id")}
        if "lead_id" in changes and "client_id" not in changes:
            merged["client_id"] = None
        _links(db, merged)
        changes.update(merged)
    if "assigned_to_id" in changes:
        if changes["assigned_to_id"] is None:
            raise ValidationFailed("Choose who should do this task.", fields={"assigned_to_id": "Choose a user."})
        changes["assigned_to_id"] = resolve_owner(db, actor, "tasks.assign", changes["assigned_to_id"],
                                                  current=task.assigned_to_id, record=task, field="assigned_to_id")
    previous_lead = task.lead_id
    before = audit.snapshot(task, AUDITED_FIELDS)
    for field, value in changes.items():
        setattr(task, field, value)
    delta = audit.diff(before, audit.snapshot(task, AUDITED_FIELDS))
    if delta:
        refresh_follow_up(db, task.lead_id)
        if previous_lead != task.lead_id:
            refresh_follow_up(db, previous_lead)
        audit.record(db, actor, "task.updated", entity_type="task", entity_id=task.id, changes=delta)
    return task


def set_status(db: Session, actor: Actor, task_id: Any, status: str, version: int | None = None) -> Task:
    if status not in {"open", "done", "cancelled"}:
        raise ValidationFailed("Choose a valid task status.", fields={"status": "Choose a valid status."})
    task = get_task(db, actor, task_id)
    actor.require_on("tasks.edit", task)
    check_version(task, version)
    if task.status == status:
        return task
    previous = task.status
    task.status = status
    task.completed_at = utcnow() if status == "done" else None
    refresh_follow_up(db, task.lead_id)
    audit.record(db, actor, "task.status_changed", entity_type="task", entity_id=task.id,
                 changes={"status": [previous, status]})
    return task


def counts(db: Session, actor: Actor, *, now: datetime | None = None) -> dict[str, int]:
    """Open, overdue, and due-today counts of the user's own tasks."""
    if not actor.can("tasks.view"):
        return {"open": 0, "overdue": 0, "today": 0}
    current = now or utcnow()
    start, end = local_day_bounds(actor.timezone, current)
    base = select(func.count()).select_from(Task).where(Task.assigned_to_id == actor.user_id, Task.status == "open")
    return {
        "open": db.scalar(base) or 0,
        "overdue": db.scalar(base.where(Task.due_at < current)) or 0,
        "today": db.scalar(base.where(Task.due_at >= start, Task.due_at < end)) or 0,
    }
