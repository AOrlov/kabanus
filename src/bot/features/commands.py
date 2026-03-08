from typing import Any, Callable, Coroutine

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

CommandCallback = Callable[
    [Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]
]


def register(app: Application, *, hi_callback: CommandCallback) -> None:
    app.add_handler(CommandHandler("hi", hi_callback))
