import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import config, provider_factory
from src.bot.contracts import (
    available_runtime_capabilities,
    compose_runtime_capabilities,
)
from src.providers.contracts import (
    AudioTranscriptionRequest,
    ImageToEventRequest,
    ImageToTextRequest,
    ProviderRouting,
    ReactionSelectionRequest,
    TextGenerationRequest,
)
from src.providers.errors import ProviderCapabilityError, ProviderConfigurationError
from src.providers.gemini import GeminiProvider
from src.providers.openai import OpenAIClientOptions, OpenAIProvider


def _settings(
    routing: ProviderRouting,
    *,
    openai_api_key: str = "openai-key",
    openai_auth_json_path: str = "",
    gemini_api_key: str = "gemini-key",
):
    openai_settings = SimpleNamespace(
        api_key=openai_api_key,
        auth_json_path=openai_auth_json_path,
        refresh_url="https://auth.openai.com/oauth/token",
        refresh_client_id="client-id",
        refresh_grant_type="refresh_token",
        auth_leeway_secs=60,
        auth_timeout_secs=20.0,
        codex_base_url="https://chatgpt.com/backend-api",
        codex_default_model="gpt-5.3-codex",
        text_model="gpt-5.3-codex",
        low_cost_model="gpt-5.3-mini",
        reaction_model="gpt-5.3-mini",
        transcription_model="gpt-4o-mini-transcribe",
        configured=bool(openai_api_key or openai_auth_json_path),
    )
    gemini_settings = SimpleNamespace(
        api_key=gemini_api_key,
        default_model="gemini-2.0-pro",
        low_cost_model="gemini-2.0-flash",
        reaction_model="gemma-3-27b-it",
        model_specs=[
            config.ModelSpec(name="gemini-2.0-pro", rpm=None, rpd=None),
            config.ModelSpec(name="gemini-2.0-flash", rpm=None, rpd=None),
            config.ModelSpec(name="gemma-3-27b-it", rpm=None, rpd=None),
        ],
        thinking_budget=0,
        use_google_search=False,
        system_instructions_path="",
        configured=bool(gemini_api_key),
    )
    return SimpleNamespace(
        provider_routing=routing,
        ai=SimpleNamespace(openai=openai_settings, gemini=gemini_settings),
        language="ru",
    )


class _OpenAIResponses:
    def __init__(self) -> None:
        self.create_calls = []
        self.stream_calls = []

    class _StreamManager:
        def __init__(self, outer, kwargs) -> None:
            self._outer = outer
            self._kwargs = kwargs

        def __enter__(self):
            self._outer.stream_calls.append(self._kwargs)
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            yield SimpleNamespace(type="response.output_text.delta", delta="open")
            yield SimpleNamespace(type="response.output_text.delta", delta="ai ")
            yield SimpleNamespace(type="response.output_text.delta", delta="stream")

        def until_done(self) -> None:
            return None

        def get_final_response(self):
            return SimpleNamespace(output_text="openai stream")

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(output_text="openai text reply")

    def stream(self, **kwargs):
        return self._StreamManager(self, kwargs)


class _OpenAIClientFactoryStub:
    def __init__(self, responses: _OpenAIResponses) -> None:
        self._client = SimpleNamespace(responses=responses)
        self._options = OpenAIClientOptions(api_key="openai-key")

    def get_client_context(self, *, force_refresh: bool = False):
        del force_refresh
        return self._client, self._options


class _GeminiModels:
    def __init__(self, responses_by_model) -> None:
        self._responses_by_model = {
            model_name: list(responses)
            for model_name, responses in responses_by_model.items()
        }
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        model_name = kwargs["model"]
        responses = self._responses_by_model.get(model_name, [])
        if not responses:
            raise AssertionError(f"unexpected Gemini model call: {model_name}")
        return responses.pop(0)


class _GeminiClientFactoryStub:
    def __init__(self, responses_by_model) -> None:
        self.client = SimpleNamespace(models=_GeminiModels(responses_by_model))

    def get_client(self):
        return self.client


class _StaticInstructionLoader:
    def __init__(self, text: str) -> None:
        self._text = text

    def load(self) -> str:
        return self._text


class _GeminiTranscriptionStub:
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"stub:{request.audio_path}"


