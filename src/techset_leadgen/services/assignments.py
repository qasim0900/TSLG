from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from techset_leadgen.domain.outreach import ACTIVE_ASSIGNMENT_STATUSES, ASSIGNMENT_STATUSES, OPEN_ASSIGNMENT_STATUSES

from techset_leadgen.database.engine import utcnow
from techset_leadgen.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from techset_leadgen.database.models import AssignmentBatch, Prospect, ProspectAssignment, Task, User
from techset_leadgen.services.schemas import BatchCreate, Reassignment
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import audit, notifications
from techset_leadgen.services.access import Actor
from techset_leadgen.services.common import check_version
from techset_leadgen.services.pagination import Page, PageRequest, like_pattern, paginate

_LOOKUP_CHUNK = 500
_VISIBLE_STATUSES = frozenset(ACTIVE_ASSIGNMENT_STATUSES)
SORTS = {
    "assigned": ProspectAssignment.assigned_at,
    "due": ProspectAssignment.due_on,
    "status": ProspectAssignment.status,
    "prospect": func.lower(Prospect.full_name),
    "assignee": func.lower(User.full_name),
}


def _chunks(values: Sequence[str]) -> Iterable[list[str]]:
    for start in range(0, len(values), _LOOKUP_CHUNK):
        yield list(values[start:start + _LOOKUP_CHUNK])


def _prospect_title(prospect: Prospect) -> str:
    return prospect.full_name or prospect.company or prospect.linkedin_key


def _load_prospects(db: Session, ids: Sequence[str]) -> dict[str, Prospect]:
    found: dict[str, Prospect] = {}
    for chunk in _chunks(ids):
        found.update({item.id: item for item in db.scalars(select(Prospect).where(Prospect.id.in_(chunk)))})
    return found


def _load_users(db: Session, ids: Sequence[str]) -> dict[str, User]:
    found: dict[str, User] = {}
    for chunk in _chunks(ids):
        found.update({item.id: item for item in db.scalars(select(User).where(User.id.in_(chunk)))})
    return found


def _validate_plan(db: Session, actor: Actor, data: BatchCreate) -> tuple[list[tuple[str, str]], dict[str, Prospect]]:
    actor.require("assignments.manage")
    actor.require("prospects.view")
    plan = [(str(item.prospect_id).strip(), str(item.assignee_id).strip()) for item in data.plan]
    if any(not prospect_id or not assignee_id for prospect_id, assignee_id in plan):
        raise ValidationFailed("Every assignment needs a prospect and an assignee.",
                               fields={"plan": "Choose a prospect and an assignee for every row."})
    prospect_ids = [prospect_id for prospect_id, _assignee_id in plan]
    if len(set(prospect_ids)) != len(prospect_ids):
        raise ValidationFailed("A prospect can appear only once in an assignment batch.",
                               fields={"plan": "Remove duplicate prospects."})

    prospects = _load_prospects(db, prospect_ids)
    missing_prospects = sorted(set(prospect_ids) - prospects.keys())
    if missing_prospects:
        raise ValidationFailed("Some selected prospects no longer exist.",
                               fields={"plan": "Reload the prospects and try again."},
                               details={"prospect_ids": missing_prospects})

    assignee_ids = sorted({assignee_id for _prospect_id, assignee_id in plan})
    users = _load_users(db, assignee_ids)
    invalid_users = sorted(user_id for user_id in assignee_ids
                           if user_id not in users or not users[user_id].is_active
                           or not Actor.for_user(users[user_id]).can("outreach.record"))
    if invalid_users:
        raise ValidationFailed("Assignments can be given only to active outreach team members.",
                               fields={"plan": "Choose active team members who can record outreach."},
                               details={"user_ids": invalid_users})

    open_rows: list[tuple[str, str]] = []
    for chunk in _chunks(prospect_ids):
        open_rows.extend(db.execute(select(ProspectAssignment.prospect_id, ProspectAssignment.id).where(
            ProspectAssignment.prospect_id.in_(chunk),
            ProspectAssignment.status.in_(sorted(OPEN_ASSIGNMENT_STATUSES)),
        )).all())
    if open_rows:
        raise Conflict("Some prospects already have an open assignment.", details={
            "prospect_ids": sorted({prospect_id for prospect_id, _assignment_id in open_rows}),
            "assignment_ids": sorted({assignment_id for _prospect_id, assignment_id in open_rows}),
        })
    return plan, prospects


