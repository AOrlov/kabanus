from types import SimpleNamespace

from src.provider_factory import (
    RoutedModelProvider,
    build_provider_for_settings,
    resolve_provider_routing,
)
from src.providers.capabilities import (
    AudioTranscriptionProvider,
    EventParsingProvider,
    LowCostTextGenerationProvider,
    OcrProvider,
    ProviderCapabilities,
    ReactionSelectionProvider,
    StreamingTextGenerationProvider,
    TextGenerationProvider,
)
from src.providers.contracts import (
    AudioTranscriptionRequest,
    ImageToEventRequest,
    ImageToTextRequest,
    ProviderRouting,
    ReactionSelectionRequest,
    TextGenerationRequest,
    build_reaction_prompt,
)
from src.providers.errors import ProviderAuthError, ProviderConfigurationError

# Contract note:
# - Stable compatibility contract is configuration behavior.
# - Provider/runtime API shape assertions here are characterization-only and may change.


class _ContractSpyProvider:
    def __init__(self) -> None:
        self.calls = []

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        self.calls.append(("transcribe_audio", request.audio_path))
        return f"t:{request.audio_path}"

    def generate_text_stream(self, request: TextGenerationRequest):
        self.calls.append(("generate_text_stream", request.prompt))
        yield f"stream:{request.prompt}"

    def generate_text(self, request: TextGenerationRequest) -> str:
        self.calls.append(("generate_text", request.prompt))
        return f"g:{request.prompt}"

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        self.calls.append(("generate_low_cost_text", request.prompt))
        return f"lc:{request.prompt}"

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        self.calls.append(
            (
                "select_reaction",
                request.message,
                list(request.allowed_reactions),
                request.context_text,
            )
        )
        return request.allowed_reactions[0]

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        self.calls.append(("parse_image_event", request.image_path))
        return {"path": request.image_path}

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        self.calls.append(
            ("extract_image_text", request.mime_type, len(request.image_bytes))
        )
        return f"{request.mime_type}:{len(request.image_bytes)}"


class _ConfigurableProvider:
    def __init__(
        self,
        name: str,
        *,
        fail_generate: bool = False,
        fail_reaction: bool = False,
        stream_mode: str = "ok",
    ) -> None:
        self.name = name
        self.fail_generate = fail_generate
        self.fail_reaction = fail_reaction
        self.stream_mode = stream_mode
        self.stream_calls = 0
        self.reaction_contexts: list[str] = []

    def transcribe_audio(self, request: AudioTranscriptionRequest) -> str:
        return f"{self.name}:{request.audio_path}"

    def generate_text(self, request: TextGenerationRequest) -> str:
        if self.fail_generate:
            raise RuntimeError("generate failed")
        return f"{self.name}:{request.prompt}"

    def generate_text_stream(self, request: TextGenerationRequest):
        self.stream_calls += 1
        if self.stream_mode == "fail":
            raise RuntimeError("stream failed")
        if self.stream_mode == "partial_fail":
            yield f"{self.name}-partial"
            raise RuntimeError("stream failed")
        yield f"{self.name}-full"

    def generate_low_cost_text(self, request: TextGenerationRequest) -> str:
        return f"{self.name}-low:{request.prompt}"

    def select_reaction(self, request: ReactionSelectionRequest) -> str:
        self.reaction_contexts.append(request.context_text)
        if self.fail_reaction:
            raise RuntimeError("reaction failed")
        return request.allowed_reactions[0]

    def parse_image_event(self, request: ImageToEventRequest) -> dict:
        return {"provider": self.name, "path": request.image_path}

    def extract_image_text(self, request: ImageToTextRequest) -> str:
        return f"{self.name}:{request.mime_type}:{len(request.image_bytes)}"


