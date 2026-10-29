from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from techset_leadgen.database.models import AuditLog, Notification, OutreachEvent, Prospect, ProspectAssignment, Task
from techset_leadgen.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from techset_leadgen.services import assignments, outreach, prospects, tasks, team
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.services.schemas import BatchCreate, OutreachRecord, Reassignment, TaskCreate, parse

PAGE = PageRequest(page_size=100)
NOW = datetime(2026, 10, 27, 9, tzinfo=UTC)


def _import(db, actor, text: str) -> list[str]:
    result = prospects.import_rows(db, actor, prospects.rows_from_text(text), source="Pasted")
    db.commit()
    return result.prospect_ids


def _batch(db, actor, plan: list[tuple[str, str]], *, draft: bool = False, work_date: date = date(2026, 10, 27)):
    batch = assignments.create_batch(db, actor, parse(BatchCreate, {
        "name": "Monday", "work_date": work_date, "draft": draft,
        "plan": [{"prospect_id": prospect_id, "assignee_id": user_id} for prospect_id, user_id in plan]}))
    db.commit()
    return batch


def _record(db, actor, prospect_id: str, event_type: str, **values):
    event = outreach.record_event(db, actor, parse(OutreachRecord, {
        "prospect_id": prospect_id, "event_type": event_type, **values}), now=NOW)
    db.commit()
    return event


@pytest.fixture()
def office(db, acme):
    manager = acme.actor("sales_manager")
    ali, sara = acme.users["bdr"], acme.users["account_executive"]
    ids = _import(db, manager, "linkedin.com/in/first-person\nhttps://www.linkedin.com/in/second-person/\n"
                               "https://uk.linkedin.com/in/third-person?trk=abc")
    _batch(db, manager, [(ids[0], ali.id), (ids[1], ali.id), (ids[2], sara.id)])
    return manager, acme.actor("bdr"), acme.actor("account_executive"), ids


def test_import_preview_separates_new_repeated_existing_and_invalid_rows(db, acme):
    manager = acme.actor("sales_manager")
    _import(db, manager, "linkedin.com/in/already-here")
    preview = prospects.check_rows(db, manager, prospects.rows_from_text(
        "linkedin.com/in/new-one\nhttps://www.linkedin.com/in/NEW-ONE/details/\nlinkedin.com/in/already-here\n"
        "https://example.com/in/x\nlnkd.in/abc"))
    assert [row.key for row in preview.new] == ["in/new-one"]
    assert [problem.row for problem in preview.repeated] == [2]
    assert [row.key for row in preview.existing] == ["in/already-here"]
    assert len(preview.rejected) == 2
    first = prospects.import_rows(db, manager, prospects.rows_from_text("linkedin.com/in/new-one"), source="x")
    db.commit()
    retry = prospects.import_rows(db, manager, prospects.rows_from_text("linkedin.com/in/new-one"), source="x")
    db.commit()
    assert len(first.created) == 1 and retry.created == []
    assert db.scalar(select(func.count()).select_from(Prospect)) == 2


def test_members_see_only_their_own_assignments_and_are_notified(db, office):
    _manager, ali, sara, ids = office
    mine = assignments.list_my_work(db, ali, page=PAGE)
    assert sorted(item.prospect_id for item in mine.items) == sorted(ids[:2])
    assert [item.prospect_id for item in assignments.list_my_work(db, sara, page=PAGE).items] == [ids[2]]
    with pytest.raises(NotFound):
        prospects.get_prospect(db, sara, ids[0])
    with pytest.raises(PermissionDenied):
        assignments.list_assignments(db, ali, page=PAGE, view="team")
    assert db.scalar(select(func.count()).select_from(Notification)
                     .where(Notification.recipient_id == ali.user_id)) == 2


