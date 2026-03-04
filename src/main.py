import asyncio
import html
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import traceback
import time
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

import tzlocal
from telegram import Update, Voice
from telegram.constants import ChatAction, ParseMode, ReactionEmoji
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src import config, logging_utils, utils
from src.calendar_provider import CalendarProvider
from src.message_store import (
    add_message,
    assemble_context,
    build_context,
    get_all_messages,
    get_message_by_telegram_message_id,
    get_summary_view_text,
)
from src.model_provider import ModelProvider
from src.provider_factory import build_provider
from src.telegram_drafts import send_message_draft

logging_utils.configure_bootstrap()
settings = config.get_settings()
logging_utils.configure_logging(settings)

logger = logging.getLogger(__name__)
model_provider = build_provider()
_CURRENT_LOG_LEVEL = None
_REACTION_DAY = None
_REACTION_COUNT = 0
_REACTION_LAST_TS = 0.0
_REACTION_ALLOWED_SET = {emoji.value for emoji in ReactionEmoji}
_REACTION_ALLOWED_LIST = sorted(_REACTION_ALLOWED_SET)
_MESSAGES_SINCE_LAST_REACTION = 0
_NON_TEXT_REPLY_PLACEHOLDER = "[non-text message]"
_IMAGE_MAX_BYTES = 15 * 1024 * 1024


def _log_context(update: Optional[Update]) -> dict:
    if update is None:
        return {}
    context = {}
    if update.effective_user is not None:
        context["user_id"] = update.effective_user.id
    if update.effective_chat is not None:
        context["chat_id"] = update.effective_chat.id
    if update.update_id is not None:
        context["update_id"] = update.update_id
    return context


def _storage_id(update: Update) -> Optional[str]:
    if update.effective_user is None or update.effective_chat is None:
        return None
    if update.effective_chat.type == "private":
        return str(update.effective_user.id)
    return str(update.effective_chat.id)


def apply_log_level(settings: config.Settings) -> None:
    global _CURRENT_LOG_LEVEL
    level = logging.DEBUG if settings.debug_mode else logging.INFO
    if _CURRENT_LOG_LEVEL == level:
        return
    logging_utils.update_log_level(level)
    _CURRENT_LOG_LEVEL = level


def transcribe_audio(audio_path: str, active_provider: ModelProvider) -> str:
    return active_provider.transcribe(audio_path)


def _entity_type_value(entity: Any) -> str:
    entity_type = getattr(entity, "type", "")
    if hasattr(entity_type, "value"):
        return str(entity_type.value).lower()
    return str(entity_type).lower()


def _iter_message_entity_blocks(message: Any) -> Iterable[Tuple[str, Iterable[Any]]]:
    text = getattr(message, "text", "") or ""
    if text:
        yield text, getattr(message, "entities", []) or []
    caption = getattr(message, "caption", "") or ""
    if caption:
        yield caption, getattr(message, "caption_entities", []) or []


def _normalized_aliases(aliases: Iterable[str]) -> set[str]:
    normalized = set()
    for alias in aliases:
        value = str(alias or "").strip().lower().lstrip("@")
        if value:
            normalized.add(value)
    return normalized


def _contains_alias_token(text: str, aliases: Iterable[str]) -> bool:
    text_lower = str(text or "").lower()
    if not text_lower:
        return False
    for alias in _normalized_aliases(aliases):
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text_lower):
            return True
    return False


def _is_bot_mentioned(
    message: Any,
    *,
    bot_username: str,
    bot_id: int,
    aliases: list[str],
    fallback_text: str = "",
) -> bool:
    normalized_aliases = _normalized_aliases(aliases)
    normalized_username = str(bot_username or "").strip().lower().lstrip("@")
    if normalized_username:
        normalized_aliases.add(normalized_username)

    for source_text, entities in _iter_message_entity_blocks(message):
        for entity in entities:
            entity_type = _entity_type_value(entity)
            if entity_type == "mention":
                try:
                    offset = int(getattr(entity, "offset", 0))
                    length = int(getattr(entity, "length", 0))
                except (TypeError, ValueError):
                    continue
                if offset < 0 or length <= 0 or offset + length > len(source_text):
                    continue
                mention = source_text[offset : offset + length].strip().lower().lstrip("@")
                if mention and mention in normalized_aliases:
                    return True
            elif entity_type == "text_mention":
                user = getattr(entity, "user", None)
                user_id = getattr(user, "id", None)
                if user_id == bot_id:
                    return True

    authored_text = "\n".join([text for text, _ in _iter_message_entity_blocks(message)])
    if _contains_alias_token(authored_text, normalized_aliases):
        return True
    if fallback_text and _contains_alias_token(fallback_text, normalized_aliases):
        return True
    return False


