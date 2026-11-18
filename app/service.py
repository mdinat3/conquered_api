import secrets
from collections.abc import Iterable
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import ClientEvent, Deck, MatchResult, User
from app.schemas import ProfileResponse, ProfileStats


def normalize_email(email: str) -> str:
    return email.strip().lower()


def build_guest_name() -> str:
    return f"Guest-{secrets.token_hex(3).upper()}"


def load_active_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.scalar(select(User).where(User.id == user_id, User.is_retired.is_(False)))


def load_active_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == normalize_email(email), User.is_retired.is_(False)))


def build_stats(db: Session, user_id: int) -> ProfileStats:
    rows = db.execute(
        select(MatchResult.result, func.count(MatchResult.id)).where(MatchResult.user_id == user_id).group_by(MatchResult.result)
    ).all()
    counts = {"win": 0, "loss": 0, "draw": 0}
    for result, count in rows:
        if result in counts:
            counts[result] = int(count)

    return ProfileStats(wins=counts["win"], losses=counts["loss"], draws=counts["draw"])


def build_profile(db: Session, user: User) -> ProfileResponse:
    return ProfileResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        friend_code=user.friend_code or "",
        is_guest=user.is_guest,
        stats=build_stats(db, user.id),
    )


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def assign_friend_code(db: Session, user: User) -> None:
    if user.friend_code:
        return

    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        taken = db.scalar(select(User.id).where(User.friend_code == code))
        if taken is None:
            user.friend_code = code
            return

    raise RuntimeError("Could not allocate a friend code.")


def ensure_friend_codes(db: Session) -> None:
    missing = db.scalars(select(User).where(User.friend_code.is_(None), User.is_retired.is_(False))).all()
    for user in missing:
        assign_friend_code(db, user)
    if len(missing) > 0:
        db.commit()


def merge_guest_into_account(db: Session, guest: User, account: User) -> None:
    if guest.id == account.id:
        return

    db.execute(update(MatchResult).where(MatchResult.user_id == guest.id).values(user_id=account.id))
    db.execute(update(Deck).where(Deck.user_id == guest.id).values(user_id=account.id))
    guest.is_retired = True
    guest.email = None
    guest.password_hash = None
    guest.display_name = f"retired-{guest.id}"


def resolve_client_ip(x_forwarded_for: str | None, remote_host: str | None) -> str | None:
    if x_forwarded_for:
        candidates: Iterable[str] = (part.strip() for part in x_forwarded_for.split(","))
        for candidate in candidates:
            if candidate:
                return candidate

    return remote_host


def parse_user_agent(user_agent: str | None) -> tuple[str, str]:
    if not user_agent:
        return "Unknown", "Unknown"

    ua = user_agent.lower()
    if "windows" in ua:
        os_name = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua or "ios" in ua:
        os_name = "iOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Unknown"

    if "edg/" in ua or "edge/" in ua:
        browser = "Edge"
    elif "opr/" in ua or "opera" in ua:
        browser = "Opera"
    elif "firefox/" in ua:
        browser = "Firefox"
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "Safari"
    elif "chrome/" in ua or "crios/" in ua:
        browser = "Chrome"
    elif "unityplayer/" in ua or "unitywebrequest" in ua:
        browser = "UnityRuntime"
    else:
        browser = "Unknown"

    return os_name, browser


def track_client_event(
    db: Session,
    user_id: int | None,
    event_type: str,
    endpoint: str,
    ip_address: str | None,
    user_agent: str | None,
    client_platform: str | None,
    client_os: str | None,
    app_version: str | None,
) -> None:
    parsed_os, parsed_browser = parse_user_agent(user_agent)
    event = ClientEvent(
        user_id=user_id,
        event_type=event_type,
        endpoint=endpoint,
        ip_address=ip_address,
        user_agent=user_agent,
        os_name=parsed_os,
        browser_name=parsed_browser,
        client_platform=(client_platform or "").strip() or None,
        client_os=(client_os or "").strip() or None,
        app_version=(app_version or "").strip() or None,
    )
    db.add(event)
    db.commit()
