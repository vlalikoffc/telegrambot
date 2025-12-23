import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
import win32gui
import win32process
from dotenv import load_dotenv
from telegram import Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

STATE_FILE = Path(__file__).with_name("state.json")
STATE_LOCK = asyncio.Lock()

FOOTER_TEXT = (
    "вот чё я делаю, но не следите пж за мной 24/7(мой юз в тг @vlalikoffc)"
)

PROCESS_ALIASES = {
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

PROCESS_COUNT_REFRESH_SECONDS = 10


@dataclass
class ProcessCountCache:
    count: Optional[int] = None
    updated_at: float = 0.0


process_count_cache = ProcessCountCache()


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return str(timedelta(seconds=seconds))


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {"chats": {}}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "chats" not in data:
            data["chats"] = {}
        return data
    except (OSError, json.JSONDecodeError):
        return {"chats": {}}


async def save_state(state: Dict[str, Any]) -> None:
    async with STATE_LOCK:
        with STATE_FILE.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)


def get_process_count() -> Optional[int]:
    now = time.time()
    if now - process_count_cache.updated_at >= PROCESS_COUNT_REFRESH_SECONDS:
        try:
            process_count_cache.count = len(psutil.pids())
        except Exception:
            process_count_cache.count = None
        process_count_cache.updated_at = now
    return process_count_cache.count


def get_active_process_info() -> Dict[str, Any]:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return {"name": "Unknown", "pid": None, "create_time": None}
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return {"name": "Unknown", "pid": None, "create_time": None}
        proc = psutil.Process(pid)
        return {
            "name": proc.name(),
            "pid": pid,
            "create_time": proc.create_time(),
        }
    except Exception:
        return {"name": "Unknown", "pid": None, "create_time": None}


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
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_seconds = (datetime.now() - boot_time).total_seconds()

    process_info = get_active_process_info()
    process_name = process_info.get("name") or "Unknown"
    app_key = resolve_app_key(process_name)
    display_name = resolve_display_name(app_key, process_name)
    tagline = resolve_tagline(app_key)

    app_uptime_seconds = None
    if process_info.get("create_time"):
        app_uptime_seconds = time.time() - process_info["create_time"]

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


def ensure_chat_state(state: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
    chats = state.setdefault("chats", {})
    chat_state = chats.setdefault(
        str(chat_id),
        {
            "enabled": False,
            "message_id": None,
            "last_sent_text": None,
            "backoff_until": None,
        },
    )
    return chat_state


async def send_or_edit_message(
    app: Application, chat_id: int, chat_state: Dict[str, Any], text: str
) -> None:
    if chat_state.get("last_sent_text") == text:
        return
    now = time.time()
    backoff_until = chat_state.get("backoff_until")
    if backoff_until and now < backoff_until:
        return
    try:
        message_id = chat_state.get("message_id")
        if message_id:
            await app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
            )
        else:
            message = await app.bot.send_message(chat_id=chat_id, text=text)
            chat_state["message_id"] = message.message_id
        chat_state["last_sent_text"] = text
        chat_state["backoff_until"] = None
    except RetryAfter as exc:
        chat_state["backoff_until"] = time.time() + exc.retry_after
        logging.warning("Rate limited for chat %s, backing off %s sec", chat_id, exc.retry_after)
    except TelegramError as exc:
        logging.exception("Telegram error for chat %s: %s", chat_id, exc)
    except Exception as exc:
        logging.exception("Unexpected error for chat %s: %s", chat_id, exc)


async def update_live_status_for_app(app: Application) -> None:
    state = app.bot_data.get("state")
    if state is None:
        return
    text = build_status_text()
    for chat_id_str, chat_state in state.get("chats", {}).items():
        if not chat_state.get("enabled"):
            continue
        await send_or_edit_message(app, int(chat_id_str), chat_state, text)
    await save_state(state)


async def live_update_loop(app: Application) -> None:
    while True:
        await update_live_status_for_app(app)
        await asyncio.sleep(1)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["enabled"] = True
    text = build_status_text()
    await send_or_edit_message(context.application, chat_id, chat_state, text)
    await save_state(state)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    text = build_status_text()
    await context.application.bot.send_message(chat_id=chat_id, text=text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_start(update, context)


async def bootstrap_default_chat(app: Application, default_chat_id: Optional[str]) -> None:
    if not default_chat_id:
        return
    try:
        chat_id = int(default_chat_id)
    except ValueError:
        logging.error("DEFAULT_CHAT_ID must be an integer, got: %s", default_chat_id)
        return
    state = app.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["enabled"] = True
    text = build_status_text()
    await send_or_edit_message(app, chat_id, chat_state, text)
    await save_state(state)


async def on_startup(app: Application) -> None:
    default_chat_id = os.getenv("DEFAULT_CHAT_ID")
    await bootstrap_default_chat(app, default_chat_id)
    app.create_task(live_update_loop(app))


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is required in environment or .env")

    state = load_state()

    application = Application.builder().token(token).post_init(on_startup).build()
    application.bot_data["state"] = state

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_polling()


if __name__ == "__main__":
    main()
