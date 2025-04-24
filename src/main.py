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
import src.utils
from telegram.constants import ChatAction
from src.config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_CHAT_ID,
    FEATURES,
    GEMINI_API_KEY,
    AI_PROVIDER,
    ALLOWED_CHAT_IDS,
    PROMPT_PREFIX,
    CALENDAR_AI_PROVIDER
)
from src.whisper_provider import WhisperProvider
from src.gemini_provider import GeminiProvider
from src.model_provider import ModelProvider
from src.calendar_provider import CalendarProvider
from datetime import datetime
import json
import tzlocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Gemini if enabled
if FEATURES['gemini_ai'] and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Instantiate providers
whisper_provider = WhisperProvider() if FEATURES['voice_transcription'] else None
gemini_provider = GeminiProvider() if FEATURES['gemini_ai'] and GEMINI_API_KEY else None

def get_model_provider() -> ModelProvider:
    if AI_PROVIDER == "gemini" and gemini_provider:
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
        if chat_id not in ALLOWED_CHAT_IDS and user_id not in ALLOWED_CHAT_IDS:
            logger.warning(f"Unauthorized access attempt by user {user_id} in chat {chat_id}")
            return False
    return True  # If no restriction set, allow all (for dev)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("Hello! I am your speech-to-text bot.")


async def gemini_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update) or not FEATURES['gemini_ai']:
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
    if not is_allowed(update) or not FEATURES['voice_transcription']:
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
    if not is_allowed(update) or not FEATURES['message_handling']:
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

    prompt_prefix= PROMPT_PREFIX
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


async def schedule_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update) or not FEATURES['schedule_events']:
        return
    
    if not update.message.photo:
        return
    
    await update.effective_chat.send_action(action=ChatAction.TYPING)
    
    try:
        # Get the largest photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        # Download the photo
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_photo:
            await file.download_to_drive(temp_photo.name)
            temp_photo_path = temp_photo.name
        
        try:
            # Read the image file
            with open(temp_photo_path, 'rb') as image_file:
                image_data = image_file.read()
            
            # Analyze the photo with Gemini
            model = genai.GenerativeModel(CALENDAR_AI_PROVIDER)
            response = model.generate_content([
                "Analyze this image and extract event information. " +
                "Provide a JSON response with the following fields: " +
                "title (string), date (YYYY-MM-DD), time (HH:MM), " +
                "location (string), description (string), " +
                "confidence (float between 0 and 1). " +
                "If any field is unclear, set it to null." +
                f"If there is no year, set it to current year ({datetime.now().year})",
                {"mime_type": "image/jpeg", "data": image_data}
            ])
            
            # Parse the response
            event_data = json.loads(src.utils.strip_markdown_to_json(response.text))
            
            # Log the event data for debugging
            logger.info(f"Event data from model: {event_data}")
            
            if event_data.get('confidence', 0) < 0.5:
                await update.message.reply_text(
                    "I'm not very confident about the event details, but I'll create it anyway."
                )
            
            # Create the event
            calendar = CalendarProvider()
            
            # Validate and handle date and time
            if not event_data.get('date'):
                raise ValueError("No date found in the event data")
                
            # Handle time with proper error checking
            event_time = event_data.get('time')
            if event_time is None:
                logger.warning("No time found in event data, using default time of 00:00")
                event_time = '00:00'
            elif not isinstance(event_time, str):
                logger.warning(f"Invalid time format: {event_time}, using default time of 00:00")
                event_time = '00:00'
            
            try:
                naive_datetime = datetime.strptime(
                    f"{event_data['date']} {event_time}",
                    "%Y-%m-%d %H:%M"
                )
            except ValueError as e:
                logger.error(f"Failed to parse datetime: {e}")
                raise ValueError(f"Invalid date or time format: {event_data['date']} {event_time}")
            
            # Get system's local timezone and set it for the datetime
            #TODO: get user's timezone
            local_tz = tzlocal.get_localzone()
            start_time = naive_datetime.replace(tzinfo=local_tz)
            
            event = calendar.create_event(
                title=event_data['title'],
                is_all_day=event_data['time'] is None,
                start_time=start_time,
                location=event_data.get('location'),
                description=event_data.get('description')
            )
            
            # Format the time for display in local timezone
            formatted_time = start_time.strftime("%H:%M")
            
            await update.message.reply_text(
                f"Event created successfully!\n"
                f"Title: {event_data['title']}\n"
                f"Date: {event_data['date']}\n"
                f"Time: {formatted_time}\n" if event_data['time'] else "All day event"
                f"Location: {event_data.get('location', 'Not specified')}"
            )
            
        except Exception as e:
            logger.error(f"Failed to process photo: {e}")
            await update.message.reply_text(
                "Sorry, I couldn't process the photo. Please make sure it contains clear event information."
            )
            await notify_admin(
                context,
                f"Photo processing failed for user {update.effective_user.id}: {e}"
            )
        finally:
            os.remove(temp_photo_path)
            
    except Exception as e:
        logger.error(f"Failed to handle photo message: {e}")
        await update.message.reply_text(
            "Sorry, something went wrong while processing your photo."
        )
        await notify_admin(
            context,
            f"Photo message handling failed for user {update.effective_user.id}: {e}"
        )


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    if FEATURES['commands']:
        if FEATURES['commands']['hi']:
            app.add_handler(CommandHandler("hi", start))
        if FEATURES['commands']['ai']:
            app.add_handler(CommandHandler("ai", gemini_command))
    
    if FEATURES['schedule_events']:
        app.add_handler(MessageHandler(filters.PHOTO, schedule_events))
    
    if FEATURES['voice_transcription']:
        app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    if FEATURES['message_handling']:
        app.add_handler(MessageHandler(filters.TEXT, handle_addressed_message))
    
    logger.info("Bot started with features: %s", FEATURES)
    app.run_polling()
