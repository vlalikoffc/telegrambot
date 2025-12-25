import logging
import time
from typing import Any, Dict

from telegram import Update
from telegram.ext import Application, ContextTypes

from analytics import build_stats_text, build_viewers_text, is_owner
from messages import (
    get_status_keyboard,
    get_hardware_keyboard,
    get_stats_keyboard,
    get_viewer_keyboard,
    send_or_edit_status_message,
    send_status_reply_message,
    startup_reset_chat_session,
)
from state import (
    ViewMode,
    active_viewer_count_global,
    active_viewers,
    ensure_chat_state,
    get_view_stats,
    prune_expired_viewers,
    record_view_event,
    save_state,
)
from status import HIDDEN_STATUS_TEXT, build_status_text
from hardware import build_hardware_text
from windows import get_local_date_string

ANTISPAM_SECONDS = 10
VIEW_DURATION_SECONDS = 300


def _spawn(app: Application, coro) -> None:
    async def runner() -> None:
        try:
            await coro
        except Exception:  # pragma: no cover - logged globally
            logging.exception("Callback task failed")

    app.create_task(runner())


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
    chat_state["view_mode"] = ViewMode.STATUS.value
    chat_state["last_sent_text"] = None
    chat_state["stats_page"] = 0
    text = HIDDEN_STATUS_TEXT

    await send_or_edit_status_message(
        context.application,
        chat_id,
        chat_state,
        text,
        reply_markup=get_status_keyboard(is_owner=is_owner(chat_id)),
        state=state,
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
    chat_state["view_mode"] = ViewMode.STATUS.value
    chat_state["stats_page"] = 0

    if not _can_reply(chat_state):
        return

    text = HIDDEN_STATUS_TEXT
    await send_or_edit_status_message(
        context.application,
        chat_id,
        chat_state,
        text,
        reply_markup=get_status_keyboard(is_owner=is_owner(chat_id)),
        state=state,
    )
    _mark_replied(chat_state)
    await save_state(state)


async def handle_show_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()

    async def process() -> None:
        state = context.application.bot_data["state"]
        chat_id = query.message.chat_id
        user_id = query.from_user.id if query.from_user else None
        if user_id is None:
            return

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
        record_view_event(
            state,
            get_local_date_string(),
            user_id,
            query.from_user.username if query.from_user else None,
            query.from_user.full_name if query.from_user else None,
            now,
        )
        chat_state["status_visible"] = True
        chat_state["enabled"] = True
        chat_state["view_mode"] = ViewMode.STATUS.value
        chat_state["stats_page"] = 0

        text = build_status_text(
            state, active_viewer_count=active_viewer_count_global(state)
        )
        await send_or_edit_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=get_status_keyboard(
                show_button=False,
                include_hardware=True,
                is_owner=is_owner(user_id),
            ),
            state=state,
        )
        await save_state(state)

    _spawn(context.application, process())


async def handle_viewer_info_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    user_id = query.from_user.id if query.from_user else None
    chat_id = query.message.chat_id
    await query.answer(text=None)

    async def process() -> None:
        state = context.application.bot_data.get("state")
        if user_id is None or state is None:
            return

        if not is_owner(user_id):
            await query.answer(text="Недостаточно прав", show_alert=True)
            return

        chat_state = ensure_chat_state(state, chat_id)
        prune_expired_viewers(chat_state)
        chat_state["view_mode"] = ViewMode.VIEWERS.value
        chat_state["stats_page"] = 0
        stats = get_view_stats(state, get_local_date_string())
        text = build_viewers_text(stats)
        await send_or_edit_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=get_viewer_keyboard(include_stats=True),
            state=state,
        )
        await save_state(state)

    _spawn(context.application, process())


