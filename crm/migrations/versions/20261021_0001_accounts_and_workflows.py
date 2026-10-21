"""Accounts, audit trail, contacts, tasks, and lead workflow on the application database.

Adds new tables and optional columns to the original ``clients`` and ``leads``
tables. Uses ``ALTER TABLE ... ADD COLUMN`` only: rebuilding ``clients`` would
drop it, and with foreign keys on, that cascades to its sales.

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


def upgrade() -> None:
    # A database created only by migrations (tests, a fresh install) gets the
    # original tables from their single definition in core.db first.
    from core.db import create_base_tables

    bind = op.get_bind()
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

    for column in _CLIENT_COLUMNS:
        op.execute(f"ALTER TABLE clients ADD COLUMN {column}")
    for column in _LEAD_COLUMNS:
        op.execute(f"ALTER TABLE leads ADD COLUMN {column}")
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