def test_draft_batches_are_invisible_until_activated(db, acme):
    manager, ali = acme.actor("sales_manager"), acme.actor("bdr")
    ids = _import(db, manager, "linkedin.com/in/draft-person")
    batch = _batch(db, manager, [(ids[0], ali.user_id)], draft=True)
    assert assignments.list_my_work(db, ali, page=PAGE).total == 0
    with pytest.raises(NotFound):
        _record(db, ali, ids[0], "connection_sent")
    db.rollback()
    assignments.activate_batch(db, manager, batch.id, batch.version)
    db.commit()
    assert assignments.list_my_work(db, ali, page=PAGE).total == 1


def test_only_managers_assign_and_a_prospect_has_one_open_assignment(db, office):
    manager, ali, _sara, ids = office
    with pytest.raises(PermissionDenied):
        _batch(db, ali, [(ids[0], ali.user_id)])
    db.rollback()
    with pytest.raises(Conflict):
        _batch(db, manager, [(ids[0], ali.user_id)])


def test_recording_an_outcome_moves_the_stage_and_starts_the_assignment(db, office):
    _manager, ali, _sara, ids = office
    event = _record(db, ali, ids[0], "connection_sent", note="Sent with a short note", request_id="req-0001")
    prospect = db.get(Prospect, ids[0])
    assignment = prospects.open_assignment(db, ids[0])
    assert (prospect.status, assignment.status) == ("connection_sent", "in_progress")
    assert prospect.last_activity_at == NOW and assignment.started_at is not None
    follow_up_retry = _record(db, ali, ids[1], "follow_up_requested", request_id="req-0002",
                              follow_up_at=(NOW + timedelta(days=1)).isoformat())
    assert _record(db, ali, ids[1], "follow_up_requested", request_id="req-0002",
                   follow_up_at=(NOW + timedelta(days=1)).isoformat()).id == follow_up_retry.id
    assert event.assignment_id == assignment.id and event.recorded_by_id == ali.user_id
    assert _record(db, ali, ids[0], "connection_sent", note="Sent with a short note", request_id="req-0001").id == event.id
    with pytest.raises(Conflict):
        _record(db, ali, ids[0], "reply_received", request_id="req-0001")
    db.rollback()
    assert db.scalar(select(func.count()).select_from(OutreachEvent)) == 2
    _record(db, ali, ids[0], "reply_received")
    _record(db, ali, ids[0], "message_sent")
    _record(db, ali, ids[0], "note", note="Asked about pricing")
    assert db.get(Prospect, ids[0]).status == "replied"


def test_members_cannot_record_outcomes_for_other_peoples_prospects(db, acme, office):
    _manager, _ali, sara, ids = office
    with pytest.raises(NotFound):
        _record(db, sara, ids[0], "connection_sent")
    db.rollback()
    with pytest.raises(PermissionDenied):
        _record(db, acme.actor("read_only"), ids[0], "connection_sent")


def test_outcome_validation(db, office):
    _manager, ali, _sara, ids = office
    with pytest.raises(ValidationFailed, match="when to follow up"):
        _record(db, ali, ids[0], "follow_up_requested")
    with pytest.raises(ValidationFailed, match="future"):
        _record(db, ali, ids[0], "connection_sent", occurred_at=(NOW + timedelta(hours=2)).isoformat())
    with pytest.raises(ValidationFailed, match="in the future"):
        _record(db, ali, ids[0], "follow_up_requested", follow_up_at=(NOW - timedelta(hours=1)).isoformat())
    with pytest.raises(ValidationFailed, match="closed prospect"):
        _record(db, ali, ids[0], "not_interested", follow_up_at=(NOW + timedelta(days=1)).isoformat())
    with pytest.raises(ValidationFailed):
        parse(OutreachRecord, {"prospect_id": ids[0], "event_type": "auto_accepted"})


