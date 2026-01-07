import asyncio
import logging
import time
from typing import Any, Dict

from telegram import Update
from telegram.ext import Application, ContextTypes

from analytics import (
    add_recent_view,
    build_recent_viewers_text,
    build_stats_text,
    is_owner,
    prune_recent_views,
)
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
from tracker import (
    get_process_list,
    get_running_apps,
    get_snapshot_for_publish,
    init_tracker_state,
)
from live_update import get_update_interval_seconds
from hardware import build_hardware_text
from windows import get_local_date_string

ANTISPAM_SECONDS = 10
VIEW_DURATION_SECONDS = 300
BUTTON_RATE_LIMIT_SECONDS = 2.0

_callback_locks: dict[int, asyncio.Lock] = {}
_UI_BUSY_KEY = "ui_busy_count"


class _UiBusy:
    def __init__(self, app: Application):
        self.app = app

    async def __aenter__(self) -> None:
        current = int(self.app.bot_data.get(_UI_BUSY_KEY, 0))
        self.app.bot_data[_UI_BUSY_KEY] = current + 1

    async def __aexit__(self, exc_type, exc, tb) -> None:
        current = int(self.app.bot_data.get(_UI_BUSY_KEY, 0))
        next_val = max(0, current - 1)
        self.app.bot_data[_UI_BUSY_KEY] = next_val


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


def _log_view_change(chat_id: int, old: str, new: str) -> None:
    if old == new:
        return
    logging.info("Chat %s: View change: %s -> %s", chat_id, old, new)


