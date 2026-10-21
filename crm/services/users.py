"""User administration, self-service profile, and the organization profile."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import Conflict, PermissionDenied, ValidationFailed
from ..models import Organization, User
from ..schemas import OrganizationUpdate, ProfileUpdate, UserAdminUpdate, UserInvite
from . import audit
from .access import Actor, get_record
from .auth import issue_token, revoke_sessions
from .pagination import Page, PageRequest, like_pattern, paginate


def list_users(db: Session, actor: Actor, *, page: PageRequest, q: str | None = None,
               include_inactive: bool = True) -> Page[User]:
    actor.require("users.view")
    statement = select(User)
    if q:
        pattern = like_pattern(q)
        statement = statement.where(or_(func.lower(User.full_name).like(pattern, escape="\\"),
                                        User.email.like(pattern, escape="\\")))
    if not include_inactive:
        statement = statement.where(User.is_active.is_(True))
    return paginate(db, statement, page, {"name": User.full_name, "email": User.email, "role": User.role,
                                          "last_login": User.last_login_at}, "name", tiebreaker=User.id)


def assignable_users(db: Session, actor: Actor) -> list[User]:
    """Active users, for owner and assignee pickers."""
    return list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)))


def get_user(db: Session, actor: Actor, user_id: Any) -> User:
    if str(user_id) != str(actor.user_id):
        actor.require("users.view")
    return get_record(db, User, user_id)


def invite_user(db: Session, actor: Actor, settings: Settings, data: UserInvite) -> tuple[User, str]:
    """Create an account without a password and return its one-time activation code.

    The code is shown once to the inviting administrator, who hands it over
    (no email service is configured). Only its hash is stored.
    """
    actor.require("users.manage")
    if db.scalar(select(User.id).where(User.email == data.email)) is not None:
        raise Conflict("A user with this email address already exists.", fields={"email": "This email is already in use."})
    user = User(email=data.email, full_name=data.full_name, role=data.role, is_active=True,
                invited_by_id=actor.user_id)
    db.add(user)
    db.flush()
    raw = issue_token(db, settings, user, "invite")
    audit.record(db, actor, "user.invited", entity_type="user", entity_id=user.id,
                 changes={"email": user.email, "role": user.role})
    return user, raw


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(
        User.role == "super_admin", User.is_active.is_(True)
    )) or 0


def update_user(db: Session, actor: Actor, user_id: Any, data: UserAdminUpdate) -> User:
    actor.require("users.manage")
    user = get_record(db, User, user_id)
    changes = data.model_dump(exclude_unset=True)
    if "full_name" in changes and not changes["full_name"]:
        raise ValidationFailed("Please correct the highlighted fields.", fields={"full_name": "This field is required."})
    if "role" in changes and changes["role"] is None:
        raise ValidationFailed("Please correct the highlighted fields.", fields={"role": "Choose a role."})
    if "is_active" in changes and changes["is_active"] is None:
        changes.pop("is_active")
    if user.id == actor.user_id and (changes.get("role", user.role) != user.role or changes.get("is_active") is False):
        raise PermissionDenied("You cannot change your own role or deactivate your own account.")
    removing_admin = user.role == "super_admin" and user.is_active and (
        changes.get("role", "super_admin") != "super_admin" or changes.get("is_active") is False
    )
    if removing_admin and _active_admins(db) <= 1:
        raise Conflict("At least one active Super Admin is required.")
    before = audit.snapshot(user, ("full_name", "role", "is_active"))
    for field, value in changes.items():
        setattr(user, field, value)
    delta = audit.diff(before, audit.snapshot(user, ("full_name", "role", "is_active")))
    if delta:
        if ("is_active" in delta and not user.is_active) or "role" in delta:
            revoke_sessions(db, user.id)  # new permissions apply from the next sign-in
        audit.record(db, actor, "user.updated", entity_type="user", entity_id=user.id, changes=delta)
    db.flush()
    return user


def issue_access_code(db: Session, actor: Actor, settings: Settings, user_id: Any) -> tuple[str, str]:
    """Administrator-issued activation or password-reset code (shown once).

    Returns ``(code, purpose)``: "invite" for accounts that never set a
    password, otherwise "password_reset".
    """
    actor.require("users.manage")
    user = get_record(db, User, user_id)
    if not user.is_active:
        raise Conflict("Reactivate this user before issuing a code.")
    purpose = "invite" if user.password_hash is None else "password_reset"
    raw = issue_token(db, settings, user, purpose)
    audit.record(db, actor, f"user.{purpose}_code_issued", entity_type="user", entity_id=user.id)
    return raw, purpose


def update_profile(db: Session, actor: Actor, data: ProfileUpdate) -> User:
    user = get_record(db, User, actor.user_id)
    changes = data.model_dump(exclude_unset=True)
    if "full_name" in changes and not changes["full_name"]:
        raise ValidationFailed("Please correct the highlighted fields.", fields={"full_name": "This field is required."})
    before = audit.snapshot(user, ("full_name", "timezone"))
    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)
    delta = audit.diff(before, audit.snapshot(user, ("full_name", "timezone")))
    if delta:
        audit.record(db, actor, "user.profile_updated", entity_type="user", entity_id=user.id, changes=delta)
    db.flush()
    return user


def get_organization(db: Session) -> Organization:
    organization = db.get(Organization, 1)
    if organization is None:  # an upgraded database whose first account came from elsewhere
        organization = Organization(id=1, name="My organization")
        db.add(organization)
        db.flush()
    return organization


def update_organization(db: Session, actor: Actor, data: OrganizationUpdate) -> Organization:
    actor.require("org.manage")
    organization = get_organization(db)
    if organization.name != data.name:
        audit.record(db, actor, "organization.updated", entity_type="organization", entity_id=organization.id,
                     changes={"name": [organization.name, data.name]})
        organization.name = data.name
    db.flush()
    return organization
