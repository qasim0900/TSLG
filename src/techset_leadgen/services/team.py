from __future__ import annotations

import csv
import io
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import Session

from techset_leadgen.database.engine import utcnow
from techset_leadgen.database.models import Organization, OutreachEvent, Prospect, ProspectAssignment, Task, User
from techset_leadgen.domain.outreach import ACTIVE_ASSIGNMENT_STATUSES
from techset_leadgen.services import audit
from techset_leadgen.services.access import Actor
from techset_leadgen.services.tasks import local_day_bounds


@dataclass(frozen=True)
class WorkloadRow:
    user_id: str
    name: str
    open_assignments: int
    completed_today: int
    overdue_follow_ups: int


@dataclass(frozen=True)
class OperationalSummary:
    timezone: str
    active_members: int
    assigned_today: int
    completed_today: int
    outstanding_assignments: int
    unassigned_prospects: int
    pending_follow_ups: int
    overdue_follow_ups: int
    due_today_follow_ups: int
    overdue_tasks: int
    workload: tuple[WorkloadRow, ...]


def _business_timezone(db: Session, actor: Actor, team_scope: bool) -> str:
    if not team_scope:
        return actor.timezone
    value = db.scalar(select(Organization.timezone).where(Organization.id == 1))
    return value or actor.timezone


def summary(db: Session, actor: Actor, *, now: datetime | None = None) -> OperationalSummary:
    can_assignments = actor.can("prospects.view")
    can_tasks = actor.can("tasks.view")
    team_scope = actor.can("team.view")
    if not can_assignments and not can_tasks:
        return OperationalSummary(actor.timezone, 1, 0, 0, 0, 0, 0, 0, 0, 0, ())

    moment = now or utcnow()
    timezone = _business_timezone(db, actor, team_scope)
    start, end = local_day_bounds(timezone, moment)

    assignment_filters = [] if team_scope else [ProspectAssignment.assignee_id == actor.user_id]
    assigned_today = completed_today = outstanding = unassigned = 0
    if can_assignments:
        assignment_base = select(func.count()).select_from(ProspectAssignment).where(*assignment_filters)
        assigned_today = db.scalar(assignment_base.where(
            ProspectAssignment.status != "planned",
            ProspectAssignment.assigned_at >= start,
            ProspectAssignment.assigned_at < end,
        )) or 0
        completed_today = db.scalar(assignment_base.where(
            ProspectAssignment.status == "completed",
            ProspectAssignment.closed_at >= start,
            ProspectAssignment.closed_at < end,
        )) or 0
        outstanding = db.scalar(assignment_base.where(
            ProspectAssignment.status.in_(sorted(ACTIVE_ASSIGNMENT_STATUSES)))) or 0
        if team_scope:
            has_open = exists(select(ProspectAssignment.id).where(
                ProspectAssignment.prospect_id == Prospect.id,
                ProspectAssignment.status.in_(sorted(ACTIVE_ASSIGNMENT_STATUSES | {"planned"})),
            ))
            unassigned = db.scalar(select(func.count()).select_from(Prospect).where(~has_open)) or 0

    task_filters = [] if team_scope else [Task.assigned_to_id == actor.user_id]
    pending = overdue_followups = due_today = overdue_tasks = 0
    if can_tasks:
        open_tasks = select(func.count()).select_from(Task).where(Task.status == "open", *task_filters)
        pending = db.scalar(open_tasks.where(Task.kind == "follow_up")) or 0
        overdue_followups = db.scalar(open_tasks.where(
            Task.kind == "follow_up", Task.due_at.is_not(None), Task.due_at < moment)) or 0
        due_today = db.scalar(open_tasks.where(
            Task.kind == "follow_up", Task.due_at >= start, Task.due_at < end)) or 0
        overdue_tasks = db.scalar(open_tasks.where(
            Task.kind == "task", Task.due_at.is_not(None), Task.due_at < moment)) or 0

    workload = tuple(_workload(db, start=start, end=end, now=moment)) if team_scope else ()
    active_members = (db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
                      if team_scope else 1)
    return OperationalSummary(
        timezone, active_members, assigned_today, completed_today, outstanding, unassigned,
        pending, overdue_followups, due_today, overdue_tasks, workload,
    )


