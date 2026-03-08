import asyncio
from types import SimpleNamespace

from telegram.ext import CommandHandler, MessageHandler as TelegramMessageHandler

from src.bot import app as bot_app


def _runtime(settings):
    return bot_app.BotRuntime(
        settings_getter=lambda force=False: settings,
        provider_getter=lambda: None,
        reaction_service=SimpleNamespace(),
        summary_handler=SimpleNamespace(),
        message_handler=SimpleNamespace(handle_addressed_message=None),
        events_handler=SimpleNamespace(),
        is_allowed_fn=lambda _update: True,
        log_context_fn=lambda _update: {},
    )


def test_bot_runtime_notify_admin_escapes_html() -> None:
    settings = SimpleNamespace(admin_chat_id="99")
    runtime = _runtime(settings)
    sent = {}

    async def _send_message(*, chat_id, text, parse_mode):
        sent["chat_id"] = chat_id
        sent["text"] = text
        sent["parse_mode"] = parse_mode

    context = SimpleNamespace(bot=SimpleNamespace(send_message=_send_message))
    asyncio.run(runtime.notify_admin(context, "<b>alert</b>"))

    assert sent["chat_id"] == "99"
    assert sent["text"] == "&lt;b&gt;alert&lt;/b&gt;"


def test_bot_runtime_error_handler_redacts_context_data() -> None:
    settings = SimpleNamespace(admin_chat_id="99")
    runtime = _runtime(settings)
    sent = {}

    async def _send_message(*, chat_id, text, parse_mode):
        sent["chat_id"] = chat_id
        sent["text"] = text
        sent["parse_mode"] = parse_mode

    context = SimpleNamespace(
        error=RuntimeError("boom"),
        chat_data={"token": "secret-chat-token"},
        user_data={"token": "secret-user-token"},
        bot=SimpleNamespace(send_message=_send_message),
    )

    asyncio.run(runtime.error_handler("opaque update payload", context))

    assert sent["chat_id"] == "99"
    assert "update_meta" in sent["text"]
    assert "context.chat_data" not in sent["text"]
    assert "context.user_data" not in sent["text"]
    assert "secret-chat-token" not in sent["text"]
    assert "secret-user-token" not in sent["text"]


def test_bot_runtime_error_handler_skips_admin_notification_without_admin_chat_id() -> None:
    settings = SimpleNamespace(admin_chat_id=None)
    runtime = _runtime(settings)
    send_calls = []

    async def _send_message(**kwargs):
        send_calls.append(kwargs)

    context = SimpleNamespace(
        error=RuntimeError("boom"),
        chat_data={"token": "secret-chat-token"},
        user_data={"token": "secret-user-token"},
        bot=SimpleNamespace(send_message=_send_message),
    )

    asyncio.run(runtime.error_handler("opaque update payload", context))

    assert send_calls == []


def test_bot_runtime_supports_no_arg_settings_getter(monkeypatch) -> None:
    settings = SimpleNamespace(admin_chat_id=None, debug_mode=False)
    levels = []
    monkeypatch.setattr(
        bot_app.logging_utils,
        "update_log_level",
        lambda level: levels.append(level),
    )

    runtime = bot_app.BotRuntime(
        settings_getter=lambda: settings,
        provider_getter=lambda: None,
        reaction_service=SimpleNamespace(),
        summary_handler=SimpleNamespace(),
        message_handler=SimpleNamespace(handle_addressed_message=None),
        events_handler=SimpleNamespace(),
        is_allowed_fn=lambda _update: True,
        log_context_fn=lambda _update: {},
    )

    assert runtime.get_settings(force=True) is settings
    asyncio.run(runtime.refresh_settings_job(None))
    assert levels


def test_build_runtime_uses_injected_provider(monkeypatch) -> None:
    settings = SimpleNamespace(admin_chat_id=None, debug_mode=False)
    provider = SimpleNamespace()

    def _forbidden_build_provider():
        raise AssertionError(
            "build_provider should not be used when provider is injected"
        )

    monkeypatch.setattr(bot_app, "build_provider", _forbidden_build_provider)

    runtime = bot_app.build_runtime(
        settings_getter=lambda force=False: settings,
        provider=provider,
    )

    assert runtime.provider() is provider
    assert runtime.reaction_service._provider_getter() is provider


