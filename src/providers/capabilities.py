"""Capability-specific provider protocols."""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from src.providers.contracts import (
    AudioTranscriptionRequest,
    EventPayload,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
)


@runtime_checkable
class TextGenerationProvider(Protocol):
    def generate_text(self, request: TextGenerationRequest) -> str: ...


@runtime_checkable
class StreamingTextGenerationProvider(Protocol):
    def generate_text_stream(self, request: TextGenerationRequest) -> Iterable[str]: ...


@runtime_checkable
class LowCostTextGenerationProvider(Protocol):
    def generate_low_cost_text(self, request: TextGenerationRequest) -> str: ...


@runtime_checkable
class AudioTranscriptionProvider(Protocol):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str: ...


@runtime_checkable
class OcrProvider(Protocol):
    def extract_image_text(self, request: ImageToTextRequest) -> str: ...


@runtime_checkable
class ReactionSelectionProvider(Protocol):
    def select_reaction(self, request: ReactionSelectionRequest) -> str: ...


@runtime_checkable
class EventParsingProvider(Protocol):
    def parse_image_event(self, request: ImageToEventRequest) -> EventPayload: ...


@runtime_checkable
class ProviderCapabilities(
    TextGenerationProvider,
    StreamingTextGenerationProvider,
    LowCostTextGenerationProvider,
    AudioTranscriptionProvider,
    OcrProvider,
    ReactionSelectionProvider,
    EventParsingProvider,
    Protocol,
):
    """Composite protocol for runtime code that still needs all capabilities."""

