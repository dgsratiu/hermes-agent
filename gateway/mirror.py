"""
Session mirroring for cross-platform message delivery.

When a message is sent to a platform (via send_message or cron delivery),
this module appends a "delivery-mirror" record to the target session's
transcript so the receiving-side agent has context about what was sent.

Standalone -- works from CLI, cron, and gateway contexts without needing
the full SessionStore machinery.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from hermes_cli.config import get_hermes_home

logger = logging.getLogger(__name__)

_SESSIONS_DIR = get_hermes_home() / "sessions"
_SESSIONS_INDEX = _SESSIONS_DIR / "sessions.json"


def mirror_to_session(
    platform: str,
    chat_id: str,
    message_text: str,
    source_label: str = "cli",
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
    *,
    create_if_missing: bool = False,
    chat_type: Optional[str] = None,
    chat_name: Optional[str] = None,
    config: Optional[Any] = None,
) -> bool:
    """
    Append a delivery-mirror message to the target session's transcript.

    Finds the gateway session that matches the given platform + chat_id,
    then writes a mirror entry to SQLite.  When ``create_if_missing`` is True,
    a target gateway session is created first so a later reply in that chat can
    load the delivered message as prior assistant context.

    Returns True if mirrored successfully, False if no matching session or error.
    All errors are caught -- this is never fatal.
    """
    try:
        session_id = _find_session_id(
            platform,
            str(chat_id),
            thread_id=thread_id,
            user_id=user_id,
        )
        if not session_id:
            if create_if_missing:
                session_id = _create_session_id(
                    platform,
                    str(chat_id),
                    thread_id=thread_id,
                    user_id=user_id,
                    chat_type=chat_type,
                    chat_name=chat_name,
                    config=config,
                )
        if not session_id:
            logger.debug(
                "Mirror: no session found for %s:%s:%s:%s",
                platform,
                chat_id,
                thread_id,
                user_id,
            )
            return False

        mirror_msg = {
            "role": "assistant",
            "content": message_text,
            "timestamp": datetime.now().isoformat(),
            "mirror": True,
            "mirror_source": source_label,
        }

        _append_to_sqlite(session_id, mirror_msg)

        logger.debug("Mirror: wrote to session %s (from %s)", session_id, source_label)
        return True

    except Exception as e:
        logger.debug(
            "Mirror failed for %s:%s:%s:%s: %s",
            platform,
            chat_id,
            thread_id,
            user_id,
            e,
        )
        return False


def _find_session_id(
    platform: str,
    chat_id: str,
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """
    Find the active session_id for a platform + chat_id pair.

    Scans sessions.json entries and matches where origin.chat_id == chat_id
    on the right platform.  DM session keys don't embed the chat_id
    (e.g. "agent:main:telegram:dm"), so we check the origin dict.

    When *user_id* is provided, prefer exact sender matches. If multiple
    same-chat candidates exist and none matches the user, return None instead
    of guessing and contaminating another participant's session.
    """
    if not _SESSIONS_INDEX.exists():
        return None

    try:
        with open(_SESSIONS_INDEX, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    platform_lower = platform.lower()
    candidates = []

    for _key, entry in data.items():
        origin = entry.get("origin") or {}
        entry_platform = (origin.get("platform") or entry.get("platform", "")).lower()

        if entry_platform != platform_lower:
            continue

        origin_chat_id = str(origin.get("chat_id", ""))
        if origin_chat_id == str(chat_id):
            origin_thread_id = origin.get("thread_id")
            if thread_id is not None and str(origin_thread_id or "") != str(thread_id):
                continue
            candidates.append(entry)

    if not candidates:
        return None

    if user_id:
        exact_user_matches = [
            entry for entry in candidates
            if str((entry.get("origin") or {}).get("user_id") or "") == str(user_id)
        ]
        if exact_user_matches:
            candidates = exact_user_matches
        elif len(candidates) > 1:
            return None
    elif len(candidates) > 1:
        # Prefer the shared group/thread session when it exists alongside
        # legacy per-user shards for the same chat.  This is the shape produced
        # when a deployment changes from per-user group sessions to shared group
        # sessions; treating it as ambiguous drops delivery context on the floor.
        shared_candidates = [
            entry for entry in candidates
            if not str((entry.get("origin") or {}).get("user_id") or "").strip()
        ]
        if shared_candidates:
            candidates = shared_candidates
        else:
            distinct_user_ids = {
                str((entry.get("origin") or {}).get("user_id") or "").strip()
                for entry in candidates
                if str((entry.get("origin") or {}).get("user_id") or "").strip()
            }
            if len(distinct_user_ids) > 1:
                return None

    best_entry = max(candidates, key=lambda entry: entry.get("updated_at", ""))
    return best_entry.get("session_id")


def _infer_chat_type(platform: str, chat_id: str, thread_id: Optional[str], chat_type: Optional[str]) -> str:
    if chat_type:
        return chat_type
    if platform.lower() == "telegram":
        return "group" if str(chat_id).startswith("-") else "dm"
    if thread_id:
        return "thread"
    return "dm"


def _create_session_id(
    platform: str,
    chat_id: str,
    *,
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
    chat_type: Optional[str] = None,
    chat_name: Optional[str] = None,
    config: Optional[Any] = None,
) -> Optional[str]:
    """Create a gateway session entry for an outbound delivery target."""
    store = None
    try:
        from gateway.config import Platform, load_gateway_config
        from gateway.session import SessionSource, SessionStore

        platform_enum = Platform(platform.lower())
        config = config or load_gateway_config()
        source = SessionSource(
            platform=platform_enum,
            chat_id=str(chat_id),
            chat_name=chat_name,
            chat_type=_infer_chat_type(platform, chat_id, thread_id, chat_type),
            user_id=str(user_id) if user_id else None,
            thread_id=str(thread_id) if thread_id else None,
        )
        store = SessionStore(sessions_dir=config.sessions_dir, config=config)
        entry = store.get_or_create_session(source)
        return entry.session_id
    except Exception as exc:
        logger.debug(
            "Mirror: failed to create session for %s:%s:%s:%s: %s",
            platform,
            chat_id,
            thread_id,
            user_id,
            exc,
        )
        return None
    finally:
        db = getattr(store, "_db", None) if store is not None else None
        if db is not None:
            try:
                db.close()
            except Exception:
                pass



def _append_to_sqlite(session_id: str, message: dict) -> None:
    """Append a message to the SQLite session database."""
    db = None
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        db.append_message(
            session_id=session_id,
            role=message.get("role", "assistant"),
            content=message.get("content"),
        )
    except Exception as e:
        logger.debug("Mirror SQLite write failed: %s", e)
    finally:
        if db is not None:
            db.close()
