import asyncio
import json
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
            "message_ids": [],
            "last_sent_text": None,
            "backoff_until": None,
            "last_user_reply_ts": None,
        },
    )
    return chat_state


def ensure_app_state(state: Dict[str, Any], app_key: str) -> Dict[str, Any]:
    apps = state.setdefault("apps", {})
    return apps.setdefault(
        app_key,
        {
            "last_active_ts": None,
            "last_title": None,
        },
    )


def record_message_id(chat_state: Dict[str, Any], message_id: int) -> None:
    message_ids = chat_state.setdefault("message_ids", [])
    if message_id not in message_ids:
        message_ids.append(message_id)
