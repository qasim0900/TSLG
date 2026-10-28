"""Validated input for every change made through the screens.

Every model forbids unknown fields, so a form cannot set server-owned
attributes (IDs, status, reasons, audit columns). Cleaning (trimming,
normalizing domains/emails, rejecting unsafe URLs) happens here; rules that
need the database happen in the services.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator

from techset_leadgen.errors import ValidationFailed
from techset_leadgen.services import normalize as norm
from techset_leadgen.domain.scheduling import BUFFER_MODES, MAX_BUFFER_MINUTES, WEEKDAYS
from techset_leadgen.domain.vocabulary import (
    ACCOUNT_STATUSES,
    ACTIVITY_TYPES,
    EMPLOYEE_RANGES,
    LEAD_STATUSES,
    OUTREACH_EVENTS,
    PRIORITIES,
    ROLES,
)


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


InputModelT = TypeVar("InputModelT", bound=InputModel)


# --- field validators -------------------------------------------------------

def _text(max_length: int, *, required: bool = False) -> BeforeValidator:
    def validate(value: Any) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("Enter text.")
        cleaned = norm.clean_text(value, max_length=max_length)
        if required and cleaned is None:
            raise ValueError("This field is required.")
        return cleaned

    return BeforeValidator(validate)


def _long_text(max_length: int) -> BeforeValidator:
    def validate(value: Any) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("Enter text.")
        return norm.clean_multiline(value, max_length=max_length)

    return BeforeValidator(validate)


def _choice(options: Iterable[str]) -> BeforeValidator:
    allowed = frozenset(options)

    def validate(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if value not in allowed:
            raise ValueError("Choose one of the listed options.")
        return str(value)

    return BeforeValidator(validate)


def _using(function: Callable[[Any], Any]) -> BeforeValidator:
    def validate(value: Any) -> Any:
        if value is not None and not isinstance(value, str):
            raise ValueError("Enter text.")
        return function(value)

    return BeforeValidator(validate)


def _blank_to_none(value: Any) -> Any:
    return None if value == "" else value


def _aware(value: Any) -> Any:
    if value == "" or value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        raise ValueError("Include a time zone offset, for example 2026-01-31T09:00:00+00:00.")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Enter a valid date and time.") from exc
        if parsed.tzinfo is None:
            raise ValueError("Include a time zone offset, for example 2026-01-31T09:00:00+00:00.")
        return parsed.astimezone(UTC)
    return value


def _iso_date(value: Any) -> str | None:
    """``YYYY-MM-DD`` text, the format of the original date columns."""
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("Enter a date as YYYY-MM-DD.") from exc


def _request_id(value: Any) -> str | None:
    """A client-generated ID that makes a retried save idempotent."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not 8 <= len(text) <= 64 or not all(ch.isalnum() or ch in "-_" for ch in text):
        raise ValueError("Invalid request ID.")
    return text


OptionalId = Annotated[str | None, BeforeValidator(_blank_to_none)]
RequestId = Annotated[str | None, BeforeValidator(_request_id)]
AwareDateTime = Annotated[datetime | None, BeforeValidator(_aware)]
IsoDate = Annotated[str | None, BeforeValidator(_iso_date)]
Short = Annotated[str | None, _text(80)]


# --- clients and contacts -----------------------------------------------------

class ClientFields(InputModel):
    name: Annotated[str | None, _text(200)] = None
    cif: Annotated[str | None, _text(40)] = None
    address: Annotated[str | None, _text(300)] = None
    contact_person: Annotated[str | None, _text(200)] = None
    email: Annotated[str | None, _text(254)] = None  # format checked by models.client_validators
    primary_domain: Annotated[str | None, _using(norm.normalize_domain)] = None
    website_url: Annotated[str | None, _using(norm.normalize_url)] = None
    industry: Annotated[str | None, _text(120)] = None
    employee_range: Annotated[str | None, _choice(EMPLOYEE_RANGES)] = None
    country: Short = None
    city: Short = None
    account_status: Annotated[str | None, _choice(ACCOUNT_STATUSES)] = None
    owner_id: OptionalId = None
    notes: Annotated[str | None, _long_text(10000)] = None


class ClientCreate(ClientFields):
    name: Annotated[str, _text(200, required=True)]


class ClientUpdate(ClientFields):
    version: int | None = None


class ContactFields(InputModel):
    first_name: Annotated[str | None, _text(100)] = None
    last_name: Annotated[str | None, _text(100)] = None
    job_title: Annotated[str | None, _text(150)] = None
    email: Annotated[str | None, _using(norm.normalize_email)] = None
    phone: Annotated[str | None, _using(norm.normalize_phone)] = None
    do_not_contact: bool = False
    suppression_reason: Annotated[str | None, _text(200)] = None
    notes: Annotated[str | None, _long_text(5000)] = None


class ContactCreate(ContactFields):
    client_id: str
    first_name: Annotated[str, _text(100, required=True)]


class ContactUpdate(ContactFields):
    version: int | None = None


# --- leads --------------------------------------------------------------------