def _should_respond_to_message(
    *,
    mentioned_bot: bool,
    replied_to_bot: bool,
    replied_to_other_user: bool,
) -> bool:
    if replied_to_other_user:
        return mentioned_bot
    return mentioned_bot or replied_to_bot


def _guess_mime_from_name(name: str) -> str:
    lowered = str(name or "").lower()
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".bmp"):
        return "image/bmp"
    if lowered.endswith((".tif", ".tiff")):
        return "image/tiff"
    return ""


def _is_image_document(document: Any) -> Tuple[bool, str]:
    mime = (getattr(document, "mime_type", "") or "").lower()
    filename = (getattr(document, "file_name", "") or "").lower()
    guessed_mime = _guess_mime_from_name(filename)
    is_image = mime.startswith("image/") or bool(guessed_mime)
    effective_mime = mime if mime.startswith("image/") else guessed_mime
    return is_image, effective_mime


def _combine_caption_and_extracted(caption: str, extracted: str) -> str:
    caption_clean = (caption or "").strip()
    extracted_clean = (extracted or "").strip()
    if caption_clean and extracted_clean:
        return f"{caption_clean}\n{extracted_clean}".strip()
    return (caption_clean or extracted_clean).strip()


async def _extract_text_from_photo_message(
    message: Any, context: ContextTypes.DEFAULT_TYPE
) -> str:
    if not getattr(message, "photo", None):
        return ""
    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    bio = io.BytesIO()
    await file.download_to_memory(bio)
    image_bytes = bio.getvalue()
    extracted = model_provider.image_to_text(image_bytes, mime_type="image/jpeg")
    return _combine_caption_and_extracted(getattr(message, "caption", "") or "", extracted)


async def _extract_text_from_image_document(
    message: Any, context: ContextTypes.DEFAULT_TYPE
) -> Optional[str]:
    document = getattr(message, "document", None)
    if document is None:
        return None
    is_image_document, effective_mime = _is_image_document(document)
    if not is_image_document:
        return None

    file = await context.bot.get_file(document.file_id)
    bio = io.BytesIO()
    await file.download_to_memory(bio)
    image_bytes = bio.getvalue()
    extracted = model_provider.image_to_text(
        image_bytes,
        mime_type=effective_mime or "image/jpeg",
    )
    return _combine_caption_and_extracted(getattr(message, "caption", "") or "", extracted)


def _message_sender_name(message: Any) -> str:
    from_user = getattr(message, "from_user", None)
    if from_user is None:
        return "Unknown"
    sender = getattr(from_user, "first_name", None) or getattr(from_user, "name", None)
    if sender:
        return str(sender)
    user_id = getattr(from_user, "id", None)
    if user_id is None:
        return "Unknown"
    return str(user_id)


async def _extract_reply_target_text(
    reply_message: Any,
    context: ContextTypes.DEFAULT_TYPE,
) -> Tuple[str, str]:
    reply_text = (getattr(reply_message, "text", "") or "").strip()
    if reply_text:
        return reply_text, "message_text"

    if getattr(reply_message, "photo", None):
        try:
            extracted = await _extract_text_from_photo_message(reply_message, context)
            extracted_text = extracted.strip()
            if extracted_text:
                return extracted_text, "fallback_ocr"
        except Exception as exc:
            logger.warning("Failed to OCR replied photo", extra={"error": str(exc)})
        caption = (getattr(reply_message, "caption", "") or "").strip()
        if caption:
            return caption, "message_caption"
        return _NON_TEXT_REPLY_PLACEHOLDER, "non_text"

    if getattr(reply_message, "document", None):
        document = reply_message.document
        if document.file_size is not None and document.file_size > _IMAGE_MAX_BYTES:
            caption = (getattr(reply_message, "caption", "") or "").strip()
            if caption:
                return caption, "message_caption"
            return _NON_TEXT_REPLY_PLACEHOLDER, "image_too_large"
        try:
            extracted = await _extract_text_from_image_document(reply_message, context)
            if extracted is not None:
                extracted_text = extracted.strip()
                if extracted_text:
                    return extracted_text, "fallback_ocr"
        except Exception as exc:
            logger.warning("Failed to OCR replied image document", extra={"error": str(exc)})
        caption = (getattr(reply_message, "caption", "") or "").strip()
        if caption:
            return caption, "message_caption"
        return _NON_TEXT_REPLY_PLACEHOLDER, "non_text"

    reply_caption = (getattr(reply_message, "caption", "") or "").strip()
    if reply_caption:
        return reply_caption, "message_caption"
    return _NON_TEXT_REPLY_PLACEHOLDER, "non_text"


