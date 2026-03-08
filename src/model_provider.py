"""Provider interface with typed-first methods and legacy convenience wrappers."""

from abc import ABC, abstractmethod
from typing import Iterator, Sequence

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

    # Legacy convenience wrappers retained for callers outside provider modules.
    def transcribe(self, audio_path: str) -> str:
        return self.transcribe_audio(AudioTranscriptionRequest(audio_path=audio_path))

    def generate(self, prompt: str) -> str:
        return self.generate_text(TextGenerationRequest(prompt=prompt))

    def generate_stream(self, prompt: str) -> Iterator[str]:
        return self.generate_text_stream(TextGenerationRequest(prompt=prompt))

    def generate_low_cost(self, prompt: str) -> str:
        return self.generate_low_cost_text(TextGenerationRequest(prompt=prompt))

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: Sequence[str],
        context_text: str = "",
    ) -> str:
        return self.select_reaction(
            ReactionSelectionRequest(
                message=message,
                allowed_reactions=allowed_reactions,
                context_text=context_text,
            )
        )

    def parse_image_to_event(self, image_path: str) -> EventPayload:
        return self.parse_image_event(ImageToEventRequest(image_path=image_path))

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        return self.extract_image_text(
            ImageToTextRequest(image_bytes=image_bytes, mime_type=mime_type)
        )
