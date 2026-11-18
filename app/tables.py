import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal, get_db
from app.deps import account_user
from app.match_client import MatchWorkerError, apply_action, create_match, replay_match, snapshot
from app.models import GameTable, MatchResult, TableAction, TableInvite, TableSeat, User
from app.presence import presence
from app.schemas import ActionRequest, InviteCreateRequest, InviteRecord, ReadyRequest, TableRecord, TableSeatRecord
from app.service import load_active_user_by_id


router = APIRouter()

INVITE_SECONDS = 45
OPENING_SECONDS = 45
TURN_SECONDS = 90
# Neither player owns the clock during simultaneous hand selection.
OPENING_CLOCK = -1
DISCONNECT_SECONDS = 60

_disconnect_since: dict[int, datetime] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def status_for_users(db: Session, user_ids: list[int]) -> dict[int, str]:
    if len(user_ids) == 0:
        return {}
    rows = db.execute(
        select(TableSeat.user_id, GameTable.status)
        .join(GameTable, GameTable.id == TableSeat.table_id)
        .where(TableSeat.user_id.in_(user_ids), GameTable.status.in_(("lobby", "playing")))
    ).all()
    found: dict[int, str] = {}
    for user_id, table_status in rows:
        if table_status == "playing":
            found[int(user_id)] = "match"
        elif int(user_id) not in found:
            found[int(user_id)] = "lobby"
    return found


def live_table_for(db: Session, user_id: int) -> GameTable | None:
    return db.scalar(
        select(GameTable)
        .join(TableSeat, TableSeat.table_id == GameTable.id)
        .where(TableSeat.user_id == user_id, GameTable.status.in_(("lobby", "playing")))
        .options(selectinload(GameTable.seats), selectinload(GameTable.invites))
    )


def _seat_for(table: GameTable, user_id: int) -> TableSeat | None:
    for seat in table.seats:
        if seat.user_id == user_id:
            return seat
    return None


def _names(db: Session, table: GameTable) -> dict[int, str]:
    ids = [seat.user_id for seat in table.seats]
    if len(ids) == 0:
        return {}
    people = db.scalars(select(User).where(User.id.in_(ids))).all()
    return {person.id: person.display_name for person in people}


def table_record(db: Session, table: GameTable, user_id: int) -> TableRecord:
    names = _names(db, table)
    seats = []
    your_seat = 0
    for seat in sorted(table.seats, key=lambda item: item.seat_index):
        if seat.user_id == user_id:
            your_seat = seat.seat_index
        seats.append(
            TableSeatRecord(
                seat=seat.seat_index,
                user_id=seat.user_id,
                display_name=names.get(seat.user_id, "Player"),
                hero_id=seat.hero_id or "",
                ready=bool(seat.ready),
                team=seat.team,
            )
        )
    return TableRecord(table_id=table.id, mode=table.mode, status=table.status, your_seat=your_seat, seats=seats)


def _publish_lobby(db: Session, table: GameTable) -> None:
    for seat in table.seats:
        record = table_record(db, table, seat.user_id)
        presence.publish(seat.user_id, {"type": "lobby", "table": record.model_dump(mode="json")})


def _publish_closed(table: GameTable, reason: str) -> None:
    for seat in list(table.seats):
        presence.publish(seat.user_id, {"type": "table_closed", "table_id": table.id, "reason": reason})


def _deadline(table: GameTable, phase: int) -> int:
    started = _utc(table.turn_started_at)
    if table.status != "playing" or started is None:
        return 0
    return int(started.timestamp()) + (OPENING_SECONDS if phase == 0 else TURN_SECONDS)


def _decorate(table: GameTable, seat: int, snap: dict[str, Any]) -> dict[str, Any]:
    heroes = ["", ""]
    for item in table.seats:
        if 0 <= item.seat_index < len(heroes):
            heroes[item.seat_index] = item.hero_id or ""
    merged = dict(snap)
    merged["table_id"] = table.id
    merged["your_seat"] = seat
    merged["heroes"] = heroes
    merged["turn_deadline_unix"] = _deadline(table, snap["phase"])
    opponent = 0
    for item in table.seats:
        if item.seat_index != seat:
            opponent = item.user_id
    merged["opponent_user_id"] = opponent
    return merged


def _decks(table: GameTable) -> list[list[str]]:
    decks: list[list[str]] = []
    for seat in sorted(table.seats, key=lambda item: item.seat_index):
        parsed = json.loads(seat.deck_json or "[]")
        decks.append([str(card_id) for card_id in parsed])
    return decks


