import asyncio
import importlib
import sys
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/summary", []),
        ("/summary 5", ["5"]),
        ("/summary budget api", ["budget", "api"]),
        ("/summary@kaban index 12", ["index", "12"]),
        ("/tldr --head 3", ["--head", "3"]),
    ],
)
def test_command_args_from_message_text_contract(monkeypatch, raw, expected) -> None:
    main = _load_main(monkeypatch)

    assert main._command_args_from_message_text(raw) == expected


@pytest.mark.parametrize(
    ("args", "expected", "expected_error"),
    [
        ([], {"head": 0, "tail": 1, "index": None, "grep": "", "show_help": False}, None),
        (["5", "urgent"], {"head": 0, "tail": 5, "index": None, "grep": "urgent", "show_help": False}, None),
        (["index", "0"], {"head": 0, "tail": 0, "index": 0, "grep": "", "show_help": False}, None),
        (["budget", "api"], {"head": 5, "tail": 0, "index": None, "grep": "budget api", "show_help": False}, None),
        (
            ["--head", "10", "--grep", "budget"],
            {"head": 10, "tail": 0, "index": None, "grep": "budget", "show_help": False},
            None,
        ),
        (
            ["--grep", "budget"],
            {"head": 5, "tail": 0, "index": None, "grep": "budget", "show_help": False},
            None,
        ),
        (["head"], None, "Missing value for head"),
    ],
)
def test_parse_summary_command_args_contract(
    monkeypatch,
    args,
    expected,
    expected_error,
) -> None:
    main = _load_main(monkeypatch)

    parsed, err = main._parse_summary_command_args(args)

    assert parsed == expected
    assert err == expected_error


def test_view_summary_prefers_message_text_args(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    monkeypatch.setattr(main, "is_allowed", lambda _update: True)

    captured_call = {}

    def _fake_get_summary_view_text(**kwargs):
        captured_call.update(kwargs)
        return "summary output"

    monkeypatch.setattr(main, "get_summary_view_text", _fake_get_summary_view_text)

    sent_replies = []

    async def _reply_text(text: str):
        sent_replies.append(text)

    message = SimpleNamespace(text="/summary 2", reply_text=_reply_text)
    update = SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(id=42, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(args=["9"])

    asyncio.run(main.view_summary(update, context))

    assert captured_call["chat_id"] == "42"
    assert captured_call["tail"] == 2
    assert sent_replies == ["summary output"]


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


class _FailingReactionProvider(_DummyProvider):
    def choose_reaction(
        self,
        message: str,
        allowed_reactions: list[str],
        context_text: str = "",
    ) -> str:
        del message, allowed_reactions, context_text
        raise RuntimeError("reaction unavailable")


class _ReactionMessage:
    def __init__(self) -> None:
        self.applied = []

    async def set_reaction(self, reaction: str) -> None:
        self.applied.append(reaction)


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


@pytest.mark.parametrize(
    ("settings_overrides", "state", "expected_provider_calls", "expected_reactions"),
    [
        ({"reaction_enabled": False}, {"count": 0, "messages_since": 0, "last_ts": 0.0}, 0, 0),
        ({"reaction_daily_budget": 1}, {"count": 1, "messages_since": 0, "last_ts": 0.0}, 0, 0),
        (
            {"reaction_cooldown_secs": 60.0},
            {"count": 0, "messages_since": 0, "last_ts": "now"},
            0,
            0,
        ),
        (
            {"reaction_messages_threshold": 2},
            {"count": 0, "messages_since": 0, "last_ts": 0.0},
            0,
            0,
        ),
        ({}, {"count": 0, "messages_since": 0, "last_ts": 0.0}, 1, 1),
    ],
)
def test_maybe_react_gating_contract(
    monkeypatch,
    settings_overrides,
    state,
    expected_provider_calls,
    expected_reactions,
) -> None:
    main = _load_main(monkeypatch)
    reaction = main._REACTION_ALLOWED_LIST[0]
    provider = _ReactionRecorderProvider(reaction)
    monkeypatch.setattr(main, "model_provider", provider)
    monkeypatch.setattr(
        main.config,
        "get_settings",
        lambda: _reaction_settings(**settings_overrides),
    )
    monkeypatch.setattr(
        main,
        "get_all_messages",
        lambda _chat_id: [
            {"sender": "Alice", "text": "one"},
            {"sender": "Bob", "text": "two"},
        ],
    )

    main._REACTION_DAY = datetime.now().date()
    main._REACTION_COUNT = state["count"]
    main._REACTION_LAST_TS = (
        time.monotonic() if state["last_ts"] == "now" else float(state["last_ts"])
    )
    main._MESSAGES_SINCE_LAST_REACTION = state["messages_since"]

    message = _ReactionMessage()
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=9, type="group"),
        update_id=1,
    )

    asyncio.run(main.maybe_react(update, "latest"))

    assert len(provider.calls) == expected_provider_calls
    assert len(message.applied) == expected_reactions


