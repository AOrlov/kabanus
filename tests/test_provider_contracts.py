from types import SimpleNamespace

from src.model_provider import ModelProvider
from src.provider_factory import (
    RoutedModelProvider,
    build_provider_for_settings,
    resolve_provider_routing,
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

# Contract note:
# - Stable compatibility contract is configuration behavior.
# - Provider/runtime API shape assertions here are characterization-only and may change.


class _ContractSpyProvider(ModelProvider):
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


class _ConfigurableProvider(ModelProvider):
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


def test_model_provider_legacy_wrappers_delegate_to_typed_methods() -> None:
    provider = _ContractSpyProvider()

    assert provider.transcribe("voice.ogg") == "t:voice.ogg"
    assert list(provider.generate_stream("hello")) == ["stream:hello"]
    assert provider.generate("hello") == "g:hello"
    assert provider.generate_low_cost("hello") == "lc:hello"
    assert provider.choose_reaction("hello", ["😀", "😴"], context_text="Alice: hi") == "😀"
    assert provider.parse_image_to_event("event.jpg") == {"path": "event.jpg"}
    assert provider.image_to_text(b"abc", mime_type="image/png") == "image/png:3"
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
    openai_routing = resolve_provider_routing(
        SimpleNamespace(
            model_provider="openai",
            gemini_api_key="gem-key",
            openai_api_key="",
            openai_auth_json_path="",
        )
    )
    assert openai_routing == ProviderRouting(
        primary="openai",
        fallback="gemini",
        transcribe_use_fallback=True,
    )

    gemini_routing = resolve_provider_routing(
        SimpleNamespace(
            model_provider="gemini",
            gemini_api_key="gem-key",
            openai_api_key="openai-key",
            openai_auth_json_path="",
        )
    )
    assert gemini_routing == ProviderRouting(
        primary="gemini",
        fallback="openai",
        transcribe_use_fallback=False,
    )


def test_build_provider_for_settings_routes_operations_and_context() -> None:
    build_order = []
    openai = _ConfigurableProvider(
        "openai",
        fail_generate=True,
        fail_reaction=True,
        stream_mode="fail",
    )
    gemini = _ConfigurableProvider("gemini")

    def _openai_factory() -> ModelProvider:
        build_order.append("openai")
        return openai

    def _gemini_factory() -> ModelProvider:
        build_order.append("gemini")
        return gemini

    provider = build_provider_for_settings(
        settings=SimpleNamespace(
            model_provider="openai",
            gemini_api_key="gem-key",
            openai_api_key="openai-key",
            openai_auth_json_path="",
        ),
        openai_factory=_openai_factory,
        gemini_factory=_gemini_factory,
    )

    assert build_order == ["openai", "gemini"]
    assert provider.transcribe("voice.ogg") == "gemini:voice.ogg"
    assert provider.generate("hello") == "gemini:hello"
    assert list(provider.generate_stream("hello")) == ["gemini-full"]
    assert provider.choose_reaction("hello", ["😀"], context_text="Alice: hi") == "😀"
    assert gemini.reaction_contexts == ["Alice: hi"]


def test_routed_provider_keeps_partial_stream_without_fallback() -> None:
    primary = _ConfigurableProvider("openai", stream_mode="partial_fail")
    fallback = _ConfigurableProvider("gemini")
    routed = RoutedModelProvider(primary=primary, fallback=fallback)

    assert list(routed.generate_stream("hello")) == ["openai-partial"]
    assert fallback.stream_calls == 0
