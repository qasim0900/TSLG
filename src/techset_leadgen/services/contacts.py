"""Contacts: the people at a client besides the main contact kept on the client itself.

Contacts follow their client's permissions: whoever may edit the client may
manage its people. Email addresses and phone numbers are returned only to roles
that may view sensitive details, and audit entries never record their values.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from techset_leadgen.database.engine import utcnow
from techset_leadgen.errors import Conflict, PermissionDenied, ValidationFailed
from techset_leadgen.database.models import Contact
from techset_leadgen.services.schemas import ContactCreate, ContactUpdate
from techset_leadgen.services import audit
from techset_leadgen.services.access import Actor, get_record
from techset_leadgen.services.common import check_version, drop_unset_defaults, referenced_client, require_values

AUDITED_FIELDS = ("first_name", "last_name", "job_title", "email", "phone", "do_not_contact",
                  "suppression_reason", "notes")
SENSITIVE_FIELDS = ("email", "phone")


def list_for_client(db: Session, actor: Actor, client_id: Any) -> list[Contact]:
    actor.require("clients.view")
    return list(db.scalars(select(Contact).where(Contact.client_id == str(client_id))
                           .options(joinedload(Contact.client)).order_by(Contact.full_name)))


def get_contact(db: Session, actor: Actor, contact_id: Any) -> Contact:
    actor.require("clients.view")
    return get_record(db, Contact, contact_id)


def _guard_sensitive(actor: Actor, fields: set[str]) -> None:
    if not actor.can("clients.view_sensitive") and set(SENSITIVE_FIELDS) & fields:
        raise PermissionDenied("Your role cannot set email addresses or phone numbers.")


def _check_email_unique(db: Session, email: str | None, exclude: str | None = None) -> None:
    if not email:
        return
    conditions = [Contact.email == email]
    if exclude is not None:
        conditions.append(Contact.id != exclude)
    existing = db.scalar(select(Contact).where(*conditions))
    if existing is not None:
        raise Conflict(f"{existing.full_name} already uses this email address.",
                       fields={"email": "Another contact already uses this email address."},
                       details={"duplicate": "contact", "existing_id": existing.id})


def _require_reason(do_not_contact: bool, reason: str | None) -> None:
    if do_not_contact and not reason:
        raise ValidationFailed("Give a reason for the do-not-contact flag.",
                               fields={"suppression_reason": "Required when do-not-contact is set."})


def _full_name(first: str, last: str | None) -> str:
    return f"{first} {last or ''}".strip()


def create_contact(db: Session, actor: Actor, data: ContactCreate) -> Contact:
    client = referenced_client(db, data.client_id)
    actor.require_on("clients.edit", client)
    _guard_sensitive(actor, data.model_fields_set)
    values = data.model_dump()
    _check_email_unique(db, values.get("email"))
    _require_reason(values["do_not_contact"], values.get("suppression_reason"))
    values["last_name"] = values.get("last_name") or ""
    contact = Contact(**values, full_name=_full_name(values["first_name"], values["last_name"]),
                      created_by_id=actor.user_id)
    db.add(contact)
    db.flush()
    audit.record(db, actor, "contact.created", entity_type="contact", entity_id=contact.id,
                 changes={"full_name": contact.full_name, "client_id": contact.client_id})
    return contact


def update_contact(db: Session, actor: Actor, contact_id: Any, data: ContactUpdate) -> Contact:
    contact = get_contact(db, actor, contact_id)
    actor.require_on("clients.edit", contact.client)
    _guard_sensitive(actor, data.model_fields_set)
    changes = data.model_dump(exclude_unset=True)
    check_version(contact, changes.pop("version", None))
    require_values(changes, "first_name")
    drop_unset_defaults(changes, "do_not_contact")
    if "email" in changes and changes["email"] != contact.email:
        _check_email_unique(db, changes["email"], exclude=contact.id)
    do_not_contact = changes.get("do_not_contact", contact.do_not_contact)
    if not do_not_contact:
        changes["suppression_reason"] = None
    _require_reason(do_not_contact, changes.get("suppression_reason", contact.suppression_reason))
    before = audit.snapshot(contact, AUDITED_FIELDS)
    for field, value in changes.items():
        setattr(contact, field, value)
    contact.last_name = contact.last_name or ""
    contact.full_name = _full_name(contact.first_name, contact.last_name)
    delta = audit.diff(before, audit.snapshot(contact, AUDITED_FIELDS))
    if delta:
        contact.updated_at = utcnow()
        db.flush()
        audit.record(db, actor, "contact.updated", entity_type="contact", entity_id=contact.id,
                     changes={field: ["[changed]"] if field in SENSITIVE_FIELDS else value
                              for field, value in delta.items()})
    return contact


def delete_contact(db: Session, actor: Actor, contact_id: Any) -> str:
    contact = get_contact(db, actor, contact_id)
    actor.require_on("clients.edit", contact.client)
    name = contact.full_name
    db.delete(contact)
    db.flush()
    audit.record(db, actor, "contact.deleted", entity_type="contact", entity_id=contact_id,
                 changes={"full_name": name, "client_id": contact.client_id})
    return name


def can_view_sensitive(actor: Actor) -> bool:
    return actor.can("clients.view_sensitive")
