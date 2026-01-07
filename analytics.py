import logging
import math
import time
from typing import Any, Dict, List, Tuple

from config import OWNER_IDS
from windows import format_local_hhmm


PAGE_SIZE = 15
RECENT_VIEW_WINDOW_SECONDS = 300


def _format_user_display(entry: Dict[str, Any]) -> str:
    username = entry.get("username")
    if username:
        return f"@{username}"
    name = entry.get("name")
    return name or "User (no username)"


def build_recent_viewers_text(recent_views: Dict[int, Dict[str, Any]]) -> str:
    if not recent_views:
        return "👀 Просмотры статуса (0):\n• Пока никто не смотрел"
    lines = [f"👀 Просмотры статуса ({len(recent_views)}):"]
    for entry in recent_views.values():
        lines.append(f"• {_format_user_display(entry)}")
    return "\n".join(lines)


def _sorted_stats_entries(stats: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    entries = list(stats.get("users", {}).items())
    entries.sort(
        key=lambda item: (
            -int(item[1].get("count", 0)),
            -(item[1].get("last_view") or 0),
        )
    )
    return entries


def build_stats_text(stats: Dict[str, Any], page: int) -> str:
    entries = _sorted_stats_entries(stats)
    total_pages = max(1, math.ceil(len(entries) / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    slice_entries = entries[start:end]

    lines = ["📊 Статистика за сегодня"]
    if not slice_entries:
        lines.append("• Пока нет просмотров")
    for _, entry in slice_entries:
        display = _format_user_display(entry)
        count = entry.get("count", 0)
        last_view = entry.get("last_view")
        lines.append(f"{display} — {count} раз")
        if last_view:
            lines.append(f"⏱️ последний: {format_local_hhmm(last_view)}")
    lines.append("")
    lines.append(f"Страница {page + 1}/{total_pages}")
    return "\n".join(lines)


def is_owner(user_id: int | None) -> bool:
    return user_id in OWNER_IDS


def prune_recent_views(recent_views: Dict[int, Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    now = time.time()
    before = len(recent_views)
    cleaned = {
        uid: info
        for uid, info in recent_views.items()
        if info.get("last_view") and now - info["last_view"] <= RECENT_VIEW_WINDOW_SECONDS
    }
    after = len(cleaned)
    if before != after:
        logging.info("Recent views cleaned: before=%s after=%s", before, after)
    return cleaned


def add_recent_view(
    recent_views: Dict[int, Dict[str, Any]],
    user_id: int,
    username: str | None,
    name: str | None,
    timestamp: float,
) -> None:
    recent_views[user_id] = {"username": username, "name": name, "last_view": timestamp}

