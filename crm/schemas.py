"""Validated input for every change made through the screens.

Every model forbids unknown fields, so a form cannot set server-owned
attributes (IDs, status, reasons, audit columns). Cleaning (trimming,
normalizing domains/emails, rejecting unsafe URLs) happens here; rules that
need the database happen in the services.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from .errors import ValidationFailed
from .services import normalize as norm
from .vocabulary import (
    ACCOUNT_STATUSES,
    ACTIVITY_TYPES,
    EMPLOYEE_RANGES,
    LEAD_STATUSES,
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


OptionalId = Annotated[str | None, BeforeValidator(_blank_to_none)]
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
    assigned_to_id: OptionalId = None
    priority: Annotated[str | None, _choice(PRIORITIES)] = None
    due_at: AwareDateTime = None


class TaskCreate(TaskFields):
    title: Annotated[str, _text(200, required=True)]


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
        fields.setdefault(name, message)
    return fields


def parse(model: type[InputModelT], data: Any) -> InputModelT:
    """Validate ``data`` or raise ``ValidationFailed`` with per-field messages."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed("Please correct the highlighted fields.", fields=error_messages(exc.errors())) from exc
