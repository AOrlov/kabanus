import logging
import tempfile
import os
import whisper
import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ChatAction
from .config import TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID

# Add allowed user/group IDs (comma-separated in env or hardcoded)
ALLOWED_CHAT_IDS = os.getenv("ALLOWED_CHAT_IDS", "").split(",") if os.getenv("ALLOWED_CHAT_IDS") else []

from .whisper_provider import WhisperProvider
from .gemini_provider import GeminiProvider
from .model_provider import ModelProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load Gemini API key from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Instantiate providers
whisper_provider = WhisperProvider()
gemini_provider = GeminiProvider() if GEMINI_API_KEY else None


def get_model_provider() -> ModelProvider:
    provider_name = os.getenv("PROVIDER_AI", "whisper").lower()
    if provider_name == "gemini" and gemini_provider:
        return gemini_provider
    return whisper_provider


def transcribe_audio(
    audio_path: str, provider: ModelProvider = whisper_provider
) -> str:
    return provider.transcribe(audio_path)


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID, text=f"[CRITICAL ERROR]\n{message}"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")


def is_allowed(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    # Allow if chat or user is in the allowed list (if list is not empty)
    if ALLOWED_CHAT_IDS:
        return chat_id in ALLOWED_CHAT_IDS or user_id in ALLOWED_CHAT_IDS
    return True  # If no restriction set, allow all (for dev)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("Hello! I am your speech-to-text bot.")


async def gemini_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not gemini_provider:
        await update.message.reply_text("Gemini API key not configured.")
        return
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Usage: /kaban <your prompt>")
        return
    await update.effective_chat.send_action(action=ChatAction.TYPING)
    try:
        response = gemini_provider.generate(prompt)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Gemini generation failed: {e}")
        await update.message.reply_text("Gemini generation failed.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    logger.info(f"Received voice message from user {update.effective_user.id}")
    await update.effective_chat.send_action(action=ChatAction.TYPING)
    voice = update.message.voice
    if voice is None:
        return
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio.name)
        temp_audio_path = temp_audio.name
    try:
        text = transcribe_audio(temp_audio_path, get_model_provider())
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        await update.message.reply_text("Извините, не удалось распознать речь.")
        await notify_admin(
            context, f"Transcription failed for user {update.effective_user.id}: {e}"
        )
    finally:
        os.remove(temp_audio_path)


async def handle_addressed_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    text = update.message.text or ""
    bot = await context.bot.get_me()
    bot_username = bot.username
    mentioned = f"@{bot_username}" in text
    is_reply_to_bot = (
        update.message.reply_to_message is not None and
        update.message.reply_to_message.from_user is not None and
        update.message.reply_to_message.from_user.id == bot.id
    )
    if not (mentioned or is_reply_to_bot):
        return

    await update.effective_chat.send_action(action=ChatAction.TYPING)
    if not gemini_provider:
        await update.message.reply_text("Gemini API key not configured.")
        return

    prompt_prefix= "Представь, что мы обсуждаем что-то из жизни обычных парней: " \
    "спорт, машины, музыку, какие-то местные движухи. " \
    "Отвечай на мои вопросы так, как будто ты свой в доску и шаришь в этих темах." \
    "Используй соответствующий сленг, уважай собеседника. " \
    "Говори по понятиям. Не душни. Отвечай по-русски. "
    try:
        if mentioned and update.message.reply_to_message:
            caption = update.message.reply_to_message.caption or ""
            original = update.message.reply_to_message.text or ""
            #remove bot's name from the text
            text = text.replace(f"@{bot_username}", "").strip()
            details = f"'{caption}'" if caption else "" + f"'{original}'" if original else ""
            prompt = (
                f"{prompt_prefix}Это контекст: {details}. "
                f"Вот мое новое сообщение: '{text}'."
            )
        elif is_reply_to_bot and update.message.reply_to_message and update.message.reply_to_message.text:
            original = update.message.reply_to_message.text or ""
            prompt = (
                f"{prompt_prefix}Вот твой предыдущий ответ: '{original}'. "
                f"Вот мое новое сообщение: '{text}'."
            )
        else:
            prompt = (
                f"{prompt_prefix}Ответь на это сообщение: {text}"
            )
        response = gemini_provider.generate(prompt)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Gemini generation failed for user {update.effective_user.id}: {e}")
        await update.message.reply_text("Gemini generation failed.")


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kaban", gemini_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT, handle_addressed_message))
    logger.info("Bot started.")
    app.run_polling()
