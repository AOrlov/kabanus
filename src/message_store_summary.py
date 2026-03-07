import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from src import config
from src import utils
from src.message_store_storage import get_all_messages, get_store_path

logger = logging.getLogger(__name__)


_summary_store_by_chat: Dict[str, Dict[str, Any]] = {}


def get_summary_store_path(chat_id: str) -> str:
    path = get_store_path(chat_id)
    if path.endswith(".jsonl"):
        return path[:-6] + ".summary.json"
    return path + ".summary.json"


def load_summary_state(chat_id: str) -> Dict[str, Any]:
    if chat_id in _summary_store_by_chat:
        return _summary_store_by_chat[chat_id]

    path = get_summary_store_path(chat_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            loaded = json.load(file)
            state = loaded if isinstance(loaded, dict) else {}
    else:
        state = {"version": 1, "last_message_count": 0, "chunks": []}
    _summary_store_by_chat[chat_id] = state
    return state


def save_summary_state(chat_id: str, state: Dict[str, Any]) -> None:
    path = get_summary_store_path(chat_id)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)


def clean_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                result.append(stripped)
    return result


def _summary_chunk_to_text(index: int, chunk: Dict[str, Any]) -> str:
    def format_items(title: str, items: List[str]) -> List[str]:
        if not items:
            return [f"{title}: -"]
        return [f"{title} ({len(items)}):"] + [f"- {item}" for item in items]

    summary = str(chunk.get("summary", ""))
    facts = clean_string_list(chunk.get("facts"))
    decisions = clean_string_list(chunk.get("decisions"))
    open_items = clean_string_list(chunk.get("open_items"))
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
    state = load_summary_state(chat_id)
    chunks = state.get("chunks", [])
    if not isinstance(chunks, list):
        raise RuntimeError("'chunks' must be a list")

    summary_path = get_summary_store_path(chat_id)
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

    selected: List[Tuple[int, Dict[str, Any]]] = list(enumerate(chunks))
    if grep:
        needle = grep.lower()
        filtered: List[Tuple[int, Dict[str, Any]]] = []
        for idx, chunk in selected:
            payload = " ".join(
                [
                    str(chunk.get("summary", "")),
                    " ".join(clean_string_list(chunk.get("facts"))),
                    " ".join(clean_string_list(chunk.get("decisions"))),
                    " ".join(clean_string_list(chunk.get("open_items"))),
                ]
            ).lower()
            if needle in payload:
                filtered.append((idx, chunk))
        selected = filtered
        lines.append(f"Matches for '{grep}': {len(selected)}")

    to_show: List[Tuple[int, Dict[str, Any]]] = []
    if head > 0:
        to_show.extend(selected[:head])
    if tail > 0:
        tail_items = selected[-tail:]
        existing = {idx for idx, _ in to_show}
        to_show.extend([(idx, chunk) for idx, chunk in tail_items if idx not in existing])

    if not to_show:
        lines.append(
            "No chunks selected. Try /summary, /summary 5, /summary index 12, "
            "or add search text like /summary budget."
        )
        return "\n".join(lines)

    for idx, chunk in to_show:
        lines.append("")
        lines.append(_summary_chunk_to_text(idx, chunk))
    return "\n".join(lines)


def _message_id(msg: Dict[str, Any], fallback_index: int) -> str:
    value = msg.get("id")
    if value:
        return str(value)
    return f"legacy-{fallback_index}"


def _format_message_line(msg: Dict[str, Any]) -> str:
    sender = msg.get("sender", "Unknown")
    text = msg.get("text", "")
    return f"{sender}: {text}"


def _chunk_to_lines(chunk: List[Dict[str, Any]]) -> List[str]:
    return [_format_message_line(msg) for msg in chunk]


def _fallback_chunk_summary(chunk: List[Dict[str, Any]], start: int, end: int) -> Dict[str, Any]:
    lines = _chunk_to_lines(chunk)
    first = lines[0] if lines else ""
    last = lines[-1] if lines else ""
    return {
        "id": f"chunk-{start}-{end}",
        "source_message_ids": [
            _message_id(msg, fallback_index=start + idx) for idx, msg in enumerate(chunk)
        ],
        "summary": f"{first} ... {last}".strip(),
        "facts": [],
        "decisions": [],
        "open_items": [],
    }


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
    chunk: List[Dict[str, Any]],
    start: int,
    end: int,
    summarize_fn: Optional[Callable[[str], str]],
) -> Dict[str, Any]:
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

        combined_text = " ".join(
            [
                str(parsed.get("summary", "")),
                " ".join(clean_string_list(parsed.get("facts"))),
                " ".join(clean_string_list(parsed.get("decisions"))),
                " ".join(clean_string_list(parsed.get("open_items"))),
            ]
        )
        if not _contains_language_markers(combined_text, target_lang):
            stricter = (
                prompt
                + "\n\nIMPORTANT: Your previous answer used the wrong language. "
                + (
                    "Respond strictly in Russian."
                    if target_lang == "ru"
                    else "Respond strictly in English."
                )
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
            "facts": clean_string_list(parsed.get("facts")),
            "decisions": clean_string_list(parsed.get("decisions")),
            "open_items": clean_string_list(parsed.get("open_items")),
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            "Failed to parse chunk summary JSON: %s", exc, extra={"chat_id": chat_id}
        )
        return fallback
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Chunk summarization failed: %s", exc, extra={"chat_id": chat_id})
        return fallback


