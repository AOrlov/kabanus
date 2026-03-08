import asyncio
from types import SimpleNamespace

import pytest

from src.bot.handlers.message_handler import (
    MessageHandler,
    build_prompt,
    is_bot_mentioned,
)


class _Provider:
    def __init__(self, reply) -> None:
        self.reply = reply
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.reply, list):
            return self.reply.pop(0)
        return self.reply

    def generate_low_cost(self, prompt: str) -> str:
        return "summary"


class _MediaService:
    async def transcribe_voice_message(self, voice, context):
        raise AssertionError("voice flow should not run")

    async def extract_text_from_photo_message(self, message, context):
        raise AssertionError("photo flow should not run")

    async def extract_text_from_image_document(self, message, context):
        raise AssertionError("document flow should not run")

    async def resolve_reply_target_context(
        self,
        message,
        *,
        chat_id,
        context,
        get_message_by_telegram_message_id_fn,
    ):
        raise AssertionError("reply target flow should not run")


class _TranscribeMediaService:
    async def transcribe_voice_message(self, voice, context):
        return "dictated this"

    async def extract_text_from_photo_message(self, message, context):
        raise AssertionError("photo flow should not run")

    async def extract_text_from_image_document(self, message, context):
        raise AssertionError("document flow should not run")

    async def resolve_reply_target_context(
        self,
        message,
        *,
        chat_id,
        context,
        get_message_by_telegram_message_id_fn,
    ):
        raise AssertionError("reply target flow should not run")


class _UnavailableVoiceMediaService:
    async def transcribe_voice_message(self, voice, context):
        raise NotImplementedError("transcribe unavailable")

    async def extract_text_from_photo_message(self, message, context):
        raise AssertionError("photo flow should not run")

    async def extract_text_from_image_document(self, message, context):
        raise AssertionError("document flow should not run")

    async def resolve_reply_target_context(
        self,
        message,
        *,
        chat_id,
        context,
        get_message_by_telegram_message_id_fn,
    ):
        raise AssertionError("reply target flow should not run")


class _PhotoMediaService:
    async def transcribe_voice_message(self, voice, context):
        raise AssertionError("voice flow should not run")

    async def extract_text_from_photo_message(self, message, context):
        return "caption from image"

    async def extract_text_from_image_document(self, message, context):
        raise AssertionError("document flow should not run")

    async def resolve_reply_target_context(
        self,
        message,
        *,
        chat_id,
        context,
        get_message_by_telegram_message_id_fn,
    ):
        raise AssertionError("reply target flow should not run")


def test_is_bot_mentioned_with_mention_entity() -> None:
    message = SimpleNamespace(
        text="@kaban explain",
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption="",
        caption_entities=[],
    )

    assert is_bot_mentioned(
        message,
        bot_username="kaban",
        bot_id=42,
        aliases=[],
    )


def test_build_prompt_with_reply_target_context() -> None:
    prompt = build_prompt(
        context_text="[RECENT_DIALOGUE]\nAlice: hello",
        sender="Bob",
        latest_text="@kaban explain",
        reply_target_context={"sender": "Alice", "text": "deploy at 18:00"},
    )

    assert "Target message for clarification:" in prompt
    assert prompt.endswith("Bob: @kaban explain")


def test_handle_addressed_message_uses_plain_generate_when_drafts_disabled() -> None:
    provider = _Provider("plain reply")
    sent = {}

    async def _maybe_react(*args, **kwargs):
        return None

    async def _send_ai_response(update, outgoing_text: str, storage_id: str):
        sent["text"] = outgoing_text
        sent["storage_id"] = storage_id

    async def _forbidden_generate_with_drafts(*args, **kwargs):
        raise AssertionError("draft path must not be called")

    message_handler = MessageHandler(
        settings_getter=lambda: SimpleNamespace(
            features={"message_handling": True},
            bot_aliases=[],
            debug_mode=False,
            telegram_use_message_drafts=True,
            model_provider="openai",
        ),
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "900",
        add_message_fn=lambda *args, **kwargs: None,
        get_message_by_telegram_message_id_fn=lambda *_args, **_kwargs: None,
        build_context_fn=lambda **kwargs: "[RECENT_DIALOGUE]\nAlice: hi",
        provider_getter=lambda: provider,
        media_service=_MediaService(),
        maybe_react_fn=_maybe_react,
        send_ai_response_fn=_send_ai_response,
        generate_response_with_drafts_fn=_forbidden_generate_with_drafts,
        message_drafts_unavailable_reason_fn=lambda _update, _settings: "chat_type_group",
        log_context_fn=lambda _update: {},
    )

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

    asyncio.run(message_handler.handle_addressed_message(update, context))

    assert sent == {"text": "plain reply", "storage_id": "900"}
    assert len(provider.prompts) == 1
    assert provider.prompts[0].endswith("Alice: @kaban explain")


