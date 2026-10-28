"""Bounded global search across prospects and retained legacy records."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from techset_leadgen.database.models import Client, Contact, Lead, Prospect
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import like_pattern
from techset_leadgen.services.prospects import visibility as prospect_visibility

MIN_QUERY = 2
PER_TYPE = 10


@dataclass(frozen=True)
class SearchResults:
    query: str
    prospects: list[Prospect]
    clients: list[Client]
    contacts: list[Contact]
    leads: list[Lead]

    @property
    def total(self) -> int:
        return len(self.prospects) + len(self.clients) + len(self.contacts) + len(self.leads)


def search(db: Session, actor: Actor, query: str) -> SearchResults:
    term = (query or "").strip()[:100]
    if len(term) < MIN_QUERY:
        return SearchResults(term, [], [], [], [])
    pattern = like_pattern(term)
    prospects: list[Prospect] = []
    clients: list[Client] = []
    contacts: list[Contact] = []
    leads: list[Lead] = []
    if actor.can("prospects.view"):
        prospects = list(db.scalars(select(Prospect).where(
            prospect_visibility(actor),
            or_(func.lower(Prospect.full_name).like(pattern, escape="\\"),
                func.lower(Prospect.company).like(pattern, escape="\\"),
                func.lower(Prospect.job_title).like(pattern, escape="\\"),
                Prospect.linkedin_key.like(pattern, escape="\\")),
        ).order_by(Prospect.last_activity_at.desc(), Prospect.created_at.desc()).limit(PER_TYPE)))
    sensitive = actor.can("clients.view_sensitive")
    if actor.can("clients.view"):
        conditions = [func.lower(Client.name).like(pattern, escape="\\"),
                      func.lower(Client.id).like(pattern, escape="\\"),
                      Client.primary_domain.like(pattern, escape="\\")]
        if sensitive:  # do not let searches probe hidden details
            conditions.append(func.lower(Client.email).like(pattern, escape="\\"))
        clients = list(db.scalars(select(Client).where(or_(*conditions)).order_by(Client.name).limit(PER_TYPE)))
        contact_conditions = [func.lower(Contact.full_name).like(pattern, escape="\\")]
        if sensitive:
            contact_conditions.append(Contact.email.like(pattern, escape="\\"))
        contacts = list(db.scalars(select(Contact).where(or_(*contact_conditions)).options(
            joinedload(Contact.client)).order_by(Contact.full_name).limit(PER_TYPE)))
    if actor.can("leads.view"):
        leads = list(db.scalars(select(Lead).outerjoin(Client, Lead.client_id == Client.id).where(or_(
            func.lower(Lead.title).like(pattern, escape="\\"),
            func.lower(Lead.id).like(pattern, escape="\\"),
            func.lower(Lead.external_id).like(pattern, escape="\\"),
            func.lower(Client.name).like(pattern, escape="\\"),
        )).options(joinedload(Lead.client)).order_by(Lead.created_on.desc()).limit(PER_TYPE)))
    return SearchResults(term, prospects, clients, contacts, leads)
