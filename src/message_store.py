# message_store.py
"""Backward-compatible facade for message history, summaries, and context assembly."""

import logging
from typing import Callable, Dict, List, Optional, Tuple

from src import config
from src.memory import context_builder, history_store, summary_store

logger = logging.getLogger(__name__)


# Compatibility cache aliases expected by existing callers/tests.
_message_store_by_chat = history_store._message_store_by_chat
_summary_store_by_chat = summary_store._summary_store_by_chat


def _safe_int(value) -> Optional[int]:
    return history_store._safe_int(value)


def make_message(
    sender: str,
    text: str,
    is_bot: bool,
    telegram_message_id: Optional[int] = None,
    reply_to_telegram_message_id: Optional[int] = None,
) -> Dict:
    return history_store.make_message(
        sender,
        text,
        is_bot,
        telegram_message_id=telegram_message_id,
        reply_to_telegram_message_id=reply_to_telegram_message_id,
    )


def _get_store_path(chat_id: str) -> str:
    return history_store._get_store_path(chat_id)


def _load_messages(chat_id: str) -> List[Dict]:
    return history_store._load_messages(chat_id)


def _append_message(msg: Dict, chat_id: str) -> None:
    history_store._append_message(msg, chat_id)


def _ensure_loaded(chat_id: str) -> List[Dict]:
    return history_store._ensure_loaded(chat_id)


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


def get_message_by_telegram_message_id(chat_id: str, telegram_message_id: int) -> Optional[Dict]:
    return history_store.get_message_by_telegram_message_id(chat_id, telegram_message_id)


def estimate_token_count(text: str) -> int:
    return context_builder.estimate_token_count(text)


def _format_message_line(msg: Dict) -> str:
    return context_builder._format_message_line(msg)


def _collect_recent_lines(messages: List[Dict], max_turns: int, token_limit: int) -> Tuple[List[str], int]:
    return context_builder._collect_recent_lines(messages, max_turns=max_turns, token_limit=token_limit)


def _get_summary_store_path(chat_id: str) -> str:
    return summary_store._get_summary_store_path(chat_id)


def _load_summary_state(chat_id: str) -> Dict:
    return summary_store._load_summary_state(chat_id)


def _save_summary_state(chat_id: str, state: Dict) -> None:
    summary_store._save_summary_state(chat_id, state)


def _summary_chunk_to_text(index: int, chunk: Dict) -> str:
    return summary_store._summary_chunk_to_text(index, chunk)


def get_summary_view_text(
    chat_id: str,
    head: int = 0,
    tail: int = 0,
    index: Optional[int] = None,
    grep: str = "",
) -> str:
    return summary_store.get_summary_view_text(chat_id=chat_id, head=head, tail=tail, index=index, grep=grep)


def _message_id(msg: Dict, fallback_index: int) -> str:
    return summary_store._message_id(msg, fallback_index)


def _chunk_to_lines(chunk: List[Dict]) -> List[str]:
    return summary_store._chunk_to_lines(chunk)


def _fallback_chunk_summary(chunk: List[Dict], start: int, end: int) -> Dict:
    return summary_store._fallback_chunk_summary(chunk, start, end)


def _clean_string_list(value) -> List[str]:
    return summary_store._clean_string_list(value)


def _detect_dominant_language(chunk_lines: List[str]) -> str:
    return summary_store._detect_dominant_language(chunk_lines)


def _contains_language_markers(text: str, lang: str) -> bool:
    return summary_store._contains_language_markers(text, lang)


def _build_summary_prompt(chunk_lines: List[str], target_lang: str) -> str:
    return summary_store._build_summary_prompt(chunk_lines, target_lang)


def _summarize_chunk(
    chat_id: str,
    chunk: List[Dict],
    start: int,
    end: int,
    summarize_fn: Optional[Callable[[str], str]],
) -> Dict:
    return summary_store._summarize_chunk(chat_id, chunk, start, end, summarize_fn)


def maybe_rollup_summary(
    chat_id: str,
    messages: Optional[List[Dict]] = None,
    summarize_fn: Optional[Callable[[str], str]] = None,
    max_chunks: Optional[int] = None,
    force_rebuild: bool = False,
    parallel_workers: int = 1,
    on_chunk_done: Optional[Callable[[], None]] = None,
) -> int:
    return summary_store.maybe_rollup_summary(
        chat_id,
        messages=messages,
        summarize_fn=summarize_fn,
        max_chunks=max_chunks,
        force_rebuild=force_rebuild,
        parallel_workers=parallel_workers,
        on_chunk_done=on_chunk_done,
    )


def _build_summary_lines(
    chat_id: str,
    latest_user_text: str,
    token_limit: int,
    max_items: int,
) -> Tuple[List[str], int]:
    return summary_store._build_summary_lines(
        chat_id=chat_id,
        latest_user_text=latest_user_text,
        token_limit=token_limit,
        max_items=max_items,
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
