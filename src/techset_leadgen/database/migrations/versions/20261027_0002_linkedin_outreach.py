"""LinkedIn outreach: prospects, daily assignment batches, assignments, outreach events, notifications.

Additive only. New tables are created; ``tasks`` gains optional columns so a
follow-up is a task linked to a prospect; ``organization`` gains the team's
business time zone. Existing rows are untouched apart from that time zone,
which starts as the first administrator's (Settings can change it).

Portable: the same DDL runs on SQLite and on the PostgreSQL team database
(exercised by ``tests/integration/test_postgresql.py``).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASK_COLUMNS = (
    "kind VARCHAR(12) NOT NULL DEFAULT 'task' CHECK (kind IN ('task', 'follow_up'))",
    "prospect_id VARCHAR(36) REFERENCES prospects(id)",
    "assignment_id VARCHAR(36) REFERENCES prospect_assignments(id) ON DELETE SET NULL",
    "outcome TEXT",
    "request_id VARCHAR(64)",
)


def _ids(name: str = "id") -> sa.Column:
    return sa.Column(name, sa.String(36), nullable=False, primary_key=True)


def _user_ref(name: str, ondelete: str | None = "SET NULL", nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.String(36), sa.ForeignKey("users.id", ondelete=ondelete), nullable=nullable)


def _version() -> sa.Column:
    return sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1"))


def upgrade() -> None:
    op.execute("ALTER TABLE organization ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'UTC'")
    op.execute(
        "UPDATE organization SET timezone = (SELECT users.timezone FROM users WHERE users.role = 'super_admin' "
        "AND users.timezone IS NOT NULL ORDER BY users.created_at LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM users WHERE users.role = 'super_admin' AND users.timezone IS NOT NULL)"
    )

    op.create_table(
        "prospects",
        _ids(),
        sa.Column("linkedin_key", sa.String(300), nullable=False),
        sa.Column("linkedin_url", sa.String(400), nullable=False),
        sa.Column("full_name", sa.String(200)),
        sa.Column("company", sa.String(200)),
        sa.Column("job_title", sa.String(200)),
        sa.Column("source", sa.String(120)),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'new'")),
        sa.Column("notes", sa.Text()),
        sa.Column("last_activity_at", sa.DateTime()),
        sa.Column("next_follow_up_at", sa.DateTime()),
        _user_ref("created_by_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        _version(),
        sa.UniqueConstraint("linkedin_key", name="uq_prospects_linkedin_key"),
        sa.CheckConstraint("status IN ('new', 'connection_sent', 'connected', 'messaged', 'replied', 'meeting', "
                           "'not_interested', 'invalid')", name="ck_prospects_status"),
    )
    op.create_index("ix_prospects_status", "prospects", ["status"])
    op.create_index("ix_prospects_created", "prospects", ["created_at"])

    op.create_table(
        "assignment_batches",
        _ids(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("notes", sa.Text()),
        _user_ref("created_by_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime()),
        sa.Column("cancelled_at", sa.DateTime()),
        _version(),
        sa.CheckConstraint("status IN ('draft', 'active', 'cancelled')", name="ck_assignment_batches_status"),
    )
    op.create_index("ix_assignment_batches_work_date", "assignment_batches", ["work_date"])

    op.create_table(
        "prospect_assignments",
        _ids(),
        sa.Column("prospect_id", sa.String(36), sa.ForeignKey("prospects.id"), nullable=False),
        _user_ref("assignee_id", ondelete=None, nullable=False),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("assignment_batches.id", ondelete="SET NULL")),
        _user_ref("assigned_by_id"),
        sa.Column("previous_assignment_id", sa.String(36),
                  sa.ForeignKey("prospect_assignments.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("due_on", sa.Date()),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("closed_at", sa.DateTime()),
        _user_ref("closed_by_id"),
        sa.Column("close_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _version(),
        sa.CheckConstraint("status IN ('planned', 'assigned', 'in_progress', 'completed', 'cancelled', "
                           "'reassigned')", name="ck_prospect_assignments_status"),
    )
    op.execute("CREATE UNIQUE INDEX uq_prospect_assignments_open ON prospect_assignments (prospect_id) "
               "WHERE status IN ('assigned', 'in_progress', 'planned')")
    op.create_index("ix_prospect_assignments_assignee", "prospect_assignments", ["assignee_id", "status"])
    op.create_index("ix_prospect_assignments_batch", "prospect_assignments", ["batch_id"])
    op.create_index("ix_prospect_assignments_prospect", "prospect_assignments", ["prospect_id", "assigned_at"])
    op.create_index("ix_prospect_assignments_closed", "prospect_assignments", ["closed_at"])

    op.create_table(
        "outreach_events",
        _ids(),
        sa.Column("prospect_id", sa.String(36), sa.ForeignKey("prospects.id"), nullable=False),
        sa.Column("assignment_id", sa.String(36), sa.ForeignKey("prospect_assignments.id", ondelete="SET NULL")),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        _user_ref("recorded_by_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.UniqueConstraint("request_id", name="uq_outreach_events_request_id"),
        sa.CheckConstraint("event_type IN ('connection_sent', 'connection_accepted', 'message_sent', "
                           "'reply_received', 'follow_up_requested', 'meeting_requested', 'not_interested', "
                           "'wrong_profile', 'note')", name="ck_outreach_events_event_type"),
    )
    op.create_index("ix_outreach_events_prospect", "outreach_events", ["prospect_id", "occurred_at"])
    op.create_index("ix_outreach_events_recorded_by", "outreach_events", ["recorded_by_id", "occurred_at"])
    op.create_index("ix_outreach_events_type", "outreach_events", ["event_type", "occurred_at"])
    op.create_index("ix_outreach_events_assignment", "outreach_events", ["assignment_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _user_ref("recipient_id", ondelete="CASCADE", nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("entity_type", sa.String(32)),
        sa.Column("entity_id", sa.String(120)),
        sa.Column("dedupe_key", sa.String(160)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime()),
        sa.UniqueConstraint("recipient_id", "dedupe_key", name="uq_notifications_dedupe"),
    )
    op.create_index("ix_notifications_recipient", "notifications", ["recipient_id", "read_at", "created_at"])

    for column in _TASK_COLUMNS:
        op.execute(f"ALTER TABLE tasks ADD COLUMN {column}")
    op.create_index("ix_tasks_prospect", "tasks", ["prospect_id"])
    op.create_index("ix_tasks_kind_status_due", "tasks", ["kind", "status", "due_at"])
    op.execute("CREATE UNIQUE INDEX uq_tasks_open_follow_up ON tasks (prospect_id) "
               "WHERE kind = 'follow_up' AND status = 'open'")
    op.execute("CREATE UNIQUE INDEX uq_tasks_request ON tasks (request_id) WHERE request_id IS NOT NULL")


def downgrade() -> None:
    # Leaving the added task foreign keys in place while dropping their parent
    # tables creates a corrupt revision-0001 schema.  Until a lossless table
    # rebuild is implemented, fail before changing either schema or revision;
    # operational rollback uses the verified pre-upgrade SQLite backup.
    raise RuntimeError(
        "Downgrade from revision 0002 is unsupported; restore the pre-upgrade database backup instead."
    )
