from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import account_user
from app.models import FriendLink, User, UserBlock
from app.presence import presence
from app.schemas import BlockRow, FriendCodeRequest, FriendOverview, FriendRow
from app.service import load_active_user_by_id


router = APIRouter()


def blocked_either(db: Session, left_id: int, right_id: int) -> bool:
    row = db.scalar(
        select(UserBlock.id).where(
            or_(
                (UserBlock.blocker_id == left_id) & (UserBlock.blocked_id == right_id),
                (UserBlock.blocker_id == right_id) & (UserBlock.blocked_id == left_id),
            )
        )
    )
    return row is not None


def find_by_code(db: Session, code: str) -> User | None:
    cleaned = (code or "").strip().upper()
    if not cleaned:
        return None
    return db.scalar(select(User).where(User.friend_code == cleaned, User.is_retired.is_(False), User.is_guest.is_(False)))


def pending_between(db: Session, left_id: int, right_id: int) -> FriendLink | None:
    return db.scalar(
        select(FriendLink).where(
            FriendLink.status == "pending",
            or_(
                (FriendLink.requester_id == left_id) & (FriendLink.addressee_id == right_id),
                (FriendLink.requester_id == right_id) & (FriendLink.addressee_id == left_id),
            ),
        )
    )


def accepted_between(db: Session, left_id: int, right_id: int) -> FriendLink | None:
    return db.scalar(
        select(FriendLink).where(
            FriendLink.status == "accepted",
            or_(
                (FriendLink.requester_id == left_id) & (FriendLink.addressee_id == right_id),
                (FriendLink.requester_id == right_id) & (FriendLink.addressee_id == left_id),
            ),
        )
    )


def friend_user_ids(db: Session, user_id: int) -> list[int]:
    rows = db.scalars(
        select(FriendLink).where(
            FriendLink.status == "accepted",
            or_(FriendLink.requester_id == user_id, FriendLink.addressee_id == user_id),
        )
    ).all()
    found: list[int] = []
    for row in rows:
        found.append(row.addressee_id if row.requester_id == user_id else row.requester_id)
    return found


def publish_friends_changed(db: Session, user_id: int) -> None:
    presence.publish(user_id, {"type": "friends_changed"})
    for other_id in friend_user_ids(db, user_id):
        presence.publish(other_id, {"type": "friends_changed"})


def _row(person: User, direction: str, request_id: int | None, statuses: dict[int, str]) -> FriendRow:
    if not presence.is_online(person.id):
        state = "offline"
    else:
        state = statuses.get(person.id, "online")
    return FriendRow(
        user_id=person.id,
        display_name=person.display_name,
        friend_code=person.friend_code or "",
        presence=state,  # type: ignore[arg-type]
        request_id=request_id or 0,
        direction=direction,  # type: ignore[arg-type]
    )


@router.get("/friends", response_model=FriendOverview)
def overview(user: User = Depends(account_user), db: Session = Depends(get_db)) -> FriendOverview:
    from app.tables import status_for_users

    links = db.scalars(
        select(FriendLink).where(
            FriendLink.status.in_(("pending", "accepted")),
            or_(FriendLink.requester_id == user.id, FriendLink.addressee_id == user.id),
        )
    ).all()
    blocks = db.scalars(select(UserBlock).where(UserBlock.blocker_id == user.id)).all()
    ids: set[int] = set()
    for link in links:
        ids.add(link.requester_id)
        ids.add(link.addressee_id)
    ids.discard(user.id)
    for block in blocks:
        ids.add(block.blocked_id)

    people: dict[int, User] = {}
    if len(ids) > 0:
        for person in db.scalars(select(User).where(User.id.in_(list(ids)))).all():
            people[person.id] = person

    statuses = status_for_users(db, list(ids))
    friends: list[FriendRow] = []
    incoming: list[FriendRow] = []
    outgoing: list[FriendRow] = []
    for link in links:
        other_id = link.addressee_id if link.requester_id == user.id else link.requester_id
        person = people.get(other_id)
        if person is None:
            continue
        if link.status == "accepted":
            friends.append(_row(person, "friend", None, statuses))
        elif link.requester_id == user.id:
            outgoing.append(_row(person, "outgoing", link.id, statuses))
        else:
            incoming.append(_row(person, "incoming", link.id, statuses))

    blocked_rows = []
    for block in blocks:
        person = people.get(block.blocked_id)
        if person is None:
            continue
        blocked_rows.append(BlockRow(user_id=person.id, display_name=person.display_name))

    return FriendOverview(
        friend_code=user.friend_code or "",
        friends=friends,
        incoming=incoming,
        outgoing=outgoing,
        blocks=blocked_rows,
    )