def test_build_application_routes_commands_and_feature_handlers(monkeypatch) -> None:
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

    async def _hi(update, context):
        del update, context
        return None

    async def _summary(update, context):
        del update, context
        return None

    async def _message(update, context):
        del update, context
        return None

    async def _events(update, context):
        del update, context
        return None

    async def _error(update, context):
        del update, context
        return None

    applied = []
    runtime = SimpleNamespace(
        summary_handler=SimpleNamespace(view_summary=_summary),
        message_handler=SimpleNamespace(handle_addressed_message=_message),
        events_handler=SimpleNamespace(schedule_events=_events),
        hi=_hi,
        error_handler=_error,
        apply_log_level=lambda settings: applied.append(settings),
    )
    settings = SimpleNamespace(
        telegram_bot_token="token",
        features={"message_handling": True, "schedule_events": True},
        debug_mode=False,
    )

    fake_app = _FakeApp()
    fake_builder = _FakeBuilder(fake_app)
    monkeypatch.setattr(bot_app, "ApplicationBuilder", lambda: fake_builder)

    app = bot_app.build_application(runtime, settings=settings)

    assert app is fake_app
    assert fake_builder.token_value == "token"
    assert fake_app.error_handlers == [_error]
    assert applied == [settings]
    command_handlers = [
        handler for handler in fake_app.handlers if isinstance(handler, CommandHandler)
    ]
    assert any(
        set(handler.commands) == {"hi"} and handler.callback is _hi
        for handler in command_handlers
    )
    assert any(
        set(handler.commands) == {"summary", "tldr"}
        and handler.callback is _summary
        for handler in command_handlers
    )
    message_callbacks = [
        handler.callback
        for handler in fake_app.handlers
        if isinstance(handler, TelegramMessageHandler)
    ]
    assert _message in message_callbacks
    assert _events in message_callbacks


def test_build_application_skips_optional_handlers_when_features_disabled(
    monkeypatch,
) -> None:
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

        def token(self, _value):
            return self

        def build(self):
            return self.app

    async def _hi(update, context):
        del update, context
        return None

    async def _summary(update, context):
        del update, context
        return None

    async def _message(update, context):
        del update, context
        return None

    async def _events(update, context):
        del update, context
        return None

    async def _error(update, context):
        del update, context
        return None

    runtime = SimpleNamespace(
        summary_handler=SimpleNamespace(view_summary=_summary),
        message_handler=SimpleNamespace(handle_addressed_message=_message),
        events_handler=SimpleNamespace(schedule_events=_events),
        hi=_hi,
        error_handler=_error,
        apply_log_level=lambda _settings: None,
    )
    settings = SimpleNamespace(
        telegram_bot_token="token",
        features={"message_handling": False, "schedule_events": False},
        debug_mode=False,
    )

    fake_app = _FakeApp()
    fake_builder = _FakeBuilder(fake_app)
    monkeypatch.setattr(bot_app, "ApplicationBuilder", lambda: fake_builder)

    bot_app.build_application(runtime, settings=settings)

    message_callbacks = [
        handler.callback
        for handler in fake_app.handlers
        if isinstance(handler, TelegramMessageHandler)
    ]
    assert _message not in message_callbacks
    assert _events not in message_callbacks


def test_run_polling_builds_runtime_when_not_provided(monkeypatch) -> None:
    settings = SimpleNamespace(debug_mode=False, features={"message_handling": True})
    runtime = SimpleNamespace(get_settings=lambda: settings)
    calls = []

    def _fake_build_runtime():
        calls.append("build_runtime")
        return runtime

    class _FakeApp:
        def run_polling(self):
            calls.append("run_polling")

    def _fake_build_application(runtime_arg, *, settings):
        calls.append(("build_application", runtime_arg, settings))
        return _FakeApp()

    monkeypatch.setattr(bot_app, "build_runtime", _fake_build_runtime)
    monkeypatch.setattr(bot_app, "build_application", _fake_build_application)

    bot_app.run_polling()

    assert calls[0] == "build_runtime"
    assert calls[1] == ("build_application", runtime, settings)
    assert calls[2] == "run_polling"


def test_run_polling_uses_passed_runtime(monkeypatch) -> None:
    settings = SimpleNamespace(debug_mode=False, features={"message_handling": True})
    runtime = SimpleNamespace(get_settings=lambda: settings)
    called = {}

    def _forbidden_build_runtime():
        raise AssertionError("run_polling should use passed runtime")

    class _FakeApp:
        def run_polling(self):
            called["ran"] = True

    def _fake_build_application(runtime_arg, *, settings):
        called["runtime"] = runtime_arg
        called["settings"] = settings
        return _FakeApp()

    monkeypatch.setattr(bot_app, "build_runtime", _forbidden_build_runtime)
    monkeypatch.setattr(bot_app, "build_application", _fake_build_application)

    bot_app.run_polling(runtime=runtime)

    assert called["runtime"] is runtime
    assert called["settings"] is settings
    assert called["ran"] is True
