"""Stage preferences and channel-aware durable delivery.

Revision ID: e42b7190
Revises: c7e2a901
"""

from alembic import op
import sqlalchemy as sa

revision = "e42b7190"
down_revision = "c7e2a901"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_preferences",
        sa.Column(
            "reminder_stages",
            sa.JSON(),
            nullable=False,
            server_default='["BEFORE_60", "BEFORE_30", "BEFORE_5", "AFTER_10", "END_10"]',
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column("in_app_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("tasks", sa.Column("reminder_stages", sa.JSON(), nullable=True))
    op.add_column("tasks", sa.Column("email_reminders_enabled", sa.Boolean(), nullable=True))
    op.add_column("reminders", sa.Column("stage_key", sa.String(30), nullable=True))
    op.add_column(
        "reminders", sa.Column("in_app_visible", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.create_index("uq_reminder_session_stage", "reminders", ["scheduled_task_id", "stage_key"], unique=True)
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.alter_column("subscription_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("channel", sa.String(10), nullable=False, server_default="push"))
        batch.add_column(sa.Column("idempotency_key", sa.String(64), nullable=True))
        batch.add_column(sa.Column("payload", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("retry_deadline", sa.DateTime(), nullable=True))
        batch.create_unique_constraint("uq_delivery_idempotency", ["idempotency_key"])
    op.create_index(
        "uq_email_occurrence",
        "notification_deliveries",
        ["reminder_id", "generation"],
        unique=True,
        sqlite_where=sa.text("channel = 'email'"),
        postgresql_where=sa.text("channel = 'email'"),
    )
    # Existing sessions retain their legacy reminders until explicitly replanned or preferences saved.


def downgrade():
    op.execute("DELETE FROM notification_deliveries WHERE channel = 'email'")
    op.drop_index("uq_email_occurrence", table_name="notification_deliveries")
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_constraint("uq_delivery_idempotency", type_="unique")
        for name in ["channel", "idempotency_key", "payload", "retry_deadline"]:
            batch.drop_column(name)
        batch.alter_column("subscription_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("uq_reminder_session_stage", table_name="reminders")
    # Native DROP COLUMN avoids SQLite batch recreation cascading into child tables (SQLite >= 3.35).
    for table, columns in [
        ("reminders", ["stage_key", "in_app_visible"]),
        ("tasks", ["reminder_stages", "email_reminders_enabled"]),
        ("user_preferences", ["reminder_stages", "in_app_notifications_enabled"]),
    ]:
        for column in columns:
            op.drop_column(table, column)
