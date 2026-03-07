import asyncio
from types import SimpleNamespace

from src.bot import app as bot_app
from src.bot.handlers.events_handler import EventsHandler


def test_schedule_events_exits_when_feature_disabled() -> None:
    notifications = []
    sent_actions = []

    async def _notify_admin(context, message):
        notifications.append((context, message))

    async def _send_action(**kwargs):
        sent_actions.append(kwargs)

    handler = EventsHandler(
        is_allowed_fn=lambda _update: True,
        provider_getter=lambda: SimpleNamespace(parse_image_to_event=lambda _path: {}),
        notify_admin_fn=_notify_admin,
        log_context_fn=lambda _update: {},
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


def test_schedule_events_exits_without_photo() -> None:
    notifications = []

    async def _notify_admin(context, message):
        notifications.append((context, message))

    handler = EventsHandler(
        is_allowed_fn=lambda _update: True,
        provider_getter=lambda: SimpleNamespace(parse_image_to_event=lambda _path: {}),
        notify_admin_fn=_notify_admin,
        log_context_fn=lambda _update: {},
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