def test_maybe_react_propagates_reaction_provider_errors(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    monkeypatch.setattr(main, "model_provider", _FailingReactionProvider())
    monkeypatch.setattr(main.config, "get_settings", lambda: _reaction_settings())
    monkeypatch.setattr(main, "get_all_messages", lambda _chat_id: [])

    main._REACTION_DAY = datetime.now().date()
    main._REACTION_COUNT = 0
    main._REACTION_LAST_TS = 0.0
    main._MESSAGES_SINCE_LAST_REACTION = 0

    message = _ReactionMessage()
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=9, type="group"),
        update_id=2,
    )

    with pytest.raises(RuntimeError, match="reaction unavailable"):
        asyncio.run(main.maybe_react(update, "latest"))


class _GenerateRecorderProvider(_DummyProvider):
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


def test_handle_addressed_message_falls_back_when_drafts_unavailable(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    provider = _GenerateRecorderProvider("plain reply")
    monkeypatch.setattr(main, "model_provider", provider)
    monkeypatch.setattr(main, "is_allowed", lambda _update: True)

    settings = SimpleNamespace(
        features={"message_handling": True},
        bot_aliases=[],
        debug_mode=False,
        telegram_use_message_drafts=True,
        model_provider="openai",
    )
    monkeypatch.setattr(main.config, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "add_message", lambda *args, **kwargs: None)

    async def _fake_maybe_react(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "maybe_react", _fake_maybe_react)
    monkeypatch.setattr(
        main,
        "build_context",
        lambda **kwargs: "[RECENT_DIALOGUE]\nAlice: hi",
    )

    draft_path_called = {"value": False}

    async def _forbidden_generate_with_drafts(*args, **kwargs):
        draft_path_called["value"] = True
        raise AssertionError("draft path must not be used in group chat")

    monkeypatch.setattr(
        main,
        "_generate_response_with_drafts",
        _forbidden_generate_with_drafts,
    )

    sent_response = {}

    async def _fake_send_ai_response(update, outgoing_text: str, storage_id: str):
        sent_response["text"] = outgoing_text
        sent_response["storage_id"] = storage_id

    monkeypatch.setattr(main, "send_ai_response", _fake_send_ai_response)

    async def _send_action(**kwargs):
        return None

    message = SimpleNamespace(
        text="@kaban explain",
        caption="",
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption_entities=[],
        voice=None,
        photo=None,
        document=None,
        reply_to_message=None,
        message_id=77,
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=11,
            first_name="Alice",
            name="Alice",
            is_bot=False,
        ),
        effective_chat=SimpleNamespace(id=900, type="group", send_action=_send_action),
        update_id=2,
    )

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(username="kaban", id=42)

    context = SimpleNamespace(bot=_Bot())

    asyncio.run(main.handle_addressed_message(update, context))

    assert draft_path_called["value"] is False
    assert sent_response == {"text": "plain reply", "storage_id": "900"}
    assert len(provider.prompts) == 1
    assert provider.prompts[0].endswith("Alice: @kaban explain")
