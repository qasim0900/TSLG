"""Scheduled client meetings.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("attendee_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("link", sa.String(1000), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(12), nullable=False, server_default=sa.text("'scheduled'")),
        sa.Column("cancellation_reason", sa.String(500)),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("status IN ('scheduled', 'completed', 'cancelled')", name="ck_meetings_status"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_meetings_time_range"),
    )
    op.create_index("ix_meetings_attendee_start", "meetings", ["attendee_id", "status", "starts_at"])
    op.create_index("ix_meetings_status_start", "meetings", ["status", "starts_at"])
    op.create_index("ix_meetings_client_name", "meetings", ["client_name"])
    op.create_index(
        "uq_meetings_request",
        "meetings",
        ["request_id"],
        unique=True,
        sqlite_where=sa.text("request_id IS NOT NULL"),
        postgresql_where=sa.text("request_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_meetings_request", table_name="meetings")
    op.drop_index("ix_meetings_client_name", table_name="meetings")
    op.drop_index("ix_meetings_status_start", table_name="meetings")
    op.drop_index("ix_meetings_attendee_start", table_name="meetings")
    op.drop_table("meetings")
