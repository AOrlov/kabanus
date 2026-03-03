import importlib
import sys
from types import SimpleNamespace

from src import config, provider_factory


class _DummyProvider:
    def transcribe(self, audio_path: str) -> str:
        return ""

    def generate(self, prompt: str) -> str:
        return ""

    def generate_low_cost(self, prompt: str) -> str:
        return ""

    def choose_reaction(self, message: str, allowed_reactions: list[str]) -> str:
        return ""

    def parse_image_to_event(self, image_path: str) -> dict:
        return {}

    def image_to_text(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        return ""


def _load_main(monkeypatch):
    monkeypatch.setattr(config, "_reload_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ENABLE_MESSAGE_HANDLING", "true")
    config._SETTINGS_CACHE = None
    config._SETTINGS_CACHE_TS = 0.0

    monkeypatch.setattr(provider_factory, "build_provider", lambda: _DummyProvider())

    sys.modules.pop("src.main", None)
    module = importlib.import_module("src.main")
    return importlib.reload(module)


def test_is_bot_mentioned_with_mention_entity(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    message = SimpleNamespace(
        text="@kaban explain",
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption="",
        caption_entities=[],
    )

    assert main._is_bot_mentioned(
        message,
        bot_username="kaban",
        bot_id=42,
        aliases=["cab"],
    )


def test_is_bot_mentioned_with_text_mention_entity(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    message = SimpleNamespace(
        text="please help",
        entities=[
            SimpleNamespace(
                type="text_mention",
                offset=0,
                length=6,
                user=SimpleNamespace(id=42),
            )
        ],
        caption="",
        caption_entities=[],
    )

    assert main._is_bot_mentioned(
        message,
        bot_username="kaban",
        bot_id=42,
        aliases=[],
    )


def test_is_bot_mentioned_avoids_substring_false_positive(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    message = SimpleNamespace(
        text="alphabet soup",
        entities=[],
        caption="",
        caption_entities=[],
    )

    assert not main._is_bot_mentioned(
        message,
        bot_username="kaban",
        bot_id=42,
        aliases=["alpha"],
    )


def test_should_respond_trigger_matrix(monkeypatch) -> None:
    main = _load_main(monkeypatch)

    assert not main._should_respond_to_message(
        mentioned_bot=False,
        replied_to_bot=False,
        replied_to_other_user=True,
    )
    assert main._should_respond_to_message(
        mentioned_bot=True,
        replied_to_bot=False,
        replied_to_other_user=True,
    )
    assert main._should_respond_to_message(
        mentioned_bot=True,
        replied_to_bot=False,
        replied_to_other_user=False,
    )
    assert main._should_respond_to_message(
        mentioned_bot=False,
        replied_to_bot=True,
        replied_to_other_user=False,
    )


def test_build_prompt_includes_reply_target_context(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    prompt = main._build_prompt(
        context_text="[RECENT_DIALOGUE]\nAlice: hello",
        sender="Bob",
        latest_text="@kaban explain",
        reply_target_context={"sender": "Alice", "text": "image says deploy at 18:00"},
    )

    assert "Target message for clarification:" in prompt
    assert "Alice: image says deploy at 18:00" in prompt
    assert prompt.endswith("Bob: @kaban explain")
