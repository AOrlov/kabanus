from src.model_provider import ModelProvider
from src.provider_factory import RoutedModelProvider


class _OkProvider(ModelProvider):
    def transcribe(self, audio_path: str) -> str:
        return f"t:{audio_path}"

    def generate(self, prompt: str) -> str:
        return f"g:{prompt}"

    def generate_low_cost(self, prompt: str) -> str:
        return f"lc:{prompt}"

    def choose_reaction(self, message: str, allowed_reactions: list[str]) -> str:
        return allowed_reactions[0]

    def parse_image_to_event(self, image_path: str) -> dict:
        return {"path": image_path}

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        return f"{mime_type}:{len(image_bytes)}"


class _FailGenerateProvider(_OkProvider):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("boom")


class _FallbackTranscribeProvider(_OkProvider):
    def transcribe(self, audio_path: str) -> str:
        return f"fallback:{audio_path}"


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
