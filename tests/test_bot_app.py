import asyncio
from types import SimpleNamespace

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