@router.post("/friends/requests", response_model=FriendOverview)
def send_request(
    payload: FriendCodeRequest,
    user: User = Depends(account_user),
    db: Session = Depends(get_db),
) -> FriendOverview:
    other = find_by_code(db, payload.friend_code)
    if other is None or other.id == user.id or blocked_either(db, user.id, other.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found.")

    if accepted_between(db, user.id, other.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are already friends.")

    existing = pending_between(db, user.id, other.id)
    if existing is not None:
        if existing.addressee_id == user.id:
            existing.status = "accepted"
            db.commit()
            publish_friends_changed(db, user.id)
            presence.publish(other.id, {"type": "friend_request", "request_id": existing.id, "status": "accepted"})
            return overview(user, db)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That request is already pending.")

    link = FriendLink(requester_id=user.id, addressee_id=other.id, status="pending")
    db.add(link)
    db.commit()
    db.refresh(link)
    presence.publish(
        other.id,
        {
            "type": "friend_request",
            "request_id": link.id,
            "from_user_id": user.id,
            "from_display_name": user.display_name,
            "status": "pending",
        },
    )
    publish_friends_changed(db, user.id)
    return overview(user, db)


def _pending_for_user(db: Session, request_id: int, user: User) -> FriendLink:
    link = db.get(FriendLink, request_id)
    if link is None or link.status != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Friend request not found.")
    if user.id not in (link.requester_id, link.addressee_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Friend request not found.")
    return link


@router.post("/friends/requests/{request_id}/accept", response_model=FriendOverview)
def accept_request(request_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> FriendOverview:
    link = _pending_for_user(db, request_id, user)
    if link.addressee_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the invited player can accept.")
    if blocked_either(db, link.requester_id, link.addressee_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found.")
    link.status = "accepted"
    db.commit()
    publish_friends_changed(db, user.id)
    return overview(user, db)


@router.post("/friends/requests/{request_id}/decline", response_model=FriendOverview)
def decline_request(request_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> FriendOverview:
    link = _pending_for_user(db, request_id, user)
    if link.addressee_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the invited player can decline.")
    link.status = "declined"
    db.commit()
    presence.publish(link.requester_id, {"type": "friends_changed"})
    return overview(user, db)


@router.delete("/friends/requests/{request_id}", response_model=FriendOverview)
def cancel_request(request_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> FriendOverview:
    link = _pending_for_user(db, request_id, user)
    if link.requester_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the sender can cancel.")
    link.status = "cancelled"
    db.commit()
    presence.publish(link.addressee_id, {"type": "friends_changed"})
    return overview(user, db)


@router.delete("/friends/{other_id}", response_model=FriendOverview)
def remove_friend(other_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> FriendOverview:
    link = accepted_between(db, user.id, other_id)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Friend not found.")
    db.delete(link)
    db.commit()
    presence.publish(other_id, {"type": "friends_changed"})
    presence.publish(user.id, {"type": "friends_changed"})
    return overview(user, db)


@router.post("/blocks", response_model=FriendOverview)
def block_player(
    payload: FriendCodeRequest,
    user: User = Depends(account_user),
    db: Session = Depends(get_db),
) -> FriendOverview:
    other = find_by_code(db, payload.friend_code)
    if other is None or other.id == user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found.")

    already = db.scalar(select(UserBlock.id).where(UserBlock.blocker_id == user.id, UserBlock.blocked_id == other.id))
    if already is None:
        db.add(UserBlock(blocker_id=user.id, blocked_id=other.id))

    for link in db.scalars(
        select(FriendLink).where(
            or_(
                (FriendLink.requester_id == user.id) & (FriendLink.addressee_id == other.id),
                (FriendLink.requester_id == other.id) & (FriendLink.addressee_id == user.id),
            )
        )
    ).all():
        if link.status == "pending":
            link.status = "cancelled"
        elif link.status == "accepted":
            db.delete(link)

    from app.tables import close_pair_invites

    close_pair_invites(db, user.id, other.id, "cancelled")
    db.commit()
    presence.publish(user.id, {"type": "friends_changed"})
    presence.publish(other.id, {"type": "friends_changed"})
    return overview(user, db)


@router.delete("/blocks/{other_id}", response_model=FriendOverview)
def unblock_player(other_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> FriendOverview:
    row = db.scalar(select(UserBlock).where(UserBlock.blocker_id == user.id, UserBlock.blocked_id == other_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found.")
    db.delete(row)
    db.commit()
    return overview(user, db)


def load_user(db: Session, user_id: int) -> User | None:
    return load_active_user_by_id(db, user_id)