def maybe_rollup_summary(
    chat_id: str,
    messages: Optional[List[Dict[str, Any]]] = None,
    summarize_fn: Optional[Callable[[str], str]] = None,
    max_chunks: Optional[int] = None,
    force_rebuild: bool = False,
    parallel_workers: int = 1,
    on_chunk_done: Optional[Callable[[], None]] = None,
) -> int:
    settings = config.get_settings()
    if not settings.memory_summary_enabled:
        return 0

    source_messages = list(messages) if messages is not None else get_all_messages(chat_id)
    if force_rebuild:
        state: Dict[str, Any] = {"version": 1, "last_message_count": 0, "chunks": []}
        _summary_store_by_chat[chat_id] = state
    else:
        state = load_summary_state(chat_id)
    chunk_size = settings.memory_summary_chunk_size
    processed = int(state.get("last_message_count", 0) or 0)
    if processed > len(source_messages):
        processed = 0
        state = {"version": 1, "last_message_count": 0, "chunks": []}
        _summary_store_by_chat[chat_id] = state

    chunk_limit = settings.memory_summary_max_chunks_per_run if max_chunks is None else max_chunks
    if chunk_limit <= 0:
        chunk_limit = 1

    changed = False
    created = 0

    candidates: List[Tuple[List[Dict[str, Any]], int, int]] = []
    scan = processed
    while len(source_messages) - scan >= chunk_size and len(candidates) < chunk_limit:
        chunk = source_messages[scan : scan + chunk_size]
        start = scan
        end = scan + chunk_size - 1
        candidates.append((chunk, start, end))
        scan += chunk_size

    summaries: List[Dict[str, Any]] = []
    if candidates:
        max_workers = max(1, int(parallel_workers))
        if summarize_fn is None or max_workers == 1 or len(candidates) == 1:
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
            by_start: Dict[int, Dict[str, Any]] = {}
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
                for future in as_completed(future_map):
                    start = future_map[future]
                    by_start[start] = future.result()
                    if on_chunk_done is not None:
                        on_chunk_done()
            summaries = [by_start[start] for _, start, _ in candidates]

        for chunk_summary in summaries:
            chunks_raw = state.setdefault("chunks", [])
            if not isinstance(chunks_raw, list):
                chunks_raw = []
                state["chunks"] = chunks_raw
            chunks_raw.append(chunk_summary)
            processed += chunk_size
            state["last_message_count"] = processed
            changed = True
            created += 1

    if changed:
        save_summary_state(chat_id, state)
    return created


def build_summary_lines(
    chat_id: str,
    latest_user_text: str,
    token_limit: int,
    max_items: int,
    *,
    estimate_token_count_fn: Callable[[str], int],
) -> Tuple[List[str], int]:
    if token_limit <= 0 or max_items <= 0:
        return [], 0

    state = load_summary_state(chat_id)
    chunks = state.get("chunks", [])
    if not isinstance(chunks, list) or not chunks:
        return [], 0

    query_terms = {term for term in latest_user_text.lower().split() if term}
    scored: List[Tuple[int, str]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        summary = str(chunk.get("summary", "")).strip()
        if not summary:
            continue
        summary_terms = set(summary.lower().split())
        overlap = len(query_terms & summary_terms) if query_terms else 0
        facts = clean_string_list(chunk.get("facts"))
        decisions = clean_string_list(chunk.get("decisions"))
        open_items = clean_string_list(chunk.get("open_items"))
        score = overlap + (2 if decisions else 0) + (1 if facts else 0) + (1 if open_items else 0)
        details: List[str] = []
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

    lines: List[str] = []
    total_tokens = 0
    for summary in selected:
        line = f"- {summary}"
        tokens = estimate_token_count_fn(line)
        if total_tokens + tokens > token_limit:
            break
        lines.append(line)
        total_tokens += tokens

    return lines, total_tokens
