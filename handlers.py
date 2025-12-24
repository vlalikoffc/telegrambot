import logging
import time
from typing import Any, Dict

from telegram import Update
from telegram.ext import Application, ContextTypes

from messages import (
    delete_bot_messages,
    get_status_keyboard,
    purge_chat_history,
    send_and_pin_status_message,
    send_or_edit_status_message,
    send_status_reply_message,
)
from state import active_viewers, ensure_chat_state, prune_expired_viewers, record_message_id, save_state
from status import HIDDEN_STATUS_TEXT, build_status_text

ANTISPAM_SECONDS = 10
VIEW_DURATION_SECONDS = 300


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
    chat_state["viewers"] = {}
    chat_state["status_visible"] = False
    text = HIDDEN_STATUS_TEXT

    if update.effective_chat.type == "private":
        message_id = chat_state.get("message_id")
        if message_id:
            record_message_id(chat_state, message_id)
        message_ids = chat_state.get("message_ids", [])
        if message_ids:
            await delete_bot_messages(context.application, chat_id, message_ids)
        chat_state["message_ids"] = []
        chat_state["message_id"] = None
        await send_and_pin_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=get_status_keyboard(),
        )
    else:
        await send_or_edit_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=get_status_keyboard(),
        )

    _mark_replied(chat_state)
    await save_state(state)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["chat_type"] = update.effective_chat.type
    chat_state["enabled"] = True

    if not _can_reply(chat_state):
        return

    active = active_viewers(chat_state)
    text = build_status_text(state, active_viewer_count=len(active))
    await send_status_reply_message(
        context.application, chat_id, chat_state, text, reply_markup=get_status_keyboard()
    )
    _mark_replied(chat_state)
    await save_state(state)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    chat_state["chat_type"] = update.effective_chat.type
    chat_state["enabled"] = True

    if not _can_reply(chat_state):
        return

    text = HIDDEN_STATUS_TEXT
    await send_or_edit_status_message(
        context.application,
        chat_id,
        chat_state,
        text,
        reply_markup=get_status_keyboard(),
    )
    _mark_replied(chat_state)
    await save_state(state)


async def handle_show_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id if query.from_user else None
    if user_id is None:
        return

    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    prune_expired_viewers(chat_state)

    viewers = chat_state.setdefault("viewers", {})
    now = time.time()
    key = str(user_id)
    current = viewers.get(key)
    if current and current.get("view_expire") and current["view_expire"] > now:
        return

    viewers[key] = {"view_start": now, "view_expire": now + VIEW_DURATION_SECONDS}
    chat_state["status_visible"] = True
    chat_state["enabled"] = True

    text = build_status_text(state, active_viewer_count=len(active_viewers(chat_state)))
    await send_or_edit_status_message(
        context.application,
        chat_id,
        chat_state,
        text,
        reply_markup=get_status_keyboard(),
    )
    await save_state(state)


async def cleanup_chats_on_startup(app: Application) -> None:
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
        include_user_messages = chat_type == "private"
        if chat_state.get("message_id"):
            record_message_id(chat_state, chat_state["message_id"])
        await purge_chat_history(app, chat_id, chat_state, include_user_messages)
        chat_state["message_ids"] = []
        chat_state["message_id"] = None
        chat_state["last_sent_text"] = None
        chat_state["viewers"] = {}
        chat_state["status_visible"] = False
        text = HIDDEN_STATUS_TEXT
        await send_and_pin_status_message(
            app,
            chat_id,
            chat_state,
            text,
            reply_markup=get_status_keyboard(),
        )
    await save_state(state)