def _get_recent_views(bot_data: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    views = bot_data.setdefault("recent_views", {})
    cleaned = prune_recent_views(views)
    bot_data["recent_views"] = cleaned
    return cleaned


def _get_callback_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _callback_locks:
        _callback_locks[chat_id] = asyncio.Lock()
    return _callback_locks[chat_id]


def _rate_limited_button(chat_state: Dict[str, Any], user_id: int) -> bool:
    last_map = chat_state.setdefault("last_button_ts", {})
    now = time.time()
    last = float(last_map.get(str(user_id), 0))
    if now - last < BUTTON_RATE_LIMIT_SECONDS:
        return True
    last_map[str(user_id)] = now
    return False


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
    chat_id = query.message.chat_id
    user_id = query.from_user.id if query.from_user else None
    logging.info("Callback received: SHOW_STATUS (chat=%s, user=%s)", chat_id, user_id)
    state = context.application.bot_data["state"]
    chat_state = ensure_chat_state(state, chat_id)
    if user_id is None:
        await query.answer()
        return
    rate_limited = _rate_limited_button(chat_state, user_id)
    if rate_limited:
        await query.answer(text="⏳ Подожди секунду", show_alert=False)
        return
    await query.answer()

    lock = _get_callback_lock(chat_id)
    if lock.locked():
        logging.info("Chat %s: callback ignored (lock busy)", chat_id)
        return

    async def process() -> None:
        start_ts = time.monotonic()
        lock_inner = _get_callback_lock(chat_id)
        async with lock_inner:
            prune_expired_viewers(chat_state)
            if chat_state.get("view_mode") == ViewMode.HARDWARE.value:
                logging.info("Chat %s: callback ignored (hardware view active)", chat_id)
                return

            viewers = chat_state.setdefault("viewers", {})
            now_ts = time.time()
            key = str(user_id)
            current = viewers.get(key)
            if current and current.get("view_expire") and current["view_expire"] > now_ts:
                return

            viewers[key] = {
                "view_start": now_ts,
                "view_expire": now_ts + VIEW_DURATION_SECONDS,
                "username": query.from_user.username if query.from_user else None,
                "name": query.from_user.full_name if query.from_user else None,
                "stats_date": get_local_date_string(),
            }
            record_view_event(
                state,
                get_local_date_string(),
                user_id,
                query.from_user.username if query.from_user else None,
                query.from_user.full_name if query.from_user else None,
                now_ts,
            )
            add_recent_view(
                _get_recent_views(context.application.bot_data),
                user_id,
                query.from_user.username if query.from_user else None,
                query.from_user.full_name if query.from_user else None,
                now_ts,
            )
            chat_state["status_visible"] = True
            chat_state["enabled"] = True
            _log_view_change(chat_id, chat_state.get("view_mode"), ViewMode.STATUS.value)
            chat_state["view_mode"] = ViewMode.STATUS.value
            chat_state["stats_page"] = 0

            tracker = init_tracker_state(context.application.bot_data)
            snapshot = get_snapshot_for_publish(tracker)
            viewer_count = active_viewer_count_global(state)
            update_interval = get_update_interval_seconds(viewer_count)
            text = build_status_text(
                state,
                snapshot,
                active_viewer_count=viewer_count,
                update_interval_seconds=update_interval,
                running_apps=get_running_apps(tracker),
                process_list=get_process_list(tracker),
            )
            reply_markup = get_status_keyboard(
                show_button=False,
                include_hardware=True,
                is_owner=is_owner(user_id),
            )

        chat_state["callback_in_progress"] = True
        logging.info("Callback EDIT start (SHOW_STATUS)")
        try:
            async with _UiBusy(context.application):
                await send_or_edit_status_message(
                    context.application,
                    chat_id,
                    chat_state,
                    text,
                    reply_markup=reply_markup,
                    state=state,
                    skip_rate_limit=True,
                )
        finally:
            chat_state["callback_in_progress"] = False
            logging.info("Callback EDIT end (SHOW_STATUS)")
            logging.info(
                "Callback processed in %.2fs (SHOW_STATUS)", time.monotonic() - start_ts
            )
        await save_state(state)

    _spawn(context.application, process())


async def handle_viewer_info_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    user_id = query.from_user.id if query.from_user else None
    chat_id = query.message.chat_id
    state = context.application.bot_data.get("state")
    chat_state = ensure_chat_state(state, chat_id) if state else None
    logging.info("Callback received: VIEWER_INFO (chat=%s, user=%s)", chat_id, user_id)
    rate_limited = bool(chat_state and user_id is not None and _rate_limited_button(chat_state, user_id))
    unauthorized = user_id is None or not is_owner(user_id)
    await query.answer(
        text="⏳ Подожди секунду" if rate_limited else ("Недостаточно прав" if unauthorized else None),
        show_alert=unauthorized,
    )
    if rate_limited or unauthorized:
        return

    lock = _get_callback_lock(chat_id)
    if lock.locked():
        logging.info("Chat %s: callback ignored (lock busy)", chat_id)
        return

    async def process() -> None:
        state_inner = context.application.bot_data.get("state")
        if user_id is None or state_inner is None:
            return

        chat_state_inner = ensure_chat_state(state_inner, chat_id)
        lock_inner = _get_callback_lock(chat_id)
        async with lock_inner:
            prune_expired_viewers(chat_state_inner)
            chat_state_inner["view_mode"] = ViewMode.VIEWERS.value
            chat_state_inner["stats_page"] = 0
            recent_views = _get_recent_views(context.application.bot_data)
            text = build_recent_viewers_text(recent_views)
            reply_markup = get_viewer_keyboard(include_stats=True)

        chat_state_inner["callback_in_progress"] = True
        logging.info("Callback EDIT start (VIEWER_INFO)")
        start_ts = time.monotonic()
        try:
            async with _UiBusy(context.application):
                await send_or_edit_status_message(
                    context.application,
                    chat_id,
                    chat_state_inner,
                    text,
                    reply_markup=reply_markup,
                    state=state_inner,
                    skip_rate_limit=True,
                )
        finally:
            chat_state_inner["callback_in_progress"] = False
            logging.info("Callback EDIT end (VIEWER_INFO)")
            logging.info(
                "Callback processed in %.2fs (VIEWER_INFO)",
                time.monotonic() - start_ts,
            )
        await save_state(state_inner)

    _spawn(context.application, process())


async def handle_viewer_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    chat_id = query.message.chat_id
    user_id = query.from_user.id if query.from_user else None
    state = context.application.bot_data.get("state")
    chat_state = ensure_chat_state(state, chat_id) if state else None
    logging.info("Callback received: VIEWER_STATS (chat=%s, user=%s)", chat_id, user_id)
    rate_limited = bool(chat_state and user_id is not None and _rate_limited_button(chat_state, user_id))
    unauthorized = user_id is None or not is_owner(user_id)
    await query.answer(
        text="⏳ Подожди секунду" if rate_limited else ("Недостаточно прав" if unauthorized else None),
        show_alert=unauthorized,
    )
    if rate_limited or unauthorized:
        return

    lock = _get_callback_lock(chat_id)
    if lock.locked():
        logging.info("Chat %s: callback ignored (lock busy)", chat_id)
        return

    async def process() -> None:
        user_inner = query.from_user.id if query.from_user else None
        chat_id_inner = query.message.chat_id
        state_inner = context.application.bot_data.get("state")
        if user_inner is None or state_inner is None:
            return
        chat_state_inner = ensure_chat_state(state_inner, chat_id_inner)
        lock_inner = _get_callback_lock(chat_id_inner)
        async with lock_inner:
            chat_state_inner["view_mode"] = ViewMode.STATS.value
            stats = get_view_stats(state_inner, get_local_date_string())
            total = max(1, (len(stats.get("users", {})) + 14) // 15)
            page = max(0, min(chat_state_inner.get("stats_page", 0), total - 1))
            chat_state_inner["stats_page"] = page
            text = build_stats_text(stats, page)
            reply_markup = get_stats_keyboard(page > 0, page < total - 1, page)

        chat_state_inner["callback_in_progress"] = True
        logging.info("Callback EDIT start (VIEWER_STATS)")
        start_ts = time.monotonic()
        try:
            async with _UiBusy(context.application):
                await send_or_edit_status_message(
                    context.application,
                    chat_id_inner,
                    chat_state_inner,
                    text,
                    reply_markup=reply_markup,
                    state=state_inner,
                    skip_rate_limit=True,
                )
        finally:
            chat_state_inner["callback_in_progress"] = False
            logging.info("Callback EDIT end (VIEWER_STATS)")
            logging.info(
                "Callback processed in %.2fs (VIEWER_STATS)",
                time.monotonic() - start_ts,
            )
        await save_state(state_inner)

    _spawn(context.application, process())


async def handle_viewer_stats_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    chat_id = query.message.chat_id
    user_id = query.from_user.id if query.from_user else None
    state = context.application.bot_data.get("state")
    chat_state = ensure_chat_state(state, chat_id) if state else None
    logging.info("Callback received: VIEWER_STATS_PAGE (chat=%s, user=%s)", chat_id, user_id)
    rate_limited = bool(chat_state and user_id is not None and _rate_limited_button(chat_state, user_id))
    unauthorized = user_id is None or not is_owner(user_id)
    await query.answer(
        text="⏳ Подожди секунду" if rate_limited else ("Недостаточно прав" if unauthorized else None),
        show_alert=unauthorized,
    )
    if rate_limited or unauthorized:
        return

    lock = _get_callback_lock(chat_id)
    if lock.locked():
        logging.info("Chat %s: callback ignored (lock busy)", chat_id)
        return

    async def process() -> None:
        data = query.data or ""
        parts = data.split(":", 1)
        if len(parts) != 2:
            return
        try:
            page = int(parts[1])
        except ValueError:
            return

        user_inner = query.from_user.id if query.from_user else None
        chat_id_inner = query.message.chat_id
        state_inner = context.application.bot_data.get("state")
        if user_inner is None or state_inner is None:
            return
        chat_state_inner = ensure_chat_state(state_inner, chat_id_inner)
        lock_inner = _get_callback_lock(chat_id_inner)
        async with lock_inner:
            stats = get_view_stats(state_inner, get_local_date_string())
            total = max(1, (len(stats.get("users", {})) + 14) // 15)
            page_inner = max(0, min(page, total - 1))
            chat_state_inner["view_mode"] = ViewMode.STATS.value
            chat_state_inner["stats_page"] = page_inner
            text = build_stats_text(stats, page_inner)
            reply_markup = get_stats_keyboard(page_inner > 0, page_inner < total - 1, page_inner)

        chat_state_inner["callback_in_progress"] = True
        logging.info("Callback EDIT start (VIEWER_STATS_PAGE)")
        start_ts = time.monotonic()
        try:
            async with _UiBusy(context.application):
                await send_or_edit_status_message(
                    context.application,
                    chat_id_inner,
                    chat_state_inner,
                    text,
                    reply_markup=reply_markup,
                    state=state_inner,
                    skip_rate_limit=True,
                )
        finally:
            chat_state_inner["callback_in_progress"] = False
            logging.info("Callback EDIT end (VIEWER_STATS_PAGE)")
            logging.info(
                "Callback processed in %.2fs (VIEWER_STATS_PAGE)",
                time.monotonic() - start_ts,
            )
        await save_state(state_inner)

    _spawn(context.application, process())


async def handle_show_hardware(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    chat_id = query.message.chat_id
    user_id = query.from_user.id if query.from_user else None
    state = context.application.bot_data.get("state")
    chat_state = ensure_chat_state(state, chat_id) if state else None
    logging.info("Callback received: SHOW_HARDWARE (chat=%s, user=%s)", chat_id, user_id)
    rate_limited = bool(chat_state and user_id is not None and _rate_limited_button(chat_state, user_id))
    await query.answer(text="⏳ Подожди секунду" if rate_limited else None, show_alert=False)
    if rate_limited:
        return

    lock = _get_callback_lock(chat_id)
    if lock.locked():
        logging.info("Chat %s: callback ignored (lock busy)", chat_id)
        return

    async def process() -> None:
        state_inner = context.application.bot_data.get("state")
        if state_inner is None:
            return
        chat_state_inner = ensure_chat_state(state_inner, chat_id)
        lock_inner = _get_callback_lock(chat_id)
        async with lock_inner:
            if chat_state_inner.get("view_mode") == ViewMode.HARDWARE.value:
                logging.info("Chat %s: Hardware view already active", chat_id)
                return
            if chat_state_inner.get("view_mode") != ViewMode.STATUS.value:
                logging.info(
                    "Chat %s: callback ignored (view=%s)",
                    chat_id,
                    chat_state_inner.get("view_mode"),
                )
                return
            old_view = chat_state_inner.get("view_mode")
            _log_view_change(chat_id, old_view, ViewMode.HARDWARE.value)
            chat_state_inner["view_mode"] = ViewMode.HARDWARE.value
            text = build_hardware_text()
            reply_markup = get_hardware_keyboard()

        chat_state_inner["callback_in_progress"] = True
        logging.info("Callback EDIT start (SHOW_HARDWARE)")
        start_ts = time.monotonic()
        try:
            async with _UiBusy(context.application):
                await send_or_edit_status_message(
                    context.application,
                    chat_id,
                    chat_state_inner,
                    text,
                    reply_markup=reply_markup,
                    state=state_inner,
                    skip_rate_limit=True,
                )
        finally:
            chat_state_inner["callback_in_progress"] = False
            logging.info("Callback EDIT end (SHOW_HARDWARE)")
            logging.info(
                "Callback processed in %.2fs (SHOW_HARDWARE)",
                time.monotonic() - start_ts,
            )
        await save_state(state_inner)

    _spawn(context.application, process())


async def handle_back_to_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    chat_id = query.message.chat_id
    user_id = query.from_user.id if query.from_user else None
    state = context.application.bot_data.get("state")
    chat_state = ensure_chat_state(state, chat_id) if state else None
    logging.info("Callback received: BACK_TO_STATUS (chat=%s, user=%s)", chat_id, user_id)
    await query.answer()

    async def process() -> None:
        state_inner = context.application.bot_data.get("state")
        if state_inner is None:
            return
        chat_state_inner = ensure_chat_state(state_inner, chat_id)
        prune_expired_viewers(chat_state_inner)
        active = active_viewers(chat_state_inner)
        old_view = chat_state_inner.get("view_mode")
        _log_view_change(chat_id, old_view, ViewMode.STATUS.value)
        chat_state_inner["view_mode"] = ViewMode.STATUS.value
        if not active:
            chat_state_inner["status_visible"] = False
            text = HIDDEN_STATUS_TEXT
            reply_markup = get_status_keyboard(show_button=True, is_owner=is_owner(chat_id))
        else:
            chat_state_inner["status_visible"] = True
            tracker = init_tracker_state(context.application.bot_data)
            snapshot = get_snapshot_for_publish(tracker)
            viewer_count = active_viewer_count_global(state_inner)
            update_interval = get_update_interval_seconds(viewer_count)
            text = build_status_text(
                state_inner,
                snapshot,
                active_viewer_count=viewer_count,
                update_interval_seconds=update_interval,
                running_apps=get_running_apps(tracker),
                process_list=get_process_list(tracker),
            )
            reply_markup = get_status_keyboard(
                show_button=False,
                include_hardware=True,
                is_owner=is_owner(chat_id),
            )

        chat_state_inner["callback_in_progress"] = True
        logging.info("Callback EDIT start (BACK_TO_STATUS)")
        logging.info("BACK_TO_STATUS forced transition executed (chat=%s)", chat_id)
        start_ts = time.monotonic()
        try:
            async with _UiBusy(context.application):
                await send_or_edit_status_message(
                    context.application,
                    chat_id,
                    chat_state_inner,
                    text,
                    reply_markup=reply_markup,
                    state=state_inner,
                    skip_rate_limit=True,
                )
        finally:
            chat_state_inner["callback_in_progress"] = False
            logging.info("Callback EDIT end (BACK_TO_STATUS)")
            logging.info(
                "Callback processed in %.2fs (BACK_TO_STATUS)",
                time.monotonic() - start_ts,
            )
        await save_state(state_inner)

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
