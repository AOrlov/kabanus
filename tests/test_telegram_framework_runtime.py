import asyncio
from types import SimpleNamespace

from telegram.constants import ParseMode

from src.telegram_framework import application
from src.telegram_framework import error_reporting
from src.telegram_framework.runtime import PollingRuntime, SettingsResolver


class _Logger:
    def __init__(self) -> None:
        self.info_calls = []

    def info(self, message, payload):
        self.info_calls.append((message, payload))


def test_settings_resolver_uses_force_for_compatible_getters() -> None:
    calls = []
    settings = SimpleNamespace(value="ok")

    def _settings_getter(force=False):
        calls.append(force)
        return settings

    resolver = SettingsResolver(_settings_getter)

    assert resolver.get(force=True) is settings
    assert calls == [True]


def test_settings_resolver_supports_no_arg_getter() -> None:
    settings = SimpleNamespace(value="ok")
    resolver = SettingsResolver(lambda: settings)

    assert resolver.get(force=True) is settings


def test_settings_resolver_does_not_pass_force_kwarg_to_varargs_getter() -> None:
    calls = []
    settings = SimpleNamespace(value="ok")

    def _settings_getter(*args):
        calls.append(args)
        return settings

    resolver = SettingsResolver(_settings_getter)

    assert resolver.get(force=True) is settings
    assert calls == [()]


def test_framework_build_application_uses_hook_points() -> None:
    class _FakeApp:
        def __init__(self) -> None:
            self.error_handlers = []
            self.registered = []

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

    async def _error(update, context):
        del update, context
        return None

    def _register_handlers(app):
        app.registered.append("called")

    app = application.build_application(
        token="abc",
        register_handlers=_register_handlers,
        error_handler=_error,
        application_builder_factory=lambda: fake_builder,
    )

    assert app is fake_app
    assert fake_builder.token_value == "abc"
    assert fake_app.error_handlers == [_error]
    assert fake_app.registered == ["called"]


def test_polling_runtime_bootstraps_application_and_runs_polling() -> None:
    settings = SimpleNamespace(features={"message_handling": True})
    logger = _Logger()
    calls = []

    class _FakeApp:
        def run_polling(self):
            calls.append("run_polling")

    def _build_application(configured_settings):
        calls.append(("build_application", configured_settings))
        return _FakeApp()

    runtime = PollingRuntime(
        settings_getter=lambda: settings,
        build_application_fn=_build_application,
        logger_override=logger,
        startup_log_value_fn=lambda loaded: loaded.features,
    )

    runtime.run_polling()

    assert calls == [
        ("build_application", settings),
        "run_polling",
    ]
    assert logger.info_calls == [
        ("Bot started with features: %s", {"message_handling": True})
    ]


def test_notify_admin_escapes_html() -> None:
    sent = {}

    async def _send_message(*, chat_id, text, parse_mode):
        sent["chat_id"] = chat_id
        sent["text"] = text
        sent["parse_mode"] = parse_mode

    context = SimpleNamespace(bot=SimpleNamespace(send_message=_send_message))

    asyncio.run(
        error_reporting.notify_admin(
            context,
            admin_chat_id="99",
            message="<b>alert</b>",
        )
    )

    assert sent == {
        "chat_id": "99",
        "text": "&lt;b&gt;alert&lt;/b&gt;",
        "parse_mode": ParseMode.HTML,
    }


def test_notify_admin_about_exception_formats_payload_without_context_data() -> None:
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

    asyncio.run(
        error_reporting.notify_admin_about_exception(
            "opaque update payload",
            context,
            admin_chat_id="99",
        )
    )

    assert sent["chat_id"] == "99"
    assert sent["parse_mode"] == ParseMode.HTML
    assert "update_meta" in sent["text"]
    assert "context.chat_data" not in sent["text"]
    assert "context.user_data" not in sent["text"]
    assert "secret-chat-token" not in sent["text"]
    assert "secret-user-token" not in sent["text"]


def test_build_error_report_message_truncation_keeps_valid_html_tags() -> None:
    long_error = RuntimeError("<boom>" * 2000)

    message = error_reporting.build_error_report_message(
        update="opaque update payload",
        error=long_error,
        max_len=512,
    )

    assert len(message) <= 512
    assert message.count("<pre>") >= 1
    assert message.count("<pre>") == message.count("</pre>")
    assert "<boom>" not in message
