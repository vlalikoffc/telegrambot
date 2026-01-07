import os
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from system.presence import PRESENCE_THRESHOLD_SECONDS, PRESENCE_TRACKER, presence_duration_seconds
from system.runtime import get_bot_uptime_seconds
from system.state import ensure_app_state
from system.platform import (
    get_last_input_idle_seconds,
    get_process_count,
    get_local_time_string,
    get_window_title_for_pid,
    list_running_processes,
)
from .constants import (
    ACTIVE_THRESHOLD_SECONDS,
    BROWSER_PROCESS_NAMES,
    DISPLAY_NAMES,
    FAVORITE_APPS,
    FOOTER_TEXT,
    HIDDEN_STATUS_TEXT,
    JS_PROCESS_NAMES,
    PROCESS_ALIASES,
    PYTHON_PROCESS_NAMES,
    TAGLINES,
)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return str(timedelta(seconds=seconds))


def _format_presence_duration(seconds: float, with_suffix: bool = False) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "только что" if with_suffix else "только что"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} мин" + (" назад" if with_suffix else "")
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes:
        return f"{hours} ч {remaining_minutes} мин" + (" назад" if with_suffix else "")
    return f"{hours} ч" + (" назад" if with_suffix else "")


def resolve_app_key(process_name: Optional[str]) -> str:
    if not process_name:
        return "unknown"
    normalized = process_name.lower()
    return PROCESS_ALIASES.get(normalized, "unknown")


def resolve_display_name(app_key: str, process_name: Optional[str], title: Optional[str] = None) -> str:
    if app_key == "minecraft" and title:
        return title
    if app_key == "browser":
        return DISPLAY_NAMES["browser"]
    if app_key != "unknown":
        return DISPLAY_NAMES.get(app_key, process_name or "Unknown")
    if process_name:
        return process_name.replace(".exe", "").strip() or "Unknown"
    return "Unknown"


def resolve_tagline(app_key: str) -> str:
    return TAGLINES.get(app_key, TAGLINES["default"])


def _detect_minecraft_display(process_info: Dict[str, Any]) -> Optional[str]:
    pid = process_info.get("pid")
    if pid is None:
        return None
    title = get_window_title_for_pid(pid)
    if title and "minecraft" in title.lower():
        return title
    return None


def _detect_app_key(process_info: Dict[str, Any]) -> (str, Optional[str]):
    name = process_info.get("name")
    if not name:
        return "unknown", None
    lower_name = name.lower()
    if lower_name in {"java.exe", "javaw.exe"}:
        title = _detect_minecraft_display(process_info)
        if title:
            return "minecraft", title
    return resolve_app_key(name), None