class _OpenAIMessageFlowStub:
    def generate_text(self, request: TextGenerationRequest) -> str:
        return f"stub:{request.prompt}"

    def generate_text_stream(self, request: TextGenerationRequest):
        yield f"stub:{request.prompt}"

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return f"stub-low:{request.prompt}"

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        return request.allowed_reactions[0]


class _FullCapabilityProviderStub(_OpenAIMessageFlowStub):
    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return request.audio_path

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return request.mime_type

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        return {"image_path": request.image_path}


def test_acceptance_full_openai_composition_supports_all_capabilities(
    tmp_path: Path,
) -> None:
    routing = ProviderRouting(
        text_generation="openai",
        streaming_text_generation="openai",
        low_cost_text_generation="openai",
        audio_transcription="openai",
        ocr="openai",
        reaction_selection="openai",
        event_parsing="openai",
    )
    settings = _settings(routing, gemini_api_key="")
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice")

    provider = provider_factory.build_provider_for_settings(
        settings,
        openai_factory=lambda _configured_settings: _FullCapabilityProviderStub(),
        gemini_factory=lambda _configured_settings: pytest.fail(
            "gemini factory should not be used"
        ),
    )

    assert provider.generate_text(TextGenerationRequest(prompt="hello")) == "stub:hello"
    assert list(
        provider.generate_text_stream(TextGenerationRequest(prompt="hello"))
    ) == ["stub:hello"]
    assert (
        provider.generate_low_cost_text(TextGenerationRequest(prompt="hello"))
        == "stub-low:hello"
    )
    assert provider.transcribe_audio(
        AudioTranscriptionRequest(audio_path=str(audio_path))
    ) == str(audio_path)
    assert (
        provider.extract_image_text(
            ImageToTextRequest(image_bytes=b"image", mime_type="image/png")
        )
        == "image/png"
    )
    assert (
        provider.select_reaction(
            ReactionSelectionRequest(message="hi", allowed_reactions=["😀", "😴"])
        )
        == "😀"
    )
    assert provider.parse_image_event(ImageToEventRequest(image_path="event.png")) == {
        "image_path": "event.png"
    }


def test_acceptance_openai_text_and_streaming_work_through_routed_composition() -> None:
    routing = ProviderRouting(
        text_generation="openai",
        streaming_text_generation="openai",
        low_cost_text_generation="openai",
        audio_transcription="gemini",
        ocr="openai",
        reaction_selection="openai",
        event_parsing="openai",
    )
    settings = _settings(routing)
    responses = _OpenAIResponses()

    provider = provider_factory.build_provider_for_settings(
        settings,
        openai_factory=lambda configured_settings: OpenAIProvider(
            configured_settings,
            client_factory=_OpenAIClientFactoryStub(responses),
        ),
        gemini_factory=lambda _configured_settings: _GeminiTranscriptionStub(),
    )

    assert (
        provider.generate_text(TextGenerationRequest(prompt="hello"))
        == "openai text reply"
    )
    assert list(
        provider.generate_text_stream(TextGenerationRequest(prompt="hello"))
    ) == ["open", "openai ", "openai stream"]
    assert responses.create_calls[0]["model"] == "gpt-5.3-codex"
    assert responses.stream_calls[0]["model"] == "gpt-5.3-codex"


