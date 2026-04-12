"""Session storage — JSON files keyed by hashed telegram_id."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import structlog
from pydantic import ValidationError

from src import config
from src.core.models import SessionState

log = structlog.get_logger()

_EMPTY_SESSION = {
    "user_id_hash": "",
    "transactions": [],
    "limits": {},
    "last_file_ts": None,
    "conversation_history": [],
    "pending_confirmation": None,
    "created_at": None,
    "updated_at": None,
}


def get_user_hash(telegram_id: int) -> str:
    raw = f"{telegram_id}:{config.SESSION_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _session_path(user_hash: str) -> Path:
    config.SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return config.SESSION_DIR / f"{user_hash}.json"


def _new_session(user_hash: str) -> dict:
    return {**_EMPTY_SESSION, "user_id_hash": user_hash, "created_at": datetime.utcnow().isoformat()}


def _validate(data: dict) -> dict:
    """Validate session against SessionState schema. Logs and resets invalid fields."""
    try:
        SessionState.model_validate(data)
    except ValidationError as e:
        log.warning("session_validation_error", errors=e.errors())
        # Reset only the invalid fields rather than dropping the whole session
        for err in e.errors():
            field = err["loc"][0] if err["loc"] else None
            if field and field in data:
                data[field] = _EMPTY_SESSION.get(field)
    return data


def load_session(user_hash: str) -> dict:
    path = _session_path(user_hash)
    if not path.exists():
        return _new_session(user_hash)
    with open(path) as f:
        session = json.load(f)
    # TTL check
    updated_at = session.get("updated_at") or session.get("created_at")
    if updated_at:
        age = datetime.utcnow() - datetime.fromisoformat(updated_at)
        if age > timedelta(days=config.SESSION_TTL_DAYS):
            log.info("session_expired", user_hash=user_hash)
            path.unlink(missing_ok=True)
            return _new_session(user_hash)
    return _validate(session)


def save_session(user_hash: str, session: dict) -> None:
    session["updated_at"] = datetime.utcnow().isoformat()
    # Validate before writing to disk
    try:
        SessionState.model_validate(session)
    except ValidationError as e:
        log.error("session_save_validation_error", errors=e.errors(), user_hash=user_hash)
    path = _session_path(user_hash)
    with open(path, "w") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    log.debug("session_saved", user_hash=user_hash)


def append_conversation(session: dict, role: str, content: str, max_messages: int = config.CONVERSATION_HISTORY_LIMIT) -> None:
    history = session.setdefault("conversation_history", [])
    history.append({"role": role, "content": content, "ts": datetime.utcnow().isoformat()})
    if len(history) > max_messages:
        session["conversation_history"] = history[-max_messages:]
