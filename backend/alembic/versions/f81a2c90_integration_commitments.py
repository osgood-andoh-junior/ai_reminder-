"""Gmail connections, deduplication and reviewed commitments.

Revision ID: f81a2c90
Revises: e42b7190
"""

from alembic import op
import sqlalchemy as sa

revision = "f81a2c90"
down_revision = "e42b7190"
branch_labels = depends_on = None


def owned():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.add_column(
        "oauth_states", sa.Column("provider", sa.String(30), nullable=False, server_default="google_calendar")
    )
    op.add_column("google_connections", sa.Column("last_error", sa.String(80), nullable=True))
    op.create_table(
        "integration_connections",
        *owned(),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("account", sa.String(254), nullable=False),
        sa.Column("encrypted_tokens", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(80), nullable=True),
        sa.UniqueConstraint("user_id", "provider"),
    )
    op.create_table(
        "external_messages",
        *owned(),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("account", sa.String(254), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("sender", sa.String(300), nullable=False),
        sa.Column("snippet", sa.String(500), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(80), nullable=True),
        sa.UniqueConstraint("user_id", "provider", "account", "external_id"),
    )
    op.create_table(
        "detected_commitments",
        *owned(),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("external_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("unresolved", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "event_id", sa.Integer(), sa.ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True
        ),
        sa.UniqueConstraint("message_id", "candidate_index"),
    )
    for table in ["integration_connections", "external_messages", "detected_commitments"]:
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
    op.create_index("ix_detected_commitments_message_id", "detected_commitments", ["message_id"])
    op.create_index("ix_detected_commitments_status", "detected_commitments", ["status"])


def downgrade():
    for table in ["detected_commitments", "external_messages", "integration_connections"]:
        op.drop_table(table)
    with op.batch_alter_table("google_connections") as batch:
        batch.drop_column("last_error")
    with op.batch_alter_table("oauth_states") as batch:
        batch.drop_column("provider")