def _stored_actions(db: Session, table_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(select(TableAction).where(TableAction.table_id == table_id).order_by(TableAction.seq)).all()
    actions = []
    for row in rows:
        body = json.loads(row.body)
        body["seat"] = row.seat_index
        body["client_action_id"] = row.client_action_id
        actions.append(body)
    return actions


def _ensure_worker(db: Session, table: GameTable) -> None:
    if table.status != "playing" or table.seed is None:
        return
    try:
        snapshot(str(table.id), 0)
        return
    except MatchWorkerError as ex:
        if not ex.missing and "not running" in ex.message:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ex.message) from ex
    try:
        replay_match(str(table.id), int(table.seed), _decks(table), _stored_actions(db, table.id))
    except MatchWorkerError as ex:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ex.message) from ex


def _push_snapshots(db: Session, table: GameTable) -> dict[int, dict[str, Any]]:
    _ensure_worker(db, table)
    found: dict[int, dict[str, Any]] = {}
    for seat in table.seats:
        try:
            snap = snapshot(str(table.id), seat.seat_index)
        except MatchWorkerError as ex:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ex.message) from ex
        found[seat.seat_index] = snap
    if found:
        sample = next(iter(found.values()))
        opening = sample["phase"] == 0
        clock_owner = OPENING_CLOCK if opening else sample["active_seat"]
        if table.turn_started_at is None or (not opening and clock_owner != table.last_active_seat):
            table.turn_started_at = _now()
        table.last_active_seat = clock_owner
    _save_result_if_finished(db, table, found)
    db.commit()
    for seat in table.seats:
        decorated = _decorate(table, seat.seat_index, found[seat.seat_index])
        found[seat.seat_index] = decorated
        presence.publish(seat.user_id, {"type": "snapshot", "snapshot": decorated})
    return found


def _save_result_if_finished(db: Session, table: GameTable, snaps: dict[int, dict[str, Any]]) -> None:
    if table.result_saved or len(snaps) == 0:
        return
    sample = next(iter(snaps.values()))
    outcome = int(sample.get("outcome", 0))
    if outcome == 0:
        return
    turn_number = int(sample.get("turn_number", 0))
    for seat in table.seats:
        if outcome == 3:
            result = "draw"
        elif (outcome == 1 and seat.seat_index == 0) or (outcome == 2 and seat.seat_index == 1):
            result = "win"
        else:
            result = "loss"
        opponent_hero = ""
        for other in table.seats:
            if other.seat_index != seat.seat_index:
                opponent_hero = other.hero_id or ""
        db.add(
            MatchResult(
                user_id=seat.user_id,
                client_match_id=f"friend-{table.id}-{seat.user_id}",
                opponent="friend",
                difficulty="medium",
                result=result,
                player_hero=seat.hero_id or None,
                opponent_hero=opponent_hero or None,
                details=f"turn={turn_number};table={table.id};mode={table.mode}",
            )
        )
    table.result_saved = True
    table.status = "finished"
    table.finished_at = _now()


