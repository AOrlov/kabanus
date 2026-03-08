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


def _provider_transcribe_audio(
    provider: ModelProvider, request: AudioTranscriptionRequest
) -> str:
    typed_fn = getattr(provider, "transcribe_audio", None)
    if callable(typed_fn):
        return typed_fn(request)
    return provider.transcribe(request.audio_path)


def _provider_generate_text(
    provider: ModelProvider, request: TextGenerationRequest
) -> str:
    typed_fn = getattr(provider, "generate_text", None)
    if callable(typed_fn):
        return typed_fn(request)
    return provider.generate(request.prompt)


def _provider_generate_text_stream(
    provider: ModelProvider, request: TextGenerationRequest
):
    typed_fn = getattr(provider, "generate_text_stream", None)
    if callable(typed_fn):
        return typed_fn(request)
    return provider.generate_stream(request.prompt)


def _provider_generate_low_cost_text(
    provider: ModelProvider,
    request: TextGenerationRequest,
) -> str:
    typed_fn = getattr(provider, "generate_low_cost_text", None)
    if callable(typed_fn):
        return typed_fn(request)
    return provider.generate_low_cost(request.prompt)


def _provider_select_reaction(
    provider: ModelProvider,
    request: ReactionSelectionRequest,
) -> str:
    typed_fn = getattr(provider, "select_reaction", None)
    if callable(typed_fn):
        return typed_fn(request)
    return provider.choose_reaction(
        message=request.message,
        allowed_reactions=list(request.allowed_reactions),
        context_text=request.context_text,
    )


def _provider_parse_image_event(
    provider: ModelProvider, request: ImageToEventRequest
) -> dict:
    typed_fn = getattr(provider, "parse_image_event", None)
    if callable(typed_fn):
        return typed_fn(request)
    return provider.parse_image_to_event(request.image_path)


def _provider_extract_image_text(
    provider: ModelProvider, request: ImageToTextRequest
) -> str:
    typed_fn = getattr(provider, "extract_image_text", None)
    if callable(typed_fn):
        return typed_fn(request)
    return provider.image_to_text(
        image_bytes=request.image_bytes,
        mime_type=request.mime_type,
    )


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
            return _provider_transcribe_audio(self._fallback, request)
        return _provider_transcribe_audio(self._primary, request)

    def generate(self, prompt: str) -> str:
        request = TextGenerationRequest(prompt=prompt)
        fallback_fn = (
            (
                lambda provider, typed_request: _provider_generate_text(
                    provider, typed_request
                )
            )
            if self._fallback is not None
            else None
        )
        return self._call(
            "generate",
            request,
            lambda provider, typed_request: _provider_generate_text(
                provider, typed_request
            ),
            fallback_fn,
        )

    def generate_stream(self, prompt: str):
        request = TextGenerationRequest(prompt=prompt)
        emitted = False
        try:
            for chunk in _provider_generate_text_stream(self._primary, request):
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
            for chunk in _provider_generate_text_stream(self._fallback, request):
                yield chunk

    def generate_low_cost(self, prompt: str) -> str:
        request = TextGenerationRequest(prompt=prompt)
        fallback_fn = (
            (
                lambda provider, typed_request: _provider_generate_low_cost_text(
                    provider, typed_request
                )
            )
            if self._fallback is not None
            else None
        )
        return self._call(
            "generate_low_cost",
            request,
            lambda provider, typed_request: _provider_generate_low_cost_text(
                provider,
                typed_request,
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
            (
                lambda provider, typed_request: _provider_select_reaction(
                    provider, typed_request
                )
            )
            if self._fallback is not None
            else None
        )
        return self._call(
            "choose_reaction",
            request,
            lambda provider, typed_request: _provider_select_reaction(
                provider, typed_request
            ),
            fallback_fn,
        )

    def parse_image_to_event(self, image_path: str) -> dict:
        request = ImageToEventRequest(image_path=image_path)
        fallback_fn = (
            (
                lambda provider, typed_request: _provider_parse_image_event(
                    provider, typed_request
                )
            )
            if self._fallback is not None
            else None
        )
        return self._call(
            "parse_image_to_event",
            request,
            lambda provider, typed_request: _provider_parse_image_event(
                provider, typed_request
            ),
            fallback_fn,
        )

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        request = ImageToTextRequest(image_bytes=image_bytes, mime_type=mime_type)
        fallback_fn = (
            (
                lambda provider, typed_request: _provider_extract_image_text(
                    provider, typed_request
                )
            )
            if self._fallback is not None
            else None
        )
        return self._call(
            "image_to_text",
            request,
            lambda provider, typed_request: _provider_extract_image_text(
                provider, typed_request
            ),
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
