import logging
from typing import Optional

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from src import config
from src import logging_utils

from src.bot.commands import build_hi_handler
from src.bot.error_handlers import build_error_handler, build_notify_admin
from src.bot.message_handler import build_handle_addressed_message_handler
from src.bot.reaction_service import ReactionState
from src.bot.runtime import BotRuntime
from src.bot.schedule_handler import build_schedule_events_handler
from src.bot.summary_handler import build_view_summary_handler

_RUNTIME_STATE: dict[str, Optional[int]] = {"current_log_level": None}


def apply_log_level(settings: config.Settings) -> None:
    level = logging.DEBUG if settings.debug_mode else logging.INFO
    if _RUNTIME_STATE["current_log_level"] == level:
        return
    logging_utils.update_log_level(level)
    _RUNTIME_STATE["current_log_level"] = level


def build_application(
    runtime: BotRuntime, reaction_state: ReactionState
) -> Application:
    settings = runtime.get_settings()
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    app.add_error_handler(build_error_handler(runtime))
    apply_log_level(settings)

    app.add_handler(CommandHandler("hi", build_hi_handler(runtime)))
    app.add_handler(
        CommandHandler(["summary", "tldr"], build_view_summary_handler(runtime))
    )

    if settings.features["message_handling"]:
        app.add_handler(
            MessageHandler(
                (filters.TEXT & ~filters.COMMAND)
                | filters.VOICE
                | filters.PHOTO
                | filters.Document.IMAGE,
                build_handle_addressed_message_handler(runtime, reaction_state),
            )
        )
    if settings.features["schedule_events"]:
        notify_admin = build_notify_admin(runtime)
        app.add_handler(
            MessageHandler(
                filters.PHOTO,
                build_schedule_events_handler(runtime, notify_admin=notify_admin),
            )
        )
    return app
