from types import SimpleNamespace

from src.model_provider import ModelProvider
from src import provider_factory
from src.provider_factory import RoutedModelProvider


class _OkProvider(ModelProvider):
    def transcribe(self, audio_path: str) -> str:
        return f"t:{audio_path}"

    def generate(self, prompt: str) -> str:
        return f"g:{prompt}"

    def generate_low_cost(self, prompt: str) -> str:
        return f"lc:{prompt}"

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        return allowed_reactions[0]

    def parse_image_to_event(self, image_path: str) -> dict:
        return {"path": image_path}

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        return f"{mime_type}:{len(image_bytes)}"


class _FailGenerateProvider(_OkProvider):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("boom")


class _FailGenerateStreamProvider(_OkProvider):
    def generate_stream(self, prompt: str):
        raise RuntimeError("boom")


class _PartialFailGenerateStreamProvider(_OkProvider):
    def generate_stream(self, prompt: str):
        yield "partial"
        raise RuntimeError("boom")


class _FallbackTranscribeProvider(_OkProvider):
    def transcribe(self, audio_path: str) -> str:
        return f"fallback:{audio_path}"


class _FailReactionProvider(_OkProvider):
    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        raise RuntimeError("boom")


class _CaptureReactionProvider(_OkProvider):
    def __init__(self) -> None:
        self.last_context = ""

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        self.last_context = context_text
        return super().choose_reaction(message, allowed_reactions, context_text=context_text)


class _OpenAIProvider(_OkProvider):
    def transcribe(self, audio_path: str) -> str:
        return f"openai:{audio_path}"

    def generate(self, prompt: str) -> str:
        return f"openai:{prompt}"


class _GeminiProvider(_OkProvider):
    def transcribe(self, audio_path: str) -> str:
        return f"gemini:{audio_path}"

    def generate(self, prompt: str) -> str:
        return f"gemini:{prompt}"


def test_routed_provider_falls_back_on_generate_error() -> None:
    provider = RoutedModelProvider(primary=_FailGenerateProvider(), fallback=_OkProvider())
    assert provider.generate("hello") == "g:hello"


def test_routed_provider_uses_fallback_for_transcribe_when_forced() -> None:
    provider = RoutedModelProvider(
        primary=_OkProvider(),
        fallback=_FallbackTranscribeProvider(),
        transcribe_use_fallback=True,
    )
    assert provider.transcribe("voice.ogg") == "fallback:voice.ogg"


def test_routed_provider_falls_back_on_generate_stream_error() -> None:
    provider = RoutedModelProvider(primary=_FailGenerateStreamProvider(), fallback=_OkProvider())

    assert list(provider.generate_stream("hello")) == ["g:hello"]


def test_routed_provider_returns_partial_stream_if_primary_fails_after_emitting() -> None:
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
