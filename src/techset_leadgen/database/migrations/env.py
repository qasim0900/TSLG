from __future__ import annotations

from typing import Any, Literal

from alembic import context
from sqlalchemy import create_engine, pool

import techset_leadgen.database.models
from techset_leadgen.config import load_settings
from techset_leadgen.database.engine import Base, UTCDateTime

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or load_settings().database_url


def _render_item(type_: str, obj: Any, autogen_context: Any) -> str | Literal[False]:
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


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