async def handle_viewer_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer(text=None)

    async def process() -> None:
        user_id = query.from_user.id if query.from_user else None
        chat_id = query.message.chat_id
        state = context.application.bot_data.get("state")
        if user_id is None or state is None:
            return
        if not is_owner(user_id):
            await query.answer(text="Недостаточно прав", show_alert=True)
            return

        chat_state = ensure_chat_state(state, chat_id)
        chat_state["view_mode"] = ViewMode.STATS.value
        stats = get_view_stats(state, get_local_date_string())
        total = max(1, (len(stats.get("users", {})) + 14) // 15)
        page = max(0, min(chat_state.get("stats_page", 0), total - 1))
        chat_state["stats_page"] = page
        text = build_stats_text(stats, page)
        reply_markup = get_stats_keyboard(page > 0, page < total - 1, page)
        await send_or_edit_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=reply_markup,
            state=state,
        )
        await save_state(state)

    _spawn(context.application, process())


async def handle_viewer_stats_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer(text=None)

    async def process() -> None:
        data = query.data or ""
        parts = data.split(":", 1)
        if len(parts) != 2:
            return
        try:
            page = int(parts[1])
        except ValueError:
            return

        user_id = query.from_user.id if query.from_user else None
        chat_id = query.message.chat_id
        state = context.application.bot_data.get("state")
        if user_id is None or state is None:
            return
        if not is_owner(user_id):
            await query.answer(text="Недостаточно прав", show_alert=True)
            return

        chat_state = ensure_chat_state(state, chat_id)
        stats = get_view_stats(state, get_local_date_string())
        total = max(1, (len(stats.get("users", {})) + 14) // 15)
        page = max(0, min(page, total - 1))
        chat_state["view_mode"] = ViewMode.STATS.value
        chat_state["stats_page"] = page
        text = build_stats_text(stats, page)
        reply_markup = get_stats_keyboard(page > 0, page < total - 1, page)
        await send_or_edit_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=reply_markup,
            state=state,
        )
        await save_state(state)

    _spawn(context.application, process())


async def handle_show_hardware(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()

    async def process() -> None:
        chat_id = query.message.chat_id
        state = context.application.bot_data.get("state")
        if state is None:
            return
        chat_state = ensure_chat_state(state, chat_id)
        prune_expired_viewers(chat_state)
        active = active_viewers(chat_state)
        if not active:
            chat_state["status_visible"] = False
            chat_state["view_mode"] = ViewMode.STATUS.value
            await send_or_edit_status_message(
                context.application,
                chat_id,
                chat_state,
                HIDDEN_STATUS_TEXT,
                reply_markup=get_status_keyboard(show_button=True, is_owner=is_owner(chat_id)),
                state=state,
            )
            await save_state(state)
            return

        chat_state["view_mode"] = ViewMode.HARDWARE.value
        text = build_hardware_text()
        await send_or_edit_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=get_hardware_keyboard(),
            state=state,
        )
        await save_state(state)

    _spawn(context.application, process())


async def handle_back_to_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()

    async def process() -> None:
        chat_id = query.message.chat_id
        state = context.application.bot_data.get("state")
        if state is None:
            return
        chat_state = ensure_chat_state(state, chat_id)
        prune_expired_viewers(chat_state)
        active = active_viewers(chat_state)
        chat_state["view_mode"] = ViewMode.STATUS.value
        if not active:
            chat_state["status_visible"] = False
            await send_or_edit_status_message(
                context.application,
                chat_id,
                chat_state,
                HIDDEN_STATUS_TEXT,
                reply_markup=get_status_keyboard(show_button=True, is_owner=is_owner(chat_id)),
                state=state,
            )
            await save_state(state)
            return

        chat_state["status_visible"] = True
        text = build_status_text(
            state, active_viewer_count=active_viewer_count_global(state)
        )
        await send_or_edit_status_message(
            context.application,
            chat_id,
            chat_state,
            text,
            reply_markup=get_status_keyboard(
                show_button=False,
                include_hardware=True,
                is_owner=is_owner(chat_id),
            ),
            state=state,
        )
        await save_state(state)

    _spawn(context.application, process())


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
            reply_markup=get_status_keyboard(is_owner=is_owner(chat_id)),
            include_restart_notice=True,
            state=state,
        )

    app.bot_data["startup_reset_done"] = True
    await save_state(state)
