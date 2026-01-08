import html
import io
import json
import logging
import os
import tempfile
import traceback
import time
from datetime import datetime
from typing import Optional

import tzlocal
from telegram import Update, Voice
from telegram.constants import ChatAction, ParseMode, ReactionEmoji
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from src import config
from src.calendar_provider import CalendarProvider
from src.gemini_provider import GeminiProvider
from src.message_store import add_message, assemble_context, get_all_messages
from src.model_provider import ModelProvider

settings = config.get_settings()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG if settings.debug_mode else logging.INFO,
)

logger = logging.getLogger(__name__)
gemini_provider = GeminiProvider()
_CURRENT_LOG_LEVEL = None
_REACTION_DAY = None
_REACTION_COUNT = 0
_REACTION_LAST_TS = 0.0
_REACTION_ALLOWED_SET = {emoji.value for emoji in ReactionEmoji}
_REACTION_ALLOWED_LIST = sorted(_REACTION_ALLOWED_SET)
_MESSAGES_SINCE_LAST_REACTION = 0


def apply_log_level(settings: config.Settings) -> None:
    global _CURRENT_LOG_LEVEL
    level = logging.DEBUG if settings.debug_mode else logging.INFO
    if _CURRENT_LOG_LEVEL == level:
        return
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)
    _CURRENT_LOG_LEVEL = level


def transcribe_audio(audio_path: str, provider: ModelProvider) -> str:
    return provider.transcribe(audio_path)


def _reset_reaction_budget_if_needed(now: datetime) -> None:
    global _REACTION_DAY, _REACTION_COUNT
    today = now.date()
    if _REACTION_DAY != today:
        _REACTION_DAY = today
        _REACTION_COUNT = 0


def is_allowed(update: Update) -> bool:
    if update.effective_chat is None or update.effective_user is None:
        return False
    settings = config.get_settings()
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    # Allow if chat or user is in the allowed list (if list is not empty)
    if settings.allowed_chat_ids:
        if chat_id not in settings.allowed_chat_ids and user_id not in settings.allowed_chat_ids:
            logger.warning(f"Unauthorized access attempt by user {user_id} in chat {chat_id}")
            return False
        return True
    logger.info("No allowed_chat_ids configured, disallowing all users")
    return False


async def maybe_react(update: Update, text: str):
    logging.debug("maybe_react called")
    settings = config.get_settings()

    if update.message is None or not settings.reaction_enabled:
        return
    global _REACTION_COUNT, _REACTION_LAST_TS, _MESSAGES_SINCE_LAST_REACTION
    _MESSAGES_SINCE_LAST_REACTION += 1

    _reset_reaction_budget_if_needed(datetime.now())
    if settings.reaction_daily_budget <= 0 or _REACTION_COUNT >= settings.reaction_daily_budget:
        return
    if settings.reaction_cooldown_secs > 0:
        if time.monotonic() - _REACTION_LAST_TS < settings.reaction_cooldown_secs:
            return
    if _MESSAGES_SINCE_LAST_REACTION < settings.reaction_messages_threshold:
        return

    reaction = gemini_provider.choose_reaction(text, _REACTION_ALLOWED_LIST).strip()
    if not reaction:
        return
    if reaction not in _REACTION_ALLOWED_SET:
        logger.warning("Model returned unsupported reaction: %s", reaction)
        return

    try:
        await update.message.set_reaction(reaction)
    except Exception as exc:
        logger.warning("Failed to set reaction: %s", exc)
        return

    _REACTION_COUNT += 1
    _REACTION_LAST_TS = time.monotonic()
    _MESSAGES_SINCE_LAST_REACTION = 0


async def hi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if update.message is None:
        return
    settings = config.get_settings()
    if not settings.features.get("commands", {}).get("hi"):
        return
    await update.message.reply_text("Hello! I am your speech-to-text bot.")
    if settings.gemini_api_key and settings.gemini_models:
        preferred = settings.gemini_models[0].name
        def fmt_limit(value: Optional[int]) -> str:
            return "unlimited" if value is None else str(value)
        formatted = ", ".join(
            f"{model.name} (rpm={fmt_limit(model.rpm)}, rpd={fmt_limit(model.rpd)})"
            for model in settings.gemini_models
        )
        await update.message.reply_text("Configured Gemini model priority: " + preferred)
        await update.message.reply_text("Configured Gemini models: " + formatted)


async def transcribe_voice_message(voice: Voice, context: ContextTypes.DEFAULT_TYPE) -> str:
    if voice is None:
        return ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio.name)
        temp_audio_path = temp_audio.name
    return transcribe_audio(temp_audio_path, gemini_provider)


