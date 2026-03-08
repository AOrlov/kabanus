"""Provider interface based on explicit typed request contracts."""

from abc import ABC, abstractmethod
from typing import Iterator

from src.providers.contracts import (
    AudioTranscriptionRequest,
    EventPayload,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
)


class ModelProvider(ABC):
    @abstractmethod
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_text(self, request: TextGenerationRequest) -> str:
        raise NotImplementedError

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterator[str]:
        text = self.generate_text(request)
        if text:
            yield text

    @abstractmethod
    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        raise NotImplementedError

    @abstractmethod
    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        raise NotImplementedError

    @abstractmethod
    def parse_image_event(self, request: ImageToEventRequest) -> EventPayload:
        raise NotImplementedError

    @abstractmethod
    def extract_image_text(self, request: ImageToTextRequest) -> str:
        raise NotImplementedError
