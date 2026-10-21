"""Clients, leads, contacts, activities, and tasks.

``clients`` and ``leads`` are the original analytics tables (created by
``core.db``); imports, the funnel and sales analytics, and these models all read
and write the same rows. The CRM migration only added optional columns to them.
Dates that came with the original schema stay ``YYYY-MM-DD`` text.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, UTCDateTime, new_id, utcnow
from ..vocabulary import ACTIVITY_TYPES, PRIORITIES, TASK_STATUSES, check_in
from .identity import User


class Client(Base):
    __tablename__ = "clients"

    # Original columns (core.db): IDs come from imported files or are "M_XXXXXX".
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    cif: Mapped[str] = mapped_column(String)  # tax ID; "-" when unknown
    address: Mapped[str | None] = mapped_column(String)
    contact_person: Mapped[str | None] = mapped_column(String)  # main contact
    email: Mapped[str | None] = mapped_column(String)  # main contact's email
    # Added by the CRM migration.
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
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # None for rows created by imports
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))  # optimistic concurrency
    __mapper_args__ = {"version_id_col": version}

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])


class Lead(Base):
    __tablename__ = "leads"

    # Original columns (core.db).
    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String)
    created_on: Mapped[str] = mapped_column("created_at", String)  # YYYY-MM-DD the lead arrived
    source: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    meeting_date: Mapped[str | None] = mapped_column(String)  # YYYY-MM-DD
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    # Added by the CRM migration.
    title: Mapped[str | None] = mapped_column(String(200))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(String(8), server_default=text("'medium'"))
    notes: Mapped[str | None] = mapped_column(Text)
    qualification_reason: Mapped[str | None] = mapped_column(Text)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # earliest open task
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
    """People at a client besides the main contact stored on the client itself."""

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
    email: Mapped[str | None] = mapped_column(String(254))  # stored lower-case; unique when present
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
    """A note, call, email, or meeting logged against a client or lead."""

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


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(check_in("status", TASK_STATUSES), name="status"),
        CheckConstraint(check_in("priority", PRIORITIES), name="priority"),
        Index("ix_tasks_assignee_status", "assigned_to_id", "status"),
        Index("ix_tasks_due", "due_at"),
        Index("ix_tasks_lead", "lead_id"),
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
    __mapper_args__ = {"version_id_col": version}

    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id])
    lead: Mapped[Lead | None] = relationship()
    client: Mapped[Client | None] = relationship()
