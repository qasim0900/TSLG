"""LinkedIn outreach: prospects, daily assignment batches, assignments, outreach events, notifications.

A prospect is one LinkedIn member profile, identified by its canonical key
(``crm.services.normalize.linkedin_profile``). Who works it, and when, lives in
``prospect_assignments`` (never overwritten: a reassignment closes one row and
opens another); what happened lives in ``outreach_events`` (append-only).
Follow-ups are ``tasks`` rows with ``kind = 'follow_up'``.

Rows here are never cascade-deleted from a prospect: history outlives edits.
"""

from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from techset_leadgen.domain.outreach import OPEN_ASSIGNMENT_STATUSES

from techset_leadgen.database.engine import Base, UTCDateTime, new_id, utcnow
from techset_leadgen.domain.vocabulary import ASSIGNMENT_STATUSES, BATCH_STATUSES, OUTREACH_EVENTS, PROSPECT_STATUSES, check_in
from techset_leadgen.database.models.identity import User

_OPEN_ASSIGNMENT = text(check_in("status", sorted(OPEN_ASSIGNMENT_STATUSES)))


class Prospect(Base):
    __tablename__ = "prospects"
    __table_args__ = (
        CheckConstraint(check_in("status", PROSPECT_STATUSES), name="status"),
        Index("ix_prospects_status", "status"),
        Index("ix_prospects_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    linkedin_key: Mapped[str] = mapped_column(String(300), unique=True)  # "in/jane-doe-1a2b"
    linkedin_url: Mapped[str] = mapped_column(String(400))  # canonical https address
    full_name: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(String(120))  # "Pasted", "Import: march.csv", ...
    status: Mapped[str] = mapped_column(String(20), default="new")  # derived from outreach events
    notes: Mapped[str | None] = mapped_column(Text)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # earliest open follow-up
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class AssignmentBatch(Base):
    """A manager's daily distribution of prospects. Draft batches are invisible to assignees."""

    __tablename__ = "assignment_batches"
    __table_args__ = (
        CheckConstraint(check_in("status", BATCH_STATUSES), name="status"),
        Index("ix_assignment_batches_work_date", "work_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    work_date: Mapped[date] = mapped_column(Date)  # the business day the work is for
    status: Mapped[str] = mapped_column(String(12), default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class ProspectAssignment(Base):
    """One person responsible for one prospect for a period of time.

    Lifecycle: planned (draft batch) -> assigned -> in_progress (first event) ->
    completed; or cancelled / reassigned. Closed rows are kept as history.
    """

    __tablename__ = "prospect_assignments"
    __table_args__ = (
        CheckConstraint(check_in("status", ASSIGNMENT_STATUSES), name="status"),
        # One open assignment per prospect: two managers assigning the same profile cannot both win.
        Index("uq_prospect_assignments_open", "prospect_id", unique=True,
              sqlite_where=_OPEN_ASSIGNMENT, postgresql_where=_OPEN_ASSIGNMENT),
        Index("ix_prospect_assignments_assignee", "assignee_id", "status"),
        Index("ix_prospect_assignments_batch", "batch_id"),
        Index("ix_prospect_assignments_prospect", "prospect_id", "assigned_at"),
        Index("ix_prospect_assignments_closed", "closed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"))
    assignee_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("assignment_batches.id", ondelete="SET NULL"))
    assigned_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    previous_assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("prospect_assignments.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), default="assigned")
    due_on: Mapped[date | None] = mapped_column(Date)  # the business day it should be finished
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)  # when it became visible
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # completed, cancelled, or reassigned
    closed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    close_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}

    prospect: Mapped[Prospect] = relationship()
    assignee: Mapped[User] = relationship(foreign_keys=[assignee_id])
    batch: Mapped[AssignmentBatch | None] = relationship()


class OutreachEvent(Base):
    """Something a team member did or observed on LinkedIn, as they recorded it. Append-only."""

    __tablename__ = "outreach_events"
    __table_args__ = (
        CheckConstraint(check_in("event_type", OUTREACH_EVENTS), name="event_type"),
        Index("ix_outreach_events_prospect", "prospect_id", "occurred_at"),
        Index("ix_outreach_events_recorded_by", "recorded_by_id", "occurred_at"),
        Index("ix_outreach_events_type", "event_type", "occurred_at"),
        Index("ix_outreach_events_assignment", "assignment_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"))
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("prospect_assignments.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    recorded_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Set by the client for each save; a retried save with the same ID is not recorded twice.
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True)

    recorded_by: Mapped[User | None] = relationship(foreign_keys=[recorded_by_id])


class Notification(Base):
    """A message for one user about work given to them. Read state is per notification."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("recipient_id", "dedupe_key", name="uq_notifications_dedupe"),
        Index("ix_notifications_recipient", "recipient_id", "read_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(120))
    # The same event never notifies the same person twice (e.g. a retried batch activation).
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
