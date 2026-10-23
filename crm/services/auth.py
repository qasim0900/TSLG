"""Sign-in, desktop sessions, activation codes, and password changes.

Passwords are hashed with Argon2id (argon2-cffi). Each signed-in desktop app
holds a random session token in memory; the database keeps only its hash plus
expiry and revocation state, so a session can be ended from any computer.
Account activation and password resets use one-time codes that an
administrator hands over (no email provider is configured).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..db import utcnow
from ..errors import Conflict, DomainError, RateLimited, ValidationFailed
from ..models import AuthAttempt, Organization, User, UserSession, UserToken
from ..security.passwords import hash_password, needs_rehash, validate_password, verify_password
from ..security.tokens import hash_token, new_token
from . import audit
from .access import Actor
from .normalize import InvalidValue, email_lookup_key, normalize_email

_LAST_SEEN_RESOLUTION = timedelta(minutes=1)
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,100}$")


class InvalidCredentials(DomainError):
    status_code = 401
    code = "invalid_credentials"


class InvalidCode(DomainError):
    status_code = 400
    code = "invalid_code"

    def __init__(self) -> None:
        super().__init__("This code is invalid, already used, or expired. Ask an administrator for a new one.")


class SessionEnded(DomainError):
    """The desktop session is no longer valid; the app must return to the sign-in screen."""

    status_code = 401
    code = "session_ended"


@dataclass(frozen=True)
class SignIn:
    user: User
    session: UserSession
    raw_token: str


# --- sign-in -----------------------------------------------------------------

def _recent_failures(db: Session, email: str, since: object) -> int:
    return db.scalar(
        select(func.count()).select_from(AuthAttempt).where(
            AuthAttempt.email == email, AuthAttempt.succeeded.is_(False), AuthAttempt.created_at >= since
        )
    ) or 0


def authenticate(db: Session, settings: Settings, *, email: str, password: str,
                 client_host: str | None = None, client_app: str | None = None) -> SignIn:
    """Verify credentials and open a session. Commits, including the record of a failure."""
    key = email_lookup_key(email)
    window_start = utcnow() - timedelta(minutes=settings.login_window_minutes)
    if _recent_failures(db, key, window_start) >= settings.login_max_failures:
        raise RateLimited(
            f"Too many unsuccessful sign-in attempts for this account. Wait {settings.login_window_minutes} "
            "minutes and try again, or ask an administrator for a reset code."
        )
    user = db.scalar(select(User).where(User.email == key))
    password_ok = verify_password(user.password_hash if user else None, password)
    if user is None or not password_ok or not user.is_active:
        db.add(AuthAttempt(email=key, client_host=client_host, succeeded=False))
        if user is not None:
            audit.record(db, None, "auth.login_failed", entity_type="user", entity_id=user.id,
                         changes={"reason": "inactive" if password_ok else "bad_password"},
                         client_host=client_host)
        db.commit()
        raise InvalidCredentials("Incorrect email or password.")

    assert user.password_hash is not None  # verify_password() is False without a hash
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    db.add(AuthAttempt(email=key, client_host=client_host, succeeded=True))
    signed_in = open_session(db, settings, user, client_host=client_host, client_app=client_app)
    audit.record(db, None, "auth.login", entity_type="user", entity_id=user.id, client_host=client_host)
    db.commit()
    return signed_in


def open_session(db: Session, settings: Settings, user: User, *, client_host: str | None,
                 client_app: str | None) -> SignIn:
    raw = new_token()
    now = utcnow()
    row = UserSession(
        user_id=user.id,
        token_hash=hash_token(raw),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        client_host=(client_host or "")[:128] or None,
        client_app=(client_app or "")[:128] or None,
    )
    db.add(row)
    db.flush()
    return SignIn(user=user, session=row, raw_token=raw)


def check_session(db: Session, settings: Settings, *, session_id: str, raw_token: str,
                  touch: bool = True) -> UserSession:
    """Return the live session or raise ``SessionEnded`` explaining why.

    ``touch`` records recent activity; the desktop passes ``False`` when the
    user has been idle, so the server-side idle limit still applies.
    """
    # Always re-read the row and its user: a cached copy could hide a revocation
    # or deactivation made from another computer.
    row = db.scalar(
        select(UserSession).options(joinedload(UserSession.user)).where(UserSession.id == session_id)
        .execution_options(populate_existing=True)
    )
    now = utcnow()
    if row is None or row.token_hash != hash_token(raw_token):
        raise SessionEnded("Your session is not valid. Please sign in again.")
    if row.revoked_at is not None:
        raise SessionEnded("You were signed out: the session was ended (sign-out elsewhere, a password or "
                           "role change, or an administrator action). Please sign in again.")
    if not row.user.is_active:
        raise SessionEnded("Your account has been deactivated. Contact an administrator.")
    if row.expires_at <= now:
        raise SessionEnded(f"Sessions last at most {settings.session_absolute_hours} hours. Please sign in again.")
    if row.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= now:
        raise SessionEnded(f"You were signed out after {settings.session_idle_minutes} minutes of inactivity.")
    if touch and now - row.last_seen_at >= _LAST_SEEN_RESOLUTION:
        row.last_seen_at = now
    return row


def sign_out(db: Session, actor: Actor, session_id: str) -> None:
    row = db.get(UserSession, session_id)
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()
    audit.record(db, actor, "auth.logout", entity_type="user", entity_id=actor.user_id)


def revoke_sessions(db: Session, user_id: str, *, keep: str | None = None) -> int:
    statement = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    if keep is not None:
        statement = statement.where(UserSession.id != keep)
    result = db.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)


# --- one-time codes ----------------------------------------------------------

def issue_token(db: Session, settings: Settings, user: User, purpose: str) -> str:
    """Create a one-time code, invalidating older unused codes for the user."""
    now = utcnow()
    db.execute(
        update(UserToken)
        .where(UserToken.user_id == user.id, UserToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw = new_token()
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=hash_token(raw),
                     expires_at=now + timedelta(hours=settings.token_ttl_hours)))
    db.flush()
    return raw


def _live_token(db: Session, raw: str) -> UserToken:
    code = (raw or "").strip()
    if not _CODE_PATTERN.match(code):
        raise InvalidCode()
    token = db.scalar(select(UserToken).where(UserToken.token_hash == hash_token(code)))
    if token is None or token.used_at is not None or token.expires_at <= utcnow() or not token.user.is_active:
        raise InvalidCode()
    return token


def code_owner(db: Session, raw: str) -> tuple[User, str]:
    """Who a code belongs to and whether it activates an account or resets a password."""
    token = _live_token(db, raw)
    return token.user, token.purpose


def redeem_code(db: Session, settings: Settings, *, raw_code: str, password: str,
                client_host: str | None = None, client_app: str | None = None) -> SignIn:
    """Set a password with a one-time code, end other sessions, and sign in. Commits."""
    token = _live_token(db, raw_code)
    user = token.user
    validate_password(password, email=user.email, full_name=user.full_name)
    user.password_hash = hash_password(password)
    token.used_at = utcnow()
    revoke_sessions(db, user.id)
    action = "user.invite_accepted" if token.purpose == "invite" else "auth.password_reset"
    audit.record(db, None, action, entity_type="user", entity_id=user.id, client_host=client_host)
    user.last_login_at = utcnow()
    signed_in = open_session(db, settings, user, client_host=client_host, client_app=client_app)
    db.commit()
    return signed_in


def change_password(db: Session, actor: Actor, *, current_session_id: str,
                    current_password: str, new_password: str) -> int:
    """Change the caller's password and end their other sessions; returns how many ended."""
    user = db.get(User, actor.user_id)
    assert user is not None
    if not verify_password(user.password_hash, current_password):
        raise ValidationFailed("Your current password is incorrect.",
                               fields={"current_password": "Your current password is incorrect."})
    validate_password(new_password, email=user.email, full_name=user.full_name, field="new_password")
    user.password_hash = hash_password(new_password)
    ended = revoke_sessions(db, user.id, keep=current_session_id)
    audit.record(db, actor, "auth.password_changed", entity_type="user", entity_id=user.id,
                 changes={"other_sessions_ended": ended})
    return ended


