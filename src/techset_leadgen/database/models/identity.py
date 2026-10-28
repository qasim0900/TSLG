"""The organization profile, user accounts, sessions, and sign-in records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from techset_leadgen.database.engine import Base, UTCDateTime, new_id, utcnow
from techset_leadgen.domain.vocabulary import ROLES, TOKEN_PURPOSES, check_in


class Organization(Base):
    """The business that uses this database (a single row)."""

    __tablename__ = "organization"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # The team's business day: "assigned today", batch work dates, and team reports use it.
    # Each person still sees times (and their own "due today") in their own time zone.
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default=text("'UTC'"))
    # Meeting scheduling (revision 0004, see domain.scheduling): the buffer kept between meetings,
    # and the business hours (minutes after midnight) and ISO weekdays offered as free slots.
    meeting_buffer_mode: Mapped[str] = mapped_column(String(12), default="post", server_default=text("'post'"))
    meeting_buffer_minutes: Mapped[int] = mapped_column(Integer, default=120, server_default=text("120"))
    meeting_day_start: Mapped[int] = mapped_column(Integer, default=540, server_default=text("540"))
    meeting_day_end: Mapped[int] = mapped_column(Integer, default=1080, server_default=text("1080"))
    meeting_work_days: Mapped[str] = mapped_column(String(7), default="12345", server_default=text("'12345'"))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(check_in("role", ROLES), name="role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lower-case
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None until an invitation is accepted
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    invited_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class UserSession(Base):
    """A signed-in desktop session.

    The application keeps only an opaque random token in memory; the database
    stores its hash, so sessions can expire or be revoked (sign-out, password
    change, deactivation, role change) and every action re-checks them.
    """

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    client_host: Mapped[str | None] = mapped_column(String(128))  # computer name
    client_app: Mapped[str | None] = mapped_column(String(128))  # application version and OS

    user: Mapped[User] = relationship()


class UserToken(Base):
    """One-time account activation or password-reset code (stored hashed)."""

    __tablename__ = "user_tokens"
    __table_args__ = (CheckConstraint(check_in("purpose", TOKEN_PURPOSES), name="purpose"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship()


class AuthAttempt(Base):
    """Sign-in attempts, used for lockout and security review."""

    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_email_created", "email", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254))
    client_host: Mapped[str | None] = mapped_column(String(128))
    succeeded: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
