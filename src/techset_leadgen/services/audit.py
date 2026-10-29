from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from techset_leadgen.errors import NotFound
from techset_leadgen.database.models import AuditLog
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import Page, PageRequest, paginate

_SECRET_FIELDS = {"password", "password_hash", "token", "token_hash", "code"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def snapshot(record: object, fields: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(record, field) for field in fields}


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    return {
        field: [_jsonable(before.get(field)), _jsonable(after.get(field))]
        for field in after
        if field not in _SECRET_FIELDS and before.get(field) != after.get(field)
    }


def record(
    session: Session,
    actor: Actor | None,
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: object | None = None,
    changes: dict[str, Any] | None = None,
    client_host: str | None = None,
) -> None:
    safe_changes = None
    if changes:
        safe_changes = {key: _jsonable(value) for key, value in changes.items() if key not in _SECRET_FIELDS}
    session.add(
        AuditLog(
            actor_user_id=actor.user_id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            changes=safe_changes,
            client_host=client_host or (actor.client_host if actor else None),
        )
    )


def list_entries(db: Session, actor: Actor, *, page: PageRequest, entity_type: str | None = None,
                 entity_id: str | None = None, action: str | None = None,
                 actions: Collection[str] | None = None) -> Page[AuditLog]:
    actor.require("audit.view")
    statement = select(AuditLog).options(joinedload(AuditLog.actor))
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if entity_id:
        statement = statement.where(AuditLog.entity_id == entity_id)
    if action:
        statement = statement.where(AuditLog.action == action)
    if actions is not None:
        statement = statement.where(AuditLog.action.in_(list(actions)))
    return paginate(db, statement, page, {"created": AuditLog.created_at}, "-created", tiebreaker=AuditLog.id)


def get_entry(db: Session, actor: Actor, entry_id: Any) -> AuditLog:
    actor.require("audit.view")
    try:
        key = int(entry_id)
    except (TypeError, ValueError) as exc:
        raise NotFound() from exc
    entry = db.scalar(select(AuditLog).where(AuditLog.id == key).options(joinedload(AuditLog.actor)))
    if entry is None:
        raise NotFound()
    return entry

