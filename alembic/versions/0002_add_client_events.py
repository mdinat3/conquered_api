"""add client events telemetry table

Revision ID: 0002_add_client_events
Revises: 0001_create_users_and_matches
Create Date: 2026-11-07 08:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_add_client_events"
down_revision = "0001_create_users_and_matches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("os_name", sa.String(length=64), nullable=True),
        sa.Column("browser_name", sa.String(length=64), nullable=True),
        sa.Column("client_platform", sa.String(length=64), nullable=True),
        sa.Column("client_os", sa.String(length=128), nullable=True),
        sa.Column("app_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_client_events_user_id", "client_events", ["user_id"], unique=False)
    op.create_index("ix_client_events_created_at", "client_events", ["created_at"], unique=False)
    op.create_index("ix_client_events_event_type", "client_events", ["event_type"], unique=False)
    op.create_index("ix_client_events_os_browser", "client_events", ["os_name", "browser_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_client_events_os_browser", table_name="client_events")
    op.drop_index("ix_client_events_event_type", table_name="client_events")
    op.drop_index("ix_client_events_created_at", table_name="client_events")
    op.drop_index("ix_client_events_user_id", table_name="client_events")
    op.drop_table("client_events")
