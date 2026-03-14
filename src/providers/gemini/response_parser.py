"""Helpers for parsing Gemini responses."""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from src import utils
from src.providers.contracts import CapabilityName, EventPayload
from src.providers.errors import ProviderResponseError

logger = logging.getLogger(__name__)


def extract_text_response(
    response: Any,
    *,
    capability: CapabilityName,
    model_name: str,
) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    logger.warning(
        "Gemini returned empty text response",
        extra={
            "model": model_name,
            "capability": capability,
            **_empty_response_details(response),
        },
    )
    raise ProviderResponseError(
        f"Gemini returned an empty response for capability '{capability}'",
        provider="gemini",
        capability=capability,
    )


def parse_reaction_response(
    response: Any,
    *,
    model_name: str,
    allowed_reactions: Sequence[str],
) -> str:
    text = extract_text_response(
        response,
        capability="reaction_selection",
        model_name=model_name,
    )
    if text in allowed_reactions:
        return text

    matching_reactions = [
        reaction for reaction in allowed_reactions if reaction in text
    ]
    if len(matching_reactions) == 1:
        return matching_reactions[0]

    logger.warning(
        "Gemini returned invalid reaction response",
        extra={
            "model": model_name,
            "response_text": text,
            "allowed_reactions": list(allowed_reactions),
        },
    )
    raise ProviderResponseError(
        "Gemini returned an invalid reaction selection",
        provider="gemini",
        capability="reaction_selection",
    )


def parse_event_payload(
    response: Any,
    *,
    model_name: str,
) -> EventPayload:
    text = extract_text_response(
        response,
        capability="event_parsing",
        model_name=model_name,
    )
    try:
        return json.loads(utils.strip_markdown_to_json(text))
    except json.JSONDecodeError as exc:
        logger.warning(
            "Gemini returned invalid event payload",
            extra={"model": model_name, "response_text": text},
        )
        raise ProviderResponseError(
            "Gemini returned invalid event payload",
            provider="gemini",
            capability="event_parsing",
        ) from exc


def _empty_response_details(response: Any) -> dict[str, Any]:
    candidates = getattr(response, "candidates", None) or []
    finish_reasons = []
    safety_ratings = []
    for candidate in candidates:
        finish_reasons.append(str(getattr(candidate, "finish_reason", "")))
        rating_items = []
        for rating in getattr(candidate, "safety_ratings", None) or []:
            rating_items.append(
                {
                    "category": str(getattr(rating, "category", "")),
                    "probability": str(getattr(rating, "probability", "")),
                    "blocked": str(getattr(rating, "blocked", "")),
                }
            )
        safety_ratings.append(rating_items)

    prompt_feedback = getattr(response, "prompt_feedback", None)
    block_reason = ""
    prompt_safety_ratings = []
    if prompt_feedback is not None:
        block_reason = str(getattr(prompt_feedback, "block_reason", ""))
        for rating in getattr(prompt_feedback, "safety_ratings", None) or []:
            prompt_safety_ratings.append(
                {
                    "category": str(getattr(rating, "category", "")),
                    "probability": str(getattr(rating, "probability", "")),
                    "blocked": str(getattr(rating, "blocked", "")),
                }
            )

    return {
        "candidate_count": len(candidates),
        "finish_reasons": finish_reasons,
        "prompt_block_reason": block_reason,
        "prompt_safety_ratings": prompt_safety_ratings,
        "candidate_safety_ratings": safety_ratings,
    }
