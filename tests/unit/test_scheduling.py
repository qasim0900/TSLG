from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from techset_leadgen.domain.scheduling import (
    Interval,
    SchedulingRules,
    candidate_starts,
    clock,
    conflict_kind,
    duration_text,
    local_instant,
    span_text,
    suggest,
)

MONDAY = datetime(2026, 11, 2, tzinfo=UTC)
NOW = datetime(2026, 10, 28, tzinfo=UTC)


def at(hour: int, minute: int = 0, day: datetime = MONDAY) -> datetime:
    return day.replace(hour=hour, minute=minute)


@pytest.mark.parametrize("mode, minutes, gap", [("none", 120, 0), ("post", 120, 120), ("around", 120, 240),
                                                ("post", 0, 0)])
def test_each_mode_requires_its_gap(mode, minutes, gap):
    assert SchedulingRules(buffer_mode=mode, buffer_minutes=minutes).gap == timedelta(minutes=gap)


def test_conflict_kind_follows_the_interval_rule_in_both_directions():
    gap = timedelta(minutes=120)
    existing = (at(10), at(10, 30))
    assert conflict_kind(*existing, at(10, 20), at(10, 50), timedelta(0)) == "overlap"
    assert conflict_kind(*existing, at(10, 15), at(10, 20), timedelta(0)) == "overlap"
    assert conflict_kind(*existing, at(10, 30), at(11), timedelta(0)) is None
    assert conflict_kind(*existing, at(12, 29), at(13), gap) == "buffer"
    assert conflict_kind(*existing, at(12, 30), at(13), gap) is None
    assert conflict_kind(*existing, at(7, 30), at(8, 1), gap) == "buffer"
    assert conflict_kind(*existing, at(7, 30), at(8), gap) is None


def test_candidates_fit_business_hours_and_skip_non_working_days():
    rules = SchedulingRules(day_start=9 * 60 + 10, day_end=10 * 60 + 30)
    starts = candidate_starts(MONDAY.date(), timedelta(minutes=30), rules)
    assert [value.strftime("%H:%M") for value in starts] == ["09:15", "09:30", "09:45", "10:00"]
    assert candidate_starts(date(2026, 11, 7), timedelta(minutes=30), rules) == []
    assert candidate_starts(MONDAY.date(), timedelta(hours=2), rules) == []


def test_suggest_prefers_the_requested_day_then_the_next_working_day():
    rules = SchedulingRules()
    busy = [Interval(at(9), at(17))]
    same_day = suggest([Interval(at(10), at(10, 30))], timedelta(minutes=30), rules, at(10), NOW)
    assert same_day.day == MONDAY.date() and not same_day.later_day
    assert [slot.starts_at for slot in same_day.slots][0] == at(12, 30)

    friday = MONDAY + timedelta(days=4)
    full = suggest([Interval(at(9, day=friday), at(17, day=friday))], timedelta(minutes=30), rules,
                   at(11, day=friday), NOW)
    assert full.later_day and full.day == date(2026, 11, 9)
    assert suggest(busy, timedelta(minutes=30), rules, at(10), NOW, days=0).slots == []


def test_suggestions_are_never_in_the_past():
    rules = SchedulingRules()
    result = suggest([], timedelta(minutes=30), rules, at(9), at(14, 2))
    assert result.slots and all(slot.starts_at >= at(14) for slot in result.slots)


def test_business_hours_follow_the_time_zone_and_daylight_saving():
    zone = ZoneInfo("Europe/London")
    rules = SchedulingRules(timezone="Europe/London")
    summer = candidate_starts(date(2026, 10, 23), timedelta(minutes=30), rules)
    winter = candidate_starts(date(2026, 10, 26), timedelta(minutes=30), rules)
    assert summer[0] == datetime(2026, 10, 23, 8, tzinfo=UTC)
    assert winter[0] == datetime(2026, 10, 26, 9, tzinfo=UTC)
    assert summer[0].astimezone(zone).hour == winter[0].astimezone(zone).hour == 9
    assert local_instant(date(2026, 3, 29), 60 + 30, zone) is None


def test_wording_is_locale_independent():
    zone = ZoneInfo("UTC")
    assert clock(at(0, 5)) == "12:05 AM" and clock(at(12)) == "12:00 PM" and clock(at(13, 30)) == "1:30 PM"
    assert span_text(at(10), at(10, 30), zone, reference=MONDAY.date()) == "from 10:00 AM to 10:30 AM"
    assert span_text(at(23), at(1) + timedelta(days=1), zone, reference=date(2026, 11, 1)) == (
        "on Mon 02 Nov 2026 from 11:00 PM to Tue 03 Nov 2026 1:00 AM")
    assert duration_text(timedelta(minutes=45)) == "45 min"
    assert duration_text(timedelta(minutes=90)) == "90 min (1 h 30 min)"
    assert SchedulingRules().hours_text() == "9:00 AM–6:00 PM, Monday–Friday"

