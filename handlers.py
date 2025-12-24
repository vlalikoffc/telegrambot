import logging
import time
from typing import Any, Dict

from telegram import Update
from telegram.ext import Application, ContextTypes

from messages import delete_bot_messages, send_and_pin_status_message, send_or_edit_status_message
from state import ensure_chat_state, record_message_id, save_state
from status import build_status_text

ANTISPAM_SECONDS = 10


def _can_reply(chat_state: Dict[str, Any]) -> bool:
    last_ts = chat_state.get("last_user_reply_ts")
    if not last_ts:
        return True
    return time.time() - last_ts >= ANTISPAM_SECONDS


def _mark_replied(chat_state: Dict[str, Any]) -> None:
    chat_state["last_user_reply_ts"] = time.time()


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["chat_type"] = update.effective_chat.type
    chat_state["enabled"] = True
    text = build_status_text(state)

    if update.effective_chat.type == "private":
        message_id = chat_state.get("message_id")
        if message_id:
            record_message_id(chat_state, message_id)
        message_ids = chat_state.get("message_ids", [])
        if message_ids:
            await delete_bot_messages(context.application, chat_id, message_ids)
        chat_state["message_ids"] = []
        chat_state["message_id"] = None
        await send_and_pin_status_message(context.application, chat_id, chat_state, text)
    else:
        await send_or_edit_status_message(context.application, chat_id, chat_state, text)

    _mark_replied(chat_state)
    await save_state(state)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["chat_type"] = update.effective_chat.type

    if not _can_reply(chat_state):
        return

    text = build_status_text(state)
    message = await context.application.bot.send_message(chat_id=chat_id, text=text)
    if update.effective_chat.type == "private":
        record_message_id(chat_state, message.message_id)
    _mark_replied(chat_state)
    await save_state(state)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["chat_type"] = update.effective_chat.type

    if not _can_reply(chat_state):
        return

    text = build_status_text(state)
    await send_or_edit_status_message(context.application, chat_id, chat_state, text)
    _mark_replied(chat_state)
    await save_state(state)


async def cleanup_private_chats_on_startup(app: Application) -> None:
    state = app.bot_data.get("state")
    if state is None:
        return
    for chat_id_str, chat_state in state.get("chats", {}).items():
        if not chat_state.get("enabled"):
            continue
        chat_id = int(chat_id_str)
        chat_type = chat_state.get("chat_type")
        if not chat_type:
            try:
                chat = await app.bot.get_chat(chat_id)
                chat_type = chat.type
                chat_state["chat_type"] = chat_type
            except Exception as exc:
                logging.warning("Failed to fetch chat info for %s: %s", chat_id, exc)
                continue
        if chat_type != "private":
            continue
        message_id = chat_state.get("message_id")
        if message_id:
            record_message_id(chat_state, message_id)
        message_ids = chat_state.get("message_ids", [])
        if message_ids:
            await delete_bot_messages(app, chat_id, message_ids)
        chat_state["message_ids"] = []
        chat_state["message_id"] = None
        chat_state["last_sent_text"] = None
        text = build_status_text(state)
        await send_and_pin_status_message(app, chat_id, chat_state, text)
    await save_state(state)