def _collect_running_apps(processes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    running: Dict[str, Dict[str, Any]] = {}
    processes = processes or list_running_processes()
    for proc_info in processes:
        app_key, detected_title = _detect_app_key(proc_info)
        if app_key == "unknown":
            continue
        current = running.setdefault(
            app_key,
            {
                "pids": set(),
                "title": detected_title,
            },
        )
        current["pids"].add(proc_info.get("pid"))
        if detected_title:
            current["title"] = detected_title
    return running


def _update_activity(state: Dict[str, Any], app_key: str, title: Optional[str]) -> None:
    app_state = ensure_app_state(state, app_key)
    app_state["last_active_ts"] = time.time()
    if title and app_key != "browser":
        app_state["last_title"] = title


def _favorite_entries_info(
    state: Dict[str, Any],
    active_app_key: str,
    running_apps: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    now = time.time()

    for app_key, info in FAVORITE_APPS.items():
        app_state = ensure_app_state(state, app_key)
        running = app_key in running_apps
        running_title = running_apps.get(app_key, {}).get("title")
        if running_title:
            app_state["last_title"] = running_title

        last_active_ts = app_state.get("last_active_ts")
        if running and app_key == active_app_key:
            _update_activity(state, app_key, running_title)
            last_active_ts = app_state.get("last_active_ts")

        is_active = False
        if running and last_active_ts and now - last_active_ts <= ACTIVE_THRESHOLD_SECONDS:
            is_active = True

        if not running:
            is_active = False

        if running:
            display_name = (
                "Браузер"
                if app_key == "browser"
                else app_state.get("last_title") or info.get("display") or DISPLAY_NAMES.get(app_key, app_key)
            )
        else:
            display_name = info.get("display") or DISPLAY_NAMES.get(app_key, app_key)
        entries.append(
            {
                "order": last_active_ts or 0,
                "name": display_name,
                "running": running,
                "active": is_active,
            }
        )

    entries.sort(key=lambda item: item["order"], reverse=True)
    return entries


def _favorite_entries(
    state: Dict[str, Any],
    active_app_key: str,
    running_apps: Dict[str, Dict[str, Any]],
) -> List[str]:
    entries = _favorite_entries_info(state, active_app_key, running_apps)
    lines = []
    for entry in entries:
        if entry["active"]:
            emoji = "▶️"
        elif entry["running"]:
            emoji = "🟢"
        else:
            emoji = "💤"
        lines.append(f"{emoji} {entry['name']}")
    return lines


def _detect_work_languages(processes: List[Dict[str, Any]], current_pid: int) -> List[str]:
    has_python = False
    has_js = False
    for proc in processes:
        name = (proc.get("name") or "").lower()
        if not name:
            continue
        pid = proc.get("pid")
        if pid == current_pid:
            continue
        if name in PYTHON_PROCESS_NAMES:
            has_python = True
            continue
        if name in JS_PROCESS_NAMES:
            has_js = True
            continue
    languages: List[str] = []
    if has_python:
        languages.append("Python")
    if has_js:
        languages.append("JavaScript")
    return languages


def _format_update_interval(seconds: float) -> str:
    if seconds.is_integer():
        return str(int(seconds))
    return f"{seconds:.1f}".rstrip("0").rstrip(".")


def build_status_text(
    state: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]],
    active_viewer_count: int = 0,
    update_interval_seconds: float = 1.0,
    running_apps: Optional[Dict[str, Dict[str, Any]]] = None,
    process_list: Optional[List[Dict[str, Any]]] = None,
    plugin_manager: Optional[Any] = None,
) -> str:
    uptime_seconds = get_bot_uptime_seconds()
    snapshot = snapshot or {}
    process_name = snapshot.get("process_name") or "Unknown"
    app_key = snapshot.get("app_key") or resolve_app_key(process_name)
    minecraft_version = snapshot.get("minecraft_version")
    minecraft_server = snapshot.get("minecraft_server")
    minecraft_client = snapshot.get("minecraft_client")
    display_name = (
        f"Minecraft {minecraft_version}" if app_key == "minecraft" and minecraft_version else "Minecraft"
        if app_key == "minecraft"
        else resolve_display_name(app_key, process_name)
    )
    tagline = snapshot.get("tagline") or resolve_tagline(app_key)
    app_uptime_seconds = snapshot.get("app_uptime_seconds")

    parts = [
        f"🖥️ Аптайм ПК (с запуска бота): {format_duration(uptime_seconds)}",
        f"⌚ Время на моём ПК: {get_local_time_string()}",
        f"🪟 Активное приложение: {display_name}",
        f"💬 Приписка: {tagline}",
    ]

    if app_uptime_seconds is not None:
        parts.append(f"⏱️ Аптайм приложения: {format_duration(app_uptime_seconds)}")

    if app_key == "minecraft" and minecraft_server:
        parts.append(f"🌐 Сервер: {minecraft_server}")
    if app_key == "minecraft" and minecraft_client:
        parts.append(f"🧩 Client: {minecraft_client}")

    process_count = get_process_count()
    if process_count is not None:
        parts.append(f"🔢 Процессов: {process_count}")

    idle_seconds = get_last_input_idle_seconds()
    presence_info = PRESENCE_TRACKER.observe(idle_seconds)
    presence_duration = presence_duration_seconds(presence_info)
    if presence_info.state == "unknown":
        parts.append("🟢 За компьютером: я здесь")
    elif presence_info.state == "active":
        label = "только что" if presence_duration < 60 else _format_presence_duration(presence_duration, with_suffix=True)
        parts.append(f"🟢 За компьютером: я здесь (последний ввод {label})")
    else:
        afk_label = _format_presence_duration(presence_duration)
        parts.append(f"💤 За компьютером: отошёл ({afk_label})")

    if running_apps is None:
        running_apps = _collect_running_apps(process_list)
    favorite_lines = _favorite_entries(state, app_key, running_apps)
    favorite_info = _favorite_entries_info(state, app_key, running_apps)

    parts.append("")
    parts.append("")
    parts.append("Избранные программы")
    parts.extend(favorite_lines)

    if process_list is None:
        process_list = list_running_processes()
    work_languages = _detect_work_languages(process_list, os.getpid())
    if work_languages:
        parts.append("")
        parts.append("🧑‍💻 Сейчас работаю:")
        for lang in work_languages:
            parts.append(f"• {lang}")

    parts.append("")
    parts.append(FOOTER_TEXT)
    if active_viewer_count > 0:
        parts.append(f"👀 Сейчас наблюдают за статусом: {active_viewer_count}")
    else:
        parts.append("😴 Сейчас никто не смотрит")
    parts.append(f"⚡ Обновление каждые {_format_update_interval(update_interval_seconds)} сек")

    if plugin_manager is not None:
        from system.plugins import RenderContext
        from system.plugins.render_context import (
            DefaultStatus,
            DefaultStatusActiveApp,
            DefaultStatusFavorite,
            DefaultStatusPresence,
        )

        default_status = DefaultStatus(
            uptime_seconds=uptime_seconds,
            local_time=get_local_time_string(),
            active_app=DefaultStatusActiveApp(
                key=app_key,
                name=display_name,
                tagline=tagline,
                uptime_seconds=app_uptime_seconds,
                minecraft_server=minecraft_server,
                minecraft_client=minecraft_client,
            ),
            process_count=process_count,
            presence=DefaultStatusPresence(
                state=presence_info.state,
                idle_seconds=idle_seconds,
                duration_seconds=presence_duration,
            ),
            favorites=tuple(
                DefaultStatusFavorite(
                    name=entry["name"],
                    running=entry["running"],
                    active=entry["active"],
                )
                for entry in favorite_info
            ),
            work_languages=tuple(work_languages),
            footer_text=FOOTER_TEXT,
            viewer_count=active_viewer_count,
            update_interval_seconds=update_interval_seconds,
        )
        render_ctx = RenderContext(lines=list(parts), default_status=default_status)
        plugin_manager.on_render(render_ctx, mode="status")
        parts = render_ctx.lines
    return "\n".join(parts)
