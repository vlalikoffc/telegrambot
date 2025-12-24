import asyncio
import logging
from typing import Any, Dict

from telegram.ext import Application

from messages import get_status_keyboard, send_or_edit_status_message
from state import active_viewers, prune_expired_viewers, save_state
from status import HIDDEN_STATUS_TEXT, build_status_text


def _should_pin(chat_state: Dict[str, Any]) -> bool:
    return chat_state.get("chat_type") == "private"


async def update_status_for_chat(
    app: Application, chat_id: int, chat_state: Dict[str, Any], text: str
) -> None:
    logging.info("Chat %s: tick", chat_id)
    if not chat_state.get("message_id") and _should_pin(chat_state):
        # Will be created by send_or_edit_status_message
        pass
    await send_or_edit_status_message(
        app, chat_id, chat_state, text, reply_markup=get_status_keyboard()
    )


async def update_live_status_for_app(app: Application) -> None:
    state = app.bot_data.get("state")
    if state is None:
        return
    tasks_info = []
    for chat_id_str, chat_state in state.get("chats", {}).items():
        if not chat_state.get("enabled"):
            continue
        chat_id = int(chat_id_str)
        prune_expired_viewers(chat_state)
        active = active_viewers(chat_state)
        if not active:
            if chat_state.get("status_visible"):
                chat_state["status_visible"] = False
                tasks_info.append(
                    (chat_id_str, chat_state, update_status_for_chat(app, chat_id, chat_state, HIDDEN_STATUS_TEXT))
                )
            continue
        chat_state["status_visible"] = True
        try:
            text = build_status_text(state, active_viewer_count=len(active))
        except Exception as exc:
            logging.exception("Failed to build status text: %s", exc)
            continue
        tasks_info.append(
            (chat_id_str, chat_state, update_status_for_chat(app, chat_id, chat_state, text))
        )
    if tasks_info:
        results = await asyncio.gather(
            *(item[2] for item in tasks_info), return_exceptions=True
        )
        for task_result, (chat_id_str, chat_state, _) in zip(results, tasks_info):
            if isinstance(task_result, Exception):
                logging.exception(
                    "Chat %s: loop error: %s", int(chat_id_str), task_result
                )
    await save_state(state)


async def live_update_loop(app: Application) -> None:
    logging.info("Live update loop started")
    while True:
        try:
            await update_live_status_for_app(app)
        except Exception as exc:
            logging.exception("Live update loop error: %s", exc)
        await asyncio.sleep(1)
