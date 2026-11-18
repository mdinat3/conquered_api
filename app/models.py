from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    friend_code: Mapped[str | None] = mapped_column(String(8), nullable=True, unique=True)
    is_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_retired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    matches: Mapped[list["MatchResult"]] = relationship(back_populates="user")
    client_events: Mapped[list["ClientEvent"]] = relationship(back_populates="user")
    decks: Mapped[list["Deck"]] = relationship(back_populates="user")


class MatchResult(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("client_match_id", name="uq_matches_client_match_id"),
        Index("ix_matches_user_played_at", "user_id", "played_at"),
        Index("ix_matches_player_hero", "player_hero"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_match_id: Mapped[str] = mapped_column(String(64), nullable=False)
    opponent: Mapped[str] = mapped_column(String(32), nullable=False, default="computer")
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    player_hero: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opponent_hero: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    played_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="matches")


class ClientEvent(Base):
    __tablename__ = "client_events"
    __table_args__ = (
        Index("ix_client_events_created_at", "created_at"),
        Index("ix_client_events_event_type", "event_type"),
        Index("ix_client_events_os_browser", "os_name", "browser_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    os_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    browser_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_os: Mapped[str | None] = mapped_column(String(128), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="client_events")


class Deck(Base):
    __tablename__ = "decks"
    __table_args__ = (
        Index("ix_decks_user_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="decks")
    cards: Mapped[list["DeckCard"]] = relationship(
        back_populates="deck",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DeckCard.slot",
    )


class DeckCard(Base):
    __tablename__ = "deck_cards"
    __table_args__ = (
        UniqueConstraint("deck_id", "slot", name="uq_deck_cards_deck_slot"),
        Index("ix_deck_cards_card_id", "card_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    card_id: Mapped[str] = mapped_column(String(32), nullable=False)

    deck: Mapped[Deck] = relationship(back_populates="cards")


class FriendLink(Base):
    __tablename__ = "friend_links"
    __table_args__ = (
        Index("ix_friend_links_addressee_status", "addressee_id", "status"),
        Index("ix_friend_links_requester_status", "requester_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    addressee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserBlock(Base):
    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_pair"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GameTable(Base):
    __tablename__ = "game_tables"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="duel")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="lobby")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_active_seat: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seats: Mapped[list["TableSeat"]] = relationship(back_populates="table", cascade="all, delete-orphan")
    invites: Mapped[list["TableInvite"]] = relationship(back_populates="table", cascade="all, delete-orphan")
    actions: Mapped[list["TableAction"]] = relationship(back_populates="table", cascade="all, delete-orphan")


class TableSeat(Base):
    __tablename__ = "table_seats"
    __table_args__ = (
        UniqueConstraint("table_id", "seat_index", name="uq_table_seats_index"),
        UniqueConstraint("table_id", "user_id", name="uq_table_seats_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("game_tables.id", ondelete="CASCADE"), nullable=False, index=True)
    seat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    team: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hero_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    deck_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    table: Mapped[GameTable] = relationship(back_populates="seats")
    user: Mapped[User] = relationship()


class TableInvite(Base):
    __tablename__ = "table_invites"
    __table_args__ = (
        Index("ix_table_invites_to_status", "to_user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("game_tables.id", ondelete="CASCADE"), nullable=False, index=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    table: Mapped[GameTable] = relationship(back_populates="invites")


class TableAction(Base):
    __tablename__ = "table_actions"
    __table_args__ = (
        UniqueConstraint("table_id", "seq", name="uq_table_actions_seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("game_tables.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    seat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    client_action_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    table: Mapped[GameTable] = relationship(back_populates="actions")
