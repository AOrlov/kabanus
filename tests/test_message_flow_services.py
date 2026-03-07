import asyncio
import logging
from types import SimpleNamespace

from src.bot.addressing_service import AddressingRequest, resolve_addressing_decision
from src.bot.message_input_service import normalize_inbound_message
from src.bot.response_generation_service import generate_response_with_retries


class _RetryProvider:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0

    def generate(self, prompt: str) -> str:
        _ = prompt
        self.calls += 1
        if not self._outputs:
            return ""
        return self._outputs.pop(0)

    def generate_stream(
        self, prompt: str
    ):  # pragma: no cover - not used in these tests
        _ = prompt
        return iter([])

def test_normalize_inbound_text_payload() -> None:
    async def run_test() -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(
                text="hello",
                caption=None,
                voice=None,
                photo=None,
                document=None,
                reply_to_message=None,
            ),
            effective_user=SimpleNamespace(id=1, first_name="Alice", name="Alice"),
            effective_chat=SimpleNamespace(id=2, type="group"),
            update_id=1,
        )
        payload = await normalize_inbound_message(
            update,
            context=SimpleNamespace(),
            model_provider=SimpleNamespace(),
            logger=logging.getLogger("test"),
        )

        assert payload is not None
        assert payload.text == "hello"
        assert payload.storage_id == "2"
        assert payload.source_kind == "text"
        assert payload.is_transcribed_text is False

    asyncio.run(run_test())


def test_normalize_inbound_non_image_document_returns_none() -> None:
    async def run_test() -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(
                text=None,
                caption=None,
                voice=None,
                photo=None,
                document=SimpleNamespace(
                    mime_type="application/pdf",
                    file_name="doc.pdf",
                    file_size=1024,
                ),
                reply_to_message=None,
            ),
            effective_user=SimpleNamespace(id=1, first_name="Alice", name="Alice"),
            effective_chat=SimpleNamespace(id=2, type="group"),
            update_id=2,
        )
        payload = await normalize_inbound_message(
            update,
            context=SimpleNamespace(),
            model_provider=SimpleNamespace(),
            logger=logging.getLogger("test"),
        )

        assert payload is None

    asyncio.run(run_test())


def test_resolve_addressing_decision_matrix() -> None:
    mention_message = SimpleNamespace(
        text="@kaban help",
        caption="",
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption_entities=[],
        reply_to_message=None,
    )
    update_mention = SimpleNamespace(message=mention_message)
    decision = resolve_addressing_decision(
        update_mention,
        request=AddressingRequest(
            text="@kaban help",
            is_transcribed_text=False,
            bot_username="kaban",
            bot_id=42,
            aliases=[],
        ),
    )
    assert decision.should_respond is True

    reply_other_message = SimpleNamespace(
        text="ok",
        caption="",
        entities=[],
        caption_entities=[],
        reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=777)),
    )
    update_reply_other = SimpleNamespace(message=reply_other_message)
    decision_reply_other = resolve_addressing_decision(
        update_reply_other,
        request=AddressingRequest(
            text="ok",
            is_transcribed_text=False,
            bot_username="kaban",
            bot_id=42,
            aliases=[],
        ),
    )
    assert decision_reply_other.replied_to_other_user is True
    assert decision_reply_other.should_respond is False


def test_generate_response_with_retries_until_non_empty(monkeypatch) -> None:
    async def run_test() -> None:
        provider = _RetryProvider(["", "", "ready"])
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=2, type="group"),
            effective_user=SimpleNamespace(id=1),
            update_id=3,
        )
        settings = SimpleNamespace(
            telegram_use_message_drafts=False,
            model_provider="openai",
        )
        original_sleep = asyncio.sleep
        monkeypatch.setattr(
            "src.bot.response_generation_service.asyncio.sleep",
            lambda _: original_sleep(0),
        )

        result = await generate_response_with_retries(
            update,
            prompt="p",
            settings=settings,
            model_provider=provider,
            logger=logging.getLogger("test"),
        )

        assert result == "ready"
        assert provider.calls == 3

    asyncio.run(run_test())


def test_generate_response_with_retries_empty_after_max_attempts(monkeypatch) -> None:
    async def run_test() -> None:
        provider = _RetryProvider(["", "", ""])
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=2, type="group"),
            effective_user=SimpleNamespace(id=1),
            update_id=4,
        )
        settings = SimpleNamespace(
            telegram_use_message_drafts=False,
            model_provider="openai",
        )
        original_sleep = asyncio.sleep
        monkeypatch.setattr(
            "src.bot.response_generation_service.asyncio.sleep",
            lambda _: original_sleep(0),
        )

        result = await generate_response_with_retries(
            update,
            prompt="p",
            settings=settings,
            model_provider=provider,
            logger=logging.getLogger("test"),
        )

        assert result == ""
        assert provider.calls == 3

    asyncio.run(run_test())


def test_generate_response_with_retries_uses_drafts_strategy(monkeypatch) -> None:
    async def run_test() -> None:
        provider = _RetryProvider(["direct answer"])
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=2, type="private"),
            effective_user=SimpleNamespace(id=1),
            update_id=5,
        )
        settings = SimpleNamespace(
            telegram_use_message_drafts=True,
            model_provider="openai",
        )

        async def fake_generate_response_with_drafts(*args, **kwargs):
            _ = args, kwargs
            return "draft answer"

        monkeypatch.setattr(
            "src.bot.response_generation_service.generate_response_with_drafts",
            fake_generate_response_with_drafts,
        )

        result = await generate_response_with_retries(
            update,
            prompt="p",
            settings=settings,
            model_provider=provider,
            logger=logging.getLogger("test"),
        )

        assert result == "draft answer"
        assert provider.calls == 0

    asyncio.run(run_test())
