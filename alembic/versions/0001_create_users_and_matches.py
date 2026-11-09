"""create users and matches tables

Revision ID: 0001_create_users_and_matches
Revises:
Create Date: 2026-11-07 08:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_create_users_and_matches"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_retired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_match_id", sa.String(length=64), nullable=False),
        sa.Column("opponent", sa.String(length=32), nullable=False, server_default="computer"),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("played_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_match_id", name="uq_matches_client_match_id"),
    )

    op.create_index("ix_matches_user_id", "matches", ["user_id"], unique=False)
    op.create_index("ix_matches_user_played_at", "matches", ["user_id", "played_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_matches_user_played_at", table_name="matches")
    op.drop_index("ix_matches_user_id", table_name="matches")
    op.drop_table("matches")
    op.drop_table("users")
