import asyncio
from types import SimpleNamespace

from src.bot.services.reply_service import (
    ReplyService,
    message_drafts_unavailable_reason,
)
from src.providers.contracts import TextGenerationRequest


class _StreamingProvider:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.prompts = []

    def generate_text_stream(self, request: TextGenerationRequest):
        self.prompts.append(request.prompt)
        for snapshot in self.snapshots:
            yield snapshot

    def generate_text(self, request: TextGenerationRequest) -> str:
        self.prompts.append(request.prompt)
        return ""


def test_generate_response_with_drafts_streams_updates() -> None:
    provider = _StreamingProvider(["he", "hello", "hello world"])
    sent_updates = []

    async def _fake_send_message_draft(**kwargs):
        sent_updates.append(kwargs)
        return True

    service = ReplyService(
        text_generation_provider=provider,
        streaming_text_generation_provider=provider,
        settings_getter=lambda: SimpleNamespace(telegram_format_ai_replies=False),
        add_message_fn=lambda *args, **kwargs: None,
        send_message_draft_fn=_fake_send_message_draft,
    )
    settings = SimpleNamespace(
        telegram_bot_token="token",
        telegram_draft_update_interval_secs=0.0,
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, type="private"),
        message=SimpleNamespace(message_id=77),
        effective_user=SimpleNamespace(id=1),
        update_id=1,
    )

    response = asyncio.run(service.generate_response_with_drafts(update, "p", settings))

    assert response == "hello world"
    assert provider.prompts == ["p"]
    assert sent_updates[-1]["text"] == "hello world"


def test_send_ai_response_plain_text_chunks() -> None:
    replies = []
    stored_messages = []

    async def _reply_text(text: str, parse_mode=None):
        replies.append((text, parse_mode))

    service = ReplyService(
        text_generation_provider=_StreamingProvider([]),
        streaming_text_generation_provider=None,
        settings_getter=lambda: SimpleNamespace(telegram_format_ai_replies=False),
        add_message_fn=lambda *args, **kwargs: stored_messages.append((args, kwargs)),
    )

    update = SimpleNamespace(message=SimpleNamespace(reply_text=_reply_text))
    text = "a" * 4101
    asyncio.run(service.send_ai_response(update, text, "chat-1"))

    assert len(replies) == 2
    assert replies[0][1] is None
    assert len(stored_messages) == 2


def test_message_drafts_unavailable_reason_requires_streaming_and_private_chat() -> (
    None
):
    update_private = SimpleNamespace(effective_chat=SimpleNamespace(type="private"))
    update_group = SimpleNamespace(effective_chat=SimpleNamespace(type="group"))
    enabled_settings = SimpleNamespace(telegram_use_message_drafts=True)

    assert (
        message_drafts_unavailable_reason(
            update_private,
            enabled_settings,
            supports_streaming=True,
        )
        is None
    )
    assert (
        message_drafts_unavailable_reason(
            update_group,
            enabled_settings,
            supports_streaming=True,
        )
        == "chat_type_group"
    )
    assert (
        message_drafts_unavailable_reason(
            update_private,
            enabled_settings,
            supports_streaming=False,
        )
        == "streaming_unavailable"
    )
