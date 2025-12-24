import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from handlers import cleanup_private_chats_on_startup, handle_start, handle_status, handle_text
from live_update import live_update_loop
from state import load_state

LOG_FILE = Path(__file__).with_name("bot.log")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )


def build_application() -> Application:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is required in environment or .env")
    application = Application.builder().token(token).build()
    return application


async def on_startup(app: Application) -> None:
    await cleanup_private_chats_on_startup(app)
    app.create_task(live_update_loop(app))


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


def main() -> None:
    load_dotenv()
    configure_logging()

    state = load_state()
    application = build_application()
    application.bot_data["state"] = state
    register_handlers(application)

    application.post_init = on_startup
    application.run_polling()


if __name__ == "__main__":
    main()
