"""Reusable helpers for Telegram application assembly."""

from typing import Any, Callable, Optional

from telegram.ext import Application, ApplicationBuilder


def build_application(
    *,
    token: str,
    register_handlers: Optional[Callable[[Application], None]] = None,
    error_handler: Optional[Callable[..., Any]] = None,
    application_builder_factory: Callable[[], Any] = ApplicationBuilder,
) -> Application:
    builder = application_builder_factory()
    app = builder.token(token).build()

    if error_handler is not None:
        app.add_error_handler(error_handler)

    if register_handlers is not None:
        register_handlers(app)

    return app
