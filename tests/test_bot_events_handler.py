import asyncio
import os
from types import SimpleNamespace

from src.bot import app as bot_app
from src.bot.handlers.events_handler import EventsHandler
from src.bot.services.media_service import IMAGE_MAX_BYTES


def _noop_calendar_factory():
    return SimpleNamespace(create_event=lambda **_kwargs: None)


def _handler(
    event_parsing_provider,
    *,
    is_allowed_fn,
    notify_admin_fn,
    settings_getter,
    calendar_provider_factory=_noop_calendar_factory,
):
    return EventsHandler(
        is_allowed_fn=is_allowed_fn,
        event_parsing_provider=event_parsing_provider,
        notify_admin_fn=notify_admin_fn,
        log_context_fn=lambda _update: {},
        settings_getter=settings_getter,
        calendar_provider_factory=calendar_provider_factory,
    )


def test_schedule_events_exits_when_feature_disabled() -> None:
    notifications = []
    sent_actions = []

    async def _notify_admin(context, message):
        notifications.append((context, message))

    async def _send_action(**kwargs):
        sent_actions.append(kwargs)

    handler = _handler(
        SimpleNamespace(parse_image_event=lambda _request: {}),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": False}),
    )

    update = SimpleNamespace(
        message=SimpleNamespace(photo=[SimpleNamespace(file_id="photo")]),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    asyncio.run(handler.schedule_events(update, context))

    assert sent_actions == []
    assert notifications == []


def test_schedule_events_exits_when_update_not_allowed() -> None:
    notifications = []
    sent_actions = []
    bot_calls = {"get_file": 0}

    async def _notify_admin(context, message):
        notifications.append((context, message))

    async def _send_action(**kwargs):
        sent_actions.append(kwargs)

    class _FakeBot:
        async def get_file(self, _file_id: str):
            bot_calls["get_file"] += 1
            raise AssertionError("disallowed updates must exit before downloading")

    handler = _handler(
        SimpleNamespace(parse_image_event=lambda _request: {}),
        is_allowed_fn=lambda _update: False,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
    )

    update = SimpleNamespace(
        message=SimpleNamespace(photo=[SimpleNamespace(file_id="photo")]),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert sent_actions == []
    assert notifications == []
    assert bot_calls["get_file"] == 0


def test_schedule_events_exits_without_photo() -> None:
    notifications = []

    async def _notify_admin(context, message):
        notifications.append((context, message))

    handler = _handler(
        SimpleNamespace(parse_image_event=lambda _request: {}),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
    )

    update = SimpleNamespace(
        message=SimpleNamespace(photo=[]),
        effective_chat=SimpleNamespace(send_action=lambda **kwargs: None),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    asyncio.run(handler.schedule_events(update, context))

    assert notifications == []


def test_schedule_events_rejects_oversized_photo() -> None:
    notifications = []
    responses = []
    bot_calls = {"get_file": 0}

    async def _notify_admin(context, message):
        notifications.append((context, message))

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    class _FakeBot:
        async def get_file(self, _file_id: str):
            bot_calls["get_file"] += 1
            raise AssertionError("oversized photo should not be downloaded")

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(parse_image_event=lambda _request: {}),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[
                SimpleNamespace(
                    file_id="photo",
                    file_size=IMAGE_MAX_BYTES + 1,
                )
            ],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert notifications == []
    assert bot_calls["get_file"] == 0
    assert any("too large" in text for text in responses)


def test_schedule_events_accepts_unknown_file_size_when_download_is_small(
    monkeypatch,
) -> None:
    removed = []
    events = []
    notifications = []
    responses = []

    async def _notify_admin(context, message):
        notifications.append((context, message))

    class _UnknownSizeFile:
        file_size = None

        async def download_to_drive(self, path: str) -> None:
            with open(path, "wb") as stream:
                stream.write(b"photo")

    class _FakeBot:
        async def get_file(self, _file_id: str):
            return _UnknownSizeFile()

    class _FakeCalendar:
        def create_event(self, **kwargs) -> None:
            events.append(kwargs)

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    monkeypatch.setattr(
        "src.bot.handlers.events_handler.os.remove",
        lambda path: removed.append(path),
    )

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(
            parse_image_event=lambda _request: {
                "title": "Design Review",
                "date": "2030-06-20",
                "time": "14:00",
                "location": "Office",
                "description": "Discuss architecture",
                "confidence": 0.9,
            }
        ),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
        calendar_provider_factory=_FakeCalendar,
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[SimpleNamespace(file_id="photo", file_size=None)],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert len(events) == 1
    assert removed
    assert notifications == []
    assert any("Event created successfully!" in text for text in responses)


def test_schedule_events_rejects_oversized_download_when_size_unknown(
    monkeypatch,
) -> None:
    removed = []
    notifications = []
    responses = []
    parse_calls = {"count": 0}

    async def _notify_admin(context, message):
        notifications.append((context, message))

    class _UnknownSizeFile:
        file_size = None

        async def download_to_drive(self, path: str) -> None:
            with open(path, "wb") as stream:
                stream.write(b"12345")

    class _FakeBot:
        async def get_file(self, _file_id: str):
            return _UnknownSizeFile()

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    monkeypatch.setattr("src.bot.handlers.events_handler.IMAGE_MAX_BYTES", 4)
    monkeypatch.setattr(
        "src.bot.handlers.events_handler.os.remove",
        lambda path: removed.append(path),
    )

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(
            parse_image_event=lambda _request: parse_calls.update(
                count=parse_calls["count"] + 1
            )
        ),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[SimpleNamespace(file_id="photo", file_size=None)],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert removed
    assert notifications == []
    assert parse_calls["count"] == 0
    assert any("too large" in text for text in responses)


def test_schedule_events_creates_event_and_cleans_temp_file(monkeypatch) -> None:
    removed = []
    events = []
    notifications = []
    responses = []

    class _FakeFile:
        file_size = 1024

        async def download_to_drive(self, path: str) -> None:
            with open(path, "wb") as stream:
                stream.write(b"photo")

    class _FakeCalendar:
        def create_event(self, **kwargs) -> None:
            events.append(kwargs)

    class _FakeBot:
        async def get_file(self, _file_id: str) -> _FakeFile:
            return _FakeFile()

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    monkeypatch.setattr(
        "src.bot.handlers.events_handler.os.remove",
        lambda path: removed.append(path),
    )

    async def _notify_admin(context, message):
        notifications.append((context, message))

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(
            parse_image_event=lambda _request: {
                "title": "Design Review",
                "date": "2030-06-20",
                "time": "14:00",
                "location": "Office",
                "description": "Discuss architecture",
                "confidence": 0.95,
            }
        ),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
        calendar_provider_factory=_FakeCalendar,
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[SimpleNamespace(file_id="photo")],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert len(events) == 1
    assert events[0]["title"] == "Design Review"
    assert removed
    assert notifications == []
    assert any("Event created successfully!" in text for text in responses)


def test_schedule_events_accepts_string_confidence(monkeypatch) -> None:
    removed = []
    events = []
    notifications = []
    responses = []

    class _FakeFile:
        file_size = 1024

        async def download_to_drive(self, path: str) -> None:
            with open(path, "wb") as stream:
                stream.write(b"photo")

    class _FakeCalendar:
        def create_event(self, **kwargs) -> None:
            events.append(kwargs)

    class _FakeBot:
        async def get_file(self, _file_id: str) -> _FakeFile:
            return _FakeFile()

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    monkeypatch.setattr(
        "src.bot.handlers.events_handler.os.remove",
        lambda path: removed.append(path),
    )

    async def _notify_admin(context, message):
        notifications.append((context, message))

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(
            parse_image_event=lambda _request: {
                "title": "Design Review",
                "date": "2030-06-20",
                "time": "14:00",
                "location": "Office",
                "description": "Discuss architecture",
                "confidence": "0.3",
            }
        ),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
        calendar_provider_factory=_FakeCalendar,
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[SimpleNamespace(file_id="photo", file_size=1024)],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert len(events) == 1
    assert removed
    assert notifications == []
    assert any("not very confident" in text for text in responses)


def test_schedule_events_handles_all_day_events_without_time(monkeypatch) -> None:
    events = []
    responses = []
    removed = []

    class _FakeFile:
        file_size = 1024

        async def download_to_drive(self, path: str) -> None:
            with open(path, "wb") as stream:
                stream.write(b"photo")

    class _FakeCalendar:
        def create_event(self, **kwargs) -> None:
            events.append(kwargs)

    class _FakeBot:
        async def get_file(self, _file_id: str) -> _FakeFile:
            return _FakeFile()

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    monkeypatch.setattr(
        "src.bot.handlers.events_handler.os.remove",
        lambda path: removed.append(path),
    )

    async def _notify_admin(_context, _message):
        return None

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(
            parse_image_event=lambda _request: {
                "title": "All Day Event",
                "date": "2030-07-20",
                "location": "Office",
                "description": "No time field provided",
                "confidence": 0.95,
            }
        ),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
        calendar_provider_factory=_FakeCalendar,
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[SimpleNamespace(file_id="photo")],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert len(events) == 1
    assert events[0]["is_all_day"] is True
    assert removed
    assert any("All day event" in text for text in responses)


def test_schedule_events_reports_error_when_event_data_missing_date(
    monkeypatch,
) -> None:
    removed = []
    notifications = []
    responses = []

    class _FakeFile:
        file_size = 1024

        async def download_to_drive(self, path: str) -> None:
            with open(path, "wb") as stream:
                stream.write(b"photo")

    class _FakeBot:
        async def get_file(self, _file_id: str) -> _FakeFile:
            return _FakeFile()

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    monkeypatch.setattr(
        "src.bot.handlers.events_handler.os.remove",
        lambda path: removed.append(path),
    )

    async def _notify_admin(context, message):
        notifications.append((context, message))

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(
            parse_image_event=lambda _request: {
                "title": "Missing Date",
                "location": "Office",
                "confidence": 0.55,
            }
        ),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[SimpleNamespace(file_id="photo")],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FakeBot())

    asyncio.run(handler.schedule_events(update, context))

    assert notifications
    assert removed
    assert any("couldn't process the photo" in text for text in responses)


def test_schedule_events_handles_chat_file_download_failure(monkeypatch) -> None:
    notifications = []
    responses = []
    removed = []

    class _FakeMessage:
        async def reply_text(self, text: str) -> None:
            responses.append(text)

    async def _notify_admin(context, message):
        notifications.append((context, message))

    async def _send_action(**kwargs):
        return None

    handler = _handler(
        SimpleNamespace(parse_image_event=lambda _request: {}),
        is_allowed_fn=lambda _update: True,
        notify_admin_fn=_notify_admin,
        settings_getter=lambda: SimpleNamespace(features={"schedule_events": True}),
    )

    class _FailingBot:
        async def get_file(self, _file_id: str):
            raise RuntimeError("download unavailable")

    monkeypatch.setattr(
        "src.bot.handlers.events_handler.os.remove",
        lambda path: removed.append(path),
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            photo=[SimpleNamespace(file_id="photo")],
            reply_text=_FakeMessage().reply_text,
        ),
        effective_chat=SimpleNamespace(send_action=_send_action),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=_FailingBot())

    asyncio.run(handler.schedule_events(update, context))

    assert notifications
    assert removed == []
    assert any("something went wrong" in text for text in responses)


def test_build_application_wiring_smoke(monkeypatch) -> None:
    class _FakeApp:
        def __init__(self) -> None:
            self.handlers = []
            self.error_handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

        def add_error_handler(self, callback):
            self.error_handlers.append(callback)

    class _FakeBuilder:
        def __init__(self, app):
            self.app = app
            self.token_value = None

        def token(self, value):
            self.token_value = value
            return self

        def build(self):
            return self.app

    fake_app = _FakeApp()
    fake_builder = _FakeBuilder(fake_app)
    monkeypatch.setattr(bot_app, "ApplicationBuilder", lambda: fake_builder)

    async def _hi(update, context):
        return None

    async def _summary(update, context):
        return None

    async def _message(update, context):
        return None

    async def _events(update, context):
        return None

    async def _error(update, context):
        return None

    class _Runtime:
        def __init__(self):
            self.summary_handler = SimpleNamespace(view_summary=_summary)
            self.message_handler = SimpleNamespace(handle_addressed_message=_message)
            self.events_handler = SimpleNamespace(schedule_events=_events)
            self.hi = _hi
            self.error_handler = _error
            self.applied = []

        def apply_log_level(self, settings):
            self.applied.append(settings)

    runtime = _Runtime()
    settings = SimpleNamespace(
        telegram_bot_token="token",
        features={"message_handling": True, "schedule_events": False},
        debug_mode=False,
    )

    app = bot_app.build_application(runtime, settings=settings)

    assert app is fake_app
    assert fake_builder.token_value == "token"
    assert fake_app.error_handlers == [_error]
    callbacks = [handler.callback for handler in fake_app.handlers]
    assert _hi in callbacks
    assert _summary in callbacks
    assert _message in callbacks
    assert _events not in callbacks
    assert runtime.applied == [settings]
