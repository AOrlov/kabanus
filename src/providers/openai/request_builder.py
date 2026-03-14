"""Helpers for assembling OpenAI Responses API requests."""

from __future__ import annotations

import base64
from typing import Any, Dict, List

from src.providers.contracts import ReactionSelectionRequest, build_reaction_prompt

DEFAULT_ASSISTANT_INSTRUCTION = "You are a helpful assistant."


def build_input_items(
    *,
    user_content: Any,
    system_instruction: str = "",
) -> List[Dict[str, Any]]:
    input_items: List[Dict[str, Any]] = []
    if system_instruction:
        input_items.append(
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_instruction}],
            }
        )
    input_items.append({"role": "user", "content": user_content})
    return input_items


def build_text_user_content(prompt: str) -> List[Dict[str, str]]:
    return [{"type": "input_text", "text": prompt}]


def build_reaction_user_content(
    request: ReactionSelectionRequest,
) -> List[Dict[str, str]]:
    return [{"type": "input_text", "text": build_reaction_prompt(request)}]


def encode_image_bytes(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


def build_event_user_content(encoded_image: str) -> List[Dict[str, str]]:
    return [
        {
            "type": "input_text",
            "text": (
                "Extract event data from image and return JSON only with fields: "
                "title (string), date (YYYY-MM-DD), time (HH:MM or null), "
                "location (string or null), description (string or null), "
                "confidence (float 0..1). If unknown use null."
            ),
        },
        {
            "type": "input_image",
            "image_url": f"data:image/jpeg;base64,{encoded_image}",
        },
    ]


def build_ocr_user_content(
    *,
    encoded_image: str,
    mime_type: str,
    language: str,
) -> List[Dict[str, str]]:
    return [
        {
            "type": "input_text",
            "text": (
                f"Extract all visible text and describe key visual details in {language}. "
                "Return plain text only."
            ),
        },
        {
            "type": "input_image",
            "image_url": f"data:{mime_type};base64,{encoded_image}",
        },
    ]
