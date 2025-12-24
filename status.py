from datetime import timedelta
from typing import Dict

from windows import (
    get_active_process_info,
    get_process_count,
    get_process_uptime_seconds,
    get_system_uptime_seconds,
)

FOOTER_TEXT = (
    "вот чё я делаю, но не следите пж за мной 24/7(мой юз в тг @vlalikoffc)"
)

PROCESS_ALIASES: Dict[str, str] = {
    "chrome.exe": "chrome",
    "msedge.exe": "browser",
    "firefox.exe": "browser",
    "code.exe": "vscode",
    "telegram.exe": "telegram",
    "cs2.exe": "cs2",
    "steam.exe": "steam",
    "discord.exe": "discord",
}

DISPLAY_NAMES = {
    "chrome": "Chrome",
    "browser": "Браузер",
    "vscode": "VS Code",
    "telegram": "Telegram",
    "cs2": "Counter-Strike 2",
    "steam": "Steam",
    "discord": "Discord",
    "unknown": "Unknown",
}

BROWSER_PROCESS_NAMES = {
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
}

TAGLINES = {
    "chrome": "сижу просто так в интернете",
    "browser": "сижу просто так в интернете",
    "vscode": "страдаю хернёй (программирую)",
    "telegram": "залип в телеге",
    "cs2": "бегу на B",
    "steam": "катаю через Steam",
    "discord": "залип в дискорде",
    "default": "живу жизнь",
}


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return str(timedelta(seconds=seconds))


def resolve_app_key(process_name: str) -> str:
    if not process_name:
        return "unknown"
    normalized = process_name.lower()
    return PROCESS_ALIASES.get(normalized, "unknown")


def resolve_display_name(app_key: str, process_name: str) -> str:
    if app_key != "unknown":
        if app_key == "browser":
            lower_name = process_name.lower()
            if lower_name in BROWSER_PROCESS_NAMES:
                return BROWSER_PROCESS_NAMES[lower_name]
        return DISPLAY_NAMES.get(app_key, process_name)
    if process_name:
        return process_name.replace(".exe", "").strip() or "Unknown"
    return "Unknown"


def resolve_tagline(app_key: str) -> str:
    return TAGLINES.get(app_key, TAGLINES["default"])


def build_status_text() -> str:
    uptime_seconds = get_system_uptime_seconds()
    process_info = get_active_process_info()
    process_name = process_info.get("name") or "Unknown"
    app_key = resolve_app_key(process_name)
    display_name = resolve_display_name(app_key, process_name)
    tagline = resolve_tagline(app_key)

    app_uptime_seconds = get_process_uptime_seconds(process_info.get("create_time"))

    parts = [
        f"🖥️ Аптайм ПК: {format_duration(uptime_seconds)}",
        f"🪟 Активное приложение: {display_name}",
        f"💬 Приписка: {tagline}",
    ]

    if app_uptime_seconds is not None:
        parts.append(f"⏱️ Аптайм приложения: {format_duration(app_uptime_seconds)}")

    process_count = get_process_count()
    if process_count is not None:
        parts.append(f"🔢 Процессов: {process_count}")

    parts.append("")
    parts.append(FOOTER_TEXT)
    return "\n".join(parts)
