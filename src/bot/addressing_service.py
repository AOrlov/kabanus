from dataclasses import dataclass
import logging
from typing import Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.media import resolve_reply_target_context
from src.bot.mentions import is_bot_mentioned, should_respond_to_message
from src.model_provider import ModelProvider


@dataclass(frozen=True)
class AddressingDecision:
    mentioned_bot: bool
    replied_to_bot: bool
    replied_to_other_user: bool
    should_respond: bool


@dataclass(frozen=True)
class AddressingRequest:
    text: str
    is_transcribed_text: bool
    bot_username: str
    bot_id: int
    aliases: list[str]


def _resolve_replied_user_id(update: Update) -> Optional[int]:
    message = update.message
    if message is None or message.reply_to_message is None:
        return None
    if message.reply_to_message.from_user is None:
        return None
    return message.reply_to_message.from_user.id


def should_resolve_reply_target(decision: AddressingDecision) -> bool:
    return decision.replied_to_other_user and decision.mentioned_bot


def resolve_addressing_decision(
    update: Update,
    request: AddressingRequest,
) -> AddressingDecision:
    message = update.message
    if message is None:
        return AddressingDecision(False, False, False, False)

    mentioned_bot = is_bot_mentioned(
        message,
        bot_username=request.bot_username or "",
        bot_id=request.bot_id,
        aliases=request.aliases,
        fallback_text=request.text if request.is_transcribed_text else "",
    )

    replied_user_id = _resolve_replied_user_id(update)

    replied_to_bot = replied_user_id == request.bot_id
    replied_to_other_user = (
        message.reply_to_message is not None
        and replied_user_id is not None
        and replied_user_id != request.bot_id
    )
    return AddressingDecision(
        mentioned_bot=mentioned_bot,
        replied_to_bot=replied_to_bot,
        replied_to_other_user=replied_to_other_user,
        should_respond=should_respond_to_message(
            mentioned_bot=mentioned_bot,
            replied_to_bot=replied_to_bot,
            replied_to_other_user=replied_to_other_user,
        ),
    )


_LOGGER = logging.getLogger(__name__)


async def resolve_reply_target_if_needed(
    update: Update,
    *,
    decision: AddressingDecision,
    chat_id: str,
    context: ContextTypes.DEFAULT_TYPE,
    model_provider: ModelProvider,
) -> Optional[Dict[str, str]]:
    if update.message is None:
        return None
    if not should_resolve_reply_target(decision):
        return None
    return await resolve_reply_target_context(
        update.message,
        chat_id=chat_id,
        context=context,
        model_provider=model_provider,
        logger=_LOGGER,
    )
