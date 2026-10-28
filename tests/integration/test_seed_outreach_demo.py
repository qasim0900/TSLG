"""The outreach demo seeder fills a realistic team day through the services, and removes exactly what it added."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from techset_leadgen.database.engine import utcnow
from techset_leadgen.database.models import (
    AssignmentBatch, Notification, OutreachEvent, Prospect, ProspectAssignment, Task, User,
)
from techset_leadgen.services import team

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_outreach_demo.py"


@pytest.fixture(scope="module")
def seeder():
    spec = importlib.util.spec_from_file_location("seed_outreach_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _count(db, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def test_demo_data_covers_the_daily_workflow_and_is_removed_cleanly(db, acme, settings, seeder):
    real_users = _count(db, User)
    db.rollback()  # end this read: SQLite lets only one connection write at a time
    counts = seeder.seed(settings, say=lambda _line: None)
    db.expire_all()
    demo = User.email.like(f"%@{seeder.DEMO_DOMAIN}")
    assert _count(db, User, demo) == 7
    assert _count(db, Prospect, Prospect.source == seeder.DEMO_SOURCE) == 150
    assert _count(db, AssignmentBatch) == 7 and counts["events"] > 100
    assert _count(db, AssignmentBatch, AssignmentBatch.status == "draft") == 1
    assert _count(db, ProspectAssignment, ProspectAssignment.status == "reassigned") == 2
    assert _count(db, ProspectAssignment, ProspectAssignment.status == "cancelled") == 1
    assert _count(db, ProspectAssignment, ProspectAssignment.status == "completed") > 10
    now = utcnow()
    follow_ups = Task.kind == "follow_up"
    assert _count(db, Task, follow_ups, Task.status == "open", Task.due_at < now) > 0  # overdue
    assert _count(db, Task, follow_ups, Task.status == "open", Task.due_at > now) > 0  # upcoming
    assert _count(db, Task, Task.kind == "task") == len(seeder.GENERAL_TASKS)
    assert _count(db, Notification, Notification.read_at.is_(None)) > 0
    # Nothing is dated in the future, and outcomes never precede their assignment.
    latest = now + timedelta(seconds=5)
    assert db.scalar(select(func.max(OutreachEvent.occurred_at))) <= latest
    assert db.scalar(select(func.max(ProspectAssignment.closed_at))) <= latest
    assert db.scalar(select(func.max(ProspectAssignment.assigned_at))) <= latest
    assert _count(db, OutreachEvent, ProspectAssignment.id == OutreachEvent.assignment_id,
                  OutreachEvent.occurred_at < ProspectAssignment.assigned_at) == 0
    # The past work shows on the manager's end-of-day summaries.
    manager = db.scalar(select(User).where(User.email == f"ayesha.malik@{seeder.DEMO_DOMAIN}"))
    from techset_leadgen.services.access import Actor

    days = seeder.working_days_before(utcnow().date(), 5)
    summary = team.daily_summary(db, Actor.for_user(manager), days[-1])
    assert summary.totals.assigned == 16 and summary.totals.connection_requests > 0

    db.rollback()
    with pytest.raises(SystemExit, match="already"):
        seeder.seed(settings, say=lambda _line: None)

    seeder.remove(settings, say=lambda _line: None)
    db.expire_all()
    assert _count(db, User) == real_users and _count(db, User, demo) == 0
    for model in (Prospect, ProspectAssignment, OutreachEvent, Task, AssignmentBatch, Notification):
        assert _count(db, model) == 0, model.__name__


def test_an_empty_database_gets_a_demo_organization(tmp_path, migrated_template, seeder):
    from techset_leadgen.config import load_settings

    database = tmp_path / "empty.db"
    database.write_bytes(migrated_template.read_bytes())
    settings = load_settings({}, database_path=database)
    seeder.seed(settings, say=lambda _line: None)
    from techset_leadgen.database.engine import create_db_engine, create_session_factory

    engine = create_db_engine(settings)
    with create_session_factory(engine)() as db:
        assert db.scalar(select(User.role).where(User.email == f"admin@{seeder.DEMO_DOMAIN}")) == "super_admin"
    engine.dispose()


def test_outcomes_never_precede_their_assignment_early_in_the_business_day(db, acme, settings, seeder):
    """Regression (QA BUG-106): before 10:00 business time, today's batch is clamped to "a few minutes
    ago"; outcomes recorded on it must still come after the assignment. The business time zone is
    chosen so that it is 06:00 there now, whatever the time of the test run."""
    from datetime import UTC, datetime

    offset = (6 - datetime.now(UTC).hour) % 24
    offset = offset - 24 if offset > 11 else offset
    acme.organization.timezone = f"Etc/GMT{-offset:+d}" if offset else "UTC"  # Etc/GMT-5 is UTC+5
    db.commit()
    seeder.seed(settings, say=lambda _line: None)
    db.expire_all()
    assert _count(db, OutreachEvent, ProspectAssignment.id == OutreachEvent.assignment_id,
                  OutreachEvent.occurred_at < ProspectAssignment.assigned_at) == 0
    assert _count(db, ProspectAssignment, ProspectAssignment.closed_at < ProspectAssignment.assigned_at) == 0
