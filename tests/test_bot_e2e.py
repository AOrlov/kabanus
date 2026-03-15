import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram import Bot, Message, Update, User
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler as TelegramMessageHandler,
)

from src import config, message_store
from src.bot import app as bot_app
from src.bot.contracts import (
    EventsCapabilities,
    MessageFlowCapabilities,
    RuntimeCapabilities,
)
from src.memory import summary_store
from src.providers.contracts import ProviderRouting


def _settings(store_path: Path, *, features=None):
    default_features = {
        "commands": {"hi": True},
        "message_handling": True,
        "schedule_events": True,
    }
    if features is None:
        resolved_features = default_features
    else:
        resolved_features = {
            **default_features,
            **features,
            "commands": {
                **default_features["commands"],
                **features.get("commands", {}),
            },
        }
    return SimpleNamespace(
        telegram_bot_token="123:TEST",
        admin_chat_id="999",
        features=resolved_features,
        allowed_chat_ids=["111", "-222"],
        bot_aliases=["kaban"],
        debug_mode=False,
        language="en",
        token_limit=200,
        chat_messages_store_path=str(store_path),
        memory_enabled=True,
        memory_recent_turns=3,
        memory_recent_budget_ratio=0.85,
        memory_summary_enabled=False,
        memory_summary_budget_ratio=0.15,
        memory_summary_chunk_size=16,
        memory_summary_max_items=4,
        memory_summary_max_chunks_per_run=1,
        settings_refresh_interval=60.0,
        reaction_enabled=False,
        reaction_cooldown_secs=0.0,
        reaction_daily_budget=0,
        reaction_messages_threshold=1,
        reaction_context_turns=3,
        reaction_context_token_limit=200,
        telegram_format_ai_replies=False,
        telegram_use_message_drafts=False,
        telegram_draft_update_interval_secs=0.0,
        google_calendar_id=None,
        google_credentials_path=None,
        google_credentials_json=None,
        provider_routing=ProviderRouting(
            text_generation="openai",
            streaming_text_generation="openai",
            low_cost_text_generation="openai",
            audio_transcription="openai",
            ocr="openai",
            reaction_selection="openai",
            event_parsing="openai",
        ),
    )


class _FakeTextGenerationProvider:
    def __init__(self, response: str = "Generated reply") -> None:
        self.prompts = []
        self.response = response

    def generate_text(self, request):
        self.prompts.append(request.prompt)
        return self.response


class _FakeStreamingTextGenerationProvider:
    def __init__(self) -> None:
        self.prompts = []

    def generate_text_stream(self, request):
        self.prompts.append(request.prompt)
        return iter(())


class _FakeLowCostTextGenerationProvider:
    def __init__(self, response: str = "Low-cost summary") -> None:
        self.prompts = []
        self.response = response

    def generate_low_cost_text(self, request):
        self.prompts.append(request.prompt)
        return self.response


class _FakeAudioTranscriptionProvider:
    def __init__(self, response: str = "voice transcript") -> None:
        self.audio_paths = []
        self.response = response

    def transcribe_audio(self, request):
        self.audio_paths.append(request.audio_path)
        return self.response


class _FakeOcrProvider:
    def __init__(self) -> None:
        self.requests = []

    def extract_image_text(self, request):
        self.requests.append(request)
        return "ocr result"


class _FakeReactionSelectionProvider:
    def __init__(self) -> None:
        self.requests = []

    def select_reaction(self, request):
        self.requests.append(request)
        return ""


class _FakeEventParsingProvider:
    def __init__(self) -> None:
        self.requests = []
        self.event_data = {
            "title": "Design Review",
            "date": "2030-06-20",
            "time": "14:00",
            "location": "Office",
            "description": "Discuss architecture",
            "confidence": 0.95,
        }

    def parse_image_event(self, request):
        self.requests.append(request.image_path)
        return dict(self.event_data)


class _RecordingCalendarProvider:
    def __init__(self, created_events: list[dict]) -> None:
        self._created_events = created_events

    def create_event(self, **kwargs) -> None:
        self._created_events.append(kwargs)


def _runtime_capabilities(providers) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        message_flow=MessageFlowCapabilities(
            text_generation=providers.text,
            streaming_text_generation=providers.streaming,
            low_cost_text_generation=providers.low_cost,
            audio_transcription=providers.audio,
            ocr=providers.ocr,
            reaction_selection=providers.reaction,
        ),
        events=EventsCapabilities(event_parsing=providers.events),
    )


class _FakeTelegramFile:
    def __init__(self, payload: bytes, file_size=None) -> None:
        self.payload = payload
        self.file_size = len(payload) if file_size is None else file_size
        self.drive_paths = []

    async def download_to_drive(self, path: str) -> None:
        self.drive_paths.append(path)
        Path(path).write_bytes(self.payload)

    async def download_to_memory(self, bio) -> None:
        bio.write(self.payload)


