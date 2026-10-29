from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import column, func, select, table
from sqlalchemy.orm import Session, joinedload

from techset_leadgen.analytics.models.client_manager import _generate_client_id
from techset_leadgen.analytics.models.client_validators import client_exists_by_cif, client_exists_by_name, client_field_errors
from techset_leadgen.utils import normalize_text

from techset_leadgen.database.engine import utcnow
from techset_leadgen.errors import Conflict, NotFound, ValidationFailed
from techset_leadgen.database.models import Client, Lead
from techset_leadgen.services.schemas import ClientCreate, ClientUpdate
from techset_leadgen.services import audit
from techset_leadgen.services.access import Actor, get_record
from techset_leadgen.services.common import check_version, drop_unset_defaults, require_values, resolve_owner

_SALES = table("sales", column("client_id"), column("client_name"))

AUDITED_FIELDS = (
    "name", "cif", "address", "contact_person", "email", "primary_domain", "website_url", "industry",
    "employee_range", "country", "city", "account_status", "owner_id", "notes",
)


@dataclass(frozen=True)
class ClientExtras:
    owner_id: str | None
    owner_name: str | None
    account_status: str | None
    industry: str | None
    editable: bool
    deletable: bool


def extras(db: Session, actor: Actor) -> dict[str, ClientExtras]:
    actor.require("clients.view")
    result: dict[str, ClientExtras] = {}
    for client in db.scalars(select(Client).options(joinedload(Client.owner))):
        result[client.id] = ClientExtras(
            client.owner_id, client.owner.full_name if client.owner else None, client.account_status,
            client.industry, actor.can_on("clients.edit", client), actor.can_on("clients.delete", client),
        )
    return result


def get_client(db: Session, actor: Actor, client_id: Any) -> Client:
    actor.require("clients.view")
    return get_record(db, Client, client_id)


def _clean_cif(value: str | None) -> str:
    return normalize_text(value or "").upper()


def _check_rules(db: Session, values: dict[str, Any], *, exclude_id: str | None = None) -> None:
    errors = client_field_errors(values.get("name") or "", values.get("cif") or "", values.get("email") or "",
                                 values.get("contact_person") or "")
    if errors:
        raise ValidationFailed("Please correct the highlighted fields.", fields=errors)
    connection = db.connection().connection.driver_connection
    cif = values.get("cif")
    if cif and cif != "-" and client_exists_by_cif(cif, exclude_id, connection):
        raise Conflict(f"A client with tax ID '{cif}' already exists.",
                       fields={"cif": "Another client already has this tax ID."}, details={"duplicate": "client"})
    if client_exists_by_name(values["name"], exclude_id, connection):
        raise Conflict(
            f"A client named '{values['name']}' already exists. Use a different name, or merge duplicates.",
            fields={"name": "Another client already has this name."}, details={"duplicate": "client"},
        )
    domain = values.get("primary_domain")
    if domain:
        conditions = [Client.primary_domain == domain]
        if exclude_id:
            conditions.append(Client.id != exclude_id)
        existing = db.scalar(select(Client).where(*conditions))
        if existing is not None:
            raise Conflict(f"{existing.name} already uses the domain {domain}.",
                           fields={"primary_domain": "Another client already uses this domain."},
                           details={"duplicate": "client", "existing_id": existing.id})


def _derive_domain(values: dict[str, Any]) -> None:
    from techset_leadgen.services.normalize import InvalidValue, normalize_domain

    if not values.get("primary_domain") and values.get("website_url"):
        try:
            values["primary_domain"] = normalize_domain(values["website_url"])
        except InvalidValue as exc:
            raise ValidationFailed(str(exc), fields={"website_url": str(exc)}) from exc


