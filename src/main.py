import asyncio
import html
import json
import logging
import traceback
import weakref
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from telegram import Update, Voice
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src import config, logging_utils
from src.bot import app as bot_app
from src.bot.handlers import common
from src.bot.handlers.events_handler import EventsHandler
from src.bot.handlers.message_handler import (
    MessageHandler,
    build_prompt,
    contains_alias_token,
    entity_type_value,
    is_bot_mentioned,
    iter_message_entity_blocks,
    normalized_aliases,
    should_respond_to_message,
)
from src.bot.handlers.summary_handler import (
    SummaryHandler,
    command_args_from_message_text,
    parse_summary_command_args,
    summary_command_usage,
)
from src.bot.services.media_service import (
    IMAGE_MAX_BYTES,
    MediaService,
    NON_TEXT_REPLY_PLACEHOLDER,
    combine_caption_and_extracted,
    guess_mime_from_name,
    is_image_document,
    message_sender_name,
)
from src.bot.services.reaction_service import (
    REACTION_ALLOWED_LIST,
    REACTION_ALLOWED_SET,
    ReactionService,
    ReactionState,
)
from src.bot.services.reply_service import (
    ReplyService,
    build_response_draft_id,
    chunk_string,
    message_drafts_unavailable_reason,
    should_use_message_drafts,
)
from src.message_store import (
    add_message,
    assemble_context,
    build_context,
    get_all_messages,
    get_message_by_telegram_message_id,
    get_summary_view_text,
)
from src.model_provider import ModelProvider
from src.provider_factory import build_provider
from src.telegram_drafts import send_message_draft

logging_utils.configure_bootstrap()
settings = config.get_settings()
logging_utils.configure_logging(settings)

logger = logging.getLogger(__name__)
model_provider = build_provider()

_CURRENT_LOG_LEVEL = None
_REACTION_DAY = None
_REACTION_COUNT = 0
_REACTION_LAST_TS = 0.0
_REACTION_ALLOWED_SET = set(REACTION_ALLOWED_SET)
_REACTION_ALLOWED_LIST = list(REACTION_ALLOWED_LIST)
_MESSAGES_SINCE_LAST_REACTION = 0
_NON_TEXT_REPLY_PLACEHOLDER = NON_TEXT_REPLY_PLACEHOLDER
_IMAGE_MAX_BYTES = IMAGE_MAX_BYTES
_LEGACY_REACTION_LOCKS: (
    "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]"
) = weakref.WeakKeyDictionary()


def _log_context(update: Optional[Update]) -> dict:
    return common.log_context(update)


def _storage_id(update: Update) -> Optional[str]:
    return common.storage_id(update)


def apply_log_level(settings: config.Settings) -> None:
    global _CURRENT_LOG_LEVEL
    level = logging.DEBUG if settings.debug_mode else logging.INFO
    if _CURRENT_LOG_LEVEL == level:
        return
    logging_utils.update_log_level(level)
    _CURRENT_LOG_LEVEL = level


def transcribe_audio(audio_path: str, active_provider: ModelProvider) -> str:
    return active_provider.transcribe(audio_path)


_entity_type_value = entity_type_value
_iter_message_entity_blocks = iter_message_entity_blocks
_normalized_aliases = normalized_aliases
_contains_alias_token = contains_alias_token
_is_bot_mentioned = is_bot_mentioned
_should_respond_to_message = should_respond_to_message
_guess_mime_from_name = guess_mime_from_name
_is_image_document = is_image_document
_combine_caption_and_extracted = combine_caption_and_extracted
_message_sender_name = message_sender_name
_build_prompt = build_prompt
_parse_summary_command_args = parse_summary_command_args
_summary_command_usage = summary_command_usage
_command_args_from_message_text = command_args_from_message_text
_message_drafts_unavailable_reason = message_drafts_unavailable_reason
_should_use_message_drafts = should_use_message_drafts
_build_response_draft_id = build_response_draft_id


def _build_media_service() -> MediaService:
    return MediaService(
        provider_getter=lambda: model_provider,
        logger_override=logger,
        log_context_fn=_log_context,
    )


def _build_reply_service() -> ReplyService:
    return ReplyService(
        provider_getter=lambda: model_provider,
        settings_getter=config.get_settings,
        add_message_fn=add_message,
        send_message_draft_fn=send_message_draft,
        log_context_fn=_log_context,
        logger_override=logger,
    )