async def _resolve_reply_target_context(
    message: Any,
    *,
    chat_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[Dict[str, str]]:
    reply_message = getattr(message, "reply_to_message", None)
    if reply_message is None:
        return None
    sender = _message_sender_name(reply_message)
    reply_message_id = getattr(reply_message, "message_id", None)
    if reply_message_id is not None:
        stored_message = get_message_by_telegram_message_id(
            chat_id=chat_id,
            telegram_message_id=reply_message_id,
        )
        if stored_message is not None:
            stored_text = str(stored_message.get("text", "")).strip()
            if stored_text:
                return {
                    "sender": str(stored_message.get("sender", sender) or sender),
                    "text": stored_text,
                    "source": "history_lookup",
                }
    resolved_text, source = await _extract_reply_target_text(reply_message, context)
    return {
        "sender": sender,
        "text": resolved_text or _NON_TEXT_REPLY_PLACEHOLDER,
        "source": source,
    }


def _build_prompt(
    *,
    context_text: str,
    sender: str,
    latest_text: str,
    reply_target_context: Optional[Dict[str, str]] = None,
) -> str:
    if reply_target_context is None:
        return f"{context_text}\n---\n{sender}: {latest_text}"
    target_sender = reply_target_context.get("sender", "Unknown")
    target_text = reply_target_context.get("text", _NON_TEXT_REPLY_PLACEHOLDER)
    return (
        f"{context_text}\n---\n"
        "Target message for clarification:\n"
        f"{target_sender}: {target_text}\n"
        "---\n"
        f"{sender}: {latest_text}"
    )


def _reset_reaction_budget_if_needed(now: datetime) -> None:
    global _REACTION_DAY, _REACTION_COUNT
    today = now.date()
    if _REACTION_DAY != today:
        _REACTION_DAY = today
        _REACTION_COUNT = 0


def _build_reaction_context(chat_id: Optional[str], settings: config.Settings) -> str:
    if (
        not chat_id
        or settings.reaction_context_turns <= 0
        or settings.reaction_context_token_limit <= 0
    ):
        return ""
    messages = get_all_messages(chat_id)
    if not messages:
        return ""
    recent_messages = messages[-settings.reaction_context_turns :]
    return assemble_context(
        recent_messages,
        token_limit=settings.reaction_context_token_limit,
    )


def is_allowed(update: Update) -> bool:
    if update.effective_chat is None or update.effective_user is None:
        return False
    settings = config.get_settings()
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    # Allow if chat or user is in the allowed list (if list is not empty)
    if settings.allowed_chat_ids:
        if (
            chat_id not in settings.allowed_chat_ids
            and user_id not in settings.allowed_chat_ids
        ):
            logger.warning(
                "Unauthorized access attempt",
                extra={"user_id": user_id, "chat_id": chat_id},
            )
            return False
        return True
    logger.info(
        "No allowed_chat_ids configured, disallowing all users",
        extra=_log_context(update),
    )
    return False


async def maybe_react(update: Update, text: str):
    logger.debug("maybe_react called", extra=_log_context(update))
    settings = config.get_settings()

    if update.message is None or not settings.reaction_enabled:
        return
    global _REACTION_COUNT, _REACTION_LAST_TS, _MESSAGES_SINCE_LAST_REACTION
    _MESSAGES_SINCE_LAST_REACTION += 1

    _reset_reaction_budget_if_needed(datetime.now())
    if (
        settings.reaction_daily_budget <= 0
        or _REACTION_COUNT >= settings.reaction_daily_budget
    ):
        return
    if settings.reaction_cooldown_secs > 0:
        if time.monotonic() - _REACTION_LAST_TS < settings.reaction_cooldown_secs:
            return
    if _MESSAGES_SINCE_LAST_REACTION < settings.reaction_messages_threshold:
        return

    storage_id = _storage_id(update)
    reaction_context = _build_reaction_context(storage_id, settings)
    if settings.debug_mode:
        logger.debug(
            "Built reaction context",
            extra={
                **_log_context(update),
                "has_context": bool(reaction_context),
                "context_chars": len(reaction_context),
                "context_preview": reaction_context[:256],
            },
        )

    reaction = model_provider.choose_reaction(
        text,
        _REACTION_ALLOWED_LIST,
        context_text=reaction_context,
    ).strip()
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
    await update.message.reply_text(
        f"Configured model provider: {settings.model_provider}"
    )
    if settings.model_provider == "openai":
        await update.message.reply_text(
            f"Configured OpenAI model: {settings.openai_model}"
        )
    elif settings.gemini_api_key and settings.gemini_models:
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


def _parse_summary_command_args(
    args: list[str],
) -> Tuple[Optional[Dict], Optional[str]]:
    parsed: Dict = {"head": 0, "tail": 0, "index": None, "grep": "", "show_help": False}
    if not args:
        parsed["tail"] = 1
        return parsed, None

    lowered = [arg.lower() for arg in args]
    if len(args) == 1 and lowered[0] in {"help", "--help", "-help", "?"}:
        parsed["show_help"] = True
        return parsed, None

    def parse_int(
        raw: str, name: str, allow_zero: bool = False
    ) -> Tuple[Optional[int], Optional[str]]:
        try:
            value = int(raw)
        except ValueError:
            return None, f"Invalid integer for {name}: {raw}"
        min_allowed = 0 if allow_zero else 1
        if value < min_allowed:
            return None, f"{name} must be >= {min_allowed}"
        return value, None

    # Friendly forms:
    # /summary 5
    # /summary index 10
    # /summary keyword phrase
    if args[0].lstrip("-").isdigit():
        value, err = parse_int(args[0], "tail")
        if err:
            return None, err
        parsed["tail"] = value
        if len(args) > 1:
            parsed["grep"] = " ".join(args[1:]).strip()
        return parsed, None
    if lowered[0] in {"head", "index"}:
        if len(args) < 2:
            return None, f"Missing value for {args[0]}"
        value, err = parse_int(args[1], lowered[0], allow_zero=(lowered[0] == "index"))
        if err:
            return None, err
        parsed[lowered[0]] = value
        if len(args) > 2:
            parsed["grep"] = " ".join(args[2:]).strip()
        return parsed, None
    if not args[0].startswith("--"):
        parsed["grep"] = " ".join(args).strip()
        parsed["head"] = 5
        return parsed, None

    # Advanced flag form kept for compatibility.
    flags = {"--head", "--index", "--grep"}
    idx = 0
    while idx < len(args):
        token = args[idx]
        if token not in flags:
            return None, f"Unknown argument: {token}"
        if token in {"--head", "--index"}:
            if idx + 1 >= len(args):
                return None, f"Missing value for {token}"
            key = token[2:]
            value, err = parse_int(args[idx + 1], key, allow_zero=(key == "index"))
            if err:
                return None, err
            parsed[key] = value
            idx += 2
            continue
        if idx + 1 >= len(args):
            return None, "Missing value for --grep"
        grep_tokens = []
        idx += 1
        while idx < len(args):
            if args[idx].startswith("--") and args[idx] in flags:
                break
            grep_tokens.append(args[idx])
            idx += 1
        if not grep_tokens:
            return None, "Missing value for --grep"
        parsed["grep"] = " ".join(grep_tokens)

    # When only grep is set, show first matches by default.
    if parsed["head"] == 0 and parsed["tail"] == 0 and parsed["index"] is None:
        parsed["head"] = 5
    return parsed, None


def _summary_command_usage() -> str:
    return (
        "Summary command examples:\n"
        "/summary               -> last chunk\n"
        "/summary 5             -> last 5 chunks\n"
        "/summary index 12      -> chunk #12\n"
        "/summary budget api    -> search text in summary/facts/decisions/open_items\n"
        "/summary --head 10 --grep budget\n"
        "Alias: /tldr"
    )


def _command_args_from_message_text(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return []
    payload = parts[1].strip()
    if not payload:
        return []
    return [token for token in re.split(r"\s+", payload) if token]


async def view_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if (
        update.message is None
        or update.effective_chat is None
        or update.effective_user is None
    ):
        return

    args = _command_args_from_message_text(update.message.text or "")
    if not args:
        args = context.args or []
    parsed, err = _parse_summary_command_args(args)
    if err:
        await update.message.reply_text(f"{err}\n\n{_summary_command_usage()}")
        return
    if parsed.get("show_help"):
        await update.message.reply_text(_summary_command_usage())
        return

    storage_id = _storage_id(update)
    if storage_id is None:
        return

    try:
        output = get_summary_view_text(
            chat_id=storage_id,
            head=int(parsed["head"]),
            tail=int(parsed["tail"]),
            index=parsed["index"],
            grep=str(parsed["grep"]),
        )
    except RuntimeError as exc:
        await update.message.reply_text(f"Failed to read summary: {exc}")
        return

    for chunk in chunk_string(output, 4000):
        if chunk.strip():
            await update.message.reply_text(chunk)


async def transcribe_voice_message(
    voice: Voice, context: ContextTypes.DEFAULT_TYPE
) -> str:
    if voice is None:
        return ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
        temp_audio_path = temp_audio.name
    try:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio_path)
        return transcribe_audio(temp_audio_path, model_provider)
    finally:
        try:
            os.remove(temp_audio_path)
        except OSError:
            logger.debug(
                "Failed to remove temporary voice file", extra={"path": temp_audio_path}
            )


async def handle_addressed_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug("handle_addressed_message called", extra=_log_context(update))
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
    authored_text = (update.message.text or (update.message.caption or "")).strip()
    if update.message.voice:
        text = await transcribe_voice_message(update.message.voice, context)
        logger.debug(
            "Received voice message",
            extra={**_log_context(update), "message_preview": text[:256]},
        )
        is_transcribe_text = True
    elif update.message.photo:
        text = await _extract_text_from_photo_message(update.message, context)
        logger.debug(
            "Received photo message",
            extra={**_log_context(update), "message_preview": text[:256]},
        )
    elif update.message.document:
        is_image_doc, _ = _is_image_document(update.message.document)
        if not is_image_doc:
            logger.debug(
                "Ignoring non-image document message", extra=_log_context(update)
            )
            return
        if (
            update.message.document.file_size is not None
            and update.message.document.file_size > _IMAGE_MAX_BYTES
        ):
            logger.warning(
                "Image document too large",
                extra={
                    **_log_context(update),
                    "file_size": update.message.document.file_size,
                },
            )
            return

        text_from_document = await _extract_text_from_image_document(
            update.message, context
        )
        if text_from_document is None:
            logger.debug(
                "Ignoring non-image document message", extra=_log_context(update)
            )
            return

        text = text_from_document
        logger.debug(
            "Received image document",
            extra={**_log_context(update), "message_preview": text[:256]},
        )
    else:
        text = authored_text
        logger.debug(
            "Received text message",
            extra={**_log_context(update), "message_preview": text[:256]},
        )
    sender = update.effective_user.first_name or update.effective_user.name
    storage_id = _storage_id(update)
    if storage_id is None:
        return

    reply_to_telegram_message_id = None
    if update.message.reply_to_message is not None:
        reply_to_telegram_message_id = update.message.reply_to_message.message_id

    add_message(
        sender,
        text,
        is_bot=False,
        chat_id=storage_id,
        telegram_message_id=update.message.message_id,
        reply_to_telegram_message_id=reply_to_telegram_message_id,
    )

    await maybe_react(update, text)

    bot = await context.bot.get_me()
    mentioned_bot = _is_bot_mentioned(
        update.message,
        bot_username=bot.username or "",
        bot_id=bot.id,
        aliases=settings.bot_aliases,
        fallback_text=text if is_transcribe_text else "",
    )

    replied_user_id = None
    if (
        update.message.reply_to_message is not None
        and update.message.reply_to_message.from_user is not None
    ):
        replied_user_id = update.message.reply_to_message.from_user.id
    replied_to_bot = replied_user_id == bot.id
    replied_to_other_user = (
        update.message.reply_to_message is not None
        and replied_user_id is not None
        and replied_user_id != bot.id
    )
    should_respond = _should_respond_to_message(
        mentioned_bot=mentioned_bot,
        replied_to_bot=replied_to_bot,
        replied_to_other_user=replied_to_other_user,
    )
    logger.debug(
        "Addressing decision",
        extra={
            **_log_context(update),
            "mentioned_bot": mentioned_bot,
            "replied_to_bot": replied_to_bot,
            "replied_to_other_user": replied_to_other_user,
            "triggered": should_respond,
        },
    )

    if not should_respond:
        if is_transcribe_text:
            # if the message is not addressed to the bot
            # just send the transcribed text
            await update.effective_chat.send_action(action=ChatAction.TYPING)
            await update.message.reply_text(text)
        return

    reply_target_context = None
    if replied_to_other_user and mentioned_bot:
        reply_target_context = await _resolve_reply_target_context(
            update.message,
            chat_id=storage_id,
            context=context,
        )
        if settings.debug_mode and reply_target_context is not None:
            logger.debug(
                "Resolved reply target context",
                extra={
                    **_log_context(update),
                    "source": reply_target_context.get("source", ""),
                    "reply_target_preview": reply_target_context.get("text", "")[:256],
                },
            )

    await update.effective_chat.send_action(action=ChatAction.TYPING)
    context_str = build_context(
        chat_id=storage_id,
        latest_user_text=text,
        summarize_fn=model_provider.generate_low_cost,
    )
    prompt = _build_prompt(
        context_text=context_str,
        sender=sender,
        latest_text=text,
        reply_target_context=reply_target_context,
    )
    if settings.debug_mode:
        # trim the promt in the middle for logging purposes
        if len(prompt) > 1024:
            logger.debug(
                "Generated prompt (trimmed)",
                extra={
                    **_log_context(update),
                    "prompt": prompt[:512] + "\n...\n" + prompt[-512:],
                },
            )
        else:
            logger.debug(
                "Generated prompt",
                extra={**_log_context(update), "prompt": prompt},
            )
    response = ""
    max_empty_retries = 3
    for attempt in range(1, max_empty_retries + 1):
        if _should_use_message_drafts(update, settings):
            response = await _generate_response_with_drafts(update, prompt, settings)
        else:
            response = (model_provider.generate(prompt) or "").strip()
        if response:
            break
        logger.warning(
            "Model returned empty response",
            extra={
                **_log_context(update),
                "attempt": attempt,
                "max_attempts": max_empty_retries,
            },
        )
        if attempt < max_empty_retries:
            await asyncio.sleep(0.5)

    if not response:
        logger.warning(
            "Ignoring message due to empty model response after retries",
            extra=_log_context(update),
        )
        return

    outgoing_text = response
    if is_transcribe_text:
        outgoing_text = f">>{text}\n\n{response}".strip()

    await send_ai_response(update, outgoing_text, storage_id)


def chunk_string(s: str, chunk_size: int) -> list[str]:
    if not s:
        return []
    if len(s) <= chunk_size:
        return [s]
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]


