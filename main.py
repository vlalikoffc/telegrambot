import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from handlers import cleanup_private_chats_on_startup, handle_start, handle_status, handle_text
from live_update import live_update_loop
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


async def on_startup(app: Application) -> None:
    LOGGER.info("Startup: cleaning private chats and launching live update loop")
    await cleanup_private_chats_on_startup(app)
    app.create_task(live_update_loop(app))


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


def main() -> None:
    load_dotenv()
    configure_logging()
    LOGGER.info("Starting Telegram PC Status Bot (polling mode)")

    state = load_state()
    application = build_application()
    application.bot_data["state"] = state
    register_handlers(application)

    application.post_init = on_startup
    application.run_polling()


if __name__ == "__main__":
    main()