def _workload(db: Session, *, start: datetime, end: datetime, now: datetime) -> list[WorkloadRow]:
    assignments = (select(
        ProspectAssignment.assignee_id.label("user_id"),
        func.count(ProspectAssignment.id).label("open_count"),
    ).where(ProspectAssignment.status.in_(sorted(ACTIVE_ASSIGNMENT_STATUSES)))
      .group_by(ProspectAssignment.assignee_id).subquery())
    completed = (select(
        ProspectAssignment.assignee_id.label("user_id"),
        func.count(ProspectAssignment.id).label("completed_count"),
    ).where(ProspectAssignment.status == "completed",
            ProspectAssignment.closed_at >= start, ProspectAssignment.closed_at < end)
      .group_by(ProspectAssignment.assignee_id).subquery())
    overdue = (select(
        Task.assigned_to_id.label("user_id"),
        func.count(Task.id).label("overdue_count"),
    ).where(Task.kind == "follow_up", Task.status == "open", Task.due_at.is_not(None), Task.due_at < now)
      .group_by(Task.assigned_to_id).subquery())
    statement = (select(
        User.id,
        User.full_name,
        func.coalesce(assignments.c.open_count, 0),
        func.coalesce(completed.c.completed_count, 0),
        func.coalesce(overdue.c.overdue_count, 0),
    ).outerjoin(assignments, assignments.c.user_id == User.id)
      .outerjoin(completed, completed.c.user_id == User.id)
      .outerjoin(overdue, overdue.c.user_id == User.id)
      .where(User.is_active.is_(True))
      .order_by(func.coalesce(assignments.c.open_count, 0).desc(), func.lower(User.full_name)))
    return [WorkloadRow(user_id, name, int(open_count), int(completed_count), int(overdue_count))
            for user_id, name, open_count, completed_count, overdue_count in db.execute(statement)]


@dataclass(frozen=True)
class DailyRow:
    user_id: str
    name: str
    assigned: int = 0
    completed: int = 0
    connection_requests: int = 0
    messages: int = 0
    replies: int = 0
    meetings: int = 0
    follow_ups_scheduled: int = 0
    follow_ups_done: int = 0
    open_assignments: int = 0
    open_tasks: int = 0
    overdue_follow_ups: int = 0


COUNT_FIELDS = tuple(item.name for item in fields(DailyRow))[2:]
COLUMN_LABELS = {
    "assigned": "Profiles assigned", "completed": "Assignments completed",
    "connection_requests": "Connection requests", "messages": "Messages sent", "replies": "Replies received",
    "meetings": "Meetings requested", "follow_ups_scheduled": "Follow-ups scheduled",
    "follow_ups_done": "Follow-ups done", "open_assignments": "Open assignments", "open_tasks": "Open tasks",
    "overdue_follow_ups": "Overdue follow-ups",
}


@dataclass(frozen=True)
class DailySummary:
    day: date
    timezone: str
    rows: tuple[DailyRow, ...]

    @property
    def totals(self) -> DailyRow:
        return DailyRow("", "Team total", *(sum(getattr(row, name) for row in self.rows) for name in COUNT_FIELDS))


