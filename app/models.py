from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
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
