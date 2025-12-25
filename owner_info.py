import asyncio
import asyncio
import logging
from typing import Any, Dict, Optional

from telegram.error import TelegramError
from telegram.ext import Application

from messages import RATE_LIMITER, send_status_reply_message


class _OwnerInfoEntry:
    def __init__(self, message_id: Optional[int], text: str, task: Optional[asyncio.Task]):
        self.message_id = message_id
        self.text = text
        self.task = task


class OwnerInfoManager:
    def __init__(self) -> None:
        self._entries: Dict[int, _OwnerInfoEntry] = {}

    async def _schedule_delete(
        self, app: Application, chat_id: int, message_id: int, entry: _OwnerInfoEntry
    ) -> None:
        try:
            await asyncio.sleep(20)
            await RATE_LIMITER.wait("delete", 2.0, scope=str(chat_id))
            await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramError as exc:
            logging.warning("Chat %s: failed to delete owner info message: %s", chat_id, exc)
        except Exception as exc:
            logging.warning("Chat %s: unexpected delete error: %s", chat_id, exc)
        finally:
            stored = self._entries.get(chat_id)
            if stored is entry:
                self._entries.pop(chat_id, None)

    async def send_or_update(
        self,
        app: Application,
        chat_id: int,
        chat_state: Dict[str, Any],
        text: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = self._entries.get(chat_id)
        if entry and entry.text == text:
            # No content change; do nothing to avoid duplication or timer reset.
            return

        message_id: Optional[int] = entry.message_id if entry else None

        if entry and entry.task:
            entry.task.cancel()

        if message_id is not None:
            try:
                await RATE_LIMITER.wait("edit", 5.0, scope=f"owner:{chat_id}")
                await app.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text
                )
            except TelegramError:
                message_id = None
            except Exception:
                message_id = None

        if message_id is None:
            message_id = await send_status_reply_message(
                app, chat_id, chat_state, text, state=state
            )
            if message_id is None:
                return

        new_entry = _OwnerInfoEntry(message_id=message_id, text=text, task=None)
        delete_task = app.create_task(
            self._schedule_delete(app, chat_id, message_id, new_entry)
        )
        new_entry.task = delete_task
        self._entries[chat_id] = new_entry


OWNER_INFO_MANAGER = OwnerInfoManager()
