from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from techset_leadgen.domain.source_labels import SOURCE_LABELS
from techset_leadgen.analytics.models.lead_manager import _generate_lead_id

from techset_leadgen.database.engine import utcnow
from techset_leadgen.errors import Conflict, NotFound, ValidationFailed
from techset_leadgen.database.models import Activity, AuditLog, Lead, LeadStatusChange
from techset_leadgen.services.schemas import BulkAssignment, LeadCreate, LeadTransition, LeadUpdate
from techset_leadgen.domain.vocabulary import CLOSED_STATUSES, LEAD_STATUSES, LEAD_TRANSITIONS, REASON_REQUIRED
from techset_leadgen.services import audit
from techset_leadgen.services.access import Actor, get_record, get_user, user_names
from techset_leadgen.services.common import check_version, drop_unset_defaults, referenced_client, require_values, resolve_owner

QUALIFICATION_STATUSES = frozenset({"qualified", "lost"})
AUDITED_FIELDS = ("title", "client_id", "source", "meeting_date", "owner_id", "priority", "notes")


@dataclass(frozen=True)
class LeadExtras:
    title: str | None
    owner_id: str | None
    owner_name: str | None
    priority: str
    next_follow_up_at: datetime | None
    editable: bool


def extras(db: Session, actor: Actor) -> dict[str, LeadExtras]:
    actor.require("leads.view")
    return {
        lead.id: LeadExtras(lead.title, lead.owner_id, lead.owner.full_name if lead.owner else None,
                            lead.priority or "medium", lead.next_follow_up_at, actor.can_on("leads.edit", lead))
        for lead in db.scalars(select(Lead).options(joinedload(Lead.owner)))
    }


def display_title(lead: Lead) -> str:
    if lead.title:
        return lead.title
    if lead.client is not None:
        return f"{lead.client.name} ({lead.created_on})"
    return f"{SOURCE_LABELS.get(lead.source, lead.source)} lead ({lead.created_on})"


def get_lead(db: Session, actor: Actor, lead_id: Any) -> Lead:
    actor.require("leads.view")
    return get_record(db, Lead, lead_id)


def _open_duplicate(db: Session, client_id: str | None) -> Lead | None:
    if client_id is None:
        return None
    return db.scalar(select(Lead).where(Lead.client_id == client_id,
                                        Lead.status.not_in(sorted(CLOSED_STATUSES))).limit(1))


def local_today(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).date().isoformat()


def create_lead(db: Session, actor: Actor, data: LeadCreate) -> Lead:
    actor.require("leads.create")
    values = data.model_dump()
    allow_duplicate = values.pop("allow_duplicate")
    if values.get("client_id"):
        values["client_id"] = referenced_client(db, values["client_id"]).id
    if not allow_duplicate:
        existing = _open_duplicate(db, values.get("client_id"))
        if existing is not None:
            raise Conflict("This client already has an open lead.",
                           details={"duplicate": "lead", "existing_id": existing.id,
                                    "existing_title": display_title(existing)})
    values["owner_id"] = resolve_owner(db, actor, "leads.assign", values.get("owner_id"), current=None, record=None)
    values["priority"] = values.get("priority") or "medium"
    values["created_on"] = values.get("created_on") or local_today(actor.timezone)
    lead_id = _generate_lead_id()
    while db.get(Lead, lead_id) is not None:
        lead_id = _generate_lead_id()
    lead = Lead(id=lead_id, **values, status="new", created_by_id=actor.user_id, updated_at=utcnow())
    db.add(lead)
    db.flush()
    db.add(LeadStatusChange(lead_id=lead.id, from_status=None, to_status="new", changed_by_id=actor.user_id))
    audit.record(db, actor, "lead.created", entity_type="lead", entity_id=lead.id,
                 changes={"title": lead.title, "client_id": lead.client_id, "source": lead.source,
                          "owner_id": lead.owner_id})
    return lead