def create_client(db: Session, actor: Actor, data: ClientCreate) -> Client:
    actor.require("clients.create")
    values = data.model_dump()
    values["cif"] = _clean_cif(values.get("cif"))
    _derive_domain(values)
    _check_rules(db, values)
    values["owner_id"] = resolve_owner(db, actor, "clients.assign", values.get("owner_id"), current=None, record=None)
    values["account_status"] = values.get("account_status") or "prospect"
    client_id = _generate_client_id()
    while db.get(Client, client_id) is not None:
        client_id = _generate_client_id()
    now = utcnow()
    client = Client(id=client_id, **values, created_by_id=actor.user_id, created_at=now, updated_at=now)
    db.add(client)
    db.flush()
    audit.record(db, actor, "client.created", entity_type="client", entity_id=client.id,
                 changes={"name": client.name, "owner_id": client.owner_id})
    return client


def _client_for_update(db: Session, client_id: Any) -> Client:
    client = db.get(Client, str(client_id))
    if client is not None:
        return client
    name = db.scalar(select(func.min(_SALES.c.client_name)).where(_SALES.c.client_id == str(client_id)))
    if name is None:
        raise NotFound()
    client = Client(id=str(client_id), name=name, cif="-")
    db.add(client)
    db.flush()
    return client


def update_client(db: Session, actor: Actor, client_id: Any, data: ClientUpdate) -> Client:
    actor.require("clients.view")
    client = _client_for_update(db, client_id)
    actor.require_on("clients.edit", client)
    changes = data.model_dump(exclude_unset=True)
    check_version(client, changes.pop("version", None))
    require_values(changes, "name")
    drop_unset_defaults(changes, "account_status")
    if "cif" in changes:
        changes["cif"] = _clean_cif(changes["cif"])
    if "website_url" in changes and "primary_domain" not in changes and not client.primary_domain:
        _derive_domain(changes)
    merged = {field: changes.get(field, getattr(client, field)) for field in
              ("name", "cif", "email", "contact_person", "primary_domain")}
    if merged["cif"] == "-":
        merged["cif"] = ""
    _check_rules(db, merged | {"primary_domain": changes.get("primary_domain")}, exclude_id=client.id)
    if "owner_id" in changes:
        changes["owner_id"] = resolve_owner(db, actor, "clients.assign", changes["owner_id"],
                                            current=client.owner_id, record=client)
    before = audit.snapshot(client, AUDITED_FIELDS)
    for field, value in changes.items():
        setattr(client, field, value)
    delta = audit.diff(before, audit.snapshot(client, AUDITED_FIELDS))
    if delta:
        client.updated_at = utcnow()
        db.flush()
        audit.record(db, actor, "client.updated", entity_type="client", entity_id=client.id, changes=delta)
    return client


def delete_client(db: Session, actor: Actor, client_id: Any) -> tuple[str, int]:
    client = get_client(db, actor, client_id)
    actor.require_on("clients.delete", client)
    sales = db.scalar(select(func.count()).select_from(_SALES).where(_SALES.c.client_id == client.id)) or 0
    leads = db.scalar(select(func.count()).select_from(Lead).where(Lead.client_id == client.id)) or 0
    name = client.name
    db.delete(client)
    db.flush()
    audit.record(db, actor, "client.deleted", entity_type="client", entity_id=client_id,
                 changes={"name": name, "sales_deleted": sales, "leads_unlinked": leads})
    return name, int(sales)


def assign_client(db: Session, actor: Actor, client_id: Any, owner_id: str | None,
                  version: int | None = None) -> Client:
    actor.require("clients.edit")
    client = get_client(db, actor, client_id)
    check_version(client, version)
    previous = client.owner_id
    client.owner_id = resolve_owner(db, actor, "clients.assign", owner_id, current=previous, record=client)
    if previous != client.owner_id:
        client.updated_at = utcnow()
        db.flush()
        audit.record(db, actor, "client.assigned", entity_type="client", entity_id=client.id,
                     changes={"owner_id": [previous, client.owner_id]})
    return client


def choices(db: Session, actor: Actor) -> list[tuple[str, str]]:
    actor.require("clients.view")
    return [(client_id, name) for client_id, name in db.execute(select(Client.id, Client.name).order_by(Client.name))]

