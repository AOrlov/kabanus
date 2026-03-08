import asyncio
import hashlib
import logging
import time
from typing import Callable, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest

from src import utils
from src.bot.contracts import AddMessageFn, BotSettings, LogContextFn, ProviderGetter
from src.providers.contracts import TextGenerationRequest
from src.telegram_drafts import send_message_draft


def chunk_string(value: str, chunk_size: int) -> list[str]:
    if not value:
        return []
    if len(value) <= chunk_size:
        return [value]
    return [value[idx : idx + chunk_size] for idx in range(0, len(value), chunk_size)]


def message_drafts_unavailable_reason(
    update: Update,
    settings: BotSettings,
) -> Optional[str]:
    if not settings.telegram_use_message_drafts:
        return "feature_disabled"
    if settings.model_provider != "openai":
        return "provider_not_openai"
    if update.effective_chat is None:
        return "missing_chat"
    if update.effective_chat.type != "private":
        return f"chat_type_{update.effective_chat.type}"
    return None


def build_response_draft_id(update: Update) -> int:
    chat_id = getattr(update.effective_chat, "id", "unknown")
    message_id = getattr(update.message, "message_id", int(time.time() * 1000))
    raw = f"{chat_id}:{message_id}".encode("utf-8")
    value = int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")
    return (value % ((1 << 63) - 1)) + 1


class ReplyService:
    def __init__(
        self,
        *,
        provider_getter: ProviderGetter,
        settings_getter: Callable[[], BotSettings],
        add_message_fn: AddMessageFn,
        send_message_draft_fn: Callable[..., object] = send_message_draft,
        log_context_fn: LogContextFn = lambda _update: {},
        logger_override: Optional[logging.Logger] = None,
    ) -> None:
        self._provider_getter = provider_getter
        self._settings_getter = settings_getter
        self._add_message = add_message_fn
        self._send_message_draft = send_message_draft_fn
        self._log_context = log_context_fn
        self._logger = logger_override or logging.getLogger(__name__)

    async def generate_response_with_drafts(
        self,
        update: Update,
        prompt: str,
        settings: BotSettings,
    ) -> str:
        chat = update.effective_chat
        provider = self._provider_getter()
        if chat is None:
            return (
                provider.generate_text(TextGenerationRequest(prompt=prompt)) or ""
            ).strip()

        draft_id = build_response_draft_id(update)
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
                await asyncio.sleep(0)
                return
            try:
                await pending_send_task
            except Exception as exc:
                draft_updates_enabled = False
                self._logger.warning(
                    "Failed to update Telegram message draft; continuing without drafts",
                    extra={
                        **self._log_context(update),
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
                self._send_message_draft(
                    bot_token=settings.telegram_bot_token,
                    chat_id=chat.id,
                    draft_id=draft_id,
                    text=draft_text,
                )
            )
            last_sent_draft = draft_text
            last_sent_ts = time.monotonic()

        try:
            for snapshot in provider.generate_text_stream(
                TextGenerationRequest(prompt=prompt)
            ):
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
                if (
                    last_sent_ts
                    and (now - last_sent_ts)
                    < settings.telegram_draft_update_interval_secs
                ):
                    continue

                _schedule_send(draft_text)
                await asyncio.sleep(0)
        except Exception as exc:
            stream_error = exc
            self._logger.warning(
                "Model stream failed; using best available response",
                extra={
                    **self._log_context(update),
                    "error": str(exc),
                    "has_partial_output": bool(stream_text.strip()),
                },
            )
        finally:
            await _finalize_pending_send(force=True)

        final_text = stream_text.strip()
        if stream_error is not None and not final_text:
            try:
                final_text = (
                    provider.generate_text(TextGenerationRequest(prompt=prompt)) or ""
                ).strip()
            except Exception as fallback_exc:
                self._logger.warning(
                    "Fallback generation failed after stream error",
                    extra={
                        **self._log_context(update),
                        "stream_error": str(stream_error),
                        "fallback_error": str(fallback_exc),
                    },
                )
                return ""

        final_draft_text = (stream_text if stream_text else final_text)[:4096]
        if (
            final_draft_text.strip()
            and draft_updates_enabled
            and final_draft_text != last_sent_draft
        ):
            _schedule_send(final_draft_text)
            await _finalize_pending_send(force=True)

        return final_text

    async def send_ai_response(
        self,
        update: Update,
        outgoing_text: str,
        storage_id: str,
    ) -> None:
        message = update.message
        if message is None:
            return

        settings = self._settings_getter()
        if not settings.telegram_format_ai_replies:
            for chunk in [
                part for part in chunk_string(outgoing_text, 4000) if part.strip()
            ]:
                await message.reply_text(chunk)
                self._add_message("Bot", chunk, chat_id=storage_id, is_bot=True)
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
                    self._add_message(
                        "Bot", plain_chunk, chat_id=storage_id, is_bot=True
                    )
            except BadRequest as exc:
                self._logger.warning(
                    "Failed to send formatted response chunk, falling back to plain text",
                    extra={
                        **self._log_context(update),
                        "error": str(exc),
                        "chunk_preview": chunk[:256],
                    },
                )
                fallback_chunk = plain_chunk or chunk
                await message.reply_text(fallback_chunk)
                self._add_message(
                    "Bot", fallback_chunk, chat_id=storage_id, is_bot=True
                )
