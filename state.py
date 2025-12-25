import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict

STATE_FILE = Path(__file__).with_name("state.json")
STATE_LOCK = asyncio.Lock()


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {"chats": {}, "apps": {}}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "chats" not in data:
            data["chats"] = {}
        if "apps" not in data:
            data["apps"] = {}
        return data
    except (OSError, json.JSONDecodeError):
        return {"chats": {}, "apps": {}}


async def save_state(state: Dict[str, Any]) -> None:
    async with STATE_LOCK:
        with STATE_FILE.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)


def ensure_chat_state(state: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
    chats = state.setdefault("chats", {})
    chat_state = chats.setdefault(
        str(chat_id),
        {
            "enabled": False,
            "chat_type": None,
            "message_id": None,
            "last_sent_text": None,
            "backoff_until": None,
            "last_user_reply_ts": None,
            "viewers": {},
            "status_visible": False,
            "view_mode": "status",
        },
    )
    if "view_mode" not in chat_state:
        chat_state["view_mode"] = "status"
    return chat_state


def active_viewers(chat_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    viewers = chat_state.get("viewers") or {}
    now = time.time()
    return {
        uid: info
        for uid, info in viewers.items()
        if info.get("view_expire") and info["view_expire"] > now
    }


def active_viewer_count_global(state: Dict[str, Any]) -> int:
    viewer_ids = set()
    now = time.time()
    for chat_state in state.get("chats", {}).values():
        prune_expired_viewers(chat_state)
        viewers = chat_state.get("viewers") or {}
        for uid, info in viewers.items():
            if info.get("view_expire") and info["view_expire"] > now:
                viewer_ids.add(uid)
    return len(viewer_ids)


def active_viewer_details_global(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    details: Dict[str, Dict[str, Any]] = {}
    now = time.time()
    for chat_state in state.get("chats", {}).values():
        prune_expired_viewers(chat_state)
        viewers = chat_state.get("viewers") or {}
        for uid, info in viewers.items():
            if info.get("view_expire") and info["view_expire"] > now:
                details[uid] = {
                    "username": info.get("username"),
                    "name": info.get("name"),
                }
    return details


def prune_expired_viewers(chat_state: Dict[str, Any]) -> None:
    viewers = chat_state.get("viewers") or {}
    now = time.time()
    to_remove = [uid for uid, info in viewers.items() if not info.get("view_expire") or info["view_expire"] <= now]
    for uid in to_remove:
        viewers.pop(uid, None)
    chat_state["viewers"] = viewers


def ensure_app_state(state: Dict[str, Any], app_key: str) -> Dict[str, Any]:
    apps = state.setdefault("apps", {})
    return apps.setdefault(
        app_key,
        {
            "last_active_ts": None,
            "last_title": None,
        },
    )
