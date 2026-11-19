import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.deps import _token
from app.presence import presence
from app.security import decode_access_token_with_expiry
from app.service import load_active_user_by_id
from app.social import publish_friends_changed
from app.tables import note_presence


router = APIRouter()


@router.websocket("/ws")
async def live_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    user_id = 0
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
    except Exception:
        await websocket.close()
        return

    token = ""
    if raw.startswith("{"):
        import json

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        token = str(payload.get("token") or "")
    if not token:
        token = _token(raw) or ""

    db = SessionLocal()
    try:
        try:
            user_id, expires_at = decode_access_token_with_expiry(token)
        except Exception:
            await websocket.send_text('{"type":"error","message":"Invalid token."}')
            await websocket.close()
            return
        user = load_active_user_by_id(db, user_id)
        if user is None:
            await websocket.send_text('{"type":"error","message":"Session not found."}')
            await websocket.close()
            return
    finally:
        db.close()

    presence.connect(user.id, websocket)
    note_presence(user.id, True)
    try:
        with SessionLocal() as session:
            publish_friends_changed(session, user.id)
        await websocket.send_text('{"type":"auth_ok"}')
        from app.tables import resume_for

        resume_for(user.id)
        while True:
            remaining = expires_at - time.time()
            if remaining <= 0:
                await websocket.close(code=1008)
                break
            try:
                incoming = await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
            except asyncio.TimeoutError:
                await websocket.close(code=1008)
                break
            if time.time() >= expires_at:
                await websocket.close(code=1008)
                break
            if incoming == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        still = presence.disconnect(user.id, websocket)
        note_presence(user.id, still)
        if not still:
            with SessionLocal() as session:
                publish_friends_changed(session, user.id)
