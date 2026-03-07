import html
import json
import traceback

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.bot.access import log_context
from src.bot.runtime import BotRuntime


def build_notify_admin(runtime: BotRuntime):
    async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
        settings = runtime.get_settings()
        if not settings.admin_chat_id:
            return
        await context.bot.send_message(
            chat_id=settings.admin_chat_id,
            text=message,
            parse_mode=ParseMode.HTML,
        )

    return notify_admin


def build_error_handler(runtime: BotRuntime):
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        runtime.logger.error(
            "Exception while handling an update",
            exc_info=context.error,
            extra=log_context(update if isinstance(update, Update) else None),
        )

        settings = runtime.get_settings()
        if not settings.admin_chat_id or context.error is None:
            return

        tb_list = traceback.format_exception(
            None, context.error, context.error.__traceback__
        )
        tb_string = "".join(tb_list)
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        message = (
            "An exception was raised while handling an update\n"
            f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
            "</pre>\n\n"
            f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
            f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
            f"<pre>{html.escape(tb_string)}</pre>"
        )
        max_len = 3500
        if len(message) <= max_len:
            await context.bot.send_message(
                chat_id=settings.admin_chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
            )
            return
        head = message[: max_len - 64]
        tail = message[-512:]
        compact = f"{head}\n\n<pre>...truncated...</pre>\n\n{tail}"
        await context.bot.send_message(
            chat_id=settings.admin_chat_id,
            text=compact,
            parse_mode=ParseMode.HTML,
        )

    return error_handler
