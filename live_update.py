import asyncio
import logging
from typing import Any, Dict

from telegram.ext import Application

from config import OWNER_IDS
from messages import get_status_keyboard, send_or_edit_status_message
from state import (
    ViewMode,
    active_viewer_count_global,
    active_viewers,
    get_view_stats,
    prune_expired_viewers,
    save_state,
)
from status import HIDDEN_STATUS_TEXT, build_status_text
from windows import get_local_date_string


def _should_pin(chat_state: Dict[str, Any]) -> bool:
    return chat_state.get("chat_type") == "private"


async def update_status_for_chat(
    app: Application,
    chat_id: int,
    chat_state: Dict[str, Any],
    text: str,
    reply_markup=None,
    state: Dict[str, Any] | None = None,
) -> None:
    logging.info("Chat %s: tick", chat_id)
    if not chat_state.get("message_id") and _should_pin(chat_state):
        # Will be created by send_or_edit_status_message
        pass
    await send_or_edit_status_message(
        app, chat_id, chat_state, text, reply_markup=reply_markup, state=state
    )


async def update_live_status_for_app(app: Application) -> None:
    state = app.bot_data.get("state")
    if state is None:
        return

    if int(app.bot_data.get("ui_busy_count", 0)) > 0:
        logging.info("Live-update skipped (UI priority)")
        return

    current_date = get_local_date_string()
    get_view_stats(state, current_date)
    global_active_count = active_viewer_count_global(state)
    tasks_info: list[tuple[int, Dict[str, Any], Any]] = []

    for chat_id_str, chat_state in state.get("chats", {}).items():
        if not chat_state.get("enabled"):
            continue
        chat_id = int(chat_id_str)
        prune_expired_viewers(chat_state)
        active = active_viewers(chat_state)

        if not active:
            if chat_state.get("status_visible") or chat_state.get("view_mode") != ViewMode.STATUS.value:
                chat_state["status_visible"] = False
                chat_state["view_mode"] = ViewMode.STATUS.value
                tasks_info.append(
                    (
                        chat_id,
                        chat_state,
                        update_status_for_chat(
                            app,
                            chat_id,
                            chat_state,
                            HIDDEN_STATUS_TEXT,
                            reply_markup=get_status_keyboard(
                                show_button=True, is_owner=chat_id in OWNER_IDS
                            ),
                            state=state,
                        ),
                    )
                )
            continue

        chat_state["status_visible"] = True
        if chat_state.get("callback_in_progress"):
            logging.info(
                "Chat %s: live-update skipped (callback in progress)", chat_id
            )
            continue
        if chat_state.get("view_mode") != ViewMode.STATUS.value:
            logging.info(
                "Chat %s: live-update skipped (view=%s)",
                chat_id,
                chat_state.get("view_mode"),
            )
            continue

        try:
            text = build_status_text(state, active_viewer_count=global_active_count)
        except Exception as exc:
            logging.exception("Failed to build status text: %s", exc)
            continue

        tasks_info.append(
            (
                chat_id,
                chat_state,
                update_status_for_chat(
                    app,
                    chat_id,
                    chat_state,
                    text,
                    reply_markup=get_status_keyboard(
                        show_button=False,
                        include_hardware=True,
                        is_owner=chat_id in OWNER_IDS,
                    ),
                    state=state,
                ),
            )
        )

    if tasks_info:
        results = await asyncio.gather(
            *(item[2] for item in tasks_info), return_exceptions=True
        )
        for task_result, (chat_id, _, _) in zip(results, tasks_info):
            if isinstance(task_result, Exception):
                logging.exception("Chat %s: loop error: %s", int(chat_id), task_result)

    await save_state(state)


async def live_update_loop(app: Application) -> None:
    logging.info("Live update loop started")
    while True:
        try:
            await update_live_status_for_app(app)
        except Exception as exc:
            logging.exception("Live update loop error: %s", exc)
        await asyncio.sleep(1)
