"""Legacy provider interface plus typed request wrappers."""

from typing import Iterator, List

from src.providers.contracts import (
    AudioTranscriptionRequest,
    EventPayload,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
    TypedProviderContract,
)


class ModelProvider(TypedProviderContract):
    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return self.transcribe(request.audio_path)

    def generate_stream(self, prompt: str) -> Iterator[str]:
        text = self.generate(prompt)
        if text:
            yield text

    def generate_text_stream(self, request: TextGenerationRequest) -> Iterator[str]:
        return self.generate_stream(request.prompt)

    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    def generate_text(self, request: TextGenerationRequest) -> str:
        return self.generate(request.prompt)

    def generate_low_cost(self, prompt: str) -> str:
        raise NotImplementedError

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return self.generate_low_cost(request.prompt)

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: List[str],
        context_text: str = "",
    ) -> str:
        raise NotImplementedError

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        return self.choose_reaction(
            message=request.message,
            allowed_reactions=list(request.allowed_reactions),
            context_text=request.context_text,
        )

    def parse_image_to_event(self, image_path: str) -> EventPayload:
        raise NotImplementedError

    def parse_image_event(self, request: ImageToEventRequest) -> EventPayload:
        return self.parse_image_to_event(request.image_path)

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        raise NotImplementedError

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return self.image_to_text(
            image_bytes=request.image_bytes,
            mime_type=request.mime_type,
        )
