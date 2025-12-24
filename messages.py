import logging
import time
from typing import Any, Dict, List

from telegram.error import RetryAfter, TelegramError
from telegram.ext import Application

from state import record_message_id


def _set_backoff(chat_state: Dict[str, Any], retry_after: int, reason: str, chat_id: int) -> None:
    chat_state["backoff_until"] = time.time() + retry_after + 1
    logging.warning("Chat %s: backoff %s sec (%s)", chat_id, retry_after, reason)


async def delete_bot_messages(
    app: Application, chat_id: int, message_ids: List[int]
) -> None:
    for message_id in message_ids:
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


async def send_and_pin_status_message(
    app: Application, chat_id: int, chat_state: Dict[str, Any], text: str
) -> None:
    try:
        message = await app.bot.send_message(chat_id=chat_id, text=text)
        chat_state["message_id"] = message.message_id
        chat_state["last_sent_text"] = None
        chat_state["backoff_until"] = None
        chat_state["message_ids"] = []
        record_message_id(chat_state, message.message_id)
        if chat_state.get("chat_type") == "private":
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
    app: Application, chat_id: int, chat_state: Dict[str, Any], text: str
) -> None:
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
        )
        return

    try:
        await app.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
        )
        chat_state["last_sent_text"] = text
        chat_state["backoff_until"] = None
        logging.info("Chat %s: edited ok", chat_id)
    except RetryAfter as exc:
        _set_backoff(chat_state, exc.retry_after, "edit", chat_id)
    except TelegramError as exc:
        logging.exception("Chat %s: edit failed (%s), recreating", chat_id, exc)
        await send_and_pin_status_message(app, chat_id, chat_state, text)
    except Exception as exc:
        logging.exception("Chat %s: unexpected edit error: %s", chat_id, exc)
        await send_and_pin_status_message(app, chat_id, chat_state, text)
