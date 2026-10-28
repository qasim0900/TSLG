"""Measure the outreach screens' queries on a realistic team-sized dataset (p50/p95, milliseconds).

Builds a throw-away database (a temporary SQLite file, or a new database on the
PostgreSQL server given with --postgres ADMIN_URL), seeds it through the same
models the application uses, and times each screen's service call. Nothing
touches the application's own data.

    poetry run python scripts/benchmark_outreach.py [--prospects 5000] [--members 25] [--postgres URL]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import create_engine, pool, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from techset_leadgen.config import settings_for_url  # noqa: E402
from techset_leadgen.database import migrations_util  # noqa: E402
from techset_leadgen.database.engine import create_db_engine, create_session_factory  # noqa: E402
from techset_leadgen.database.models import (  # noqa: E402
    AssignmentBatch, Organization, OutreachEvent, Prospect, ProspectAssignment, Task, User,
)
from techset_leadgen.services import assignments, prospects, tasks, team  # noqa: E402
from techset_leadgen.services.access import Actor  # noqa: E402
from techset_leadgen.services.pagination import PageRequest  # noqa: E402

NOW = datetime(2026, 10, 27, 9, tzinfo=UTC)
EVENTS = ("connection_sent", "connection_accepted", "message_sent", "reply_received")


def seed(factory, prospect_count: int, member_count: int) -> tuple[Actor, Actor]:
    with factory() as db:
        db.add(Organization(id=1, name="Benchmark"))
        manager = User(email="manager@bench.example", full_name="Manager", role="sales_manager", is_active=True)
        members = [User(email=f"m{n}@bench.example", full_name=f"Member {n:02d}", role="bdr", is_active=True)
                   for n in range(member_count)]
        db.add_all([manager, *members])
        db.flush()
        days = 20
        for day in range(days):
            db.add(AssignmentBatch(id=f"batch-{day}", name=f"Day {day}", work_date=date(2026, 10, 7) + timedelta(day),
                                   status="active", created_by_id=manager.id))
        db.flush()
        # One list per table, flushed in foreign-key order (events and tasks name their prospect by id only).
        layers: dict[str, list[object]] = {"prospects": [], "assignments": [], "children": []}
        for number in range(prospect_count):
            prospect_id = str(uuid.uuid4())
            member = members[number % member_count]
            day = number % days
            closed = number % 3 == 0
            assignment_id = str(uuid.uuid4())
            layers["prospects"].append(Prospect(
                id=prospect_id, linkedin_key=f"in/bench-{number}", linkedin_url=f"https://www.linkedin.com/in/bench-{number}/",
                full_name=f"Prospect {number}", company=f"Company {number % 400}", status="messaged",
                created_by_id=manager.id, last_activity_at=NOW))
            layers["assignments"].append(ProspectAssignment(
                id=assignment_id, prospect_id=prospect_id, assignee_id=member.id, batch_id=f"batch-{day}",
                assigned_by_id=manager.id, status="completed" if closed else "in_progress",
                due_on=date(2026, 10, 7) + timedelta(day), assigned_at=NOW - timedelta(days=days - day),
                closed_at=NOW if closed else None))
            for index, kind in enumerate(EVENTS[: 1 + number % 4]):
                layers["children"].append(OutreachEvent(
                    prospect_id=prospect_id, assignment_id=assignment_id, event_type=kind,
                    occurred_at=NOW - timedelta(hours=index), recorded_by_id=member.id))
            if not closed:
                layers["children"].append(Task(
                    title=f"Follow up {number}", kind="follow_up", prospect_id=prospect_id,
                    assignment_id=assignment_id, assigned_to_id=member.id, priority="medium",
                    due_at=NOW + timedelta(hours=number % 96 - 48), status="open", created_by_id=member.id))
        for layer in layers.values():
            for start in range(0, len(layer), 5000):
                db.add_all(layer[start:start + 5000])
                db.flush()
                db.expunge_all()
        db.commit()
        return Actor.for_user(manager), Actor.for_user(members[0])


def measure(factory, name: str, work: Callable, repeat: int) -> tuple[str, float, float]:
    timings = []
    for _ in range(repeat):
        with factory() as db:
            start = time.perf_counter()
            work(db)
            timings.append((time.perf_counter() - start) * 1000)
            db.rollback()
    timings.sort()
    p95 = timings[min(len(timings) - 1, round(0.95 * (len(timings) - 1)))]
    return name, statistics.median(timings), p95


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prospects", type=int, default=5000)
    parser.add_argument("--members", type=int, default=25)
    parser.add_argument("--repeat", type=int, default=40)
    parser.add_argument("--postgres", help="admin URL of a PostgreSQL server that may create databases")
    options = parser.parse_args()

    cleanup: Callable[[], None] = lambda: None  # noqa: E731
    if options.postgres:
        admin = create_engine(make_url(options.postgres).set(drivername="postgresql+psycopg"),
                              poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
        name = f"tslg_bench_{uuid.uuid4().hex[:8]}"
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = make_url(options.postgres).set(drivername="postgresql+psycopg", database=name)
        url_text = url.render_as_string(hide_password=False)

        def drop() -> None:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            admin.dispose()

        cleanup = drop
        label = "PostgreSQL"
    else:
        folder = tempfile.mkdtemp(prefix="tslg-bench-")
        url_text = f"sqlite:///{Path(folder) / 'bench.db'}"
        label = "SQLite"
    try:
        migrations_util.upgrade(url_text)
        engine = create_db_engine(settings_for_url(url_text))
        factory = create_session_factory(engine)
        started = time.perf_counter()
        manager, member = seed(factory, options.prospects, options.members)
        print(f"{label}: seeded {options.prospects} prospects, {options.members} members "
              f"in {time.perf_counter() - started:.1f} s")
        page = PageRequest(page_size=50)
        cases = [
            ("Prospects page (50 rows, newest)", lambda db: prospects.list_prospects(db, manager, page=page)),
            ("Prospects search", lambda db: prospects.list_prospects(db, manager, page=page, q="company 12")),
            ("Team assignments page", lambda db: assignments.list_assignments(db, manager, page=page, view="team")),
            ("My Work page", lambda db: assignments.list_my_work(db, member, page=page)),
            ("Team follow-ups: overdue", lambda db: tasks.list_tasks(db, manager, page=page, kind="follow_up",
                                                                     view="team", due="overdue", now=NOW)),
            ("Dashboard (team KPIs + workload)", lambda db: team.summary(db, manager, now=NOW)),
            ("End-of-day summary", lambda db: team.daily_summary(db, manager, NOW.date(), now=NOW)),
            ("Assignable members", lambda db: assignments.assignable_members(db, manager)),
        ]
        print(f"{'Operation':<36}{'p50 ms':>10}{'p95 ms':>10}")
        for case_name, work in cases:
            _name, p50, p95 = measure(factory, case_name, work, options.repeat)
            print(f"{case_name:<36}{p50:>10.1f}{p95:>10.1f}")
        rows = prospects.rows_from_text("\n".join(f"linkedin.com/in/import-{n}" for n in range(2000)))
        with factory() as db:
            start = time.perf_counter()
            prospects.import_rows(db, manager, rows, source="Benchmark")
            db.commit()
            print(f"{'Import 2,000 new profiles':<36}{(time.perf_counter() - start) * 1000:>10.0f} (one run)")
        engine.dispose()
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
