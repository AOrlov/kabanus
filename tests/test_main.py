import asyncio
import importlib
import sys
import threading
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


def test_parse_summary_command_args_friendly_forms(monkeypatch) -> None:
    main = _load_main(monkeypatch)

    parsed_tail, tail_err = main._parse_summary_command_args(["5", "budget"])
    parsed_index, index_err = main._parse_summary_command_args(["index", "12"])
    parsed_grep, grep_err = main._parse_summary_command_args(["incident", "report"])

    assert tail_err is None
    assert parsed_tail == {
        "head": 0,
        "tail": 5,
        "index": None,
        "grep": "budget",
        "show_help": False,
    }
    assert index_err is None
    assert parsed_index == {
        "head": 0,
        "tail": 0,
        "index": 12,
        "grep": "",
        "show_help": False,
    }
    assert grep_err is None
    assert parsed_grep == {
        "head": 5,
        "tail": 0,
        "index": None,
        "grep": "incident report",
        "show_help": False,
    }


def test_parse_summary_command_args_help_aliases(monkeypatch) -> None:
    main = _load_main(monkeypatch)

    for token in ["help", "--help", "-help", "?"]:
        parsed, err = main._parse_summary_command_args([token])
        assert err is None
        assert parsed is not None
        assert parsed["show_help"] is True


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
    monkeypatch.setattr(
        main.config,
        "get_settings",
        lambda: _reaction_settings(reaction_context_turns=2),
    )
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
        lambda: _reaction_settings(
            reaction_context_turns=10, reaction_context_token_limit=30
        ),
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


class _DraftSchedulingProbeProvider(_DummyProvider):
    def __init__(self, first_draft_sent: threading.Event):
        self._first_draft_sent = first_draft_sent
        self.wait_saw_signal = False

    def generate_stream(self, prompt: str):
        yield "he"
        self.wait_saw_signal = self._first_draft_sent.wait(timeout=0.2)
        yield "hello"


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


def test_message_drafts_unavailable_reason(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    update_private = SimpleNamespace(effective_chat=SimpleNamespace(type="private"))
    update_group = SimpleNamespace(effective_chat=SimpleNamespace(type="group"))

    disabled_settings = SimpleNamespace(
        telegram_use_message_drafts=False,
        model_provider="openai",
    )
    gemini_settings = SimpleNamespace(
        telegram_use_message_drafts=True,
        model_provider="gemini",
    )
    openai_settings = SimpleNamespace(
        telegram_use_message_drafts=True,
        model_provider="openai",
    )
    update_without_chat = SimpleNamespace(effective_chat=None)

    assert (
        main._message_drafts_unavailable_reason(update_private, disabled_settings)
        == "feature_disabled"
    )
    assert (
        main._message_drafts_unavailable_reason(update_private, gemini_settings)
        == "provider_not_openai"
    )
    assert (
        main._message_drafts_unavailable_reason(update_without_chat, openai_settings)
        == "missing_chat"
    )
    assert (
        main._message_drafts_unavailable_reason(update_group, openai_settings)
        == "chat_type_group"
    )
    assert (
        main._message_drafts_unavailable_reason(update_private, openai_settings) is None
    )


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
    assert all(
        isinstance(item["draft_id"], int) and item["draft_id"] > 0
        for item in sent_updates
    )


def test_generate_response_with_drafts_disables_updates_after_error(
    monkeypatch,
) -> None:
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


def test_generate_response_with_drafts_keeps_partial_output_on_stream_error(
    monkeypatch,
) -> None:
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


def test_generate_response_with_drafts_falls_back_to_generate_when_stream_empty(
    monkeypatch,
) -> None:
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


def test_generate_response_with_drafts_starts_sending_before_next_chunk(
    monkeypatch,
) -> None:
    main = _load_main(monkeypatch)
    first_draft_sent = threading.Event()
    provider = _DraftSchedulingProbeProvider(first_draft_sent)
    monkeypatch.setattr(main, "model_provider", provider)

    async def _fake_send_message_draft(**kwargs):
        first_draft_sent.set()
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

    assert response == "hello"
    assert provider.wait_saw_signal is True


def test_build_response_draft_id_is_positive_int(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=104727218),
        message=SimpleNamespace(message_id=157),
    )

    draft_id = main._build_response_draft_id(update)

    assert isinstance(draft_id, int)
    assert draft_id > 0


def test_notify_admin_preserves_html(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    sent = {}

    async def _send_message(*, chat_id, text, parse_mode):
        sent["chat_id"] = chat_id
        sent["text"] = text
        sent["parse_mode"] = parse_mode

    monkeypatch.setattr(
        main.config,
        "get_settings",
        lambda force=False: SimpleNamespace(admin_chat_id="42"),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=_send_message))

    asyncio.run(main.notify_admin(context, "<b>alert</b>"))

    assert sent["chat_id"] == "42"
    assert sent["text"] == "<b>alert</b>"


def test_error_handler_redacts_context_payload(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    sent = {}

    async def _send_message(*, chat_id, text, parse_mode):
        sent["chat_id"] = chat_id
        sent["text"] = text
        sent["parse_mode"] = parse_mode

    monkeypatch.setattr(
        main.config,
        "get_settings",
        lambda force=False: SimpleNamespace(admin_chat_id="42"),
    )
    context = SimpleNamespace(
        error=RuntimeError("boom"),
        chat_data={"token": "secret-chat-token"},
        user_data={"token": "secret-user-token"},
        bot=SimpleNamespace(send_message=_send_message),
    )

    asyncio.run(main.error_handler("opaque update payload", context))

    assert sent["chat_id"] == "42"
    assert "update_meta" in sent["text"]
    assert "context.chat_data" not in sent["text"]
    assert "context.user_data" not in sent["text"]
    assert "secret-chat-token" not in sent["text"]
    assert "secret-user-token" not in sent["text"]
