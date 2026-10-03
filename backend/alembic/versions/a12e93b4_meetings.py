"""User-owned contacts and organizer event metadata."""

from alembic import op
import sqlalchemy as sa

revision = "a12e93b4"
down_revision = "f81a2c90"
branch_labels = depends_on = None


def upgrade():
    op.add_column("calendar_events", sa.Column("meeting_metadata", sa.JSON(), nullable=True))
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "email"),
    )
    op.create_index("ix_contacts_user_id", "contacts", ["user_id"])


def downgrade():
    op.drop_table("contacts")
    op.drop_column("calendar_events", "meeting_metadata")