def _notify_assignment(db: Session, actor: Actor, assignment: ProspectAssignment, prospect: Prospect, *,
                       kind: str, verb: str) -> None:
    notifications.notify(
        db,
        assignment.assignee_id,
        kind=kind,
        title=f"LinkedIn prospect {verb}",
        body=f"{_prospect_title(prospect)} · due {assignment.due_on.isoformat()}"
             if assignment.due_on else _prospect_title(prospect),
        entity_type="prospect_assignment",
        entity_id=assignment.id,
        dedupe_key=f"assignment:{assignment.id}:{kind}",
        actor=actor,
    )


def create_batch(db: Session, actor: Actor, data: BatchCreate) -> AssignmentBatch:
    plan, prospects = _validate_plan(db, actor, data)
    now = utcnow()
    status = "draft" if data.draft else "active"
    batch = AssignmentBatch(name=data.name, work_date=data.work_date, status=status, notes=data.notes,
                            created_by_id=actor.user_id, created_at=now,
                            activated_at=None if data.draft else now)
    db.add(batch)
    db.flush()
    rows = [
        ProspectAssignment(
            prospect_id=prospect_id,
            assignee_id=assignee_id,
            batch_id=batch.id,
            assigned_by_id=actor.user_id,
            status="planned" if data.draft else "assigned",
            due_on=data.work_date,
            assigned_at=now,
            created_at=now,
        )
        for prospect_id, assignee_id in plan
    ]
    db.add_all(rows)
    db.flush()
    audit.record(db, actor, "assignment_batch.created", entity_type="assignment_batch", entity_id=batch.id,
                 changes={"name": batch.name, "work_date": batch.work_date, "status": batch.status,
                          "assignments": len(rows)})
    if not data.draft:
        for assignment in rows:
            _notify_assignment(db, actor, assignment, prospects[assignment.prospect_id],
                               kind="prospect_assigned", verb="assigned to you")
    return batch


def get_batch(db: Session, actor: Actor, batch_id: Any) -> AssignmentBatch:
    actor.require("assignments.manage")
    key = str(batch_id or "").strip()
    batch = db.get(AssignmentBatch, key) if key else None
    if batch is None:
        raise NotFound()
    return batch


def assignments_for_batch(db: Session, actor: Actor, batch_id: Any) -> list[ProspectAssignment]:
    batch = get_batch(db, actor, batch_id)
    return list(db.scalars(select(ProspectAssignment).where(ProspectAssignment.batch_id == batch.id)
                           .options(joinedload(ProspectAssignment.prospect),
                                    joinedload(ProspectAssignment.assignee),
                                    joinedload(ProspectAssignment.batch))
                           .order_by(ProspectAssignment.created_at, ProspectAssignment.id)))


def activate_batch(db: Session, actor: Actor, batch_id: Any, version: int | None = None) -> AssignmentBatch:
    batch = get_batch(db, actor, batch_id)
    check_version(batch, version)
    if batch.status != "draft":
        raise Conflict("Only a draft assignment batch can be activated.",
                       details={"current_status": batch.status, "current_version": batch.version})
    rows = assignments_for_batch(db, actor, batch.id)
    if not rows or any(item.status != "planned" for item in rows):
        raise Conflict("This draft changed and can no longer be activated. Reload it and review the assignments.")
    now = utcnow()
    batch.status = "active"
    batch.activated_at = now
    for assignment in rows:
        assignment.status = "assigned"
        assignment.assigned_at = now
    db.flush()
    audit.record(db, actor, "assignment_batch.activated", entity_type="assignment_batch", entity_id=batch.id,
                 changes={"status": ["draft", "active"], "assignments": len(rows)})
    for assignment in rows:
        _notify_assignment(db, actor, assignment, assignment.prospect,
                           kind="prospect_assigned", verb="assigned to you")
    return batch


