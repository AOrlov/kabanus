import asyncio
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

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
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


class _ReactionRecorderProvider(_DummyProvider):
    def __init__(self, reaction: str) -> None:
        self.reaction = reaction
        self.calls = []

    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        self.calls.append(
            {
                "message": message,
                "allowed_reactions": list(allowed_reactions),
                "context_text": context_text,
            }
        )
        return self.reaction


class _ReactionMessage:
    def __init__(self) -> None:
        self.reaction = None

    async def set_reaction(self, reaction: str) -> None:
        self.reaction = reaction


def _reaction_settings(**overrides):
    base = {
        "reaction_enabled": True,
        "reaction_daily_budget": 10,
        "reaction_cooldown_secs": 0.0,
        "reaction_messages_threshold": 1,
        "reaction_context_turns": 8,
        "reaction_context_token_limit": 1200,
        "debug_mode": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_maybe_react_uses_recent_context_window(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    reaction = main._REACTION_ALLOWED_LIST[0]
    provider = _ReactionRecorderProvider(reaction)
    monkeypatch.setattr(main, "model_provider", provider)
    monkeypatch.setattr(main.config, "get_settings", lambda: _reaction_settings(reaction_context_turns=2))
    monkeypatch.setattr(
        main,
        "get_all_messages",
        lambda _chat_id: [
            {"sender": "Alice", "text": "one"},
            {"sender": "Bob", "text": "two"},
            {"sender": "Carol", "text": "three"},
        ],
    )

    main._REACTION_DAY = None
    main._REACTION_COUNT = 0
    main._REACTION_LAST_TS = 0.0
    main._MESSAGES_SINCE_LAST_REACTION = 0

    message = _ReactionMessage()
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=2, type="group"),
        update_id=123,
    )

    asyncio.run(main.maybe_react(update, "latest"))

    assert message.reaction == reaction
    assert len(provider.calls) == 1
    context = provider.calls[0]["context_text"]
    assert "Bob: two" in context
    assert "Carol: three" in context
    assert "Alice: one" not in context


def test_maybe_react_respects_reaction_context_token_limit(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    reaction = main._REACTION_ALLOWED_LIST[0]
    provider = _ReactionRecorderProvider(reaction)
    monkeypatch.setattr(main, "model_provider", provider)
    monkeypatch.setattr(
        main.config,
        "get_settings",
        lambda: _reaction_settings(reaction_context_turns=10, reaction_context_token_limit=30),
    )
    monkeypatch.setattr(
        main,
        "get_all_messages",
        lambda _chat_id: [
            {"sender": "Alice", "text": "a" * 60},
            {"sender": "Bob", "text": "b" * 60},
            {"sender": "Carol", "text": "c" * 60},
        ],
    )

    main._REACTION_DAY = None
    main._REACTION_COUNT = 0
    main._REACTION_LAST_TS = 0.0
    main._MESSAGES_SINCE_LAST_REACTION = 0

    message = _ReactionMessage()
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=2, type="group"),
        update_id=456,
    )

    asyncio.run(main.maybe_react(update, "latest"))

    assert len(provider.calls) == 1
    context = provider.calls[0]["context_text"]
    assert "Carol: ccccc" in context
    assert "Bob: bbbbb" not in context
