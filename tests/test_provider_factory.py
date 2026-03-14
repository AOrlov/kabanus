from types import SimpleNamespace

import pytest

from src import provider_factory
from src.provider_factory import RoutedModelProvider
from src.providers.contracts import (
    AudioTranscriptionRequest,
    ImageToEventRequest,
    ImageToTextRequest,
    ProviderRouting,
    ReactionSelectionRequest,
    TextGenerationRequest,
)
from src.providers.errors import ProviderCapabilityError, ProviderConfigurationError


class _OpenAIProvider:
    def __init__(self, settings) -> None:
        self.settings = settings

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"openai:{request.audio_path}"

    def generate_text_stream(self, request: TextGenerationRequest):
        yield f"openai-stream:{request.prompt}"

    def generate_text(self, request: TextGenerationRequest) -> str:
        return f"openai:{request.prompt}"

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return f"openai-low:{request.prompt}"

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        return request.allowed_reactions[0]

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        return {"provider": "openai", "path": request.image_path}

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return f"openai:{request.mime_type}:{len(request.image_bytes)}"


class _GeminiProvider:
    def __init__(self, settings) -> None:
        self.settings = settings

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"gemini:{request.audio_path}"

    def generate_text(self, request: TextGenerationRequest) -> str:
        return f"gemini:{request.prompt}"

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return f"gemini-low:{request.prompt}"

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        return request.allowed_reactions[-1]

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        return {"provider": "gemini", "path": request.image_path}

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return f"gemini:{request.mime_type}:{len(request.image_bytes)}"


def _settings(
    routing: ProviderRouting,
    *,
    openai_configured: bool = True,
    gemini_configured: bool = True,
):
    return SimpleNamespace(
        provider_routing=routing,
        ai=SimpleNamespace(
            openai=SimpleNamespace(configured=openai_configured),
            gemini=SimpleNamespace(configured=gemini_configured),
        ),
    )


def test_routed_provider_dispatches_to_configured_capability_provider() -> None:
    provider = RoutedModelProvider(
        text_generation=_OpenAIProvider(None),
        streaming_text_generation=_OpenAIProvider(None),
        low_cost_text_generation=_GeminiProvider(None),
        audio_transcription=_GeminiProvider(None),
        ocr=_OpenAIProvider(None),
        reaction_selection=_GeminiProvider(None),
        event_parsing=_OpenAIProvider(None),
    )

    assert (
        provider.generate_text(TextGenerationRequest(prompt="hello")) == "openai:hello"
    )
    assert list(
        provider.generate_text_stream(TextGenerationRequest(prompt="hello"))
    ) == ["openai-stream:hello"]
    assert (
        provider.generate_low_cost_text(TextGenerationRequest(prompt="hello"))
        == "gemini-low:hello"
    )
    assert (
        provider.transcribe_audio(AudioTranscriptionRequest(audio_path="voice.ogg"))
        == "gemini:voice.ogg"
    )
    assert (
        provider.extract_image_text(
            ImageToTextRequest(image_bytes=b"abc", mime_type="image/png")
        )
        == "openai:image/png:3"
    )
    assert (
        provider.select_reaction(
            ReactionSelectionRequest(message="hi", allowed_reactions=["😀", "😴"])
        )
        == "😴"
    )
    assert provider.parse_image_event(ImageToEventRequest(image_path="event.jpg")) == {
        "provider": "openai",
        "path": "event.jpg",
    }


def test_build_provider_uses_explicit_capability_routes(monkeypatch) -> None:
    settings = _settings(
        ProviderRouting(
            text_generation="openai",
            streaming_text_generation="openai",
            low_cost_text_generation="gemini",
            audio_transcription="gemini",
            ocr="openai",
            reaction_selection="gemini",
            event_parsing="openai",
        )
    )
    captured = {"openai": [], "gemini": []}

    def _openai_factory(configured_settings):
        captured["openai"].append(configured_settings)
        return _OpenAIProvider(configured_settings)

    def _gemini_factory(configured_settings):
        captured["gemini"].append(configured_settings)
        return _GeminiProvider(configured_settings)

    provider = provider_factory.build_provider_for_settings(
        settings,
        openai_factory=_openai_factory,
        gemini_factory=_gemini_factory,
    )

    assert captured["openai"] == [settings]
    assert captured["gemini"] == [settings]
    assert provider.generate_text(TextGenerationRequest(prompt="ping")) == "openai:ping"
    assert list(
        provider.generate_text_stream(TextGenerationRequest(prompt="ping"))
    ) == ["openai-stream:ping"]
    assert (
        provider.generate_low_cost_text(TextGenerationRequest(prompt="ping"))
        == "gemini-low:ping"
    )
    assert (
        provider.transcribe_audio(AudioTranscriptionRequest(audio_path="voice.ogg"))
        == "gemini:voice.ogg"
    )


def test_build_provider_rejects_missing_credentials_for_routed_provider() -> None:
    settings = _settings(
        ProviderRouting(
            text_generation="openai",
            streaming_text_generation="openai",
            low_cost_text_generation="openai",
            audio_transcription="gemini",
            ocr="openai",
            reaction_selection="openai",
            event_parsing="openai",
        ),
        gemini_configured=False,
    )

    with pytest.raises(ProviderConfigurationError, match="Gemini credentials"):
        provider_factory.build_provider_for_settings(
            settings,
            openai_factory=_OpenAIProvider,
            gemini_factory=_GeminiProvider,
        )


def test_build_provider_rejects_unsupported_capability_route() -> None:
    settings = _settings(
        ProviderRouting(
            text_generation="openai",
            streaming_text_generation="gemini",
            low_cost_text_generation="openai",
            audio_transcription="gemini",
            ocr="openai",
            reaction_selection="openai",
            event_parsing="openai",
        )
    )

    with pytest.raises(ProviderCapabilityError, match="streaming_text_generation"):
        provider_factory.build_provider_for_settings(
            settings,
            openai_factory=_OpenAIProvider,
            gemini_factory=_GeminiProvider,
        )


def test_build_provider_uses_config_settings(monkeypatch) -> None:
    settings = _settings(
        ProviderRouting(
            text_generation="openai",
            streaming_text_generation="openai",
            low_cost_text_generation="openai",
            audio_transcription="gemini",
            ocr="openai",
            reaction_selection="openai",
            event_parsing="openai",
        )
    )
    monkeypatch.setattr(provider_factory.config, "get_settings", lambda: settings)
    monkeypatch.setattr(provider_factory, "OpenAIProvider", _OpenAIProvider)
    monkeypatch.setattr(provider_factory, "GeminiProvider", _GeminiProvider)

    provider = provider_factory.build_provider()

    assert provider.generate_text(TextGenerationRequest(prompt="ping")) == "openai:ping"
