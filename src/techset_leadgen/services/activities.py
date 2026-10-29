from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from techset_leadgen.database.engine import utcnow
from techset_leadgen.errors import ValidationFailed
from techset_leadgen.database.models import Activity
from techset_leadgen.services.schemas import ActivityCreate
from techset_leadgen.services import audit
from techset_leadgen.services.access import Actor
from techset_leadgen.services.common import referenced_client, referenced_contact, referenced_lead

_CLOCK_SKEW = timedelta(minutes=5)


def create_activity(db: Session, actor: Actor, data: ActivityCreate) -> Activity:
    actor.require("activities.create")
    lead = referenced_lead(db, data.lead_id) if data.lead_id else None
    client = referenced_client(db, data.client_id) if data.client_id else None
    contact = referenced_contact(db, data.contact_id) if data.contact_id else None
    if lead is None and client is None and contact is None:
        raise ValidationFailed("Link the activity to a client or a lead.")
    client_id = client.id if client else (lead.client_id if lead else (contact.client_id if contact else None))
    if lead and client and lead.client_id != client.id:
        raise ValidationFailed("The client does not match the lead.", fields={"client_id": "Does not match the lead."})
    occurred_at = data.occurred_at or utcnow()
    if occurred_at > utcnow() + _CLOCK_SKEW:
        raise ValidationFailed("Activities record what already happened; add a task for future work.",
                               fields={"occurred_at": "Choose a time that is not in the future."})
    activity = Activity(activity_type=data.activity_type, subject=data.subject, body=data.body,
                        occurred_at=occurred_at, client_id=client_id, contact_id=contact.id if contact else None,
                        lead_id=lead.id if lead else None, created_by_id=actor.user_id)
    db.add(activity)
    if lead and (lead.last_activity_at is None or occurred_at > lead.last_activity_at):
        lead.last_activity_at = occurred_at
    db.flush()
    audit.record(db, actor, "activity.created", entity_type="activity", entity_id=activity.id,
                 changes={"activity_type": activity.activity_type, "lead_id": activity.lead_id,
                          "client_id": activity.client_id})
    return activity


def for_subject(db: Session, actor: Actor, *, lead_id: Any = None, client_id: Any = None,
                limit: int = 200) -> list[Activity]:
    statement = select(Activity).options(joinedload(Activity.created_by), joinedload(Activity.contact))
    if lead_id is not None:
        actor.require("leads.view")
        statement = statement.where(Activity.lead_id == str(lead_id))
    elif client_id is not None:
        actor.require("clients.view")
        statement = statement.where(Activity.client_id == str(client_id))
    else:
        raise ValidationFailed("Choose a client or a lead.")
    return list(db.scalars(statement.order_by(Activity.occurred_at.desc()).limit(limit)))

