"""Public memory API for chat history, context assembly, and summary views."""

from typing import Callable, Dict, List, Optional

from src.memory import context_builder, history_store, summary_store


def clear_memory_state(chat_id: Optional[str] = None) -> None:
    history_store.clear_cache(chat_id)
    summary_store.clear_cache(chat_id)


def get_last_message(chat_id: str) -> Optional[Dict]:
    return history_store.get_last_message(chat_id)


def add_message(
    sender: str,
    text: str,
    chat_id: str,
    is_bot: bool = False,
    telegram_message_id: Optional[int] = None,
    reply_to_telegram_message_id: Optional[int] = None,
) -> None:
    history_store.add_message(
        sender,
        text,
        chat_id,
        is_bot=is_bot,
        telegram_message_id=telegram_message_id,
        reply_to_telegram_message_id=reply_to_telegram_message_id,
    )


def get_all_messages(chat_id: str) -> List[Dict]:
    return history_store.get_all_messages(chat_id)


def get_message_by_telegram_message_id(
    chat_id: str, telegram_message_id: int
) -> Optional[Dict]:
    return history_store.get_message_by_telegram_message_id(
        chat_id, telegram_message_id
    )


def get_summary_view_text(
    chat_id: str,
    head: int = 0,
    tail: int = 0,
    index: Optional[int] = None,
    grep: str = "",
) -> str:
    return summary_store.get_summary_view_text(
        chat_id=chat_id,
        head=head,
        tail=tail,
        index=index,
        grep=grep,
    )


def build_context(
    chat_id: str,
    latest_user_text: str = "",
    token_limit: Optional[int] = None,
    messages: Optional[List[Dict]] = None,
    summarize_fn: Optional[Callable[[str], str]] = None,
) -> str:
    return context_builder.build_context(
        chat_id=chat_id,
        latest_user_text=latest_user_text,
        token_limit=token_limit,
        messages=messages,
        summarize_fn=summarize_fn,
    )


def assemble_context(messages: list, token_limit: Optional[int] = None) -> str:
    return context_builder.assemble_context(messages, token_limit=token_limit)


__all__ = [
    "add_message",
    "assemble_context",
    "build_context",
    "clear_memory_state",
    "get_all_messages",
    "get_last_message",
    "get_message_by_telegram_message_id",
    "get_summary_view_text",
]
