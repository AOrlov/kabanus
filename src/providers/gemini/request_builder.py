"""Helpers for assembling Gemini requests."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from google.genai import types

from src.providers.contracts import ReactionSelectionRequest, build_reaction_prompt

REACTION_SYSTEM_INSTRUCTION = (
    "You are a Telegram reactions selector. "
    "Pick a single reaction emoji that fits the user message. "
    "Return only the emoji, nothing else."
)


def model_supports_system_instruction(model_name: str) -> bool:
    return "gemma" not in model_name.lower()


def model_supports_tools(model_name: str) -> bool:
    return "gemma" not in model_name.lower()


def model_supports_thinking_config(model_name: str) -> bool:
    return "gemma" not in model_name.lower()


def prepare_contents(
    model_name: str,
    contents: Any,
    system_instruction: str,
) -> tuple[Any, Optional[str]]:
    if not system_instruction:
        return contents, None
    if model_supports_system_instruction(model_name):
        return contents, system_instruction
    if isinstance(contents, str):
        return f"{system_instruction}\n\n{contents}", None
    if isinstance(contents, list) and contents:
        if isinstance(contents[0], str):
            return [f"{system_instruction}\n\n{contents[0]}"] + contents[1:], None
        return [system_instruction] + contents, None
    return contents, None


def build_generation_config(
    model_name: str,
    *,
    system_instruction: Optional[str],
    thinking_budget: int,
    use_google_search: bool = False,
) -> types.GenerateContentConfig:
    effective_budget = (
        thinking_budget if model_supports_thinking_config(model_name) else 0
    )
    thinking_config = None
    if effective_budget > 0:
        thinking_config = types.ThinkingConfig(thinking_budget=effective_budget)

    tools: Optional[list[Any]] = None
    if use_google_search and model_supports_tools(model_name):
        tools = [types.Tool(google_search=types.GoogleSearch())]

    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        thinking_config=thinking_config,
        tools=tools,
    )


def build_audio_transcription_contents(
    *, audio_bytes: bytes, language: str
) -> list[Any]:
    return [
        f"Transcribe this audio to {language} text.",
        types.Part.from_bytes(
            data=audio_bytes,
            mime_type="audio/ogg",
        ),
    ]


def build_text_contents(prompt: str) -> str:
    return prompt


def build_reaction_contents(request: ReactionSelectionRequest) -> str:
    return build_reaction_prompt(request)


def build_event_contents(
    *,
    image_bytes: bytes,
    current_year: Optional[int] = None,
) -> list[Any]:
    year = current_year or datetime.now().year
    return [
        (
            "Analyze this image and extract event information. "
            "Provide a JSON response with the following fields: "
            "title (string), date (YYYY-MM-DD), time (HH:MM), "
            "location (string), description (string), "
            "confidence (float between 0 and 1). "
            "If any field is unclear, set it to null. "
            f"If there is no year, set it to current year ({year})."
        ),
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
    ]


def build_ocr_contents(
    *,
    image_bytes: bytes,
    mime_type: str,
    language: str,
) -> list[Any]:
    return [
        (
            "Extract all visible text from the image and, if helpful, briefly "
            f"describe important visual content. Respond in {language}. "
            "Return plain text only without any markdown or JSON."
        ),
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
    ]
