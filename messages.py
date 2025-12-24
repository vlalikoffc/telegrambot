import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter, TelegramError
from telegram.ext import Application

from state import record_message_id


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


def _set_backoff(chat_state: Dict[str, Any], retry_after: int, reason: str, chat_id: int) -> None:
    chat_state["backoff_until"] = time.time() + retry_after + 1
    logging.warning("Chat %s: backoff %s sec (%s)", chat_id, retry_after, reason)


async def delete_bot_messages(
    app: Application, chat_id: int, message_ids: List[int]
) -> None:
    for message_id in message_ids:
        await _delete_message(app, chat_id, message_id)


async def _delete_message(app: Application, chat_id: int, message_id: int) -> None:
    await RATE_LIMITER.wait("delete", 2.0, scope=str(chat_id))
    try:
        await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError as exc:
        logging.warning(
            "Failed to delete message %s in chat %s: %s", message_id, chat_id, exc
        )
    except Exception as exc:
        logging.warning(
            "Unexpected error while deleting message %s in chat %s: %s",
            message_id,
            chat_id,
            exc,
        )


def get_status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="👁 Показать статус", callback_data="show_status")]]
    )


async def send_and_pin_status_message(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    try:
        await RATE_LIMITER.wait("send", 2.0, scope=str(chat_id))
        message = await app.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )
        chat_state["message_id"] = message.message_id
        chat_state["last_sent_text"] = None
        chat_state["backoff_until"] = None
        chat_state["message_ids"] = []
        record_message_id(chat_state, message.message_id)
        should_pin = chat_state.get("chat_type") in {"private", "group", "supergroup"}
        if should_pin:
            try:
                await app.bot.pin_chat_message(chat_id=chat_id, message_id=message.message_id)
            except TelegramError as exc:
                logging.warning("Failed to pin message in chat %s: %s", chat_id, exc)
        logging.info("Chat %s: recreated message %s", chat_id, message.message_id)
    except RetryAfter as exc:
        _set_backoff(chat_state, exc.retry_after, "send", chat_id)
    except TelegramError as exc:
        logging.exception("Telegram error for chat %s on send: %s", chat_id, exc)
    except Exception as exc:
        logging.exception("Unexpected error for chat %s on send: %s", chat_id, exc)


async def send_or_edit_status_message(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    lock = _get_chat_lock(chat_id)
    async with lock:
        now = time.time()
        backoff_until = chat_state.get("backoff_until")
        if backoff_until and now < backoff_until:
            remaining = max(0, int(backoff_until - now))
            logging.info("Chat %s: backoff %s sec", chat_id, remaining)
            return
        if chat_state.get("last_sent_text") == text:
            logging.info("Chat %s: skip unchanged", chat_id)
            return

        message_id = chat_state.get("message_id")
        if not message_id:
            await send_and_pin_status_message(
                app,
                chat_id,
                chat_state,
                text,
                reply_markup=reply_markup,
            )
            return

        try:
            await RATE_LIMITER.wait("edit", 5.0, scope=str(chat_id))
            await app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            chat_state["last_sent_text"] = text
            chat_state["backoff_until"] = None
            logging.info("Chat %s: edited ok", chat_id)
        except RetryAfter as exc:
            _set_backoff(chat_state, exc.retry_after, "edit", chat_id)
        except TelegramError as exc:
            logging.exception("Chat %s: edit failed (%s), recreating", chat_id, exc)
            await send_and_pin_status_message(
                app, chat_id, chat_state, text, reply_markup=reply_markup
            )
        except Exception as exc:
            logging.exception("Chat %s: unexpected edit error: %s", chat_id, exc)
            await send_and_pin_status_message(
                app, chat_id, chat_state, text, reply_markup=reply_markup
            )


async def send_status_reply_message(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[int]:
    try:
        await RATE_LIMITER.wait("send", 2.0, scope=str(chat_id))
        message = await app.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )
        if chat_state.get("chat_type") == "private":
            record_message_id(chat_state, message.message_id)
        return message.message_id
    except RetryAfter as exc:
        _set_backoff(chat_state, exc.retry_after, "send", chat_id)
    except TelegramError as exc:
        logging.exception("Telegram error for chat %s on send: %s", chat_id, exc)
    except Exception as exc:
        logging.exception("Unexpected error for chat %s on send: %s", chat_id, exc)
    return None


async def purge_chat_history(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    include_user_messages: bool,
    recent_limit: int = 50,
) -> None:
    ids_to_delete = set(chat_state.get("message_ids", []) or [])
    if chat_state.get("message_id"):
        ids_to_delete.add(chat_state["message_id"])
    if ids_to_delete:
        await delete_bot_messages(app, chat_id, list(ids_to_delete))

    if not include_user_messages:
        return

    probe_message_id: Optional[int] = None
    try:
        await RATE_LIMITER.wait("send", 2.0, scope=str(chat_id))
        probe = await app.bot.send_message(
            chat_id=chat_id, text="\u2060", disable_notification=True
        )
        probe_message_id = probe.message_id
    except TelegramError as exc:
        logging.warning("Failed to create probe message for chat %s: %s", chat_id, exc)
    except Exception as exc:
        logging.warning("Unexpected probe error for chat %s: %s", chat_id, exc)

    if probe_message_id:
        start_id = probe_message_id
        end_id = max(1, probe_message_id - recent_limit)
        for message_id in range(start_id, end_id - 1, -1):
            await _delete_message(app, chat_id, message_id)


_CHAT_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _CHAT_LOCKS:
        _CHAT_LOCKS[chat_id] = asyncio.Lock()
    return _CHAT_LOCKS[chat_id]
