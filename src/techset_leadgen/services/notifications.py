from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from techset_leadgen.database.engine import utcnow
from techset_leadgen.database.models import Notification
from techset_leadgen.errors import NotFound
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import Page, PageRequest, paginate

RECENT_LIMIT = 30


def notify(db: Session, recipient_id: str, *, kind: str, title: str, body: str | None = None,
           entity_type: str | None = None, entity_id: str | None = None, dedupe_key: str | None = None,
           actor: Actor | None = None) -> Notification | None:
    if actor is not None and recipient_id == actor.user_id:
        return None
    if dedupe_key is not None and db.scalar(select(Notification.id).where(
            Notification.recipient_id == recipient_id, Notification.dedupe_key == dedupe_key)) is not None:
        return None
    notification = Notification(recipient_id=recipient_id, kind=kind, title=title[:200], body=body,
                                entity_type=entity_type, entity_id=entity_id, dedupe_key=dedupe_key)
    db.add(notification)
    return notification


def unread_count(db: Session, actor: Actor) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == actor.user_id, Notification.read_at.is_(None))) or 0


def recent(db: Session, actor: Actor, *, limit: int = RECENT_LIMIT) -> list[Notification]:
    return list(db.scalars(select(Notification).where(Notification.recipient_id == actor.user_id)
                           .order_by(Notification.read_at.is_not(None), Notification.created_at.desc(),
                                     Notification.id.desc()).limit(limit)))


SORTS = {"created": Notification.created_at}


def list_notifications(db: Session, actor: Actor, *, page: PageRequest, unread: bool = False) -> Page[Notification]:
    statement = select(Notification).where(Notification.recipient_id == actor.user_id)
    if unread:
        statement = statement.where(Notification.read_at.is_(None))
    return paginate(db, statement, page, SORTS, "-created", tiebreaker=Notification.id)


def get_notification(db: Session, actor: Actor, notification_id: int) -> Notification:
    found = db.scalar(select(Notification).where(Notification.id == notification_id,
                                                 Notification.recipient_id == actor.user_id))
    if found is None:
        raise NotFound()
    return found


def mark_read(db: Session, actor: Actor, ids: list[int] | None = None, *, now: datetime | None = None) -> int:
    statement = update(Notification).where(Notification.recipient_id == actor.user_id,
                                           Notification.read_at.is_(None))
    if ids is not None:
        statement = statement.where(Notification.id.in_(ids))
    result = db.execute(statement.values(read_at=now or utcnow()))
    return int(getattr(result, "rowcount", 0) or 0)