def test_follow_up_requested_schedules_one_follow_up_and_rescheduling_keeps_history(db, office):
    _manager, ali, _sara, ids = office
    first_due = datetime(2026, 10, 30, 5, tzinfo=UTC)
    _record(db, ali, ids[0], "follow_up_requested", follow_up_at=first_due.isoformat(), note="Call on the 30th")
    follow_up = tasks.get_open_follow_up(db, ali, ids[0])
    assert follow_up is not None and follow_up.due_at == first_due and follow_up.assigned_to_id == ali.user_id
    assert db.get(Prospect, ids[0]).next_follow_up_at == first_due
    moved = first_due + timedelta(days=3)
    _record(db, ali, ids[0], "follow_up_requested", follow_up_at=moved.isoformat())
    open_count = db.scalar(select(func.count()).select_from(Task).where(
        Task.kind == "follow_up", Task.status == "open", Task.prospect_id == ids[0]))
    assert open_count == 1
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "follow_up.rescheduled"))
    assert entry is not None and entry.changes["due_at"][0].startswith("2026-10-30")


def test_due_and_overdue_follow_ups_appear_in_the_right_view_until_resolved(db, office):
    _manager, ali, _sara, ids = office
    due = datetime(2026, 10, 28, 6, tzinfo=UTC)
    _record(db, ali, ids[0], "follow_up_requested", follow_up_at=due.isoformat())

    def view(name: str, moment: datetime) -> int:
        return tasks.list_tasks(db, ali, page=PAGE, kind="follow_up", due=name, now=moment).total

    assert (view("today", NOW), view("upcoming", NOW), view("overdue", NOW)) == (0, 1, 0)
    on_the_day = datetime(2026, 10, 28, 4, tzinfo=UTC)
    assert (view("today", on_the_day), view("overdue", on_the_day)) == (1, 0)
    days_later = datetime(2026, 11, 2, 4, tzinfo=UTC)
    assert view("overdue", days_later) == 1
    follow_up = tasks.get_open_follow_up(db, ali, ids[0])
    tasks.complete_follow_up(db, ali, follow_up.id, version=follow_up.version, outcome="Booked a call")
    db.commit()
    assert (view("overdue", days_later), view("done", days_later)) == (0, 1)
    assert db.get(Prospect, ids[0]).next_follow_up_at is None


def test_a_closing_outcome_cancels_the_open_follow_up(db, office):
    _manager, ali, _sara, ids = office
    _record(db, ali, ids[0], "follow_up_requested", follow_up_at=(NOW + timedelta(days=2)).isoformat())
    _record(db, ali, ids[0], "not_interested", note="Not hiring this year")
    assert tasks.get_open_follow_up(db, ali, ids[0]) is None
    assert db.get(Prospect, ids[0]).status == "not_interested"


def test_reassignment_keeps_history_and_moves_the_work(db, office):
    manager, ali, sara, ids = office
    _record(db, ali, ids[0], "follow_up_requested", follow_up_at=(NOW + timedelta(days=1)).isoformat())
    old = prospects.open_assignment(db, ids[0])
    successor = assignments.reassign(db, manager, old.id, parse(Reassignment, {
        "assignee_id": sara.user_id, "reason": "Ali is on leave", "version": old.version}))
    db.commit()
    db.refresh(old)
    assert (old.status, successor.previous_assignment_id, successor.assignee_id) == (
        "reassigned", old.id, sara.user_id)
    assert tasks.get_open_follow_up(db, sara, ids[0]).assigned_to_id == sara.user_id
    with pytest.raises(PermissionDenied):
        _record(db, ali, ids[0], "message_sent")
    db.rollback()
    with pytest.raises((PermissionDenied, Conflict, NotFound)):
        assignments.complete_assignment(db, ali, old.id)
    db.rollback()
    done = assignments.complete_assignment(db, sara, successor.id, successor.version, reason="Meeting booked")
    db.commit()
    assert done.status == "completed"
    history = [entry.title for entry in prospects.history(db, manager, db.get(Prospect, ids[0]))]
    assert any(title.startswith("Reassigned to") for title in history)
    assert db.scalar(select(func.count()).select_from(ProspectAssignment)
                     .where(ProspectAssignment.prospect_id == ids[0])) == 2