class _FakeBot(Bot):
    __slots__ = ("files", "sent_messages", "sent_actions", "_next_message_id")

    def __init__(self) -> None:
        super().__init__(token="123:TEST")
        object.__setattr__(self, "files", {})
        object.__setattr__(self, "sent_messages", [])
        object.__setattr__(self, "sent_actions", [])
        object.__setattr__(self, "_next_message_id", 9000)
        object.__setattr__(
            self,
            "_bot_user",
            User(id=42, first_name="Kaban", is_bot=True, username="kaban"),
        )

    async def initialize(self) -> None:
        object.__setattr__(self, "_initialized", True)

    async def shutdown(self) -> None:
        object.__setattr__(self, "_initialized", False)

    async def get_me(self, *args, **kwargs):
        del args, kwargs
        return self._bot_user

    async def send_message(self, *args, **kwargs):
        del args
        sent = {
            "chat_id": kwargs["chat_id"],
            "text": kwargs["text"],
            "parse_mode": kwargs.get("parse_mode"),
        }
        self.sent_messages.append(sent)

        message_id = self._next_message_id
        object.__setattr__(self, "_next_message_id", message_id + 1)
        payload = {
            "message_id": message_id,
            "date": 0,
            "chat": {"id": kwargs["chat_id"], "type": "private"},
            "from": {
                "id": self._bot_user.id,
                "is_bot": True,
                "first_name": self._bot_user.first_name,
                "username": self._bot_user.username,
            },
            "text": kwargs["text"],
        }
        return Message.de_json(payload, self)

    async def send_chat_action(self, *args, **kwargs):
        del args
        self.sent_actions.append(kwargs)
        return True

    async def get_file(self, file_id: str):
        return self.files[file_id]


class _InjectedBotBuilder:
    def __init__(self, bot: _FakeBot) -> None:
        self._builder = ApplicationBuilder().bot(bot)

    def token(self, _value):
        return self

    def build(self):
        return self._builder.build()


class _HermeticBotHarness:
    def __init__(
        self,
        *,
        monkeypatch,
        tmp_path: Path,
        features=None,
        created_events=None,
    ) -> None:
        store_path = tmp_path / "messages.jsonl"
        self.settings = _settings(store_path, features=features)
        self.providers = SimpleNamespace(
            text=_FakeTextGenerationProvider(),
            streaming=_FakeStreamingTextGenerationProvider(),
            low_cost=_FakeLowCostTextGenerationProvider(),
            audio=_FakeAudioTranscriptionProvider(),
            ocr=_FakeOcrProvider(),
            reaction=_FakeReactionSelectionProvider(),
            events=_FakeEventParsingProvider(),
        )
        self.bot = _FakeBot()
        self._next_update_id = 1
        self._next_message_id = 1
        self.created_events = [] if created_events is None else created_events

        message_store.clear_memory_state()
        monkeypatch.setattr(config, "get_settings", lambda force=False: self.settings)
        monkeypatch.setattr(
            bot_app.logging_utils,
            "update_log_level",
            lambda _level: None,
        )
        if created_events is not None:
            monkeypatch.setattr(
                "src.bot.features.events.CalendarProvider",
                lambda: _RecordingCalendarProvider(self.created_events),
            )

        self.runtime = bot_app.build_runtime(
            settings_getter=lambda force=False: self.settings,
            capabilities=_runtime_capabilities(self.providers),
        )
        self.application = bot_app.build_application(
            self.runtime,
            settings=self.settings,
            application_builder_factory=lambda: _InjectedBotBuilder(self.bot),
        )

    @property
    def reply_texts(self):
        return [message["text"] for message in self.bot.sent_messages]

    def clear_state(self) -> None:
        message_store.clear_memory_state()

    def register_file(self, *, file_id: str, payload: bytes, file_size=None):
        telegram_file = _FakeTelegramFile(payload, file_size=file_size)
        self.bot.files[file_id] = telegram_file
        return telegram_file

    def dispatch_command(
        self,
        command: str,
        *,
        chat_id: int = 111,
        user_id: int = 111,
        chat_type: str = "private",
    ) -> Update:
        update = self._build_update(
            chat_id=chat_id,
            user_id=user_id,
            chat_type=chat_type,
            text=f"/{command}",
            entities=[{"type": "bot_command", "offset": 0, "length": len(command) + 1}],
        )
        self._dispatch(update)
        return update

    def dispatch_text(
        self,
        text: str,
        *,
        chat_id: int = 111,
        user_id: int = 111,
        chat_type: str = "private",
        entities=None,
        reply_to_message=None,
    ) -> Update:
        update = self._build_update(
            chat_id=chat_id,
            user_id=user_id,
            chat_type=chat_type,
            text=text,
            entities=entities,
            reply_to_message=reply_to_message,
        )
        self._dispatch(update)
        return update

    def dispatch_photo(
        self,
        *,
        file_id: str,
        caption: str = "",
        chat_id: int = 111,
        user_id: int = 111,
        chat_type: str = "private",
    ) -> Update:
        update = self._build_update(
            chat_id=chat_id,
            user_id=user_id,
            chat_type=chat_type,
            caption=caption,
            photo=[
                {
                    "file_id": file_id,
                    "file_unique_id": f"{file_id}-unique",
                    "width": 1,
                    "height": 1,
                }
            ],
        )
        self._dispatch(update)
        return update

    def dispatch_voice(
        self,
        *,
        file_id: str,
        chat_id: int = 111,
        user_id: int = 111,
        chat_type: str = "private",
        caption: str = "",
        caption_entities=None,
    ) -> Update:
        update = self._build_update(
            chat_id=chat_id,
            user_id=user_id,
            chat_type=chat_type,
            caption=caption,
            caption_entities=caption_entities,
            voice={
                "file_id": file_id,
                "file_unique_id": f"{file_id}-unique",
                "duration": 1,
                "mime_type": "audio/ogg",
            },
        )
        self._dispatch(update)
        return update

    def _dispatch(self, update: Update) -> None:
        asyncio.run(self._dispatch_async(update))

    async def _dispatch_async(self, update: Update) -> None:
        await self.application.initialize()
        try:
            await self.application.process_update(update)
        finally:
            await self.application.shutdown()

    def _build_update(
        self,
        *,
        chat_id: int,
        user_id: int,
        chat_type: str,
        text=None,
        entities=None,
        caption=None,
        caption_entities=None,
        photo=None,
        voice=None,
        reply_to_message=None,
    ) -> Update:
        message_id = self._next_message_id
        self._next_message_id += 1

        message_payload = {
            "message_id": message_id,
            "date": 0,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": user_id, "is_bot": False, "first_name": "Alice"},
        }
        if text is not None:
            message_payload["text"] = text
        if entities is not None:
            message_payload["entities"] = entities
        if caption is not None:
            message_payload["caption"] = caption
        if caption_entities is not None:
            message_payload["caption_entities"] = caption_entities
        if photo is not None:
            message_payload["photo"] = photo
        if voice is not None:
            message_payload["voice"] = voice
        if reply_to_message is not None:
            message_payload["reply_to_message"] = reply_to_message

        update = Update.de_json(
            {
                "update_id": self._next_update_id,
                "message": message_payload,
            },
            self.bot,
        )
        self._next_update_id += 1
        return update


