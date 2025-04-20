# main.py

import logging
import tempfile
import os
import whisper
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatAction
from config import TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load Gemini API key from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Modular model interface
class ModelProvider:
    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError
    def generate(self, prompt: str) -> str:
        raise NotImplementedError

class WhisperProvider(ModelProvider):
    def __init__(self):
        self.model = whisper.load_model("small")
    def transcribe(self, audio_path: str) -> str:
        result = self.model.transcribe(audio_path, language="ru")
        return result["text"].strip()
    def generate(self, prompt: str) -> str:
        raise NotImplementedError("Whisper does not support text generation.")

class GeminiProvider(ModelProvider):
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-2.0-flash-lite")
    def transcribe(self, audio_path: str) -> str:
        # Gemini multimodal: send audio file for transcription
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        response = self.model.generate_content([
            {"mime_type": "audio/ogg", "data": audio_bytes},
            "Transcribe this audio to Russian text."
        ])
        return response.text.strip()
    def generate(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text.strip()

# Instantiate providers
whisper_provider = WhisperProvider()
gemini_provider = GeminiProvider() if GEMINI_API_KEY else None

def get_model_provider() -> ModelProvider:
    provider_name = os.getenv("PROVIDER_AI", "whisper").lower()
    if provider_name == "gemini" and gemini_provider:
        return gemini_provider
    return whisper_provider

def transcribe_audio(audio_path: str, provider: ModelProvider = whisper_provider) -> str:
    return provider.transcribe(audio_path)

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"[CRITICAL ERROR]\n{message}")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am your speech-to-text bot.")

async def gemini_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not gemini_provider:
        await update.message.reply_text("Gemini API key not configured.")
        return
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Usage: /gemini <your prompt>")
        return
    await update.message.chat.send_action(action=ChatAction.TYPING)
    try:
        response = gemini_provider.generate(prompt)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Gemini generation failed: {e}")
        await update.message.reply_text("Gemini generation failed.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received voice message from user {update.effective_user.id}")
    await update.message.chat.send_action(action=ChatAction.TYPING)
    voice = update.message.voice
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
        await notify_admin(context, f"Transcription failed for user {update.effective_user.id}: {e}")
    finally:
        os.remove(temp_audio_path)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    #app.add_handler(CommandHandler("start", start))
    #app.add_handler(CommandHandler("gemini", gemini_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Bot started.")
    app.run_polling()