def update_lead(db: Session, actor: Actor, lead_id: Any, data: LeadUpdate) -> Lead:
    lead = get_lead(db, actor, lead_id)
    actor.require_on("leads.edit", lead)
    changes = data.model_dump(exclude_unset=True)
    check_version(lead, changes.pop("version", None))
    require_values(changes, "source")
    drop_unset_defaults(changes, "priority")
    if changes.get("client_id"):
        changes["client_id"] = referenced_client(db, changes["client_id"]).id
    if lead.status == "converted" and "client_id" in changes and not changes["client_id"]:
        raise ValidationFailed("A lead marked Client must stay linked to its client.",
                               fields={"client_id": "Required for leads marked Client."})
    if "owner_id" in changes:
        changes["owner_id"] = resolve_owner(db, actor, "leads.assign", changes["owner_id"],
                                            current=lead.owner_id, record=lead)
    before = audit.snapshot(lead, AUDITED_FIELDS)
    for field, value in changes.items():
        setattr(lead, field, value)
    delta = audit.diff(before, audit.snapshot(lead, AUDITED_FIELDS))
    if delta:
        lead.updated_at = utcnow()
        db.flush()
        audit.record(db, actor, "lead.updated", entity_type="lead", entity_id=lead.id, changes=delta)
    return lead


def allowed_transitions(actor: Actor, lead: Lead) -> list[str]:
    if not actor.can_on("leads.edit", lead):
        return []
    options = []
    for target in LEAD_STATUSES:
        if target not in LEAD_TRANSITIONS.get(lead.status, frozenset()):
            continue
        if (target in QUALIFICATION_STATUSES or lead.status in QUALIFICATION_STATUSES) and not actor.can_on(
            "leads.qualify", lead
        ):
            continue
        options.append(target)
    return options


def transition(db: Session, actor: Actor, lead_id: Any, data: LeadTransition, *,
               meeting_date: str | None = None) -> Lead:
    lead = get_lead(db, actor, lead_id)
    actor.require_on("leads.edit", lead)
    check_version(lead, data.version)
    target, current = data.status, lead.status
    if target == current:
        raise Conflict(f"The lead is already at {LEAD_STATUSES.get(target, target)}.")
    if target not in LEAD_TRANSITIONS.get(current, frozenset()):
        allowed = ", ".join(LEAD_STATUSES[item] for item in sorted(LEAD_TRANSITIONS.get(current, ())))
        raise Conflict(f"A lead cannot move from {LEAD_STATUSES.get(current, current)} to "
                       f"{LEAD_STATUSES[target]}." + (f" Allowed: {allowed}." if allowed else ""),
                       details={"allowed": sorted(LEAD_TRANSITIONS.get(current, ()))})
    if target in QUALIFICATION_STATUSES or current in QUALIFICATION_STATUSES:
        actor.require_on("leads.qualify", lead)
    if target in REASON_REQUIRED and not data.reason:
        raise ValidationFailed("Explain the decision.", fields={"reason": "A reason is required for this stage."})
    if target == "converted" and lead.client_id is None:
        raise ValidationFailed("Link the lead to a client before marking it Client.",
                               fields={"status": "Link the lead to a client first (Edit lead)."})
    if meeting_date:
        try:
            lead.meeting_date = date.fromisoformat(meeting_date).isoformat()
        except ValueError as exc:
            raise ValidationFailed("Enter a date as YYYY-MM-DD.", fields={"meeting_date": "Enter a valid date."}) from exc
    lead.status = target
    if target == "qualified":
        lead.qualification_reason = data.reason
    elif target == "lost":
        lead.lost_reason = data.reason
    lead.updated_at = utcnow()
    db.add(LeadStatusChange(lead_id=lead.id, from_status=current, to_status=target, reason=data.reason,
                            changed_by_id=actor.user_id))
    db.flush()
    audit.record(db, actor, "lead.status_changed", entity_type="lead", entity_id=lead.id,
                 changes={"status": [current, target], "reason": data.reason})
    return lead


def assign(db: Session, actor: Actor, lead_id: Any, owner_id: str | None, version: int | None = None) -> Lead:
    actor.require("leads.edit")
    lead = get_lead(db, actor, lead_id)
    check_version(lead, version)
    previous = lead.owner_id
    lead.owner_id = resolve_owner(db, actor, "leads.assign", owner_id, current=previous, record=lead)
    if previous != lead.owner_id:
        lead.updated_at = utcnow()
        db.flush()
        audit.record(db, actor, "lead.assigned", entity_type="lead", entity_id=lead.id,
                     changes={"owner_id": [previous, lead.owner_id]})
    return lead


