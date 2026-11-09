"""add user decks

Revision ID: 0004_add_decks
Revises: 0003_add_match_heroes
Create Date: 2026-11-07 16:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_decks"
down_revision = "0003_add_match_heroes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decks_user_id", "decks", ["user_id"], unique=False)
    op.create_index("ix_decks_user_updated_at", "decks", ["user_id", "updated_at"], unique=False)

    op.create_table(
        "deck_cards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("deck_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["deck_id"], ["decks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deck_id", "slot", name="uq_deck_cards_deck_slot"),
    )
    op.create_index("ix_deck_cards_deck_id", "deck_cards", ["deck_id"], unique=False)
    op.create_index("ix_deck_cards_card_id", "deck_cards", ["card_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_deck_cards_card_id", table_name="deck_cards")
    op.drop_index("ix_deck_cards_deck_id", table_name="deck_cards")
    op.drop_table("deck_cards")
    op.drop_index("ix_decks_user_updated_at", table_name="decks")
    op.drop_index("ix_decks_user_id", table_name="decks")
    op.drop_table("decks")