def test_handle_addressed_message_uses_voice_transcription_flow() -> None:
    provider = _Provider("voice reply")
    sent = {}

    async def _maybe_react(*args, **kwargs):
        return None

    async def _send_ai_response(update, outgoing_text: str, storage_id: str):
        sent["text"] = outgoing_text
        sent["storage_id"] = storage_id

    message_handler = MessageHandler(
        settings_getter=lambda: SimpleNamespace(
            features={"message_handling": True},
            bot_aliases=[],
            debug_mode=False,
            telegram_use_message_drafts=False,
            model_provider="openai",
        ),
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "901",
        add_message_fn=lambda *args, **kwargs: None,
        get_message_by_telegram_message_id_fn=lambda *_args, **_kwargs: None,
        build_context_fn=lambda **kwargs: "[RECENT_DIALOGUE]\nAlice: hi",
        provider_getter=lambda: provider,
        media_service=_TranscribeMediaService(),
        maybe_react_fn=_maybe_react,
        send_ai_response_fn=_send_ai_response,
        generate_response_with_drafts_fn=lambda _update, _prompt, _settings: "unused",
        message_drafts_unavailable_reason_fn=lambda _update, _settings: "feature_disabled",
        log_context_fn=lambda _update: {},
    )

    async def _send_action(**kwargs):
        return None

    message = SimpleNamespace(
        text="@kaban",
        caption="",
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption_entities=[],
        voice=SimpleNamespace(file_id="voice"),
        photo=None,
        document=None,
        reply_to_message=None,
        message_id=88,
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=11,
            first_name="Alice",
            name="Alice",
            is_bot=False,
        ),
        effective_chat=SimpleNamespace(id=901, type="private", send_action=_send_action),
        update_id=2,
    )

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(username="kaban", id=42)

    context = SimpleNamespace(bot=_Bot())

    asyncio.run(message_handler.handle_addressed_message(update, context))

    assert sent["text"] == f">>{'dictated this'}\n\nvoice reply"
    assert sent["storage_id"] == "901"
    assert len(provider.prompts) == 1


def test_handle_addressed_message_propagates_voice_transcription_error() -> None:
    provider = _Provider("should-not-run")
    sent = []

    async def _maybe_react(*args, **kwargs):
        return None

    async def _send_ai_response(update, outgoing_text: str, storage_id: str):
        sent.append((outgoing_text, storage_id))

    message_handler = MessageHandler(
        settings_getter=lambda: SimpleNamespace(
            features={"message_handling": True},
            bot_aliases=[],
            debug_mode=False,
            telegram_use_message_drafts=False,
            model_provider="openai",
        ),
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "901",
        add_message_fn=lambda *args, **kwargs: None,
        get_message_by_telegram_message_id_fn=lambda *_args, **_kwargs: None,
        build_context_fn=lambda **kwargs: "[RECENT_DIALOGUE]\nAlice: hi",
        provider_getter=lambda: provider,
        media_service=_UnavailableVoiceMediaService(),
        maybe_react_fn=_maybe_react,
        send_ai_response_fn=_send_ai_response,
        generate_response_with_drafts_fn=lambda _update, _prompt, _settings: "unused",
        message_drafts_unavailable_reason_fn=lambda _update, _settings: "feature_disabled",
        log_context_fn=lambda _update: {},
    )

    async def _send_action(**kwargs):
        return None

    message = SimpleNamespace(
        text="@kaban",
        caption="",
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption_entities=[],
        voice=SimpleNamespace(file_id="voice"),
        photo=None,
        document=None,
        reply_to_message=None,
        message_id=99,
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=11,
            first_name="Alice",
            name="Alice",
            is_bot=False,
        ),
        effective_chat=SimpleNamespace(id=901, type="private", send_action=_send_action),
        update_id=2,
    )

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(username="kaban", id=42)

    context = SimpleNamespace(bot=_Bot())

    with pytest.raises(NotImplementedError, match="transcribe unavailable"):
        asyncio.run(message_handler.handle_addressed_message(update, context))

    assert sent == []
    assert provider.prompts == []


