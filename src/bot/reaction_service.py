from dataclasses import dataclass
from datetime import date, datetime
import logging
import time
from typing import Any, Callable, Optional

from telegram import Update
from telegram.constants import ReactionEmoji

from src import config
from src.message_store import build_recent_context, get_all_messages
from src.model_provider import ModelProvider

REACTION_ALLOWED_SET = {emoji.value for emoji in ReactionEmoji}
REACTION_ALLOWED_LIST = sorted(REACTION_ALLOWED_SET)


@dataclass
class ReactionState:
    day: Optional[date] = None
    count: int = 0
    last_ts: float = 0.0
    messages_since_last: int = 0


def reset_reaction_budget_if_needed(now: datetime, state: ReactionState) -> None:
    today = now.date()
    if state.day != today:
        state.day = today
        state.count = 0


def build_reaction_context(
    chat_id: Optional[str],
    settings: config.Settings,
    *,
    get_all_messages_fn: Callable[[str], list[dict[str, Any]]] = get_all_messages,
    build_recent_context_fn: Callable[..., str] = build_recent_context,
) -> str:
    if (
        not chat_id
        or settings.reaction_context_turns <= 0
        or settings.reaction_context_token_limit <= 0
    ):
        return ""
    messages = get_all_messages_fn(chat_id)
    if not messages:
        return ""
    recent_messages = messages[-settings.reaction_context_turns :]
    return build_recent_context_fn(
        recent_messages,
        token_limit=settings.reaction_context_token_limit,
    )


async def maybe_react(
    update: Update,
    text: str,
    *,
    state: ReactionState,
    settings_getter: Callable[..., config.Settings],
    model_provider: ModelProvider,
    logger: logging.Logger,
    log_context_fn: Callable[[Optional[Update]], dict[str, Any]],
    storage_id_fn: Callable[[Update], Optional[str]],
    get_all_messages_fn: Callable[[str], list[dict[str, Any]]] = get_all_messages,
    build_recent_context_fn: Callable[..., str] = build_recent_context,
    allowed_list: Optional[list[str]] = None,
    allowed_set: Optional[set[str]] = None,
) -> (
    None
):  # pylint: disable=too-many-arguments,too-many-locals,too-many-return-statements,broad-exception-caught
    logger.debug("maybe_react called", extra=log_context_fn(update))
    settings = settings_getter()
    if update.message is None or not settings.reaction_enabled:
        return

    active_allowed_list = (
        allowed_list if allowed_list is not None else REACTION_ALLOWED_LIST
    )
    active_allowed_set = (
        allowed_set if allowed_set is not None else REACTION_ALLOWED_SET
    )

    state.messages_since_last += 1
    reset_reaction_budget_if_needed(datetime.now(), state)
    if (
        settings.reaction_daily_budget <= 0
        or state.count >= settings.reaction_daily_budget
    ):
        return

    if settings.reaction_cooldown_secs > 0:
        if time.monotonic() - state.last_ts < settings.reaction_cooldown_secs:
            return
    if state.messages_since_last < settings.reaction_messages_threshold:
        return

    chat_storage_id = storage_id_fn(update)
    reaction_context = build_reaction_context(
        chat_storage_id,
        settings,
        get_all_messages_fn=get_all_messages_fn,
        build_recent_context_fn=build_recent_context_fn,
    )
    if settings.debug_mode:
        logger.debug(
            "Built reaction context",
            extra={
                **log_context_fn(update),
                "has_context": bool(reaction_context),
                "context_chars": len(reaction_context),
                "context_preview": reaction_context[:256],
            },
        )

    reaction = model_provider.choose_reaction(
        text,
        active_allowed_list,
        context_text=reaction_context,
    ).strip()
    if not reaction:
        return
    if reaction not in active_allowed_set:
        logger.warning("Model returned unsupported reaction: %s", reaction)
        return

    try:
        await update.message.set_reaction(reaction)
    except Exception as exc:
        logger.warning("Failed to set reaction: %s", exc)
        return

    state.count += 1
    state.last_ts = time.monotonic()
    state.messages_since_last = 0
