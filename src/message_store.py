# message_store.py
"""
In-memory message storage for context-aware Telegram bot extension.
"""
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

from src import config
from src import utils

logger = logging.getLogger(__name__)


# Message object schema
def make_message(sender: str, text: str, is_bot: bool) -> Dict:
    return {
        'id': f"{int(time.time() * 1000)}-{os.getpid()}",
        'ts': int(time.time()),
        'kind': 'bot' if is_bot else 'user',
        'sender': sender.strip() if not is_bot else 'Bot',  # sender's first name or `Bot` for bot messages
        'text': text.strip(),  # message text
    }


# File to persist messages (JSON Lines format)
def _get_store_path(chat_id: str) -> str:
    settings = config.get_settings()
    if os.path.isabs(settings.chat_messages_store_path):
        base_path = settings.chat_messages_store_path
    else:
        base_path = os.path.join(os.path.dirname(__file__), settings.chat_messages_store_path)
    if not chat_id:
        raise ValueError("chat_id is required for message storage")
    root, ext = os.path.splitext(base_path)
    if ext:
        base_dir = os.path.dirname(base_path) or "."
        stem = os.path.basename(root) or "messages"
    else:
        base_dir = base_path
        stem = "messages"
    ext = ".jsonl"
    safe_chat_id = str(chat_id).strip()
    path = os.path.join(base_dir, f"{stem}_{safe_chat_id}{ext}")
    # Ensure the file exists
    if not os.path.exists(path):
        # Create the file and its parent directory if needed
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'a', encoding='utf-8'):
            pass
    return path


def _load_messages(chat_id: str):
    path = _get_store_path(chat_id)
    logger.debug("Loading messages from file", extra={"chat_id": chat_id, "path": path})

    messages = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            messages.append(json.loads(line))
    logger.debug("Loaded messages", extra={"chat_id": chat_id, "count": len(messages)})
    return messages


def _append_message(msg: Dict, chat_id: str):
    path = _get_store_path(chat_id)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(msg, ensure_ascii=False) + '\n')


# In-memory list for message storage, keyed by chat id
_message_store_by_chat: Dict[str, List[Dict]] = {}
_summary_store_by_chat: Dict[str, Dict] = {}


def _ensure_loaded(chat_id: str) -> List[Dict]:
    if not chat_id:
        raise ValueError("chat_id is required for message storage")
    if chat_id not in _message_store_by_chat:
        _message_store_by_chat[chat_id] = _load_messages(chat_id)
    return _message_store_by_chat[chat_id]


def get_last_message(chat_id: str) -> Optional[Dict]:
    """Retrieve the last message from the in-memory store."""
    messages = _ensure_loaded(chat_id)
    if messages:
        return messages[-1]
    return None


def add_message(sender: str, text: str, chat_id: str, is_bot: bool = False):
    """Add a message to the in-memory store and append to file."""
    msg = make_message(sender, text, is_bot)
    messages = _ensure_loaded(chat_id)
    messages.append(msg)
    _append_message(msg, chat_id)


def get_all_messages(chat_id: str) -> List[Dict]:
    """Retrieve all stored messages."""
    messages = _ensure_loaded(chat_id)
    return list(messages)


def estimate_token_count(text: str) -> int:
    """Estimate token count for a message (simple word count as proxy)."""
    return max(1, len(text) // 4)


def _format_message_line(msg: Dict) -> str:
    sender = msg.get('sender', 'Unknown')
    text = msg.get('text', '')
    return f"{sender}: {text}"


def _collect_recent_lines(messages: List[Dict], max_turns: int, token_limit: int) -> Tuple[List[str], int]:
    context_lines = []
    total_tokens = 0
    turns_used = 0

    # Traverse messages in reverse (most recent first)
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

    # Reverse again to restore chronological order
    context_lines.reverse()
    return context_lines, total_tokens


def _get_summary_store_path(chat_id: str) -> str:
    path = _get_store_path(chat_id)
    if path.endswith(".jsonl"):
        return path[:-6] + ".summary.json"
    return path + ".summary.json"


def _load_summary_state(chat_id: str) -> Dict:
    if chat_id in _summary_store_by_chat:
        return _summary_store_by_chat[chat_id]

    path = _get_summary_store_path(chat_id)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {"version": 1, "last_message_count": 0, "chunks": []}
    _summary_store_by_chat[chat_id] = state
    return state


def _save_summary_state(chat_id: str, state: Dict) -> None:
    path = _get_summary_store_path(chat_id)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)


