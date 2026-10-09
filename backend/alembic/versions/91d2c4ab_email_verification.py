"""Add verification and consent without altering existing account data."""

from alembic import op
import sqlalchemy as sa

revision = "91d2c4ab"
down_revision = "a12e93b4"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("email_reminders_opted_in_at", sa.DateTime(), nullable=True))
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("delivery_status", sa.String(20), nullable=False),
    )
    op.create_index("ix_email_verifications_user_id", "email_verifications", ["user_id"])


def downgrade():
    op.drop_table("email_verifications")
    op.drop_column("users", "email_reminders_opted_in_at")
    op.drop_column("users", "email_verified_at")