@router.post("/invites", response_model=InviteRecord)
def create_invite(
    payload: InviteCreateRequest,
    user: User = Depends(account_user),
    db: Session = Depends(get_db),
) -> InviteRecord:
    from app.social import accepted_between, blocked_either

    if payload.user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot invite yourself.")
    if live_table_for(db, user.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are already in a game.")
    other = load_active_user_by_id(db, payload.user_id)
    if other is None or other.is_guest or blocked_either(db, user.id, other.id) or accepted_between(db, user.id, other.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found.")
    if not presence.is_online(other.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That player is offline.")
    if live_table_for(db, other.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That player is already in a game.")

    table = GameTable(mode="duel", status="lobby")
    db.add(table)
    db.flush()
    db.add(TableSeat(table_id=table.id, seat_index=0, user_id=user.id, team=0, hero_id="", deck_json="[]", ready=False))
    expires = _now() + timedelta(seconds=INVITE_SECONDS)
    invite = TableInvite(
        table_id=table.id,
        from_user_id=user.id,
        to_user_id=other.id,
        status="pending",
        expires_at=expires,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    record = InviteRecord(
        invite_id=invite.id,
        table_id=table.id,
        from_user_id=user.id,
        from_display_name=user.display_name,
        to_user_id=other.id,
        expires_unix=int(expires.timestamp()),
        status="pending",
    )
    presence.publish(other.id, {"type": "invite", "invite": record.model_dump(mode="json")})
    presence.publish(user.id, {"type": "invite_sent", "invite": record.model_dump(mode="json")})
    return record


def _load_invite(db: Session, invite_id: int) -> TableInvite:
    invite = db.scalar(
        select(TableInvite)
        .where(TableInvite.id == invite_id)
        .with_for_update()
        .options(selectinload(TableInvite.table).selectinload(GameTable.seats), selectinload(TableInvite.table).selectinload(GameTable.invites))
    )
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    return invite


def _close_invite(db: Session, invite: TableInvite, reason: str, commit: bool) -> None:
    invite.status = reason
    table = invite.table
    if table is not None and table.status == "lobby":
        table.status = "cancelled"
        table.finished_at = _now()
        _publish_closed(table, "The invite was closed.")
    presence.publish(invite.from_user_id, {"type": "invite_closed", "invite_id": invite.id, "table_id": invite.table_id, "status": reason})
    presence.publish(invite.to_user_id, {"type": "invite_closed", "invite_id": invite.id, "table_id": invite.table_id, "status": reason})
    if commit:
        db.commit()


def close_pair_invites(db: Session, left_id: int, right_id: int, reason: str) -> None:
    invites = db.scalars(
        select(TableInvite)
        .where(TableInvite.status == "pending")
        .options(selectinload(TableInvite.table).selectinload(GameTable.seats))
    ).all()
    for invite in invites:
        pair = {invite.from_user_id, invite.to_user_id}
        if pair == {left_id, right_id}:
            _close_invite(db, invite, reason, commit=False)


@router.post("/invites/{invite_id}/accept", response_model=TableRecord)
def accept_invite(invite_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> TableRecord:
    invite = _load_invite(db, invite_id)
    if invite.to_user_id != user.id or invite.status != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    expires = _utc(invite.expires_at)
    if expires is not None and expires <= _now():
        _close_invite(db, invite, "expired", commit=True)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That invite expired.")
    if live_table_for(db, user.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are already in a game.")
    table = invite.table
    if table is None or table.status != "lobby":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That table is no longer open.")
    invite.status = "accepted"
    table.seats.append(TableSeat(seat_index=1, user_id=user.id, team=0, hero_id="", deck_json="[]", ready=False))
    db.commit()
    refreshed = live_table_for(db, user.id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That table is no longer open.")
    _publish_lobby(db, refreshed)
    return table_record(db, refreshed, user.id)


@router.post("/invites/{invite_id}/decline")
def decline_invite(invite_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> dict[str, str]:
    invite = _load_invite(db, invite_id)
    if invite.to_user_id != user.id or invite.status != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    _close_invite(db, invite, "declined", commit=True)
    return {"status": "declined"}


@router.post("/invites/{invite_id}/cancel")
def cancel_invite(invite_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> dict[str, str]:
    invite = _load_invite(db, invite_id)
    if invite.from_user_id != user.id or invite.status != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    _close_invite(db, invite, "cancelled", commit=True)
    return {"status": "cancelled"}


@router.get("/tables/current")
def current_table(user: User = Depends(account_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    table = live_table_for(db, user.id)
    if table is None:
        return {"table": None}
    return {"table": table_record(db, table, user.id).model_dump(mode="json")}


def _lock_table(db: Session, table_id: int) -> GameTable | None:
    # End the read view opened by authentication or the clock's list query.
    # Each writer reads the latest action sequence under the same row lock.
    db.commit()
    return db.scalar(
        select(GameTable).where(GameTable.id == table_id).with_for_update()
        .execution_options(populate_existing=True)
        .options(selectinload(GameTable.seats), selectinload(GameTable.invites))
    )


def _require_table(db: Session, table_id: int, user: User) -> tuple[GameTable, TableSeat]:
    table = _lock_table(db, table_id)
    if table is None or table.status not in ("lobby", "playing"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found.")
    seat = _seat_for(table, user.id)
    if seat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found.")
    return table, seat


@router.post("/tables/{table_id}/ready", response_model=TableRecord)
def ready_up(
    table_id: int,
    payload: ReadyRequest,
    user: User = Depends(account_user),
    db: Session = Depends(get_db),
) -> TableRecord:
    from app.main import _validate_deck_cards

    table, seat = _require_table(db, table_id, user)
    if table.status != "lobby":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The match has already started.")
    cards = _validate_deck_cards(list(payload.card_ids))
    if len(cards) != 30:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A match deck needs 30 cards.")
    for other in table.seats:
        if other.user_id != user.id and other.ready and other.hero_id == payload.hero_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pick a different hero from your friend.")
    seat.hero_id = payload.hero_id
    seat.deck_json = json.dumps(cards)
    seat.ready = True
    if len(table.seats) == 2 and all(item.ready and item.hero_id for item in table.seats):
        _start_match(db, table)
    else:
        db.commit()
        _publish_lobby(db, table)
    return table_record(db, table, user.id)


def _start_match(db: Session, table: GameTable) -> None:
    table.seed = secrets.randbelow(2_000_000_000) + 1
    table.status = "playing"
    table.turn_started_at = _now()
    table.last_active_seat = OPENING_CLOCK
    try:
        create_match(str(table.id), int(table.seed), _decks(table))
    except MatchWorkerError as ex:
        table.status = "lobby"
        for seat in table.seats:
            seat.ready = False
        db.commit()
        _publish_lobby(db, table)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ex.message) from ex
    _push_snapshots(db, table)


@router.post("/tables/{table_id}/leave")
def leave_table(table_id: int, user: User = Depends(account_user), db: Session = Depends(get_db)) -> dict[str, str]:
    table, seat = _require_table(db, table_id, user)
    if table.status == "lobby":
        table.status = "cancelled"
        table.finished_at = _now()
        for invite in table.invites:
            if invite.status == "pending":
                invite.status = "cancelled"
        _publish_closed(table, "The other player left the lobby.")
        db.commit()
        return {"status": "cancelled"}
    _force_concede(db, table, seat.seat_index, f"leave-{table.id}-{seat.seat_index}")
    return {"status": "conceded"}


@router.post("/tables/{table_id}/actions")
def post_action(
    table_id: int,
    payload: ActionRequest,
    user: User = Depends(account_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    table, seat = _require_table(db, table_id, user)
    if table.status != "playing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The match is not in progress.")
    if payload.action_type == "RestartMatch":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restart is not available online.")

    existing = db.scalar(
        select(TableAction).where(
            TableAction.table_id == table.id,
            TableAction.seat_index == seat.seat_index,
            TableAction.client_action_id == payload.client_action_id,
        )
    )
    if existing is not None:
        _ensure_worker(db, table)
        try:
            snap = snapshot(str(table.id), seat.seat_index)
        except MatchWorkerError as ex:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ex.message) from ex
        return {"ok": True, "error": "", "snapshot": _decorate(table, seat.seat_index, snap)}

    if payload.action_type == "ConfirmMulligan" and _now().timestamp() >= _deadline(table, 0):
        return {"ok": False, "error": "Opening hand selection has ended.", "snapshot": None}

    body = {
        "kind": "action",
        "action_type": payload.action_type,
        "card_instance_ids": payload.card_instance_ids,
        "card_instance_id": payload.card_instance_id,
        "lane_index": payload.lane_index,
        "target_player_index": payload.target_player_index,
        "target_unit_instance_id": payload.target_unit_instance_id,
        "second_target_unit_instance_id": payload.second_target_unit_instance_id,
        "ally_unit_instance_id": payload.ally_unit_instance_id,
    }
    request_body = {"seat": seat.seat_index, "client_action_id": payload.client_action_id}
    request_body.update(body)
    try:
        result = apply_action(str(table.id), request_body)
    except MatchWorkerError as ex:
        if not ex.missing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ex.message) from ex
        _ensure_worker(db, table)
        try:
            result = apply_action(str(table.id), request_body)
        except MatchWorkerError as again:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=again.message) from again

    if not result.get("ok", False):
        return {"ok": False, "error": result.get("error") or "That action was rejected.", "snapshot": None}

    table.action_seq += 1
    db.add(
        TableAction(
            table_id=table.id,
            seq=table.action_seq,
            seat_index=seat.seat_index,
            client_action_id=payload.client_action_id,
            body=json.dumps(body),
        )
    )
    db.flush()
    snaps = _push_snapshots(db, table)
    return {"ok": True, "error": "", "snapshot": snaps.get(seat.seat_index)}


def _force_concede(db: Session, table: GameTable, seat_index: int, client_action_id: str) -> None:
    if table.status != "playing":
        return
    body = {"kind": "force_concede", "action_type": "ForceConcede"}
    request_body = {"seat": seat_index, "client_action_id": client_action_id}
    request_body.update(body)
    try:
        result = apply_action(str(table.id), request_body)
    except MatchWorkerError:
        return
    if not result.get("ok", False):
        return
    table.action_seq += 1
    db.add(
        TableAction(
            table_id=table.id,
            seq=table.action_seq,
            seat_index=seat_index,
            client_action_id=client_action_id,
            body=json.dumps(body),
        )
    )
    db.flush()
    _push_snapshots(db, table)


def _clock_body(action_type: str) -> dict[str, Any]:
    return {
        "kind": "action",
        "action_type": action_type,
        "card_instance_ids": [],
        "card_instance_id": 0,
        "lane_index": -1,
        "target_player_index": -1,
        "target_unit_instance_id": 0,
        "second_target_unit_instance_id": 0,
        "ally_unit_instance_id": 0,
    }


def note_presence(user_id: int, online: bool) -> None:
    if online:
        _disconnect_since.pop(user_id, None)
    elif user_id not in _disconnect_since:
        _disconnect_since[user_id] = _now()


def resume_for(user_id: int) -> None:
    db = SessionLocal()
    try:
        pending = db.scalars(select(TableInvite).where(
            TableInvite.status == "pending",
            (TableInvite.from_user_id == user_id) | (TableInvite.to_user_id == user_id),
            TableInvite.expires_at > _now(),
        ).order_by(TableInvite.id)).all()
        for invite in pending:
            sender = db.get(User, invite.from_user_id)
            record = InviteRecord(invite_id=invite.id, table_id=invite.table_id,
                                  from_user_id=invite.from_user_id, from_display_name=sender.display_name,
                                  to_user_id=invite.to_user_id, status="pending",
                                  expires_unix=int(_utc(invite.expires_at).timestamp()))
            event = "invite_sent" if invite.from_user_id == user_id else "invite"
            presence.publish(user_id, {"type": event, "invite": record.model_dump(mode="json")})
        table = live_table_for(db, user_id)
        if table is None:
            return
        if table.status == "lobby":
            if len(table.seats) < 2:
                return
            presence.publish(user_id, {"type": "lobby", "table": table_record(db, table, user_id).model_dump(mode="json")})
            return
        if table.status != "playing":
            return
        seat = _seat_for(table, user_id)
        if seat is None:
            return
        _ensure_worker(db, table)
        decorated = _decorate(table, seat.seat_index, snapshot(str(table.id), seat.seat_index))
        presence.publish(user_id, {"type": "snapshot", "snapshot": decorated})
    except Exception:
        return
    finally:
        db.close()


def watch_tables() -> None:
    db = SessionLocal()
    try:
        now = _now()
        invites = db.scalars(
            select(TableInvite)
            .where(TableInvite.status == "pending")
            .options(selectinload(TableInvite.table).selectinload(GameTable.seats))
        ).all()
        for invite in invites:
            expires = _utc(invite.expires_at)
            if expires is not None and expires <= now:
                _close_invite(db, invite, "expired", commit=False)
        db.commit()

        online = presence.online_ids()
        playing = db.scalars(select(GameTable.id).where(GameTable.status == "playing")).all()
        for table_id in playing:
            table = _lock_table(db, table_id)
            if table is None or table.status != "playing":
                continue
            for seat in table.seats:
                if seat.user_id in online:
                    _disconnect_since.pop(seat.user_id, None)
                else:
                    started = _disconnect_since.get(seat.user_id)
                    if started is None:
                        _disconnect_since[seat.user_id] = now
                    elif (now - started).total_seconds() >= DISCONNECT_SECONDS:
                        _force_concede(db, table, seat.seat_index, f"disconnect-{table.id}-{seat.seat_index}")
                        _disconnect_since.pop(seat.user_id, None)
            if table.status != "playing":
                continue
            if now.timestamp() < _deadline(table, 0):
                continue
            try:
                _ensure_worker(db, table)
                sample = snapshot(str(table.id), 0)
            except (MatchWorkerError, HTTPException):
                continue
            if sample["outcome"] != 0:
                _push_snapshots(db, table)
                continue
            phase = sample["phase"]
            if now.timestamp() < _deadline(table, phase):
                continue
            opening = phase == 0
            seats = [idx for idx in (0, 1) if not sample[f"mulligan_{idx}"]] if opening else [sample["active_seat"]]
            for seat in seats:
                body = _clock_body("ConfirmMulligan" if opening else "EndTurn")
                seq = table.action_seq + 1
                action_id = f"clock-{table.id}-{seq}"
                try:
                    result = apply_action(str(table.id), dict(body, seat=seat, client_action_id=action_id))
                except MatchWorkerError:
                    break
                if not result.get("ok"):
                    if not opening:
                        _force_concede(db, table, seat, f"clock-force-{table.id}-{seq}")
                    break
                table.action_seq = seq
                db.add(TableAction(table_id=table.id, seq=seq, seat_index=seat,
                                   client_action_id=action_id, body=json.dumps(body)))
            if db.new:
                db.flush()
                _push_snapshots(db, table)
    finally:
        db.close()
