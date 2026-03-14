import logging
from typing import Callable, Dict, Iterable, Optional, cast

from src import config
from src.providers.capabilities import (
    AudioTranscriptionProvider,
    EventParsingProvider,
    LowCostTextGenerationProvider,
    OcrProvider,
    ProviderCapabilities,
    ReactionSelectionProvider,
    StreamingTextGenerationProvider,
    TextGenerationProvider,
)
from src.providers.contracts import (
    AudioTranscriptionRequest,
    CapabilityName,
    ImageToEventRequest,
    ImageToTextRequest,
    ProviderRouting,
    ReactionSelectionRequest,
    TextGenerationRequest,
)
from src.providers.errors import ProviderCapabilityError, ProviderConfigurationError
from src.providers.gemini import GeminiProvider
from src.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)

_CAPABILITIES: tuple[CapabilityName, ...] = (
    "text_generation",
    "streaming_text_generation",
    "low_cost_text_generation",
    "audio_transcription",
    "ocr",
    "reaction_selection",
    "event_parsing",
)

_PROVIDER_SUPPORTED_CAPABILITIES = {
    "openai": frozenset(
        {
            "text_generation",
            "streaming_text_generation",
            "low_cost_text_generation",
            "ocr",
            "reaction_selection",
            "event_parsing",
        }
    ),
    "gemini": frozenset(
        {
            "text_generation",
            "low_cost_text_generation",
            "audio_transcription",
            "ocr",
            "reaction_selection",
            "event_parsing",
        }
    ),
}

_PROTOCOL_BY_CAPABILITY = {
    "text_generation": TextGenerationProvider,
    "streaming_text_generation": StreamingTextGenerationProvider,
    "low_cost_text_generation": LowCostTextGenerationProvider,
    "audio_transcription": AudioTranscriptionProvider,
    "ocr": OcrProvider,
    "reaction_selection": ReactionSelectionProvider,
    "event_parsing": EventParsingProvider,
}


class RoutedModelProvider:
    def __init__(
        self,
        *,
        text_generation: TextGenerationProvider,
        streaming_text_generation: StreamingTextGenerationProvider,
        low_cost_text_generation: LowCostTextGenerationProvider,
        audio_transcription: AudioTranscriptionProvider,
        ocr: OcrProvider,
        reaction_selection: ReactionSelectionProvider,
        event_parsing: EventParsingProvider,
    ) -> None:
        self._text_generation = text_generation
        self._streaming_text_generation = streaming_text_generation
        self._low_cost_text_generation = low_cost_text_generation
        self._audio_transcription = audio_transcription
        self._ocr = ocr
        self._reaction_selection = reaction_selection
        self._event_parsing = event_parsing

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return self._audio_transcription.transcribe_audio(request)

    def generate_text(self, request: TextGenerationRequest) -> str:
        return self._text_generation.generate_text(request)

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterable[str]:
        return self._streaming_text_generation.generate_text_stream(request)

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return self._low_cost_text_generation.generate_low_cost_text(request)

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        return self._reaction_selection.select_reaction(request)

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        return self._event_parsing.parse_image_event(request)

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return self._ocr.extract_image_text(request)


def resolve_provider_routing(settings: config.Settings) -> ProviderRouting:
    return settings.provider_routing


def _provider_is_configured(settings: config.Settings, provider_name: str) -> bool:
    if provider_name == "openai":
        return settings.ai.openai.configured
    return settings.ai.gemini.configured


def _capability_scope(
    required_capabilities: Optional[Iterable[CapabilityName]] = None,
) -> tuple[CapabilityName, ...]:
    if required_capabilities is None:
        return _CAPABILITIES
    selected = set(required_capabilities)
    return tuple(capability for capability in _CAPABILITIES if capability in selected)