def _sync_reaction_state_to_globals(state: ReactionState) -> None:
    global _REACTION_DAY, _REACTION_COUNT, _REACTION_LAST_TS, _MESSAGES_SINCE_LAST_REACTION
    _REACTION_DAY = state.day
    _REACTION_COUNT = state.count
    _REACTION_LAST_TS = state.last_ts
    _MESSAGES_SINCE_LAST_REACTION = state.messages_since_last_reaction


def _reaction_state_from_globals() -> ReactionState:
    return ReactionState(
        day=_REACTION_DAY,
        count=_REACTION_COUNT,
        last_ts=_REACTION_LAST_TS,
        messages_since_last_reaction=_MESSAGES_SINCE_LAST_REACTION,
    )


def _get_legacy_reaction_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _LEGACY_REACTION_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _LEGACY_REACTION_LOCKS[loop] = lock
    return lock


def _reset_reaction_budget_if_needed(now: datetime) -> None:
    global _REACTION_DAY, _REACTION_COUNT
    today = now.date()
    if _REACTION_DAY != today:
        _REACTION_DAY = today
        _REACTION_COUNT = 0


def _build_reaction_context(chat_id: Optional[str], settings: config.Settings) -> str:
    if (
        not chat_id
        or settings.reaction_context_turns <= 0
        or settings.reaction_context_token_limit <= 0
    ):
        return ""
    messages = get_all_messages(chat_id)
    if not messages:
        return ""
    recent_messages = messages[-settings.reaction_context_turns :]
    return assemble_context(
        recent_messages,
        token_limit=settings.reaction_context_token_limit,
    )


