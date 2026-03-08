from typing import Any, Callable, Coroutine, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.bot.handlers.summary_handler import SummaryHandler

CommandCallback = Callable[
    [Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]
]


def build_summary_handler(
    *,
    is_allowed_fn: Callable[[Update], bool],
    storage_id_fn: Callable[[Update], Optional[str]],
    get_summary_view_text_fn: Callable[..., str],
) -> SummaryHandler:
    return SummaryHandler(
        is_allowed_fn=is_allowed_fn,
        storage_id_fn=storage_id_fn,
        get_summary_view_text_fn=get_summary_view_text_fn,
    )


def register(app: Application, *, summary_callback: CommandCallback) -> None:
    app.add_handler(CommandHandler(["summary", "tldr"], summary_callback))
