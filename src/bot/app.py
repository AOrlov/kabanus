import inspect
import html
import json
import logging
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src import config, logging_utils
from src.bot.handlers import common
from src.bot.handlers.events_handler import EventsHandler
from src.bot.handlers.message_handler import MessageHandler as AddressedMessageHandler
from src.bot.handlers.summary_handler import SummaryHandler
from src.bot.services.media_service import MediaService
from src.bot.services.reaction_service import ReactionService, ReactionState
from src.bot.services.reply_service import (
    ReplyService,
    message_drafts_unavailable_reason,
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

logger = logging.getLogger(__name__)


@dataclass
class LogLevelState:
    current_level: Optional[int] = None


def _supports_force_kwarg(
    settings_getter: Callable[..., config.Settings],
) -> bool:
    try:
        getter_signature = inspect.signature(settings_getter)
    except (TypeError, ValueError):
        return True

    force_param = getter_signature.parameters.get("force")
    if force_param and force_param.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    ):
        return True

    return any(
        parameter.kind
        in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
        for parameter in getter_signature.parameters.values()
    )


class BotRuntime:
    def __init__(
        self,
        *,
        settings_getter: Callable[..., config.Settings],
        provider_getter: Callable[[], ModelProvider],
        reaction_service: ReactionService,
        summary_handler: SummaryHandler,
        message_handler: AddressedMessageHandler,
        events_handler: EventsHandler,
        log_level_state: Optional[LogLevelState] = None,
        is_allowed_fn: Optional[Callable[[Update], bool]] = None,
        log_context_fn: Callable[[Optional[Update]], dict] = common.log_context,
    ) -> None:
        self._settings_getter = settings_getter
        self._settings_getter_accepts_force = _supports_force_kwarg(settings_getter)
        self._provider_getter = provider_getter
        self.reaction_service = reaction_service
        self.summary_handler = summary_handler
        self.message_handler = message_handler
        self.events_handler = events_handler
        self.log_level_state = log_level_state or LogLevelState()
        self._is_allowed = is_allowed_fn or (
            lambda update: common.is_allowed(update, settings_getter=settings_getter)
        )
        self._log_context = log_context_fn

    def provider(self) -> ModelProvider:
        return self._provider_getter()

    def _call_settings_getter(self, force: bool = False) -> config.Settings:
        if self._settings_getter_accepts_force:
            return self._settings_getter(force=force)
        return self._settings_getter()

    def get_settings(self, force: bool = False) -> config.Settings:
        return self._call_settings_getter(force=force)

    def apply_log_level(self, settings: config.Settings) -> None:
        level = logging.DEBUG if settings.debug_mode else logging.INFO
        if self.log_level_state.current_level == level:
            return
        logging_utils.update_log_level(level)
        self.log_level_state.current_level = level

    async def hi(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not self._is_allowed(update):
            return
        if update.message is None:
            return

        settings = self.get_settings()
        if not settings.features.get("commands", {}).get("hi"):
            return

        await update.message.reply_text("Hello! I am your speech-to-text bot.")
        await update.message.reply_text(
            f"Configured model provider: {settings.model_provider}"
        )
        if settings.model_provider == "openai":
            await update.message.reply_text(
                f"Configured OpenAI model: {settings.openai_model}"
            )
        elif settings.gemini_api_key and settings.gemini_models:
            preferred = settings.gemini_models[0].name

            def fmt_limit(value: Optional[int]) -> str:
                return "unlimited" if value is None else str(value)

            formatted = ", ".join(
                f"{model.name} (rpm={fmt_limit(model.rpm)}, rpd={fmt_limit(model.rpd)})"
                for model in settings.gemini_models
            )
            await update.message.reply_text(
                "Configured Gemini model priority: " + preferred
            )
            await update.message.reply_text("Configured Gemini models: " + formatted)

    async def notify_admin(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
    ) -> None:
        settings = self.get_settings()
        if not settings.admin_chat_id:
            return
        safe_message = html.escape(message or "")
        await context.bot.send_message(
            chat_id=settings.admin_chat_id,
            text=safe_message,
            parse_mode=ParseMode.HTML,
        )

    async def error_handler(
        self,
        update: object,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        logger.error(
            "Exception while handling an update",
            exc_info=context.error,
            extra=self._log_context(update if isinstance(update, Update) else None),
        )

        settings = self.get_settings()
        if not settings.admin_chat_id or context.error is None:
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

    async def refresh_settings_job(self, _: ContextTypes.DEFAULT_TYPE) -> None:
        settings = self.get_settings(force=True)
        self.apply_log_level(settings)


def build_runtime(
    *,
    settings_getter: Callable[..., config.Settings] = config.get_settings,
    provider: Optional[ModelProvider] = None,
    provider_getter: Optional[Callable[[], ModelProvider]] = None,
    add_message_fn: Callable[..., None] = add_message,
    build_context_fn: Callable[..., str] = build_context,
    get_all_messages_fn: Callable[[str], list] = get_all_messages,
    get_summary_view_text_fn: Callable[..., str] = get_summary_view_text,
    get_message_by_telegram_message_id_fn: Callable[
        [str, int], Optional[dict]
    ] = get_message_by_telegram_message_id,
    assemble_context_fn: Callable[..., str] = assemble_context,
    is_allowed_fn: Optional[Callable[[Update], bool]] = None,
    log_context_fn: Callable[[Optional[Update]], dict] = common.log_context,
    storage_id_fn: Callable[[Update], Optional[str]] = common.storage_id,
) -> BotRuntime:
    provider_instance = provider
    runtime: Optional[BotRuntime] = None
    if provider_getter is None:
        if provider_instance is None:
            provider_instance = build_provider()

        def provider_getter() -> ModelProvider:
            assert provider_instance is not None
            return provider_instance

    if is_allowed_fn is None:

        def is_allowed_fn(update: Update) -> bool:
            return common.is_allowed(
                update,
                settings_getter=settings_getter,
                logger_override=logger,
                log_context_fn=log_context_fn,
            )

    reaction_state = ReactionState()
    reaction_service = ReactionService(
        state=reaction_state,
        provider_getter=provider_getter,
        settings_getter=settings_getter,
        get_all_messages_fn=get_all_messages_fn,
        assemble_context_fn=assemble_context_fn,
        storage_id_fn=storage_id_fn,
        log_context_fn=log_context_fn,
        logger_override=logger,
    )

    media_service = MediaService(
        provider_getter=provider_getter,
        logger_override=logger,
        log_context_fn=log_context_fn,
    )

    reply_service = ReplyService(
        provider_getter=provider_getter,
        settings_getter=settings_getter,
        add_message_fn=add_message_fn,
        log_context_fn=log_context_fn,
        logger_override=logger,
    )

    summary_handler = SummaryHandler(
        is_allowed_fn=is_allowed_fn,
        storage_id_fn=storage_id_fn,
        get_summary_view_text_fn=get_summary_view_text_fn,
    )

    async def _notify_admin_proxy(
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
    ) -> None:
        if runtime is None:
            return
        await runtime.notify_admin(context, message)

    events_handler = EventsHandler(
        is_allowed_fn=is_allowed_fn,
        provider_getter=provider_getter,
        notify_admin_fn=_notify_admin_proxy,
        log_context_fn=log_context_fn,
        settings_getter=settings_getter,
        logger_override=logger,
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
        logger_override=logger,
    )

    runtime = BotRuntime(
        settings_getter=settings_getter,
        provider_getter=provider_getter,
        reaction_service=reaction_service,
        summary_handler=summary_handler,
        message_handler=message_handler,
        events_handler=events_handler,
        is_allowed_fn=is_allowed_fn,
        log_context_fn=log_context_fn,
    )
    return runtime


def build_application(
    runtime: BotRuntime,
    *,
    settings: Optional[config.Settings] = None,
) -> Application:
    active_settings = settings or runtime.get_settings()
    app = ApplicationBuilder().token(active_settings.telegram_bot_token).build()
    app.add_error_handler(runtime.error_handler)
    runtime.apply_log_level(active_settings)

    app.add_handler(CommandHandler("hi", runtime.hi))
    app.add_handler(
        CommandHandler(["summary", "tldr"], runtime.summary_handler.view_summary)
    )

    if active_settings.features["message_handling"]:
        app.add_handler(
            MessageHandler(
                (filters.TEXT & ~filters.COMMAND)
                | filters.VOICE
                | filters.PHOTO
                | filters.Document.IMAGE,
                runtime.message_handler.handle_addressed_message,
            )
        )
    if active_settings.features["schedule_events"]:
        app.add_handler(
            MessageHandler(filters.PHOTO, runtime.events_handler.schedule_events)
        )

    return app


def run_polling(runtime: Optional[BotRuntime] = None) -> None:
    active_runtime = runtime or build_runtime()
    settings = active_runtime.get_settings()
    app = build_application(active_runtime, settings=settings)
    logger.info("Bot started with features: %s", settings.features)
    app.run_polling()
