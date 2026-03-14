"""Typed provider request and routing contracts."""

from dataclasses import dataclass
from typing import Any, Dict, Literal, Sequence

ProviderName = Literal["openai", "gemini"]
CapabilityName = Literal[
    "text_generation",
    "streaming_text_generation",
    "low_cost_text_generation",
    "audio_transcription",
    "ocr",
    "reaction_selection",
    "event_parsing",
]
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
    text_generation: ProviderName
    streaming_text_generation: ProviderName
    low_cost_text_generation: ProviderName
    audio_transcription: ProviderName
    ocr: ProviderName
    reaction_selection: ProviderName
    event_parsing: ProviderName

    def provider_for(self, capability: CapabilityName) -> ProviderName:
        return getattr(self, capability)


def build_reaction_prompt(request: ReactionSelectionRequest) -> str:
    prompt_parts = [f"Current message: {request.message}"]
    if request.context_text:
        prompt_parts.append(f"Recent context:\n{request.context_text}")
    prompt_parts.append(f"Allowed reactions: {', '.join(request.allowed_reactions)}")
    return "\n\n".join(prompt_parts)
