from types import SimpleNamespace

from telegram.ext import MessageHandler as TelegramMessageHandler

from src.bot import features
from src.bot.features import events, message_flow


def test_register_handlers_delegates_to_feature_modules(monkeypatch) -> None:
    calls = []

    def _record(name):
        def _inner(*args, **kwargs):
            calls.append((name, args, kwargs))

        return _inner

    monkeypatch.setattr(features.commands, "register", _record("commands"))
    monkeypatch.setattr(features.summary, "register", _record("summary"))
    monkeypatch.setattr(features.message_flow, "register", _record("message_flow"))
    monkeypatch.setattr(features.events, "register", _record("events"))

    app = object()
    hi = object()
    view_summary = object()
    addressed = object()
    schedule_events = object()
    runtime = SimpleNamespace(
        hi=hi,
        summary_handler=SimpleNamespace(view_summary=view_summary),
        message_handler=SimpleNamespace(handle_addressed_message=addressed),
        events_handler=SimpleNamespace(schedule_events=schedule_events),
    )
    settings = SimpleNamespace()

    features.register_handlers(app, runtime=runtime, settings=settings)

    assert [name for name, _, _ in calls] == [
        "commands",
        "summary",
        "message_flow",
        "events",
    ]
    assert calls[0][2]["hi_callback"] is hi
    assert calls[1][2]["summary_callback"] is view_summary
    assert calls[2][2]["addressed_message_callback"] is addressed
    assert calls[3][2]["schedule_events_callback"] is schedule_events
    assert all(call[0] for call in calls)
    assert all(call[1] == (app,) for call in calls)
    assert all(call[2]["settings"] is settings for call in calls[2:])


def test_message_flow_register_honors_feature_flag() -> None:
    class _FakeApp:
        def __init__(self) -> None:
            self.handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

    async def _callback(update, context):
        del update, context
        return None

    app_enabled = _FakeApp()
    message_flow.register(
        app_enabled,
        settings=SimpleNamespace(features={"message_handling": True}),
        addressed_message_callback=_callback,
    )
    enabled_callbacks = [
        handler.callback
        for handler in app_enabled.handlers
        if isinstance(handler, TelegramMessageHandler)
    ]
    assert enabled_callbacks == [_callback]

    app_disabled = _FakeApp()
    message_flow.register(
        app_disabled,
        settings=SimpleNamespace(features={"message_handling": False}),
        addressed_message_callback=_callback,
    )
    assert app_disabled.handlers == []


def test_events_register_honors_feature_flag() -> None:
    class _FakeApp:
        def __init__(self) -> None:
            self.handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

    async def _callback(update, context):
        del update, context
        return None

    app_enabled = _FakeApp()
    events.register(
        app_enabled,
        settings=SimpleNamespace(features={"schedule_events": True}),
        schedule_events_callback=_callback,
    )
    enabled_callbacks = [
        handler.callback
        for handler in app_enabled.handlers
        if isinstance(handler, TelegramMessageHandler)
    ]
    assert enabled_callbacks == [_callback]

    app_disabled = _FakeApp()
    events.register(
        app_disabled,
        settings=SimpleNamespace(features={"schedule_events": False}),
        schedule_events_callback=_callback,
    )
    assert app_disabled.handlers == []


def test_build_message_flow_wires_provider_getter() -> None:
    settings = SimpleNamespace()
    provider = object()
    components = message_flow.build_message_flow(
        settings_getter=lambda force=False: settings,
        provider_getter=lambda: provider,
        is_allowed_fn=lambda _update: True,
        storage_id_fn=lambda _update: "chat",
        add_message_fn=lambda *args, **kwargs: None,
        get_all_messages_fn=lambda _chat_id: [],
        get_message_by_telegram_message_id_fn=lambda _chat_id, _message_id: None,
        build_context_fn=lambda *args, **kwargs: "",
        assemble_context_fn=lambda *args, **kwargs: "",
        log_context_fn=lambda _update: {},
    )

    assert components.reaction_service._provider_getter() is provider
    assert components.message_handler._provider_getter() is provider
