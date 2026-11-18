import asyncio

from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import ClientEvent, Deck, DeckCard, MatchResult, User
from app.schemas import (
    AuthTokenResponse,
    DeckCreateRequest,
    DeckListResponse,
    DeckRecord,
    DeckUpdateRequest,
    GuestCreateRequest,
    LoginRequest,
    MatchCreateRequest,
    MatchListResponse,
    MatchRecord,
    ProfileResponse,
    SignupRequest,
    UsageCountItem,
    UsageStatsResponse,
)
from app.security import create_access_token, decode_access_token, hash_password, verify_password
from app.service import (
    assign_friend_code,
    build_guest_name,
    build_profile,
    ensure_friend_codes,
    load_active_user_by_email,
    load_active_user_by_id,
    merge_guest_into_account,
    normalize_email,
    resolve_client_ip,
    track_client_event,
)
from app.realtime import router as realtime_router
from app.social import router as social_router
from app.tables import router as tables_router
from app.tables import watch_tables
from app.presence import presence


app = FastAPI(title=settings.api_title)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AllowedDeckCardIds = {
    "bulwark",
    "champion",
    "insight",
    "mend",
    "raider",
    "scout",
    "sentinel",
    "spark",
    "vanguard",
    "warden",
}
for number in range(1, 101):
    AllowedDeckCardIds.add(f"u{number:03d}")
for number in range(1, 51):
    AllowedDeckCardIds.add(f"s{number:03d}")
for number in range(1, 51):
    AllowedDeckCardIds.add(f"d{number:03d}")

DeckSizeLimit = 30
MaxCopiesPerCard = 2


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_friend_codes(db)
    finally:
        db.close()


@app.on_event("startup")
async def start_realtime() -> None:
    presence.bind_loop(asyncio.get_running_loop())

    async def clock() -> None:
        while True:
            await asyncio.sleep(1)
            try:
                watch_tables()
            except Exception:
                continue

    asyncio.create_task(clock())


app.include_router(social_router)
app.include_router(tables_router)
app.include_router(realtime_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    messages: list[str] = []
    for issue in exc.errors():
        loc = issue.get("loc", [])
        field = ".".join(str(part) for part in loc if part != "body")
        message = issue.get("msg", "Invalid value.")
        if field:
            messages.append(f"{field}: {message}")
        else:
            messages.append(message)

    if len(messages) == 0:
        messages = ["Invalid request payload."]

    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": "; ".join(messages)})


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None

    if not authorization.lower().startswith("bearer "):
        return None

    token = authorization[7:].strip()
    return token or None


def _resolve_optional_user(db: Session, authorization: Optional[str]) -> Optional[User]:
    token = _extract_bearer_token(authorization)
    if token is None:
        return None

    try:
        user_id = decode_access_token(token)
    except (jwt.PyJWTError, ValueError) as ex:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from ex

    user = load_active_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found.")

    return user


def require_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    user = _resolve_optional_user(db, authorization)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")

    return user


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for")
    remote = request.client.host if request.client is not None else None
    ip_address = resolve_client_ip(forwarded, remote)
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent


def _track(
    db: Session,
    user_id: int | None,
    request: Request,
    event_type: str,
    endpoint: str,
    client_platform: str | None,
    client_os: str | None,
    app_version: str | None,
) -> None:
    ip_address, user_agent = _request_meta(request)
    track_client_event(
        db,
        user_id=user_id,
        event_type=event_type,
        endpoint=endpoint,
        ip_address=ip_address,
        user_agent=user_agent,
        client_platform=client_platform,
        client_os=client_os,
        app_version=app_version,
    )


def _validate_deck_cards(card_ids: list[str]) -> list[str]:
    cards = list(card_ids or [])
    if len(cards) > DeckSizeLimit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Deck cannot have more than {DeckSizeLimit} cards.")

    counts: dict[str, int] = {}
    cleaned: list[str] = []
    for card_id in cards:
        card_text = (card_id or "").strip()
        if not card_text:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Card id cannot be empty.")

        card_key = card_text.lower()
        if card_key not in AllowedDeckCardIds:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown card id '{card_id}'.")

        previous = counts.get(card_key, 0)
        next_count = previous + 1
        if next_count > MaxCopiesPerCard:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Deck cannot include more than {MaxCopiesPerCard} copies of '{card_key}'.",
            )
        counts[card_key] = next_count
        cleaned.append(card_text)

    return cleaned


