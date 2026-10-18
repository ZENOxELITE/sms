from threading import RLock
from uuid import uuid4

_sessions: dict[str, dict[str, object]] = {}
_lock = RLock()


def save_session(access_token: str, refresh_token: str, expires_at: int) -> str:
    session_id = uuid4().hex
    with _lock:
        _sessions[session_id] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
    return session_id


def get_session(session_id: str) -> dict[str, object] | None:
    with _lock:
        stored = _sessions.get(session_id)
        return stored.copy() if stored else None


def update_session(session_id: str, access_token: str, refresh_token: str, expires_at: int) -> None:
    with _lock:
        if session_id in _sessions:
            _sessions[session_id] = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
            }


def delete_session(session_id: str | None) -> None:
    if session_id:
        with _lock:
            _sessions.pop(session_id, None)