async def handle_addressed_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.debug("handle_addressed_message called")
    settings = config.get_settings()
    if not is_allowed(update) or not settings.features["message_handling"]:
        return
    # ignore if the update is not a message (e.g., a callback, edited message, etc.) or sent by non-user (bot)
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    if update.effective_user.is_bot:
        return

    # if the message is audio or image, transcribe/extract it
    is_transcribe_text = False
    is_image = False
    if update.message.voice:
        text = await transcribe_voice_message(update.message.voice, context)
        logger.debug(f"Received voice message {text} from {update.effective_user.id}")
        is_transcribe_text = True
    elif update.message.photo:
        # Process the largest photo in-memory
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        bio = io.BytesIO()
        await file.download_to_memory(bio)
        image_bytes = bio.getvalue()
        extracted = gemini_provider.image_to_text(image_bytes, mime_type="image/jpeg")
        # Include caption if present
        caption = update.message.caption or ""
        text = (caption + "\n" + extracted).strip() if caption else extracted
        logger.debug(f"Received photo -> text '{text}' from {update.effective_user.id}")
        is_transcribe_text = False
    elif update.message.document:
        # Only process if the document is an image; ignore others
        doc = update.message.document
        mime = (doc.mime_type or "").lower()
        name = (doc.file_name or "").lower()

        def guess_mime_from_name(n: str) -> str:
            if n.endswith((".jpg", ".jpeg")):
                return "image/jpeg"
            if n.endswith(".png"):
                return "image/png"
            if n.endswith(".webp"):
                return "image/webp"
            if n.endswith(".gif"):
                return "image/gif"
            if n.endswith((".bmp",)):
                return "image/bmp"
            if n.endswith((".tif", ".tiff")):
                return "image/tiff"
            return ""

        is_image_doc = mime.startswith("image/") or guess_mime_from_name(name) != ""
        eff_mime = mime if mime.startswith("image/") else guess_mime_from_name(name)

        # Basic size guard (e.g., 15 MB)
        if not is_image_doc:
            logger.debug("Ignoring non-image document message")
            return
        if doc.file_size is not None and doc.file_size > 15 * 1024 * 1024:
            logger.warning(f"Image document too large: {doc.file_size} bytes")
            return

        file = await context.bot.get_file(doc.file_id)
        bio = io.BytesIO()
        await file.download_to_memory(bio)
        image_bytes = bio.getvalue()
        extracted = gemini_provider.image_to_text(image_bytes, mime_type=eff_mime or "image/jpeg")
        caption = update.message.caption or ""
        text = (caption + "\n" + extracted).strip() if caption else extracted
        logger.debug(f"Received image document -> text '{text}' from {update.effective_user.id}")
        is_transcribe_text = False
    else:
        text = update.message.text or (update.message.caption or "")
        logger.debug(f"Received text message '{text}' from {update.effective_user.id}")
    sender = update.effective_user.first_name or update.effective_user.name
    if update.effective_chat.type == "private":
        storage_id = str(update.effective_user.id)
    else:
        storage_id = str(update.effective_chat.id)

    add_message(sender, text, is_bot=False, chat_id=storage_id)

    await maybe_react(update, text)

    bot = await context.bot.get_me()
    bot_names_and_aliases = list(settings.bot_aliases)
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
    context_str = assemble_context(get_all_messages(chat_id=storage_id))
    prompt = f"{context_str}\n---\n{sender}: {text}"
    if settings.debug_mode:
        # trim the promt in the middle for logging purposes
        if len(prompt) > 1024:
            logger.debug(f"Generated prompt: {prompt[:512] + "\n...\n" + prompt[-512:]}")
        else:
            logger.debug(f"Generated prompt: {prompt}")
    response = gemini_provider.generate(prompt)

    # if is_transcribe_text append a quote to the response
    if is_transcribe_text:
        response_with_transcribed_text = f">>{text}\n\n{response}"

    for chunk in chunk_string(response_with_transcribed_text if is_transcribe_text else response, 4000):
        await update.message.reply_text(chunk)
        add_message('Bot', chunk, chat_id=storage_id, is_bot=True)

def chunk_string(s: str, chunk_size: int) -> list[str]:
    if len(s) <= chunk_size:
        return [s]
    return [s[i:i + chunk_size] for i in range(0, len(s), chunk_size)]


async def schedule_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = config.get_settings()
    if not is_allowed(update) or not settings.features["schedule_events"]:
        return

    if update.message is None or update.effective_chat is None or update.effective_user is None:
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
            event_data = gemini_provider.parse_image_to_event(temp_photo_path)

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

    settings = config.get_settings()
    if not settings.admin_chat_id or context.error is None:
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
        chat_id=settings.admin_chat_id, text=message, parse_mode=ParseMode.HTML
    )


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
    """Send a notification message to the admin chat."""
    settings = config.get_settings()
    if not settings.admin_chat_id:
        return
    await context.bot.send_message(
        chat_id=settings.admin_chat_id,
        text=message,
        parse_mode=ParseMode.HTML
    )


async def refresh_settings_job(_: ContextTypes.DEFAULT_TYPE) -> None:
    settings = config.get_settings(force=True)
    apply_log_level(settings)


if __name__ == "__main__":
    settings = config.get_settings()
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_error_handler(error_handler)
    apply_log_level(settings)

    app.add_handler(CommandHandler("hi", hi))
    app.add_handler(MessageHandler(filters.PHOTO, schedule_events))
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.IMAGE,
            handle_addressed_message,
        )
    )

    '''
    app.job_queue.run_repeating(
        refresh_settings_job,
        interval=settings.settings_refresh_interval,
        first=settings.settings_refresh_interval,
    )
    '''
    
    logger.info("Bot started with features: %s", settings.features)
    app.run_polling()
