"""Prompt context assembly from recent dialogue and long-term summaries."""

import logging
from typing import Callable, Dict, List, Optional, Tuple

from src import config
from src.memory import history_store, summary_store

logger = logging.getLogger(__name__)


def estimate_token_count(text: str) -> int:
    return max(1, len(text) // 4)


def _format_message_line(msg: Dict) -> str:
    sender = msg.get("sender", "Unknown")
    text = msg.get("text", "")
    return f"{sender}: {text}"


def _collect_recent_lines(
    messages: List[Dict], max_turns: int, token_limit: int
) -> Tuple[List[str], int]:
    context_lines = []
    total_tokens = 0
    turns_used = 0

    for msg in reversed(messages):
        if turns_used >= max_turns:
            break
        line = _format_message_line(msg)
        tokens = estimate_token_count(line)
        if total_tokens + tokens > token_limit:
            break
        context_lines.append(line)
        total_tokens += tokens
        turns_used += 1

    context_lines.reverse()
    return context_lines, total_tokens


def build_context(
    chat_id: str,
    latest_user_text: str = "",
    token_limit: Optional[int] = None,
    messages: Optional[List[Dict]] = None,
    summarize_fn: Optional[Callable[[str], str]] = None,
) -> str:
    settings = config.get_settings()
    if token_limit is None:
        token_limit = settings.token_limit
    if token_limit <= 0:
        return ""

    source_messages = (
        list(messages)
        if messages is not None
        else history_store.get_all_messages(chat_id)
    )

    if not settings.memory_enabled:
        return assemble_context(source_messages, token_limit=token_limit)

    summary_store.maybe_rollup_summary(
        chat_id,
        source_messages,
        summarize_fn=summarize_fn,
        max_chunks=settings.memory_summary_max_chunks_per_run,
    )

    summary_budget_ratio = (
        settings.memory_summary_budget_ratio if settings.memory_summary_enabled else 0.0
    )
    summary_budget = int(token_limit * summary_budget_ratio)
    summary_budget = min(summary_budget, token_limit)
    recent_budget = max(0, token_limit - summary_budget)

    recent_lines, recent_tokens = _collect_recent_lines(
        source_messages,
        max_turns=settings.memory_recent_turns,
        token_limit=recent_budget,
    )

    sections = []
    used_tokens = recent_tokens
    if recent_lines:
        sections.append("[RECENT_DIALOGUE]\n" + "\n".join(recent_lines))

    if settings.memory_summary_enabled and summary_budget > 0:
        remaining = max(0, token_limit - used_tokens)
        summary_lines, summary_tokens = summary_store.build_summary_lines(
            chat_id=chat_id,
            latest_user_text=latest_user_text,
            token_limit=min(summary_budget, remaining),
            max_items=settings.memory_summary_max_items,
        )
        if summary_lines:
            sections.append("[LONG_TERM_SUMMARY]\n" + "\n".join(summary_lines))
            used_tokens += summary_tokens

    context = "\n\n".join(sections).strip()
    logger.debug(
        "Built context",
        extra={
            "chat_id": chat_id,
            "message_count": len(source_messages),
            "token_limit": token_limit,
            "approx_used_tokens": used_tokens,
            "recent_turns": settings.memory_recent_turns,
            "summary_enabled": settings.memory_summary_enabled,
        },
    )
    return context


def assemble_context(messages: list, token_limit: Optional[int] = None) -> str:
    if token_limit is None:
        token_limit = config.get_settings().token_limit
    logger.debug(
        "Assembling context with token limit", extra={"token_limit": token_limit}
    )
    context_lines, total_tokens = _collect_recent_lines(
        list(messages),
        max_turns=len(messages),
        token_limit=token_limit,
    )
    logger.debug(
        "Assembled context",
        extra={"message_count": len(context_lines), "token_count": total_tokens},
    )
    return "\n".join(context_lines)
