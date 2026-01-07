import asyncio
import json
import logging
import time
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Dict

from windows import get_local_date_string


class ViewMode(str, Enum):
    STATUS = "status"
    HARDWARE = "hardware"
    VIEWERS = "viewers"
    STATS = "stats"

STATE_FILE = Path(__file__).with_name("state.json")
STATS_DIR = STATE_FILE.parent
STATE_LOCK = asyncio.Lock()


def _stats_filename_for_date(current_date: str) -> Path:
    try:
        parsed = date.fromisoformat(current_date)
        return STATS_DIR / f"stats_{parsed.day:02d}_{parsed.month:02d}_{parsed.year:04d}.json"
    except Exception:
        return STATS_DIR / "stats_unknown.json"


def _cleanup_old_stats_files(current_date: str) -> None:
    desired = _stats_filename_for_date(current_date).name
    for path in STATS_DIR.glob("stats_*.json"):
        if path.name != desired:
            try:
                path.unlink()
                logging.info("Daily stats date mismatch, deleting %s", path.name)
            except OSError:
                logging.warning("Failed to delete old stats file %s", path)


def load_daily_stats(current_date: str) -> Dict[str, Any]:
    _cleanup_old_stats_files(current_date)
    stats_file = _stats_filename_for_date(current_date)
    if not stats_file.exists():
        logging.info("Loaded daily stats file: %s (new)", stats_file.name)
        return {"date": current_date, "users": {}}
    try:
        with stats_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("date") != current_date:
            logging.info("Daily stats date mismatch, resetting stats")
            return {"date": current_date, "users": {}}
        logging.info("Loaded daily stats file: %s", stats_file.name)
        return {"date": current_date, "users": data.get("users", {})}
    except (OSError, json.JSONDecodeError):
        logging.warning("Failed to read stats file %s, resetting", stats_file)
        return {"date": current_date, "users": {}}


def save_daily_stats(stats: Dict[str, Any]) -> None:
    current_date = stats.get("date") or get_local_date_string()
    stats_file = _stats_filename_for_date(current_date)
    try:
        with stats_file.open("w", encoding="utf-8") as handle:
            json.dump({"date": current_date, "users": stats.get("users", {})}, handle, ensure_ascii=False, indent=2)
    except OSError:
        logging.exception("Unable to save daily stats to %s", stats_file)


def load_state(current_date: str | None = None) -> Dict[str, Any]:
    current_date = current_date or get_local_date_string()
    base = {"chats": {}, "apps": {}, "view_stats": load_daily_stats(current_date)}
    if not STATE_FILE.exists():
        return base
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "chats" not in data:
            data["chats"] = {}
        if "apps" not in data:
            data["apps"] = {}
        data["view_stats"] = load_daily_stats(current_date)
        return data
    except (OSError, json.JSONDecodeError):
        return base


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
            "chat_username": None,
            "chat_name": None,
            "message_id": None,
            "last_sent_text": None,
            "backoff_until": None,
            "last_user_reply_ts": None,
            "last_button_ts": {},
            "viewers": {},
            "status_visible": False,
            "view_mode": ViewMode.STATUS.value,
            "stats_page": 0,
            "callback_in_progress": False,
        },
    )
    if chat_state.get("view_mode") not in {mode.value for mode in ViewMode}:
        chat_state["view_mode"] = ViewMode.STATUS.value
    if "stats_page" not in chat_state:
        chat_state["stats_page"] = 0
    if "last_button_ts" not in chat_state:
        chat_state["last_button_ts"] = {}
    if "callback_in_progress" not in chat_state:
        chat_state["callback_in_progress"] = False
    return chat_state


def format_chat_label(chat_id: int, chat_state: Dict[str, Any]) -> str:
    username = chat_state.get("chat_username")
    name = chat_state.get("chat_name")
    if username:
        return f"@{username} ({chat_id})"
    if name:
        return f"{name} ({chat_id})"
    return str(chat_id)


def disable_chat(state: Dict[str, Any] | None, chat_id: int) -> None:
    if state is None:
        return
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["enabled"] = False
    chat_state["viewers"] = {}
    chat_state["status_visible"] = False
    chat_state["view_mode"] = ViewMode.STATUS.value
    chat_state["message_id"] = None
    chat_state["last_sent_text"] = None
    chat_state["backoff_until"] = None
    stats = state.get("view_stats") if state else None
    if stats:
        stats.get("users", {}).pop(str(chat_id), None)


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


def ensure_view_stats(state: Dict[str, Any], current_date: str) -> Dict[str, Any]:
    stats = state.setdefault("view_stats", {"date": None, "users": {}})
    if stats.get("date") != current_date:
        stats = load_daily_stats(current_date)
        state["view_stats"] = stats
    if "users" not in stats:
        stats["users"] = {}
    return stats


def record_view_event(
    state: Dict[str, Any],
    current_date: str,
    user_id: int,
    username: str | None,
    name: str | None,
    timestamp: float,
) -> None:
    stats = ensure_view_stats(state, current_date)
    users = stats.setdefault("users", {})
    entry = users.setdefault(
        str(user_id),
        {"username": username, "name": name, "count": 0, "last_view": timestamp},
    )
    entry["username"] = username or entry.get("username")
    entry["name"] = name or entry.get("name")
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_view"] = timestamp
    save_daily_stats(stats)


def get_view_stats(state: Dict[str, Any], current_date: str) -> Dict[str, Any]:
    return ensure_view_stats(state, current_date)