def _validate_routing(
    settings: config.Settings,
    routing: ProviderRouting,
    *,
    required_capabilities: Optional[Iterable[CapabilityName]] = None,
) -> None:
    for capability in _capability_scope(required_capabilities):
        provider_name = routing.provider_for(capability)
        if not _provider_is_configured(settings, provider_name):
            if provider_name == "openai":
                message = (
                    "Capability routing requires OpenAI credentials, but "
                    "OPENAI_API_KEY or OPENAI_AUTH_JSON_PATH is missing"
                )
            else:
                message = (
                    "Capability routing requires Gemini credentials, but "
                    "GEMINI_API_KEY or GOOGLE_API_KEY is missing"
                )
            raise ProviderConfigurationError(
                message,
                provider=provider_name,
                capability=capability,
            )
        if capability not in _PROVIDER_SUPPORTED_CAPABILITIES[provider_name]:
            raise ProviderCapabilityError(
                f"Capability '{capability}' is not supported by provider '{provider_name}'",
                provider=provider_name,
                capability=capability,
            )


def _resolve_capability_provider(
    routing: ProviderRouting,
    providers_by_name: Dict[str, object],
    capability: CapabilityName,
) -> object:
    provider_name = routing.provider_for(capability)
    provider = providers_by_name[provider_name]
    protocol = _PROTOCOL_BY_CAPABILITY[capability]
    if not isinstance(provider, protocol):
        raise ProviderCapabilityError(
            f"Provider '{provider_name}' does not implement capability '{capability}'",
            provider=provider_name,
            capability=capability,
        )
    return provider


def _providers_in_use(
    routing: ProviderRouting,
    *,
    required_capabilities: Optional[Iterable[CapabilityName]] = None,
) -> list[str]:
    ordered: list[str] = []
    for capability in _capability_scope(required_capabilities):
        provider_name = routing.provider_for(capability)
        if provider_name not in ordered:
            ordered.append(provider_name)
    return ordered


def build_capability_providers_for_settings(
    settings: config.Settings,
    *,
    required_capabilities: Iterable[CapabilityName],
    openai_factory: Optional[Callable[[config.Settings], object]] = None,
    gemini_factory: Optional[Callable[[config.Settings], object]] = None,
) -> Dict[CapabilityName, object]:
    routing = resolve_provider_routing(settings)
    scoped_capabilities = _capability_scope(required_capabilities)
    _validate_routing(
        settings,
        routing,
        required_capabilities=scoped_capabilities,
    )

    if openai_factory is None:
        openai_factory = OpenAIProvider
    if gemini_factory is None:
        gemini_factory = GeminiProvider

    providers_by_name: Dict[str, object] = {}
    for provider_name in _providers_in_use(
        routing,
        required_capabilities=scoped_capabilities,
    ):
        if provider_name == "openai":
            providers_by_name[provider_name] = openai_factory(settings)
        else:
            providers_by_name[provider_name] = gemini_factory(settings)

    capability_providers: Dict[CapabilityName, object] = {}
    for capability in scoped_capabilities:
        capability_providers[capability] = _resolve_capability_provider(
            routing,
            providers_by_name,
            capability,
        )

    return capability_providers


def build_provider_for_settings(
    settings: config.Settings,
    *,
    openai_factory: Optional[Callable[[config.Settings], object]] = None,
    gemini_factory: Optional[Callable[[config.Settings], object]] = None,
) -> ProviderCapabilities:
    capability_providers = build_capability_providers_for_settings(
        settings,
        required_capabilities=_CAPABILITIES,
        openai_factory=openai_factory,
        gemini_factory=gemini_factory,
    )
    routed_provider = RoutedModelProvider(
        text_generation=cast(
            TextGenerationProvider,
            capability_providers["text_generation"],
        ),
        streaming_text_generation=cast(
            StreamingTextGenerationProvider,
            capability_providers["streaming_text_generation"],
        ),
        low_cost_text_generation=cast(
            LowCostTextGenerationProvider,
            capability_providers["low_cost_text_generation"],
        ),
        audio_transcription=cast(
            AudioTranscriptionProvider,
            capability_providers["audio_transcription"],
        ),
        ocr=cast(
            OcrProvider,
            capability_providers["ocr"],
        ),
        reaction_selection=cast(
            ReactionSelectionProvider,
            capability_providers["reaction_selection"],
        ),
        event_parsing=cast(
            EventParsingProvider,
            capability_providers["event_parsing"],
        ),
    )
    logger.debug(
        "Built capability-routed provider",
        extra={"routing": resolve_provider_routing(settings)},
    )
    return routed_provider