def bulk_assign(db: Session, actor: Actor, data: BulkAssignment) -> int:
    actor.require("leads.assign")
    if data.owner_id is not None:
        get_user(db, data.owner_id, field="owner_id")
    ids = list(dict.fromkeys(data.lead_ids))
    found = list(db.scalars(select(Lead).where(Lead.id.in_(ids))))
    if len(found) != len(ids):
        raise NotFound("One or more selected leads were not found.")
    changed = 0
    for lead in found:
        actor.require_on("leads.assign", lead)
        if lead.owner_id != data.owner_id:
            audit.record(db, actor, "lead.assigned", entity_type="lead", entity_id=lead.id,
                         changes={"owner_id": [lead.owner_id, data.owner_id], "bulk": True})
            lead.owner_id = data.owner_id
            lead.updated_at = utcnow()
            changed += 1
    db.flush()
    return changed


def status_history(db: Session, actor: Actor, lead: Lead) -> list[LeadStatusChange]:
    actor.require("leads.view")
    return list(db.scalars(select(LeadStatusChange).where(LeadStatusChange.lead_id == lead.id)
                           .order_by(LeadStatusChange.changed_at.desc(), LeadStatusChange.id.desc())))


@dataclass(frozen=True)
class TimelineEntry:
    kind: str
    occurred_at: datetime
    title: str
    body: str | None
    actor_name: str | None


def timeline(db: Session, actor: Actor, lead: Lead, *, limit: int = 200) -> list[TimelineEntry]:
    actor.require("leads.view")
    names = user_names(db)
    entries: list[TimelineEntry] = []
    for activity in db.scalars(select(Activity).where(Activity.lead_id == lead.id)
                               .order_by(Activity.occurred_at.desc()).limit(limit)):
        entries.append(TimelineEntry(activity.activity_type, activity.occurred_at, activity.subject, activity.body,
                                     names.get(activity.created_by_id or "")))
    for change in status_history(db, actor, lead)[:limit]:
        if change.from_status:
            title = (f"Stage: {LEAD_STATUSES.get(change.from_status, change.from_status)} → "
                     f"{LEAD_STATUSES.get(change.to_status, change.to_status)}")
        else:
            title = "Lead created"
        entries.append(TimelineEntry("stage", change.changed_at, title, change.reason,
                                     names.get(change.changed_by_id or "")))
    for entry in db.scalars(select(AuditLog).where(
        AuditLog.entity_type == "lead", AuditLog.entity_id == lead.id,
        AuditLog.action.in_(("lead.updated", "lead.assigned")),
    ).order_by(AuditLog.created_at.desc()).limit(limit)):
        changed = sorted((entry.changes or {}).keys() - {"bulk"})
        if entry.action == "lead.assigned":
            new_owner = (entry.changes or {}).get("owner_id", [None, None])[1]
            title = f"Assigned to {names.get(new_owner, 'someone')}" if new_owner else "Unassigned"
        else:
            title = "Edited " + ", ".join(field.replace("_", " ") for field in changed)
        entries.append(TimelineEntry("change", entry.created_at, title, None, names.get(entry.actor_user_id or "")))
    entries.sort(key=lambda item: item.occurred_at, reverse=True)
    return entries[:limit]


def open_choices(db: Session, actor: Actor, *, limit: int = 2000) -> list[tuple[str, str]]:
    actor.require("leads.view")
    found = db.scalars(select(Lead).where(Lead.status.not_in(sorted(CLOSED_STATUSES)))
                       .options(joinedload(Lead.client)).order_by(Lead.created_on.desc()).limit(limit))
    return [(lead.id, display_title(lead)) for lead in found]


def for_client(db: Session, actor: Actor, client_id: str) -> list[Lead]:
    actor.require("leads.view")
    return list(db.scalars(select(Lead).where(Lead.client_id == client_id).options(joinedload(Lead.owner))
                           .order_by(Lead.created_on.desc())))