def cancel_batch(db: Session, actor: Actor, batch_id: Any, version: int | None = None, *,
                 reason: str | None = None) -> AssignmentBatch:
    batch = get_batch(db, actor, batch_id)
    check_version(batch, version)
    if batch.status not in {"draft", "active"}:
        raise Conflict("This assignment batch is already closed.",
                       details={"current_status": batch.status, "current_version": batch.version})
    previous = batch.status
    now = utcnow()
    rows = list(db.scalars(select(ProspectAssignment).where(
        ProspectAssignment.batch_id == batch.id,
        ProspectAssignment.status.in_(sorted(OPEN_ASSIGNMENT_STATUSES)),
    ).options(joinedload(ProspectAssignment.prospect))))
    visible_rows = [row for row in rows if row.status != "planned"]
    for assignment in rows:
        assignment.status = "cancelled"
        assignment.closed_at = now
        assignment.closed_by_id = actor.user_id
        assignment.close_reason = reason
    batch.status = "cancelled"
    batch.cancelled_at = now
    db.flush()
    audit.record(db, actor, "assignment_batch.cancelled", entity_type="assignment_batch", entity_id=batch.id,
                 changes={"status": [previous, "cancelled"], "assignments_cancelled": len(rows),
                          "reason": reason})
    for assignment in visible_rows:
        _notify_assignment(db, actor, assignment, assignment.prospect,
                           kind="assignment_cancelled", verb="assignment cancelled")
    return batch


def _assignment_query() -> Any:
    return select(ProspectAssignment).options(joinedload(ProspectAssignment.prospect),
                                               joinedload(ProspectAssignment.assignee),
                                               joinedload(ProspectAssignment.batch))


def get_assignment(db: Session, actor: Actor, assignment_id: Any) -> ProspectAssignment:
    actor.require("prospects.view")
    key = str(assignment_id or "").strip()
    assignment = db.scalar(_assignment_query().where(ProspectAssignment.id == key)) if key else None
    if assignment is None:
        raise NotFound()
    can_view_team = actor.can("assignments.manage") or actor.can("team.view")
    if not can_view_team and assignment.assignee_id != actor.user_id:
        raise NotFound()
    return assignment


def _require_active_owner(actor: Actor, assignment: ProspectAssignment) -> None:
    scope = actor.require("outreach.record")
    if scope is Scope.OWN and assignment.assignee_id != actor.user_id:
        raise PermissionDenied("This assignment is no longer assigned to you.")
    if assignment.status not in ACTIVE_ASSIGNMENT_STATUSES:
        raise Conflict("This assignment is no longer open.",
                       details={"current_status": assignment.status, "current_version": assignment.version})


def reassign(db: Session, actor: Actor, assignment_id: Any, data: Reassignment) -> ProspectAssignment:
    actor.require("assignments.manage")
    current = get_assignment(db, actor, assignment_id)
    check_version(current, data.version)
    if current.status not in OPEN_ASSIGNMENT_STATUSES:
        raise Conflict("This assignment was already closed or reassigned.",
                       details={"current_status": current.status, "current_version": current.version})
    assignee_id = str(data.assignee_id or "").strip()
    user = db.get(User, assignee_id) if assignee_id else None
    if user is None or not user.is_active or not Actor.for_user(user).can("outreach.record"):
        raise ValidationFailed("Choose an active outreach team member.",
                               fields={"assignee_id": "Choose an active outreach team member."})
    if assignee_id == current.assignee_id:
        raise ValidationFailed("Choose a different assignee.",
                               fields={"assignee_id": "This person already owns the assignment."})

    previous_assignee = current.assignee_id
    previous_status = current.status
    now = utcnow()
    current.status = "reassigned"
    current.closed_at = now
    current.closed_by_id = actor.user_id
    current.close_reason = data.reason
    db.flush()

    successor = ProspectAssignment(
        prospect_id=current.prospect_id,
        assignee_id=assignee_id,
        batch_id=current.batch_id,
        assigned_by_id=actor.user_id,
        previous_assignment_id=current.id,
        status="planned" if previous_status == "planned" else "assigned",
        due_on=current.due_on,
        assigned_at=now,
        created_at=now,
    )
    db.add(successor)
    db.flush()

    follow_up = db.scalar(select(Task).where(Task.kind == "follow_up", Task.status == "open",
                                             Task.prospect_id == current.prospect_id))
    if follow_up is not None:
        follow_up.assigned_to_id = assignee_id
        follow_up.assignment_id = successor.id
        audit.record(db, actor, "follow_up.reassigned", entity_type="task", entity_id=follow_up.id,
                     changes={"assigned_to_id": [previous_assignee, assignee_id],
                              "assignment_id": [current.id, successor.id]})
    audit.record(db, actor, "assignment.reassigned", entity_type="prospect_assignment", entity_id=successor.id,
                 changes={"prospect_id": current.prospect_id,
                          "assignee_id": [previous_assignee, assignee_id],
                          "previous_assignment_id": current.id, "reason": data.reason})
    _notify_assignment(db, actor, successor, current.prospect,
                       kind="prospect_reassigned", verb="reassigned to you")
    return successor