def _summary_chunk_to_text(index: int, chunk: Dict) -> str:
    def format_items(title: str, items: List[str]) -> List[str]:
        if not items:
            return [f"{title}: -"]
        return [f"{title} ({len(items)}):"] + [f"- {item}" for item in items]

    summary = str(chunk.get("summary", ""))
    facts = _clean_string_list(chunk.get("facts"))
    decisions = _clean_string_list(chunk.get("decisions"))
    open_items = _clean_string_list(chunk.get("open_items"))
    source_ids = chunk.get("source_message_ids", [])
    lines = [
        f"Chunk #{index}: {chunk.get('id', '')}",
        f"Summary: {summary or '-'}",
    ]
    lines.extend(format_items("Facts", facts))
    lines.extend(format_items("Decisions", decisions))
    lines.extend(format_items("Open items", open_items))
    if isinstance(source_ids, list) and source_ids:
        lines.append(f"Messages: {source_ids[0]} .. {source_ids[-1]} ({len(source_ids)})")
    return "\n".join(lines)


def get_summary_view_text(
    chat_id: str,
    head: int = 0,
    tail: int = 0,
    index: Optional[int] = None,
    grep: str = "",
) -> str:
    """Render summary state similarly to scripts/view_summary.py output."""
    state = _load_summary_state(chat_id)
    chunks = state.get("chunks", [])
    if not isinstance(chunks, list):
        raise RuntimeError("'chunks' must be a list")

    summary_path = _get_summary_store_path(chat_id)
    lines = [
        "Summary overview",
        f"File: {summary_path}",
        f"Version: {state.get('version')}",
        f"Messages processed: {state.get('last_message_count')}",
        f"Chunks total: {len(chunks)}",
    ]

    if index is not None:
        if index < 0 or index >= len(chunks):
            raise RuntimeError(f"index out of range: {index}")
        lines.append("")
        lines.append(_summary_chunk_to_text(index, chunks[index]))
        return "\n".join(lines)

    selected: List[Tuple[int, Dict]] = list(enumerate(chunks))
    if grep:
        needle = grep.lower()
        filtered: List[Tuple[int, Dict]] = []
        for idx, chunk in selected:
            payload = " ".join(
                [
                    str(chunk.get("summary", "")),
                    " ".join(_clean_string_list(chunk.get("facts"))),
                    " ".join(_clean_string_list(chunk.get("decisions"))),
                    " ".join(_clean_string_list(chunk.get("open_items"))),
                ]
            ).lower()
            if needle in payload:
                filtered.append((idx, chunk))
        selected = filtered
        lines.append(f"Matches for '{grep}': {len(selected)}")

    to_show: List[Tuple[int, Dict]] = []
    if head > 0:
        to_show.extend(selected[:head])
    if tail > 0:
        tail_items = selected[-tail:]
        existing = {idx for idx, _ in to_show}
        to_show.extend([(idx, chunk) for idx, chunk in tail_items if idx not in existing])

    if not to_show:
        lines.append(
            "No chunks selected. Try /summary, /summary tail 5, /summary index 12, "
            "or add search text like /summary budget."
        )
        return "\n".join(lines)

    for idx, chunk in to_show:
        lines.append("")
        lines.append(_summary_chunk_to_text(idx, chunk))
    return "\n".join(lines)


def _message_id(msg: Dict, fallback_index: int) -> str:
    value = msg.get('id')
    if value:
        return str(value)
    return f"legacy-{fallback_index}"


def _chunk_to_lines(chunk: List[Dict]) -> List[str]:
    return [_format_message_line(msg) for msg in chunk]


def _fallback_chunk_summary(chunk: List[Dict], start: int, end: int) -> Dict:
    lines = _chunk_to_lines(chunk)
    first = lines[0] if lines else ""
    last = lines[-1] if lines else ""
    return {
        "id": f"chunk-{start}-{end}",
        "source_message_ids": [
            _message_id(msg, fallback_index=start + idx)
            for idx, msg in enumerate(chunk)
        ],
        "summary": f"{first} ... {last}".strip(),
        "facts": [],
        "decisions": [],
        "open_items": [],
    }


def _clean_string_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                result.append(stripped)
    return result


def _detect_dominant_language(chunk_lines: List[str]) -> str:
    text = "\n".join(chunk_lines)
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    if cyr > lat:
        return "ru"
    return "en"


