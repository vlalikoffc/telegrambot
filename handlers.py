import logging
import time
from typing import Any, Dict

from telegram import Update
from telegram.ext import Application, ContextTypes

from config import OWNER_IDS
from messages import (
    get_status_keyboard,
    send_or_edit_status_message,
    send_status_reply_message,
    startup_reset_chat_session,
)
from state import (
    active_viewer_count_global,
    active_viewer_details_global,
    ensure_chat_state,
    prune_expired_viewers,
    save_state,
)
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
    chat_state["last_sent_text"] = None
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

    viewers[key] = {
        "view_start": now,
        "view_expire": now + VIEW_DURATION_SECONDS,
        "username": query.from_user.username if query.from_user else None,
        "name": query.from_user.full_name if query.from_user else None,
    }
    chat_state["status_visible"] = True
    chat_state["enabled"] = True

    text = build_status_text(state, active_viewer_count=active_viewer_count_global(state))
    await send_or_edit_status_message(
        context.application,
        chat_id,
        chat_state,
        text,
        reply_markup=get_status_keyboard(show_button=False),
    )
    await save_state(state)


async def handle_viewer_info_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    user_id = query.from_user.id if query.from_user else None
    chat_id = query.message.chat_id
    if user_id is None:
        await query.answer()
        return
    await query.answer()

    state = context.application.bot_data.get("state")
    if state is None:
        return

    if user_id not in OWNER_IDS:
        await send_status_reply_message(
            context.application,
            chat_id,
            ensure_chat_state(state, chat_id),
            "❌ Недостаточно прав",
        )
        return

    details = active_viewer_details_global(state)
    if not details:
        text = "👀 Детали наблюдателей (0):\n• Сейчас никто не смотрит"
    else:
        lines = []
        for info in details.values():
            username = info.get("username")
            if username:
                lines.append(f"• @{username}")
            else:
                name = info.get("name") or "User (no username)"
                lines.append(f"• {name}")
        text = "\n".join([f"👀 Детали наблюдателей ({len(details)}):", *lines])

    await send_status_reply_message(
        context.application,
        chat_id,
        ensure_chat_state(state, chat_id),
        text,
    )


async def startup_reset_chats(app: Application, preexisting_chat_ids: set[int]) -> None:
    state = app.bot_data.get("state")
    if state is None:
        return

    if app.bot_data.get("startup_reset_done"):
        return

    for chat_id_str, chat_state in state.get("chats", {}).items():
        chat_id = int(chat_id_str)
        if chat_id not in preexisting_chat_ids:
            continue
        if not chat_state.get("enabled"):
            continue
        chat_type = chat_state.get("chat_type")
        if not chat_type:
            try:
                chat = await app.bot.get_chat(chat_id)
                chat_type = chat.type
                chat_state["chat_type"] = chat_type
            except Exception as exc:
                logging.warning("Failed to fetch chat info for %s: %s", chat_id, exc)
                continue
        chat_state["message_id"] = None
        chat_state["last_sent_text"] = None
        chat_state["viewers"] = {}
        chat_state["status_visible"] = False
        text = HIDDEN_STATUS_TEXT
        await startup_reset_chat_session(
            app,
            chat_id,
            chat_state,
            text,
            reply_markup=get_status_keyboard(),
            include_restart_notice=True,
        )

    app.bot_data["startup_reset_done"] = True
    await save_state(state)
