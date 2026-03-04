import logging
from typing import Callable, Optional, TypeVar

from src import config
from src.gemini_provider import GeminiProvider
from src.model_provider import ModelProvider
from src.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")


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

    def _call(self, op_name: str, primary_fn: Callable[[], T], fallback_fn: Optional[Callable[[], T]] = None) -> T:
        try:
            return primary_fn()
        except Exception as exc:
            if fallback_fn is None:
                raise
            logger.warning(
                "Primary provider operation failed, falling back",
                extra={"operation": op_name, "error": str(exc)},
            )
            return fallback_fn()

    def transcribe(self, audio_path: str) -> str:
        if self._transcribe_use_fallback and self._fallback is not None:
            return self._fallback.transcribe(audio_path)
        return self._primary.transcribe(audio_path)

    def generate(self, prompt: str) -> str:
        fallback_fn = (lambda: self._fallback.generate(prompt)) if self._fallback is not None else None
        return self._call("generate", lambda: self._primary.generate(prompt), fallback_fn)

    def generate_stream(self, prompt: str):
        emitted = False
        try:
            for chunk in self._primary.generate_stream(prompt):
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
            for chunk in self._fallback.generate_stream(prompt):
                yield chunk

    def generate_low_cost(self, prompt: str) -> str:
        fallback_fn = (lambda: self._fallback.generate_low_cost(prompt)) if self._fallback is not None else None
        return self._call("generate_low_cost", lambda: self._primary.generate_low_cost(prompt), fallback_fn)

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        fallback_fn = (
            lambda: self._fallback.choose_reaction(
                message,
                allowed_reactions,
                context_text=context_text,
            )
        ) if self._fallback is not None else None
        return self._call(
            "choose_reaction",
            lambda: self._primary.choose_reaction(
                message,
                allowed_reactions,
                context_text=context_text,
            ),
            fallback_fn,
        )

    def parse_image_to_event(self, image_path: str) -> dict:
        fallback_fn = (lambda: self._fallback.parse_image_to_event(image_path)) if self._fallback is not None else None
        return self._call("parse_image_to_event", lambda: self._primary.parse_image_to_event(image_path), fallback_fn)

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        fallback_fn = (
            lambda: self._fallback.image_to_text(image_bytes, mime_type=mime_type)
        ) if self._fallback is not None else None
        return self._call(
            "image_to_text",
            lambda: self._primary.image_to_text(image_bytes, mime_type=mime_type),
            fallback_fn,
        )


def build_provider() -> ModelProvider:
    settings = config.get_settings()
    if settings.model_provider == "openai":
        gemini_fallback = GeminiProvider() if settings.gemini_api_key else None
        return RoutedModelProvider(
            primary=OpenAIProvider(),
            fallback=gemini_fallback,
            transcribe_use_fallback=gemini_fallback is not None,
        )
    fallback = OpenAIProvider() if (settings.openai_api_key or settings.openai_auth_json_path) else None
    return RoutedModelProvider(
        primary=GeminiProvider(),
        fallback=fallback,
        transcribe_use_fallback=False,
    )
