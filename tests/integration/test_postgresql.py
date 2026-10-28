"""The shared team database: the same migrations, workflow, and concurrency rules on a real PostgreSQL server.

Runs only when ``TSLG_TEST_POSTGRES_URL`` names a server account that may create
databases, e.g. ``postgresql://admin:secret@127.0.0.1:5432/postgres``. Each test
gets a new, empty database that is dropped afterwards.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, pool, select, text
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from techset_leadgen.config import Settings, settings_for_url
from techset_leadgen.database import migrations_util, transfer
from techset_leadgen.database.engine import create_db_engine, create_session_factory
from techset_leadgen.database.models import (
    Client, Meeting, MeetingAttendee, Notification, OutreachEvent, ProspectAssignment, Task, User,
)
from techset_leadgen.errors import Conflict
from techset_leadgen.services import assignments, meetings, outreach, prospects, tasks, team
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.services.schemas import (
    AvailabilityQuery, BatchCreate, MeetingCreate, MeetingReschedule, OutreachRecord, Reassignment,
    SchedulingRulesUpdate, parse,
)

from tests.integration.conftest import Team, World

ADMIN_URL = os.environ.get("TSLG_TEST_POSTGRES_URL", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not ADMIN_URL, reason="TSLG_TEST_POSTGRES_URL is not set")]
NOW = datetime(2026, 10, 27, 9, tzinfo=UTC)


def _admin_engine():
    return create_engine(make_url(ADMIN_URL).set(drivername="postgresql+psycopg"),
                         poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")


def _new_database() -> Iterator[str]:
    name = f"tslg_test_{uuid.uuid4().hex[:12]}"
    admin = _admin_engine()
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(drivername="postgresql+psycopg", database=name)
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture()
def empty_server_url() -> Iterator[str]:
    yield from _new_database()


@pytest.fixture()
def spare_server_url() -> Iterator[str]:
    """A second new, empty database (somewhere to restore a backup)."""
    yield from _new_database()


@pytest.fixture()
def server_url(empty_server_url: str) -> str:
    migrations_util.upgrade(empty_server_url)
    return empty_server_url


@pytest.fixture()
def pg_factory(server_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_db_engine(settings_for_url(server_url))
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture()
def pg(pg_factory) -> Iterator[Session]:
    with pg_factory() as session:
        yield session


@pytest.fixture()
def pg_team(pg, password_hash) -> Team:
    return World(pg, password_hash).team()


def _import_and_assign(db, manager, member_id: str, count: int = 2) -> list[str]:
    text_rows = "\n".join(f"linkedin.com/in/pg-person-{number}" for number in range(count))
    ids = prospects.import_rows(db, manager, prospects.rows_from_text(text_rows), source="Pasted").prospect_ids
    assignments.create_batch(db, manager, parse(BatchCreate, {
        "name": "Server batch", "work_date": date(2026, 10, 27),
        "plan": [{"prospect_id": prospect_id, "assignee_id": member_id} for prospect_id in ids]}))
    db.commit()
    return ids


# --- schema ----------------------------------------------------------------------------------

def test_migrations_build_the_unified_layout_and_are_idempotent(server_url):
    engine = create_db_engine(settings_for_url(server_url))
    with engine.connect() as connection:
        state = migrations_util.schema_state(connection)
        assert state.ready and migrations_util.layout_problems(connection) == []
        kinds = dict(connection.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'clients' AND column_name IN ('created_at', 'id')")).all())
    engine.dispose()
    assert kinds == {"created_at": "timestamp without time zone", "id": "text"}
    migrations_util.upgrade(server_url)  # already at head: nothing to do, nothing breaks


# --- the workflow on the server --------------------------------------------------------------

def test_outreach_workflow_runs_unchanged_on_postgresql(pg, pg_team):
    manager, ali, sara = pg_team.actor("sales_manager"), pg_team.actor("bdr"), pg_team.actor("account_executive")
    ids = _import_and_assign(pg, manager, ali.user_id)
    outreach.record_event(pg, ali, parse(OutreachRecord, {
        "prospect_id": ids[0], "event_type": "follow_up_requested", "request_id": "pg-req-0001",
        "follow_up_at": (NOW + timedelta(days=3)).isoformat()}), now=NOW)
    pg.commit()
    follow_up = tasks.get_open_follow_up(pg, ali, ids[0])
    assert follow_up is not None and follow_up.due_at == NOW + timedelta(days=3)
    old = prospects.open_assignment(pg, ids[0])
    assignments.reassign(pg, manager, old.id, parse(Reassignment, {"assignee_id": sara.user_id,
                                                                    "version": old.version}))
    pg.commit()
    assert tasks.get_open_follow_up(pg, sara, ids[0]).assigned_to_id == sara.user_id
    page = assignments.list_assignments(pg, manager, page=PageRequest(page_size=10), view="team", status="all")
    assert page.total == 3  # the reassigned row is kept as history
    summary = team.daily_summary(pg, manager, NOW.date(), now=NOW + timedelta(hours=1))
    assert {row.user_id: row.replies for row in summary.rows}[ali.user_id] == 0


# --- concurrency ------------------------------------------------------------------------------

def test_two_managers_assigning_the_same_prospect_at_once_cannot_both_win(pg, pg_team, pg_factory):
    manager, ali, sara = pg_team.actor("sales_manager"), pg_team.actor("bdr"), pg_team.actor("account_executive")
    ids = prospects.import_rows(pg, manager, prospects.rows_from_text("linkedin.com/in/contested"),
                                source="Pasted").prospect_ids
    pg.commit()

    def assign_to(member_id: str):
        def work(session: Session) -> None:
            assignments.create_batch(session, manager, parse(BatchCreate, {
                "name": "Race", "work_date": date(2026, 10, 27),
                "plan": [{"prospect_id": ids[0], "assignee_id": member_id}]}))
        return work

    outcomes = _race_pair(pg_factory, assign_to(ali.user_id), assign_to(sara.user_id))
    failures = [outcome for outcome in outcomes if outcome is not None]
    assert len(failures) == 1 and isinstance(failures[0], IntegrityError | Conflict)
    open_rows = pg.scalar(select(func.count()).select_from(ProspectAssignment).where(
        ProspectAssignment.prospect_id == ids[0], ProspectAssignment.status == "assigned"))
    assert open_rows == 1


# --- meetings ---------------------------------------------------------------------------------

MEETING_DAY = datetime(2026, 11, 2, tzinfo=UTC)  # a Monday after NOW


def _pg_client(db: Session, name: str, email: str) -> str:
    client = Client(id=f"PG_{uuid.uuid4().hex[:8]}", name=name, cif="-", email=email)
    db.add(client)
    db.commit()
    return client.id


def _meeting(client_id: str, attendee_ids: list[str], hour: int, minute: int = 0, *, minutes: int = 30,
             title: str = "Discovery call"):
    start = MEETING_DAY.replace(hour=hour, minute=minute)
    return parse(MeetingCreate, {"title": title, "client_id": client_id, "attendee_ids": attendee_ids,
                                 "starts_at": start, "ends_at": start + timedelta(minutes=minutes),
                                 "link": "https://meet.example.com/pg", "request_id": uuid.uuid4().hex})


def test_meeting_scheduling_runs_on_postgresql(pg, pg_team):
    manager = pg_team.actor("sales_manager")
    bdr, executive = pg_team.users["bdr"].id, pg_team.users["account_executive"].id
    client_id = _pg_client(pg, "Smith Holdings", "john@example.com")
    first = meetings.create_meeting(pg, manager, _meeting(client_id, [bdr, executive], 10), now=NOW)
    pg.commit()

    assert [choice.id for choice in meetings.search_clients(pg, manager, "JOHN@example")] == [client_id]
    query = parse(AvailabilityQuery, {"client_id": client_id, "attendee_ids": [bdr],
                                      "starts_at": MEETING_DAY.replace(hour=10, minute=15),
                                      "ends_at": MEETING_DAY.replace(hour=10, minute=45)})
    result = meetings.check_availability(pg, manager, query, now=NOW)
    assert result.client_conflicts[0].message.startswith(
        "This client already has a meeting scheduled from 10:00 AM to 10:30 AM")
    assert result.suggestions[0].starts_at == MEETING_DAY.replace(hour=12, minute=30)
    moved = meetings.reschedule_meeting(pg, manager, first.id, parse(MeetingReschedule, {
        "starts_at": MEETING_DAY.replace(hour=12, minute=30), "ends_at": MEETING_DAY.replace(hour=13),
        "version": first.version}), now=NOW)
    pg.commit()
    assert moved.starts_at == MEETING_DAY.replace(hour=12, minute=30)
    second = meetings.create_meeting(pg, manager, _meeting(client_id, [executive], 15, minutes=60), now=NOW)
    pg.commit()
    meetings.update_scheduling_rules(pg, pg_team.actor("super_admin"), parse(SchedulingRulesUpdate, {
        "buffer_mode": "around", "buffer_minutes": 120, "day_start": 540, "day_end": 1080,
        "work_days": ["1", "2", "3", "4", "5"]}))
    pg.commit()
    assert meetings.meeting_counts(pg, manager, now=NOW)["conflicts"] == 2
    assert meetings.list_meetings(pg, manager, page=PageRequest(), view="conflicts", now=NOW).total == 2
    assert meetings.list_meetings(pg, manager, page=PageRequest(), q="john@example.com").total == 2
    meetings.cancel_meeting(pg, manager, second.id, "Moved online", version=second.version)
    pg.commit()
    counts = meetings.meeting_counts(pg, manager, now=NOW)
    assert (counts["upcoming"], counts["cancelled"], counts["conflicts"]) == (1, 1, 0)
    assert pg.scalar(select(func.count()).select_from(MeetingAttendee)) == 3


def test_two_bookings_of_one_attendee_that_both_looked_free_cannot_both_win(pg, pg_team, pg_factory):
    manager = pg_team.actor("sales_manager")
    attendee_id = pg_team.users["bdr"].id
    clients = [_pg_client(pg, "Left Ltd", "l@example.com"), _pg_client(pg, "Right Ltd", "r@example.com")]
    previews = [meetings.check_availability(pg, manager, parse(AvailabilityQuery, {
        "client_id": client_id, "attendee_ids": [attendee_id], "starts_at": MEETING_DAY.replace(hour=10),
        "ends_at": MEETING_DAY.replace(hour=10, minute=30)}), now=NOW) for client_id in clients]
    assert all(preview.available for preview in previews)  # both screens say "available"

    def book(client_id: str):
        return lambda session: meetings.create_meeting(session, manager, _meeting(client_id, [attendee_id], 10),
                                                       now=NOW)

    outcomes = _race_pair(pg_factory, book(clients[0]), book(clients[1]))
    failures = [outcome for outcome in outcomes if outcome is not None]
    assert len(failures) == 1 and isinstance(failures[0], Conflict)
    assert pg.scalar(select(func.count()).select_from(Meeting).where(Meeting.status == "scheduled")) == 1


def test_two_bookings_of_one_client_with_different_attendees_cannot_both_win(pg, pg_team, pg_factory):
    manager = pg_team.actor("sales_manager")
    client_id = _pg_client(pg, "Contested Ltd", "c@example.com")

    def book(role: str):
        attendee_id = pg_team.users[role].id
        return lambda session: meetings.create_meeting(session, manager, _meeting(client_id, [attendee_id], 10),
                                                       now=NOW)

    outcomes = _race_pair(pg_factory, book("bdr"), book("account_executive"))
    failures = [outcome for outcome in outcomes if outcome is not None]
    assert len(failures) == 1 and isinstance(failures[0], Conflict)
    assert pg.scalar(select(func.count()).select_from(Meeting).where(Meeting.client_id == client_id)) == 1


def test_a_booking_in_progress_holds_its_client_and_attendees_until_it_commits(pg, pg_team, pg_factory):
    """Deterministic: the first transaction has locked and inserted but not committed."""
    manager = pg_team.actor("sales_manager")
    bdr, executive = pg_team.users["bdr"].id, pg_team.users["account_executive"].id
    researcher = pg_team.users["lead_researcher"].id
    shared_client = _pg_client(pg, "Shared Ltd", "s@example.com")
    other_client = _pg_client(pg, "Unrelated Ltd", "u@example.com")
    outcomes: dict[str, str] = {}

    def book(name: str, client_id: str, attendee_id: str) -> threading.Thread:
        def work() -> None:
            with pg_factory() as session:
                try:
                    meetings.create_meeting(session, manager, _meeting(client_id, [attendee_id], 10), now=NOW)
                    session.commit()
                    outcomes[name] = "created"
                except Conflict:
                    session.rollback()
                    outcomes[name] = "conflict"
        thread = threading.Thread(target=work)
        thread.start()
        return thread

    first = pg_factory()
    meetings.create_meeting(first, manager, _meeting(shared_client, [bdr], 10), now=NOW)  # locked, uncommitted
    unrelated = book("unrelated", other_client, researcher)
    unrelated.join(timeout=10)
    assert outcomes.get("unrelated") == "created"  # shares nothing: does not wait
    contested = book("contested", shared_client, executive)
    contested.join(timeout=1.5)
    assert contested.is_alive() and "contested" not in outcomes  # waits for the client's row lock
    first.commit()
    first.close()
    contested.join(timeout=15)
    assert outcomes["contested"] == "conflict"  # after the wait it sees the committed meeting


def test_the_meeting_upgrade_keeps_existing_attendees_on_postgresql(empty_server_url):
    migrations_util.upgrade(empty_server_url, "0003")
    engine = create_engine(empty_server_url, poolclass=pool.NullPool)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users (id, email, full_name, role, is_active, timezone, created_at, updated_at) "
            "VALUES ('U1', 'u1@example.com', 'User One', 'bdr', true, 'UTC', now(), now())"))
        connection.execute(text(
            "INSERT INTO meetings (id, client_name, title, attendee_id, starts_at, ends_at, link, status, "
            "created_at, updated_at, version) VALUES ('M1', 'Acme', 'Intro', 'U1', '2026-11-02 10:00', "
            "'2026-11-02 11:00', 'https://meet.example.com', 'scheduled', now(), now(), 1)"))
    migrations_util.upgrade(empty_server_url)
    with engine.connect() as connection:
        assert migrations_util.layout_problems(connection) == []
        assert connection.execute(text("SELECT meeting_id, user_id FROM meeting_attendees")).all() == [("M1", "U1")]
        columns = {row[0] for row in connection.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'meetings'"))}
    engine.dispose()
    assert "attendee_id" not in columns and {"client_email", "link"} <= columns


def _race_pair(factory: sessionmaker[Session], left, right) -> list[BaseException | None]:
    """Run ``left`` and ``right`` on two connections at the same moment; returns each one's exception."""
    barrier = threading.Barrier(2)
    outcomes: list[BaseException | None] = [None, None]

    def run(index: int, work) -> None:
        with factory() as session:
            try:
                barrier.wait(timeout=10)
                work(session)
                session.commit()
            except BaseException as exc:  # recorded for the assertions
                session.rollback()
                outcomes[index] = exc

    threads = [threading.Thread(target=run, args=(0, left)), threading.Thread(target=run, args=(1, right))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return outcomes


def test_a_retried_outcome_from_two_computers_is_recorded_once(pg, pg_team, pg_factory):
    manager, ali = pg_team.actor("sales_manager"), pg_team.actor("bdr")
    ids = _import_and_assign(pg, manager, ali.user_id, count=1)

    def save(session: Session) -> None:
        outreach.record_event(session, ali, parse(OutreachRecord, {
            "prospect_id": ids[0], "event_type": "connection_sent", "request_id": "pg-retry-0001"}), now=NOW)

    outcomes = _race_pair(pg_factory, save, save)
    assert all(outcome is None or isinstance(outcome, IntegrityError | StaleDataError) for outcome in outcomes)
    assert pg.scalar(select(func.count()).select_from(OutreachEvent)) == 1


def test_a_stale_follow_up_change_is_refused(pg, pg_team, pg_factory):
    manager, ali = pg_team.actor("sales_manager"), pg_team.actor("bdr")
    ids = _import_and_assign(pg, manager, ali.user_id, count=1)
    outreach.record_event(pg, ali, parse(OutreachRecord, {
        "prospect_id": ids[0], "event_type": "follow_up_requested",
        "follow_up_at": (NOW + timedelta(days=2)).isoformat()}), now=NOW)
    pg.commit()
    loaded = tasks.get_open_follow_up(pg, ali, ids[0])
    seen_version = loaded.version
    with pg_factory() as other:  # someone else reschedules first
        outreach.record_event(other, ali, parse(OutreachRecord, {
            "prospect_id": ids[0], "event_type": "follow_up_requested",
            "follow_up_at": (NOW + timedelta(days=5)).isoformat()}), now=NOW)
        other.commit()
    pg.expire_all()
    with pytest.raises(Conflict):
        tasks.complete_follow_up(pg, ali, loaded.id, version=seen_version)


# --- moving a single-computer database to the server -------------------------------------------

def test_a_local_database_is_copied_completely_into_an_empty_team_database(
        tmp_path: Path, migrated_template: Path, password_hash: str, server_url: str):
    local = tmp_path / "sales.db"
    local.write_bytes(migrated_template.read_bytes())
    engine = create_db_engine(Settings(local))
    with create_session_factory(engine)() as db:
        world_team = World(db, password_hash).team()
        manager, ali, sara = (world_team.actor("sales_manager"), world_team.actor("bdr"),
                              world_team.actor("account_executive"))
        ids = _import_and_assign(db, manager, ali.user_id)
        outreach.record_event(db, ali, parse(OutreachRecord, {
            "prospect_id": ids[0], "event_type": "follow_up_requested",
            "follow_up_at": (NOW + timedelta(days=1)).isoformat()}), now=NOW)
        old = prospects.open_assignment(db, ids[0])
        assignments.reassign(db, manager, old.id, parse(Reassignment, {"assignee_id": sara.user_id}))
        db.commit()
        expected = {name: db.scalar(select(func.count()).select_from(model))
                    for name, model in (("users", User), ("prospect_assignments", ProspectAssignment),
                                        ("tasks", Task), ("notifications", Notification))}
    engine.dispose()

    copied = transfer.copy_local_to_server(local, server_url, say=lambda _line: None)
    for name, rows in expected.items():
        assert copied[name] == rows
    server = create_db_engine(settings_for_url(server_url))
    with create_session_factory(server)() as db:
        chain = db.scalars(select(ProspectAssignment).where(ProspectAssignment.prospect_id == ids[0])
                           .order_by(ProspectAssignment.created_at)).all()
        assert chain[1].previous_assignment_id == chain[0].id  # self-reference restored
        assert all(user.is_active is True for user in db.scalars(select(User)))
        follow_up = db.scalar(select(Task).where(Task.kind == "follow_up"))
        assert follow_up.due_at == NOW + timedelta(days=1)  # time zone intact
        db.add(Notification(recipient_id=ali.user_id, kind="test", title="After the copy"))
        db.commit()  # the id sequence continues after the copied rows
    server.dispose()
    with pytest.raises(transfer.TransferRefused, match="already has data"):
        transfer.copy_local_to_server(local, server_url, say=lambda _line: None)


def test_an_unmigrated_team_database_is_refused_for_copying(tmp_path, migrated_template, empty_server_url):
    local = tmp_path / "sales.db"
    local.write_bytes(migrated_template.read_bytes())
    with pytest.raises(transfer.TransferRefused, match="upgrade-database"):
        transfer.copy_local_to_server(local, empty_server_url, say=lambda _line: None)


# --- the desktop's connection handling ----------------------------------------------------------

def test_the_desktop_does_not_upgrade_a_shared_database_itself(empty_server_url):
    pytest.importorskip("PySide6.QtCore")
    from techset_leadgen.desktop.session import AppContext, ConnectionProblem

    context = AppContext(settings_for_url(empty_server_url))
    with pytest.raises(ConnectionProblem, match="needs an upgrade"):
        context.open()
    engine = create_db_engine(settings_for_url(empty_server_url))
    with engine.connect() as connection:
        assert migrations_util.schema_state(connection).current is None  # untouched
    engine.dispose()


# --- backups -------------------------------------------------------------------------------------

def test_a_team_backup_restores_completely_into_a_new_database(pg, pg_team, server_url, spare_server_url,
                                                                 tmp_path):
    import shutil

    from techset_leadgen.database import server_backup

    if shutil.which("pg_dump") is None:
        pytest.skip("pg_dump is not installed")
    manager, ali = pg_team.actor("sales_manager"), pg_team.actor("bdr")
    _import_and_assign(pg, manager, ali.user_id, count=3)
    dump = server_backup.backup(server_url, tmp_path / "backups")
    assert dump.is_file() and dump.stat().st_size > 0
    server_backup.restore(dump, spare_server_url)

    def counts(url: str) -> dict[str, int]:
        engine = create_engine(url, poolclass=pool.NullPool)
        try:
            with engine.connect() as connection:
                names = [name for name in sqlalchemy_inspect(connection).get_table_names()]
                return {name: connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()  # noqa: S608
                        for name in names}
        finally:
            engine.dispose()

    original, restored = counts(server_url), counts(spare_server_url)
    assert restored == original and restored["prospect_assignments"] == 3
    with pytest.raises(server_backup.BackupFailed, match="new, empty database"):
        server_backup.restore(dump, server_url)  # never over live data
    with pytest.raises(server_backup.BackupFailed) as caught:
        server_backup.backup(make_url(server_url).set(password="wrong-secret").render_as_string(
            hide_password=False), tmp_path / "other")
    assert "wrong-secret" not in str(caught.value)