def complete_assignment(db: Session, actor: Actor, assignment_id: Any, version: int | None = None, *,
                        reason: str | None = None) -> ProspectAssignment:
    assignment = get_assignment(db, actor, assignment_id)
    _require_active_owner(actor, assignment)
    check_version(assignment, version)
    previous = assignment.status
    assignment.status = "completed"
    assignment.closed_at = utcnow()
    assignment.closed_by_id = actor.user_id
    assignment.close_reason = reason
    db.flush()
    audit.record(db, actor, "assignment.completed", entity_type="prospect_assignment", entity_id=assignment.id,
                 changes={"status": [previous, "completed"], "reason": reason,
                          "prospect_id": assignment.prospect_id})
    if assignment.assigned_by_id:
        notifications.notify(db, assignment.assigned_by_id, kind="assignment_completed",
                             title="LinkedIn assignment completed", body=_prospect_title(assignment.prospect),
                             entity_type="prospect_assignment", entity_id=assignment.id,
                             dedupe_key=f"assignment:{assignment.id}:completed", actor=actor)
    return assignment


def cancel_assignment(db: Session, actor: Actor, assignment_id: Any, version: int | None = None, *,
                      reason: str | None = None) -> ProspectAssignment:
    actor.require("assignments.manage")
    assignment = get_assignment(db, actor, assignment_id)
    check_version(assignment, version)
    if assignment.status not in OPEN_ASSIGNMENT_STATUSES:
        raise Conflict("This assignment is already closed.",
                       details={"current_status": assignment.status, "current_version": assignment.version})
    previous = assignment.status
    assignment.status = "cancelled"
    assignment.closed_at = utcnow()
    assignment.closed_by_id = actor.user_id
    assignment.close_reason = reason
    db.flush()
    audit.record(db, actor, "assignment.cancelled", entity_type="prospect_assignment", entity_id=assignment.id,
                 changes={"status": [previous, "cancelled"], "reason": reason,
                          "prospect_id": assignment.prospect_id})
    if previous != "planned":
        _notify_assignment(db, actor, assignment, assignment.prospect,
                           kind="assignment_cancelled", verb="assignment cancelled")
    return assignment


