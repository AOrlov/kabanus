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


class _StreamingProvider(_DummyProvider):
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.prompts = []

    def generate_stream(self, prompt: str):
        self.prompts.append(prompt)
        for snapshot in self.snapshots:
            yield snapshot


class _FailingStreamProvider(_DummyProvider):
    def __init__(self, snapshots, fallback_text: str = ""):
        self.snapshots = list(snapshots)
        self.fallback_text = fallback_text
        self.stream_prompts = []
        self.generate_prompts = []

    def generate_stream(self, prompt: str):
        self.stream_prompts.append(prompt)
        for snapshot in self.snapshots:
            if isinstance(snapshot, Exception):
                raise snapshot
            yield snapshot

    def generate(self, prompt: str) -> str:
        self.generate_prompts.append(prompt)
        return self.fallback_text


def test_should_use_message_drafts_private_openai_only(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    update_private = SimpleNamespace(effective_chat=SimpleNamespace(type="private"))
    update_group = SimpleNamespace(effective_chat=SimpleNamespace(type="group"))
    openai_settings = SimpleNamespace(
        telegram_use_message_drafts=True,
        model_provider="openai",
    )
    gemini_settings = SimpleNamespace(
        telegram_use_message_drafts=True,
        model_provider="gemini",
    )

    assert main._should_use_message_drafts(update_private, openai_settings) is True
    assert main._should_use_message_drafts(update_group, openai_settings) is False
    assert main._should_use_message_drafts(update_private, gemini_settings) is False


def test_generate_response_with_drafts_streams_updates(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    provider = _StreamingProvider(["he", "hello", "hello world"])
    monkeypatch.setattr(main, "model_provider", provider)
    sent_updates = []

    async def _fake_send_message_draft(**kwargs):
        sent_updates.append(kwargs)
        return True

    monkeypatch.setattr(main, "send_message_draft", _fake_send_message_draft)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, type="private"),
        message=SimpleNamespace(message_id=77),
        effective_user=SimpleNamespace(id=1),
        update_id=1,
    )
    settings = SimpleNamespace(
        telegram_bot_token="test-token",
        telegram_draft_update_interval_secs=0.0,
    )

    response = asyncio.run(main._generate_response_with_drafts(update, "p", settings))

    assert response == "hello world"
    assert provider.prompts == ["p"]
    assert sent_updates
    assert sent_updates[0]["text"] == "he"
    assert sent_updates[-1]["text"] == "hello world"
    assert all(isinstance(item["draft_id"], int) and item["draft_id"] > 0 for item in sent_updates)


def test_generate_response_with_drafts_disables_updates_after_error(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    provider = _StreamingProvider(["he", "hello"])
    monkeypatch.setattr(main, "model_provider", provider)
    send_calls = {"count": 0}

    async def _failing_send_message_draft(**kwargs):
        send_calls["count"] += 1
        raise RuntimeError("draft failed")

    monkeypatch.setattr(main, "send_message_draft", _failing_send_message_draft)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, type="private"),
        message=SimpleNamespace(message_id=77),
        effective_user=SimpleNamespace(id=1),
        update_id=1,
    )
    settings = SimpleNamespace(
        telegram_bot_token="test-token",
        telegram_draft_update_interval_secs=0.0,
    )

    response = asyncio.run(main._generate_response_with_drafts(update, "p", settings))

    assert response == "hello"
    assert send_calls["count"] == 1


def test_generate_response_with_drafts_keeps_partial_output_on_stream_error(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    provider = _FailingStreamProvider(["partial", RuntimeError("stream failed")])
    monkeypatch.setattr(main, "model_provider", provider)
    sent_updates = []

    async def _fake_send_message_draft(**kwargs):
        sent_updates.append(kwargs)
        return True

    monkeypatch.setattr(main, "send_message_draft", _fake_send_message_draft)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, type="private"),
        message=SimpleNamespace(message_id=77),
        effective_user=SimpleNamespace(id=1),
        update_id=1,
    )
    settings = SimpleNamespace(
        telegram_bot_token="test-token",
        telegram_draft_update_interval_secs=0.0,
    )

    response = asyncio.run(main._generate_response_with_drafts(update, "p", settings))

    assert response == "partial"
    assert provider.stream_prompts == ["p"]
    assert provider.generate_prompts == []
    assert sent_updates[-1]["text"] == "partial"


def test_generate_response_with_drafts_falls_back_to_generate_when_stream_empty(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    provider = _FailingStreamProvider(
        [RuntimeError("stream failed")],
        fallback_text="fallback response",
    )
    monkeypatch.setattr(main, "model_provider", provider)
    sent_updates = []

    async def _fake_send_message_draft(**kwargs):
        sent_updates.append(kwargs)
        return True

    monkeypatch.setattr(main, "send_message_draft", _fake_send_message_draft)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, type="private"),
        message=SimpleNamespace(message_id=77),
        effective_user=SimpleNamespace(id=1),
        update_id=1,
    )
    settings = SimpleNamespace(
        telegram_bot_token="test-token",
        telegram_draft_update_interval_secs=0.0,
    )

    response = asyncio.run(main._generate_response_with_drafts(update, "p", settings))

    assert response == "fallback response"
    assert provider.stream_prompts == ["p"]
    assert provider.generate_prompts == ["p"]
    assert sent_updates[-1]["text"] == "fallback response"


def test_build_response_draft_id_is_positive_int(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=104727218),
        message=SimpleNamespace(message_id=157),
    )

    draft_id = main._build_response_draft_id(update)

    assert isinstance(draft_id, int)
    assert draft_id > 0
