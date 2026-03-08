import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.bot.contracts import (
    AddMessageFn,
    BotSettings,
    BuildContextFn,
    GetMessageByTelegramMessageIdFn,
    IsAllowedFn,
    LogContextFn,
    ProviderGetter,
    StorageIdFn,
)
from src.bot.services.media_service import (
    IMAGE_MAX_BYTES,
    MediaService,
    NON_TEXT_REPLY_PLACEHOLDER,
    is_image_document,
)
from src.providers.contracts import TextGenerationRequest


def entity_type_value(entity: Any) -> str:
    entity_type = getattr(entity, "type", "")
    if hasattr(entity_type, "value"):
        return str(entity_type.value).lower()
    return str(entity_type).lower()


def iter_message_entity_blocks(message: Any) -> Iterable[Tuple[str, Iterable[Any]]]:
    text = getattr(message, "text", "") or ""
    if text:
        yield text, getattr(message, "entities", []) or []
    caption = getattr(message, "caption", "") or ""
    if caption:
        yield caption, getattr(message, "caption_entities", []) or []


def normalized_aliases(aliases: Iterable[str]) -> set[str]:
    normalized = set()
    for alias in aliases:
        value = str(alias or "").strip().lower().lstrip("@")
        if value:
            normalized.add(value)
    return normalized


def contains_alias_token(text: str, aliases: Iterable[str]) -> bool:
    text_lower = str(text or "").lower()
    if not text_lower:
        return False
    for alias in normalized_aliases(aliases):
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text_lower):
            return True
    return False


def _extract_utf16_entity_text(text: str, offset: int, length: int) -> str:
    if offset < 0 or length <= 0:
        return ""
    encoded = str(text).encode("utf-16-le")
    start = offset * 2
    end = (offset + length) * 2
    if start < 0 or end > len(encoded):
        return ""
    try:
        return encoded[start:end].decode("utf-16-le")
    except UnicodeDecodeError:
        return ""


def is_bot_mentioned(
    message: Any,
    *,
    bot_username: str,
    bot_id: int,
    aliases: list[str],
    fallback_text: str = "",
) -> bool:
    normalized = normalized_aliases(aliases)
    normalized_username = str(bot_username or "").strip().lower().lstrip("@")
    if normalized_username:
        normalized.add(normalized_username)

    for source_text, entities in iter_message_entity_blocks(message):
        for entity in entities:
            entity_type = entity_type_value(entity)
            if entity_type == "mention":
                try:
                    offset = int(getattr(entity, "offset", 0))
                    length = int(getattr(entity, "length", 0))
                except (TypeError, ValueError):
                    continue
                mention_text = _extract_utf16_entity_text(source_text, offset, length)
                if not mention_text:
                    continue
                mention = mention_text.strip().lower().lstrip("@")
                if mention and mention in normalized:
                    return True
            elif entity_type == "text_mention":
                user = getattr(entity, "user", None)
                user_id = getattr(user, "id", None)
                if user_id == bot_id:
                    return True

    authored_text = "\n".join([text for text, _ in iter_message_entity_blocks(message)])
    if contains_alias_token(authored_text, normalized):
        return True
    if fallback_text and contains_alias_token(fallback_text, normalized):
        return True
    return False


def should_respond_to_message(
    *,
    mentioned_bot: bool,
    replied_to_bot: bool,
    replied_to_other_user: bool,
) -> bool:
    if replied_to_other_user:
        return mentioned_bot
    return mentioned_bot or replied_to_bot


def build_prompt(
    *,
    context_text: str,
    sender: str,
    latest_text: str,
    reply_target_context: Optional[Dict[str, str]] = None,
) -> str:
    if reply_target_context is None:
        return f"{context_text}\n---\n{sender}: {latest_text}"

    target_sender = reply_target_context.get("sender", "Unknown")
    target_text = reply_target_context.get("text", NON_TEXT_REPLY_PLACEHOLDER)
    return (
        f"{context_text}\n---\n"
        "Target message for clarification:\n"
        f"{target_sender}: {target_text}\n"
        "---\n"
        f"{sender}: {latest_text}"
    )