def _deck_record(deck: Deck) -> DeckRecord:
    ordered = sorted(deck.cards, key=lambda card: card.slot)
    return DeckRecord(
        id=deck.id,
        name=deck.name,
        card_ids=[card.card_id for card in ordered],
        updated_at=deck.updated_at,
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/auth/guest", response_model=AuthTokenResponse)
def create_guest(payload: GuestCreateRequest, request: Request, db: Session = Depends(get_db)) -> AuthTokenResponse:
    display_name = (payload.display_name or "").strip() or build_guest_name()
    guest = User(display_name=display_name, is_guest=True, is_retired=False)
    assign_friend_code(db, guest)
    db.add(guest)
    db.commit()
    db.refresh(guest)
    _track(
        db,
        user_id=guest.id,
        request=request,
        event_type="guest_created",
        endpoint="/auth/guest",
        client_platform=payload.client_platform,
        client_os=payload.client_os,
        app_version=payload.app_version,
    )

    return AuthTokenResponse(token=create_access_token(guest.id), profile=build_profile(db, guest))


@app.post("/auth/signup", response_model=AuthTokenResponse)
def signup(
    payload: SignupRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    email = normalize_email(payload.email)
    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name is required.")

    existing = load_active_user_by_email(db, email)
    session_user = _resolve_optional_user(db, authorization)
    if session_user is not None and not session_user.is_guest:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Current session already has an account.")

    if session_user is not None and session_user.is_guest:
        if existing is not None and existing.id != session_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use.")

        account = session_user
        account.email = email
        account.password_hash = hash_password(payload.password)
        account.display_name = display_name
        account.is_guest = False
        assign_friend_code(db, account)
        db.commit()
        db.refresh(account)
    else:
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use.")

        account = User(
            email=email,
            password_hash=hash_password(payload.password),
            display_name=display_name,
            is_guest=False,
            is_retired=False,
        )
        assign_friend_code(db, account)
        db.add(account)
        db.commit()
        db.refresh(account)

    _track(
        db,
        user_id=account.id,
        request=request,
        event_type="signup",
        endpoint="/auth/signup",
        client_platform=payload.client_platform,
        client_os=payload.client_os,
        app_version=payload.app_version,
    )

    return AuthTokenResponse(token=create_access_token(account.id), profile=build_profile(db, account))


@app.post("/auth/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    email = normalize_email(payload.email)
    account = load_active_user_by_email(db, email)
    if account is None or not account.password_hash or not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    session_user = _resolve_optional_user(db, authorization)
    if session_user is not None and session_user.is_guest and session_user.id != account.id:
        merge_guest_into_account(db, session_user, account)
        db.commit()
        db.refresh(account)

    _track(
        db,
        user_id=account.id,
        request=request,
        event_type="login",
        endpoint="/auth/login",
        client_platform=payload.client_platform,
        client_os=payload.client_os,
        app_version=payload.app_version,
    )

    return AuthTokenResponse(token=create_access_token(account.id), profile=build_profile(db, account))


@app.get("/me", response_model=ProfileResponse)
def me(request: Request, current_user: User = Depends(require_user), db: Session = Depends(get_db)) -> ProfileResponse:
    _track(
        db,
        user_id=current_user.id,
        request=request,
        event_type="profile_read",
        endpoint="/me",
        client_platform=None,
        client_os=None,
        app_version=None,
    )
    return build_profile(db, current_user)


@app.post("/matches", response_model=MatchRecord)
def create_match(
    payload: MatchCreateRequest,
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> MatchRecord:
    if payload.opponent != "computer":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only computer matches are supported.")
    if payload.player_hero == payload.opponent_hero:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The player and the computer must use different heroes.")

    existing = db.scalar(select(MatchResult).where(MatchResult.client_match_id == payload.client_match_id))
    if existing is not None:
        if existing.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="client_match_id already belongs to another user.")

        _track(
            db,
            user_id=current_user.id,
            request=request,
            event_type="match_duplicate",
            endpoint="/matches",
            client_platform=payload.client_platform,
            client_os=payload.client_os,
            app_version=payload.app_version,
        )
        return MatchRecord.model_validate(existing)

    match = MatchResult(
        user_id=current_user.id,
        client_match_id=payload.client_match_id,
        opponent=payload.opponent,
        difficulty=payload.difficulty,
        result=payload.result,
        player_hero=payload.player_hero,
        opponent_hero=payload.opponent_hero,
        details=payload.details,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    _track(
        db,
        user_id=current_user.id,
        request=request,
        event_type="match_saved",
        endpoint="/matches",
        client_platform=payload.client_platform,
        client_os=payload.client_os,
        app_version=payload.app_version,
    )
    return MatchRecord.model_validate(match)


@app.get("/matches", response_model=MatchListResponse)
def list_matches(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> MatchListResponse:
    _track(
        db,
        user_id=current_user.id,
        request=request,
        event_type="matches_list",
        endpoint="/matches",
        client_platform=None,
        client_os=None,
        app_version=None,
    )
    rows = db.scalars(
        select(MatchResult).where(MatchResult.user_id == current_user.id).order_by(MatchResult.played_at.desc()).limit(limit)
    ).all()
    return MatchListResponse(items=[MatchRecord.model_validate(row) for row in rows])


@app.get("/decks", response_model=DeckListResponse)
def list_decks(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeckListResponse:
    _track(
        db,
        user_id=current_user.id,
        request=request,
        event_type="decks_list",
        endpoint="/decks",
        client_platform=None,
        client_os=None,
        app_version=None,
    )
    rows = db.scalars(
        select(Deck).where(Deck.user_id == current_user.id).order_by(Deck.updated_at.desc(), Deck.id.desc())
    ).all()
    return DeckListResponse(items=[_deck_record(row) for row in rows])


@app.post("/decks", response_model=DeckRecord)
def create_deck(
    payload: DeckCreateRequest,
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeckRecord:
    card_ids = _validate_deck_cards(payload.card_ids)
    deck_name = payload.name.strip()
    if deck_name == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deck name is required.")

    deck = Deck(user_id=current_user.id, name=deck_name)
    db.add(deck)
    db.flush()
    for slot, card_id in enumerate(card_ids):
        db.add(DeckCard(deck_id=deck.id, slot=slot, card_id=card_id))
    db.commit()
    db.refresh(deck)
    _track(
        db,
        user_id=current_user.id,
        request=request,
        event_type="deck_created",
        endpoint="/decks",
        client_platform=payload.client_platform,
        client_os=payload.client_os,
        app_version=payload.app_version,
    )
    return _deck_record(deck)


@app.put("/decks/{deck_id}", response_model=DeckRecord)
def update_deck(
    deck_id: int,
    payload: DeckUpdateRequest,
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeckRecord:
    card_ids = _validate_deck_cards(payload.card_ids)
    deck_name = payload.name.strip()
    if deck_name == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deck name is required.")

    deck = db.scalar(select(Deck).where(Deck.id == deck_id, Deck.user_id == current_user.id))
    if deck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deck not found.")

    deck.name = deck_name
    existing_cards = list(deck.cards)
    for item in existing_cards:
        db.delete(item)
    db.flush()
    for slot, card_id in enumerate(card_ids):
        db.add(DeckCard(deck_id=deck.id, slot=slot, card_id=card_id))
    db.commit()
    db.refresh(deck)
    _track(
        db,
        user_id=current_user.id,
        request=request,
        event_type="deck_updated",
        endpoint="/decks/{deck_id}",
        client_platform=payload.client_platform,
        client_os=payload.client_os,
        app_version=payload.app_version,
    )
    return _deck_record(deck)


@app.delete("/decks/{deck_id}")
def delete_deck(
    deck_id: int,
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    deck = db.scalar(select(Deck).where(Deck.id == deck_id, Deck.user_id == current_user.id))
    if deck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deck not found.")

    db.delete(deck)
    db.commit()
    _track(
        db,
        user_id=current_user.id,
        request=request,
        event_type="deck_deleted",
        endpoint="/decks/{deck_id}",
        client_platform=None,
        client_os=None,
        app_version=None,
    )
    return {"ok": True}


@app.get("/stats/usage", response_model=UsageStatsResponse)
def usage_stats(days: int = Query(default=30, ge=1, le=3650), db: Session = Depends(get_db)) -> UsageStatsResponse:
    cutoff = datetime.utcnow() - timedelta(days=days)
    total_events = db.scalar(select(func.count(ClientEvent.id)).where(ClientEvent.created_at >= cutoff)) or 0

    os_rows = db.execute(
        select(func.coalesce(ClientEvent.os_name, "Unknown"), func.count(ClientEvent.id))
        .where(ClientEvent.created_at >= cutoff)
        .group_by(ClientEvent.os_name)
        .order_by(func.count(ClientEvent.id).desc())
        .limit(20)
    ).all()
    browser_rows = db.execute(
        select(func.coalesce(ClientEvent.browser_name, "Unknown"), func.count(ClientEvent.id))
        .where(ClientEvent.created_at >= cutoff)
        .group_by(ClientEvent.browser_name)
        .order_by(func.count(ClientEvent.id).desc())
        .limit(20)
    ).all()
    platform_rows = db.execute(
        select(func.coalesce(ClientEvent.client_platform, "Unknown"), func.count(ClientEvent.id))
        .where(ClientEvent.created_at >= cutoff)
        .group_by(ClientEvent.client_platform)
        .order_by(func.count(ClientEvent.id).desc())
        .limit(20)
    ).all()

    return UsageStatsResponse(
        days=days,
        total_events=int(total_events),
        os=[UsageCountItem(key=str(name), count=int(count)) for name, count in os_rows],
        browsers=[UsageCountItem(key=str(name), count=int(count)) for name, count in browser_rows],
        platforms=[UsageCountItem(key=str(name), count=int(count)) for name, count in platform_rows],
    )
