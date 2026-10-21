"""Alembic environment for the application database (``data/sales.db``).

``core.db`` owns the original analytics tables; these migrations own everything
added since. They always run on a plain connection with foreign-key enforcement
off (SQLite's default), so no schema step can cascade into existing rows.
Never use batch mode (table rebuilds) on ``clients``, ``leads``, or ``sales``.
"""

from __future__ import annotations

from typing import Any, Literal

from alembic import context
from sqlalchemy import create_engine, pool

import crm.models  # noqa: F401  (registers every table on Base.metadata)
from crm.config import load_settings
from crm.db import Base, UTCDateTime

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or load_settings().database_url


def _render_item(type_: str, obj: Any, autogen_context: Any) -> str | Literal[False]:
    # UTCDateTime is a Python-side conversion; the column is a plain DateTime.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


# Owned by core.db.create_base_tables(); autogenerate must never propose changes to them.
_CORE_TABLES = frozenset({"sales", "marketing_spend", "import_metadata", "funnel_events"})


def _include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    if type_ == "table" and name in _CORE_TABLES:
        return False
    table = getattr(obj, "table", None)
    return not (table is not None and table.name in _CORE_TABLES)


def _configure(**kwargs: Any) -> None:
    context.configure(target_metadata=target_metadata, compare_type=True, render_item=_render_item,
                      include_object=_include_object, **kwargs)


def run_migrations_offline() -> None:
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
