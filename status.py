import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from state import ensure_app_state
from windows import (
    get_active_process_info,
    get_last_input_idle_seconds,
    get_process_count,
    get_process_uptime_seconds,
    get_local_time_string,
    get_system_uptime_seconds,
    get_window_title_for_pid,
    list_running_processes,
)

FOOTER_TEXT = "вот чё я делаю, но не следите пж за мной 24/7(мой юз в тг @vlalikoffc)"
HIDDEN_STATUS_TEXT = "🙈 Статус сейчас скрыт\n\nНажмите кнопку ниже, чтобы посмотреть актуальный статус."

BROWSER_PROCESS_NAMES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "chromium.exe",
    "supermium.exe",
    "brave.exe",
    "bravebrowser.exe",
    "opera.exe",
    "opera_gx.exe",
}

PROCESS_ALIASES: Dict[str, str] = {
    **{name: "browser" for name in BROWSER_PROCESS_NAMES},
    "code.exe": "vscode",
    "telegram.exe": "telegram",
    "cs2.exe": "cs2",
    "csgo.exe": "cs2",
    "steam.exe": "steam",
    "discord.exe": "discord",
    "spotify.exe": "spotify",
    "obs64.exe": "obs",
    "obs32.exe": "obs",
    "java.exe": "java",
    "javaw.exe": "java",
}

DISPLAY_NAMES = {
    "browser": "Браузер",
    "vscode": "VS Code",
    "telegram": "Telegram",
    "cs2": "Counter-Strike 2",
    "steam": "Steam",
    "discord": "Discord",
    "spotify": "Spotify",
    "obs": "OBS",
    "minecraft": "Minecraft",
    "unknown": "Unknown",
}

TAGLINES = {
    "browser": "сижу просто так в интернете",
    "vscode": "страдаю хернёй (программирую)",
    "telegram": "залип в телеге",
    "cs2": "бегу на B",
    "steam": "катаю через Steam",
    "discord": "залип в дискорде",
    "spotify": "наслушиваюсь треков",
    "obs": "что-то записываю",
    "minecraft": "копаюсь в кубах",
    "default": "живу жизнь",
}

FAVORITE_APPS = {
    "minecraft": {"process_names": {"java.exe", "javaw.exe"}, "display": "Minecraft"},
    "browser": {"process_names": set(BROWSER_PROCESS_NAMES), "display": "Браузер"},
    "telegram": {"process_names": {"telegram.exe"}, "display": "Telegram"},
    "discord": {"process_names": {"discord.exe"}, "display": "Discord"},
    "spotify": {"process_names": {"spotify.exe"}, "display": "Spotify"},
    "obs": {"process_names": {"obs64.exe", "obs32.exe"}, "display": "OBS"},
    "vscode": {"process_names": {"code.exe"}, "display": "VS Code"},
    "cs2": {"process_names": {"cs2.exe", "csgo.exe"}, "display": "Counter-Strike 2"},
    "steam": {"process_names": {"steam.exe"}, "display": "Steam"},
}

ACTIVE_THRESHOLD_SECONDS = 300
PRESENCE_THRESHOLD_SECONDS = 300


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return str(timedelta(seconds=seconds))


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


def _collect_running_apps() -> Dict[str, Dict[str, Any]]:
    running: Dict[str, Dict[str, Any]] = {}
    for proc_info in list_running_processes():
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


def _favorite_entries(state: Dict[str, Any], active_app_key: str, running_apps: Dict[str, Dict[str, Any]]) -> List[str]:
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

        emoji = "▶️" if is_active else ("🟢" if running else "💤")
        display_name = (
            "Браузер"
            if app_key == "browser"
            else app_state.get("last_title") or info.get("display") or DISPLAY_NAMES.get(app_key, app_key)
        )
        entries.append(
            {
                "order": last_active_ts or 0,
                "line": f"{emoji} {display_name}",
            }
        )

    entries.sort(key=lambda item: item["order"], reverse=True)
    return [item["line"] for item in entries]


def build_status_text(state: Dict[str, Any], active_viewer_count: int = 0) -> str:
    uptime_seconds = get_system_uptime_seconds()
    process_info = get_active_process_info()
    process_name = process_info.get("name") or "Unknown"
    title = process_info.get("title")
    app_key, detected_title = _detect_app_key(process_info)
    if app_key == "browser":
        detected_title = None
        title = None
    display_name = resolve_display_name(app_key, process_name, detected_title or title)
    tagline = resolve_tagline(app_key)

    if app_key != "unknown":
        _update_activity(state, app_key, detected_title or title)

    app_uptime_seconds = get_process_uptime_seconds(process_info.get("create_time"))

    parts = [
        f"🖥️ Аптайм ПК: {format_duration(uptime_seconds)}",
        f"⌚ Время в Windows: {get_local_time_string()}",
        f"🪟 Активное приложение: {display_name}",
        f"💬 Приписка: {tagline}",
    ]

    if app_uptime_seconds is not None:
        parts.append(f"⏱️ Аптайм приложения: {format_duration(app_uptime_seconds)}")

    process_count = get_process_count()
    if process_count is not None:
        parts.append(f"🔢 Процессов: {process_count}")

    idle_seconds = get_last_input_idle_seconds()
    is_present = True if idle_seconds is None else idle_seconds < PRESENCE_THRESHOLD_SECONDS
    if is_present:
        parts.append("🟢 За компьютером: я здесь")
    else:
        parts.append("💤 За компьютером: отошёл")

    running_apps = _collect_running_apps()
    favorite_lines = _favorite_entries(state, app_key, running_apps)

    parts.append("")
    parts.append("")
    parts.append("Избранные программы")
    parts.extend(favorite_lines)

    parts.append("")
    parts.append(FOOTER_TEXT)
    if active_viewer_count > 0:
        parts.append(f"👀 Сейчас наблюдают за статусом: {active_viewer_count}")
    else:
        parts.append("😴 Сейчас никто не смотрит")
    return "\n".join(parts)