def day_bounds(timezone: str, day: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def _count_by(column: Any, *conditions: Any, label: str) -> Any:
    return (select(column.label("user_id"), func.count().label(label)).where(*conditions)
            .group_by(column).subquery())


def _event_counts(start: datetime, end: datetime) -> Any:
    def kind(event_type: str) -> Any:
        return func.sum(case((OutreachEvent.event_type == event_type, 1), else_=0))

    return (select(OutreachEvent.recorded_by_id.label("user_id"),
                   kind("connection_sent").label("connection_requests"),
                   kind("message_sent").label("messages"),
                   kind("reply_received").label("replies"),
                   kind("meeting_requested").label("meetings"))
            .where(OutreachEvent.occurred_at >= start, OutreachEvent.occurred_at < end)
            .group_by(OutreachEvent.recorded_by_id).subquery())


def daily_summary(db: Session, actor: Actor, day: date | None = None, *,
                  now: datetime | None = None) -> DailySummary:
    actor.require("prospects.view")
    team_scope = actor.can("team.view")
    moment = now or utcnow()
    timezone = _business_timezone(db, actor, team_scope)
    chosen = day or moment.astimezone(ZoneInfo(timezone)).date()
    start, end = day_bounds(timezone, chosen)
    assigned = _count_by(ProspectAssignment.assignee_id, ProspectAssignment.status != "planned",
                         ProspectAssignment.assigned_at >= start, ProspectAssignment.assigned_at < end,
                         label="n")
    completed = _count_by(ProspectAssignment.assignee_id, ProspectAssignment.status == "completed",
                          ProspectAssignment.closed_at >= start, ProspectAssignment.closed_at < end, label="n")
    scheduled = _count_by(Task.created_by_id, Task.kind == "follow_up", Task.created_at >= start,
                          Task.created_at < end, label="n")
    done = _count_by(Task.assigned_to_id, Task.kind == "follow_up", Task.status == "done",
                     Task.completed_at >= start, Task.completed_at < end, label="n")
    open_assignments = _count_by(ProspectAssignment.assignee_id,
                                 ProspectAssignment.status.in_(sorted(ACTIVE_ASSIGNMENT_STATUSES)), label="n")
    open_tasks = _count_by(Task.assigned_to_id, Task.kind == "task", Task.status == "open", label="n")
    overdue = _count_by(Task.assigned_to_id, Task.kind == "follow_up", Task.status == "open",
                        Task.due_at.is_not(None), Task.due_at < moment, label="n")
    events = _event_counts(start, end)
    counted = (assigned, completed, events, scheduled, done, open_assignments, open_tasks, overdue)
    zero = func.coalesce
    statement = select(
        User.id, User.full_name,
        zero(assigned.c.n, 0), zero(completed.c.n, 0),
        zero(events.c.connection_requests, 0), zero(events.c.messages, 0), zero(events.c.replies, 0),
        zero(events.c.meetings, 0), zero(scheduled.c.n, 0), zero(done.c.n, 0),
        zero(open_assignments.c.n, 0), zero(open_tasks.c.n, 0), zero(overdue.c.n, 0),
    )
    for subquery in counted:
        statement = statement.outerjoin(subquery, subquery.c.user_id == User.id)
    if team_scope:
        statement = statement.where(User.is_active.is_(True))
    else:
        statement = statement.where(User.id == actor.user_id)
    rows = tuple(DailyRow(user_id, name, *(int(value) for value in values))
                 for user_id, name, *values in db.execute(statement.order_by(func.lower(User.full_name))))
    return DailySummary(chosen, timezone, rows)


def _cell(value: object) -> object:
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_daily_summary(db: Session, actor: Actor, day: date | None = None, *,
                         now: datetime | None = None) -> tuple[DailySummary, str]:
    actor.require("data.export")
    result = daily_summary(db, actor, day, now=now)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Time zone", "Team member", *(COLUMN_LABELS[name] for name in COUNT_FIELDS)])
    for row in (*result.rows, result.totals):
        writer.writerow([result.day.isoformat(), result.timezone, _cell(row.name),
                         *(getattr(row, name) for name in COUNT_FIELDS)])
    audit.record(db, actor, "report.exported", entity_type="report", entity_id="daily_summary",
                 changes={"day": result.day.isoformat(), "rows": len(result.rows)})
    return result, buffer.getvalue()


__all__ = ["COLUMN_LABELS", "COUNT_FIELDS", "DailyRow", "DailySummary", "OperationalSummary", "WorkloadRow",
           "daily_summary", "day_bounds", "export_daily_summary", "summary"]