def _contains_language_markers(text: str, lang: str) -> bool:
    if not text.strip():
        return True
    if lang == "ru":
        return bool(re.search(r"[А-Яа-яЁё]", text))
    if lang == "en":
        return bool(re.search(r"[A-Za-z]", text))
    return True


def _build_summary_prompt(chunk_lines: List[str], target_lang: str) -> str:
    dialogue = "\n".join(chunk_lines)
    lang_name = "Russian" if target_lang == "ru" else "English"
    lang_rule = (
        "Use Russian only. Do not translate to English."
        if target_lang == "ru"
        else "Use English only."
    )
    return (
        "Summarize this chat dialogue chunk. Return JSON only, no markdown.\n"
        "Schema:\n"
        "{\n"
        '  "summary": string,\n'
        '  "facts": string[],\n'
        '  "decisions": string[],\n'
        '  "open_items": string[]\n'
        "}\n"
        "Rules:\n"
        "- Keep summary under 80 words.\n"
        "- facts: durable preferences/profile/context facts only.\n"
        "- decisions: concrete choices made.\n"
        "- open_items: unresolved asks/tasks/questions.\n"
        "- If unknown, return empty arrays.\n\n"
        f"- Target language: {lang_name}.\n"
        f"- {lang_rule}\n\n"
        "Dialogue:\n"
        f"{dialogue}"
    )


