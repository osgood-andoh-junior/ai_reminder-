"""Extend reminders and add Web Push outbox.

Revision ID: c7e2a901
Revises: bd3cf0657410
"""

from alembic import op
import sqlalchemy as sa

revision = "c7e2a901"
down_revision = "bd3cf0657410"
branch_labels = None
depends_on = None


def upgrade():
    for name in [
        "browser_notifications_enabled",
        "email_notifications_enabled",
        "deadline_reminders_enabled",
    ]:
        op.add_column(
            "user_preferences", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
        )
    for column in [
        sa.Column("title", sa.String(200), nullable=False, server_default="Reminder"),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(30), nullable=False, server_default="CUSTOM"),
    ]:
        op.add_column("reminders", column)
    op.create_index("ix_reminders_snoozed_until", "reminders", ["snoozed_until"])
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(128), nullable=False),
        sa.Column("auth", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "reminder_id", sa.Integer(), sa.ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("push_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("reminder_id", "generation", "subscription_id"),
    )
    for name in ["user_id", "reminder_id", "status", "next_attempt_at"]:
        op.create_index("ix_notification_deliveries_" + name, "notification_deliveries", [name])


def downgrade():
    op.drop_table("notification_deliveries")
    op.drop_table("push_subscriptions")
    op.drop_index("ix_reminders_snoozed_until", table_name="reminders")
    with op.batch_alter_table("reminders") as batch:
        for name in ["title", "read_at", "dismissed_at", "snoozed_until", "generation", "kind"]:
            batch.drop_column(name)
    with op.batch_alter_table("user_preferences") as batch:
        for name in [
            "browser_notifications_enabled",
            "email_notifications_enabled",
            "deadline_reminders_enabled",
        ]:
            batch.drop_column(name)