def test_handle_addressed_message_uses_photo_path() -> None:
    provider = _Provider("photo reply")
    sent = {}

    async def _maybe_react(*args, **kwargs):
        return None

    async def _send_ai_response(update, outgoing_text: str, storage_id: str):
        sent["text"] = outgoing_text
        sent["storage_id"] = storage_id

    message_handler = MessageHandler(
        settings_getter=lambda: SimpleNamespace(
            features={"message_handling": True},
            bot_aliases=[],
            debug_mode=False,
            telegram_use_message_drafts=False,
            model_provider="openai",
        ),
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "902",
        add_message_fn=lambda *args, **kwargs: None,
        get_message_by_telegram_message_id_fn=lambda *_args, **_kwargs: None,
        build_context_fn=lambda **kwargs: "[RECENT_DIALOGUE]\nAlice: hi",
        provider_getter=lambda: provider,
        media_service=_PhotoMediaService(),
        maybe_react_fn=_maybe_react,
        send_ai_response_fn=_send_ai_response,
        generate_response_with_drafts_fn=lambda _update, _prompt, _settings: "unused",
        message_drafts_unavailable_reason_fn=lambda _update, _settings: "feature_disabled",
        log_context_fn=lambda _update: {},
    )

    async def _send_action(**kwargs):
        return None

    message = SimpleNamespace(
        text="@kaban photo",
        caption="",
        entities=[SimpleNamespace(type="mention", offset=0, length=6)],
        caption_entities=[],
        voice=None,
        photo=[SimpleNamespace(file_id="photo")],
        document=None,
        reply_to_message=None,
        message_id=89,
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=11,
            first_name="Alice",
            name="Alice",
            is_bot=False,
        ),
        effective_chat=SimpleNamespace(id=902, type="private", send_action=_send_action),
        update_id=3,
    )

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(username="kaban", id=42)

    context = SimpleNamespace(bot=_Bot())

    asyncio.run(message_handler.handle_addressed_message(update, context))

    assert sent == {"text": "photo reply", "storage_id": "902"}
    assert len(provider.prompts) == 1


def test_handle_addressed_message_ignores_unmentioned_text() -> None:
    provider = _Provider("should-not-run")
    sent = {}

    async def _maybe_react(*args, **kwargs):
        return None

    async def _send_ai_response(update, outgoing_text: str, storage_id: str):
        sent["text"] = outgoing_text

    message_handler = MessageHandler(
        settings_getter=lambda: SimpleNamespace(
            features={"message_handling": True},
            bot_aliases=[],
            debug_mode=False,
            telegram_use_message_drafts=False,
            model_provider="openai",
        ),
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "903",
        add_message_fn=lambda *args, **kwargs: None,
        get_message_by_telegram_message_id_fn=lambda *_args, **_kwargs: None,
        build_context_fn=lambda **kwargs: "[RECENT_DIALOGUE]\nAlice: hi",
        provider_getter=lambda: provider,
        media_service=_MediaService(),
        maybe_react_fn=_maybe_react,
        send_ai_response_fn=_send_ai_response,
        generate_response_with_drafts_fn=lambda _update, _prompt, _settings: "unused",
        message_drafts_unavailable_reason_fn=lambda _update, _settings: "feature_disabled",
        log_context_fn=lambda _update: {},
    )

    async def _send_action(**kwargs):
        return None

    message = SimpleNamespace(
        text="random hello",
        caption="",
        entities=[],
        caption_entities=[],
        voice=None,
        photo=None,
        document=None,
        reply_to_message=None,
        message_id=90,
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=11,
            first_name="Alice",
            name="Alice",
            is_bot=False,
        ),
        effective_chat=SimpleNamespace(id=903, type="private", send_action=_send_action),
        update_id=4,
    )

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(username="kaban", id=42)

    context = SimpleNamespace(bot=_Bot())

    asyncio.run(message_handler.handle_addressed_message(update, context))

    assert sent == {}
    assert provider.prompts == []


def test_handle_addressed_message_retries_when_model_returns_empty() -> None:
    provider = _Provider(["", "", "final response"])
    sent = {}
    sleeps = []

    async def _maybe_react(*args, **kwargs):
        return None

    async def _send_ai_response(update, outgoing_text: str, storage_id: str):
        sent["text"] = outgoing_text
        sent["storage_id"] = storage_id

    async def _sleep(value: float):
        sleeps.append(value)

    message_handler = MessageHandler(
        settings_getter=lambda: SimpleNamespace(
            features={"message_handling": True},
            bot_aliases=[],
            debug_mode=False,
            telegram_use_message_drafts=False,
            model_provider="openai",
        ),
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "904",
        add_message_fn=lambda *args, **kwargs: None,
        get_message_by_telegram_message_id_fn=lambda *_args, **_kwargs: None,
        build_context_fn=lambda **kwargs: "[RECENT_DIALOGUE]\nAlice: hi",
        provider_getter=lambda: provider,
        media_service=_MediaService(),
        maybe_react_fn=_maybe_react,
        send_ai_response_fn=_send_ai_response,
        generate_response_with_drafts_fn=lambda _update, _prompt, _settings: "unused",
        message_drafts_unavailable_reason_fn=lambda _update, _settings: "feature_disabled",
        log_context_fn=lambda _update: {},
        sleep_fn=_sleep,
    )

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
        message_id=91,
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(
            id=11,
            first_name="Alice",
            name="Alice",
            is_bot=False,
        ),
        effective_chat=SimpleNamespace(id=904, type="private", send_action=_send_action),
        update_id=5,
    )

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(username="kaban", id=42)

    context = SimpleNamespace(bot=_Bot())

    asyncio.run(message_handler.handle_addressed_message(update, context))

    assert sent == {"text": "final response", "storage_id": "904"}
    assert sleeps == [0.5, 0.5]
    assert len(provider.prompts) == 3
