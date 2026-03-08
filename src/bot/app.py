import logging
from dataclasses import dataclass
from typing import Callable, Optional

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
)

from src import config, logging_utils
from src.bot import features as bot_features
from src.bot.handlers.events_handler import EventsHandler
from src.bot.handlers.message_handler import MessageHandler as AddressedMessageHandler
from src.bot.handlers.summary_handler import SummaryHandler
from src.bot.services.reaction_service import ReactionService
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
from src.telegram_framework import application as framework_application
from src.telegram_framework import error_reporting as framework_error_reporting
from src.telegram_framework import policy as framework_policy
from src.telegram_framework.runtime import PollingRuntime, SettingsResolver

logger = logging.getLogger(__name__)


@dataclass
class LogLevelState:
    current_level: Optional[int] = None


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
        log_context_fn: Callable[
            [Optional[Update]], dict
        ] = framework_policy.log_context,
    ) -> None:
        self._settings = SettingsResolver(settings_getter)
        self._provider_getter = provider_getter
        self.reaction_service = reaction_service
        self.summary_handler = summary_handler
        self.message_handler = message_handler
        self.events_handler = events_handler
        self.log_level_state = log_level_state or LogLevelState()
        self._is_allowed = is_allowed_fn or (
            lambda update: framework_policy.is_allowed(
                update,
                settings_getter=self.get_settings,
                logger_override=logger,
                log_context_fn=log_context_fn,
            )
        )
        self._log_context = log_context_fn

    def provider(self) -> ModelProvider:
        return self._provider_getter()

    def get_settings(self, force: bool = False) -> config.Settings:
        return self._settings.get(force=force)

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
        await framework_error_reporting.notify_admin(
            context,
            admin_chat_id=settings.admin_chat_id,
            message=message,
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
        await framework_error_reporting.notify_admin_about_exception(
            update,
            context,
            admin_chat_id=settings.admin_chat_id,
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
    log_context_fn: Callable[[Optional[Update]], dict] = framework_policy.log_context,
    storage_id_fn: Callable[[Update], Optional[str]] = framework_policy.storage_id,
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
            return framework_policy.is_allowed(
                update,
                settings_getter=settings_getter,
                logger_override=logger,
                log_context_fn=log_context_fn,
            )

    summary_handler = bot_features.build_summary_handler(
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

    events_handler = bot_features.build_events_handler(
        is_allowed_fn=is_allowed_fn,
        provider_getter=provider_getter,
        notify_admin_fn=_notify_admin_proxy,
        log_context_fn=log_context_fn,
        settings_getter=lambda: settings_getter(),
        logger_override=logger,
    )

    message_flow = bot_features.build_message_flow(
        settings_getter=settings_getter,
        provider_getter=provider_getter,
        is_allowed_fn=is_allowed_fn,
        storage_id_fn=storage_id_fn,
        add_message_fn=add_message_fn,
        get_all_messages_fn=get_all_messages_fn,
        get_message_by_telegram_message_id_fn=get_message_by_telegram_message_id_fn,
        build_context_fn=build_context_fn,
        assemble_context_fn=assemble_context_fn,
        log_context_fn=log_context_fn,
        logger_override=logger,
    )

    runtime = BotRuntime(
        settings_getter=settings_getter,
        provider_getter=provider_getter,
        reaction_service=message_flow.reaction_service,
        summary_handler=summary_handler,
        message_handler=message_flow.message_handler,
        events_handler=events_handler,
        is_allowed_fn=is_allowed_fn,
        log_context_fn=log_context_fn,
    )
    return runtime


def register_handlers(
    app: Application,
    runtime: BotRuntime,
    *,
    settings: config.Settings,
) -> None:
    bot_features.register_handlers(
        app,
        runtime=runtime,
        settings=settings,
    )


def build_application(
    runtime: BotRuntime,
    *,
    settings: Optional[config.Settings] = None,
) -> Application:
    active_settings = settings or runtime.get_settings()
    runtime.apply_log_level(active_settings)

    return framework_application.build_application(
        token=active_settings.telegram_bot_token,
        error_handler=runtime.error_handler,
        register_handlers=lambda app: register_handlers(
            app,
            runtime,
            settings=active_settings,
        ),
        application_builder_factory=ApplicationBuilder,
    )


def run_polling(runtime: Optional[BotRuntime] = None) -> None:
    active_runtime = runtime or build_runtime()
    polling_runtime = PollingRuntime(
        settings_getter=active_runtime.get_settings,
        build_application_fn=lambda settings: build_application(
            active_runtime,
            settings=settings,
        ),
        logger_override=logger,
        startup_log_value_fn=lambda settings: settings.features,
    )
    polling_runtime.run_polling()


def run(
    *,
    settings_getter: Callable[..., config.Settings] = config.get_settings,
    runtime: Optional[BotRuntime] = None,
) -> None:
    active_runtime = runtime or build_runtime(settings_getter=settings_getter)
    logging_utils.configure_logging(active_runtime.get_settings())
    run_polling(runtime=active_runtime)