# --- first run ---------------------------------------------------------------

def has_users(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None


def bootstrap_organization(db: Session, *, organization_name: str, admin_email: str,
                           admin_name: str, password: str) -> User:
    """Name the organization and create its first Super Admin.

    The first-run screen calls this only while the database has no users at
    all; afterwards accounts are created by administrators.
    """
    fields: dict[str, str] = {}
    try:
        email = normalize_email(admin_email)
    except InvalidValue as exc:
        fields["admin_email"] = str(exc)
        email = None
    if not email and "admin_email" not in fields:
        fields["admin_email"] = "This field is required."
    if not organization_name.strip():
        fields["organization_name"] = "This field is required."
    if not admin_name.strip():
        fields["admin_name"] = "This field is required."
    if fields:
        raise ValidationFailed("Please correct the highlighted fields.", fields=fields)
    assert email is not None
    validate_password(password, email=email, full_name=admin_name)
    if has_users(db):
        raise Conflict("Accounts already exist. Sign in instead.")
    organization = db.get(Organization, 1)
    if organization is None:
        organization = Organization(id=1, name=organization_name.strip())
        db.add(organization)
    else:
        organization.name = organization_name.strip()
    user = User(email=email, full_name=admin_name.strip(), password_hash=hash_password(password),
                role="super_admin", is_active=True)
    db.add(user)
    db.flush()
    audit.record(db, None, "organization.created", entity_type="organization", entity_id=1,
                 changes={"name": organization.name, "admin_user_id": user.id})
    return user