class LeadFields(InputModel):
    title: Annotated[str | None, _text(200)] = None
    client_id: OptionalId = None
    source: Annotated[str | None, _text(40)] = None
    meeting_date: IsoDate = None
    owner_id: OptionalId = None
    priority: Annotated[str | None, _choice(PRIORITIES)] = None
    notes: Annotated[str | None, _long_text(5000)] = None


class LeadCreate(LeadFields):
    title: Annotated[str, _text(200, required=True)]
    source: Annotated[str, _text(40, required=True)]
    created_on: IsoDate = None  # defaults to today
    allow_duplicate: bool = False


class LeadUpdate(LeadFields):
    version: int | None = None


class LeadTransition(InputModel):
    status: Annotated[str, _choice(LEAD_STATUSES)]
    reason: Annotated[str | None, _long_text(2000)] = None
    version: int | None = None


class Assignment(InputModel):
    owner_id: OptionalId = None
    version: int | None = None


class BulkAssignment(InputModel):
    lead_ids: list[str] = Field(min_length=1, max_length=500)
    owner_id: OptionalId = None


# --- activities and tasks -----------------------------------------------------

class ActivityCreate(InputModel):
    activity_type: Annotated[str, _choice(ACTIVITY_TYPES)]
    subject: Annotated[str, _text(200, required=True)]
    body: Annotated[str | None, _long_text(10000)] = None
    occurred_at: AwareDateTime = None
    client_id: OptionalId = None
    contact_id: OptionalId = None
    lead_id: OptionalId = None


class TaskFields(InputModel):
    title: Annotated[str | None, _text(200)] = None
    description: Annotated[str | None, _long_text(5000)] = None
    client_id: OptionalId = None
    lead_id: OptionalId = None
    prospect_id: OptionalId = None
    assigned_to_id: OptionalId = None
    priority: Annotated[str | None, _choice(PRIORITIES)] = None
    due_at: AwareDateTime = None


class TaskCreate(TaskFields):
    title: Annotated[str, _text(200, required=True)]
    request_id: RequestId = None


def _meeting_link(value: Any) -> str | None:
    link = norm.normalize_url(value, max_length=1000)
    if link is not None and not link.lower().startswith("https://"):
        raise ValueError("Use a secure meeting link that starts with https://.")
    return link


def _attendee_ids(value: Any) -> Any:
    """Distinct IDs in the order given (a person chosen twice attends once)."""
    if not isinstance(value, list | tuple):
        return value
    seen: dict[str, None] = {}
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 36:
            raise ValueError("Choose team members from the list.")
        seen.setdefault(item.strip(), None)
    return list(seen)


AttendeeIds = Annotated[list[str], BeforeValidator(_attendee_ids), Field(max_length=20)]


class MeetingFields(InputModel):
    title: Annotated[str, _text(200, required=True)]
    # An existing client; or, when empty, a new client named ``client_name`` is added.
    client_id: OptionalId = None
    client_name: Annotated[str | None, _text(200)] = None
    client_email: Annotated[str | None, _using(norm.normalize_email)] = None
    attendee_ids: AttendeeIds
    starts_at: Annotated[datetime, BeforeValidator(_aware)]
    ends_at: Annotated[datetime, BeforeValidator(_aware)]
    link: Annotated[str | None, _using(_meeting_link)] = None
    description: Annotated[str | None, _long_text(5000)] = None


class MeetingCreate(MeetingFields):
    request_id: RequestId = None


class MeetingUpdate(MeetingFields):
    version: int | None = None


class MeetingReschedule(InputModel):
    starts_at: Annotated[datetime, BeforeValidator(_aware)]
    ends_at: Annotated[datetime, BeforeValidator(_aware)]
    version: int | None = None


class AvailabilityQuery(InputModel):
    """A proposed time for a client and attendees; ``meeting_id`` is the meeting being changed."""

    client_id: OptionalId = None
    attendee_ids: AttendeeIds = Field(default_factory=list)
    starts_at: Annotated[datetime, BeforeValidator(_aware)]
    ends_at: Annotated[datetime, BeforeValidator(_aware)]
    meeting_id: OptionalId = None


def _work_days(value: Any) -> Any:
    if isinstance(value, list | tuple | set):
        days = sorted({str(day).strip() for day in value})
        if not days or any(day not in WEEKDAYS for day in days):
            raise ValueError("Choose at least one working day.")
        return "".join(days)
    return value


class SchedulingRulesUpdate(InputModel):
    buffer_mode: Annotated[str, _choice(BUFFER_MODES)]
    buffer_minutes: Annotated[int, Field(ge=0, le=MAX_BUFFER_MINUTES)]
    day_start: Annotated[int, Field(ge=0, le=24 * 60)]
    day_end: Annotated[int, Field(ge=0, le=24 * 60)]
    work_days: Annotated[str, BeforeValidator(_work_days), Field(min_length=1, max_length=7)]

    @field_validator("day_end")
    @classmethod
    def _hours_in_order(cls, value: int, info: Any) -> int:
        start = info.data.get("day_start")
        if start is not None and value <= start:
            raise ValueError("The business day must end after it starts.")
        return value