def test_build_reaction_prompt_contract() -> None:
    without_context = build_reaction_prompt(
        ReactionSelectionRequest(message="ship it", allowed_reactions=["😀", "😴"])
    )
    assert without_context == "Current message: ship it\n\nAllowed reactions: 😀, 😴"

    with_context = build_reaction_prompt(
        ReactionSelectionRequest(
            message="ship it",
            allowed_reactions=["😀", "😴"],
            context_text="Alice: deploy in 10 minutes",
        )
    )
    assert "Current message: ship it" in with_context
    assert "Recent context:\nAlice: deploy in 10 minutes" in with_context
    assert with_context.endswith("Allowed reactions: 😀, 😴")


def test_provider_capability_protocol_contract_invocations() -> None:
    provider = _ContractSpyProvider()

    assert isinstance(provider, AudioTranscriptionProvider)
    assert isinstance(provider, TextGenerationProvider)
    assert isinstance(provider, StreamingTextGenerationProvider)
    assert isinstance(provider, LowCostTextGenerationProvider)
    assert isinstance(provider, ReactionSelectionProvider)
    assert isinstance(provider, EventParsingProvider)
    assert isinstance(provider, OcrProvider)
    assert isinstance(provider, ProviderCapabilities)

    assert (
        provider.transcribe_audio(AudioTranscriptionRequest(audio_path="voice.ogg"))
        == "t:voice.ogg"
    )
    assert list(
        provider.generate_text_stream(TextGenerationRequest(prompt="hello"))
    ) == ["stream:hello"]
    assert provider.generate_text(TextGenerationRequest(prompt="hello")) == "g:hello"
    assert (
        provider.generate_low_cost_text(TextGenerationRequest(prompt="hello"))
        == "lc:hello"
    )
    assert (
        provider.select_reaction(
            ReactionSelectionRequest(
                message="hello",
                allowed_reactions=["😀", "😴"],
                context_text="Alice: hi",
            )
        )
        == "😀"
    )
    assert provider.parse_image_event(ImageToEventRequest(image_path="event.jpg")) == {
        "path": "event.jpg"
    }
    assert (
        provider.extract_image_text(
            ImageToTextRequest(image_bytes=b"abc", mime_type="image/png")
        )
        == "image/png:3"
    )
    assert provider.calls == [
        ("transcribe_audio", "voice.ogg"),
        ("generate_text_stream", "hello"),
        ("generate_text", "hello"),
        ("generate_low_cost_text", "hello"),
        ("select_reaction", "hello", ["😀", "😴"], "Alice: hi"),
        ("parse_image_event", "event.jpg"),
        ("extract_image_text", "image/png", 3),
    ]


def test_resolve_provider_routing_contract() -> None:
    routing = ProviderRouting(
        text_generation="openai",
        streaming_text_generation="openai",
        low_cost_text_generation="gemini",
        audio_transcription="gemini",
        ocr="openai",
        reaction_selection="gemini",
        event_parsing="openai",
    )
    settings = SimpleNamespace(provider_routing=routing)

    assert resolve_provider_routing(settings) is routing


def test_build_provider_for_settings_routes_operations_and_context() -> None:
    build_order = []
    openai = _ConfigurableProvider("openai")
    gemini = _ConfigurableProvider("gemini")

    def _openai_factory(_settings) -> ProviderCapabilities:
        build_order.append("openai")
        return openai

    def _gemini_factory(_settings) -> ProviderCapabilities:
        build_order.append("gemini")
        return gemini

    provider = build_provider_for_settings(
        settings=SimpleNamespace(
            provider_routing=ProviderRouting(
                text_generation="openai",
                streaming_text_generation="openai",
                low_cost_text_generation="gemini",
                audio_transcription="gemini",
                ocr="openai",
                reaction_selection="gemini",
                event_parsing="openai",
            ),
            ai=SimpleNamespace(
                openai=SimpleNamespace(configured=True),
                gemini=SimpleNamespace(configured=True),
            ),
        ),
        openai_factory=_openai_factory,
        gemini_factory=_gemini_factory,
    )

    assert build_order == ["openai", "gemini"]
    assert (
        provider.transcribe_audio(AudioTranscriptionRequest(audio_path="voice.ogg"))
        == "gemini:voice.ogg"
    )
    assert (
        provider.generate_text(TextGenerationRequest(prompt="hello")) == "openai:hello"
    )
    assert list(
        provider.generate_text_stream(TextGenerationRequest(prompt="hello"))
    ) == ["openai-full"]
    assert (
        provider.generate_low_cost_text(TextGenerationRequest(prompt="hello"))
        == "gemini-low:hello"
    )
    assert (
        provider.select_reaction(
            ReactionSelectionRequest(
                message="hello",
                allowed_reactions=["😀"],
                context_text="Alice: hi",
            )
        )
        == "😀"
    )
    assert gemini.reaction_contexts == ["Alice: hi"]


