import io
import logging
import os
import tempfile
from typing import Any, Callable, Dict, Optional, Tuple

from telegram import Voice
from telegram.ext import ContextTypes

from src.model_provider import ModelProvider

NON_TEXT_REPLY_PLACEHOLDER = "[non-text message]"
IMAGE_MAX_BYTES = 15 * 1024 * 1024


def guess_mime_from_name(name: str) -> str:
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


def is_image_document(document: Any) -> Tuple[bool, str]:
    mime = (getattr(document, "mime_type", "") or "").lower()
    filename = (getattr(document, "file_name", "") or "").lower()
    guessed_mime = guess_mime_from_name(filename)
    image_doc = mime.startswith("image/") or bool(guessed_mime)
    effective_mime = mime if mime.startswith("image/") else guessed_mime
    return image_doc, effective_mime


def combine_caption_and_extracted(caption: str, extracted: str) -> str:
    caption_clean = (caption or "").strip()
    extracted_clean = (extracted or "").strip()
    if caption_clean and extracted_clean:
        return f"{caption_clean}\n{extracted_clean}".strip()
    return (caption_clean or extracted_clean).strip()


def message_sender_name(message: Any) -> str:
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


def _safe_file_size(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    if size < 0:
        return None
    return size


def _resolve_file_size(primary: Any, fallback: Any) -> Optional[int]:
    primary_size = _safe_file_size(primary)
    if primary_size is not None:
        return primary_size
    return _safe_file_size(fallback)


class MediaService:
    def __init__(
        self,
        *,
        provider_getter: Callable[[], ModelProvider],
        logger_override: Optional[logging.Logger] = None,
        log_context_fn: Optional[Callable[[Any], dict]] = None,
    ) -> None:
        self._provider_getter = provider_getter
        self._logger = logger_override or logging.getLogger(__name__)
        self._log_context = log_context_fn or (lambda _update: {})

    def transcribe_audio(self, audio_path: str) -> str:
        provider = self._provider_getter()
        return provider.transcribe(audio_path)

    async def transcribe_voice_message(
        self,
        voice: Voice,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> str:
        if voice is None:
            return ""

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
            temp_audio_path = temp_audio.name

        try:
            file = await context.bot.get_file(voice.file_id)
            await file.download_to_drive(temp_audio_path)
            return self.transcribe_audio(temp_audio_path)
        finally:
            try:
                os.remove(temp_audio_path)
            except OSError:
                self._logger.debug(
                    "Failed to remove temporary voice file",
                    extra={"path": temp_audio_path},
                )

    async def extract_text_from_photo_message(
        self,
        message: Any,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> str:
        if not getattr(message, "photo", None):
            return ""

        photo = message.photo[-1]
        photo_size = _safe_file_size(getattr(photo, "file_size", None))
        if photo_size is not None and photo_size > IMAGE_MAX_BYTES:
            self._logger.warning(
                "Photo too large for OCR",
                extra={"file_size": photo_size},
            )
            return (getattr(message, "caption", "") or "").strip()

        file = await context.bot.get_file(photo.file_id)
        resolved_size = _resolve_file_size(getattr(file, "file_size", None), photo_size)
        if resolved_size is not None and resolved_size > IMAGE_MAX_BYTES:
            self._logger.warning(
                "Photo too large for OCR",
                extra={"file_size": resolved_size},
            )
            return (getattr(message, "caption", "") or "").strip()

        bio = io.BytesIO()
        await file.download_to_memory(bio)
        image_bytes = bio.getvalue()
        if len(image_bytes) > IMAGE_MAX_BYTES:
            self._logger.warning(
                "Photo too large for OCR",
                extra={"file_size": len(image_bytes)},
            )
            return (getattr(message, "caption", "") or "").strip()
        extracted = self._provider_getter().image_to_text(
            image_bytes,
            mime_type="image/jpeg",
        )
        return combine_caption_and_extracted(
            getattr(message, "caption", "") or "",
            extracted,
        )

    async def extract_text_from_image_document(
        self,
        message: Any,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> Optional[str]:
        document = getattr(message, "document", None)
        if document is None:
            return None

        image_doc, effective_mime = is_image_document(document)
        if not image_doc:
            return None

        document_size = _safe_file_size(getattr(document, "file_size", None))
        if document_size is not None and document_size > IMAGE_MAX_BYTES:
            self._logger.warning(
                "Image document too large for OCR",
                extra={"file_size": document_size},
            )
            return (getattr(message, "caption", "") or "").strip()

        file = await context.bot.get_file(document.file_id)
        resolved_size = _resolve_file_size(
            getattr(file, "file_size", None), document_size
        )
        if resolved_size is not None and resolved_size > IMAGE_MAX_BYTES:
            self._logger.warning(
                "Image document too large for OCR",
                extra={"file_size": resolved_size},
            )
            return (getattr(message, "caption", "") or "").strip()

        bio = io.BytesIO()
        await file.download_to_memory(bio)
        image_bytes = bio.getvalue()
        if len(image_bytes) > IMAGE_MAX_BYTES:
            self._logger.warning(
                "Image document too large for OCR",
                extra={"file_size": len(image_bytes)},
            )
            return (getattr(message, "caption", "") or "").strip()
        extracted = self._provider_getter().image_to_text(
            image_bytes,
            mime_type=effective_mime or "image/jpeg",
        )
        return combine_caption_and_extracted(
            getattr(message, "caption", "") or "",
            extracted,
        )

    async def extract_reply_target_text(
        self,
        reply_message: Any,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> Tuple[str, str]:
        reply_text = (getattr(reply_message, "text", "") or "").strip()
        if reply_text:
            return reply_text, "message_text"

        if getattr(reply_message, "photo", None):
            try:
                extracted = await self.extract_text_from_photo_message(
                    reply_message,
                    context,
                )
                extracted_text = extracted.strip()
                if extracted_text:
                    return extracted_text, "fallback_ocr"
            except Exception as exc:
                self._logger.warning(
                    "Failed to OCR replied photo",
                    extra={"error": str(exc)},
                )

            caption = (getattr(reply_message, "caption", "") or "").strip()
            if caption:
                return caption, "message_caption"
            return NON_TEXT_REPLY_PLACEHOLDER, "non_text"

        if getattr(reply_message, "document", None):
            document = reply_message.document
            if document.file_size is not None and document.file_size > IMAGE_MAX_BYTES:
                caption = (getattr(reply_message, "caption", "") or "").strip()
                if caption:
                    return caption, "message_caption"
                return NON_TEXT_REPLY_PLACEHOLDER, "image_too_large"

            try:
                extracted = await self.extract_text_from_image_document(
                    reply_message,
                    context,
                )
                if extracted is not None:
                    extracted_text = extracted.strip()
                    if extracted_text:
                        return extracted_text, "fallback_ocr"
            except Exception as exc:
                self._logger.warning(
                    "Failed to OCR replied image document",
                    extra={"error": str(exc)},
                )

            caption = (getattr(reply_message, "caption", "") or "").strip()
            if caption:
                return caption, "message_caption"
            return NON_TEXT_REPLY_PLACEHOLDER, "non_text"

        reply_caption = (getattr(reply_message, "caption", "") or "").strip()
        if reply_caption:
            return reply_caption, "message_caption"
        return NON_TEXT_REPLY_PLACEHOLDER, "non_text"

    async def resolve_reply_target_context(
        self,
        message: Any,
        *,
        chat_id: str,
        context: ContextTypes.DEFAULT_TYPE,
        get_message_by_telegram_message_id_fn: Callable[[str, int], Optional[Dict]],
    ) -> Optional[Dict[str, str]]:
        reply_message = getattr(message, "reply_to_message", None)
        if reply_message is None:
            return None

        sender = message_sender_name(reply_message)
        reply_message_id = getattr(reply_message, "message_id", None)
        if reply_message_id is not None:
            stored_message = get_message_by_telegram_message_id_fn(
                chat_id,
                reply_message_id,
            )
            if stored_message is not None:
                stored_text = str(stored_message.get("text", "")).strip()
                if stored_text:
                    return {
                        "sender": str(stored_message.get("sender", sender) or sender),
                        "text": stored_text,
                        "source": "history_lookup",
                    }

        resolved_text, source = await self.extract_reply_target_text(
            reply_message,
            context,
        )
        return {
            "sender": sender,
            "text": resolved_text or NON_TEXT_REPLY_PLACEHOLDER,
            "source": source,
        }