# --- LinkedIn outreach --------------------------------------------------------

class ProspectFields(InputModel):
    full_name: Annotated[str | None, _text(200)] = None
    company: Annotated[str | None, _text(200)] = None
    job_title: Annotated[str | None, _text(200)] = None
    notes: Annotated[str | None, _long_text(5000)] = None


class ProspectCreate(ProspectFields):
    linkedin_url: Annotated[str, _text(500, required=True)]  # canonicalized by the service
    source: Annotated[str | None, _text(120)] = None


class ProspectUpdate(ProspectFields):
    linkedin_url: Annotated[str | None, _text(500)] = None
    version: int | None = None


class ProspectRow(InputModel):
    """One row of an import or a paste, before validation (row numbers are 1-based, as shown)."""

    row: int
    linkedin_url: str | None = None
    full_name: Annotated[str | None, _text(200)] = None
    company: Annotated[str | None, _text(200)] = None
    job_title: Annotated[str | None, _text(200)] = None


class PlannedAssignment(InputModel):
    prospect_id: str
    assignee_id: str


class BatchCreate(InputModel):
    name: Annotated[str, _text(120, required=True)]
    work_date: date
    plan: list[PlannedAssignment] = Field(min_length=1, max_length=2000)
    draft: bool = False
    notes: Annotated[str | None, _long_text(2000)] = None


class Reassignment(InputModel):
    assignee_id: str
    reason: Annotated[str | None, _long_text(2000)] = None
    version: int | None = None


class OutreachRecord(InputModel):
    prospect_id: str
    event_type: Annotated[str, _choice(OUTREACH_EVENTS)]
    note: Annotated[str | None, _long_text(5000)] = None
    occurred_at: AwareDateTime = None  # defaults to now
    follow_up_at: AwareDateTime = None  # schedules (or moves) the prospect's follow-up
    request_id: RequestId = None


class FollowUpSchedule(InputModel):
    prospect_id: str
    due_at: datetime
    note: Annotated[str | None, _long_text(2000)] = None
    request_id: RequestId = None

    @field_validator("due_at", mode="before")
    @classmethod
    def _due_aware(cls, value: Any) -> Any:
        parsed = _aware(value)
        if parsed is None:
            raise ValueError("Choose when to follow up.")
        return parsed


class TaskUpdate(TaskFields):
    version: int | None = None


# --- users and authentication -------------------------------------------------

class UserInvite(InputModel):
    email: Annotated[str, _using(norm.normalize_email)]
    full_name: Annotated[str, _text(200, required=True)]
    role: Annotated[str, _choice(ROLES)]


class UserAdminUpdate(InputModel):
    full_name: Annotated[str | None, _text(200)] = None
    role: Annotated[str | None, _choice(ROLES)] = None
    is_active: bool | None = None


class ProfileUpdate(InputModel):
    full_name: Annotated[str | None, _text(200)] = None
    timezone: Annotated[str | None, _using(norm.normalize_timezone)] = None


class PasswordChange(InputModel):
    current_password: Annotated[str, Field(max_length=1024)]
    new_password: Annotated[str, Field(max_length=1024)]


class OrganizationUpdate(InputModel):
    name: Annotated[str, _text(200, required=True)]
    # The team's business time zone: "today", due today, and the end-of-day summary use it.
    timezone: Annotated[str | None, _using(norm.normalize_timezone)] = None


# --- helpers ------------------------------------------------------------------

def error_messages(errors: Iterable[Any]) -> dict[str, str]:
    """Pydantic error items as ``{field: message}`` with user-facing wording."""
    fields: dict[str, str] = {}
    for item in errors:
        location = [str(part) for part in item.get("loc", ()) if not isinstance(part, int)]
        name = location[0] if location else "__all__"
        kind = item.get("type")
        message = str(item.get("msg", "Invalid value.")).removeprefix("Value error, ")
        if kind == "missing":
            message = "This field is required."
        elif kind == "extra_forbidden":
            message = "This field cannot be set."
        elif kind in {"int_parsing", "int_type"}:
            message = "Enter a whole number."
        elif kind in {"bool_parsing", "bool_type"}:
            message = "Choose yes or no."
        elif kind in {"too_short", "too_long"} and name == "lead_ids":
            message = "Select between 1 and 500 leads."
        elif kind in {"too_short", "too_long"} and name == "plan":
            message = "Assign between 1 and 2000 prospects at a time."
        elif kind in {"too_short", "too_long"} and name == "attendee_ids":
            message = "Choose between 1 and 20 team members."
        elif kind in {"date_parsing", "date_type", "date_from_datetime_parsing"}:
            message = "Enter a valid date."
        fields.setdefault(name, message)
    return fields


def parse(model: type[InputModelT], data: Any) -> InputModelT:
    """Validate ``data`` or raise ``ValidationFailed`` with per-field messages."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed("Please correct the highlighted fields.", fields=error_messages(exc.errors())) from exc
