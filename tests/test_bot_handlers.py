# pylint: disable=too-few-public-methods,duplicate-code

import asyncio
import logging
from types import SimpleNamespace

from telegram.error import BadRequest

from src.bot.message_handler import build_handle_addressed_message_handler
from src.bot.reaction_service import ReactionState
from src.bot.response_service import send_ai_response
from src.bot.runtime import BotRuntime


class _GenerateRetryProvider:
    def __init__(self) -> None:
        self.generate_calls = 0

    def transcribe(
        self, _audio_path: str
    ) -> str:  # pragma: no cover - not used in this test
        return ""

    def generate(self, _prompt: str) -> str:
        self.generate_calls += 1
        if self.generate_calls < 3:
            return ""
        return "final answer"

    def generate_low_cost(self, _prompt: str) -> str:
        return "summary"

    def choose_reaction(
        self,
        _message: str,
        _allowed_reactions: list[str],
        _context_text: str = "",
    ) -> str:
        return ""

    def parse_image_to_event(
        self, _image_path: str
    ) -> dict:  # pragma: no cover - not used in this test
        return {}

    def image_to_text(
        self, _image_bytes: bytes, _mime_type: str = "image/jpeg"
    ) -> str:  # pragma: no cover
        return ""


class _TranscribeProvider(_GenerateRetryProvider):
    def transcribe(self, _audio_path: str) -> str:
        return "voice text"

    def generate(
        self, _prompt: str
    ) -> str:  # pragma: no cover - should never be called in this test
        raise AssertionError(
            "Model generate should not be called for non-addressed voice messages"
        )


class _FakeChat:
    def __init__(self, chat_id: int, chat_type: str) -> None:
        self.id = chat_id
        self.type = chat_type
        self.actions = []

    async def send_action(self, action: str) -> None:
        self.actions.append(action)


class _FakeMessage:
    def __init__(self, **kwargs) -> None:
        self.replies = []
        for key, value in kwargs.items():
            setattr(self, key, value)

    async def reply_text(self, text: str, parse_mode=None) -> None:
        self.replies.append((text, parse_mode))


class _FakeBotFile:
    async def download_to_drive(self, path: str) -> None:
        with open(path, "wb") as file:
            file.write(b"")


class _FakeBot:
    async def get_me(self):
        return SimpleNamespace(id=42, username="kaban")

    async def get_file(self, file_id: str):
        _ = file_id
        return _FakeBotFile()


def _base_settings(**overrides):
    settings = {
        "features": {"message_handling": True},
        "allowed_chat_ids": ["1", "2"],
        "bot_aliases": [],
        "debug_mode": False,
        "telegram_use_message_drafts": False,
        "model_provider": "openai",
        "reaction_enabled": False,
    }
    settings.update(overrides)
    return SimpleNamespace(**settings)


def test_send_ai_response_falls_back_to_plain_text_on_bad_request() -> None:
    async def run_test() -> None:
        message = _FakeMessage()
        calls = {"count": 0}

        async def reply_text(text: str, parse_mode=None) -> None:
            calls["count"] += 1
            message.replies.append((text, parse_mode))
            if parse_mode is not None and calls["count"] == 1:
                raise BadRequest("can't parse entities")

        message.reply_text = reply_text
        update = SimpleNamespace(
            message=message,
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=2),
            update_id=1,
        )
        stored_chunks = []

        def add_message_probe(*args, **kwargs):
            stored_chunks.append((args, kwargs))

        await send_ai_response(
            update,
            "**hello**",
            "2",
            settings_getter=lambda: SimpleNamespace(telegram_format_ai_replies=True),
            logger=logging.getLogger("test"),
            log_context_fn=lambda _: {"chat_id": 2},
            add_message_fn=add_message_probe,
        )

        assert len(message.replies) == 2
        assert message.replies[0][1] is not None
        assert message.replies[1][0] == "hello"
        assert len(stored_chunks) == 1
        assert stored_chunks[0][0][1] == "hello"

    asyncio.run(run_test())


def test_handle_addressed_message_retries_empty_generation(monkeypatch) -> None:
    provider = _GenerateRetryProvider()

    def _settings():
        return _base_settings()

    runtime = BotRuntime(
        model_provider=provider,
        logger=logging.getLogger("test"),
        get_settings=_settings,
    )
    handler = build_handle_addressed_message_handler(runtime, ReactionState())

    message = _FakeMessage(
        text="@kaban help",
        caption=None,
        voice=None,
        photo=None,
        document=None,
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption_entities=[],
        message_id=33,
        reply_to_message=None,
    )
    chat = _FakeChat(chat_id=2, chat_type="group")
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=1, first_name="Alice", name="Alice", is_bot=False
        ),
        effective_chat=chat,
        update_id=10,
    )
    context = SimpleNamespace(bot=_FakeBot())

    captured = {}

    async def fake_send_ai_response(_update, outgoing_text, storage_id, **_kwargs):
        captured["outgoing_text"] = outgoing_text
        captured["storage_id"] = storage_id

    monkeypatch.setattr(
        "src.bot.message_handler.add_message", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("src.bot.message_handler.build_context", lambda **kwargs: "CTX")
    monkeypatch.setattr(
        "src.bot.message_handler.send_ai_response", fake_send_ai_response
    )
    original_sleep = asyncio.sleep
    monkeypatch.setattr(
        "src.bot.response_generation_service.asyncio.sleep",
        lambda _: original_sleep(0),
    )

    asyncio.run(handler(update, context))

    assert provider.generate_calls == 3
    assert captured["outgoing_text"] == "final answer"
    assert captured["storage_id"] == "2"


def test_handle_voice_message_not_addressed_replies_with_transcript(
    monkeypatch,
) -> None:
    provider = _TranscribeProvider()

    def _settings():
        return _base_settings()

    runtime = BotRuntime(
        model_provider=provider,
        logger=logging.getLogger("test"),
        get_settings=_settings,
    )
    handler = build_handle_addressed_message_handler(runtime, ReactionState())

    message = _FakeMessage(
        text=None,
        caption=None,
        voice=SimpleNamespace(file_id="voice-file"),
        photo=None,
        document=None,
        entities=[],
        caption_entities=[],
        message_id=22,
        reply_to_message=None,
    )
    chat = _FakeChat(chat_id=2, chat_type="group")
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=1, first_name="Alice", name="Alice", is_bot=False
        ),
        effective_chat=chat,
        update_id=11,
    )
    context = SimpleNamespace(bot=_FakeBot())

    async def fail_send_ai_response(*args, **kwargs):  # pragma: no cover - guard branch
        raise AssertionError("send_ai_response should not be called")

    monkeypatch.setattr(
        "src.bot.message_handler.add_message", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "src.bot.message_handler.send_ai_response", fail_send_ai_response
    )

    asyncio.run(handler(update, context))

    assert len(message.replies) == 1
    assert message.replies[0][0] == "voice text"
