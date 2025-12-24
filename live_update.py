import asyncio
import logging
from typing import Any, Dict

from telegram.ext import Application

from messages import send_or_edit_status_message
from state import save_state
from status import build_status_text


def _should_pin(chat_state: Dict[str, Any]) -> bool:
    return chat_state.get("chat_type") == "private"


async def update_status_for_chat(
    app: Application, chat_id: int, chat_state: Dict[str, Any], text: str
) -> None:
    logging.info("Chat %s: tick", chat_id)
    if not chat_state.get("message_id") and _should_pin(chat_state):
        # Will be created by send_or_edit_status_message
        pass
    await send_or_edit_status_message(app, chat_id, chat_state, text)


async def update_live_status_for_app(app: Application) -> None:
    state = app.bot_data.get("state")
    if state is None:
        return
    try:
        text = build_status_text(state)
    except Exception as exc:
        logging.exception("Failed to build status text: %s", exc)
        return
    for chat_id_str, chat_state in state.get("chats", {}).items():
        if not chat_state.get("enabled"):
            continue
        chat_id = int(chat_id_str)
        try:
            await update_status_for_chat(app, chat_id, chat_state, text)
        except Exception as exc:
            logging.exception("Chat %s: loop error: %s", chat_id, exc)
            continue
    await save_state(state)


async def live_update_loop(app: Application) -> None:
    logging.info("Live update loop started")
    while True:
        try:
            await update_live_status_for_app(app)
        except Exception as exc:
            logging.exception("Live update loop error: %s", exc)
        await asyncio.sleep(1)
