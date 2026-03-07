"""Facade module for message storage, summary rollup, and context building."""

from src import config
from src.message_store_context import build_context, build_recent_context, estimate_token_count
from src.message_store_storage import (
    _message_store_by_chat,
    add_message,
    get_all_messages,
    get_last_message,
    get_message_by_telegram_message_id,
    make_message,
)
from src.message_store_summary import (
    _summary_store_by_chat,
    get_summary_view_text,
    maybe_rollup_summary,
)

__all__ = [
    "add_message",
    "build_context",
    "build_recent_context",
    "config",
    "estimate_token_count",
    "get_all_messages",
    "get_last_message",
    "get_message_by_telegram_message_id",
    "get_summary_view_text",
    "make_message",
    "maybe_rollup_summary",
    "_message_store_by_chat",
    "_summary_store_by_chat",
]
