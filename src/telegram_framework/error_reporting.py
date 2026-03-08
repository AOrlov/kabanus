"""Generic admin-notification and exception-report formatting utilities."""

import html
import json
import traceback
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes


def _send_html_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    admin_chat_id: str,
    message: str,
) -> Any:
    return context.bot.send_message(
        chat_id=admin_chat_id,
        text=message,
        parse_mode=ParseMode.HTML,
    )


async def notify_admin(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    admin_chat_id: str,
    message: str,
) -> None:
    if not admin_chat_id:
        return
    safe_message = html.escape(message or "")
    await _send_html_message(
        context,
        admin_chat_id=admin_chat_id,
        message=safe_message,
    )


def _update_meta(update: object) -> dict:
    if isinstance(update, Update):
        return {
            "update_id": update.update_id,
            "chat_id": getattr(update.effective_chat, "id", None),
            "user_id": getattr(update.effective_user, "id", None),
            "has_message": update.message is not None,
        }
    return {"type": type(update).__name__}


def build_error_report_message(
    *,
    update: object,
    error: BaseException,
    max_len: int = 3500,
) -> str:
    tb_list = traceback.format_exception(
        None,
        error,
        error.__traceback__,
    )
    tb_string = "".join(tb_list[-8:])

    update_meta = _update_meta(update)
    message = (
        "An exception was raised while handling an update\n"
        f"<pre>update_meta = {html.escape(json.dumps(update_meta, ensure_ascii=False))}</pre>\n\n"
        f"<pre>error = {html.escape(type(error).__name__)}: "
        f"{html.escape(str(error))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    if len(message) <= max_len:
        return message

    head = message[: max_len - 64]
    tail = message[-512:]
    return f"{head}\n\n<pre>...truncated...</pre>\n\n{tail}"


async def notify_admin_about_exception(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    admin_chat_id: str,
    max_len: int = 3500,
) -> None:
    if not admin_chat_id or context.error is None:
        return

    message = build_error_report_message(
        update=update,
        error=context.error,
        max_len=max_len,
    )
    await _send_html_message(
        context,
        admin_chat_id=admin_chat_id,
        message=message,
    )
