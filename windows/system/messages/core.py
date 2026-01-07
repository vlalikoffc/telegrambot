import asyncio
import logging
import time
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import Application

from system.config import GITHUB_URL
from system.state import disable_chat, ensure_chat_state, format_chat_label
from .constants import MAX_EDIT_DELAY


class RateLimiter:
    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_times: Dict[str, float] = {}

    def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def wait(self, action: str, min_interval: float, scope: Optional[str] = None) -> None:
        key = f"{action}:{scope or 'global'}"
        lock = self._get_lock(key)
        async with lock:
            now = time.monotonic()
            last = self._last_times.get(key, 0.0)
            allowed_at = max(last + min_interval, now)
            self._last_times[key] = allowed_at
        delay = allowed_at - now
        if delay > 0:
            await asyncio.sleep(delay)


RATE_LIMITER = RateLimiter()


def _bump_edit_delay(chat_state: Dict[str, Any], retry_after: int, chat_id: int) -> None:
    current = float(chat_state.get("edit_delay", 0.0) or 0.0)
    boosted = max(current, retry_after + 0.5)
    chat_state["edit_delay"] = min(boosted, MAX_EDIT_DELAY)
    logging.warning(
        "Chat %s: rate limit, edit delay %.1fs",
        format_chat_label(chat_id, chat_state),
        chat_state["edit_delay"],
    )


def get_status_keyboard(
    show_button: bool = True, include_hardware: bool = False, is_owner: bool = False
) -> InlineKeyboardMarkup:
    rows = []
    first_row = []
    if show_button:
        first_row.append(InlineKeyboardButton(text="👁 Показать статус", callback_data="show_status"))
    first_row.append(InlineKeyboardButton(text="💻 GitHub проекта", url=GITHUB_URL))
    rows.append(first_row)

    second_row: list[InlineKeyboardButton] = []
    if include_hardware:
        second_row.append(InlineKeyboardButton(text="🖥️ Железо", callback_data="show_hardware"))
    if is_owner:
        second_row.append(InlineKeyboardButton(text="ℹ️ Больше информации", callback_data="viewer_info"))
    if second_row:
        rows.append(second_row)
    return InlineKeyboardMarkup(rows)


def get_viewer_keyboard(include_stats: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_status")]]
    if include_stats:
        rows.append([InlineKeyboardButton(text="📊 Статистика", callback_data="viewer_stats")])
    return InlineKeyboardMarkup(rows)


def get_stats_keyboard(has_prev: bool, has_next: bool, page: int) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(text="◀️", callback_data=f"viewer_stats_page:{page - 1}")
        )
    if has_next:
        nav_row.append(
            InlineKeyboardButton(text="▶️", callback_data=f"viewer_stats_page:{page + 1}")
        )
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_status")])
    return InlineKeyboardMarkup(buttons)


def get_hardware_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_status")]]
    )