def _should_use_message_drafts(update: Update, settings: config.Settings) -> bool:
    if not settings.telegram_use_message_drafts:
        return False
    if settings.model_provider != "openai":
        return False
    if update.effective_chat is None:
        return False
    return update.effective_chat.type == "private"


def _build_response_draft_id(update: Update) -> int:
    chat_id = getattr(update.effective_chat, "id", "unknown")
    message_id = getattr(update.message, "message_id", int(time.time() * 1000))
    raw = f"{chat_id}:{message_id}".encode("utf-8")
    value = int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")
    # draft_id must be a non-zero integer.
    return (value % ((1 << 63) - 1)) + 1


async def _generate_response_with_drafts(
    update: Update,
    prompt: str,
    settings: config.Settings,
) -> str:
    chat = update.effective_chat
    if chat is None:
        return (model_provider.generate(prompt) or "").strip()

    draft_id = _build_response_draft_id(update)
    last_sent_draft = ""
    last_sent_ts = 0.0
    stream_text = ""
    draft_updates_enabled = True
    pending_send_task: Optional[asyncio.Task] = None
    pending_send_text = ""
    stream_error: Optional[Exception] = None

    async def _finalize_pending_send(force: bool = False) -> None:
        nonlocal pending_send_task, draft_updates_enabled, pending_send_text
        if pending_send_task is None:
            return
        if not force and not pending_send_task.done():
            # Let pending draft update task start/advance before the next stream poll.
            await asyncio.sleep(0)
            return
        try:
            await pending_send_task
        except Exception as exc:
            draft_updates_enabled = False
            logger.warning(
                "Failed to update Telegram message draft; continuing without drafts",
                extra={
                    **_log_context(update),
                    "error": str(exc),
                    "draft_id": draft_id,
                    "draft_preview": pending_send_text[:128],
                },
            )
        finally:
            pending_send_task = None
            pending_send_text = ""

    def _schedule_send(draft_text: str) -> None:
        nonlocal pending_send_task, pending_send_text, last_sent_draft, last_sent_ts
        pending_send_text = draft_text
        pending_send_task = asyncio.create_task(
            send_message_draft(
                bot_token=settings.telegram_bot_token,
                chat_id=chat.id,
                draft_id=draft_id,
                text=draft_text,
            )
        )
        last_sent_draft = draft_text
        last_sent_ts = time.monotonic()

    try:
        for snapshot in model_provider.generate_stream(prompt):
            stream_text = str(snapshot or "")
            draft_text = stream_text[:4096]
            if not draft_text.strip():
                continue

            await _finalize_pending_send()
            if not draft_updates_enabled:
                continue
            if pending_send_task is not None:
                continue
            if draft_text == last_sent_draft:
                continue
            now = time.monotonic()
            if last_sent_ts and (now - last_sent_ts) < settings.telegram_draft_update_interval_secs:
                continue
            _schedule_send(draft_text)
            await asyncio.sleep(0)
    except Exception as exc:
        stream_error = exc
        logger.warning(
            "Model stream failed; using best available response",
            extra={
                **_log_context(update),
                "error": str(exc),
                "has_partial_output": bool(stream_text.strip()),
            },
        )
    finally:
        await _finalize_pending_send(force=True)

    final_text = stream_text.strip()
    if stream_error is not None and not final_text:
        try:
            final_text = (model_provider.generate(prompt) or "").strip()
        except Exception as fallback_exc:
            logger.warning(
                "Fallback generation failed after stream error",
                extra={
                    **_log_context(update),
                    "stream_error": str(stream_error),
                    "fallback_error": str(fallback_exc),
                },
            )
            return ""

    final_draft_text = (stream_text if stream_text else final_text)[:4096]
    if final_draft_text.strip() and draft_updates_enabled and final_draft_text != last_sent_draft:
        _schedule_send(final_draft_text)
        await _finalize_pending_send(force=True)
    return final_text


