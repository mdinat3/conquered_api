"""friends, blocks, and live tables

Revision ID: 0005_friends_and_tables
Revises: 0004_add_decks
Create Date: 2026-11-12 20:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_friends_and_tables"
down_revision = "0004_add_decks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("friend_code", sa.String(length=8), nullable=True))
    op.create_index("ix_users_friend_code", "users", ["friend_code"], unique=True)

    op.create_table(
        "friend_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("requester_id", sa.BigInteger(), nullable=False),
        sa.Column("addressee_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["addressee_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_friend_links_requester_id", "friend_links", ["requester_id"], unique=False)
    op.create_index("ix_friend_links_addressee_id", "friend_links", ["addressee_id"], unique=False)
    op.create_index("ix_friend_links_addressee_status", "friend_links", ["addressee_id", "status"], unique=False)
    op.create_index("ix_friend_links_requester_status", "friend_links", ["requester_id", "status"], unique=False)

    op.create_table(
        "user_blocks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("blocker_id", sa.BigInteger(), nullable=False),
        sa.Column("blocked_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_pair"),
    )
    op.create_index("ix_user_blocks_blocker_id", "user_blocks", ["blocker_id"], unique=False)
    op.create_index("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"], unique=False)

    op.create_table(
        "game_tables",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("action_seq", sa.Integer(), nullable=False),
        sa.Column("last_active_seat", sa.Integer(), nullable=False),
        sa.Column("turn_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_saved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "table_seats",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("table_id", sa.BigInteger(), nullable=False),
        sa.Column("seat_index", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("team", sa.Integer(), nullable=False),
        sa.Column("hero_id", sa.String(length=32), nullable=False),
        sa.Column("deck_json", sa.Text(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["table_id"], ["game_tables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_id", "seat_index", name="uq_table_seats_index"),
        sa.UniqueConstraint("table_id", "user_id", name="uq_table_seats_user"),
    )
    op.create_index("ix_table_seats_table_id", "table_seats", ["table_id"], unique=False)
    op.create_index("ix_table_seats_user_id", "table_seats", ["user_id"], unique=False)

    op.create_table(
        "table_invites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("table_id", sa.BigInteger(), nullable=False),
        sa.Column("from_user_id", sa.BigInteger(), nullable=False),
        sa.Column("to_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["table_id"], ["game_tables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_table_invites_table_id", "table_invites", ["table_id"], unique=False)
    op.create_index("ix_table_invites_to_user_id", "table_invites", ["to_user_id"], unique=False)
    op.create_index("ix_table_invites_to_status", "table_invites", ["to_user_id", "status"], unique=False)

    op.create_table(
        "table_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("table_id", sa.BigInteger(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("seat_index", sa.Integer(), nullable=False),
        sa.Column("client_action_id", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["table_id"], ["game_tables.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_id", "seq", name="uq_table_actions_seq"),
    )
    op.create_index("ix_table_actions_table_id", "table_actions", ["table_id"], unique=False)


def downgrade() -> None:
    op.drop_table("table_actions")
    op.drop_table("table_invites")
    op.drop_table("table_seats")
    op.drop_table("game_tables")
    op.drop_table("user_blocks")
    op.drop_table("friend_links")
    op.drop_index("ix_users_friend_code", table_name="users")
    op.drop_column("users", "friend_code")
