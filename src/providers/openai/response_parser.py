"""Helpers for parsing OpenAI Responses API outputs."""

from __future__ import annotations

import json
from typing import Any, Iterator

from src import utils
from src.providers.contracts import EventPayload


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text.strip()

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


def iter_stream_text_snapshots(stream: Any) -> Iterator[str]:
    accumulated = ""
    for event in stream:
        event_type = str(getattr(event, "type", ""))
        if event_type != "response.output_text.delta":
            continue
        delta = getattr(event, "delta", None)
        if not isinstance(delta, str) or not delta:
            continue
        accumulated += delta
        yield accumulated


def parse_event_payload(text: str) -> EventPayload:
    if not text:
        return {}
    return json.loads(utils.strip_markdown_to_json(text))
