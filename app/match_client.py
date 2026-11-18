import json
import urllib.error
import urllib.request
from typing import Any

from app.config import settings


class MatchWorkerError(Exception):
    def __init__(self, message: str, missing: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.missing = missing


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = settings.match_url.rstrip("/") + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode("utf-8", "replace")
        message = raw or ex.reason
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("error"):
                message = str(parsed["error"])
        except json.JSONDecodeError:
            pass
        raise MatchWorkerError(message, missing=ex.code == 404) from ex
    except urllib.error.URLError as ex:
        raise MatchWorkerError("Match server is not running.") from ex

    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise MatchWorkerError("Match server returned an unexpected response.")
    return parsed


def create_match(match_id: str, seed: int, decks: list[list[str]]) -> dict[str, Any]:
    return _request("POST", "/matches", {"match_id": match_id, "seed": seed, "decks": decks})


def replay_match(match_id: str, seed: int, decks: list[list[str]], actions: list[dict[str, Any]]) -> dict[str, Any]:
    return _request(
        "POST",
        f"/matches/{match_id}/replay",
        {"match_id": match_id, "seed": seed, "decks": decks, "actions": actions},
    )


def apply_action(match_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _request("POST", f"/matches/{match_id}/actions", payload)


def snapshot(match_id: str, seat: int) -> dict[str, Any]:
    return _request("GET", f"/matches/{match_id}/snapshot?seat={seat}")
