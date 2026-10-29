from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BUFFER_MODES = {
    "none": "No buffer: only overlapping meetings are refused",
    "post": "Buffer after each meeting",
    "around": "Buffer before and after each meeting",
}
DEFAULT_BUFFER_MODE = "post"
DEFAULT_BUFFER_MINUTES = 120
MAX_BUFFER_MINUTES = 480
DEFAULT_DAY_START = 9 * 60
DEFAULT_DAY_END = 18 * 60
DEFAULT_WORK_DAYS = "12345"
WEEKDAYS = {"1": "Monday", "2": "Tuesday", "3": "Wednesday", "4": "Thursday", "5": "Friday",
            "6": "Saturday", "7": "Sunday"}

MAX_DURATION = timedelta(hours=12)
PAST_GRACE = timedelta(minutes=5)
SLOT_STEP = timedelta(minutes=15)
SEARCH_DAYS = 30
SUGGESTIONS = 6

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class SchedulingRules:
    timezone: str = "UTC"
    buffer_mode: str = DEFAULT_BUFFER_MODE
    buffer_minutes: int = DEFAULT_BUFFER_MINUTES
    day_start: int = DEFAULT_DAY_START
    day_end: int = DEFAULT_DAY_END
    work_days: str = DEFAULT_WORK_DAYS

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def buffer(self) -> timedelta:
        return timedelta(minutes=0 if self.buffer_mode == "none" else self.buffer_minutes)

    @property
    def gap(self) -> timedelta:
        return self.buffer * (2 if self.buffer_mode == "around" else 1)

    def summary(self) -> str:
        minutes = self.buffer_minutes
        if self.buffer_mode == "none" or minutes == 0:
            return "No buffer: meetings may follow each other directly; only overlapping meetings are refused."
        if self.buffer_mode == "post":
            return (f"{minutes}-minute buffer after each meeting: the next meeting for the same client or "
                    f"team member can start {minutes} minutes after the previous one ends.")
        return (f"{minutes}-minute buffer before and after each meeting: meetings for the same client or "
                f"team member need {2 * minutes} minutes between them.")

    def hours_text(self) -> str:
        days = sorted(set(self.work_days))
        if days == list("12345"):
            named = "Monday–Friday"
        elif days == list("1234567"):
            named = "every day"
        else:
            named = ", ".join(WEEKDAYS[day] for day in days) or "no working days"
        return f"{clock_minutes(self.day_start)}–{clock_minutes(self.day_end)}, {named}"

    def is_work_day(self, day: date) -> bool:
        return str(day.isoweekday()) in self.work_days


@dataclass(frozen=True)
class Interval:
    starts_at: datetime
    ends_at: datetime


def conflict_kind(existing_start: datetime, existing_end: datetime, start: datetime, end: datetime,
                  gap: timedelta) -> str | None:
    if existing_start < end and existing_end > start:
        return "overlap"
    if existing_start < end + gap and existing_end + gap > start:
        return "buffer"
    return None


def is_free(busy: Iterable[Interval], start: datetime, end: datetime, gap: timedelta) -> bool:
    return all(conflict_kind(item.starts_at, item.ends_at, start, end, gap) is None for item in busy)


def local_instant(day: date, minutes: int, zone: ZoneInfo) -> datetime | None:
    hour, minute = divmod(minutes, 60)
    local = datetime.combine(day, time(hour % 24, minute), tzinfo=zone) + timedelta(days=hour // 24)
    instant = local.astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None
    return instant


def day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return start, end


def candidate_starts(day: date, duration: timedelta, rules: SchedulingRules) -> list[datetime]:
    if not rules.is_work_day(day) or rules.day_end <= rules.day_start:
        return []
    zone = rules.zone
    close = local_instant(day, rules.day_end, zone)
    if close is None:
        return []
    step = int(SLOT_STEP.total_seconds() // 60)
    first = -(-rules.day_start // step) * step
    starts = []
    for minutes in range(first, rules.day_end, step):
        start = local_instant(day, minutes, zone)
        if start is not None and start + duration <= close:
            starts.append(start)
    return starts


def outside_hours(start: datetime, end: datetime, rules: SchedulingRules) -> bool:
    day = start.astimezone(rules.zone).date()
    opening = local_instant(day, rules.day_start, rules.zone)
    closing = local_instant(day, rules.day_end, rules.zone)
    return (not rules.is_work_day(day) or opening is None or closing is None
            or start < opening or end > closing)


@dataclass(frozen=True)
class Suggestions:
    slots: list[Interval]
    day: date | None
    later_day: bool


def suggest(busy: Sequence[Interval], duration: timedelta, rules: SchedulingRules, requested: datetime,
            now: datetime, *, limit: int = SUGGESTIONS, days: int = SEARCH_DAYS) -> Suggestions:
    gap = rules.gap
    earliest = now - PAST_GRACE

    def free_on(day: date) -> list[Interval]:
        return [Interval(start, start + duration) for start in candidate_starts(day, duration, rules)
                if start >= earliest and is_free(busy, start, start + duration, gap)]

    first_day = requested.astimezone(rules.zone).date()
    same_day = free_on(first_day)
    if same_day:
        closest = sorted(same_day, key=lambda slot: (abs(slot.starts_at - requested), slot.starts_at))[:limit]
        return Suggestions(sorted(closest, key=lambda slot: slot.starts_at), first_day, False)
    for offset in range(1, days + 1):
        day = first_day + timedelta(days=offset)
        slots = free_on(day)
        if slots:
            return Suggestions(slots[:limit], day, True)
    return Suggestions([], None, False)


def search_window(requested: datetime, rules: SchedulingRules, *, days: int = SEARCH_DAYS) -> tuple[datetime, datetime]:
    first_day = requested.astimezone(rules.zone).date()
    start, _ = day_bounds(first_day, rules.zone)
    _, end = day_bounds(first_day + timedelta(days=days), rules.zone)
    return start, end


def clock(value: datetime, zone: ZoneInfo | None = None) -> str:
    local = value.astimezone(zone) if zone is not None else value
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def clock_minutes(minutes: int) -> str:
    return clock(datetime(2000, 1, 1) + timedelta(minutes=minutes % (24 * 60)))


def day_text(value: date) -> str:
    return f"{_DAYS[value.weekday()]} {value.day:02d} {_MONTHS[value.month - 1]} {value.year}"


def span_text(start: datetime, end: datetime, zone: ZoneInfo, *, reference: date | None = None) -> str:
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    text = f"from {clock(local_start)} to "
    if local_end.date() != local_start.date():
        text += f"{day_text(local_end.date())} "
    text += clock(local_end)
    if local_start.date() != reference:
        text = f"on {day_text(local_start.date())} {text}"
    return text


def duration_text(duration: timedelta) -> str:
    minutes = int(duration.total_seconds() // 60)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{minutes} min ({hours} h {rest} min)"
    if hours:
        return f"{minutes} min ({hours} h)"
    return f"{minutes} min"


__all__ = [
    "BUFFER_MODES", "DEFAULT_BUFFER_MINUTES", "DEFAULT_BUFFER_MODE", "DEFAULT_DAY_END", "DEFAULT_DAY_START",
    "DEFAULT_WORK_DAYS", "Interval", "MAX_BUFFER_MINUTES", "MAX_DURATION", "PAST_GRACE", "SchedulingRules",
    "Suggestions", "WEEKDAYS", "candidate_starts", "clock", "clock_minutes", "conflict_kind", "day_bounds",
    "day_text", "duration_text", "is_free", "local_instant", "outside_hours", "search_window", "span_text",
    "suggest",
]