@pytest.fixture
def bot_harness(monkeypatch, tmp_path):
    harness = _HermeticBotHarness(monkeypatch=monkeypatch, tmp_path=tmp_path)
    yield harness
    harness.clear_state()


def test_hermetic_harness_builds_real_application_and_registers_handlers(
    bot_harness,
) -> None:
    assert isinstance(bot_harness.application, Application)

    handlers = [
        handler
        for group in bot_harness.application.handlers.values()
        for handler in group
    ]
    command_handlers = [
        handler for handler in handlers if isinstance(handler, CommandHandler)
    ]
    message_handlers = [
        handler
        for handler in handlers
        if isinstance(handler, TelegramMessageHandler)
    ]

    assert any(set(handler.commands) == {"hi"} for handler in command_handlers)
    assert any(
        set(handler.commands) == {"summary", "tldr"} for handler in command_handlers
    )
    assert len(message_handlers) == 2


def test_hermetic_harness_dispatches_hi_command_end_to_end(bot_harness) -> None:
    bot_harness.dispatch_command("hi")

    assert bot_harness.reply_texts[0] == "Hello! I am your speech-to-text bot."
    assert "Available AI capabilities:" in bot_harness.reply_texts[1]
    assert "Configured AI routing:" in bot_harness.reply_texts[2]
    assert message_store.get_all_messages("111") == []


def test_hermetic_harness_dispatches_summary_command_end_to_end(bot_harness) -> None:
    summary_store.save_summary_state(
        "111",
        {
            "version": 1,
            "last_message_count": 4,
            "chunks": [
                {
                    "id": "chunk-0-3",
                    "source_message_ids": ["m1", "m2", "m3", "m4"],
                    "summary": "Need follow-up on launch checklist",
                    "facts": ["Budget approved"],
                    "decisions": ["Ship on Friday"],
                    "open_items": ["Confirm owner"],
                }
            ],
        },
    )

    bot_harness.dispatch_command("summary")

    assert len(bot_harness.reply_texts) == 1
    reply = bot_harness.reply_texts[0]
    assert "Summary overview" in reply
    assert "Chunks total: 1" in reply
    assert "Summary: Need follow-up on launch checklist" in reply
    assert "Facts (1):" in reply
    assert "- Budget approved" in reply
    assert "- Ship on Friday" in reply
    assert "- Confirm owner" in reply
    assert message_store.get_all_messages("111") == []


