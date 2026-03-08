from typing import Any

from telegram.ext import Application

from src import config
from . import commands, events, message_flow, summary
from .events import build_events_handler
from .message_flow import MessageFlowComponents, build_message_flow
from .summary import build_summary_handler


def register_handlers(
    app: Application,
    *,
    runtime: Any,
    settings: config.Settings,
) -> None:
    commands.register(app, hi_callback=runtime.hi)
    summary.register(app, summary_callback=runtime.summary_handler.view_summary)
    message_flow.register(
        app,
        settings=settings,
        addressed_message_callback=runtime.message_handler.handle_addressed_message,
    )
    events.register(
        app,
        settings=settings,
        schedule_events_callback=runtime.events_handler.schedule_events,
    )


__all__ = [
    "MessageFlowComponents",
    "build_events_handler",
    "build_message_flow",
    "build_summary_handler",
    "commands",
    "events",
    "message_flow",
    "register_handlers",
    "summary",
]
