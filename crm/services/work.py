"""The signed-in user's work summary for the Dashboard: tasks due and leads waiting.

Every number is a count over current rows; nothing is cached or estimated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import utcnow
from ..models import Lead, Task
from .access import Actor
from .tasks import counts


@dataclass(frozen=True)
class WorkSummary:
    open_tasks: int
    overdue: int
    due_today: int
    my_open_leads: int
    unassigned_new_leads: int
    upcoming: list[tuple[str, str, datetime | None, bool]]  # task id, title, due, overdue


def summary(db: Session, actor: Actor, *, now: datetime | None = None) -> WorkSummary:
    current = now or utcnow()
    task_counts = counts(db, actor, now=current)
    upcoming: list[tuple[str, str, datetime | None, bool]] = []
    if actor.can("tasks.view"):
        for task in db.scalars(select(Task).where(Task.assigned_to_id == actor.user_id, Task.status == "open")
                               .options(joinedload(Task.lead))
                               .order_by(Task.due_at.is_(None), Task.due_at, Task.created_at).limit(6)):
            upcoming.append((task.id, task.title, task.due_at, task.due_at is not None and task.due_at < current))
    my_leads = unassigned = 0
    if actor.can("leads.view"):
        open_lead = Lead.status.not_in(("converted", "lost"))
        my_leads = db.scalar(select(func.count()).select_from(Lead).where(open_lead, Lead.owner_id == actor.user_id)) or 0
        unassigned = db.scalar(select(func.count()).select_from(Lead).where(
            Lead.status == "new", Lead.owner_id.is_(None))) or 0
    return WorkSummary(task_counts["open"], task_counts["overdue"], task_counts["today"], my_leads, unassigned,
                       upcoming)
