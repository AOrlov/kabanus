import asyncio
import logging
from typing import Dict, Optional

from telegram import Update

from src import config
from src.bot.access import log_context
from src.bot.draft_service import (
    generate_response_with_drafts,
    message_drafts_unavailable_reason,
)
from src.model_provider import ModelProvider


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
    target_text = reply_target_context.get("text", "[non-text message]")
    return (
        f"{context_text}\n---\n"
        "Target message for clarification:\n"
        f"{target_sender}: {target_text}\n"
        "---\n"
        f"{sender}: {latest_text}"
    )


def log_prompt_if_debug(
    *,
    prompt: str,
    settings: config.Settings,
    logger: logging.Logger,
    update: Update,
) -> None:
    if not settings.debug_mode:
        return
    if len(prompt) > 1024:
        logger.debug(
            "Generated prompt (trimmed)",
            extra={
                **log_context(update),
                "prompt": prompt[:512] + "\n...\n" + prompt[-512:],
            },
        )
        return
    logger.debug(
        "Generated prompt",
        extra={**log_context(update), "prompt": prompt},
    )


def _should_use_message_drafts(
    update: Update,
    settings: config.Settings,
    *,
    logger: logging.Logger,
) -> bool:
    draft_unavailable_reason = message_drafts_unavailable_reason(update, settings)
    use_message_drafts = draft_unavailable_reason is None
    if settings.telegram_use_message_drafts and not use_message_drafts:
        logger.debug(
            "Telegram message drafts are enabled but cannot be used in this chat",
            extra={
                **log_context(update),
                "reason": draft_unavailable_reason,
                "model_provider": settings.model_provider,
                "chat_type": getattr(update.effective_chat, "type", None),
            },
        )
    return use_message_drafts


async def _generate_response_once(
    update: Update,
    *,
    prompt: str,
    settings: config.Settings,
    model_provider: ModelProvider,
    logger: logging.Logger,
) -> str:
    if _should_use_message_drafts(update, settings, logger=logger):
        return await generate_response_with_drafts(
            update,
            prompt,
            settings,
            model_provider=model_provider,
            logger=logger,
            log_context_fn=log_context,
        )
    return (model_provider.generate(prompt) or "").strip()


async def generate_response_with_retries(
    update: Update,
    *,
    prompt: str,
    settings: config.Settings,
    model_provider: ModelProvider,
    logger: logging.Logger,
) -> str:
    response = ""
    max_empty_retries = 3
    for attempt in range(1, max_empty_retries + 1):
        response = await _generate_response_once(
            update,
            prompt=prompt,
            settings=settings,
            model_provider=model_provider,
            logger=logger,
        )
        if response:
            break
        logger.warning(
            "Model returned empty response",
            extra={
                **log_context(update),
                "attempt": attempt,
                "max_attempts": max_empty_retries,
            },
        )
        if attempt < max_empty_retries:
            await asyncio.sleep(0.5)

    if response:
        return response

    logger.warning(
        "Ignoring message due to empty model response after retries",
        extra=log_context(update),
    )
    return ""


def build_outgoing_text(
    *,
    source_text: str,
    response_text: str,
    is_transcribed_text: bool,
) -> str:
    if not is_transcribed_text:
        return response_text
    return f">>{source_text}\n\n{response_text}".strip()
