"""SQLAlchemy engine, session factory, and shared column types for the application database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import Settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    """Text IDs, like the existing ``clients.id`` and ``leads.id`` columns."""
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """Store timestamps as naive UTC and always return timezone-aware UTC.

    SQLite has no time-zone type, so aware datetimes would otherwise come back
    naive and compare unpredictably. Naive input is rejected rather than guessed at.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def create_db_engine(settings: Settings) -> Engine:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        # The sqlite3 module opens transactions only before INSERT/UPDATE/DELETE,
        # so a SAVEPOINT could become the outermost transaction and its RELEASE
        # would commit. SQLAlchemy's documented fix: disable the driver's handling
        # and emit BEGIN ourselves (below).
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores FKs otherwise
        cursor.execute("PRAGMA journal_mode=WAL")  # as core.db.get_connection(): readers never block
        cursor.close()

    @event.listens_for(engine, "begin")
    def _sqlite_begin(connection: Any) -> None:
        # IMMEDIATE takes the write lock up front, so concurrent writers (another
        # window, the import worker) queue for the busy timeout instead of failing
        # with SQLITE_BUSY when a read transaction later tries to write.
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
