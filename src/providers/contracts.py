"""Typed provider contracts used by routing and implementations."""

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Literal, Optional, Sequence

ProviderName = Literal["openai", "gemini"]
EventPayload = Dict[str, Any]


@dataclass(frozen=True)
class AudioTranscriptionRequest:
    audio_path: str


@dataclass(frozen=True)
class TextGenerationRequest:
    prompt: str


@dataclass(frozen=True)
class ReactionSelectionRequest:
    message: str
    allowed_reactions: Sequence[str]
    context_text: str = ""


@dataclass(frozen=True)
class ImageToEventRequest:
    image_path: str


@dataclass(frozen=True)
class ImageToTextRequest:
    image_bytes: bytes
    mime_type: str = "image/jpeg"


@dataclass(frozen=True)
class ProviderRouting:
    primary: ProviderName
    fallback: Optional[ProviderName]
    transcribe_use_fallback: bool


def build_reaction_prompt(request: ReactionSelectionRequest) -> str:
    prompt_parts = [f"Current message: {request.message}"]
    if request.context_text:
        prompt_parts.append(f"Recent context:\n{request.context_text}")
    prompt_parts.append(f"Allowed reactions: {', '.join(request.allowed_reactions)}")
    return "\n\n".join(prompt_parts)


class TypedProviderContract:
    """Documented typed surface layered on top of legacy provider methods."""

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        raise NotImplementedError

    def generate_text(self, request: TextGenerationRequest) -> str:
        raise NotImplementedError

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterator[str]:
        raise NotImplementedError

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        raise NotImplementedError

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        raise NotImplementedError

    def parse_image_event(self, request: ImageToEventRequest) -> EventPayload:
        raise NotImplementedError

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        raise NotImplementedError
