from dataclasses import dataclass
import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.access import log_context, storage_id
from src.bot.media import (
    IMAGE_MAX_BYTES,
    extract_text_from_image_document,
    extract_text_from_photo_message,
    is_image_document,
    transcribe_voice_message,
)
from src.model_provider import ModelProvider


@dataclass(frozen=True)
class InboundMessagePayload:
    text: str
    sender: str
    storage_id: str
    is_transcribed_text: bool
    reply_to_telegram_message_id: Optional[int]
    source_kind: str


@dataclass(frozen=True)
class ResolvedInputText:
    text: str
    is_transcribed_text: bool
    source_kind: str


def _effective_sender(update: Update) -> Optional[str]:
    if update.effective_user is None:
        return None
    return (
        update.effective_user.first_name
        or update.effective_user.name
        or str(update.effective_user.id)
    )


def _reply_to_message_id(update: Update) -> Optional[int]:
    message = update.message
    if message is None or message.reply_to_message is None:
        return None
    return message.reply_to_message.message_id


async def _resolve_input_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    model_provider: ModelProvider,
    logger: logging.Logger,
) -> Optional[ResolvedInputText]:
    message = update.message
    if message is None:
        return None
    authored_text = (message.text or (message.caption or "")).strip()

    if message.voice:
        return await _resolve_voice_text(
            update,
            context,
            model_provider=model_provider,
            logger=logger,
        )

    if message.photo:
        return await _resolve_photo_text(
            update,
            context,
            model_provider=model_provider,
            logger=logger,
        )

    if message.document:
        return await _resolve_image_document_text(
            update,
            context,
            model_provider=model_provider,
            logger=logger,
        )

    logger.debug(
        "Received text message",
        extra={**log_context(update), "message_preview": authored_text[:256]},
    )
    return ResolvedInputText(authored_text, False, "text")


async def _resolve_voice_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    model_provider: ModelProvider,
    logger: logging.Logger,
) -> ResolvedInputText:
    assert update.message is not None
    assert update.message.voice is not None
    text = await transcribe_voice_message(
        update.message.voice,
        context,
        model_provider=model_provider,
        logger=logger,
    )
    logger.debug(
        "Received voice message",
        extra={**log_context(update), "message_preview": text[:256]},
    )
    return ResolvedInputText(text, True, "voice")


async def _resolve_photo_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    model_provider: ModelProvider,
    logger: logging.Logger,
) -> ResolvedInputText:
    assert update.message is not None
    text = await extract_text_from_photo_message(
        update.message,
        context,
        model_provider=model_provider,
    )
    logger.debug(
        "Received photo message",
        extra={**log_context(update), "message_preview": text[:256]},
    )
    return ResolvedInputText(text, False, "photo")


async def _resolve_image_document_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    model_provider: ModelProvider,
    logger: logging.Logger,
) -> Optional[ResolvedInputText]:
    assert update.message is not None
    assert update.message.document is not None
    document = update.message.document
    is_image_doc, _ = is_image_document(document)
    if not is_image_doc:
        logger.debug(
            "Ignoring non-image document message",
            extra=log_context(update),
        )
        return None
    if document.file_size is not None and document.file_size > IMAGE_MAX_BYTES:
        logger.warning(
            "Image document too large",
            extra={
                **log_context(update),
                "file_size": document.file_size,
            },
        )
        return None
    extracted = await extract_text_from_image_document(
        update.message,
        context,
        model_provider=model_provider,
    )
    if extracted is None:
        logger.debug(
            "Ignoring non-image document message",
            extra=log_context(update),
        )
        return None
    logger.debug(
        "Received image document",
        extra={**log_context(update), "message_preview": extracted[:256]},
    )
    return ResolvedInputText(extracted, False, "image_document")


async def normalize_inbound_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    model_provider: ModelProvider,
    logger: logging.Logger,
) -> Optional[InboundMessagePayload]:
    if update.message is None or update.effective_user is None:
        return None

    resolved_text = await _resolve_input_text(
        update,
        context,
        model_provider=model_provider,
        logger=logger,
    )
    if resolved_text is None:
        return None

    sender = _effective_sender(update)
    if sender is None:
        return None
    chat_storage_id = storage_id(update)
    if chat_storage_id is None:
        return None

    return InboundMessagePayload(
        text=resolved_text.text,
        sender=sender,
        storage_id=chat_storage_id,
        is_transcribed_text=resolved_text.is_transcribed_text,
        reply_to_telegram_message_id=_reply_to_message_id(update),
        source_kind=resolved_text.source_kind,
    )