def test_routed_provider_uses_explicit_capability_objects() -> None:
    openai = _ConfigurableProvider("openai")
    gemini = _ConfigurableProvider("gemini")
    routed = RoutedModelProvider(
        text_generation=openai,
        streaming_text_generation=openai,
        low_cost_text_generation=gemini,
        audio_transcription=gemini,
        ocr=openai,
        reaction_selection=gemini,
        event_parsing=openai,
    )

    assert routed.generate_text(TextGenerationRequest(prompt="hello")) == "openai:hello"
    assert list(routed.generate_text_stream(TextGenerationRequest(prompt="hello"))) == [
        "openai-full"
    ]
    assert (
        routed.generate_low_cost_text(TextGenerationRequest(prompt="hello"))
        == "gemini-low:hello"
    )
    assert (
        routed.transcribe_audio(AudioTranscriptionRequest(audio_path="voice.ogg"))
        == "gemini:voice.ogg"
    )


def test_provider_errors_preserve_provider_and_capability_context() -> None:
    error = ProviderAuthError(
        "bad credentials",
        provider="openai",
        capability="text_generation",
    )

    assert str(error) == "bad credentials"
    assert error.provider == "openai"
    assert error.capability == "text_generation"


def test_routed_provider_surfaces_typed_provider_errors() -> None:
    class _AuthFailProvider(_ConfigurableProvider):
        def generate_text(self, request: TextGenerationRequest) -> str:
            _ = request
            raise ProviderAuthError(
                "bad credentials",
                provider="openai",
                capability="text_generation",
            )

    routed = RoutedModelProvider(
        text_generation=_AuthFailProvider("openai"),
        streaming_text_generation=_ConfigurableProvider("openai"),
        low_cost_text_generation=_ConfigurableProvider("openai"),
        audio_transcription=_ConfigurableProvider("gemini"),
        ocr=_ConfigurableProvider("openai"),
        reaction_selection=_ConfigurableProvider("openai"),
        event_parsing=_ConfigurableProvider("openai"),
    )

    try:
        routed.generate_text(TextGenerationRequest(prompt="hello"))
    except ProviderAuthError as exc:
        assert exc.provider == "openai"
        assert exc.capability == "text_generation"
    else:
        raise AssertionError("expected ProviderAuthError")


def test_routed_provider_surfaces_configuration_errors() -> None:
    class _ConfigFailProvider(_ConfigurableProvider):
        def select_reaction(self, request: ReactionSelectionRequest) -> str:
            _ = request
            raise ProviderConfigurationError(
                "missing settings",
                provider="openai",
                capability="reaction_selection",
            )

    routed = RoutedModelProvider(
        text_generation=_ConfigurableProvider("openai"),
        streaming_text_generation=_ConfigurableProvider("openai"),
        low_cost_text_generation=_ConfigurableProvider("openai"),
        audio_transcription=_ConfigurableProvider("gemini"),
        ocr=_ConfigurableProvider("openai"),
        reaction_selection=_ConfigFailProvider("openai"),
        event_parsing=_ConfigurableProvider("openai"),
    )

    try:
        routed.select_reaction(
            ReactionSelectionRequest(message="hello", allowed_reactions=["😀"])
        )
    except ProviderConfigurationError as exc:
        assert exc.provider == "openai"
        assert exc.capability == "reaction_selection"
    else:
        raise AssertionError("expected ProviderConfigurationError")
