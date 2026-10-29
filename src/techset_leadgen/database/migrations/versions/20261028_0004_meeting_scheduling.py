from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORGANIZATION_COLUMNS = (
    "meeting_buffer_mode VARCHAR(12) NOT NULL DEFAULT 'post' "
    "CHECK (meeting_buffer_mode IN ('none', 'post', 'around'))",
    "meeting_buffer_minutes INTEGER NOT NULL DEFAULT 120 "
    "CHECK (meeting_buffer_minutes BETWEEN 0 AND 480)",
    "meeting_day_start INTEGER NOT NULL DEFAULT 540 CHECK (meeting_day_start BETWEEN 0 AND 1440)",
    "meeting_day_end INTEGER NOT NULL DEFAULT 1080 CHECK (meeting_day_end BETWEEN 0 AND 1440)",
    "meeting_work_days VARCHAR(7) NOT NULL DEFAULT '12345'",
)
_REQUEST = sa.text("request_id IS NOT NULL")


def upgrade() -> None:
    for column in _ORGANIZATION_COLUMNS:
        op.execute(f"ALTER TABLE organization ADD COLUMN {column}")

    op.create_table(
        "meeting_attendees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("uq_meeting_attendees", "meeting_attendees", ["meeting_id", "user_id"], unique=True)
    op.create_index("ix_meeting_attendees_user", "meeting_attendees", ["user_id", "meeting_id"])
    op.execute("INSERT INTO meeting_attendees (meeting_id, user_id, created_at) "
               "SELECT id, attendee_id, created_at FROM meetings ORDER BY created_at, id")

    for name in ("ix_meetings_attendee_start", "ix_meetings_status_start", "ix_meetings_client_name",
                 "uq_meetings_request"):
        op.drop_index(name, table_name="meetings")
    with op.batch_alter_table("meetings") as batch:
        batch.drop_column("attendee_id")
        batch.alter_column("link", existing_type=sa.String(1000), nullable=True)
        batch.add_column(sa.Column("client_email", sa.String(254)))
    op.create_index("ix_meetings_status_start", "meetings", ["status", "starts_at"])
    op.create_index("ix_meetings_client_start", "meetings", ["client_id", "status", "starts_at"])
    op.create_index("ix_meetings_client_name", "meetings", ["client_name"])
    op.create_index("uq_meetings_request", "meetings", ["request_id"], unique=True,
                    sqlite_where=_REQUEST, postgresql_where=_REQUEST)


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade from revision 0004 is unsupported; restore the pre-upgrade database backup instead."
    )

