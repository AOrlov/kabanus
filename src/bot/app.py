import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, cast

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
)

from src import config, logging_utils
from src.bot import features as bot_features
from src.bot.contracts import (
    EventsCapabilities,
    MessageFlowCapabilities,
    RuntimeCapabilities,
    available_runtime_capabilities,
    compose_runtime_capabilities,
)
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
from src.provider_factory import build_capability_providers_for_settings
from src.providers.capabilities import (
    AudioTranscriptionProvider,
    EventParsingProvider,
    LowCostTextGenerationProvider,
    OcrProvider,
    ReactionSelectionProvider,
    StreamingTextGenerationProvider,
    TextGenerationProvider,
)
from src.providers.contracts import CapabilityName
from src.providers.errors import ProviderConfigurationError
from src.providers.gemini import GeminiProvider
from src.providers.openai import OpenAIProvider
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
        capabilities: RuntimeCapabilities,
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
        self._capabilities = capabilities
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

    @property
    def capabilities(self) -> RuntimeCapabilities:
        return self._capabilities

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
            "Available AI capabilities: "
            + ", ".join(available_runtime_capabilities(self._capabilities))
        )
        await update.message.reply_text(
            "Configured AI routing: "
            f"text={settings.provider_routing.text_generation}, "
            f"stream={settings.provider_routing.streaming_text_generation}, "
            f"low_cost={settings.provider_routing.low_cost_text_generation}, "
            f"audio={settings.provider_routing.audio_transcription}, "
            f"ocr={settings.provider_routing.ocr}, "
            f"reaction={settings.provider_routing.reaction_selection}, "
            f"events={settings.provider_routing.event_parsing}"
        )

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


def _provider_name_for_capability(
    settings: config.Settings,
    capability: CapabilityName,
) -> str:
    routing = getattr(settings, "provider_routing", None)
    if routing is not None and hasattr(routing, "provider_for"):
        return str(routing.provider_for(capability))
    return str(getattr(settings, "model_provider", "openai"))


def _require_runtime_capability(
    settings: config.Settings,
    capability: CapabilityName,
    available: object,
) -> None:
    if available is not None:
        return
    raise ProviderConfigurationError(
        (
            "Runtime requires capability "
            f"'{capability}', but it is not available in the assembled provider composition"
        ),
        provider=_provider_name_for_capability(settings, capability),  # type: ignore[arg-type]
        capability=capability,
    )


def _validate_runtime_capabilities(
    settings: config.Settings,
    capabilities: RuntimeCapabilities,
) -> None:
    features = getattr(settings, "features", {})
    if features.get("message_handling"):
        _require_runtime_capability(
            settings,
            "text_generation",
            capabilities.message_flow.text_generation,
        )
        _require_runtime_capability(
            settings,
            "low_cost_text_generation",
            capabilities.message_flow.low_cost_text_generation,
        )
        _require_runtime_capability(
            settings,
            "audio_transcription",
            capabilities.message_flow.audio_transcription,
        )
        _require_runtime_capability(
            settings,
            "ocr",
            capabilities.message_flow.ocr,
        )
        if getattr(settings, "telegram_use_message_drafts", False):
            _require_runtime_capability(
                settings,
                "streaming_text_generation",
                capabilities.message_flow.streaming_text_generation,
            )
    if getattr(settings, "reaction_enabled", False):
        _require_runtime_capability(
            settings,
            "reaction_selection",
            capabilities.message_flow.reaction_selection,
        )
    if features.get("schedule_events"):
        _require_runtime_capability(
            settings,
            "event_parsing",
            capabilities.events.event_parsing,
        )


def _required_runtime_capabilities(settings: config.Settings) -> tuple[CapabilityName, ...]:
    required: list[CapabilityName] = []
    features = getattr(settings, "features", {})

    if features.get("message_handling"):
        required.extend(
            [
                "text_generation",
                "low_cost_text_generation",
                "audio_transcription",
                "ocr",
            ]
        )
        if getattr(settings, "telegram_use_message_drafts", False):
            required.append("streaming_text_generation")
    if getattr(settings, "reaction_enabled", False):
        required.append("reaction_selection")
    if features.get("schedule_events"):
        required.append("event_parsing")
    return tuple(required)


def _compose_runtime_capabilities_from_map(
    capability_providers: dict[CapabilityName, object],
) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        message_flow=MessageFlowCapabilities(
            text_generation=cast(
                Optional[TextGenerationProvider],
                capability_providers.get("text_generation"),
            ),
            streaming_text_generation=cast(
                Optional[StreamingTextGenerationProvider],
                capability_providers.get("streaming_text_generation"),
            ),
            low_cost_text_generation=cast(
                Optional[LowCostTextGenerationProvider],
                capability_providers.get("low_cost_text_generation"),
            ),
            audio_transcription=cast(
                Optional[AudioTranscriptionProvider],
                capability_providers.get("audio_transcription"),
            ),
            ocr=cast(
                Optional[OcrProvider],
                capability_providers.get("ocr"),
            ),
            reaction_selection=cast(
                Optional[ReactionSelectionProvider],
                capability_providers.get("reaction_selection"),
            ),
        ),
        events=EventsCapabilities(
            event_parsing=cast(
                Optional[EventParsingProvider],
                capability_providers.get("event_parsing"),
            )
        ),
    )


def build_runtime(
    *,
    settings_getter: Callable[..., config.Settings] = config.get_settings,
    provider: Optional[object] = None,
    capabilities: Optional[RuntimeCapabilities] = None,
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
    settings_resolver = SettingsResolver(settings_getter)
    settings = settings_resolver.get()
    required_capabilities = _required_runtime_capabilities(settings)
    provider_instance = provider
    runtime_capabilities = capabilities
    runtime: Optional[BotRuntime] = None
    if runtime_capabilities is None:
        if provider_instance is not None:
            runtime_capabilities = compose_runtime_capabilities(provider_instance)
        elif required_capabilities:
            capability_providers = build_capability_providers_for_settings(
                settings,
                required_capabilities=required_capabilities,
                openai_factory=lambda _configured_settings: OpenAIProvider(
                    settings_resolver.get
                ),
                gemini_factory=lambda _configured_settings: GeminiProvider(
                    settings_resolver.get
                ),
            )
            runtime_capabilities = _compose_runtime_capabilities_from_map(
                capability_providers
            )
        else:
            runtime_capabilities = RuntimeCapabilities()
    _validate_runtime_capabilities(settings, runtime_capabilities)

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
        capabilities=runtime_capabilities.events,
        notify_admin_fn=_notify_admin_proxy,
        log_context_fn=log_context_fn,
        settings_getter=lambda: settings_getter(),
        logger_override=logger,
    )

    message_flow = bot_features.build_message_flow(
        settings_getter=settings_getter,
        capabilities=runtime_capabilities.message_flow,
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
        capabilities=runtime_capabilities,
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
    application_builder_factory: Optional[Callable[[], Any]] = None,
) -> Application:
    active_settings = settings or runtime.get_settings()
    runtime.apply_log_level(active_settings)
    active_application_builder_factory = (
        application_builder_factory or ApplicationBuilder
    )

    return framework_application.build_application(
        token=active_settings.telegram_bot_token,
        error_handler=runtime.error_handler,
        register_handlers=lambda app: register_handlers(
            app,
            runtime,
            settings=active_settings,
        ),
        application_builder_factory=active_application_builder_factory,
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
