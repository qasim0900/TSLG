from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from techset_leadgen.database.engine import Base, UTCDateTime, new_id, utcnow
from techset_leadgen.domain.vocabulary import ACTIVITY_TYPES, PRIORITIES, TASK_KINDS, TASK_STATUSES, check_in
from techset_leadgen.database.models.identity import User
from techset_leadgen.database.models.outreach import Prospect


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    cif: Mapped[str] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)
    contact_person: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    primary_domain: Mapped[str | None] = mapped_column(String(253))
    website_url: Mapped[str | None] = mapped_column(String(500))
    industry: Mapped[str | None] = mapped_column(String(120))
    employee_range: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(80))
    account_status: Mapped[str | None] = mapped_column(String(16))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String)
    created_on: Mapped[str] = mapped_column("created_at", String)
    source: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    meeting_date: Mapped[str | None] = mapped_column(String)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    title: Mapped[str | None] = mapped_column(String(200))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(String(8), server_default=text("'medium'"))
    notes: Mapped[str | None] = mapped_column(Text)
    qualification_reason: Mapped[str | None] = mapped_column(Text)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}

    client: Mapped[Client | None] = relationship()
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])


class LeadStatusChange(Base):
    __tablename__ = "lead_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


_NOT_NULL_EMAIL = text("email IS NOT NULL")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_client", "client_id"),
        Index("uq_contacts_email", "email", unique=True, sqlite_where=_NOT_NULL_EMAIL),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), default="")
    full_name: Mapped[str] = mapped_column(String(201))
    job_title: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}

    client: Mapped[Client] = relationship()


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(check_in("activity_type", ACTIVITY_TYPES), name="activity_type"),
        CheckConstraint("client_id IS NOT NULL OR lead_id IS NOT NULL", name="has_subject"),
        Index("ix_activities_lead", "lead_id", "occurred_at"),
        Index("ix_activities_client", "client_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    activity_type: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    created_by: Mapped[User | None] = relationship()
    contact: Mapped[Contact | None] = relationship()


_OPEN_FOLLOW_UP = text("kind = 'follow_up' AND status = 'open'")
_HAS_REQUEST = text("request_id IS NOT NULL")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(check_in("status", TASK_STATUSES), name="status"),
        CheckConstraint(check_in("priority", PRIORITIES), name="priority"),
        CheckConstraint(check_in("kind", TASK_KINDS), name="kind"),
        Index("ix_tasks_assignee_status", "assigned_to_id", "status"),
        Index("ix_tasks_due", "due_at"),
        Index("ix_tasks_lead", "lead_id"),
        Index("ix_tasks_prospect", "prospect_id"),
        Index("ix_tasks_kind_status_due", "kind", "status", "due_at"),
        Index("uq_tasks_open_follow_up", "prospect_id", unique=True,
              sqlite_where=_OPEN_FOLLOW_UP, postgresql_where=_OPEN_FOLLOW_UP),
        Index("uq_tasks_request", "request_id", unique=True, sqlite_where=_HAS_REQUEST,
              postgresql_where=_HAS_REQUEST),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    assigned_to_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(String(8), default="medium")
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(12), default="open")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    kind: Mapped[str] = mapped_column(String(12), default="task", server_default=text("'task'"))
    prospect_id: Mapped[str | None] = mapped_column(ForeignKey("prospects.id"))
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("prospect_assignments.id", ondelete="SET NULL"))
    outcome: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    __mapper_args__ = {"version_id_col": version}

    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id])
    lead: Mapped[Lead | None] = relationship()
    client: Mapped[Client | None] = relationship()
    prospect: Mapped[Prospect | None] = relationship()

