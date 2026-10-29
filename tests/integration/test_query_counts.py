from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event

from techset_leadgen.database.models import (
    AssignmentBatch,
    Notification,
    OutreachEvent,
    Prospect,
    ProspectAssignment,
    Task,
    User,
)
from techset_leadgen.services import assignments, notifications, prospects, tasks, team
from techset_leadgen.services.pagination import PageRequest

pytest.importorskip("PySide6.QtWidgets")
from techset_leadgen.desktop.pages.assignment_pages import AssignmentsPage
from techset_leadgen.desktop.pages.outreach_pages import FollowUpsPage, MyWorkPage
from techset_leadgen.desktop.pages.prospects_page import ProspectsPage

NOW = datetime(2026, 10, 27, 9, tzinfo=UTC)


@contextmanager
def counting(db) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = db.get_bind()

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _seed(db, acme, rows: int) -> tuple[Any, Any]:
    manager, member = acme.users["sales_manager"], acme.users["bdr"]
    other = acme.users["account_executive"]
    batch = AssignmentBatch(name="Batch", work_date=date(2026, 10, 27), status="active", created_by_id=manager.id)
    db.add(batch)
    db.flush()
    for number in range(rows):
        key = f"in/p-{uuid.uuid4().hex[:10]}"
        prospect = Prospect(linkedin_key=key, linkedin_url=f"https://www.linkedin.com/{key}/",
                            full_name=f"Person {number}", company="Acme", status="connection_sent",
                            created_by_id=manager.id, last_activity_at=NOW)
        db.add(prospect)
        db.flush()
        assignee = member if number % 2 == 0 else other
        assignment = ProspectAssignment(prospect_id=prospect.id, assignee_id=assignee.id, batch_id=batch.id,
                                        assigned_by_id=manager.id, status="in_progress", due_on=date(2026, 10, 27),
                                        assigned_at=NOW)
        db.add(assignment)
        db.flush()
        db.add(OutreachEvent(prospect_id=prospect.id, assignment_id=assignment.id, event_type="connection_sent",
                             occurred_at=NOW, recorded_by_id=assignee.id))
        db.add(Task(title=f"Follow up {number}", kind="follow_up", prospect_id=prospect.id,
                    assignment_id=assignment.id, assigned_to_id=assignee.id, priority="medium",
                    due_at=NOW + timedelta(days=1), status="open", created_by_id=assignee.id))
        db.add(Notification(recipient_id=member.id, kind="prospect_assigned", title=f"Assigned {number}"))
    db.commit()
    return acme.actor("sales_manager"), acme.actor("bdr")


def _statements(db, work: Callable[[], Any]) -> int:
    db.expire_all()
    with counting(db) as statements:
        work()
    return len(statements)


SCREENS: dict[str, Callable[[Any, Any, Any, int], Any]] = {
    "prospects page": lambda db, manager, _member, size: ProspectsPage.fetch(
        None, db, manager, PageRequest(page_size=size), {}),
    "assignments page": lambda db, manager, _member, size: AssignmentsPage.fetch(
        None, db, manager, PageRequest(page_size=size), {"status": "all"}),
    "my work page": lambda db, _manager, member, size: MyWorkPage.fetch(
        None, db, member, PageRequest(page_size=size), {}),
    "follow-ups page (team)": lambda db, manager, _member, size: FollowUpsPage.fetch(
        None, db, manager, PageRequest(page_size=size), {"due": "open", "view": "team"}),
    "notifications": lambda db, _manager, member, size: notifications.list_notifications(
        db, member, page=PageRequest(page_size=size)).items,
    "team workload": lambda db, manager, _member, _size: team.summary(db, manager, now=NOW),
    "end-of-day summary": lambda db, manager, _member, _size: team.daily_summary(db, manager, NOW.date(), now=NOW),
    "batches": lambda db, manager, _member, _size: assignments.list_batches(db, manager),
    "assignable members": lambda db, manager, _member, _size: assignments.assignable_members(db, manager),
    "team follow-up list": lambda db, manager, _member, size: [
        (task.prospect.full_name, task.assigned_to.full_name) for task in tasks.list_tasks(
            db, manager, page=PageRequest(page_size=size), kind="follow_up", view="team").items],
}


@pytest.mark.parametrize("screen", SCREENS)
def test_statement_count_does_not_grow_with_the_rows_shown(world, screen):
    counts = []
    for rows in (5, 50):
        acme = world.team(name="Techset Solutions")
        manager, member = _seed(world.db, acme, rows)
        counts.append(_statements(world.db, lambda: SCREENS[screen](world.db, manager, member, rows)))
    small, large = counts
    assert large == small, f"{screen}: {small} statements for 5 rows but {large} for 50 (a query per row?)"
    assert small <= 12, f"{screen}: {small} statements for one page"


def test_prospect_history_is_bounded_whatever_its_length(world):
    counts = []
    for events in (5, 80):
        acme = world.team(name="Techset Solutions")
        manager, _member = _seed(world.db, acme, 1)
        prospect = world.db.query(Prospect).order_by(Prospect.created_at.desc()).first()
        for number in range(events):
            world.db.add(OutreachEvent(prospect_id=prospect.id, event_type="note", note=str(number),
                                       occurred_at=NOW - timedelta(minutes=number)))
        world.db.commit()
        counts.append(_statements(world.db, lambda: prospects.history(world.db, manager, prospect, limit=50)))
    assert counts[0] == counts[1], counts


def test_members_list_grows_without_queries_per_person(world, password_hash):
    acme = world.team(name="Techset Solutions")
    manager = acme.actor("sales_manager")
    before = _statements(world.db, lambda: assignments.assignable_members(world.db, manager))
    for number in range(25):
        world.db.add(User(email=f"extra{number}@example.com", full_name=f"Extra {number}", role="bdr",
                          password_hash=password_hash, is_active=True))
    world.db.commit()
    assert _statements(world.db, lambda: assignments.assignable_members(world.db, manager)) == before


def test_an_import_does_not_query_or_insert_per_profile(world):
    acme = world.team(name="Techset Solutions")
    manager = acme.actor("sales_manager")
    counts = []
    for size in (10, 300):
        tag = uuid.uuid4().hex[:6]
        rows = prospects.rows_from_text("\n".join(f"linkedin.com/in/import-{tag}-{n}" for n in range(size)))
        counts.append(_statements(world.db, lambda: prospects.import_rows(world.db, manager, rows, source="x")))
        world.db.commit()
    assert counts[0] == counts[1], counts

