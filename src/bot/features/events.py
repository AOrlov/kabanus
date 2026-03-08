import logging
from typing import Awaitable, Callable, Optional

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src import config
from src.bot.handlers.events_handler import EventsHandler
from src.model_provider import ModelProvider

MessageCallback = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def build_events_handler(
    *,
    is_allowed_fn: Callable[[Update], bool],
    provider_getter: Callable[[], ModelProvider],
    notify_admin_fn: Callable[[ContextTypes.DEFAULT_TYPE, str], Awaitable[None]],
    log_context_fn: Callable[[Optional[Update]], dict],
    settings_getter: Callable[[], config.Settings],
    logger_override: Optional[logging.Logger] = None,
) -> EventsHandler:
    return EventsHandler(
        is_allowed_fn=is_allowed_fn,
        provider_getter=provider_getter,
        notify_admin_fn=notify_admin_fn,
        log_context_fn=log_context_fn,
        settings_getter=settings_getter,
        logger_override=logger_override,
    )


def register(
    app: Application,
    *,
    settings: config.Settings,
    schedule_events_callback: MessageCallback,
) -> None:
    if not settings.features.get("schedule_events"):
        return
    app.add_handler(MessageHandler(filters.PHOTO, schedule_events_callback))