def _summarize_chunk(
    chat_id: str,
    chunk: List[Dict],
    start: int,
    end: int,
    summarize_fn: Optional[Callable[[str], str]],
) -> Dict:
    fallback = _fallback_chunk_summary(chunk, start, end)
    if summarize_fn is None:
        return fallback
    chunk_lines = _chunk_to_lines(chunk)
    target_lang = _detect_dominant_language(chunk_lines)
    try:
        prompt = _build_summary_prompt(chunk_lines, target_lang=target_lang)
        raw = summarize_fn(prompt).strip()
        if not raw:
            return fallback
        parsed = json.loads(utils.strip_markdown_to_json(raw))
        # Retry once with stricter wording if language does not match.
        combined_text = " ".join(
            [
                str(parsed.get("summary", "")),
                " ".join(_clean_string_list(parsed.get("facts"))),
                " ".join(_clean_string_list(parsed.get("decisions"))),
                " ".join(_clean_string_list(parsed.get("open_items"))),
            ]
        )
        if not _contains_language_markers(combined_text, target_lang):
            stricter = (
                prompt
                + "\n\nIMPORTANT: Your previous answer used the wrong language. "
                + ("Respond strictly in Russian." if target_lang == "ru" else "Respond strictly in English.")
            )
            raw_retry = summarize_fn(stricter).strip()
            if raw_retry:
                parsed_retry = json.loads(utils.strip_markdown_to_json(raw_retry))
                if isinstance(parsed_retry, dict):
                    parsed = parsed_retry
        if not isinstance(parsed, dict):
            return fallback
        summary_text = str(parsed.get("summary", "")).strip()
        if not summary_text:
            summary_text = fallback["summary"]
        return {
            "id": fallback["id"],
            "source_message_ids": fallback["source_message_ids"],
            "summary": summary_text,
            "facts": _clean_string_list(parsed.get("facts")),
            "decisions": _clean_string_list(parsed.get("decisions")),
            "open_items": _clean_string_list(parsed.get("open_items")),
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Failed to parse chunk summary JSON: %s", exc, extra={"chat_id": chat_id})
        return fallback
    except Exception as exc:
        logger.warning("Chunk summarization failed: %s", exc, extra={"chat_id": chat_id})
        return fallback


def maybe_rollup_summary(
    chat_id: str,
    messages: Optional[List[Dict]] = None,
    summarize_fn: Optional[Callable[[str], str]] = None,
    max_chunks: Optional[int] = None,
    force_rebuild: bool = False,
    parallel_workers: int = 1,
    on_chunk_done: Optional[Callable[[], None]] = None,
) -> int:
    """Create chunk-level summaries. Returns number of newly created chunks."""
    settings = config.get_settings()
    if not settings.memory_summary_enabled:
        return 0

    messages = list(messages) if messages is not None else get_all_messages(chat_id)
    if force_rebuild:
        state = {"version": 1, "last_message_count": 0, "chunks": []}
        _summary_store_by_chat[chat_id] = state
    else:
        state = _load_summary_state(chat_id)
    chunk_size = settings.memory_summary_chunk_size
    processed = int(state.get("last_message_count", 0))
    if processed > len(messages):
        processed = 0
        state = {"version": 1, "last_message_count": 0, "chunks": []}
        _summary_store_by_chat[chat_id] = state

    chunk_limit = settings.memory_summary_max_chunks_per_run if max_chunks is None else max_chunks
    if chunk_limit <= 0:
        chunk_limit = 1

    changed = False
    created = 0

    candidates = []
    scan = processed
    while len(messages) - scan >= chunk_size and len(candidates) < chunk_limit:
        chunk = messages[scan:scan + chunk_size]
        start = scan
        end = scan + chunk_size - 1
        candidates.append((chunk, start, end))
        scan += chunk_size

    if candidates:
        max_workers = max(1, int(parallel_workers))
        if summarize_fn is None or max_workers == 1 or len(candidates) == 1:
            summaries = []
            for chunk, start, end in candidates:
                summaries.append(
                    _summarize_chunk(
                        chat_id=chat_id,
                        chunk=chunk,
                        start=start,
                        end=end,
                        summarize_fn=summarize_fn,
                    )
                )
                if on_chunk_done is not None:
                    on_chunk_done()
        else:
            by_start = {}
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {
                    pool.submit(
                        _summarize_chunk,
                        chat_id,
                        chunk,
                        start,
                        end,
                        summarize_fn,
                    ): start
                    for chunk, start, end in candidates
                }
                for fut in as_completed(future_map):
                    start = future_map[fut]
                    by_start[start] = fut.result()
                    if on_chunk_done is not None:
                        on_chunk_done()
            summaries = [by_start[start] for _, start, _ in candidates]

        for chunk_summary in summaries:
            state.setdefault("chunks", []).append(chunk_summary)
            processed += chunk_size
            state["last_message_count"] = processed
            changed = True
            created += 1

    if changed:
        _save_summary_state(chat_id, state)
    return created


def _build_summary_lines(
    chat_id: str,
    latest_user_text: str,
    token_limit: int,
    max_items: int,
) -> Tuple[List[str], int]:
    if token_limit <= 0 or max_items <= 0:
        return [], 0

    state = _load_summary_state(chat_id)
    chunks = state.get("chunks", [])
    if not chunks:
        return [], 0

    query_terms = {term for term in latest_user_text.lower().split() if term}
    scored = []
    for chunk in chunks:
        summary = str(chunk.get("summary", "")).strip()
        if not summary:
            continue
        summary_terms = set(summary.lower().split())
        overlap = len(query_terms & summary_terms) if query_terms else 0
        facts = _clean_string_list(chunk.get("facts"))
        decisions = _clean_string_list(chunk.get("decisions"))
        open_items = _clean_string_list(chunk.get("open_items"))
        score = overlap + (2 if decisions else 0) + (1 if facts else 0) + (1 if open_items else 0)
        details = []
        if facts:
            details.append("facts: " + "; ".join(facts[:3]))
        if decisions:
            details.append("decisions: " + "; ".join(decisions[:3]))
        if open_items:
            details.append("open_items: " + "; ".join(open_items[:3]))
        text = summary if not details else summary + " | " + " | ".join(details)
        scored.append((score, text))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [summary for _, summary in scored[:max_items]]

    lines = []
    total_tokens = 0
    for summary in selected:
        line = f"- {summary}"
        tokens = estimate_token_count(line)
        if total_tokens + tokens > token_limit:
            break
        lines.append(line)
        total_tokens += tokens

    return lines, total_tokens


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

    source_messages = list(messages) if messages is not None else get_all_messages(chat_id)

    if not settings.memory_enabled:
        return assemble_context(source_messages, token_limit=token_limit)

    maybe_rollup_summary(
        chat_id,
        source_messages,
        summarize_fn=summarize_fn,
        max_chunks=settings.memory_summary_max_chunks_per_run,
    )

    summary_budget_ratio = settings.memory_summary_budget_ratio if settings.memory_summary_enabled else 0.0
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
        summary_lines, summary_tokens = _build_summary_lines(
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
    """Backward-compatible context assembly for existing callers."""
    if token_limit is None:
        token_limit = config.get_settings().token_limit
    logger.debug("Assembling context with token limit", extra={"token_limit": token_limit})
    context_lines, total_tokens = _collect_recent_lines(
        list(messages),
        max_turns=len(messages),
        token_limit=token_limit,
    )
    logger.debug(
        "Assembled context",
        extra={"message_count": len(context_lines), "token_count": total_tokens},
    )
    return '\n'.join(context_lines)
