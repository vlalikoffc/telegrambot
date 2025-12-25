import asyncio
import contextlib
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from handlers import (
    handle_show_status_button,
    handle_show_hardware,
    handle_back_to_status,
    handle_start,
    handle_text,
    handle_viewer_info_button,
    handle_viewer_stats,
    handle_viewer_stats_page,
    startup_reset_chats,
)
from live_update import live_update_loop
from hardware import init_hardware_cache
from state import load_state

LOG_FILE = Path(__file__).with_name("bot.log")
LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )
    # Silence verbose HTTP logs like "200 OK" while keeping warnings/errors.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_application() -> Application:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is required in environment or .env")
    application = Application.builder().token(token).build()
    return application


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CallbackQueryHandler(handle_show_status_button, pattern="^show_status$"))
    application.add_handler(CallbackQueryHandler(handle_show_hardware, pattern="^show_hardware$"))
    application.add_handler(CallbackQueryHandler(handle_back_to_status, pattern="^back_to_status$"))
    application.add_handler(CallbackQueryHandler(handle_viewer_info_button, pattern="^viewer_info$"))
    application.add_handler(CallbackQueryHandler(handle_viewer_stats, pattern="^viewer_stats$"))
    application.add_handler(
        CallbackQueryHandler(handle_viewer_stats_page, pattern=r"^viewer_stats_page:(.+)$")
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


async def main_async() -> None:
    load_dotenv()
    init_hardware_cache()
    configure_logging()
    LOGGER.info("Starting Telegram PC Status Bot (polling mode)")

    state = load_state()
    preexisting_chat_ids = set(int(cid) for cid in state.get("chats", {}).keys())
    application = build_application()
    application.bot_data["state"] = state
    register_handlers(application)

    await application.initialize()
    await startup_reset_chats(application, preexisting_chat_ids)

    live_task = None
    try:
        await application.start()
        await application.updater.start_polling()
        live_task = asyncio.create_task(live_update_loop(application))
        wait_call = getattr(application.updater, "wait", None)
        if wait_call:
            await wait_call()
        else:
            stop_event = asyncio.Event()
            await stop_event.wait()
    finally:
        if live_task:
            live_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await live_task
        await application.stop()
        await application.shutdown()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
