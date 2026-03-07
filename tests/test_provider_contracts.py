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


class _ContractSpyProvider(ModelProvider):
    def __init__(self) -> None:
        self.calls = []

    def transcribe(self, audio_path: str) -> str:
        self.calls.append(("transcribe", audio_path))
        return f"t:{audio_path}"

    def generate_stream(self, prompt: str):
        self.calls.append(("generate_stream", prompt))
        yield f"stream:{prompt}"

    def generate(self, prompt: str) -> str:
        self.calls.append(("generate", prompt))
        return f"g:{prompt}"

    def generate_low_cost(self, prompt: str) -> str:
        self.calls.append(("generate_low_cost", prompt))
        return f"lc:{prompt}"

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        self.calls.append(("choose_reaction", message, allowed_reactions, context_text))
        return allowed_reactions[0]

    def parse_image_to_event(self, image_path: str) -> dict:
        self.calls.append(("parse_image_to_event", image_path))
        return {"path": image_path}

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        self.calls.append(("image_to_text", mime_type, len(image_bytes)))
        return f"{mime_type}:{len(image_bytes)}"


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

    def transcribe(self, audio_path: str) -> str:
        return f"{self.name}:{audio_path}"

    def generate(self, prompt: str) -> str:
        if self.fail_generate:
            raise RuntimeError("generate failed")
        return f"{self.name}:{prompt}"

    def generate_stream(self, prompt: str):
        self.stream_calls += 1
        if self.stream_mode == "fail":
            raise RuntimeError("stream failed")
        if self.stream_mode == "partial_fail":
            yield f"{self.name}-partial"
            raise RuntimeError("stream failed")
        yield f"{self.name}-full"

    def generate_low_cost(self, prompt: str) -> str:
        return f"{self.name}-low:{prompt}"

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        self.reaction_contexts.append(context_text)
        if self.fail_reaction:
            raise RuntimeError("reaction failed")
        return allowed_reactions[0]

    def parse_image_to_event(self, image_path: str) -> dict:
        return {"provider": self.name, "path": image_path}

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        return f"{self.name}:{mime_type}:{len(image_bytes)}"


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


def test_model_provider_typed_wrappers_delegate_to_legacy_methods() -> None:
    provider = _ContractSpyProvider()

    assert (
        provider.transcribe_audio(AudioTranscriptionRequest("voice.ogg"))
        == "t:voice.ogg"
    )
    assert list(provider.generate_text_stream(TextGenerationRequest("hello"))) == [
        "stream:hello"
    ]
    assert provider.generate_text(TextGenerationRequest("hello")) == "g:hello"
    assert provider.generate_low_cost_text(TextGenerationRequest("hello")) == "lc:hello"
    assert (
        provider.select_reaction(
            ReactionSelectionRequest(
                message="hello",
                allowed_reactions=("😀", "😴"),
                context_text="Alice: hi",
            )
        )
        == "😀"
    )
    assert provider.parse_image_event(ImageToEventRequest("event.jpg")) == {
        "path": "event.jpg"
    }
    assert (
        provider.extract_image_text(ImageToTextRequest(b"abc", mime_type="image/png"))
        == "image/png:3"
    )
    assert provider.calls == [
        ("transcribe", "voice.ogg"),
        ("generate_stream", "hello"),
        ("generate", "hello"),
        ("generate_low_cost", "hello"),
        ("choose_reaction", "hello", ["😀", "😴"], "Alice: hi"),
        ("parse_image_to_event", "event.jpg"),
        ("image_to_text", "image/png", 3),
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
