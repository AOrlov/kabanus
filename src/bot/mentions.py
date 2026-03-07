import re
from typing import Any, Iterable, Tuple


def _entity_type_value(entity: Any) -> str:
    entity_type = getattr(entity, "type", "")
    if hasattr(entity_type, "value"):
        return str(entity_type.value).lower()
    return str(entity_type).lower()


def _iter_message_entity_blocks(message: Any) -> Iterable[Tuple[str, Iterable[Any]]]:
    text = getattr(message, "text", "") or ""
    if text:
        yield text, getattr(message, "entities", []) or []
    caption = getattr(message, "caption", "") or ""
    if caption:
        yield caption, getattr(message, "caption_entities", []) or []


def _normalized_aliases(aliases: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for alias in aliases:
        value = str(alias or "").strip().lower().lstrip("@")
        if value:
            normalized.add(value)
    return normalized


def _contains_alias_token(text: str, aliases: Iterable[str]) -> bool:
    text_lower = str(text or "").lower()
    if not text_lower:
        return False
    for alias in _normalized_aliases(aliases):
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text_lower):
            return True
    return False


def is_bot_mentioned(  # pylint: disable=too-many-locals
    message: Any,
    *,
    bot_username: str,
    bot_id: int,
    aliases: list[str],
    fallback_text: str = "",
) -> bool:
    normalized_aliases = _normalized_aliases(aliases)
    normalized_username = str(bot_username or "").strip().lower().lstrip("@")
    if normalized_username:
        normalized_aliases.add(normalized_username)

    for source_text, entities in _iter_message_entity_blocks(message):
        for entity in entities:
            entity_type = _entity_type_value(entity)
            if entity_type == "mention":
                try:
                    offset = int(getattr(entity, "offset", 0))
                    length = int(getattr(entity, "length", 0))
                except (TypeError, ValueError):
                    continue
                if offset < 0 or length <= 0 or offset + length > len(source_text):
                    continue
                mention = (
                    source_text[offset : offset + length].strip().lower().lstrip("@")
                )
                if mention and mention in normalized_aliases:
                    return True
            elif entity_type == "text_mention":
                user = getattr(entity, "user", None)
                user_id = getattr(user, "id", None)
                if user_id == bot_id:
                    return True

    authored_text = "\n".join(
        [text for text, _ in _iter_message_entity_blocks(message)]
    )
    if _contains_alias_token(authored_text, normalized_aliases):
        return True
    if fallback_text and _contains_alias_token(fallback_text, normalized_aliases):
        return True
    return False


def should_respond_to_message(
    *,
    mentioned_bot: bool,
    replied_to_bot: bool,
    replied_to_other_user: bool,
) -> bool:
    if replied_to_other_user:
        return mentioned_bot
    return mentioned_bot or replied_to_bot
