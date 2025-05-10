import json
import logging
import os
import tempfile

import google.generativeai as genai
import tzlocal
import whisper
from httpx import get
from telegram import Update, Voice
from telegram.constants import ChatAction
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import src.utils
from src.calendar_provider import CalendarProvider
from src.config import (ADMIN_CHAT_ID, AI_PROVIDER, ALLOWED_CHAT_IDS,
                        CALENDAR_AI_PROVIDER, FEATURES, GEMINI_API_KEY,
                        PROMPT_PREFIX, TELEGRAM_BOT_TOKEN)
from src.gemini_provider import GeminiProvider
from src.message_store import (add_message, assemble_context, get_all_messages,
                               get_last_message)
from src.model_provider import ModelProvider
from src.whisper_provider import WhisperProvider

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


async def transcribe_voice_message(voice: Voice, context: ContextTypes.DEFAULT_TYPE) -> str:
    if voice is None:
        return ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio.name)
        temp_audio_path = temp_audio.name
    try:
        return transcribe_audio(temp_audio_path, get_model_provider())
    except Exception as e:
        logger.error(f"Transcription failed: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update) or not FEATURES['voice_transcription']:
        return
    logger.info(f"Received voice message from user {update.effective_user.id}")
    await update.effective_chat.send_action(action=ChatAction.TYPING)

    try:
        text = await transcribe_voice_message(update.message.voice, context)
        await update.message.reply_text(text)
        # Add transcribed voice message to message store
        sender = update.effective_user.first_name or str(
            update.effective_user.id)
        add_message(sender, text, is_bot=False)
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
    # if the message is audio, transcribe it
    is_transcribe_text = False
    if update.message.voice:
        text = await transcribe_voice_message(update.message.voice, context)
        is_transcribe_text = True
    else:
        text = update.message.text or ""
    sender = update.effective_user.first_name or str(update.effective_user.id)
    try:
        if update.message.reply_to_message:
            # bot never speaks
            reply_text = update.message.reply_to_message.text
            if reply_text:
                if get_last_message() is None:
                    add_message('Bot', reply_text, is_bot=True)
        add_message(sender, text, is_bot=False)
    except Exception as e:
        logger.error(f"Failed to store user message: {e}")
        await update.message.reply_text("Internal error: could not store your message.")
        return
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
    try:
        try:
            context_str = assemble_context(get_all_messages())
        except Exception as e:
            logger.error(f"Context assembly failed: {e}")
            await update.message.reply_text("Internal error: could not assemble context.")
            return
        prompt = f"{PROMPT_PREFIX}\n{context_str}\n---\n{sender}: {text}"
        try:
            response = gemini_provider.generate(prompt)
        except Exception as e:
            logger.error(f"AI provider failed: {e}")
            await update.message.reply_text("AI provider error. Please try again later.")
            return
        # if is_transcribe_text append a quote to the response
        if is_transcribe_text:
            response_with_transcribed_text = f">>{text}\n\n{response}"
        await update.message.reply_text(response_with_transcribed_text if is_transcribe_text else response)
        try:
            add_message('Bot', response, is_bot=True)
        except Exception as e:
            logger.error(f"Failed to store bot reply: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_addressed_message: {e}")
        await update.message.reply_text("Unexpected error occurred.")


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
            is_all_day = event_time is None
            if event_time is None:
                logger.warning("No time found in event data, treating as all-day event")
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
            local_tz = tzlocal.get_localzone()
            start_time = naive_datetime.replace(tzinfo=local_tz)
            
            event = calendar.create_event(
                title=event_data['title'],
                is_all_day=is_all_day,
                start_time=start_time,
                location=event_data.get('location'),
                description=event_data.get('description')
            )
            
            # Format the time for display in local timezone
            formatted_time = start_time.strftime("%H:%M")
            
            message_parts = [
                "Event created successfully!",
                f"Title: {event_data['title']}",
                f"Date: {event_data['date']}",
                f"Time: {formatted_time} ({local_tz})" if event_data['time'] else "All day event",
                f"Location: {event_data.get('location', 'Not specified')}"
            ]
            
            await update.message.reply_text("\n".join(message_parts))
            
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
        app.add_handler(MessageHandler(
            filters.VOICE & ~filters.REPLY, handle_voice))
    
        # Handle text and voice messages that mention the bot or are replies to the bot
    if FEATURES['message_handling']:
        app.add_handler(MessageHandler(
            filters.TEXT | filters.VOICE, handle_addressed_message))
    
    logger.info("Bot started with features: %s", FEATURES)
    app.run_polling()
