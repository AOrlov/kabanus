# main.py

import logging
import tempfile
import os
import whisper
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatAction
from config import TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

model = whisper.load_model("small")

def transcribe_audio(audio_path: str) -> str:
    result = model.transcribe(audio_path, language="ru")
    return result["text"].strip()

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"[CRITICAL ERROR]\n{message}")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am your speech-to-text bot.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received voice message from user {update.effective_user.id}")
    await update.message.chat.send_action(action=ChatAction.TYPING)
    voice = update.message.voice
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio.name)
        temp_audio_path = temp_audio.name
    try:
        text = transcribe_audio(temp_audio_path)
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        await update.message.reply_text("Извините, не удалось распознать речь.")
        # Notify admin for critical errors (e.g., unexpected exceptions)
        await notify_admin(context, f"Transcription failed for user {update.effective_user.id}: {e}")
    finally:
        os.remove(temp_audio_path)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Bot started.")
    app.run_polling()