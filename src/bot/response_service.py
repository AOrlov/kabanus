import logging
from typing import Any, Callable, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest

from src import config, utils
from src.message_store import add_message


def chunk_string(s: str, chunk_size: int) -> list[str]:
    if not s:
        return []
    if len(s) <= chunk_size:
        return [s]
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]


async def send_ai_response(  # pylint: disable=too-many-arguments
    update: Update,
    outgoing_text: str,
    storage_id: str,
    *,
    settings_getter: Callable[..., config.Settings],
    logger: logging.Logger,
    log_context_fn: Callable[[Optional[Update]], dict[str, Any]],
    add_message_fn: Callable[..., Any] = add_message,
) -> None:
    message = update.message
    if message is None:
        return

    settings = settings_getter()
    if not settings.telegram_format_ai_replies:
        for chunk in [
            item for item in chunk_string(outgoing_text, 4000) if item.strip()
        ]:
            await message.reply_text(chunk)
            add_message_fn("Bot", chunk, chat_id=storage_id, is_bot=True)
        return

    html_chunks = [
        chunk
        for chunk in utils.build_telegram_html_chunks(outgoing_text, 4000)
        if chunk.strip()
    ]
    for chunk in html_chunks:
        plain_chunk = utils.telegram_html_to_plain_text(chunk).strip()
        try:
            await message.reply_text(chunk, parse_mode=ParseMode.HTML)
            if plain_chunk:
                add_message_fn("Bot", plain_chunk, chat_id=storage_id, is_bot=True)
        except BadRequest as exc:
            logger.warning(
                "Failed to send formatted response chunk, falling back to plain text",
                extra={
                    **log_context_fn(update),
                    "error": str(exc),
                    "chunk_preview": chunk[:256],
                },
            )
            fallback_chunk = plain_chunk or chunk
            await message.reply_text(fallback_chunk)
            add_message_fn("Bot", fallback_chunk, chat_id=storage_id, is_bot=True)