def test_members_cannot_reassign_or_cancel(db, office):
    _manager, ali, sara, ids = office
    assignment = prospects.open_assignment(db, ids[0])
    with pytest.raises(PermissionDenied):
        assignments.reassign(db, ali, assignment.id, parse(Reassignment, {"assignee_id": sara.user_id}))
    with pytest.raises(PermissionDenied):
        assignments.cancel_assignment(db, sara, assignment.id)


def test_general_tasks_need_no_prospect_and_sort_by_business_priority(db, acme):
    manager, ali = acme.actor("sales_manager"), acme.actor("bdr")
    for title, priority in (("Clean data", "low"), ("Weekly report", "urgent"), ("Research", "medium"),
                            ("Review", "high")):
        tasks.create_task(db, manager, parse(TaskCreate, {"title": title, "priority": priority,
                                                          "assigned_to_id": ali.user_id}))
    db.commit()
    page = tasks.list_tasks(db, ali, page=PageRequest(page_size=10, sort="priority", descending=True), kind="task")
    assert [task.priority for task in page.items] == ["urgent", "high", "medium", "low"]


def test_daily_summary_counts_recorded_work_per_person(db, acme, office):
    manager, ali, sara, ids = office
    _record(db, ali, ids[0], "connection_sent")
    _record(db, ali, ids[1], "connection_sent")
    _record(db, ali, ids[1], "reply_received")
    _record(db, ali, ids[1], "follow_up_requested", follow_up_at=(NOW + timedelta(days=1)).isoformat())
    done = prospects.open_assignment(db, ids[0])
    assignments.complete_assignment(db, ali, done.id, done.version)
    db.commit()
    db.execute(update(ProspectAssignment).values(assigned_at=NOW - timedelta(hours=1)))
    db.execute(update(ProspectAssignment).where(ProspectAssignment.status == "completed").values(closed_at=NOW))
    db.execute(update(Task).values(created_at=NOW))
    db.commit()
    moment = NOW + timedelta(hours=1)
    summary = team.daily_summary(db, manager, date(2026, 10, 27), now=moment)
    rows = {row.user_id: row for row in summary.rows}
    assert summary.timezone == "UTC"
    mine = rows[ali.user_id]
    assert (mine.assigned, mine.completed, mine.connection_requests, mine.replies, mine.follow_ups_scheduled,
            mine.open_assignments) == (2, 1, 2, 1, 1, 1)
    assert rows[sara.user_id].connection_requests == 0 and rows[sara.user_id].open_assignments == 1
    assert summary.totals.assigned == 3
    own = team.daily_summary(db, ali, date(2026, 10, 27), now=moment)
    assert [row.user_id for row in own.rows] == [ali.user_id]
    other_day = team.daily_summary(db, manager, date(2026, 10, 26), now=moment)
    assert other_day.totals.connection_requests == 0


def test_summary_export_needs_permission_and_neutralises_formulas(db, acme, office):
    manager, ali, _sara, _ids = office
    acme.users["bdr"].full_name = "=HYPERLINK(\"http://x\")"
    db.commit()
    with pytest.raises(PermissionDenied):
        team.export_daily_summary(db, ali, date(2026, 10, 27), now=NOW)
    _summary, text = team.export_daily_summary(db, manager, date(2026, 10, 27), now=NOW)
    db.commit()
    assert "'=HYPERLINK" in text and "\n=HYPERLINK" not in text
    assert text.splitlines()[0].startswith("Date,Time zone,Team member,Profiles assigned")
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "report.exported")) == 1


def test_day_bounds_follow_the_business_time_zone_across_daylight_saving():
    start, end = team.day_bounds("Europe/London", date(2026, 3, 29))
    assert end - start == timedelta(hours=23)
    start, end = team.day_bounds("Asia/Karachi", date(2026, 10, 27))
    assert start == datetime(2026, 10, 26, 19, tzinfo=UTC) and end - start == timedelta(hours=24)