async def send_ai_response(update: Update, outgoing_text: str, storage_id: str) -> None:
    message = update.message
    if message is None:
        return

    settings = config.get_settings()
    if not settings.telegram_format_ai_replies:
        for chunk in [
            chunk for chunk in chunk_string(outgoing_text, 4000) if chunk.strip()
        ]:
            await message.reply_text(chunk)
            add_message("Bot", chunk, chat_id=storage_id, is_bot=True)
        return

    html_chunks = [
        chunk
        for chunk in utils.build_telegram_html_chunks(outgoing_text, 4000)
        if chunk.strip()
    ]
    for chunk in html_chunks:
        plain_chunk = utils.telegram_html_to_plain_text(chunk).strip()
        try:
            await message.reply_text(chunk, parse_mode=ParseMode.HTML)
            if plain_chunk:
                add_message("Bot", plain_chunk, chat_id=storage_id, is_bot=True)
        except BadRequest as exc:
            logger.warning(
                "Failed to send formatted response chunk, falling back to plain text",
                extra={
                    **_log_context(update),
                    "error": str(exc),
                    "chunk_preview": chunk[:256],
                },
            )
            fallback_chunk = plain_chunk or chunk
            await message.reply_text(fallback_chunk)
            add_message("Bot", fallback_chunk, chat_id=storage_id, is_bot=True)


