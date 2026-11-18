import asyncio
import json
import threading
from typing import Any

from fastapi import WebSocket


class Presence:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sockets: dict[int, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def connect(self, user_id: int, socket: WebSocket) -> None:
        with self._lock:
            current = self._sockets.get(user_id)
            if current is None:
                current = set()
                self._sockets[user_id] = current
            current.add(socket)

    def disconnect(self, user_id: int, socket: WebSocket) -> bool:
        with self._lock:
            current = self._sockets.get(user_id)
            if current is None:
                return False
            current.discard(socket)
            if len(current) == 0:
                self._sockets.pop(user_id, None)
                return False
            return True

    def is_online(self, user_id: int) -> bool:
        with self._lock:
            current = self._sockets.get(user_id)
            return current is not None and len(current) > 0

    def online_ids(self) -> set[int]:
        with self._lock:
            return {user_id for user_id, sockets in self._sockets.items() if len(sockets) > 0}

    def publish(self, user_id: int, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        message = json.dumps(payload)
        asyncio.run_coroutine_threadsafe(self._send(user_id, message), loop)

    async def _send(self, user_id: int, message: str) -> None:
        with self._lock:
            sockets = list(self._sockets.get(user_id, set()))

        dead: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_text(message)
            except Exception:
                dead.append(socket)

        if len(dead) == 0:
            return

        with self._lock:
            current = self._sockets.get(user_id)
            if current is None:
                return
            for socket in dead:
                current.discard(socket)
            if len(current) == 0:
                self._sockets.pop(user_id, None)


presence = Presence()