async def _extract_text_from_photo_message(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    return await _build_media_service().extract_text_from_photo_message(
        message, context
    )


async def _extract_text_from_image_document(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[str]:
    return await _build_media_service().extract_text_from_image_document(
        message, context
    )


async def _extract_reply_target_text(
    reply_message: Any,
    context: ContextTypes.DEFAULT_TYPE,
) -> Tuple[str, str]:
    return await _build_media_service().extract_reply_target_text(
        reply_message, context
    )


async def _resolve_reply_target_context(
    message: Any,
    *,
    chat_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[Dict[str, str]]:
    return await _build_media_service().resolve_reply_target_context(
        message,
        chat_id=chat_id,
        context=context,
        get_message_by_telegram_message_id_fn=get_message_by_telegram_message_id,
    )


def is_allowed(update: Update) -> bool:
    return common.is_allowed(
        update,
        settings_getter=config.get_settings,
        logger_override=logger,
        log_context_fn=_log_context,
    )


async def maybe_react(update: Update, text: str):
    async with _get_legacy_reaction_lock():
        state = _reaction_state_from_globals()
        service = ReactionService(
            state=state,
            provider_getter=lambda: model_provider,
            settings_getter=config.get_settings,
            get_all_messages_fn=get_all_messages,
            assemble_context_fn=assemble_context,
            storage_id_fn=_storage_id,
            allowed_reactions=_REACTION_ALLOWED_LIST,
            allowed_reaction_set=_REACTION_ALLOWED_SET,
            log_context_fn=_log_context,
            logger_override=logger,
        )
        try:
            await service.maybe_react(update, text)
        finally:
            _sync_reaction_state_to_globals(service.state)


async def hi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    runtime = bot_app.build_runtime(
        settings_getter=config.get_settings,
        provider_getter=lambda: model_provider,
        is_allowed_fn=is_allowed,
        log_context_fn=_log_context,
        storage_id_fn=_storage_id,
        add_message_fn=add_message,
        build_context_fn=build_context,
        get_all_messages_fn=get_all_messages,
        get_summary_view_text_fn=get_summary_view_text,
        get_message_by_telegram_message_id_fn=get_message_by_telegram_message_id,
        assemble_context_fn=assemble_context,
    )
    await runtime.hi(update, context)


async def view_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handler = SummaryHandler(
        is_allowed_fn=is_allowed,
        storage_id_fn=_storage_id,
        get_summary_view_text_fn=get_summary_view_text,
        parse_summary_args_fn=_parse_summary_command_args,
        summary_usage_fn=_summary_command_usage,
        command_args_from_text_fn=_command_args_from_message_text,
        chunk_string_fn=chunk_string,
    )
    await handler.view_summary(update, context)


async def transcribe_voice_message(
    voice: Voice,
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    return await _build_media_service().transcribe_voice_message(voice, context)


async def _generate_response_with_drafts(
    update: Update,
    prompt: str,
    settings: config.Settings,
) -> str:
    return await _build_reply_service().generate_response_with_drafts(
        update,
        prompt,
        settings,
    )


async def send_ai_response(update: Update, outgoing_text: str, storage_id: str) -> None:
    await _build_reply_service().send_ai_response(update, outgoing_text, storage_id)


async def handle_addressed_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handler = MessageHandler(
        settings_getter=lambda: config.get_settings(),
        is_allowed_fn=is_allowed,
        storage_id_fn=_storage_id,
        add_message_fn=add_message,
        get_message_by_telegram_message_id_fn=get_message_by_telegram_message_id,
        build_context_fn=build_context,
        provider_getter=lambda: model_provider,
        media_service=_build_media_service(),
        maybe_react_fn=maybe_react,
        send_ai_response_fn=send_ai_response,
        generate_response_with_drafts_fn=_generate_response_with_drafts,
        message_drafts_unavailable_reason_fn=_message_drafts_unavailable_reason,
        log_context_fn=_log_context,
        logger_override=logger,
    )
    await handler.handle_addressed_message(update, context)


async def schedule_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handler = EventsHandler(
        is_allowed_fn=is_allowed,
        provider_getter=lambda: model_provider,
        notify_admin_fn=notify_admin,
        log_context_fn=_log_context,
        settings_getter=config.get_settings,
        logger_override=logger,
    )
    await handler.schedule_events(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(
        "Exception while handling an update",
        exc_info=context.error,
        extra=_log_context(update if isinstance(update, Update) else None),
    )

    active_settings = config.get_settings()
    if not active_settings.admin_chat_id or context.error is None:
        return

    tb_list = traceback.format_exception(
        None,
        context.error,
        context.error.__traceback__,
    )
    tb_string = "".join(tb_list[-8:])
    if isinstance(update, Update):
        update_meta = {
            "update_id": update.update_id,
            "chat_id": getattr(update.effective_chat, "id", None),
            "user_id": getattr(update.effective_user, "id", None),
            "has_message": update.message is not None,
        }
    else:
        update_meta = {"type": type(update).__name__}
    message = (
        "An exception was raised while handling an update\n"
        f"<pre>update_meta = {html.escape(json.dumps(update_meta, ensure_ascii=False))}</pre>\n\n"
        f"<pre>error = {html.escape(type(context.error).__name__)}: "
        f"{html.escape(str(context.error))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )
    max_len = 3500
    if len(message) <= max_len:
        await context.bot.send_message(
            chat_id=active_settings.admin_chat_id,
            text=message,
            parse_mode=ParseMode.HTML,
        )
        return

    head = message[: max_len - 64]
    tail = message[-512:]
    compact = f"{head}\n\n<pre>...truncated...</pre>\n\n{tail}"
    await context.bot.send_message(
        chat_id=active_settings.admin_chat_id,
        text=compact,
        parse_mode=ParseMode.HTML,
    )


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
    active_settings = config.get_settings()
    if not active_settings.admin_chat_id:
        return
    safe_message = html.escape(message or "")
    await context.bot.send_message(
        chat_id=active_settings.admin_chat_id,
        text=safe_message,
        parse_mode=ParseMode.HTML,
    )


async def refresh_settings_job(_: ContextTypes.DEFAULT_TYPE) -> None:
    active_settings = config.get_settings(force=True)
    apply_log_level(active_settings)


def _build_runtime() -> bot_app.BotRuntime:
    return bot_app.build_runtime(
        settings_getter=config.get_settings,
        provider_getter=lambda: model_provider,
        add_message_fn=add_message,
        build_context_fn=build_context,
        get_all_messages_fn=get_all_messages,
        get_summary_view_text_fn=get_summary_view_text,
        get_message_by_telegram_message_id_fn=get_message_by_telegram_message_id,
        assemble_context_fn=assemble_context,
        is_allowed_fn=is_allowed,
        log_context_fn=_log_context,
        storage_id_fn=_storage_id,
    )


def run() -> None:
    active_settings = config.get_settings()
    runtime = _build_runtime()
    runtime.apply_log_level(active_settings)
    app = bot_app.build_application(runtime, settings=active_settings)
    logger.info("Bot started with features: %s", active_settings.features)
    app.run_polling()


if __name__ == "__main__":
    run()
