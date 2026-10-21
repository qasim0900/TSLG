"""Programmatic Alembic helpers used by the desktop app (on start-up) and the tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import Connection

ALEMBIC_INI = Path(__file__).with_name("alembic.ini")


def alembic_config(database_url: str | None = None) -> Config:
    """Without a URL, migrations use the configured application database (``crm.config``)."""
    config = Config(str(ALEMBIC_INI))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str | None, revision: str) -> None:
    command.downgrade(alembic_config(database_url), revision)


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_and_head(connection: Connection) -> tuple[str | None, str | None]:
    current = MigrationContext.configure(connection).get_current_revision()
    return current, head_revision()


def is_known(revision: str) -> bool:
    """False when the database was migrated by a newer version of the application."""
    try:
        return ScriptDirectory.from_config(alembic_config()).get_revision(revision) is not None
    except CommandError:
        return False


@dataclass(frozen=True)
class SchemaState:
    current: str | None
    head: str | None

    @property
    def ready(self) -> bool:
        return self.current == self.head

    @property
    def empty(self) -> bool:
        return self.current is None

    @property
    def newer_than_app(self) -> bool:
        return self.current is not None and not is_known(self.current)


def schema_state(connection: Connection) -> SchemaState:
    return SchemaState(*current_and_head(connection))


# What revision 0001 created. The standalone CRM database of an earlier build was
# also stamped "0001" but has a different layout, so the label alone is not proof.
_UNIFIED_TABLES = frozenset({"organization", "users", "user_sessions", "audit_logs", "contacts", "tasks",
                             "activities", "lead_status_history", "clients", "leads", "sales"})
_UNIFIED_COLUMNS = {"clients": frozenset({"owner_id", "version"}), "leads": frozenset({"owner_id", "version"})}


def layout_problems(connection: Connection) -> list[str]:
    """Differences between the database and the unified layout (empty when it matches)."""
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    problems = [f"missing table {name}" for name in sorted(_UNIFIED_TABLES - tables)]
    for table, columns in _UNIFIED_COLUMNS.items():
        if table in tables:
            present = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
            problems += [f"missing column {table}.{name}" for name in sorted(columns - present)]
    if "companies" in tables and "organization" not in tables:
        problems.insert(0, "this is the standalone CRM database of an earlier build")
    return problems