def test_acceptance_gemini_multimodal_capabilities_work_through_routed_composition(
    tmp_path: Path,
) -> None:
    routing = ProviderRouting(
        text_generation="openai",
        streaming_text_generation="openai",
        low_cost_text_generation="openai",
        audio_transcription="gemini",
        ocr="gemini",
        reaction_selection="openai",
        event_parsing="gemini",
    )
    settings = _settings(routing)
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice")
    image_path = tmp_path / "poster.png"
    image_path.write_bytes(b"poster")
    gemini_factory = _GeminiClientFactoryStub(
        {
            "gemini-2.0-pro": [
                SimpleNamespace(text="meeting transcript"),
                SimpleNamespace(text="poster text"),
                SimpleNamespace(
                    text='{"title":"Team Lunch","date":"2026-03-14","time":"12:00"}'
                ),
            ]
        }
    )

    provider = provider_factory.build_provider_for_settings(
        settings,
        openai_factory=lambda _configured_settings: _OpenAIMessageFlowStub(),
        gemini_factory=lambda configured_settings: GeminiProvider(
            configured_settings,
            client_factory=gemini_factory,
            instruction_loader=_StaticInstructionLoader("follow the checklist"),
        ),
    )

    assert (
        provider.transcribe_audio(AudioTranscriptionRequest(audio_path=str(audio_path)))
        == "meeting transcript"
    )
    assert (
        provider.extract_image_text(
            ImageToTextRequest(image_bytes=b"image", mime_type="image/png")
        )
        == "poster text"
    )
    assert provider.parse_image_event(
        ImageToEventRequest(image_path=str(image_path))
    ) == {
        "title": "Team Lunch",
        "date": "2026-03-14",
        "time": "12:00",
    }
    assert [call["model"] for call in gemini_factory.client.models.calls] == [
        "gemini-2.0-pro",
        "gemini-2.0-pro",
        "gemini-2.0-pro",
    ]


def test_acceptance_runtime_capability_listing_matches_available_composition() -> None:
    capabilities = compose_runtime_capabilities(_FullCapabilityProviderStub())

    assert list(available_runtime_capabilities(capabilities)) == [
        "text_generation",
        "streaming_text_generation",
        "low_cost_text_generation",
        "audio_transcription",
        "ocr",
        "reaction_selection",
        "event_parsing",
    ]


@pytest.mark.parametrize(
    ("auth_payload", "error_pattern"),
    [
        ("{", "not valid JSON"),
        ('{"kind":"missing-credentials"}', "access_token, api_key, or refresh_token"),
    ],
)
def test_acceptance_startup_fails_fast_for_invalid_openai_transcription_auth(
    tmp_path: Path,
    auth_payload: str,
    error_pattern: str,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(auth_payload, encoding="utf-8")
    if os.name != "nt":
        auth_file.chmod(0o600)

    settings = _settings(
        ProviderRouting(
            text_generation="openai",
            streaming_text_generation="openai",
            low_cost_text_generation="openai",
            audio_transcription="openai",
            ocr="openai",
            reaction_selection="openai",
            event_parsing="openai",
        ),
        openai_api_key="",
        openai_auth_json_path=str(auth_file),
        gemini_api_key="",
    )

    with pytest.raises(ProviderConfigurationError, match=error_pattern):
        provider_factory.build_capability_providers_for_settings(
            settings,
            required_capabilities=("audio_transcription",),
        )


@pytest.mark.parametrize(
    ("routing", "openai_api_key", "gemini_api_key", "error_type", "message"),
    [
        (
            ProviderRouting(
                text_generation="openai",
                streaming_text_generation="gemini",
                low_cost_text_generation="openai",
                audio_transcription="gemini",
                ocr="openai",
                reaction_selection="openai",
                event_parsing="openai",
            ),
            "openai-key",
            "gemini-key",
            ProviderCapabilityError,
            "streaming_text_generation",
        ),
        (
            ProviderRouting(
                text_generation="openai",
                streaming_text_generation="openai",
                low_cost_text_generation="openai",
                audio_transcription="gemini",
                ocr="openai",
                reaction_selection="openai",
                event_parsing="openai",
            ),
            "openai-key",
            "",
            ProviderConfigurationError,
            "Gemini credentials",
        ),
        (
            ProviderRouting(
                text_generation="openai",
                streaming_text_generation="openai",
                low_cost_text_generation="openai",
                audio_transcription="gemini",
                ocr="openai",
                reaction_selection="openai",
                event_parsing="openai",
            ),
            "",
            "gemini-key",
            ProviderConfigurationError,
            "OpenAI credentials",
        ),
    ],
)
def test_acceptance_startup_fails_with_clear_error_for_invalid_routing_or_missing_credentials(
    routing: ProviderRouting,
    openai_api_key: str,
    gemini_api_key: str,
    error_type: type[Exception],
    message: str,
) -> None:
    settings = _settings(
        routing,
        openai_api_key=openai_api_key,
        gemini_api_key=gemini_api_key,
    )

    with pytest.raises(error_type, match=message):
        provider_factory.build_provider_for_settings(settings)