class MessageHandler:
    def __init__(
        self,
        *,
        settings_getter: Callable[[], BotSettings],
        is_allowed_fn: IsAllowedFn,
        storage_id_fn: StorageIdFn,
        add_message_fn: AddMessageFn,
        get_message_by_telegram_message_id_fn: GetMessageByTelegramMessageIdFn,
        build_context_fn: BuildContextFn,
        provider_getter: ProviderGetter,
        media_service: MediaService,
        maybe_react_fn: Callable[[Update, str], Awaitable[None]],
        send_ai_response_fn: Callable[[Update, str, str], Awaitable[None]],
        generate_response_with_drafts_fn: Callable[
            [Update, str, BotSettings], Awaitable[str]
        ],
        message_drafts_unavailable_reason_fn: Callable[
            [Update, BotSettings], Optional[str]
        ],
        log_context_fn: LogContextFn,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
        logger_override: Optional[logging.Logger] = None,
    ) -> None:
        self._settings_getter = settings_getter
        self._is_allowed = is_allowed_fn
        self._storage_id = storage_id_fn
        self._add_message = add_message_fn
        self._get_message_by_telegram_message_id = get_message_by_telegram_message_id_fn
        self._build_context = build_context_fn
        self._provider_getter = provider_getter
        self._media_service = media_service
        self._maybe_react = maybe_react_fn
        self._send_ai_response = send_ai_response_fn
        self._generate_response_with_drafts = generate_response_with_drafts_fn
        self._message_drafts_unavailable_reason = message_drafts_unavailable_reason_fn
        self._log_context = log_context_fn
        self._sleep = sleep_fn
        self._logger = logger_override or logging.getLogger(__name__)

    async def handle_addressed_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        self._logger.debug(
            "handle_addressed_message called", extra=self._log_context(update)
        )
        settings = self._settings_getter()
        if not self._is_allowed(update) or not settings.features["message_handling"]:
            return

        if not update.message or not update.effective_user or not update.effective_chat:
            return
        if update.effective_user.is_bot:
            return

        is_transcribe_text = False
        authored_text = (update.message.text or (update.message.caption or "")).strip()
        if update.message.voice:
            text = await self._media_service.transcribe_voice_message(
                update.message.voice,
                context,
            )
            self._logger.debug(
                "Received voice message",
                extra={**self._log_context(update), "message_preview": text[:256]},
            )
            is_transcribe_text = True
        elif update.message.photo:
            text = await self._media_service.extract_text_from_photo_message(
                update.message,
                context,
            )
            self._logger.debug(
                "Received photo message",
                extra={**self._log_context(update), "message_preview": text[:256]},
            )
        elif update.message.document:
            image_doc, _ = is_image_document(update.message.document)
            if not image_doc:
                self._logger.debug(
                    "Ignoring non-image document message",
                    extra=self._log_context(update),
                )
                return

            if (
                update.message.document.file_size is not None
                and update.message.document.file_size > IMAGE_MAX_BYTES
            ):
                self._logger.warning(
                    "Image document too large",
                    extra={
                        **self._log_context(update),
                        "file_size": update.message.document.file_size,
                    },
                )
                return

            text_from_document = (
                await self._media_service.extract_text_from_image_document(
                    update.message,
                    context,
                )
            )
            if text_from_document is None:
                self._logger.debug(
                    "Ignoring non-image document message",
                    extra=self._log_context(update),
                )
                return

            text = text_from_document
            self._logger.debug(
                "Received image document",
                extra={**self._log_context(update), "message_preview": text[:256]},
            )
        else:
            text = authored_text
            self._logger.debug(
                "Received text message",
                extra={**self._log_context(update), "message_preview": text[:256]},
            )

        sender = update.effective_user.first_name or update.effective_user.name
        chat_storage_id = self._storage_id(update)
        if chat_storage_id is None:
            return

        reply_to_telegram_message_id = None
        if update.message.reply_to_message is not None:
            reply_to_telegram_message_id = update.message.reply_to_message.message_id

        self._add_message(
            sender,
            text,
            is_bot=False,
            chat_id=chat_storage_id,
            telegram_message_id=update.message.message_id,
            reply_to_telegram_message_id=reply_to_telegram_message_id,
        )

        await self._maybe_react(update, text)

        bot = await context.bot.get_me()
        mentioned_bot = is_bot_mentioned(
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
        should_respond = should_respond_to_message(
            mentioned_bot=mentioned_bot,
            replied_to_bot=replied_to_bot,
            replied_to_other_user=replied_to_other_user,
        )
        self._logger.debug(
            "Addressing decision",
            extra={
                **self._log_context(update),
                "mentioned_bot": mentioned_bot,
                "replied_to_bot": replied_to_bot,
                "replied_to_other_user": replied_to_other_user,
                "triggered": should_respond,
            },
        )

        if not should_respond:
            if is_transcribe_text:
                await update.effective_chat.send_action(action=ChatAction.TYPING)
                await update.message.reply_text(text)
            return

        reply_target_context = None
        if replied_to_other_user and mentioned_bot:
            reply_target_context = await self._media_service.resolve_reply_target_context(
                update.message,
                chat_id=chat_storage_id,
                context=context,
                get_message_by_telegram_message_id_fn=self._get_message_by_telegram_message_id,
            )
            if settings.debug_mode and reply_target_context is not None:
                self._logger.debug(
                    "Resolved reply target context",
                    extra={
                        **self._log_context(update),
                        "source": reply_target_context.get("source", ""),
                        "reply_target_preview": reply_target_context.get("text", "")[
                            :256
                        ],
                    },
                )

        await update.effective_chat.send_action(action=ChatAction.TYPING)
        provider = self._provider_getter()
        context_str = self._build_context(
            chat_id=chat_storage_id,
            latest_user_text=text,
            summarize_fn=lambda prompt: provider.generate_low_cost_text(
                TextGenerationRequest(prompt=prompt)
            ),
        )
        prompt = build_prompt(
            context_text=context_str,
            sender=sender,
            latest_text=text,
            reply_target_context=reply_target_context,
        )
        if settings.debug_mode:
            if len(prompt) > 1024:
                self._logger.debug(
                    "Generated prompt (trimmed)",
                    extra={
                        **self._log_context(update),
                        "prompt": prompt[:512] + "\n...\n" + prompt[-512:],
                    },
                )
            else:
                self._logger.debug(
                    "Generated prompt",
                    extra={**self._log_context(update), "prompt": prompt},
                )

        draft_unavailable_reason = self._message_drafts_unavailable_reason(
            update, settings
        )
        use_message_drafts = draft_unavailable_reason is None
        if settings.telegram_use_message_drafts and not use_message_drafts:
            self._logger.debug(
                "Telegram message drafts are enabled but cannot be used in this chat",
                extra={
                    **self._log_context(update),
                    "reason": draft_unavailable_reason,
                    "model_provider": settings.model_provider,
                    "chat_type": getattr(update.effective_chat, "type", None),
                },
            )

        response = ""
        max_empty_retries = 3
        for attempt in range(1, max_empty_retries + 1):
            if use_message_drafts:
                response = await self._generate_response_with_drafts(
                    update,
                    prompt,
                    settings,
                )
            else:
                response = (
                    provider.generate_text(TextGenerationRequest(prompt=prompt)) or ""
                ).strip()
            if response:
                break

            self._logger.warning(
                "Model returned empty response",
                extra={
                    **self._log_context(update),
                    "attempt": attempt,
                    "max_attempts": max_empty_retries,
                },
            )
            if attempt < max_empty_retries:
                await self._sleep(0.5)

        if not response:
            self._logger.warning(
                "Ignoring message due to empty model response after retries",
                extra=self._log_context(update),
            )
            return

        outgoing_text = response
        if is_transcribe_text:
            outgoing_text = f">>{text}\n\n{response}".strip()

        await self._send_ai_response(update, outgoing_text, chat_storage_id)
