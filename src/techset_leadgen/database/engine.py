from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from techset_leadgen.config import Settings

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
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator[datetime]):
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


SERVER_TIMEOUTS = {
    "connect_timeout": 10,
    "options": "-c statement_timeout=30000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=60000",
}


def create_db_engine(settings: Settings) -> Engine:
    if settings.is_server:
        return create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=4,
            max_overflow=4,
            pool_recycle=1800,
            connect_args={**SERVER_TIMEOUTS, "application_name": "Techset LeadGen"},
        )
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _sqlite_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

