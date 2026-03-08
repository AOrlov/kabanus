import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Optional

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src import config
from src.bot.handlers.message_handler import MessageHandler as AddressedMessageHandler
from src.bot.services.media_service import MediaService
from src.bot.services.reaction_service import ReactionService, ReactionState
from src.bot.services.reply_service import (
    ReplyService,
    message_drafts_unavailable_reason,
)
from src.model_provider import ModelProvider

MessageCallback = Callable[
    [Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]
]


@dataclass
class MessageFlowComponents:
    reaction_service: ReactionService
    message_handler: AddressedMessageHandler


def build_message_flow(
    *,
    settings_getter: Callable[..., config.Settings],
    provider_getter: Callable[[], ModelProvider],
    is_allowed_fn: Callable[[Update], bool],
    storage_id_fn: Callable[[Update], Optional[str]],
    add_message_fn: Callable[..., None],
    get_all_messages_fn: Callable[[str], list],
    get_message_by_telegram_message_id_fn: Callable[[str, int], Optional[dict]],
    build_context_fn: Callable[..., str],
    assemble_context_fn: Callable[..., str],
    log_context_fn: Callable[[Optional[Update]], dict],
    logger_override: Optional[logging.Logger] = None,
) -> MessageFlowComponents:
    reaction_state = ReactionState()
    reaction_service = ReactionService(
        state=reaction_state,
        provider_getter=provider_getter,
        settings_getter=lambda: settings_getter(),
        get_all_messages_fn=get_all_messages_fn,
        assemble_context_fn=assemble_context_fn,
        storage_id_fn=storage_id_fn,
        log_context_fn=log_context_fn,
        logger_override=logger_override,
    )

    media_service = MediaService(
        provider_getter=provider_getter,
        logger_override=logger_override,
        log_context_fn=log_context_fn,
    )

    reply_service = ReplyService(
        provider_getter=provider_getter,
        settings_getter=lambda: settings_getter(),
        add_message_fn=add_message_fn,
        log_context_fn=log_context_fn,
        logger_override=logger_override,
    )

    message_handler = AddressedMessageHandler(
        settings_getter=lambda: settings_getter(),
        is_allowed_fn=is_allowed_fn,
        storage_id_fn=storage_id_fn,
        add_message_fn=add_message_fn,
        get_message_by_telegram_message_id_fn=get_message_by_telegram_message_id_fn,
        build_context_fn=build_context_fn,
        provider_getter=provider_getter,
        media_service=media_service,
        maybe_react_fn=reaction_service.maybe_react,
        send_ai_response_fn=reply_service.send_ai_response,
        generate_response_with_drafts_fn=reply_service.generate_response_with_drafts,
        message_drafts_unavailable_reason_fn=message_drafts_unavailable_reason,
        log_context_fn=log_context_fn,
        logger_override=logger_override,
    )

    return MessageFlowComponents(
        reaction_service=reaction_service,
        message_handler=message_handler,
    )


def register(
    app: Application,
    *,
    settings: config.Settings,
    addressed_message_callback: MessageCallback,
) -> None:
    if not settings.features.get("message_handling"):
        return
    app.add_handler(
        MessageHandler(
            (filters.TEXT & ~filters.COMMAND)
            | filters.VOICE
            | filters.PHOTO
            | filters.Document.IMAGE,
            addressed_message_callback,
        )
    )
