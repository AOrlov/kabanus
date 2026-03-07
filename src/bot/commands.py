from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.access import is_allowed
from src.bot.runtime import BotRuntime


def build_hi_handler(runtime: BotRuntime):
    async def hi(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed(
            update,
            settings_getter=runtime.get_settings,
            logger=runtime.logger,
        ):
            return
        if update.message is None:
            return

        settings = runtime.get_settings()
        if not settings.features.get("commands", {}).get("hi"):
            return

        await update.message.reply_text("Hello! I am your speech-to-text bot.")
        await update.message.reply_text(
            f"Configured model provider: {settings.model_provider}"
        )
        if settings.model_provider == "openai":
            await update.message.reply_text(
                f"Configured OpenAI model: {settings.openai_model}"
            )
            return

        if settings.gemini_api_key and settings.gemini_models:
            preferred = settings.gemini_models[0].name

            def fmt_limit(value: Optional[int]) -> str:
                return "unlimited" if value is None else str(value)

            formatted = ", ".join(
                f"{model.name} (rpm={fmt_limit(model.rpm)}, rpd={fmt_limit(model.rpd)})"
                for model in settings.gemini_models
            )
            await update.message.reply_text(
                "Configured Gemini model priority: " + preferred
            )
            await update.message.reply_text("Configured Gemini models: " + formatted)

    return hi
