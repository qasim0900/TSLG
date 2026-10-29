from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from techset_leadgen.errors import NotFound, PermissionDenied, ValidationFailed
from techset_leadgen.database.models import Client, Contact, Lead, Task, User
from techset_leadgen.security.permissions import Scope, scope_for

M = TypeVar("M")


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str
    email: str = ""
    full_name: str = ""
    timezone: str = "UTC"
    client_host: str | None = None

    @classmethod
    def for_user(cls, user: User, *, client_host: str | None = None) -> Actor:
        return cls(user_id=user.id, role=user.role, email=user.email, full_name=user.full_name,
                   timezone=user.timezone, client_host=client_host)

    def scope(self, permission: str) -> Scope | None:
        return scope_for(self.role, permission)

    def can(self, permission: str) -> bool:
        return self.scope(permission) is not None

    def require(self, permission: str) -> Scope:
        scope = self.scope(permission)
        if scope is None:
            raise PermissionDenied()
        return scope

    def can_on(self, permission: str, record: object) -> bool:
        scope = self.scope(permission)
        return scope is Scope.ALL or (scope is Scope.OWN and owns(record, self.user_id))

    def require_on(self, permission: str, record: object) -> None:
        if not self.can_on(permission, record):
            raise PermissionDenied()


def owns(record: object, user_id: str) -> bool:
    if isinstance(record, Task):
        return user_id in (record.assigned_to_id, record.created_by_id)
    if isinstance(record, Contact):
        return record.client is not None and owns(record.client, user_id)
    if isinstance(record, Client | Lead):
        if record.owner_id is not None:
            return record.owner_id == user_id
        return record.created_by_id == user_id
    return False


def get_record(session: Session, model: type[M], record_id: Any) -> M:
    if record_id is None or str(record_id).strip() == "":
        raise NotFound()
    record = session.get(model, str(record_id))
    if record is None:
        raise NotFound()
    return record


def get_user(session: Session, user_id: Any, *, field: str, active_only: bool = True) -> User:
    user = session.get(User, str(user_id)) if user_id else None
    if user is None or (active_only and not user.is_active):
        raise ValidationFailed("Choose an active user.", fields={field: "Choose an active user."})
    return user


def id_filter(statement: Any, column: Any, value: Any) -> Any:
    key = str(value).strip() if value is not None else ""
    return statement.where(column == key) if key else statement.where(false())


def user_names(session: Session) -> dict[str, str]:
    return {user_id: name for user_id, name in session.execute(select(User.id, User.full_name)).all()}

