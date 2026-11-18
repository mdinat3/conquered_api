from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


ResultKind = Literal["win", "loss", "draw"]
DifficultyKind = Literal["easy", "medium", "hard"]
HeroKind = Literal["wizard", "elf", "mage", "warrior", "rogue", "barbarian"]


class ProfileStats(BaseModel):
    wins: int
    losses: int
    draws: int


class ProfileResponse(BaseModel):
    user_id: int
    email: str | None
    display_name: str
    friend_code: str
    is_guest: bool
    stats: ProfileStats


class AuthTokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    profile: ProfileResponse


class GuestCreateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    client_platform: str | None = Field(default=None, max_length=64)
    client_os: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=64)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=2, max_length=80)
    client_platform: str | None = Field(default=None, max_length=64)
    client_os: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    client_platform: str | None = Field(default=None, max_length=64)
    client_os: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=64)


class MatchCreateRequest(BaseModel):
    client_match_id: str = Field(min_length=6, max_length=64)
    difficulty: DifficultyKind
    result: ResultKind
    opponent: str = Field(default="computer", max_length=32)
    player_hero: HeroKind
    opponent_hero: HeroKind
    details: str | None = Field(default=None, max_length=1000)
    client_platform: str | None = Field(default=None, max_length=64)
    client_os: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=64)


class MatchRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_match_id: str
    difficulty: DifficultyKind
    result: ResultKind
    opponent: str
    player_hero: str | None
    opponent_hero: str | None
    details: str | None
    played_at: datetime


class MatchListResponse(BaseModel):
    items: list[MatchRecord]


class DeckCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    card_ids: list[str] = Field(default_factory=list, max_length=30)
    client_platform: str | None = Field(default=None, max_length=64)
    client_os: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=64)


class DeckUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    card_ids: list[str] = Field(default_factory=list, max_length=30)
    client_platform: str | None = Field(default=None, max_length=64)
    client_os: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=64)


class DeckRecord(BaseModel):
    id: int
    name: str
    card_ids: list[str]
    updated_at: datetime


class DeckListResponse(BaseModel):
    items: list[DeckRecord]


class UsageCountItem(BaseModel):
    key: str
    count: int


class UsageStatsResponse(BaseModel):
    days: int
    total_events: int
    os: list[UsageCountItem]
    browsers: list[UsageCountItem]
    platforms: list[UsageCountItem]


PresenceKind = Literal["offline", "online", "lobby", "match"]
FriendDirection = Literal["friend", "incoming", "outgoing"]


class FriendCodeRequest(BaseModel):
    friend_code: str = Field(min_length=4, max_length=8)


class FriendRow(BaseModel):
    user_id: int
    display_name: str
    friend_code: str
    presence: PresenceKind
    request_id: int = 0
    direction: FriendDirection


class BlockRow(BaseModel):
    user_id: int
    display_name: str


class FriendOverview(BaseModel):
    friend_code: str
    friends: list[FriendRow]
    incoming: list[FriendRow]
    outgoing: list[FriendRow]
    blocks: list[BlockRow]


class InviteCreateRequest(BaseModel):
    user_id: int


class InviteRecord(BaseModel):
    invite_id: int
    table_id: int
    from_user_id: int
    from_display_name: str
    to_user_id: int
    expires_unix: int
    status: str


class TableSeatRecord(BaseModel):
    seat: int
    user_id: int
    display_name: str
    hero_id: str
    ready: bool
    team: int


class TableRecord(BaseModel):
    table_id: int
    mode: str
    status: str
    your_seat: int
    seats: list[TableSeatRecord]


class ReadyRequest(BaseModel):
    hero_id: HeroKind
    card_ids: list[str] = Field(min_length=30, max_length=30)


class ActionRequest(BaseModel):
    client_action_id: str = Field(min_length=4, max_length=64)
    action_type: str
    card_instance_ids: list[int] = Field(default_factory=list)
    card_instance_id: int = 0
    lane_index: int = -1
    target_player_index: int = -1
    target_unit_instance_id: int = 0
    second_target_unit_instance_id: int = 0
    ally_unit_instance_id: int = 0