async def unpin_all_messages(app: Application, chat_id: int) -> None:
    try:
        await app.bot.unpin_all_chat_messages(chat_id)
        chat_state = ensure_chat_state(app.bot_data.get("state", {}), chat_id)
        logging.info("Chat %s: unpinned all messages", format_chat_label(chat_id, chat_state))
    except TelegramError as exc:
        chat_state = ensure_chat_state(app.bot_data.get("state", {}), chat_id)
        logging.warning(
            "Chat %s: failed to unpin messages: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )
    except Exception as exc:
        chat_state = ensure_chat_state(app.bot_data.get("state", {}), chat_id)
        logging.warning(
            "Chat %s: unexpected unpin error: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )


async def unpin_status_message(
    app: Application,
    chat_id: int,
    message_id: int | None,
    chat_state: Optional[Dict[str, Any]] = None,
) -> None:
    if not message_id:
        return
    try:
        await app.bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
        label = format_chat_label(chat_id, chat_state) if chat_state else str(chat_id)
        logging.info("Chat %s: unpinned old status message %s", label, message_id)
    except TelegramError as exc:
        label = format_chat_label(chat_id, chat_state) if chat_state else str(chat_id)
        logging.warning("Chat %s: failed to unpin message %s: %s", label, message_id, exc)
    except Exception as exc:
        logging.warning(
            "Chat %s: unexpected unpin error for message %s: %s", chat_id, message_id, exc
        )


async def send_restart_notice(
    app: Application, chat_id: int, chat_state: Optional[Dict[str, Any]] = None
) -> None:
    try:
        await RATE_LIMITER.wait("send", 2.0, scope=str(chat_id))
        await app.bot.send_message(chat_id=chat_id, text="♻️ Бот был перезагружен.\nby vlal")
    except RetryAfter as exc:
        label = format_chat_label(chat_id, chat_state) if chat_state else str(chat_id)
        logging.warning("Chat %s: retry after on restart notice: %s", label, exc.retry_after)
    except TelegramError as exc:
        label = format_chat_label(chat_id, chat_state) if chat_state else str(chat_id)
        logging.warning("Chat %s: failed to send restart notice: %s", label, exc)
    except Exception as exc:
        label = format_chat_label(chat_id, chat_state) if chat_state else str(chat_id)
        logging.warning("Chat %s: unexpected restart notice error: %s", label, exc)


async def startup_reset_chat_session(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    hidden_text: str,
    reply_markup: Optional[InlineKeyboardMarkup],
    include_restart_notice: bool,
    state: Optional[Dict[str, Any]] = None,
) -> None:
    await unpin_status_message(app, chat_id, chat_state.get("message_id"), chat_state=chat_state)
    if include_restart_notice:
        await send_restart_notice(app, chat_id, chat_state=chat_state)
    await send_and_pin_status_message(
        app,
        chat_id,
        chat_state,
        hidden_text,
        reply_markup=reply_markup,
        pin=True,
        state=state,
    )


async def send_and_pin_status_message(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    pin: bool = True,
    state: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        await RATE_LIMITER.wait("send", 2.0, scope=str(chat_id))
        message = await app.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )
        chat_state["message_id"] = message.message_id
        chat_state["last_sent_text"] = None
        should_pin = pin and chat_state.get("chat_type") in {"private", "group", "supergroup"}
        if should_pin:
            try:
                await app.bot.pin_chat_message(chat_id=chat_id, message_id=message.message_id)
            except TelegramError as exc:
                logging.warning("Failed to pin message in chat %s: %s", chat_id, exc)
        logging.info(
            "Chat %s: recreated message %s",
            format_chat_label(chat_id, chat_state),
            message.message_id,
        )
    except RetryAfter as exc:
        logging.warning(
            "Chat %s: retry after on send: %s",
            format_chat_label(chat_id, chat_state),
            exc.retry_after,
        )
    except (Forbidden, BadRequest) as exc:
        logging.warning(
            "Chat %s: unrecoverable send error: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )
        disable_chat(state, chat_id)
    except TelegramError as exc:
        logging.exception(
            "Telegram error for chat %s on send: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )
    except Exception as exc:
        logging.exception(
            "Unexpected error for chat %s on send: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )


async def send_or_edit_status_message(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    state: Optional[Dict[str, Any]] = None,
    *,
    skip_rate_limit: bool = False,
    edit_min_interval: float = 5.0,
) -> None:
    lock = _get_chat_lock(chat_id)
    async with lock:
        snapshot_message_id = chat_state.get("message_id")
        snapshot_last_text = chat_state.get("last_sent_text")

    if snapshot_message_id and snapshot_last_text == text:
        logging.info("Chat %s: skip unchanged", format_chat_label(chat_id, chat_state))
        return

    if not snapshot_message_id:
        await send_and_pin_status_message(
            app,
            chat_id,
            chat_state,
            text,
            reply_markup=reply_markup,
            state=state,
        )
        return

    if not skip_rate_limit:
        effective_interval = max(edit_min_interval, float(chat_state.get("edit_delay", 0.0) or 0.0))
        effective_interval = min(max(effective_interval, edit_min_interval), MAX_EDIT_DELAY)
        await RATE_LIMITER.wait("edit", effective_interval, scope=str(chat_id))

    need_send_instead = False
    async with lock:
        message_id = chat_state.get("message_id")
        if not message_id:
            need_send_instead = True
        elif chat_state.get("last_sent_text") == text:
            logging.info("Chat %s: skip unchanged", format_chat_label(chat_id, chat_state))
            return
        else:
            try:
                await app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=reply_markup,
                )
                chat_state["last_sent_text"] = text
                current_delay = float(chat_state.get("edit_delay", 0.0) or 0.0)
                if current_delay > edit_min_interval:
                    chat_state["edit_delay"] = min(
                        max(edit_min_interval, current_delay - 0.5), MAX_EDIT_DELAY
                    )
                logging.info("Chat %s: edited ok", format_chat_label(chat_id, chat_state))
                return
            except RetryAfter as exc:
                _bump_edit_delay(chat_state, exc.retry_after, chat_id)
                return
            except (Forbidden, BadRequest) as exc:
                logging.warning(
                    "Chat %s: unrecoverable edit error: %s",
                    format_chat_label(chat_id, chat_state),
                    exc,
                )
                disable_chat(state, chat_id)
                return
            except TelegramError as exc:
                logging.exception(
                    "Chat %s: edit failed (%s), recreating",
                    format_chat_label(chat_id, chat_state),
                    exc,
                )
                need_send_instead = True
            except Exception as exc:
                logging.exception(
                    "Chat %s: unexpected edit error: %s",
                    format_chat_label(chat_id, chat_state),
                    exc,
                )
                need_send_instead = True

    if need_send_instead:
        await send_and_pin_status_message(
            app, chat_id, chat_state, text, reply_markup=reply_markup, state=state
        )


async def send_status_reply_message(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    state: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    try:
        await RATE_LIMITER.wait("send", 2.0, scope=str(chat_id))
        message = await app.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )
        return message.message_id
    except RetryAfter as exc:
        logging.warning(
            "Chat %s: retry after on send: %s",
            format_chat_label(chat_id, chat_state),
            exc.retry_after,
        )
    except (Forbidden, BadRequest) as exc:
        logging.warning(
            "Chat %s: unrecoverable send error: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )
        disable_chat(state, chat_id)
    except TelegramError as exc:
        logging.exception(
            "Telegram error for chat %s on send: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )
    except Exception as exc:
        logging.exception(
            "Unexpected error for chat %s on send: %s",
            format_chat_label(chat_id, chat_state),
            exc,
        )
    return None


_CHAT_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _CHAT_LOCKS:
        _CHAT_LOCKS[chat_id] = asyncio.Lock()
    return _CHAT_LOCKS[chat_id]