def list_assignments(db: Session, actor: Actor, *, page: PageRequest, view: str = "mine",
                     status: str | None = None, due: str | None = None, q: str | None = None,
                     batch_id: str | None = None, assignee_id: str | None = None,
                     now: datetime | None = None) -> Page[ProspectAssignment]:
    actor.require("prospects.view")
    statement = (_assignment_query().join(Prospect, Prospect.id == ProspectAssignment.prospect_id)
                 .join(User, User.id == ProspectAssignment.assignee_id))
    if view == "team":
        actor.require("team.view")
        if batch_id:
            statement = statement.where(ProspectAssignment.batch_id == batch_id)
        if assignee_id:
            statement = statement.where(ProspectAssignment.assignee_id == assignee_id)
    elif view == "mine":
        statement = statement.where(ProspectAssignment.assignee_id == actor.user_id,
                                    ProspectAssignment.status != "planned")
    else:
        raise ValidationFailed("Choose whose assignments to view.", fields={"view": "Choose My Work or Team."})

    if status and status != "all":
        if status not in ASSIGNMENT_STATUSES:
            raise ValidationFailed("Choose a valid assignment status.",
                                   fields={"status": "Choose a listed status."})
        statement = statement.where(ProspectAssignment.status == status)
    elif status is None:
        statement = statement.where(ProspectAssignment.status.in_(sorted(_VISIBLE_STATUSES)))
    if q and q.strip():
        pattern = like_pattern(q)
        statement = statement.where(or_(func.lower(Prospect.full_name).like(pattern, escape="\\"),
                                        func.lower(Prospect.company).like(pattern, escape="\\"),
                                        Prospect.linkedin_key.like(pattern, escape="\\")))
    moment = now or utcnow()
    today = moment.astimezone(ZoneInfo(actor.timezone)).date()
    if due == "today":
        statement = statement.where(ProspectAssignment.due_on == today)
    elif due == "overdue":
        statement = statement.where(ProspectAssignment.due_on < today)
    elif due == "upcoming":
        statement = statement.where(ProspectAssignment.due_on > today,
                                    ProspectAssignment.due_on <= today + timedelta(days=7))
    elif due not in (None, "all"):
        raise ValidationFailed("Choose a valid due-date filter.", fields={"due": "Choose a listed filter."})
    return cast(Page[ProspectAssignment], paginate(db, cast(Any, statement), page, SORTS, "due",
                                                   tiebreaker=ProspectAssignment.id))


def open_count(db: Session, actor: Actor) -> int:
    return db.scalar(select(func.count()).select_from(ProspectAssignment).where(
        ProspectAssignment.assignee_id == actor.user_id,
        ProspectAssignment.status.in_(sorted(_VISIBLE_STATUSES)))) or 0


def list_my_work(db: Session, actor: Actor, *, page: PageRequest, status: str | None = None,
                 due: str | None = None, q: str | None = None,
                 now: datetime | None = None) -> Page[ProspectAssignment]:
    return list_assignments(db, actor, page=page, view="mine", status=status, due=due, q=q, now=now)


@dataclass(frozen=True)
class BatchSummary:
    batch: AssignmentBatch
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def list_batches(db: Session, actor: Actor, *, limit: int = 60) -> list[BatchSummary]:
    actor.require("assignments.manage")
    batches = list(db.scalars(select(AssignmentBatch).order_by(AssignmentBatch.work_date.desc(),
                                                               AssignmentBatch.created_at.desc()).limit(limit)))
    counts: dict[str, dict[str, int]] = {batch.id: {} for batch in batches}
    if batches:
        rows = db.execute(select(ProspectAssignment.batch_id, ProspectAssignment.status, func.count())
                          .where(ProspectAssignment.batch_id.in_(list(counts)))
                          .group_by(ProspectAssignment.batch_id, ProspectAssignment.status))
        for batch_id, status, number in rows:
            if batch_id is not None:
                counts[batch_id][status] = int(number)
    return [BatchSummary(batch, counts[batch.id]) for batch in batches]


@dataclass(frozen=True)
class Member:
    user_id: str
    name: str
    open_assignments: int


def assignable_members(db: Session, actor: Actor) -> list[Member]:
    actor.require("assignments.manage")
    open_work = (select(ProspectAssignment.assignee_id.label("user_id"), func.count().label("n"))
                 .where(ProspectAssignment.status.in_(sorted(_VISIBLE_STATUSES)))
                 .group_by(ProspectAssignment.assignee_id).subquery())
    rows = db.execute(select(User, func.coalesce(open_work.c.n, 0)).outerjoin(open_work, open_work.c.user_id == User.id)
                      .where(User.is_active.is_(True)).order_by(func.lower(User.full_name)))
    return [Member(user.id, user.full_name, int(count)) for user, count in rows
            if Actor.for_user(user).can("outreach.record")]


__all__ = [
    "SORTS",
    "BatchSummary",
    "Member",
    "activate_batch",
    "assignable_members",
    "list_batches",
    "open_count",
    "assignments_for_batch",
    "cancel_assignment",
    "cancel_batch",
    "complete_assignment",
    "create_batch",
    "get_assignment",
    "get_batch",
    "list_assignments",
    "list_my_work",
    "reassign",
]

