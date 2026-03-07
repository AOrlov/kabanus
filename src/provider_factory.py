import logging
from typing import Callable, Optional, TypeVar

from src import config
from src.gemini_provider import GeminiProvider
from src.model_provider import ModelProvider
from src.openai_provider import OpenAIProvider
from src.providers.contracts import (
    AudioTranscriptionRequest,
    ImageToEventRequest,
    ImageToTextRequest,
    ProviderRouting,
    ReactionSelectionRequest,
    TextGenerationRequest,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class RoutedModelProvider(ModelProvider):
    def __init__(
        self,
        primary: ModelProvider,
        fallback: Optional[ModelProvider],
        *,
        transcribe_use_fallback: bool = False,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._transcribe_use_fallback = transcribe_use_fallback

    def _call(
        self,
        op_name: str,
        request: R,
        primary_fn: Callable[[ModelProvider, R], T],
        fallback_fn: Optional[Callable[[ModelProvider, R], T]] = None,
    ) -> T:
        try:
            return primary_fn(self._primary, request)
        except Exception as exc:
            if self._fallback is None or fallback_fn is None:
                raise
            logger.warning(
                "Primary provider operation failed, falling back",
                extra={"operation": op_name, "error": str(exc)},
            )
            return fallback_fn(self._fallback, request)

    def transcribe(self, audio_path: str) -> str:
        request = AudioTranscriptionRequest(audio_path=audio_path)
        if self._transcribe_use_fallback and self._fallback is not None:
            return self._fallback.transcribe_audio(request)
        return self._primary.transcribe_audio(request)

    def generate(self, prompt: str) -> str:
        request = TextGenerationRequest(prompt=prompt)
        fallback_fn = (
            (lambda provider, typed_request: provider.generate_text(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "generate",
            request,
            lambda provider, typed_request: provider.generate_text(typed_request),
            fallback_fn,
        )

    def generate_stream(self, prompt: str):
        request = TextGenerationRequest(prompt=prompt)
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
                    extra={"operation": "generate_stream", "error": str(exc)},
                )
                return
            if self._fallback is None:
                raise
            logger.warning(
                "Primary provider operation failed, falling back",
                extra={"operation": "generate_stream", "error": str(exc)},
            )
            for chunk in self._fallback.generate_text_stream(request):
                yield chunk

    def generate_low_cost(self, prompt: str) -> str:
        request = TextGenerationRequest(prompt=prompt)
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
            "generate_low_cost",
            request,
            lambda provider, typed_request: provider.generate_low_cost_text(
                typed_request
            ),
            fallback_fn,
        )

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        request = ReactionSelectionRequest(
            message=message,
            allowed_reactions=allowed_reactions,
            context_text=context_text,
        )
        fallback_fn = (
            (lambda provider, typed_request: provider.select_reaction(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "choose_reaction",
            request,
            lambda provider, typed_request: provider.select_reaction(typed_request),
            fallback_fn,
        )

    def parse_image_to_event(self, image_path: str) -> dict:
        request = ImageToEventRequest(image_path=image_path)
        fallback_fn = (
            (lambda provider, typed_request: provider.parse_image_event(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "parse_image_to_event",
            request,
            lambda provider, typed_request: provider.parse_image_event(typed_request),
            fallback_fn,
        )

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        request = ImageToTextRequest(image_bytes=image_bytes, mime_type=mime_type)
        fallback_fn = (
            (lambda provider, typed_request: provider.extract_image_text(typed_request))
            if self._fallback is not None
            else None
        )
        return self._call(
            "image_to_text",
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
    openai_factory: Optional[Callable[[], ModelProvider]] = None,
    gemini_factory: Optional[Callable[[], ModelProvider]] = None,
) -> ModelProvider:
    if openai_factory is None:
        openai_factory = OpenAIProvider
    if gemini_factory is None:
        gemini_factory = GeminiProvider

    routing = resolve_provider_routing(settings)
    factories: dict[str, Callable[[], ModelProvider]] = {
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


def build_provider() -> ModelProvider:
    settings = config.get_settings()
    return build_provider_for_settings(settings)
