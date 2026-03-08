from types import SimpleNamespace

from src import provider_factory
from src.model_provider import ModelProvider
from src.provider_factory import RoutedModelProvider
from src.providers.contracts import (
    AudioTranscriptionRequest,
    ImageToEventRequest,
    ImageToTextRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
)


class _OkProvider(ModelProvider):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"t:{request.audio_path}"

    def generate_text(self, request: TextGenerationRequest) -> str:
        return f"g:{request.prompt}"

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return f"lc:{request.prompt}"

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        return request.allowed_reactions[0]

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        return {"path": request.image_path}

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return f"{request.mime_type}:{len(request.image_bytes)}"


class _FailGenerateProvider(_OkProvider):
    def generate_text(self, request: TextGenerationRequest) -> str:
        _ = request
        raise RuntimeError("boom")


class _FailGenerateStreamProvider(_OkProvider):
    def generate_text_stream(self, request: TextGenerationRequest):
        _ = request
        raise RuntimeError("boom")


class _PartialFailGenerateStreamProvider(_OkProvider):
    def generate_text_stream(self, request: TextGenerationRequest):
        _ = request
        yield "partial"
        raise RuntimeError("boom")


class _FallbackTranscribeProvider(_OkProvider):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"fallback:{request.audio_path}"


class _FailReactionProvider(_OkProvider):
    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        _ = request
        raise RuntimeError("boom")


class _CaptureReactionProvider(_OkProvider):
    def __init__(self) -> None:
        self.last_context = ""

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        self.last_context = request.context_text
        return super().select_reaction(request)


class _OpenAIProvider(_OkProvider):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"openai:{request.audio_path}"

    def generate_text(self, request: TextGenerationRequest) -> str:
        return f"openai:{request.prompt}"


class _GeminiProvider(_OkProvider):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"gemini:{request.audio_path}"

    def generate_text(self, request: TextGenerationRequest) -> str:
        return f"gemini:{request.prompt}"


def test_routed_provider_falls_back_on_generate_error() -> None:
    provider = RoutedModelProvider(
        primary=_FailGenerateProvider(), fallback=_OkProvider()
    )
    assert provider.generate("hello") == "g:hello"


def test_routed_provider_uses_fallback_for_transcribe_when_forced() -> None:
    provider = RoutedModelProvider(
        primary=_OkProvider(),
        fallback=_FallbackTranscribeProvider(),
        transcribe_use_fallback=True,
    )
    assert provider.transcribe("voice.ogg") == "fallback:voice.ogg"


def test_routed_provider_falls_back_on_generate_stream_error() -> None:
    provider = RoutedModelProvider(
        primary=_FailGenerateStreamProvider(), fallback=_OkProvider()
    )

    assert list(provider.generate_stream("hello")) == ["g:hello"]


def test_routed_provider_returns_partial_stream_if_primary_fails_after_emitting() -> (
    None
):
    provider = RoutedModelProvider(
        primary=_PartialFailGenerateStreamProvider(),
        fallback=_OkProvider(),
    )

    assert list(provider.generate_stream("hello")) == ["partial"]


def test_routed_provider_forwards_reaction_context_to_fallback() -> None:
    fallback = _CaptureReactionProvider()
    provider = RoutedModelProvider(primary=_FailReactionProvider(), fallback=fallback)

    reaction = provider.choose_reaction("hello", ["😀"], context_text="Alice: hi")

    assert reaction == "😀"
    assert fallback.last_context == "Alice: hi"


def test_build_provider_openai_uses_gemini_transcribe_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_factory.config,
        "get_settings",
        lambda: SimpleNamespace(
            model_provider="openai",
            gemini_api_key="gem-key",
            openai_api_key="openai-key",
            openai_auth_json_path="",
        ),
    )
    monkeypatch.setattr(provider_factory, "OpenAIProvider", _OpenAIProvider)
    monkeypatch.setattr(provider_factory, "GeminiProvider", _GeminiProvider)

    routed = provider_factory.build_provider()

    assert routed.generate("ping") == "openai:ping"
    assert routed.transcribe("voice.ogg") == "gemini:voice.ogg"


def test_build_provider_openai_without_fallback_keeps_primary_transcribe(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_factory.config,
        "get_settings",
        lambda: SimpleNamespace(
            model_provider="openai",
            gemini_api_key="",
            openai_api_key="openai-key",
            openai_auth_json_path="",
        ),
    )
    monkeypatch.setattr(provider_factory, "OpenAIProvider", _OpenAIProvider)
    monkeypatch.setattr(provider_factory, "GeminiProvider", _GeminiProvider)

    routed = provider_factory.build_provider()

    assert routed.generate("ping") == "openai:ping"
    assert routed.transcribe("voice.ogg") == "openai:voice.ogg"


def test_build_provider_gemini_keeps_primary_transcribe_even_with_openai_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_factory.config,
        "get_settings",
        lambda: SimpleNamespace(
            model_provider="gemini",
            gemini_api_key="gem-key",
            openai_api_key="openai-key",
            openai_auth_json_path="",
        ),
    )
    monkeypatch.setattr(provider_factory, "OpenAIProvider", _OpenAIProvider)
    monkeypatch.setattr(provider_factory, "GeminiProvider", _GeminiProvider)

    routed = provider_factory.build_provider()

    assert routed.generate("ping") == "gemini:ping"
    assert routed.transcribe("voice.ogg") == "gemini:voice.ogg"
