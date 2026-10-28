"""Accounts, audit trail, contacts, tasks, and lead workflow on the application database.

Adds new tables and optional columns to the original ``clients`` and ``leads``
tables. Uses ``ALTER TABLE ... ADD COLUMN`` only: rebuilding ``clients`` would
drop it, and with foreign keys on, that cascades to its sales.

SQLite runs exactly the DDL it always ran. A PostgreSQL team database (added
later, never migrated before) gets the original tables from
``_create_base_tables_postgresql`` and ``TIMESTAMP`` where SQLite says ``DATETIME``.

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLIENT_COLUMNS = (
    "primary_domain VARCHAR(253)",
    "website_url VARCHAR(500)",
    "industry VARCHAR(120)",
    "employee_range VARCHAR(16)",
    "country VARCHAR(80)",
    "city VARCHAR(80)",
    "account_status VARCHAR(16)",
    "owner_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    "notes TEXT",
    "created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    "created_at DATETIME",
    "updated_at DATETIME",
    "version INTEGER NOT NULL DEFAULT 1",
)
_LEAD_COLUMNS = (
    "title VARCHAR(200)",
    "owner_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    "priority VARCHAR(8) NOT NULL DEFAULT 'medium'",
    "notes TEXT",
    "qualification_reason TEXT",
    "lost_reason TEXT",
    "next_follow_up_at DATETIME",
    "last_activity_at DATETIME",
    "created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    "updated_at DATETIME",
    "version INTEGER NOT NULL DEFAULT 1",
)


def _ids(name: str) -> sa.Column:
    return sa.Column(name, sa.String(36), nullable=False, primary_key=True)


def _user_ref(name: str, ondelete: str = "SET NULL") -> sa.Column:
    return sa.Column(name, sa.String(36), sa.ForeignKey("users.id", ondelete=ondelete), nullable=True)


def _create_base_tables_postgresql() -> None:
    """The original analytics tables (``local_db.create_base_tables``) in PostgreSQL types.

    Dates stay ``YYYY-MM-DD`` text, as the analytics read and write them.
    """
    text_id = sa.Column("id", sa.Text(), primary_key=True)
    op.create_table("clients", text_id, sa.Column("name", sa.Text(), nullable=False),
                    sa.Column("cif", sa.Text(), nullable=False), sa.Column("address", sa.Text()),
                    sa.Column("contact_person", sa.Text()), sa.Column("email", sa.Text()))
    op.create_table("sales", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("client_name", sa.Text(), nullable=False),
                    sa.Column("client_id", sa.Text(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("product_type", sa.Text(), nullable=False), sa.Column("price", sa.Float(), nullable=False),
                    sa.Column("date", sa.Text(), nullable=False))
    op.create_table("leads", sa.Column("id", sa.Text(), primary_key=True), sa.Column("external_id", sa.Text()),
                    sa.Column("created_at", sa.Text(), nullable=False), sa.Column("source", sa.Text(), nullable=False),
                    sa.Column("status", sa.Text(), nullable=False), sa.Column("meeting_date", sa.Text()),
                    sa.Column("client_id", sa.Text(), sa.ForeignKey("clients.id", ondelete="SET NULL")))
    op.create_table("marketing_spend", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("source", sa.Text(), nullable=False), sa.Column("amount", sa.Float(), nullable=False),
                    sa.Column("date", sa.Text(), nullable=False))
    op.create_table("import_metadata", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("imported_at", sa.Text(), nullable=False), sa.Column("file_name", sa.Text()),
                    sa.Column("total_rows", sa.Integer()), sa.Column("valid_rows", sa.Integer()),
                    sa.Column("rejected_rows", sa.Integer()), sa.Column("duration_seconds", sa.Float()))
    op.create_table("funnel_events", sa.Column("id", sa.Text(), primary_key=True),
                    sa.Column("client_id", sa.Text(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
                    sa.Column("lead_id", sa.Text(), sa.ForeignKey("leads.id", ondelete="SET NULL")),
                    sa.Column("event_type", sa.Text(), nullable=False), sa.Column("source", sa.Text()),
                    sa.Column("event_date", sa.Text(), nullable=False), sa.Column("metadata", sa.Text()))
    for name, table, columns in (
        ("idx_sales_date", "sales", ["date"]), ("idx_sales_client_name", "sales", ["client_name"]),
        ("idx_sales_product_type", "sales", ["product_type"]), ("idx_sales_client_id", "sales", ["client_id"]),
        ("idx_leads_client_id", "leads", ["client_id"]), ("idx_leads_created_at", "leads", ["created_at"]),
        ("idx_leads_source", "leads", ["source"]), ("idx_leads_status", "leads", ["status"]),
        ("idx_leads_source_created", "leads", ["source", "created_at"]),
        ("idx_spend_source", "marketing_spend", ["source"]), ("idx_spend_date", "marketing_spend", ["date"]),
        ("idx_funnel_events_client", "funnel_events", ["client_id"]),
        ("idx_funnel_events_event_type", "funnel_events", ["event_type"]),
        ("idx_funnel_events_date", "funnel_events", ["event_date"]),
    ):
        op.create_index(name, table, columns)
    op.create_index("idx_leads_external_source", "leads", ["external_id", "source"], unique=True)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql = bind.dialect.name == "postgresql"
    if postgresql:
        _create_base_tables_postgresql()
    else:
        # A database created only by migrations (tests, a fresh install) gets the
        # original tables from their single definition in local_db first.
        from techset_leadgen.database.local_db import create_base_tables

        cursor = bind.connection.cursor()
        create_base_tables(cursor)
        cursor.close()

    op.create_table(
        "organization",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "users",
        _ids("id"),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("last_login_at", sa.DateTime()),
        _user_ref("invited_by_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('super_admin', 'sales_manager', 'lead_researcher', 'bdr', 'account_executive', "
            "'marketing', 'read_only')", name="ck_users_role"),
    )
    op.create_table(
        "user_sessions",
        _ids("id"),
        _user_ref("user_id", "CASCADE"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("client_host", sa.String(128)),
        sa.Column("client_app", sa.String(128)),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "user_tokens",
        _ids("id"),
        _user_ref("user_id", "CASCADE"),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("purpose IN ('invite', 'password_reset')", name="ck_user_tokens_purpose"),
    )
    op.create_index("ix_user_tokens_user_id", "user_tokens", ["user_id"])
    op.create_table(
        "auth_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("client_host", sa.String(128)),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_auth_attempts_email_created", "auth_attempts", ["email", "created_at"])
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _user_ref("actor_user_id"),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32)),
        sa.Column("entity_id", sa.String(120)),
        sa.Column("changes", sa.JSON()),
        sa.Column("client_host", sa.String(128)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_created", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])

    def portable(column: str) -> str:
        return column.replace(" DATETIME", " TIMESTAMP") if postgresql else column

    for column in _CLIENT_COLUMNS:
        op.execute(f"ALTER TABLE clients ADD COLUMN {portable(column)}")
    for column in _LEAD_COLUMNS:
        op.execute(f"ALTER TABLE leads ADD COLUMN {portable(column)}")
    op.execute("CREATE UNIQUE INDEX uq_clients_primary_domain ON clients(primary_domain) "
               "WHERE primary_domain IS NOT NULL")
    op.execute("CREATE INDEX ix_clients_owner ON clients(owner_id)")
    op.execute("CREATE INDEX ix_leads_owner ON leads(owner_id)")
    op.execute("CREATE INDEX ix_leads_follow_up ON leads(next_follow_up_at)")

    op.create_table(
        "lead_status_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(16)),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text()),
        _user_ref("changed_by_id"),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lead_status_history_lead_id", "lead_status_history", ["lead_id"])
    op.create_table(
        "contacts",
        _ids("id"),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("full_name", sa.String(201), nullable=False),
        sa.Column("job_title", sa.String(150)),
        sa.Column("email", sa.String(254)),
        sa.Column("phone", sa.String(40)),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False),
        sa.Column("suppression_reason", sa.String(200)),
        sa.Column("notes", sa.Text()),
        _user_ref("created_by_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_contacts_client", "contacts", ["client_id"])
    op.execute("CREATE UNIQUE INDEX uq_contacts_email ON contacts(email) WHERE email IS NOT NULL")
    op.create_table(
        "activities",
        _ids("id"),
        sa.Column("activity_type", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id", ondelete="CASCADE")),
        sa.Column("contact_id", sa.String(36), sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id", ondelete="CASCADE")),
        _user_ref("created_by_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("activity_type IN ('note', 'call', 'email', 'meeting', 'other')",
                           name="ck_activities_activity_type"),
        sa.CheckConstraint("client_id IS NOT NULL OR lead_id IS NOT NULL", name="ck_activities_has_subject"),
    )
    op.create_index("ix_activities_lead", "activities", ["lead_id", "occurred_at"])
    op.create_index("ix_activities_client", "activities", ["client_id", "occurred_at"])
    op.create_table(
        "tasks",
        _ids("id"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id", ondelete="CASCADE")),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id", ondelete="CASCADE")),
        _user_ref("assigned_to_id"),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("due_at", sa.DateTime()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        _user_ref("created_by_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("status IN ('open', 'done', 'cancelled')", name="ck_tasks_status"),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name="ck_tasks_priority"),
    )
    op.create_index("ix_tasks_assignee_status", "tasks", ["assigned_to_id", "status"])
    op.create_index("ix_tasks_due", "tasks", ["due_at"])
    op.create_index("ix_tasks_lead", "tasks", ["lead_id"])


def downgrade() -> None:
    # The added client/lead columns stay (SQLite cannot drop them without rebuilding the
    # tables, which would cascade to sales); everything else is removed.
    for table in ("tasks", "activities", "contacts", "lead_status_history", "audit_logs", "auth_attempts",
                  "user_tokens", "user_sessions", "users", "organization"):
        op.drop_table(table)