async def schedule_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = config.get_settings()
    if not is_allowed(update) or not settings.features["schedule_events"]:
        return

    if (
        update.message is None
        or update.effective_chat is None
        or update.effective_user is None
    ):
        return

    if not update.message.photo:
        return

    await update.effective_chat.send_action(action=ChatAction.TYPING)

    temp_photo_path: Optional[str] = None
    try:
        # Get the largest photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        # Download the photo
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_photo:
            temp_photo_path = temp_photo.name
        await file.download_to_drive(temp_photo_path)

        try:
            event_data = model_provider.parse_image_to_event(temp_photo_path)

            if event_data.get("confidence", 0) < 0.5:
                await update.message.reply_text(
                    "I'm not very confident about the event details, but I'll create it anyway."
                )

            # Create the event
            calendar = CalendarProvider()

            # Validate and handle date and time
            if not event_data.get("date"):
                raise ValueError("No date found in the event data")

            # Handle time with proper error checking
            event_time = event_data.get("time")
            is_all_day = event_time is None
            if event_time is None:
                logger.warning(
                    "No time found in event data, treating as all-day event",
                    extra=_log_context(update),
                )
                event_time = "00:00"
            elif not isinstance(event_time, str):
                logger.warning(
                    "Invalid time format, using default time of 00:00",
                    extra={**_log_context(update), "event_time": event_time},
                )
                event_time = "00:00"

            try:
                naive_datetime = datetime.strptime(
                    f"{event_data['date']} {event_time}", "%Y-%m-%d %H:%M"
                )
            except ValueError as e:
                logger.error(
                    "Failed to parse datetime",
                    extra={**_log_context(update), "error": str(e)},
                )
                raise ValueError(
                    f"Invalid date or time format: {event_data['date']} {event_time}"
                )

            # Get system's local timezone and set it for the datetime
            local_tz = tzlocal.get_localzone()
            start_time = naive_datetime.replace(tzinfo=local_tz)

            event = calendar.create_event(
                title=event_data["title"],
                is_all_day=is_all_day,
                start_time=start_time,
                location=event_data.get("location"),
                description=event_data.get("description"),
            )

            # Format the time for display in local timezone
            formatted_time = start_time.strftime("%H:%M")

            message_parts = [
                "Event created successfully!",
                f"Title: {event_data['title']}",
                f"Date: {event_data['date']}",
                (
                    f"Time: {formatted_time} ({local_tz})"
                    if event_data["time"]
                    else "All day event"
                ),
                f"Location: {event_data.get('location', 'Not specified')}",
            ]

            await update.message.reply_text("\n".join(message_parts))

        except Exception as e:
            logger.error(
                "Failed to process photo",
                extra={**_log_context(update), "error": str(e)},
            )
            await update.message.reply_text(
                "Sorry, I couldn't process the photo. Please make sure it contains clear event information."
            )
            await notify_admin(
                context,
                f"Photo processing failed for user {update.effective_user.id}: {e}",
            )

    except Exception as e:
        logger.error(
            "Failed to handle photo message",
            extra={**_log_context(update), "error": str(e)},
        )
        await update.message.reply_text(
            "Sorry, something went wrong while processing your photo."
        )
        await notify_admin(
            context,
            f"Photo message handling failed for user {update.effective_user.id}: {e}",
        )
    finally:
        if temp_photo_path:
            try:
                os.remove(temp_photo_path)
            except OSError:
                logger.debug(
                    "Failed to remove temporary photo file",
                    extra={"path": temp_photo_path, **_log_context(update)},
                )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(
        "Exception while handling an update",
        exc_info=context.error,
        extra=_log_context(update if isinstance(update, Update) else None),
    )

    settings = config.get_settings()
    if not settings.admin_chat_id or context.error is None:
        return

    tb_list = traceback.format_exception(
        None, context.error, context.error.__traceback__
    )
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
    max_len = 3500
    if len(message) <= max_len:
        await context.bot.send_message(
            chat_id=settings.admin_chat_id, text=message, parse_mode=ParseMode.HTML
        )
        return
    head = message[: max_len - 64]
    tail = message[-512:]
    compact = f"{head}\n\n<pre>...truncated...</pre>\n\n{tail}"
    await context.bot.send_message(
        chat_id=settings.admin_chat_id, text=compact, parse_mode=ParseMode.HTML
    )


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
    """Send a notification message to the admin chat."""
    settings = config.get_settings()
    if not settings.admin_chat_id:
        return
    await context.bot.send_message(
        chat_id=settings.admin_chat_id, text=message, parse_mode=ParseMode.HTML
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
    app.add_handler(CommandHandler(["summary", "tldr"], view_summary))
    if settings.features["message_handling"]:
        app.add_handler(
            MessageHandler(
                (filters.TEXT & ~filters.COMMAND)
                | filters.VOICE
                | filters.PHOTO
                | filters.Document.IMAGE,
                handle_addressed_message,
            )
        )
    if settings.features["schedule_events"]:
        app.add_handler(MessageHandler(filters.PHOTO, schedule_events))

    """
    app.job_queue.run_repeating(
        refresh_settings_job,
        interval=settings.settings_refresh_interval,
        first=settings.settings_refresh_interval,
    )
    """

    logger.info("Bot started with features: %s", settings.features)
    app.run_polling()
