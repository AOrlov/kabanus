import html
import json
import logging
import os
import tempfile
import traceback

import google.generativeai as genai
import tzlocal
from telegram import Update, Voice
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import src.utils
from src import config
from src.calendar_provider import CalendarProvider
from src.config import (ADMIN_CHAT_ID, ALLOWED_CHAT_IDS, DEBUG_MODE, FEATURES,
                        GEMINI_API_KEY, GEMINI_MODEL, PROMPT_PREFIX,
                        TELEGRAM_BOT_TOKEN)
from src.gemini_provider import GeminiProvider
from src.message_store import add_message, assemble_context, get_all_messages
from src.model_provider import ModelProvider

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG if DEBUG_MODE else logging.INFO
)

logger = logging.getLogger(__name__)
gemini_provider = GeminiProvider(GEMINI_API_KEY, GEMINI_MODEL)


def transcribe_audio(audio_path: str, provider: ModelProvider) -> str:
    return provider.transcribe(audio_path)


def is_allowed(update: Update) -> bool:
    if update.effective_chat is None or update.effective_user is None:
        return False
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    # Allow if chat or user is in the allowed list (if list is not empty)
    if ALLOWED_CHAT_IDS:
        if chat_id not in ALLOWED_CHAT_IDS and user_id not in ALLOWED_CHAT_IDS:
            logger.warning(f"Unauthorized access attempt by user {user_id} in chat {chat_id}")
            return False
        return True
    return False  # If no restriction set, allow all (for dev)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("Hello! I am your speech-to-text bot.")


async def transcribe_voice_message(voice: Voice, context: ContextTypes.DEFAULT_TYPE) -> str:
    if voice is None:
        return ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio.name)
        temp_audio_path = temp_audio.name
    return transcribe_audio(temp_audio_path, gemini_provider)


async def handle_addressed_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update) or not FEATURES['message_handling']:
        return
    # ignore if the update is not a message (e.g., a callback, edited message, etc.) or sent by non-user (bot)
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    # if the message is audio, transcribe it
    is_transcribe_text = False
    if update.message.voice:
        text = await transcribe_voice_message(update.message.voice, context)
        is_transcribe_text = True
    else:
        text = update.message.text or ""
    sender = update.effective_user.first_name or update.effective_user.name

    add_message(sender, text, is_bot=False)

    bot = await context.bot.get_me()
    bot_names_and_aliases = config.BOT_ALIASES
    if bot.username:
        bot_names_and_aliases.append(bot.username.lower())
    text_lower = text.lower()
    mentioned = any(alias in text_lower for alias in bot_names_and_aliases)
    is_reply_to_bot = mentioned or (
        update.message.reply_to_message and
        update.message.reply_to_message.from_user and
        update.message.reply_to_message.from_user.id == bot.id
    )
    if not is_reply_to_bot:
        if is_transcribe_text:
            # if the message is not addressed to the bot
            # just send the transcribed text
            await update.effective_chat.send_action(action=ChatAction.TYPING)
            await update.message.reply_text(text)
        return

    await update.effective_chat.send_action(action=ChatAction.TYPING)
    context_str = assemble_context(get_all_messages())
    prompt = f"{PROMPT_PREFIX}\n{context_str}\n---\n{sender}: {text}"
    if config.DEBUG_MODE:
        # trim the promt in the middle for logging purposes
        if len(prompt) > 1024:
            logger.debug(f"Generated prompt: {prompt[:512] + "\n...\n" + prompt[-512:]}")
        else:
            logger.debug(f"Generated prompt: {prompt}")
    response = gemini_provider.generate(prompt)

    # if is_transcribe_text append a quote to the response
    if is_transcribe_text:
        response_with_transcribed_text = f">>{text}\n\n{response}"
    await update.message.reply_text(response_with_transcribed_text if is_transcribe_text else response)
    add_message('Bot', response, is_bot=True)


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
            model = genai.GenerativeModel(GEMINI_MODEL)
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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    if not ADMIN_CHAT_ID:
        return
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        "An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )
    # Finally, send the message
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID, text=message, parse_mode=ParseMode.HTML
    )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    if FEATURES['commands']:
        if FEATURES['commands']['hi']:
            app.add_handler(CommandHandler("hi", start))

    if FEATURES['schedule_events']:
        app.add_handler(MessageHandler(filters.PHOTO, schedule_events))

        # Handle text messages that mention the bot or are replies to the bot
    if FEATURES['message_handling']:
        app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_addressed_message))

    logger.info("Bot started with features: %s", FEATURES)
    app.run_polling()
