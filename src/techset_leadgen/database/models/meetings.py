from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from techset_leadgen.database.engine import Base, UTCDateTime, new_id, utcnow
from techset_leadgen.database.models.identity import User
from techset_leadgen.database.models.records import Client


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled', 'completed', 'cancelled')", name="status"),
        CheckConstraint("ends_at > starts_at", name="time_range"),
        Index("ix_meetings_status_start", "status", "starts_at"),
        Index("ix_meetings_client_start", "client_id", "status", "starts_at"),
        Index("ix_meetings_client_name", "client_name"),
        Index("uq_meetings_request", "request_id", unique=True, sqlite_where=text("request_id IS NOT NULL"),
              postgresql_where=text("request_id IS NOT NULL")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    client_name: Mapped[str] = mapped_column(String(200))
    client_email: Mapped[str | None] = mapped_column(String(254))
    title: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    link: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="scheduled", server_default=text("'scheduled'"))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    request_id: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}

    client: Mapped[Client | None] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    attendee_links: Mapped[list[MeetingAttendee]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="MeetingAttendee.id")

    @property
    def attendees(self) -> list[User]:
        return sorted((link.user for link in self.attendee_links), key=lambda user: user.full_name.casefold())

    @property
    def attendee_ids(self) -> set[str]:
        return {link.user_id for link in self.attendee_links}


class MeetingAttendee(Base):
    __tablename__ = "meeting_attendees"
    __table_args__ = (
        Index("uq_meeting_attendees", "meeting_id", "user_id", unique=True),
        Index("ix_meeting_attendees_user", "user_id", "meeting_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="attendee_links")
    user: Mapped[User] = relationship()

