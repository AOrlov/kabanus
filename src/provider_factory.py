import logging
from typing import Callable, Iterator, Optional, TypeVar

from src import config
from src.gemini_provider import GeminiProvider
from src.openai_provider import OpenAIProvider
from src.providers.capabilities import ProviderCapabilities
from src.providers.contracts import (
    AudioTranscriptionRequest,
    ImageToEventRequest,
    ImageToTextRequest,
    ProviderRouting,
    ReactionSelectionRequest,
    TextGenerationRequest,
)
from src.providers.errors import (
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderQuotaError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class RoutedModelProvider:
    def __init__(
        self,
        primary: ProviderCapabilities,
        fallback: Optional[ProviderCapabilities],
        *,
        transcribe_use_fallback: bool = False,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._transcribe_use_fallback = transcribe_use_fallback

    def _should_raise_without_fallback(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                ProviderAuthError,
                ProviderCapabilityError,
                ProviderConfigurationError,
                ProviderQuotaError,
            ),
        )

    def _call(
        self,
        op_name: str,
        request: R,
        primary_fn: Callable[[ProviderCapabilities, R], T],
        fallback_fn: Optional[Callable[[ProviderCapabilities, R], T]] = None,
    ) -> T:
        try:
            return primary_fn(self._primary, request)
        except Exception as exc:
            if (
                self._fallback is None
                or fallback_fn is None
                or self._should_raise_without_fallback(exc)
            ):
                raise
            logger.warning(
                "Primary provider operation failed, falling back",
                extra={"operation": op_name, "error": str(exc)},
            )
            return fallback_fn(self._fallback, request)

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        if self._transcribe_use_fallback and self._fallback is not None:
            return self._fallback.transcribe_audio(request)
        return self._primary.transcribe_audio(request)

    def generate_text(self, request: TextGenerationRequest) -> str:
        fallback_fn = (
            (lambda provider, typed_request: provider.generate_text(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "generate_text",
            request,
            lambda provider, typed_request: provider.generate_text(typed_request),
            fallback_fn,
        )

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterator[str]:
        emitted = False
        try:
            for chunk in self._primary.generate_text_stream(request):
                emitted = True
                yield chunk
            return
        except Exception as exc:
            if emitted:
                logger.warning(
                    "Primary provider stream failed after partial output; returning partial response",
                    extra={"operation": "generate_text_stream", "error": str(exc)},
                )
                return
            if self._fallback is None or self._should_raise_without_fallback(exc):
                raise
            logger.warning(
                "Primary provider operation failed, falling back",
                extra={"operation": "generate_text_stream", "error": str(exc)},
            )
            for chunk in self._fallback.generate_text_stream(request):
                yield chunk

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        fallback_fn = (
            (
                lambda provider, typed_request: provider.generate_low_cost_text(
                    typed_request
                )
            )
            if self._fallback is not None
            else None
        )
        return self._call(
            "generate_low_cost_text",
            request,
            lambda provider, typed_request: provider.generate_low_cost_text(
                typed_request
            ),
            fallback_fn,
        )

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        fallback_fn = (
            (lambda provider, typed_request: provider.select_reaction(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "select_reaction",
            request,
            lambda provider, typed_request: provider.select_reaction(typed_request),
            fallback_fn,
        )

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        fallback_fn = (
            (lambda provider, typed_request: provider.parse_image_event(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "parse_image_event",
            request,
            lambda provider, typed_request: provider.parse_image_event(typed_request),
            fallback_fn,
        )

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        fallback_fn = (
            (lambda provider, typed_request: provider.extract_image_text(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "extract_image_text",
            request,
            lambda provider, typed_request: provider.extract_image_text(typed_request),
            fallback_fn,
        )


def resolve_provider_routing(settings: config.Settings) -> ProviderRouting:
    if settings.model_provider == "openai":
        has_gemini_fallback = bool(settings.gemini_api_key)
        return ProviderRouting(
            primary="openai",
            fallback="gemini" if has_gemini_fallback else None,
            transcribe_use_fallback=has_gemini_fallback,
        )
    has_openai_fallback = bool(
        settings.openai_api_key or settings.openai_auth_json_path
    )
    return ProviderRouting(
        primary="gemini",
        fallback="openai" if has_openai_fallback else None,
        transcribe_use_fallback=False,
    )


def build_provider_for_settings(
    settings: config.Settings,
    *,
    openai_factory: Optional[Callable[[], ProviderCapabilities]] = None,
    gemini_factory: Optional[Callable[[], ProviderCapabilities]] = None,
) -> ProviderCapabilities:
    if openai_factory is None:
        openai_factory = OpenAIProvider
    if gemini_factory is None:
        gemini_factory = GeminiProvider

    routing = resolve_provider_routing(settings)
    factories: dict[str, Callable[[], ProviderCapabilities]] = {
        "openai": openai_factory,
        "gemini": gemini_factory,
    }
    primary = factories[routing.primary]()
    fallback = factories[routing.fallback]() if routing.fallback is not None else None
    return RoutedModelProvider(
        primary=primary,
        fallback=fallback,
        transcribe_use_fallback=routing.transcribe_use_fallback,
    )


def build_provider() -> ProviderCapabilities:
    settings = config.get_settings()
    return build_provider_for_settings(settings)
