"""Generic admin-notification and exception-report formatting utilities."""

import html
import json
import traceback
from typing import Any, Callable

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


def _truncate_middle(text: str, *, max_chars: int) -> str:
    marker = "\n...truncated...\n"
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(marker):
        return marker[:max_chars]
    head_len = (max_chars - len(marker)) // 2
    tail_len = max_chars - len(marker) - head_len
    return f"{text[:head_len]}{marker}{text[-tail_len:]}"


def _fit_rendered_text(
    *,
    text: str,
    max_len: int,
    render_fn: Callable[[str], str],
) -> str:
    rendered = render_fn(text)
    if len(rendered) <= max_len:
        return rendered

    low = 0
    high = len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = _truncate_middle(text, max_chars=mid)
        candidate_rendered = render_fn(candidate)
        if len(candidate_rendered) <= max_len:
            best = candidate_rendered
            low = mid + 1
        else:
            high = mid - 1
    return best


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
    prefix = (
        "An exception was raised while handling an update\n"
        f"<pre>update_meta = {html.escape(json.dumps(update_meta, ensure_ascii=False))}</pre>\n\n"
        f"<pre>error = {html.escape(type(error).__name__)}: "
        f"{html.escape(str(error))}</pre>\n\n"
    )
    render_with_traceback = lambda traceback_text: (
        f"{prefix}<pre>{html.escape(traceback_text)}</pre>"
    )
    message = _fit_rendered_text(
        text=tb_string,
        max_len=max_len,
        render_fn=render_with_traceback,
    )
    if message:
        return message

    compact_payload = (
        f"update_meta = {json.dumps(update_meta, ensure_ascii=False)}\n\n"
        f"error = {type(error).__name__}: {error}"
    )
    return _fit_rendered_text(
        text=compact_payload,
        max_len=max_len,
        render_fn=lambda payload: f"<pre>{html.escape(payload)}</pre>",
    )


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
