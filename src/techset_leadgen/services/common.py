from __future__ import annotations

from typing import Any

from sqlalchemy import false
from sqlalchemy.orm import Session

from techset_leadgen.errors import Conflict, NotFound, ValidationFailed
from techset_leadgen.database.models import Client, Contact, Lead
from techset_leadgen.services.access import Actor, get_record, get_user

STALE_MESSAGE = "This record was changed by someone else. Reload it and try again."


def check_version(record: Any, expected: int | None) -> None:
    if expected is not None and expected != record.version:
        raise Conflict(STALE_MESSAGE, details={"current_version": record.version})


def require_values(changes: dict[str, Any], *fields: str) -> None:
    missing = {field: "This field is required." for field in fields if field in changes and changes[field] in (None, "")}
    if missing:
        raise ValidationFailed("Please correct the highlighted fields.", fields=missing)


def drop_unset_defaults(changes: dict[str, Any], *fields: str) -> None:
    for field in fields:
        if field in changes and changes[field] is None:
            del changes[field]


def resolve_owner(db: Session, actor: Actor, permission: str, owner_id: str | None, *, current: str | None,
                  record: object | None, field: str = "owner_id") -> str | None:
    owner_id = owner_id or None
    if owner_id == current:
        return owner_id
    if owner_id is not None:
        get_user(db, owner_id, field=field)
    self_service = owner_id == actor.user_id and current is None
    if not self_service:
        if record is None:
            actor.require(permission)
        else:
            actor.require_on(permission, record)
    return owner_id


def _referenced(db: Session, model: type[Any], record_id: Any, *, field: str, noun: str) -> Any:
    try:
        return get_record(db, model, record_id)
    except NotFound as exc:
        raise ValidationFailed(f"Choose an existing {noun}.", fields={field: f"Choose an existing {noun}."}) from exc


def referenced_client(db: Session, client_id: Any, *, field: str = "client_id") -> Client:
    client: Client = _referenced(db, Client, client_id, field=field, noun="client")
    return client


def referenced_lead(db: Session, lead_id: Any, *, field: str = "lead_id") -> Lead:
    lead: Lead = _referenced(db, Lead, lead_id, field=field, noun="lead")
    return lead


def referenced_contact(db: Session, contact_id: Any, *, field: str = "contact_id") -> Contact:
    contact: Contact = _referenced(db, Contact, contact_id, field=field, noun="contact")
    return contact


def owner_filter(statement: Any, column: Any, owner: str | None, actor: Actor) -> Any:
    if not owner:
        return statement
    if owner == "me":
        return statement.where(column == actor.user_id)
    if owner == "none":
        return statement.where(column.is_(None))
    return statement.where(column == owner) if owner.strip() else statement.where(false())

