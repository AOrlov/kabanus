import asyncio
import hashlib
import logging
import time
from typing import Any, Callable, Optional

from telegram import Update

from src import config
from src.model_provider import ModelProvider
from src.telegram_drafts import send_message_draft


def message_drafts_unavailable_reason(
    update: Update, settings: config.Settings
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


async def generate_response_with_drafts(
    update: Update,
    prompt: str,
    settings: config.Settings,
    *,
    model_provider: ModelProvider,
    logger: logging.Logger,
    log_context_fn: Callable[[Optional[Update]], dict[str, Any]],
    send_message_draft_fn: Callable[..., Any] = send_message_draft,
) -> (
    str
):  # pylint: disable=too-many-arguments,too-many-locals,too-many-statements,broad-exception-caught
    chat = update.effective_chat
    if chat is None:
        return (model_provider.generate(prompt) or "").strip()

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
            logger.warning(
                "Failed to update Telegram message draft; continuing without drafts",
                extra={
                    **log_context_fn(update),
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
            send_message_draft_fn(
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
            interval = settings.telegram_draft_update_interval_secs
            if last_sent_ts and (now - last_sent_ts) < interval:
                continue
            _schedule_send(draft_text)
            await asyncio.sleep(0)
    except Exception as exc:
        stream_error = exc
        logger.warning(
            "Model stream failed; using best available response",
            extra={
                **log_context_fn(update),
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
                    **log_context_fn(update),
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
