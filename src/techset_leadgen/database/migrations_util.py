"""Programmatic Alembic helpers used by the desktop app (on start-up) and the tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import Connection, create_engine, inspect, pool, text

ALEMBIC_INI = Path(__file__).with_name("alembic.ini")


def alembic_config(database_url: str | None = None) -> Config:
    """Without a URL, migrations use the configured application database (``crm.config``)."""
    config = Config(str(ALEMBIC_INI))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


# Any constant: every computer upgrading the shared database takes the same lock.
_UPGRADE_LOCK = 72_710_027


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    """Migrate the database. A PostgreSQL upgrade holds an advisory lock, so two
    administrators (or two computers) can never run the migrations at the same time;
    its DDL is transactional, so a failed upgrade leaves the previous schema intact."""
    config = alembic_config(database_url)
    url = config.get_main_option("sqlalchemy.url") or ""
    if not url.startswith("postgresql"):
        command.upgrade(config, revision)
        return
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _UPGRADE_LOCK})
            connection.commit()  # the lock belongs to the session, not to this transaction
            try:
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
                connection.commit()
            finally:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _UPGRADE_LOCK})
                connection.commit()
    finally:
        engine.dispose()


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


# What each revision created. The standalone CRM database of an earlier build
# was also stamped "0001" but has a different layout, so the label alone is not
# proof that it is safe to run a later migration against the file.
_REVISION_TABLES = {
    "0001": frozenset({
        "organization", "users", "user_sessions", "user_tokens", "auth_attempts", "audit_logs",
        "contacts", "tasks", "activities", "lead_status_history", "clients", "leads", "sales",
        "marketing_spend", "import_metadata", "funnel_events",
    }),
    "0002": frozenset({
        "organization", "users", "user_sessions", "user_tokens", "auth_attempts", "audit_logs",
        "contacts", "tasks", "activities", "lead_status_history", "clients", "leads", "sales",
        "marketing_spend", "import_metadata", "funnel_events", "prospects", "assignment_batches",
        "prospect_assignments", "outreach_events", "notifications",
    }),
    "0003": frozenset({
        "organization", "users", "user_sessions", "user_tokens", "auth_attempts", "audit_logs",
        "contacts", "tasks", "activities", "lead_status_history", "clients", "leads", "sales",
        "marketing_spend", "import_metadata", "funnel_events", "prospects", "assignment_batches",
        "prospect_assignments", "outreach_events", "notifications", "meetings",
    }),
    "0004": frozenset({
        "organization", "users", "user_sessions", "user_tokens", "auth_attempts", "audit_logs",
        "contacts", "tasks", "activities", "lead_status_history", "clients", "leads", "sales",
        "marketing_spend", "import_metadata", "funnel_events", "prospects", "assignment_batches",
        "prospect_assignments", "outreach_events", "notifications", "meetings", "meeting_attendees",
    }),
}
_REVISION_COLUMNS = {
    "0001": {
        "clients": frozenset({"owner_id", "version"}),
        "leads": frozenset({"owner_id", "version"}),
    },
    "0002": {
        "clients": frozenset({"owner_id", "version"}),
        "leads": frozenset({"owner_id", "version"}),
        "organization": frozenset({"timezone"}),
        "tasks": frozenset({"kind", "prospect_id", "assignment_id", "outcome", "request_id"}),
        "prospects": frozenset({"linkedin_key", "linkedin_url", "status", "version"}),
        "prospect_assignments": frozenset({"prospect_id", "assignee_id", "status", "version"}),
        "outreach_events": frozenset({"prospect_id", "event_type", "request_id"}),
        "notifications": frozenset({"recipient_id", "dedupe_key", "read_at"}),
    },
    "0003": {
        "clients": frozenset({"owner_id", "version"}),
        "leads": frozenset({"owner_id", "version"}),
        "organization": frozenset({"timezone"}),
        "tasks": frozenset({"kind", "prospect_id", "assignment_id", "outcome", "request_id"}),
        "prospects": frozenset({"linkedin_key", "linkedin_url", "status", "version"}),
        "prospect_assignments": frozenset({"prospect_id", "assignee_id", "status", "version"}),
        "outreach_events": frozenset({"prospect_id", "event_type", "request_id"}),
        "notifications": frozenset({"recipient_id", "dedupe_key", "read_at"}),
        "meetings": frozenset({"attendee_id", "starts_at", "ends_at", "status", "version"}),
    },
    "0004": {
        "clients": frozenset({"owner_id", "version"}),
        "leads": frozenset({"owner_id", "version"}),
        "organization": frozenset({"timezone", "meeting_buffer_mode", "meeting_buffer_minutes",
                                   "meeting_day_start", "meeting_day_end", "meeting_work_days"}),
        "tasks": frozenset({"kind", "prospect_id", "assignment_id", "outcome", "request_id"}),
        "prospects": frozenset({"linkedin_key", "linkedin_url", "status", "version"}),
        "prospect_assignments": frozenset({"prospect_id", "assignee_id", "status", "version"}),
        "outreach_events": frozenset({"prospect_id", "event_type", "request_id"}),
        "notifications": frozenset({"recipient_id", "dedupe_key", "read_at"}),
        "meetings": frozenset({"client_id", "client_email", "starts_at", "ends_at", "status", "version"}),
        "meeting_attendees": frozenset({"meeting_id", "user_id"}),
    },
}


def _layout_problems(connection: Connection, revision: str) -> list[str]:
    expected_tables = _REVISION_TABLES[revision]
    expected_columns = _REVISION_COLUMNS[revision]
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    problems = [f"missing table {name}" for name in sorted(expected_tables - tables)]
    for table, columns in expected_columns.items():
        if table in tables:
            present = {column["name"] for column in inspector.get_columns(table)}
            problems += [f"missing column {table}.{name}" for name in sorted(columns - present)]
    if "companies" in tables and "organization" not in tables:
        problems.insert(0, "this is the standalone CRM database of an earlier build")
    return problems


def pre_upgrade_layout_problems(connection: Connection, revision: str | None) -> list[str]:
    """Refuse a falsely stamped or damaged schema *before* changing it.

    An unversioned database is allowed because revision 0001 intentionally
    adopts the original core tables. Known versioned databases, however, must
    match the minimum layout their revision promises before a later migration
    can safely assume those tables and columns exist.
    """
    tables = set(inspect(connection).get_table_names())
    if "companies" in tables and "organization" not in tables:
        return ["this is the standalone CRM database of an earlier build"]
    if revision is None:
        return []
    expected = revision if revision in _REVISION_TABLES else max(_REVISION_TABLES)
    return _layout_problems(connection, expected)


def layout_problems(connection: Connection) -> list[str]:
    """Differences between the database and the unified layout (empty when it matches)."""
    return _layout_problems(connection, max(_REVISION_TABLES))
