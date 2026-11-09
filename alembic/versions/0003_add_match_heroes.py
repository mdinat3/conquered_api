"""store the heroes used in a match

Revision ID: 0003_add_match_heroes
Revises: 0002_add_client_events
Create Date: 2026-11-07 15:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_match_heroes"
down_revision = "0002_add_client_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("player_hero", sa.String(length=32), nullable=True))
    op.add_column("matches", sa.Column("opponent_hero", sa.String(length=32), nullable=True))
    op.create_index("ix_matches_player_hero", "matches", ["player_hero"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_matches_player_hero", table_name="matches")
    op.drop_column("matches", "opponent_hero")
    op.drop_column("matches", "player_hero")
