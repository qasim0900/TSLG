"""Meetings: clients, attendees, conflict detection, buffers, suggested slots, lifecycle, and access.

Times are fixed: ``NOW`` is Wednesday 28 Oct 2026 08:00 UTC and meetings are booked on
Monday 2 Nov 2026 (business time zone UTC unless a test changes it; 09:00–18:00, Monday–Friday).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from techset_leadgen.database.models import AuditLog, Client, Meeting, MeetingAttendee, Notification, Organization
from techset_leadgen.domain import scheduling
from techset_leadgen.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from techset_leadgen.services import meetings
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.services.schemas import (
    AvailabilityQuery,
    MeetingCreate,
    MeetingReschedule,
    MeetingUpdate,
    SchedulingRulesUpdate,
    parse,
)

NOW = datetime(2026, 10, 28, 8, tzinfo=UTC)
DAY = datetime(2026, 11, 2, tzinfo=UTC)  # a Monday


def at(hour: int, minute: int = 0, *, day: datetime = DAY) -> datetime:
    return day.replace(hour=hour, minute=minute)


@pytest.fixture()
def manager(acme) -> Actor:
    return acme.actor("sales_manager")


@pytest.fixture()
def client(world, manager) -> Client:
    return world.client(manager, "Smith Holdings", email="john@example.com", contact_person="John Smith")


def _create(db, actor, attendees, start, end, *, client=None, **overrides) -> Meeting:
    values = {
        "title": "Product introduction",
        "client_id": client.id if client is not None else None,
        "attendee_ids": [user.id for user in attendees],
        "starts_at": start,
        "ends_at": end,
        "link": "https://meet.example.com/intro",
        "request_id": uuid4().hex,
        **overrides,
    }
    meeting = meetings.create_meeting(db, actor, parse(MeetingCreate, values), now=NOW)
    db.commit()
    return meeting


def _check(db, actor, start, end, *, client=None, attendees=(), meeting=None) -> meetings.Availability:
    query = parse(AvailabilityQuery, {
        "client_id": client.id if client is not None else None,
        "attendee_ids": [user.id for user in attendees],
        "starts_at": start, "ends_at": end,
        "meeting_id": meeting.id if meeting is not None else None,
    })
    return meetings.check_availability(db, actor, query, now=NOW)


def _set_rules(db, acme, mode: str, minutes: int = 120, **values) -> None:
    data = parse(SchedulingRulesUpdate, {"buffer_mode": mode, "buffer_minutes": minutes, "day_start": 540,
                                         "day_end": 1080, "work_days": list("12345"), **values})
    meetings.update_scheduling_rules(db, acme.actor("super_admin"), data)
    db.commit()


def _update_values(meeting: Meeting, **changes) -> dict:
    return {"title": meeting.title, "client_id": meeting.client_id, "client_email": meeting.client_email,
            "attendee_ids": [user.id for user in meeting.attendees], "starts_at": meeting.starts_at,
            "ends_at": meeting.ends_at, "link": meeting.link, "description": meeting.description,
            "version": meeting.version, **changes}


# --- creating and finding -------------------------------------------------------------------------

def test_create_stores_client_attendees_creator_audit_and_notifications(db, acme, manager, client):
    bdr, executive = acme.users["bdr"], acme.users["account_executive"]
    meeting = _create(db, manager, [bdr, executive], at(10), at(10, 30), client=client,
                      description="Agenda: pricing")

    saved = db.get(Meeting, meeting.id)
    assert (saved.client_id, saved.client_name, saved.client_email) == (client.id, "Smith Holdings",
                                                                       "john@example.com")
    assert saved.attendee_ids == {bdr.id, executive.id}
    assert saved.created_by_id == manager.user_id  # the signed-in user, never a submitted value
    assert saved.status == "scheduled" and saved.description == "Agenda: pricing"
    assert db.scalar(select(func.count()).select_from(MeetingAttendee).where(
        MeetingAttendee.meeting_id == meeting.id)) == 2
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "meeting.created", AuditLog.entity_id == meeting.id))
    assert entry.changes["attendee_ids"] == sorted([bdr.id, executive.id])
    assert {row.recipient_id for row in db.scalars(select(Notification).where(
        Notification.entity_id == meeting.id))} == {bdr.id, executive.id}


def test_creator_cannot_be_supplied_by_the_form(manager, acme):
    with pytest.raises(ValidationFailed) as error:
        parse(MeetingCreate, {"title": "x", "attendee_ids": [acme.users["bdr"].id], "starts_at": at(10),
                              "ends_at": at(11), "created_by_id": acme.users["bdr"].id})
    assert error.value.fields["created_by_id"] == "This field cannot be set."


def test_client_search_by_name_and_email_is_case_insensitive(db, world, manager, client):
    world.client(manager, "Johnson Media", email="info@johnson.example")
    assert [found.name for found in meetings.search_clients(db, manager, "smith")] == ["Smith Holdings"]
    found = meetings.search_clients(db, manager, "JOHN@EXAMPLE.COM")
    assert [(item.id, item.email) for item in found] == [(client.id, "john@example.com")]
    assert [item.name for item in meetings.search_clients(db, manager, "john")][0] == "Johnson Media"
    assert len(meetings.search_clients(db, manager, "", limit=1)) == 1
    with pytest.raises(PermissionDenied):
        meetings.search_clients(db, Actor.for_user(world.user(None, "read_only")), "smith")


def test_choosing_a_client_uses_its_email_and_a_typed_email_overrides_it(db, acme, manager, client):
    first = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    assert first.client_email == "john@example.com"
    second = _create(db, manager, [acme.users["account_executive"]], at(14), at(14, 30), client=client,
                     client_email="Assistant@Example.com")
    assert second.client_email == "assistant@example.com"


def test_a_new_client_is_added_once_and_duplicates_are_refused(db, acme, manager, client):
    meeting = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client_name="Nova Labs",
                      client_email="ceo@nova.example")
    added = db.get(Client, meeting.client_id)
    assert (added.name, added.email, added.created_by_id) == ("Nova Labs", "ceo@nova.example", manager.user_id)
    with pytest.raises(Conflict, match="already exists"):
        _create(db, manager, [acme.users["bdr"]], at(15), at(15, 30), client_name="smith holdings",
                client_email="other@example.com")
    db.rollback()
    with pytest.raises(Conflict, match="already uses the email"):
        _create(db, manager, [acme.users["bdr"]], at(15), at(15, 30), client_name="Another Name",
                client_email="john@example.com")
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Client)) == 2


def test_client_schedule_shows_the_day_upcoming_and_past_and_hides_colleagues_titles(db, acme, manager, client):
    bdr, executive = acme.users["bdr"], acme.users["account_executive"]
    _create(db, manager, [bdr], at(10), at(10, 30), client=client, title="BDR call")
    _create(db, manager, [executive], at(15), at(15, 30), client=client, title="AE demo")
    _create(db, manager, [bdr], at(10, day=DAY + timedelta(days=3)), at(11, day=DAY + timedelta(days=3)),
            client=client, title="Follow-up")

    schedule = meetings.client_schedule(db, manager, client.id, on_date=DAY.date(), now=NOW)
    assert [entry.title for entry in schedule.on_date] == ["BDR call", "AE demo"]
    assert [entry.title for entry in schedule.upcoming] == ["BDR call", "AE demo", "Follow-up"]
    assert schedule.past == []
    later = meetings.client_schedule(db, manager, client.id, now=at(12))
    assert [entry.title for entry in later.past] == ["BDR call"]

    member_view = meetings.client_schedule(db, Actor.for_user(bdr), client.id, on_date=DAY.date(), now=NOW)
    assert [entry.title for entry in member_view.on_date] == ["BDR call", None]  # a colleague's: time only
    assert member_view.on_date[1].attendees == ""


# --- conflicts --------------------------------------------------------------------------------------

def test_overlapping_meeting_for_the_same_client_is_refused_with_its_time(db, acme, manager, client):
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)

    result = _check(db, manager, at(10, 15), at(10, 45), client=client, attendees=[acme.users["account_executive"]])
    assert not result.available
    assert [clash.message for clash in result.client_conflicts] == [
        "This client already has a meeting scheduled from 10:00 AM to 10:30 AM (Product introduction)."]
    assert result.attendee_conflicts == []
    with pytest.raises(Conflict) as error:
        _create(db, manager, [acme.users["account_executive"]], at(10, 15), at(10, 45), client=client)
    db.rollback()
    assert error.value.message == "This time slot is unavailable."
    assert "This client already has a meeting scheduled from 10:00 AM to 10:30 AM" in error.value.fields["availability"]
    assert "Available alternatives: " in error.value.fields["availability"]


def test_attendee_overlap_is_refused_and_names_the_person(db, acme, manager, world):
    sarah = acme.users["bdr"]
    other_client = world.client(manager, "Other Co", email="other@example.com")
    _create(db, manager, [sarah], at(11), at(11, 30), client=other_client)

    result = _check(db, manager, at(11, 15), at(11, 45), attendees=[sarah])
    assert [clash.message for clash in result.attendee_conflicts] == [
        f"{sarah.full_name} already has a meeting from 11:00 AM to 11:30 AM (Product introduction)."]
    assert result.attendee_conflicts[0].party == sarah.id


def test_with_several_attendees_only_the_busy_one_is_reported(db, acme, manager, client, world):
    busy, free = acme.users["bdr"], acme.users["account_executive"]
    _create(db, manager, [busy], at(11), at(11, 30), client=world.client(manager, "Third", email="t@example.com"))

    result = _check(db, manager, at(11), at(11, 30), client=client, attendees=[busy, free])
    assert [clash.party for clash in result.attendee_conflicts] == [busy.id]
    assert _check(db, manager, at(11), at(11, 30), client=client, attendees=[free]).available


@pytest.mark.parametrize("requested, overlap", [
    ((10, 20, 10, 50), True),  # starts inside
    ((10, 15, 10, 20), True),  # inside
    ((9, 30, 11, 0), True),  # around it
    ((10, 30, 11, 0), False),  # starts exactly when it ends
    ((9, 30, 10, 0), False),  # ends exactly when it starts
])
def test_overlap_uses_start_and_end_and_touching_meetings_do_not_overlap(db, acme, manager, client, requested,
                                                                         overlap):
    _set_rules(db, acme, "none")
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    start, end = at(*requested[:2]), at(*requested[2:])
    assert _check(db, manager, start, end, client=client, attendees=[acme.users["bdr"]]).available is not overlap


def test_cancelled_meetings_do_not_block_and_stay_in_history(db, acme, manager, client):
    meeting = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    meetings.cancel_meeting(db, manager, meeting.id, "Client asked", version=meeting.version)
    db.commit()

    again = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    assert again.id != meeting.id
    assert db.get(Meeting, meeting.id).status == "cancelled"


def test_completed_meetings_do_not_block_later_slots(db, acme, manager, client):
    meeting = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    meetings.complete_meeting(db, manager, meeting.id, version=meeting.version, now=at(10, 40))
    db.commit()
    assert _check(db, manager, at(11), at(11, 30), client=client, attendees=[acme.users["bdr"]]).available


# --- buffer modes -----------------------------------------------------------------------------------

@pytest.mark.parametrize("mode, minutes, start, expected", [
    ("none", 120, (10, 30), None),
    ("post", 120, (10, 30), "buffer"),
    ("post", 120, (12, 29), "buffer"),
    ("post", 120, (12, 30), None),  # 120 minutes after it ends
    ("post", 60, (11, 30), None),
    ("around", 60, (12, 29), "buffer"),
    ("around", 60, (12, 30), None),  # 60 after it + 60 before the next = 120 between
    ("around", 120, (12, 30), "buffer"),
    ("around", 120, (14, 30), None),
])
def test_buffer_modes_after_an_existing_meeting(db, acme, manager, client, mode, minutes, start, expected):
    _set_rules(db, acme, mode, minutes)
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    result = _check(db, manager, at(*start), at(*start) + timedelta(minutes=30), attendees=[acme.users["bdr"]])
    assert [clash.kind for clash in result.conflicts] == ([expected] if expected else [])


@pytest.mark.parametrize("mode, latest_free_end", [("none", (10, 0)), ("post", (8, 0)), ("around", (6, 0))])
def test_buffer_modes_before_an_existing_meeting_apply_in_both_directions(db, acme, manager, client, mode,
                                                                          latest_free_end):
    _set_rules(db, acme, mode, 120)
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    end = at(*latest_free_end)
    attendee = [acme.users["bdr"]]
    assert _check(db, manager, end - timedelta(minutes=30), end, attendees=attendee).available
    assert not _check(db, manager, end - timedelta(minutes=29), end + timedelta(minutes=1), attendees=attendee).available


def test_buffer_message_explains_the_rule(db, acme, manager, client):
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    result = _check(db, manager, at(11), at(11, 30), client=client)
    assert result.client_conflicts[0].message == (
        "This client has a meeting from 10:00 AM to 10:30 AM (Product introduction), and a 120-minute buffer is "
        "required after each meeting.")
    assert result.buffer_conflicts == result.client_conflicts


def test_editing_an_unchanged_meeting_is_valid_in_every_mode(db, acme, manager, client):
    first = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    second = _create(db, manager, [acme.users["bdr"]], at(14), at(14, 30), client=client)
    _set_rules(db, acme, "around", 120)  # the two are now too close: both count as conflicts
    assert meetings.meeting_counts(db, manager, now=NOW)["conflicts"] == 2
    assert meetings.list_meetings(db, manager, page=PageRequest(), view="conflicts", now=NOW).total == 2
    _set_rules(db, acme, "post", 120)
    for meeting in (first, second):
        meetings.update_meeting(db, manager, meeting.id, parse(MeetingUpdate, _update_values(
            db.get(Meeting, meeting.id), title="Renamed")), now=NOW)
        db.commit()
    assert meetings.meeting_counts(db, manager, now=NOW)["conflicts"] == 0


# --- suggestions --------------------------------------------------------------------------------------

def test_suggestions_are_free_closest_to_the_request_and_respect_business_hours(db, acme, manager, client):
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)

    result = _check(db, manager, at(10), at(10, 30), client=client, attendees=[acme.users["bdr"]])
    assert not result.available and result.suggestion_day == DAY.date() and not result.suggestions_later
    starts = [slot.starts_at for slot in result.suggestions]
    assert starts == [at(12, 30), at(12, 45), at(13), at(13, 15), at(13, 30), at(13, 45)]
    for slot in result.suggestions:
        assert _check(db, manager, slot.starts_at, slot.ends_at, client=client,
                      attendees=[acme.users["bdr"]]).available  # every suggestion passes the real check
        assert not scheduling.outside_hours(slot.starts_at, slot.ends_at, result.rules)

    early = _check(db, manager, at(7), at(7, 30), client=client, attendees=[acme.users["bdr"]])
    assert early.available and early.outside_hours  # allowed, but flagged as outside business hours


def test_suggestions_consider_every_attendee_and_the_client(db, acme, manager, client, world):
    bdr, executive = acme.users["bdr"], acme.users["account_executive"]
    elsewhere = world.client(manager, "Elsewhere", email="e@example.com")
    _create(db, manager, [bdr], at(9), at(10), client=elsewhere)
    _create(db, manager, [executive], at(13), at(14), client=elsewhere)
    _create(db, manager, [acme.users["lead_researcher"]], at(16), at(16, 30), client=client)

    result = _check(db, manager, at(9), at(10), client=client, attendees=[bdr, executive])
    rules = result.rules
    for slot in result.suggestions:
        for busy_start, busy_end in ((at(9), at(10)), (at(13), at(14)), (at(16), at(16, 30))):
            assert scheduling.conflict_kind(busy_start, busy_end, slot.starts_at, slot.ends_at, rules.gap) is None
    assert result.suggestions  # 12:00 (after 9–10 + 120) to 12:00 does not fit before 13:00; later days do


def test_a_full_day_offers_the_next_working_day(db, acme, manager, client, world):
    friday = datetime(2026, 11, 6, tzinfo=UTC)
    bdr = acme.users["bdr"]
    _create(db, manager, [bdr], at(9, day=friday), at(17, day=friday),
            client=world.client(manager, "All day", email="a@example.com"))

    result = _check(db, manager, at(11, day=friday), at(11, 30, day=friday), attendees=[bdr])
    assert result.suggestions_later and result.suggestion_day == date(2026, 11, 9)  # Monday, not the weekend
    assert result.suggestions[0].starts_at == datetime(2026, 11, 9, 9, tzinfo=UTC)


def test_no_free_time_anywhere_returns_no_suggestions(db, acme, manager, client):
    _set_rules(db, acme, "post", 120, day_start=540, day_end=570)  # a 30-minute business day
    result = _check(db, manager, at(9), at(10), client=client)  # an hour never fits
    assert result.available  # nothing booked: the requested time itself is free
    _create(db, manager, [acme.users["bdr"]], at(9), at(10), client=client)
    blocked = _check(db, manager, at(9), at(10), client=client)
    assert not blocked.available and blocked.suggestions == [] and blocked.suggestion_day is None
    with pytest.raises(Conflict) as error:
        _create(db, manager, [acme.users["account_executive"]], at(9), at(10), client=client)
    db.rollback()
    assert "No free time was found" in error.value.fields["availability"]


def test_meetings_across_midnight_use_elapsed_time(db, acme, manager, client):
    _set_rules(db, acme, "post", 120)
    bdr = acme.users["bdr"]
    _create(db, manager, [bdr], at(23), at(0, 30, day=DAY + timedelta(days=1)), client=client)
    next_day = DAY + timedelta(days=1)
    assert not _check(db, manager, at(2, 29, day=next_day), at(3, day=next_day), attendees=[bdr]).available
    assert _check(db, manager, at(2, 30, day=next_day), at(3, day=next_day), attendees=[bdr]).available


# --- edit, reschedule, cancel, complete -------------------------------------------------------------

def test_edit_changes_details_and_attendees_and_never_conflicts_with_itself(db, acme, manager, client):
    bdr, executive = acme.users["bdr"], acme.users["account_executive"]
    meeting = _create(db, manager, [bdr], at(10), at(10, 30), client=client)

    updated = meetings.update_meeting(db, manager, meeting.id, parse(MeetingUpdate, _update_values(
        meeting, title="Pricing review", attendee_ids=[executive.id], ends_at=at(10, 45),
        link="https://zoom.us/j/123")), now=NOW)
    db.commit()
    assert (updated.title, updated.attendee_ids, updated.ends_at) == ("Pricing review", {executive.id}, at(10, 45))
    assert db.scalar(select(func.count()).select_from(MeetingAttendee)) == 1  # the removed link is deleted
    kinds = {(row.recipient_id, row.kind) for row in db.scalars(select(Notification).where(
        Notification.entity_id == meeting.id))}
    assert {(bdr.id, "meeting.removed"), (executive.id, "meeting.scheduled")} <= kinds
    assert db.scalar(select(AuditLog.action).where(AuditLog.entity_id == meeting.id).order_by(
        AuditLog.id.desc()).limit(1)) == "meeting.rescheduled"


def test_reschedule_checks_the_new_time_and_records_the_old_one(db, acme, manager, client):
    bdr = acme.users["bdr"]
    first = _create(db, manager, [bdr], at(10), at(10, 30), client=client)
    _create(db, manager, [bdr], at(16), at(16, 30), client=client)

    with pytest.raises(Conflict):
        meetings.reschedule_meeting(db, manager, first.id, parse(MeetingReschedule, {
            "starts_at": at(15), "ends_at": at(15, 30), "version": first.version}), now=NOW)
    db.rollback()
    moved = meetings.reschedule_meeting(db, manager, first.id, parse(MeetingReschedule, {
        "starts_at": at(11), "ends_at": at(11, 30), "version": first.version}), now=NOW)  # overlaps only itself
    db.commit()
    assert (moved.starts_at, moved.ends_at) == (at(11), at(11, 30))
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "meeting.rescheduled",
                                             AuditLog.entity_id == first.id))
    assert entry.changes["starts_at"] == [at(10).isoformat(), at(11).isoformat()]


def test_stale_edits_are_refused(db, acme, manager, client):
    meeting = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    old_version = meeting.version
    meetings.reschedule_meeting(db, manager, meeting.id, parse(MeetingReschedule, {
        "starts_at": at(11), "ends_at": at(11, 30), "version": old_version}), now=NOW)
    db.commit()
    with pytest.raises(Conflict, match="changed by someone else"):
        meetings.cancel_meeting(db, manager, meeting.id, version=old_version)


def test_status_transitions(db, acme, manager, client):
    meeting = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    with pytest.raises(Conflict, match="has not started"):
        meetings.complete_meeting(db, manager, meeting.id, now=NOW)
    meetings.cancel_meeting(db, manager, meeting.id, "No longer needed")
    db.commit()
    with pytest.raises(Conflict, match="cancelled and can no longer be changed"):
        meetings.update_meeting(db, manager, meeting.id, parse(MeetingUpdate, _update_values(meeting)), now=NOW)
    with pytest.raises(Conflict):
        meetings.reschedule_meeting(db, manager, meeting.id, parse(MeetingReschedule, {
            "starts_at": at(12), "ends_at": at(12, 30)}), now=NOW)
    with pytest.raises(Conflict):
        meetings.complete_meeting(db, manager, meeting.id, now=at(12))
    with pytest.raises(Conflict):
        meetings.cancel_meeting(db, manager, meeting.id)
    assert db.get(Meeting, meeting.id).cancellation_reason == "No longer needed"


# --- validation ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("changes, field", [
    ({"title": "  "}, "title"),
    ({"title": None}, "title"),
    ({"client_email": "not-an-email"}, "client_email"),
    ({"link": "javascript:alert(1)"}, "link"),
    ({"link": "http://meet.example.com/x"}, "link"),
    ({"link": "https://user:pass@meet.example.com"}, "link"),
    ({"starts_at": "2026-11-02T10:00:00"}, "starts_at"),  # no time zone
    ({"attendee_ids": "everyone"}, "attendee_ids"),
    ({"attendee_ids": [str(index) for index in range(21)]}, "attendee_ids"),
])
def test_invalid_input_is_refused_by_the_schema(acme, changes, field):
    values = {"title": "Call", "client_name": "Acme", "client_email": "a@example.com",
              "attendee_ids": [acme.users["bdr"].id], "starts_at": at(10), "ends_at": at(11), **changes}
    with pytest.raises(ValidationFailed) as error:
        parse(MeetingCreate, values)
    assert field in error.value.fields


@pytest.mark.parametrize("changes, field", [
    ({"ends_at": at(9)}, "ends_at"),  # end before start
    ({"ends_at": at(10)}, "ends_at"),  # zero length
    ({"ends_at": at(23)}, "ends_at"),  # longer than 12 hours
    ({"starts_at": datetime(2026, 10, 27, 10, tzinfo=UTC), "ends_at": datetime(2026, 10, 27, 11, tzinfo=UTC)},
     "starts_at"),  # in the past
    ({"attendee_ids": []}, "attendee_ids"),
    ({"attendee_ids": ["no-such-user"]}, "attendee_ids"),
    ({"client_id": "NO_SUCH_CLIENT"}, "client_id"),
    ({"client_id": None, "client_name": None}, "client_id"),
    ({"client_id": None, "client_name": "Brand new", "client_email": None}, "client_email"),
])
def test_invalid_meetings_are_refused_by_the_service_and_nothing_is_saved(db, acme, manager, client, changes,
                                                                          field):
    with pytest.raises(ValidationFailed) as error:
        _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30) + timedelta(minutes=30), client=client,
                **changes)
    db.rollback()
    assert field in error.value.fields
    assert db.scalar(select(func.count()).select_from(Meeting)) == 0


def test_inactive_attendees_are_refused(db, acme, manager, client, world):
    former = world.user(acme.organization, "bdr", active=False)
    db.commit()
    with pytest.raises(ValidationFailed):
        _create(db, manager, [former], at(10), at(10, 30), client=client)


def test_a_failed_save_leaves_no_meeting_attendee_or_new_client(db, acme, manager, client):
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    with pytest.raises(Conflict):
        _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client_name="Brand New Client",
                client_email="new@example.com")  # the attendee is busy
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Meeting)) == 1
    assert db.scalar(select(func.count()).select_from(MeetingAttendee)) == 1
    assert db.scalar(select(Client).where(Client.name == "Brand New Client")) is None


def test_duplicate_request_id_returns_the_original_meeting(db, acme, manager, client):
    request_id = uuid4().hex
    first = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client, request_id=request_id)
    again = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client, request_id=request_id)
    assert again.id == first.id
    assert db.scalar(select(func.count()).select_from(Meeting)) == 1


# --- time zones -------------------------------------------------------------------------------------------

def test_business_time_zone_is_used_for_days_hours_and_messages(db, acme, manager, client):
    organization = db.get(Organization, 1)
    organization.timezone = "Asia/Karachi"  # UTC+5
    db.commit()
    bdr = acme.users["bdr"]
    meeting = _create(db, manager, [bdr], at(5), at(5, 30), client=client)  # 10:00–10:30 in Karachi
    assert meeting.starts_at == at(5)  # stored in UTC

    result = _check(db, manager, at(5, 15), at(5, 45), client=client)
    assert "from 10:00 AM to 10:30 AM" in result.client_conflicts[0].message
    assert result.suggestions[0].starts_at.astimezone(result.rules.zone).hour >= 9
    late_utc = datetime(2026, 11, 2, 20, tzinfo=UTC)  # 3 Nov 01:00 in Karachi
    _create(db, manager, [acme.users["account_executive"]], late_utc, late_utc + timedelta(minutes=30),
            client_name="Night Owl", client_email="owl@example.com")
    assert meetings.list_meetings(db, manager, page=PageRequest(), on_date=date(2026, 11, 2)).total == 1
    assert meetings.list_meetings(db, manager, page=PageRequest(), on_date=date(2026, 11, 3)).total == 1


# --- lists and counts --------------------------------------------------------------------------------------

def test_counts_match_views_and_lists_filter_and_page(db, acme, manager, client, world):
    bdr, executive = acme.users["bdr"], acme.users["account_executive"]
    today = NOW.replace(hour=0)
    held = _create(db, manager, [bdr], at(10, day=today), at(10, 30, day=today), client=client,
                   title="Today held")
    _create(db, manager, [executive], at(15, day=today), at(15, 30, day=today), client=client, title="Today later")
    dropped = _create(db, manager, [bdr], at(10), at(10, 30), client=client, title="Dropped")
    for number in range(4):
        _create(db, manager, [executive], at(9 + 3 * number, day=DAY + timedelta(days=1)),
                at(9 + 3 * number, 30, day=DAY + timedelta(days=1)),
                client=world.client(manager, f"Client {number}", email=f"c{number}@example.com"),
                title=f"Upcoming {number}")
    meetings.complete_meeting(db, manager, held.id, now=at(11, day=today))
    meetings.cancel_meeting(db, manager, dropped.id)
    db.commit()

    later = at(12, day=today)
    counts = meetings.meeting_counts(db, manager, now=later)
    assert counts == {"today": 2, "upcoming": 5, "completed": 1, "cancelled": 1, "conflicts": 0}
    for view, total in counts.items():
        assert meetings.list_meetings(db, manager, page=PageRequest(), view=view, now=later).total == total

    first = meetings.list_meetings(db, manager, page=PageRequest(page=1, page_size=3), view="upcoming", now=later)
    second = meetings.list_meetings(db, manager, page=PageRequest(page=2, page_size=3), view="upcoming", now=later)
    assert (first.total, first.pages, len(first.items), len(second.items)) == (5, 2, 3, 2)
    assert {item.id for item in first.items}.isdisjoint({item.id for item in second.items})
    assert [item.title for item in first.items][0] == "Today later"  # by date, earliest first

    def total(**filters) -> int:
        return meetings.list_meetings(db, manager, page=PageRequest(), now=later, **filters).total

    assert total(q="smith holdings") == 3
    assert total(q="C2@EXAMPLE.COM") == 1
    assert total(q="upcoming 3") == 1
    assert total(q=dropped.id) == 1
    assert total(q=bdr.email.upper()) == 2
    assert total(attendee_id=executive.id) == 5
    assert total(client_id=client.id) == 3
    assert total(status="cancelled") == 1
    assert total(date_from=DAY.date(), date_to=(DAY + timedelta(days=1)).date()) == 5
    assert total(on_date=today.date()) == 2
    with pytest.raises(ValidationFailed):
        total(date_from=DAY.date(), date_to=today.date())
    with pytest.raises(ValidationFailed):
        total(view="everything")


# --- access ------------------------------------------------------------------------------------------------

def test_members_see_and_change_only_their_own_meetings(db, acme, manager, client):
    member, colleague = acme.users["bdr"], acme.users["account_executive"]
    actor = Actor.for_user(member)
    theirs = _create(db, manager, [colleague], at(10), at(10, 30), client=client, title="Colleague's")
    mine = _create(db, actor, [member, colleague], at(15), at(15, 30), client=client, title="Mine")

    assert [item.id for item in meetings.list_meetings(db, actor, page=PageRequest()).items] == [mine.id]
    assert meetings.meeting_counts(db, actor, now=NOW)["upcoming"] == 1
    with pytest.raises(NotFound):
        meetings.get_meeting(db, actor, theirs.id)
    with pytest.raises(NotFound):
        meetings.cancel_meeting(db, actor, theirs.id)
    with pytest.raises(NotFound):
        meetings.update_meeting(db, actor, theirs.id, parse(MeetingUpdate, _update_values(theirs)), now=NOW)
    with pytest.raises(PermissionDenied, match="Add yourself"):
        _create(db, actor, [colleague], at(17), at(17, 30), client=client)
    result = _check(db, actor, at(10), at(10, 30), client=client)
    assert result.client_conflicts[0].title is None  # a colleague's meeting: time only
    assert result.client_conflicts[0].message == "This client already has a meeting scheduled from 10:00 AM to 10:30 AM."


def test_roles_without_meeting_permissions_are_refused(db, acme, manager, client):
    meeting = _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    read_only = acme.actor("read_only")
    for call in (
        lambda: meetings.list_meetings(db, read_only, page=PageRequest()),
        lambda: meetings.get_meeting(db, read_only, meeting.id),
        lambda: meetings.meeting_counts(db, read_only),
        lambda: meetings.search_attendees(db, read_only),
        lambda: _check(db, read_only, at(12), at(13)),
        lambda: _create(db, read_only, [acme.users["bdr"]], at(15), at(15, 30), client=client),
        lambda: meetings.cancel_meeting(db, read_only, meeting.id),
        lambda: meetings.update_scheduling_rules(db, manager, parse(SchedulingRulesUpdate, {
            "buffer_mode": "none", "buffer_minutes": 0, "day_start": 540, "day_end": 1080, "work_days": ["1"]})),
    ):
        with pytest.raises(PermissionDenied):
            call()


def test_scheduling_rules_are_validated_and_audited(db, acme):
    with pytest.raises(ValidationFailed):
        parse(SchedulingRulesUpdate, {"buffer_mode": "sometimes", "buffer_minutes": 30, "day_start": 540,
                                      "day_end": 1080, "work_days": ["1"]})
    with pytest.raises(ValidationFailed):
        parse(SchedulingRulesUpdate, {"buffer_mode": "post", "buffer_minutes": 30, "day_start": 600,
                                      "day_end": 600, "work_days": ["1"]})
    with pytest.raises(ValidationFailed):
        parse(SchedulingRulesUpdate, {"buffer_mode": "post", "buffer_minutes": 30, "day_start": 540,
                                      "day_end": 1080, "work_days": []})
    _set_rules(db, acme, "around", 45, work_days=["1", "3", "5"])
    rules = meetings.scheduling_rules(db)
    assert (rules.buffer_mode, rules.buffer_minutes, rules.work_days, rules.gap) == (
        "around", 45, "135", timedelta(minutes=90))
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "organization.meeting_rules_updated"))
    assert entry.changes["buffer_mode"] == ["post", "around"]


# --- concurrency (SQLite: BEGIN IMMEDIATE; PostgreSQL: see test_postgresql.py) -------------------------------

def test_concurrent_conflicting_saves_are_serialized(db, session_factory, acme, manager, client):
    gate = Barrier(2)

    def save(attendee_id: str) -> str:
        with session_factory() as worker_db:
            data = parse(MeetingCreate, {"title": "Race", "client_id": client.id, "attendee_ids": [attendee_id],
                                         "starts_at": at(10), "ends_at": at(10, 30), "request_id": uuid4().hex})
            gate.wait(timeout=5)
            try:
                meetings.create_meeting(worker_db, manager, data, now=NOW)
                worker_db.commit()
                return "created"
            except Conflict:
                worker_db.rollback()
                return "conflict"

    # Different attendees, same client: only the client links them.
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, [acme.users["bdr"].id, acme.users["account_executive"].id]))
    assert sorted(outcomes) == ["conflict", "created"]
    assert db.scalar(select(func.count()).select_from(Meeting).where(Meeting.status == "scheduled")) == 1


def test_history_lists_every_change_newest_first_for_those_who_may_see_the_meeting(db, acme, manager, client):
    bdr = acme.users["bdr"]
    meeting = _create(db, manager, [bdr], at(10), at(10, 30), client=client)
    meetings.update_meeting(db, manager, meeting.id, parse(MeetingUpdate, _update_values(
        meeting, title="Renamed")), now=NOW)
    db.commit()
    meetings.reschedule_meeting(db, manager, meeting.id, parse(MeetingReschedule, {
        "starts_at": at(13), "ends_at": at(13, 30)}), now=NOW)
    meetings.cancel_meeting(db, manager, meeting.id, "Postponed")
    db.commit()
    actions = [entry.action for entry in meetings.history(db, Actor.for_user(bdr), meeting.id)]
    assert actions == ["meeting.cancelled", "meeting.rescheduled", "meeting.updated", "meeting.created"]
    with pytest.raises(NotFound):
        meetings.history(db, acme.actor("account_executive"), meeting.id)


def test_client_filter_matches_name_or_email(db, acme, manager, client, world):
    _create(db, manager, [acme.users["bdr"]], at(10), at(10, 30), client=client)
    _create(db, manager, [acme.users["account_executive"]], at(10), at(10, 30),
            client=world.client(manager, "Other Co", email="team@other.example"))
    assert meetings.list_meetings(db, manager, page=PageRequest(), client_q="SMITH").total == 1
    assert meetings.list_meetings(db, manager, page=PageRequest(), client_q="other.example").total == 1