def test_group_addressed_message_flow_persists_history_and_bot_reply(
    bot_harness,
) -> None:
    bot_harness.providers.text.response = "Let us draft the rollout plan next."

    bot_harness.dispatch_text(
        "Project status: build passed and QA signed off.",
        chat_id=-222,
        user_id=333,
        chat_type="group",
    )
    mention_update = bot_harness.dispatch_text(
        "@kaban what should we do next?",
        chat_id=-222,
        user_id=444,
        chat_type="group",
        entities=[{"type": "mention", "offset": 0, "length": 6}],
    )

    assert bot_harness.reply_texts == ["Let us draft the rollout plan next."]
    assert len(bot_harness.providers.text.prompts) == 1
    prompt = bot_harness.providers.text.prompts[0]
    assert "[RECENT_DIALOGUE]" in prompt
    assert "Project status: build passed and QA signed off." in prompt
    assert prompt.endswith("Alice: @kaban what should we do next?")
    assert bot_harness.providers.low_cost.prompts == []

    bot_harness.clear_state()
    stored_messages = message_store.get_all_messages("-222")

    assert [message["text"] for message in stored_messages] == [
        "Project status: build passed and QA signed off.",
        "@kaban what should we do next?",
        "Let us draft the rollout plan next.",
    ]
    assert [message["kind"] for message in stored_messages] == ["user", "user", "bot"]
    assert stored_messages[1]["telegram_message_id"] == mention_update.message.message_id


def test_voice_message_flow_uses_fake_download_and_cleans_temp_file(
    monkeypatch,
    tmp_path,
) -> None:
    bot_harness = _HermeticBotHarness(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        features={"message_handling": True, "schedule_events": False},
    )
    removed_paths = []
    original_remove = os.remove

    def _capture_remove(path: str) -> None:
        removed_paths.append(path)
        original_remove(path)

    monkeypatch.setattr(os, "remove", _capture_remove)

    bot_harness.providers.audio.response = "kaban review the roadmap"
    bot_harness.providers.text.response = "Voice plan confirmed."
    telegram_file = bot_harness.register_file(file_id="voice-1", payload=b"voice-bytes")

    bot_harness.dispatch_voice(file_id="voice-1")

    assert bot_harness.reply_texts == [">>kaban review the roadmap\n\nVoice plan confirmed."]
    assert len(bot_harness.providers.text.prompts) == 1
    assert bot_harness.providers.text.prompts[0].endswith(
        "Alice: kaban review the roadmap"
    )
    assert bot_harness.providers.audio.audio_paths == telegram_file.drive_paths
    assert len(removed_paths) == 1
    assert removed_paths[0] == telegram_file.drive_paths[0]
    assert not Path(removed_paths[0]).exists()

    bot_harness.clear_state()
    stored_messages = message_store.get_all_messages("111")
    assert [message["text"] for message in stored_messages] == [
        "kaban review the roadmap",
        ">>kaban review the roadmap\n\nVoice plan confirmed.",
    ]
    assert [message["kind"] for message in stored_messages] == ["user", "bot"]


def test_schedule_events_photo_flow_creates_event_and_cleans_temp_file(
    monkeypatch,
    tmp_path,
) -> None:
    created_events = []
    bot_harness = _HermeticBotHarness(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        features={"message_handling": False, "schedule_events": True},
        created_events=created_events,
    )
    removed_paths = []
    original_remove = os.remove

    def _capture_remove(path: str) -> None:
        removed_paths.append(path)
        original_remove(path)

    monkeypatch.setattr(os, "remove", _capture_remove)

    telegram_file = bot_harness.register_file(file_id="event-photo", payload=b"photo")

    bot_harness.dispatch_photo(file_id="event-photo")

    assert bot_harness.reply_texts == [
        "Event created successfully!\n"
        "Title: Design Review\n"
        "Date: 2030-06-20\n"
        f"Time: 14:00 ({created_events[0]['start_time'].tzinfo})\n"
        "Location: Office"
    ]
    assert bot_harness.providers.events.requests == telegram_file.drive_paths
    assert len(created_events) == 1
    created_event = created_events[0]
    assert created_event["title"] == "Design Review"
    assert created_event["is_all_day"] is False
    assert created_event["start_time"].strftime("%Y-%m-%d %H:%M") == "2030-06-20 14:00"
    assert created_event["location"] == "Office"
    assert created_event["description"] == "Discuss architecture"
    assert len(removed_paths) == 1
    assert removed_paths[0] == telegram_file.drive_paths[0]
    assert not Path(removed_paths[0]).exists()
